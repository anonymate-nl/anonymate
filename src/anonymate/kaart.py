"""The map's data and arithmetic, without Qt: what the desktop window and the browser both use.

Counts per H3 cell, the station areas (Voronoi), the statistics of a cell for an attacker who
knows sigma (2^entropy of where the noise could have come from; see
docs/herleidbaarheid-uitleg.md, section 5), the noise itself, the share of a cell that is Dutch
land, and the reading of the map layers (land, municipal borders, largest municipalities).
Drawing is in :mod:`anonymate.gui_kaart` (Qt) or in the page (canvas).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .population import Population
from .tabel import lees_parquet

WATER, LAND = "#CFDDEA", "#F4F1EA"      # background (water, and all land abroad) and Dutch land

N_MC = 200
HEAT_SHARE = 0.95        # the heat map shows the smallest area holding this much probability
STATION_COLOURS = ["#8DB3D9", "#B9A6D3", "#9CCFB6", "#E6C08A", "#D9A3A3", "#A6C8C8",
                   "#C7C98C", "#B7B7D9", "#D6B79C", "#9FBF9F", "#C9A9C9", "#A9BCD0"]


NL_BOX = (3.3, 50.72, 7.25, 53.58)     # lon/lat box of the Netherlands

def available(population) -> bool:
    return all(c in population.columns for c in ("lat", "lon", "h3_r6"))


class MapData:
    """Counts per H3 cell and station areas, read once from the population."""

    def __init__(self, population, stations: pd.DataFrame | None = None,
                 borders: list | None = None, whole_country: bool = True,
                 land: list | None = None):
        self.population = population
        self.borders = borders or []
        # the Dutch land without water: polygons of rings (lon, lat), outer ring first
        self.land = land or []
        con, rel = population.con, population.relation
        base = con.execute(f"""SELECT h3_r6, count(*) AS n,
            {"mode(knmi_station)" if "knmi_station" in population.columns else "NULL"} AS st
            FROM {rel} WHERE h3_r6 IS NOT NULL GROUP BY 1""").df()
        import h3
        # a population without stations per dwelling (the practice one) gives NA here
        self.base = [(c, int(n), s if isinstance(s, str) and s else None,
                      [(lat, lng) for lat, lng in h3.cell_to_boundary(c)])
                     for c, n, s in base.itertuples(index=False)]
        lats = [p[0] for _, _, _, b in self.base for p in b]
        lngs = [p[1] for _, _, _, b in self.base for p in b]
        # the whole country, unless a region was chosen: then that region
        if lats and not whole_country:
            self.bbox = (min(lngs), min(lats), max(lngs), max(lats))
        else:
            self.bbox = NL_BOX if not lats else (
                min(NL_BOX[0], min(lngs)), min(NL_BOX[1], min(lats)),
                max(NL_BOX[2], max(lngs)), max(NL_BOX[3], max(lats)))
        names = sorted({s for *_, s, _ in self.base if s})
        self.station_colour = {s: STATION_COLOURS[i % len(STATION_COLOURS)]
                               for i, s in enumerate(names)}
        self.stations = stations
        self._counts: dict[int, dict[str, int]] = {}
        self.cities = largest_municipalities(population)
        # station areas always for the whole country, so zooming out never shows an edge
        x0, y0, x1, y1 = self.bbox
        whole = (min(x0, NL_BOX[0]), min(y0, NL_BOX[1]), max(x1, NL_BOX[2]), max(y1, NL_BOX[3]))
        self.voronoi = voronoi(stations, whole) if stations is not None else {}

    def station_at(self, lat: float, lng: float) -> tuple[str | None, int]:
        """The nearest station to a point, and how many dwellings have it as nearest."""
        if self.stations is None or not len(self.stations):
            return None, 0
        st = self.stations
        d = np.hypot((st["lat"].astype(float) - lat) * 111.0,
                     (st["lon"].astype(float) - lng) * 68.0)
        station = str(st["knmi_station"].iloc[int(np.argmin(d.to_numpy()))])
        if not hasattr(self, "_per_station"):
            self._per_station = {}
            if "knmi_station" in self.population.columns:
                self._per_station = {str(k): int(n) for k, n in self.population.con.execute(
                    f"SELECT knmi_station, count(*) FROM {self.population.relation} "
                    "GROUP BY 1").fetchall()}
        return station, self._per_station.get(station, 0)

    def station_name(self, station: str) -> str:
        if self.stations is not None and "naam" in self.stations.columns:
            hit = self.stations[self.stations["knmi_station"].astype(str) == str(station)]
            if len(hit):
                return f"{hit['naam'].iloc[0]} ({station})"
        return str(station)

    def land_share(self, cell: str) -> float | None:
        """Share of the cell that is Dutch land (from the land-water boundary), or None when the
        map has no land: the centres of its children three levels finer, tested one by one."""
        if not self.land:
            return None
        import h3
        if getattr(self, "_land_rings", None) is None:
            self._land_rings = prepare_rings(self.land)
        children = h3.cell_to_children(cell, min(h3.get_resolution(cell) + 3, 15))
        centres = np.array([h3.cell_to_latlng(c) for c in children], float).reshape(-1, 2)
        inside = inside_rings(self._land_rings, centres[:, 1], centres[:, 0])
        return int(inside.sum()) / max(len(children), 1)

    def counts(self, level: int) -> dict[str, int]:
        """Dwellings per cell of ``level`` (4 to 8)."""
        if level not in self._counts:
            col = f"h3_r{level}"
            if col in self.population.columns:
                df = self.population.con.execute(
                    f"SELECT {col}, count(*) FROM {self.population.relation} "
                    f"WHERE {col} IS NOT NULL GROUP BY 1").fetchall()
                self._counts[level] = {c: int(n) for c, n in df}
            else:
                self._counts[level] = {}
        return self._counts[level]

    def cell_stats(self, cell: str, sigma: float) -> dict:
        """Dwellings in the cell, with its ring-1 neighbours; for an attacker who knows sigma,
        the effective number of candidates and a heat map of where the dwelling truly lies.

        Dwellings are bundled per cell two levels finer (at their centre: small against sigma).
        Each such cell weighs its dwellings times the chance that noise carries them into the
        clicked cell; the heat map is the smallest set of those cells holding HEAT_SHARE of it."""
        import h3
        level = h3.get_resolution(cell)
        counts = self.counts(level)
        ring = list(h3.grid_disk(cell, 1))
        own = counts.get(cell, 0)
        with_ring = sum(counts.get(c, 0) for c in ring)
        out = {"cel": cell, "niveau": level, "woningen": own, "met_buren": with_ring,
               "k_eff": float(own), "gebied_km2": h3.cell_area(cell, unit="km^2")}
        if sigma <= 0 or "h3_r8" not in self.population.columns:
            return out
        # where could the published cell have come from: every finer cell within reach
        fine = min(level + 2, 8)
        if f"h3_r{fine}" not in self.population.columns:
            fine = 8
        reach = list(h3.grid_disk(cell, 1 + math.ceil(2.5 * sigma / (
            math.sqrt(3) * h3.average_hexagon_edge_length(level, unit="km")))))
        rows = self.population.con.execute(
            f"SELECT h3_r{fine}, count(*) FROM {self.population.relation} "
            f"WHERE list_contains(?, h3_r{level}) AND h3_r{fine} IS NOT NULL GROUP BY 1",
            [reach]).fetchall()
        if not rows:
            return out
        rng = np.random.default_rng(0)
        dy0 = rng.normal(0, sigma, N_MC) / 111.0
        dx0 = rng.normal(0, sigma, N_MC)
        weights, n, where = [], [], []
        for f, cnt in rows:
            la, lo = h3.cell_to_latlng(f)
            dx = dx0 / (111.0 * math.cos(math.radians(la)))
            hits = sum(1 for a, b in zip(dy0, dx) if h3.latlng_to_cell(la + a, lo + b, level) == cell)
            if hits:
                weights.append(hits / N_MC)
                n.append(cnt)
                where.append(f)
        if weights:
            w, n = np.array(weights), np.array(n, float)
            total = float((n * w).sum())
            entropy = math.log2(total) - float((n * w * np.log2(w)).sum()) / total
            out["k_eff"] = 2 ** entropy
            mass = n * w / total
            order = np.argsort(-mass)
            keep = order[:int(np.searchsorted(np.cumsum(mass[order]), HEAT_SHARE)) + 1]
            top = float(mass[keep].max())
            out["heat"] = {where[i]: float(mass[i] / top) for i in keep}
            out["heat_woningen"] = int(n[keep].sum())
            out["heat_km2"] = len(keep) * h3.average_hexagon_area(fine, unit="km^2")
        return out


def _clip(poly: list, a: np.ndarray, b: np.ndarray) -> list:
    """Sutherland-Hodgman: the part of ``poly`` (x, y km) closer to ``a`` than to ``b``."""
    m, n = (a + b) / 2, b - a
    inside = lambda p: (p[0] - m[0]) * n[0] + (p[1] - m[1]) * n[1] <= 0  # noqa: E731
    out = []
    for i, cur in enumerate(poly):
        prev = poly[i - 1]
        if inside(cur):
            if not inside(prev):
                out.append(_cross(prev, cur, m, n))
            out.append(cur)
        elif inside(prev):
            out.append(_cross(prev, cur, m, n))
    return out


def _cross(p, q, m, n):
    dp = (p[0] - m[0]) * n[0] + (p[1] - m[1]) * n[1]
    dq = (q[0] - m[0]) * n[0] + (q[1] - m[1]) * n[1]
    t = dp / (dp - dq)
    return (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))


def voronoi(stations: pd.DataFrame, bbox, margin_km: float = 60.0) -> dict[str, list]:
    """Per station its Voronoi polygon (lat, lon) within the map's box: every point in it is
    closer to that station than to any other. Plain half-plane clipping, no extra library."""
    kx, ky = 111.32 * math.cos(math.radians(52.2)), 110.57
    xy = np.column_stack([stations["lon"].astype(float) * kx, stations["lat"].astype(float) * ky])
    x0, y0, x1, y1 = bbox[0] * kx - margin_km, bbox[1] * ky - margin_km, \
        bbox[2] * kx + margin_km, bbox[3] * ky + margin_km
    out = {}
    for i, name in enumerate(stations["knmi_station"].astype(str)):
        poly = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        for j in range(len(xy)):
            if j != i and poly:
                poly = _clip(poly, xy[i], xy[j])
        out[name] = [(y / ky, x / kx) for x, y in poly]
    return out


def noisy_cells(lat, lon, level: int, sigma: float, seed: int) -> list[str | None]:
    """H3 cell of each location after Gaussian noise of ``sigma`` km per axis."""
    import h3
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    rng = np.random.default_rng(seed)
    dy = rng.normal(0, sigma, len(lat)) / 111.0 if sigma else np.zeros(len(lat))
    dx = (rng.normal(0, sigma, len(lat)) / (111.0 * np.cos(np.radians(np.nan_to_num(lat, nan=52))))
          if sigma else np.zeros(len(lat)))
    return [h3.latlng_to_cell(a + y, b + x, level) if not (math.isnan(a) or math.isnan(b))
            else None for a, b, y, x in zip(lat, lon, dy, dx)]



def largest_municipalities(population, n: int = 22) -> list[tuple]:
    """The ``n`` municipalities with most dwellings, largest first, as (name, lat, lon, count)
    with the mean position of their dwellings as the centre: the labels of the map."""
    if "gemeente" not in population.columns or "lat" not in population.columns:
        return []
    return population.con.execute(
        f"SELECT gemeente, avg(lat), avg(lon), count(*) AS n FROM {population.relation} "
        "WHERE gemeente IS NOT NULL AND lat IS NOT NULL GROUP BY 1 ORDER BY n DESC "
        f"LIMIT {int(n)}").fetchall()


class ScopedMapData(MapData):
    """MapData restricted to the population's scope (the region chosen in step 1)."""

    def __init__(self, population, stations, borders=None, land=None):
        params: list = []
        where = population.where(params)
        rel = population.relation
        if where.strip() != "TRUE":
            # the region as a small table: only the columns the map needs
            keep = [c for c in ("lat", "lon", "knmi_station", "gemeente", "h3_r4", "h3_r5",
                                "h3_r6", "h3_r7", "h3_r8") if c in population.columns]
            rel = f"_kaart_{id(self)}"
            population.con.execute(f"CREATE OR REPLACE TEMP TABLE {rel} AS SELECT "
                                   f"{', '.join(keep)} FROM {population.relation} "
                                   f"WHERE {where}", params)
        super().__init__(Population(population.con, rel, population.snapshot), stations,
                         borders, whole_country=where.strip() == "TRUE", land=land)


