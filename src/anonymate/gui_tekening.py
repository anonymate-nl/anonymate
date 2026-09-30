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
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath,
                           QPen)
from PySide6.QtWidgets import QSizePolicy, QWidget

from .generalize import TARGET_SHARE
from .stappen import (IDEAL_FROM_X, K_EDGES, TRADEOFF_DEFAULT, TRADEOFF_TEXTS,
                      houses_for,  # noqa: F401 (re-exported)
                      k_histogram, target_label, target_note, tradeoff_points, tradeoff_view)

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
IDEAL = QColor("#2E7D4F")           # the ideal corner of the utility view
SERIF = "Georgia"
MONO = "Consolas"

STYLE = f"""
QMainWindow, QWidget#page {{ background: {PAPER}; }}
QWidget {{ font-family: 'Segoe UI', sans-serif; font-size: 10pt; color: {INK}; }}
QWidget#rail {{ background: {INK}; }}
QLabel#brand {{ color: #FFFFFF; font-family: {SERIF}; font-size: 17pt; font-weight: 600; }}
QLabel#brandSub, QLabel#railNote {{ color: #A9B4C4; font-size: 9pt; }}
QWidget#practiceBanner {{ background: #E07A1F; border-radius: 8px; }}
QLabel#practiceTitle {{ color: #FFFFFF; font-weight: 700; letter-spacing: 1px; }}
QLabel#practiceText {{ color: #FFFFFF; font-size: 9pt; }}
QLabel#datasetCard {{ background: #1F2D42; color: #E8ECF2; border-radius: 8px; padding: 10px; }}
QListWidget#steps {{ background: transparent; border: none; color: #E8ECF2; font-size: 11pt;
    outline: 0; }}
QListWidget#steps::item {{ padding: 5px 6px; border-radius: 8px; }}
QListWidget#steps::item:selected {{ background: #2A3D59; color: #FFFFFF; }}
QListWidget#steps::item:hover {{ background: #22324A; }}
QLabel#eyebrow {{ color: #6B5B45; font-size: 9pt; letter-spacing: 1px; }}
QLabel#h1 {{ font-family: {SERIF}; font-size: 17pt; font-weight: 600; }}
QLabel#h2 {{ font-size: 11pt; font-weight: 600; }}
QLabel#lead, QLabel#note {{ color: #3E4A5C; }}
QLabel#big {{ font-family: {MONO}; font-size: 17pt; }}
QLabel#statLabel {{ color: {MUTED}; font-size: 9pt; }}
QFrame#card {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 10px; }}
QFrame#cardRisk {{ background: #FFFFFF; border: 2px solid #C8611F; border-radius: 10px; }}
QFrame#voortgang {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 8px; }}
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


class BitsBar(QWidget):
    """Guess Who: bits needed to single out one dwelling, bits each attribute gives away, and
    what remains (median over the records), with the norm's log2(k) as a line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._needed, self._parts, self._remaining, self._norm = 0.0, [], None, 0.0
        self.setMinimumHeight(92)

    def set(self, needed: float, parts: list[tuple[str, float]], remaining: float | None,
            norm_bits: float) -> None:
        """``remaining`` None: not known (no record has a match), so no "to go" part is drawn."""
        self._needed, self._parts = needed, parts
        self._remaining, self._norm = remaining, norm_bits
        nl = lambda b: f"{b:.1f}".replace(".", ",")  # noqa: E731
        self.setToolTip("\n".join([f"{name}: {nl(bits)} bits" for name, bits in parts]
                                   + [f"nog te gaan: {nl(remaining)} bits" if remaining is not None
                                      else "nog te gaan: onbekend (geen enkel record heeft een match)",
                                      f"norm: minstens {nl(norm_bits)} te gaan"]))
        self.update()

    def paintEvent(self, _event) -> None:
        if self._needed <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width() - 8
        remaining = self._remaining or 0.0
        total = max(self._needed, sum(b for _, b in self._parts) + remaining)
        scale = w / total
        shades = [NAVY, BLUE, "#5E8FBF", "#93B4D6", "#B7CDE3", "#CFDDEC"]
        x, y, h = 4.0, 8.0, 24.0
        small = QFont("Segoe UI")
        small.setPointSizeF(8.5)
        p.setFont(small)
        fm = QFontMetricsF(small)
        # labels in two rows under the bar; one that would overlap is left out (tooltip has all)
        row_end = [-1e9, -1e9]
        skipped = 0
        for i, (name, bits) in enumerate(self._parts):
            width = bits * scale
            p.fillRect(QRectF(x, y, width, h), QColor(shades[i % len(shades)]))
            text = f"{name} {bits:.1f}".replace(".", ",")
            tw = fm.horizontalAdvance(text)
            lx = min(x, w + 4 - tw)
            row = next((r for r in (0, 1) if lx >= row_end[r] + 6), None)
            if row is None:
                skipped += 1
            else:
                p.setPen(QColor(INK))
                p.drawText(QRectF(lx, y + h + 2 + 15 * row, tw + 2, 16), Qt.AlignLeft, text)
                row_end[row] = lx + tw
            x += width
        if self._remaining is not None:
            rest = QRectF(x, y, remaining * scale, h)
            p.fillRect(rest, QColor("#EFEBE2"))
            p.setPen(QColor("#C9C2B4"))
            p.drawRect(rest)
            p.setPen(QColor(INK))
            text = f"nog te gaan: {remaining:.1f}".replace(".", ",")
            if fm.horizontalAdvance(text) + 10 > rest.width():
                text = f"{remaining:.1f}".replace(".", ",")
            if fm.horizontalAdvance(text) + 8 <= rest.width():
                p.drawText(rest.adjusted(6, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
        nx = 4 + (total - self._norm) * scale
        p.setPen(QPen(QColor(ORANGE_DARK), 2))
        p.drawLine(QPointF(nx, 2), QPointF(nx, y + h + 6))
        norm = f"norm: minstens {self._norm:.1f} te gaan".replace(".", ",")
        if skipped:
            norm += " · wijs aan voor alles"
        tw = fm.horizontalAdvance(norm)
        p.drawText(QRectF(max(4.0, min(nx + 4, w + 4 - tw)), y + h + 34, tw + 2, 16),
                   Qt.AlignLeft, norm)


def _short(n: float) -> str:
    return f"{n / 1000:g}k" if n >= 1000 else f"{n:g}"


class KHistogram(QWidget):
    """How many records have how many look-alikes, in classes, with the norm as a line."""

    EDGES = K_EDGES

    def __init__(self, parent=None):
        super().__init__(parent)
        self._counts, self._norm = [], 11
        self.setMinimumSize(210, 130)

    def set(self, ks, norm_k: int) -> None:
        self._norm = norm_k
        bins = k_histogram(ks, norm_k)
        self._edges = [(a, b) for a, b, _ in bins]
        self._counts = [c for _, _, c in bins]
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
            if QFontMetricsF(font).horizontalAdvance(label) > bw - 2 and 0 < i and b != math.inf:
                label = f"≥{_short(a)}"             # too narrow for a range: its lower bound
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(5 + i * bw, base + 4, bw, 16), Qt.AlignCenter, label)
        pen = QPen(QColor(ORANGE_DARK), 1.5)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(5 + bw, top - 12), QPointF(5 + bw, base))
        p.drawText(QRectF(5 + bw + 4, 0, 80, 14), Qt.AlignLeft, f"k = {self._norm}")


