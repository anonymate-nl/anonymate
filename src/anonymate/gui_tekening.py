"""Look and painted pieces of the desktop window: theme, houses, bits bar, k histogram, trade-off.

The look ("kaarttafel") follows the NeedForHeat AnonyMate presentation for KITE: a navy step
rail on a paper-coloured table, houses as the unit of everything, one warm accent (orange
roofs) for the dwelling at stake. Within the norm is blue, too identifiable is orange: they also
differ in lightness, so they stay apart for colour-blind readers and in greyscale print.

The house pictures are an icon array: k dwellings drawn as k houses, the standard way to make a
frequency ("1 in 11") readable (Galesic, Garcia-Retamero & Gigerenzer, 2009). The bits bar is
the "Guess Who?" view of explain.py: how many yes/no questions each published attribute answers,
and how many are still to go against the norm's log2(k).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

INK = "#172233"
NAVY = "#1F3A5F"
BLUE = "#2D6A9F"
BLUE_LIGHT = "#DCE5EF"
PAPER = "#F4F1EA"
LINE = "#D9D3C7"
MUTED = "#4A5568"
ORANGE = "#E8923F"
ORANGE_DARK = "#9A4A12"
ORANGE_LIGHT = "#FBEBDD"
SERIF = "Georgia"
MONO = "Consolas"

STYLE = f"""
QMainWindow, QWidget#page {{ background: {PAPER}; }}
QWidget {{ font-family: 'Segoe UI', sans-serif; font-size: 10pt; color: {INK}; }}
QWidget#rail {{ background: {INK}; }}
QLabel#brand {{ color: #FFFFFF; font-family: {SERIF}; font-size: 17pt; font-weight: 600; }}
QLabel#brandSub, QLabel#railNote {{ color: #A9B4C4; font-size: 9pt; }}
QLabel#datasetCard {{ background: #1F2D42; color: #E8ECF2; border-radius: 8px; padding: 10px; }}
QListWidget#steps {{ background: transparent; border: none; color: #E8ECF2; font-size: 11pt;
    outline: 0; }}
QListWidget#steps::item {{ padding: 8px 6px; border-radius: 8px; }}
QListWidget#steps::item:selected {{ background: #2A3D59; color: #FFFFFF; }}
QListWidget#steps::item:hover {{ background: #22324A; }}
QLabel#eyebrow {{ color: #6B5B45; font-size: 9pt; letter-spacing: 1px; }}
QLabel#h1 {{ font-family: {SERIF}; font-size: 20pt; font-weight: 600; }}
QLabel#h2 {{ font-size: 11pt; font-weight: 600; }}
QLabel#lead, QLabel#note {{ color: #3E4A5C; }}
QLabel#big {{ font-family: {MONO}; font-size: 20pt; }}
QLabel#statLabel {{ color: {MUTED}; font-size: 9pt; }}
QFrame#card {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 10px; }}
QFrame#cardRisk {{ background: #FFFFFF; border: 2px solid #C8611F; border-radius: 10px; }}
QFrame#soft {{ background: {PAPER}; border-radius: 8px; }}
QPushButton {{ background: #FFFFFF; color: {NAVY}; border: 1px solid {NAVY}; border-radius: 8px;
    padding: 8px 16px; font-weight: 600; }}
