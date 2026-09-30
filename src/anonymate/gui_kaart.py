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

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

# The map's data and arithmetic are in :mod:`anonymate.kaart` (no Qt); re-exported here so that
# existing imports keep working.
from .gui_tekening import INK, MUTED, NAVY, ORANGE_DARK
from .kaart import (HEAT_SHARE, LAND, N_MC, NL_BOX, STATION_COLOURS, WATER, MapData,  # noqa: F401
                    ScopedMapData, _clip, _cross, available, noisy_cells, voronoi)  # noqa: F401


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
    def _frame(self, size=None):
        x0, y0, x1, y1 = self.data.bbox
        kx = math.cos(math.radians((y0 + y1) / 2))
        width, height = (size.width(), size.height()) if size is not None else \
            (self.width(), self.height())
        w, h = width - 20, height - 20
        scale = min(w / ((x1 - x0) * kx), h / (y1 - y0)) * self._zoom
        return x0, y1, kx, scale

    def _to_screen(self, lat: float, lng: float) -> QPointF:
        x0, y1, kx, s = self._frame()
        return QPointF(10 + (lng - x0) * kx * s + self._pan.x(), 10 + (y1 - lat) * s + self._pan.y())

    def _to_geo(self, p: QPointF, size=None) -> tuple[float, float]:
        x0, y1, kx, s = self._frame(size)
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

    def resizeEvent(self, e) -> None:
        # keep the same place in the middle when the map gets bigger or smaller (the text
        # under it grows after a click): otherwise the clicked cell slides out of view
        old = e.oldSize()
        centre = None
        if self.data is not None and old.width() > 0 and old.height() > 0 and self._zoom > 1:
            centre = self._to_geo(QPointF(old.width() / 2, old.height() / 2), old)
        super().resizeEvent(e)
        if centre is not None:
            self._pan += QPointF(self.width() / 2, self.height() / 2) - self._to_screen(*centre)

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
        # water everywhere (foreign land is left out), the Dutch land on top: coast, IJsselmeer
        # and Wadden stay recognisable; then cells with dwellings, then municipal borders
        land = QPainterPath()
        land.setFillRule(Qt.OddEvenFill)
        if self.data.land:
            p.fillRect(self.rect(), QColor(WATER))
            for rings in self.data.land:
                for ring in rings:
                    land.addPolygon(QPolygonF([self._to_screen(la, lo) for lo, la in ring]))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(LAND))
            p.drawPath(land)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#E4DFD5"))
        for cell, n, st, boundary in self.data.base:
            p.drawPolygon(self._poly(boundary))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(150, 140, 125, 150), 0.7))
        for ring in self.data.borders:
            p.drawPolyline(QPolygonF([self._to_screen(la, lo) for lo, la in ring]))
        if self.mode == "knmi":
            # the station areas only on Dutch land: the coast stays readable
            p.save()
            if not land.isEmpty():
                p.setClipPath(land)
            for i, (name, poly) in enumerate(self.data.voronoi.items()):
                colour = QColor(STATION_COLOURS[i % len(STATION_COLOURS)])
                colour.setAlpha(120)
                p.setBrush(colour)
                p.setPen(QPen(QColor(60, 60, 60, 180), 1.0))
                p.drawPolygon(self._poly(poly))
            p.restore()
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
            # a legend of what is actually on the map right now
            parts = []
            if self.selected:
                parts.append("dikke rand: de aangeklikte cel · dunne randen: haar zes buurcellen"
                             + (" · oranje: waar de woning met 95% kans ligt" if self.heat
                                else ""))
            else:
                parts.append(f"klik een cel van niveau {self.level} voor de uitleg")
            if self.dataset_cells:
                parts.append("blauw: cellen die woningen uit je dataset als weerzone kregen")
            parts.append("dubbelklik: heel Nederland")
            text = " · ".join(parts)
            text = text[0].upper() + text[1:] + "."
        else:
            text = "Geen weerlocatie."
        # wrapped over at most two lines, on a pale band so it stays readable over the map
        box = QRectF(10, self.height() - 38, self.width() - 20, 34)
        used = p.boundingRect(box, Qt.AlignLeft | Qt.AlignBottom | Qt.TextWordWrap, text)
        band = QRectF(0, used.top() - 3, self.width(), self.height() - used.top() + 3)
        p.fillRect(band, QColor(255, 255, 255, 190))
        p.drawText(box, Qt.AlignLeft | Qt.AlignBottom | Qt.TextWordWrap, text)