class TradeoffChart(QWidget):
    """Generalisation steps in two views (stappen.TRADEOFF_VIEWS), the selected step marked:
    "nut", after El Emam & Arbuckle (2013): data utility against the share of dwellings that meet
    the norm; "verlies": information loss against the publishable share."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[str, float, float]] = []
        self._target = 100 * TARGET_SHARE
        self._view = TRADEOFF_DEFAULT
        self._selected = -1
        self.setMinimumSize(420, 300)
        self._tip = ("Informatieverlies: gemiddeld over woningen en kenmerken. 0% = alle waarden "
                     "exact, 100% = alle kenmerken weggelaten. Een klasse van 10 jaar bij "
                     "bouwjaren van 1900 tot 2020 kost bijvoorbeeld zo'n 8%.")
        self.setToolTip(self._tip + "\n\n" + target_note())

    def set(self, rows: list[tuple[str, float, float]], target_pct: float = 100 * TARGET_SHARE,
            selected: int | None = None) -> None:
        self._rows, self._target = rows, target_pct
        self._selected = len(rows) - 1 if selected is None else selected
        self.setToolTip(self._tip + "\n\n" + target_note(target_pct / 100))
        self.update()

    def set_view(self, view: str) -> None:
        self._view = tradeoff_view(view)
        self.update()

    def select(self, index: int) -> None:
        self._selected = index
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._rows:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        nut = self._view == "nut"
        texts = TRADEOFF_TEXTS[self._view]
        left, right, top, bottom = 58, w - 16, 18, h - 34
        raw = tradeoff_points(self._rows, self._view)
        if nut:                        # the utility axis is fixed: 0% (no use) to 100% (all use)
            top_x, tick = 100, 25
        else:                          # the loss axis: to a round number just above the largest loss
            hi = max(x for x, _ in raw)
            tick = next(t for t in (1, 2, 5, 10, 20, 25) if hi / t <= 5)
            top_x = max(tick, math.ceil(hi / tick) * tick)
        span = right - left - 40

        def px(x: float) -> float:
            return left + x / top_x * span

        def py(y: float) -> float:
            return bottom - y / 100 * (bottom - top)

        ty = py(self._target)
        font = QFont("Segoe UI")
        font.setPointSizeF(8.5)
        p.setFont(font)
        fm = QFontMetricsF(font)
        # the axis and its texts (under and left of the plot) are obstacles for the labels too
        placed: list[QRectF] = [QRectF(0, bottom + 2, w, h), QRectF(0, 0, left, h)]
        if nut:                        # the ideal corner: much utility, much protection
            ideal = QRectF(px(IDEAL_FROM_X), top, px(100) - px(IDEAL_FROM_X), max(ty - top, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(IDEAL.red(), IDEAL.green(), IDEAL.blue(), 28))
            p.drawRect(ideal)
            p.setBrush(QBrush(IDEAL, Qt.BDiagPattern))
            p.drawRect(ideal)
            iw = fm.horizontalAdvance(texts["ideal"]) + 2
            rect = QRectF(px(100) - iw, top - 16, iw, 14)
            p.setPen(IDEAL)
            p.drawText(rect, Qt.AlignRight, texts["ideal"])
            placed.append(rect)
        p.setPen(QPen(QColor("#8C8577"), 1))
        p.drawLine(QPointF(left, bottom), QPointF(right, bottom))
        p.drawLine(QPointF(left, top), QPointF(left, bottom))
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(0, top - 6, left - 6, 14), Qt.AlignRight, texts["y_max"])
        p.drawText(QRectF(0, bottom - 8, left - 6, 14), Qt.AlignRight, texts["y_min"])
        p.save()
        p.translate(12, (top + bottom) / 2)
        p.rotate(-90)
        p.drawText(QRectF(-(bottom - top) / 2 - 20, -8, bottom - top + 40, 16), Qt.AlignCenter,
                   texts["y_title"])
        p.restore()
        for v in range(0, top_x + 1, tick):
            x = px(v)
            p.drawLine(QPointF(x, bottom), QPointF(x, bottom + 4))
            if nut and v == 0:
                label = texts["x_min"]
            elif nut and v == 100:
                label = texts["x_max"]
            else:
                label = f"{v}%"
            if v or nut:
                p.drawText(QRectF(x - 40, bottom + 5, 80, 14), Qt.AlignCenter, label)
        p.drawText(QRectF(right - 300, bottom + 18, 300, 16), Qt.AlignRight, texts["x_title"])
        if texts["source"]:
            p.drawText(QRectF(left, bottom + 18, 200, 16), Qt.AlignLeft, texts["source"])
        target = QPen(QColor(ORANGE_DARK), 1.2)
        target.setStyle(Qt.DashLine)
        p.setPen(target)
        p.drawLine(QPointF(left, ty), QPointF(right, ty))
        pts = [QPointF(px(x), py(y)) for x, y in raw]
        p.setPen(QPen(QColor(BLUE), 2.2))
        for a, b in zip(pts, pts[1:]):
            p.drawLine(a, b)
        chosen = self._selected
        # the points themselves are obstacles too: a label never covers a marker
        placed += [QRectF(q.x() - 8, q.y() - 8, 16, 16) for q in pts]
        # what the orange dashed line is: the goal of the search (left end, above the line)
        goal = target_label(self._target / 100)
        gw = fm.horizontalAdvance(goal) + 2
        goal_rect = QRectF(left + 6, ty - 15, gw, 14)
        p.setPen(QColor(ORANGE_DARK))
        p.drawText(goal_rect, Qt.AlignLeft, goal)
        placed.append(goal_rect)

        def place(i: int) -> None:
            label, pct, _ = self._rows[i]
            q = pts[i]
            text = f"{label} · {pct:.0f}%"
            tw = fm.horizontalAdvance(text) + 2
            for rect in (QRectF(q.x() + 10, q.y() - 8, tw, 16),      # right of the point
                         QRectF(q.x() - 10 - tw, q.y() - 8, tw, 16),  # left of it
                         QRectF(q.x() - tw / 2, q.y() + 8, tw, 16),   # under it
                         QRectF(q.x() - tw / 2, q.y() - 24, tw, 16)):  # above it
                if rect.left() >= 2 and rect.right() <= w - 2 and rect.bottom() <= h \
                        and not any(rect.intersects(o) for o in placed):
                    placed.append(rect)
                    p.setPen(QColor(INK))
                    p.drawText(rect, Qt.AlignLeft, text)
                    return
        for i, q in enumerate(pts):
            last = i == chosen
            p.setBrush(QColor(ORANGE if last else BLUE))
            p.setPen(QPen(QColor(ORANGE_DARK if last else BLUE), 1.5))
            r = 7 if last else 5
            p.drawEllipse(q, r, r)
        # the chosen step first, then the others where there is room (the list shows all)
        if 0 <= chosen < len(pts):
            place(chosen)
        for i in range(len(pts)):
            if i != chosen:
                place(i)
