"""Weather location step of the desktop window: nearest KNMI station, or an H3 cell with noise.

A dataset that carries an address, BAG-ID or GPS location can get a weather location instead:
the nearest KNMI station (an area around one of ~34 stations), or the H3 cell of the location
after Gaussian noise (sigma per axis, drawn once per dwelling), whose centre is the point for
weather interpolation. Optionally the urban heat island (UHI) per postcode, in classes.

The map is drawn offline, from data already on this computer: the land as the H3 cells of
level 6 that hold dwellings, municipal borders (simplified, from the areas ingest), and the
largest municipalities by name. Map tiles from a web service would tell that service which area
the user looks at, so there are none. On it: the station areas as a Voronoi diagram (every point
coloured by its nearest station, transparent), or the cells of the chosen level
with the dataset's dwellings, and for a clicked cell its neighbours and circles of one and two
sigma. Clicking a cell shows how many dwellings it holds, how many with its neighbours, and the
effective number of candidates for an attacker who knows sigma (2^entropy of where the noise
could have come from; see docs/herleidbaarheid-uitleg.md, section 5).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from .gui_tekening import INK, MUTED, NAVY, ORANGE_DARK

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
                 borders: list | None = None, whole_country: bool = True):
        self.population = population
        self.borders = borders or []
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
        self.cities = []
        if "gemeente" in population.columns and "lat" in population.columns:
            self.cities = con.execute(
                f"SELECT gemeente, avg(lat), avg(lon), count(*) AS n FROM {rel} "
                "WHERE gemeente IS NOT NULL AND lat IS NOT NULL GROUP BY 1 ORDER BY n DESC "
                "LIMIT 22").fetchall()
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


class MapWidget(QWidget):
    """The Netherlands as H3 cells; click a cell to select it. Wheel zooms, dragging pans."""

    cellClicked = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: MapData | None = None
        self.mode = "h3"               # "h3", "knmi" or "none"
        self.level, self.sigma = 5, 10.0
        self.dataset_cells: dict[str, int] = {}
        self.selected: str | None = None
        self.heat: dict[str, float] = {}
        self._zoom, self._pan = 1.0, QPointF(0, 0)
        self._drag: QPointF | None = None
        self._moved = False
        self.setMinimumSize(360, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(False)

    # --- projection ----------------------------------------------------------------------------
    def _frame(self):
        x0, y0, x1, y1 = self.data.bbox
        kx = math.cos(math.radians((y0 + y1) / 2))
        w, h = self.width() - 20, self.height() - 20
        scale = min(w / ((x1 - x0) * kx), h / (y1 - y0)) * self._zoom
        return x0, y1, kx, scale

    def _to_screen(self, lat: float, lng: float) -> QPointF:
        x0, y1, kx, s = self._frame()
        return QPointF(10 + (lng - x0) * kx * s + self._pan.x(), 10 + (y1 - lat) * s + self._pan.y())

    def _to_geo(self, p: QPointF) -> tuple[float, float]:
        x0, y1, kx, s = self._frame()
        lng = x0 + (p.x() - 10 - self._pan.x()) / (kx * s)
        lat = y1 - (p.y() - 10 - self._pan.y()) / s
        return lat, lng

    def _poly(self, boundary) -> QPolygonF:
        return QPolygonF([self._to_screen(a, b) for a, b in boundary])

    # --- interaction ---------------------------------------------------------------------------
    def wheelEvent(self, e) -> None:
        if self.data is None:
            return
        factor = 1.25 if e.angleDelta().y() > 0 else 0.8
        pos = e.position()
        before = self._to_geo(pos)
        self._zoom = min(max(self._zoom * factor, 1.0), 40.0)
        after = self._to_screen(*before)
        self._pan += pos - after
        self.update()

    def focus(self, lat: float, lng: float, km: float) -> None:
        """Zoom so that a square of ``km`` around (lat, lng) fills the map."""
        if self.data is None:
            return
        self._zoom, self._pan = 1.0, QPointF(0, 0)
        _, _, _, scale = self._frame()
        self._zoom = min(max(min(self.width(), self.height()) / (km / 111.0 * scale), 1.0), 40.0)
        self._pan = QPointF(0, 0)
        here = self._to_screen(lat, lng)
        self._pan = QPointF(self.width() / 2, self.height() / 2) - here
        self.update()

    def mouseDoubleClickEvent(self, e) -> None:
        self._zoom, self._pan = 1.0, QPointF(0, 0)       # back to the whole country
        self.update()

    def mousePressEvent(self, e) -> None:
        self._drag, self._moved = e.position(), False

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None:
            d = e.position() - self._drag
            if abs(d.x()) + abs(d.y()) > 3:
                self._moved = True
                self._pan += d
                self._drag = e.position()
                self.update()

    def mouseReleaseEvent(self, e) -> None:
        if self._drag is not None and not self._moved and self.data is not None:
            lat, lng = self._to_geo(e.position())
            self.cellClicked.emit(lat, lng)
        self._drag = None

    # --- painting ------------------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#E8EEF3"))
        if self.data is None:
            p.setPen(QColor(MUTED))
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap,
                       "Geen kaart: de populatie heeft geen coördinaten\n"
                       "(bouw de populatie op, of kies geen synthetische populatie)")
            return
        import h3
        # the land: cells with dwellings, then municipal borders
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#E4DFD5"))
        for cell, n, st, boundary in self.data.base:
            p.drawPolygon(self._poly(boundary))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(150, 140, 125, 150), 0.7))
        for ring in self.data.borders:
            p.drawPolyline(QPolygonF([self._to_screen(la, lo) for lo, la in ring]))
        if self.mode == "knmi":
            for i, (name, poly) in enumerate(self.data.voronoi.items()):
                colour = QColor(STATION_COLOURS[i % len(STATION_COLOURS)])
                colour.setAlpha(95)
                p.setBrush(colour)
                p.setPen(QPen(QColor(60, 60, 60, 180), 1.0))
                p.drawPolygon(self._poly(poly))
            if self.data.stations is not None:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(INK))
                for la, lo in zip(self.data.stations["lat"], self.data.stations["lon"]):
                    p.drawEllipse(self._to_screen(float(la), float(lo)), 3.5, 3.5)
        if self.mode == "h3":
            counts = self.data.counts(self.level)
            if self.level <= 6:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, 170), 0.8))
                for cell in counts:
                    p.drawPolygon(self._poly(h3.cell_to_boundary(cell)))
            if self.selected:
                ring = h3.grid_disk(self.selected, 1)
                p.setPen(QPen(QColor(154, 74, 18, 140), 0.8))
                p.setBrush(Qt.NoBrush)
                for cell in ring:
                    p.drawPolygon(self._poly(h3.cell_to_boundary(cell)))
            p.setPen(QPen(QColor(NAVY), 1.2))
            p.setBrush(QColor(45, 106, 159, 105))
            for cell in self.dataset_cells:
                p.drawPolygon(self._poly(h3.cell_to_boundary(cell)))
            if self.selected:
                p.setPen(QPen(QColor(ORANGE_DARK), 2.4))
                p.setBrush(Qt.NoBrush)
                p.drawPolygon(self._poly(h3.cell_to_boundary(self.selected)))
                # where the dwelling truly lies, given this cell and sigma: darker = likelier
                p.setPen(Qt.NoPen)
                for c, share in self.heat.items():
                    p.setBrush(QColor(200, 80, 20, int(60 + 180 * share)))
                    p.drawPolygon(self._poly(h3.cell_to_boundary(c)))
                p.setPen(QPen(QColor(ORANGE_DARK), 2.4))
                p.setBrush(Qt.NoBrush)
                p.drawPolygon(self._poly(h3.cell_to_boundary(self.selected)))
        self._cities(p)
        self._legend(p)

    def _cities(self, p: QPainter) -> None:
        """Names of the largest municipalities, on a light halo so they stay readable."""
        f = QFont("Segoe UI")
        f.setPointSizeF(8.0)
        f.setBold(True)
        p.setFont(f)
        placed: list[QRectF] = []
        metrics = p.fontMetrics()
        for name, la, lo, _n in self.data.cities:          # largest first
            pt = self._to_screen(float(la), float(lo))
            w = metrics.horizontalAdvance(name) + 6
            rect = QRectF(pt.x() - w / 2, pt.y() - 8, w, 16)
            if any(rect.intersects(r) for r in placed):      # a larger city is already there
                continue
            placed.append(rect)
            p.setPen(QColor(255, 255, 255, 220))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                p.drawText(rect.translated(dx, dy), Qt.AlignCenter, name)
            p.setPen(QColor(INK))
            p.drawText(rect, Qt.AlignCenter, name)

    def _legend(self, p: QPainter) -> None:
        f = QFont("Segoe UI")
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(MUTED))
        if self.mode == "knmi":
            text = "Voronoi: elk gekleurd vlak ligt dichter bij zijn KNMI-station (stip) dan bij elk ander."
        elif self.mode == "h3":
            text = (f"Blauw: cellen van niveau {self.level} met woningen uit de dataset. Klik "
                    "een cel: oranje = waar de woning werkelijk kan liggen (95% van de kans). "
                    "Dubbelklik: heel Nederland.")
        else:
            text = "Geen weerlocatie."
        p.drawText(QRectF(10, self.height() - 22, self.width() - 20, 18), Qt.AlignLeft, text)