QPushButton:hover {{ background: #EEF3F8; }}
QPushButton:disabled {{ color: #9AA6B6; border-color: #C3CBD6; background: #F7F8FA; }}
QPushButton#primary {{ background: {NAVY}; color: #FFFFFF; border: none; }}
QPushButton#primary:hover {{ background: #16304F; }}
QPushButton#primary:disabled {{ background: #9AA6B6; color: #F2F4F7; }}
QLineEdit, QComboBox, QDoubleSpinBox, QPlainTextEdit {{ background: #FFFFFF;
    border: 1px solid #C9C2B4; border-radius: 6px; padding: 4px 8px; }}
QTableWidget {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 8px;
    gridline-color: #ECE7DD; selection-background-color: #DCE5EF; selection-color: {INK}; }}
QHeaderView::section {{ background: #EFEBE2; color: {MUTED}; border: none; padding: 6px;
    font-weight: 600; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 8px 14px; color: {MUTED}; font-weight: 600; }}
QTabBar::tab:selected {{ color: {INK}; border-bottom: 2px solid {ORANGE}; }}
QSlider::groove:horizontal {{ height: 6px; background: #D9D3C7; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {NAVY}; width: 18px; margin: -7px 0; border-radius: 9px; }}
QSlider::sub-page:horizontal {{ background: {BLUE}; border-radius: 3px; }}
"""


def _house(size: float) -> QPainterPath:
    s = size
    p = QPainterPath()
    p.moveTo(0.12 * s, 0.46 * s)
    p.lineTo(0.5 * s, 0.14 * s)
    p.lineTo(0.88 * s, 0.46 * s)
    p.lineTo(0.88 * s, 0.86 * s)
    p.lineTo(0.12 * s, 0.86 * s)
    p.closeSubpath()
    return p


class HouseArray(QWidget):
    """``total`` places for houses: ``filled`` of them drawn, the first as the dwelling at stake;
    the rest dashed (places still missing to reach the norm). ``more`` adds a "+n" label."""

    def __init__(self, size: int = 30, parent=None):
        super().__init__(parent)
        self._size = size
        self._filled, self._total, self._more = 0, 0, 0
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def set(self, filled: int, total: int, more: int = 0) -> None:
        self._filled, self._total, self._more = max(filled, 0), max(total, filled), max(more, 0)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        n = self._total + (2 if self._more else 0)
        return QSize(max(n, 1) * (self._size + 6), self._size + 4)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        step = self._size + 6
        shape = _house(self._size)
        for i in range(self._total):
            p.save()
            p.translate(i * step, 2)
            if i < self._filled:
                target = i == 0
                p.setBrush(QColor(ORANGE if target else BLUE_LIGHT))
                p.setPen(QPen(QColor(ORANGE_DARK if target else NAVY), 1.4))
            else:
                p.setBrush(Qt.NoBrush)
                pen = QPen(QColor("#B9B1A2"), 1.2)
                pen.setStyle(Qt.DashLine)
                p.setPen(pen)
            p.drawPath(shape)
            p.restore()
        if self._more:
            p.setPen(QColor(MUTED))
            f = QFont(MONO)
            f.setPointSizeF(10)
            p.setFont(f)
            p.drawText(QRectF(self._total * step, 0, 2 * step, self._size + 4),
                       Qt.AlignVCenter | Qt.AlignLeft, f"+{self._more:,}".replace(",", "."))


def houses_for(k: float, norm_k: int, cap: int = 20) -> tuple[int, int, int]:
    """(filled, total, more) for a HouseArray showing k dwellings against the norm."""
    k = 0 if k is None or (isinstance(k, float) and math.isnan(k)) else int(k)
    total = max(norm_k, min(k, cap))
    filled = min(k, total)
    return filled, total, max(k - total, 0)


class BitsBar(QWidget):
    """Guess Who: bits needed to single out one dwelling, bits each attribute gives away, and
    what remains (median over the records), with the norm's log2(k) as a line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._needed, self._parts, self._remaining, self._norm = 0.0, [], 0.0, 0.0
        self.setMinimumHeight(74)

    def set(self, needed: float, parts: list[tuple[str, float]], remaining: float,
            norm_bits: float) -> None:
        self._needed, self._parts = needed, parts
        self._remaining, self._norm = remaining, norm_bits
        self.update()

    def paintEvent(self, _event) -> None:
        if self._needed <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width() - 8
        total = max(self._needed, sum(b for _, b in self._parts) + self._remaining)
        scale = w / total
        shades = [NAVY, BLUE, "#5E8FBF", "#93B4D6", "#B7CDE3", "#CFDDEC"]
        x, y, h = 4.0, 8.0, 24.0
        small = QFont("Segoe UI")
        small.setPointSizeF(8.5)
        p.setFont(small)
        for i, (name, bits) in enumerate(self._parts):
            width = bits * scale
            p.fillRect(QRectF(x, y, width, h), QColor(shades[i % len(shades)]))
            p.setPen(QColor(INK))
            p.drawText(QRectF(x, y + h + 2, max(width, 1), 16), Qt.AlignLeft | Qt.TextDontClip,
                       f"{name} {bits:.1f}".replace(".", ","))
            x += width
        rest = QRectF(x, y, self._remaining * scale, h)
        p.fillRect(rest, QColor("#EFEBE2"))
        p.setPen(QColor("#C9C2B4"))
        p.drawRect(rest)
        p.setPen(QColor(INK))
        p.drawText(rest.adjusted(6, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft | Qt.TextDontClip,
                   f"nog te gaan: {self._remaining:.1f}".replace(".", ","))
        nx = 4 + (total - self._norm) * scale
        p.setPen(QPen(QColor(ORANGE_DARK), 2))
        p.drawLine(QPointF(nx, 2), QPointF(nx, y + h + 6))
        p.drawText(QRectF(nx + 4, y + h + 20, 260, 16), Qt.AlignLeft,
                   f"norm: minstens {self._norm:.1f} te gaan".replace(".", ","))


def _short(n: float) -> str:
    return f"{n / 1000:g}k" if n >= 1000 else f"{n:g}"


class KHistogram(QWidget):
    """How many records have how many look-alikes, in classes, with the norm as a line."""

    EDGES = [(0, 10), (11, 30), (31, 100), (101, 300), (301, 1000), (1001, math.inf)]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._counts, self._norm = [], 11
        self.setMinimumSize(260, 150)

    def set(self, ks, norm_k: int) -> None:
        ks = [0 if k is None or (isinstance(k, float) and math.isnan(k)) else k for k in ks]
        self._norm = norm_k
        edges = [(0, norm_k - 1)] + [(max(a, norm_k), b) for a, b in self.EDGES[1:]
                                     if b >= norm_k]
        self._edges = edges
        self._counts = [sum(1 for k in ks if a <= k <= b) for a, b in edges]
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._counts:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self._counts)
        w, h = self.width(), self.height()
        bw = (w - 10) / n
        top, base = 18, h - 22
        peak = max(max(self._counts), 1)
        font = QFont("Segoe UI")
        font.setPointSizeF(8)
        p.setFont(font)
        for i, (c, (a, b)) in enumerate(zip(self._counts, self._edges)):
            bh = (base - top) * c / peak
            rect = QRectF(5 + i * bw + 4, base - bh, bw - 8, bh)
            p.fillRect(rect, QColor("#C8611F" if i == 0 else BLUE))
            p.setPen(QColor(INK))
            p.drawText(QRectF(rect.x(), rect.y() - 16, rect.width(), 14), Qt.AlignCenter, str(c))
            label = f"<{self._norm}" if i == 0 else (f">{_short(a - 1)}" if b == math.inf
                                                        else f"{_short(a)}–{_short(b)}")
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(5 + i * bw, base + 4, bw, 16), Qt.AlignCenter, label)
        pen = QPen(QColor(ORANGE_DARK), 1.5)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(5 + bw, top - 12), QPointF(5 + bw, base))
        p.drawText(QRectF(5 + bw + 4, 0, 80, 14), Qt.AlignLeft, f"k = {self._norm}")


class TradeoffChart(QWidget):
    """Generalisation steps: share publishable against information loss, last step marked."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[str, float, float]] = []
        self._target = 95.0
        self.setMinimumSize(420, 260)

    def set(self, rows: list[tuple[str, float, float]], target_pct: float = 95.0) -> None:
        self._rows, self._target = rows, target_pct
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._rows:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        left, right, top, bottom = 48, w - 16, 16, h - 30
        losses = [r[2] for r in self._rows]
        lo, hi = min(losses), max(losses)
        span = (hi - lo) or 1.0

        def pt(pct: float, loss: float) -> QPointF:
            return QPointF(left + (loss - lo) / span * (right - left - 180),
                           bottom - pct / 100 * (bottom - top))

        p.setPen(QPen(QColor("#8C8577"), 1))
        p.drawLine(QPointF(left, bottom), QPointF(right, bottom))
        p.drawLine(QPointF(left, top), QPointF(left, bottom))
        font = QFont("Segoe UI")
        font.setPointSizeF(8.5)
        p.setFont(font)
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(0, top - 6, left - 6, 14), Qt.AlignRight, "100%")
        p.drawText(QRectF(0, bottom - 8, left - 6, 14), Qt.AlignRight, "0%")
        p.drawText(QRectF(left, bottom + 8, 300, 16), Qt.AlignLeft, "informatieverlies →")
        target = QPen(QColor(ORANGE_DARK), 1.2)
        target.setStyle(Qt.DashLine)
        p.setPen(target)
        ty = bottom - self._target / 100 * (bottom - top)
        p.drawLine(QPointF(left, ty), QPointF(right, ty))
        pts = [pt(r[1], r[2]) for r in self._rows]
        p.setPen(QPen(QColor(BLUE), 2.2))
        for a, b in zip(pts, pts[1:]):
            p.drawLine(a, b)
        for i, ((label, pct, _), q) in enumerate(zip(self._rows, pts)):
            last = i == len(pts) - 1
            p.setBrush(QColor(ORANGE if last else BLUE))
            p.setPen(QPen(QColor(ORANGE_DARK if last else BLUE), 1.5))
            r = 7 if last else 5
            p.drawEllipse(q, r, r)
            p.setPen(QColor(INK))
            p.drawText(QRectF(q.x() + 10, q.y() - 8, 260, 16), Qt.AlignLeft | Qt.TextDontClip,
                       f"{label} · {pct:.0f}%")
