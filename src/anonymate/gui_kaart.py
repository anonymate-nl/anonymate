"""Weather location step of the desktop window: nearest KNMI station, or an H3 cell with noise.

A dataset that carries an address, BAG-ID or GPS location can get a weather location instead:
the nearest KNMI station (an area around one of ~34 stations), or the H3 cell of the location
after Gaussian noise (sigma per axis, drawn once per dwelling), whose centre is the point for
weather interpolation. Optionally the urban heat island (UHI) per postcode, in classes.

The map is drawn from the population itself, offline: every H3 cell of level 6 that holds
dwellings is a grey hexagon, so the country's shape needs no base map and no network. On it:
the station areas (cells coloured by their nearest station), or the cells of the chosen level
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

N_MC = 400
STATION_COLOURS = ["#8DB3D9", "#B9A6D3", "#9CCFB6", "#E6C08A", "#D9A3A3", "#A6C8C8",
                   "#C7C98C", "#B7B7D9", "#D6B79C", "#9FBF9F", "#C9A9C9", "#A9BCD0"]


def available(population) -> bool:
    return all(c in population.columns for c in ("lat", "lon", "h3_r6"))


class MapData:
    """Counts per H3 cell and station areas, read once from the population."""

    def __init__(self, population, stations: pd.DataFrame | None = None):
        self.population = population
        con, rel = population.con, population.relation
        base = con.execute(f"""SELECT h3_r6, count(*) AS n,
            {"mode(knmi_station)" if "knmi_station" in population.columns else "NULL"} AS st
            FROM {rel} WHERE h3_r6 IS NOT NULL GROUP BY 1""").df()
        import h3
        self.base = [(c, int(n), s, [(lat, lng) for lat, lng in h3.cell_to_boundary(c)])
                     for c, n, s in base.itertuples(index=False)]
        lats = [p[0] for _, _, _, b in self.base for p in b]
        lngs = [p[1] for _, _, _, b in self.base for p in b]
        self.bbox = (min(lngs), min(lats), max(lngs), max(lats)) if lats else (3.2, 50.7, 7.3, 53.6)
        names = sorted({s for *_, s, _ in self.base if s})
        self.station_colour = {s: STATION_COLOURS[i % len(STATION_COLOURS)]
                               for i, s in enumerate(names)}
        self.stations = stations
        self._counts: dict[int, dict[str, int]] = {}

    def station_at(self, lat: float, lng: float) -> tuple[str | None, int]:
        """The station of the area under a point, and how many dwellings that area holds."""
        import h3
        cell = h3.latlng_to_cell(lat, lng, 6)
        station = next((st for c, _, st, _ in self.base if c == cell), None)
        if station is None:
            return None, 0
        if not hasattr(self, "_per_station"):
            self._per_station: dict[str, int] = {}
            for _, n, st, _ in self.base:
                if st:
                    self._per_station[st] = self._per_station.get(st, 0) + n
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
        """Dwellings in the cell, with its ring-1 neighbours, and the effective number of
        candidates for an attacker who knows sigma (dwellings at their level-8 cell centres)."""
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
        # where could the published cell have come from: every level-8 cell within reach
        reach = list(h3.grid_disk(cell, 1 + math.ceil(2.5 * sigma / (
            math.sqrt(3) * h3.average_hexagon_edge_length(level, unit="km")))))
        rows = self.population.con.execute(
            f"SELECT h3_r8, count(*) FROM {self.population.relation} "
            f"WHERE list_contains(?, h3_r{level}) AND h3_r8 IS NOT NULL GROUP BY 1",
            [reach]).fetchall()
        if not rows:
            return out
        rng = np.random.default_rng(0)
        weights, n = [], []
        for f, cnt in rows:
            la, lo = h3.cell_to_latlng(f)
            dy = rng.normal(0, sigma, N_MC) / 111.0
            dx = rng.normal(0, sigma, N_MC) / (111.0 * math.cos(math.radians(la)))
            hits = sum(1 for a, b in zip(dy, dx) if h3.latlng_to_cell(la + a, lo + b, level) == cell)
            if hits:
                weights.append(hits / N_MC)
                n.append(cnt)
        if weights:
            w, n = np.array(weights), np.array(n, float)
            total = float((n * w).sum())
            entropy = math.log2(total) - float((n * w * np.log2(w)).sum()) / total
            out["k_eff"] = 2 ** entropy
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
        self._zoom, self._pan = 1.0, QPointF(0, 0)
        self._drag: QPointF | None = None
        self._moved = False
        self.setMinimumSize(420, 460)
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
        p.setPen(Qt.NoPen)
        for cell, n, st, boundary in self.data.base:
            if self.mode == "knmi" and st:
                p.setBrush(QColor(self.data.station_colour.get(st, "#D9D3C7")))
            else:
                p.setBrush(QColor("#D9D3C7"))
            p.drawPolygon(self._poly(boundary))
        if self.mode == "knmi" and self.data.stations is not None:
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
                p.setPen(QPen(QColor(ORANGE_DARK), 1))
                p.setBrush(QColor(232, 146, 63, 70))
                for cell in ring:
                    p.drawPolygon(self._poly(h3.cell_to_boundary(cell)))
            p.setPen(QPen(QColor(NAVY), 1.2))
            p.setBrush(QColor(45, 106, 159, 150))
            for cell in self.dataset_cells:
                p.drawPolygon(self._poly(h3.cell_to_boundary(cell)))
            if self.selected:
                p.setPen(QPen(QColor(ORANGE_DARK), 2.4))
                p.setBrush(QColor(232, 146, 63, 120))
                p.drawPolygon(self._poly(h3.cell_to_boundary(self.selected)))
                if self.sigma > 0:
                    la, lo = h3.cell_to_latlng(self.selected)
                    centre = self._to_screen(la, lo)
                    edge = self._to_screen(la + self.sigma / 111.0, lo)
                    r = abs(centre.y() - edge.y())
                    for mult, alpha in ((1, 220), (2, 150)):
                        pen = QPen(QColor(154, 74, 18, alpha), 1.4)
                        pen.setStyle(Qt.DashLine)
                        p.setPen(pen)
                        p.setBrush(Qt.NoBrush)
                        p.drawEllipse(centre, r * mult, r * mult)
        self._legend(p)

    def _legend(self, p: QPainter) -> None:
        f = QFont("Segoe UI")
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(MUTED))
        if self.mode == "knmi":
            text = "Gekleurd: het gebied rond elk KNMI-station (dichtstbijzijnd station)."
        elif self.mode == "h3":
            text = (f"Blauw: cellen van niveau {self.level} met woningen uit de dataset. "
                    "Klik een cel: oranje met buren; stippellijnen 1σ en 2σ ruis.")
        else:
            text = "Geen weerlocatie."
        p.drawText(QRectF(10, self.height() - 22, self.width() - 20, 18), Qt.AlignLeft, text)