# --- the map layers ----------------------------------------------------------------------------
def map_layer(name: str, local: Path | str | None = None) -> list:
    """Polygons of a map layer (lists of rings of (lon, lat)): from ``local / name`` when the
    caller has such a directory with the file in it (the local store's 'anonymate ingest
    gebieden', newest), else the copy that ships with anonymate (so the practice mode has a
    recognisable map without downloads). A layer is a nicety: any problem gives []."""
    try:
        path = Path(local) / name if local is not None else None
        if path is None or not path.exists():
            path = Path(__file__).with_name("data") / "kaart" / name
        return [json.loads(r) for r in lees_parquet(path, ["ringen"])["ringen"]]
    except Exception:  # noqa: BLE001 (a map layer is a nicety)
        return []


def land_layer(local: Path | str | None = None) -> list:
    """The Dutch land without water: polygons of rings (lon, lat), outer ring first."""
    return map_layer("nederland_land.parquet", local)


def border_rings(local: Path | str | None = None) -> list:
    """The municipal borders (simplified) as a flat list of rings of (lon, lat)."""
    return [ring for rings in map_layer("gemeentegrenzen.parquet", local) for ring in rings]


# --- even-odd point in polygon ------------------------------------------------------------------
def prepare_rings(land: list) -> list[tuple]:
    """The rings of ``land`` (polygons of rings (lon, lat)) as numpy arrays with their box:
    (x0, y0, x1, y1 of the edges, (xmin, ymin, xmax, ymax))."""
    out = []
    for rings in land:
        for ring in rings:
            a = np.asarray(ring, float).reshape(-1, 2)
            if len(a) < 3:
                continue
            b = np.roll(a, -1, axis=0)
            out.append((a[:, 0], a[:, 1], b[:, 0], b[:, 1],
                        (a[:, 0].min(), a[:, 1].min(), a[:, 0].max(), a[:, 1].max())))
    return out


def inside_rings(rings: list[tuple], lon, lat) -> np.ndarray:
    """Which points lie on land: the even-odd rule over all rings together (a point inside an
    odd number of rings is inside; a hole is a ring inside another), as Qt's OddEvenFill."""
    px, py = np.asarray(lon, float), np.asarray(lat, float)
    odd = np.zeros(len(px), bool)
    if not len(px):
        return odd
    lo_x, hi_x, lo_y, hi_y = px.min(), px.max(), py.min(), py.max()
    for x0, y0, x1, y1, (bx0, by0, bx1, by1) in rings:
        if bx1 < lo_x or bx0 > hi_x or by1 < lo_y or by0 > hi_y:
            continue
        crosses = (y0[None, :] > py[:, None]) != (y1[None, :] > py[:, None])
        dy = np.where(y1 == y0, 1.0, y1 - y0)
        x_at = x0[None, :] + (py[:, None] - y0[None, :]) * ((x1 - x0) / dy)[None, :]
        odd ^= (np.count_nonzero(crosses & (px[:, None] < x_at), axis=1) % 2).astype(bool)
    return odd
