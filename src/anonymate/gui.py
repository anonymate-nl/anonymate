"""Desktop window for people who do not use a terminal.

A plain local Qt application: no web server, no network port. It drives the same library
functions as the CLI, in the same order, one page per step in a rail on the left:

1. open a dataset;
2. fix the norm (p, and so k) before any outcome is visible;
3. check the proposed role of every column;
4. optionally add an address-based heat performance signature;
5. choose the attacker and the population, and assess;
6. read the outcome (per record, and in bits), weigh generalisations; save.

The look and the painted pieces (houses, bits bar, k histogram, trade-off chart) are in
:mod:`anonymate.gui_tekening`.
"""
from __future__ import annotations

import math
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QEventLoop, QObject, QSettings, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPalette
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QRadioButton, QScrollArea,
                               QSizePolicy, QSlider, QSpinBox,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from . import __version__, opbouw
from .cli import SCENARIOS, qids_from, read_dataset
from .detect import Role, derive_h3_columns, detect
from .generalize import LOSS_NOTE, TARGET_SHARE, suggest
from .gui_kaart import MapWidget, ScopedMapData, available
from .gui_tekening import (STYLE, BitsBar, HouseArray, KHistogram, TradeoffChart, houses_for)
from .kaart import border_rings, land_layer, map_layer
from .opbouw import Bron
from .population import Population
from .lezing import Lezing, gevoeligheid, onderzoek
from .qids import CATALOGUE, Kind
from .report import write
from .risk import P_DEFAULT, P_MAX, P_MIN, Status, Threshold, assess
from .stappen import COLUMN_TIPS, DEELNAME
from .stappen import (TRADEOFF_TEXTS, TRADEOFF_VIEWS, tradeoff_view, DASH, GPS_LAT, GPS_LON, STATUS_TEXT, UHI, UNKNOWN_TIP, WEATHER_H3,  # noqa: F401
                      WEATHER_STATION, add_uhi, add_weather, apply_trace, bits_note, cell_html,
                      cell_text, g3, guess_gps, histogram_note, html, is_unknown, k_line,
                      link_columns, link_kwargs, locations, merge_scope, nl, nr, stat_tiles,
                      numeric_column, numeric_columns, population_with_uhi, read_uhi, read_uhi_frame,
                      uhi_from_population, uhi_table, UHI_FROM_POPULATION,
                      readable_error, record_card, region_scope, region_text,
                      representativeness_lines, signature_available, station_text, table_cell,
                      target_count_text, target_note, verken_kop, verken_rooster,
                     weather_band,
                      weather_zones)
from .voortgang import Schatter, Voortgang, klaar_rond, vooraf_schatting

ROLE_LABELS = {
    Role.DIRECT: "direct identificerend: weglaten",
    Role.QID: "quasi-identifier",
    Role.IMPLICIT_LOCATION: "verborgen locatie",
    Role.DERIVED: "afgeleid (lekt hetzelfde)",
    Role.MEASUREMENT: "meetwaarde",
}
NO_QID = "(geen)"
DIRECT = "(weglaten)"
STATUS_COLOURS = {Status.OK: "#FFFFFF", Status.AT_RISK: "#FBEBDD", Status.NO_MATCH: "#F3EBD2"}
# the norm's reference points, shown under the slider (El Emam & Arbuckle 2013; grid operators)
NORM_MARKS = [(0.05, "streng: openbare publicatie van gevoelige gegevens"),
              (0.09, "standaard van AnonyMate"),
              (0.10, "netbeheerders, verbruik per PC6"),
              (0.20, "medisch, gecontroleerde toegang"),
              (0.33, "ondergrens, gecontroleerde toegang")]
LOCK_TEXT = "Norm vastleggen en verder"
LOCKED_TEXT = "Norm vastgelegd · verder"
STEPS = ["Dataset", "Norm", "Kolommen", "Signatuur", "Weerlocatie", "Aanvaller", "Uitkomst"]
PROVINCES = ["Drenthe", "Flevoland", "Fryslân", "Gelderland", "Groningen", "Limburg",
             "Noord-Brabant", "Noord-Holland", "Overijssel", "Utrecht", "Zeeland", "Zuid-Holland"]


_g = g3


_nl = nl


class Worker(QObject):
    """Runs one long computation off the UI thread."""

    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object, str)      # fraction 0..1, or None when unknown

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            # a computation that takes one argument gets a way to report its progress
            takes = self.fn.__code__.co_argcount if hasattr(self.fn, "__code__") else 0
            self.done.emit(self.fn(self.progress.emit) if takes == 1 else self.fn())
        except Exception as e:  # noqa: BLE001 (shown to the user)
            self.failed.emit(f"{type(e).__name__}: {e}")


class _EnkeleRegel(QLabel):
    """A label that stays on one line, whatever its text: too long, it ends in an ellipsis (the whole
    text is in the tooltip) and it never asks for more width. ``text()`` still gives all of it."""

    def __init__(self, text: str = "", name: str = ""):
        super().__init__(text)
        if name:
            self.setObjectName(name)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.WindowText))
        shown = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.width())
        painter.drawText(self.rect(), int(Qt.AlignLeft | Qt.AlignVCenter), shown)


class VoortgangBalk(QFrame):
    """The one progress indicator of the window, the same box as in the browser version: a lightly
    framed box of fixed width (that of its container, never that of its text) with two lines: the
    text of what is happening on top (one line), under it the bar with the time left in a slot of
    fixed width on the right ("nog ongeveer m:ss" and the like, monospaced digits).

    Fed with ``report(fraction, text)`` (fraction None: unknown, the bar then just runs); the time left
    comes from ``voortgang.Schatter``, the same text the browser version shows. Used for every
    long operation; ``pump`` lets one that runs on the window's own thread keep the bar moving.
    ``vertical`` is kept for the callers; the box looks the same everywhere."""

    def __init__(self, thick: int = 8, vertical: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("voortgang")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(5)
        self.label = _EnkeleRegel("", "note")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(thick)
        self.time = QLabel("")
        self.time.setObjectName("note")
        font = self.time.font()
        font.setFamily("Consolas")                    # digits of equal width: the text does not jitter
        self.time.setFont(font)
        self.time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.time.setFixedWidth(self.time.fontMetrics().horizontalAdvance("n" * 19))
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.bar, 1)
        row.addWidget(self.time)
        lay.addWidget(self.label)
        lay.addLayout(row)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._t0 = 0.0
        self._fraction = None
        self._text = "aan het rekenen"
        self._schatter = Schatter()
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._show)
        self.hide()

    def start(self, text: str = "aan het rekenen…") -> None:
        import time
        self._t0 = time.monotonic()
        self._fraction, self._text = None, text
        self._schatter = Schatter()
        self.bar.setRange(0, 0)                    # running, no fraction known yet
        self._show()
        self.show()
        self._tick.start(1000)

    def report(self, fraction=None, text: str | None = None) -> None:
        if not self.isVisible() and not self._tick.isActive():
            return
        if text:
            self._text = text
        if fraction is not None:
            self._fraction = max(self._fraction or 0.0, float(fraction))    # never back
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(1000 * self._fraction))
        self._show()

    def _show(self) -> None:
        import time
        elapsed = time.monotonic() - self._t0
        left = self._schatter.text(self._fraction, elapsed)
        self.label.setText(self._text or "aan het rekenen")
        self.time.setText(left)

    def stop(self) -> None:
        self._tick.stop()
        self.hide()

    def pump(self, fraction=None, text: str | None = None) -> None:
        """``report`` for work on the window's thread: also lets the window repaint."""
        self.report(fraction, text)
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)


# symbol (rich text), unit and meaning of each published signature output
SIGNATURE_OUTPUTS = {
    "H": ("H", "W/K", "warmteverlies per graad verschil tussen binnen en buiten"),
    "C": ("C", "Wh/K", "warmtecapaciteit: hoeveel warmte de woning vasthoudt"),
    "tau": ("τ", "h", "tijdconstante C/H: hoe snel de woning afkoelt"),
    "Asol": ("A<sub>sol</sub>", "m²", "effectief zonoppervlak: hoeveel zonnewarmte binnenkomt"),
    "Ainf": ("A<sub>inf</sub>", "cm²",
             "infiltratie-apertuur: hoeveel lucht door kieren naar binnen lekt"),
}


def _header(column: str) -> str:
    """Table header for an exploration column (see :func:`anonymate.stappen.verken_kop`)."""
    return verken_kop(column)


def _label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def _card(name: str = "card") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName(name)
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(10)
    return frame, lay


def _primary(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("primary")
    b.setCursor(Qt.PointingHandCursor)
    return b


def _align_numeric(table: QTableWidget) -> None:
    """Right-align the columns that hold only numbers (header included), like the browser."""
    for j in range(table.columnCount()):
        items = [table.item(i, j) for i in range(table.rowCount())]
        if not numeric_column(it.text() if it else "" for it in items):
            continue
        for it in items:
            if it:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head = table.horizontalHeaderItem(j)
        if head:
            head.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)


class PopulatieOpbouw(QDialog):
    """Guides building the population on this computer, with or without the user's own EP-online
    key. Four screens (choice, key, overview, busy); all logic and texts are in
    :mod:`anonymate.opbouw`, which this only drives. The key lives in the key field and in the
    closures of the steps, and nowhere else (not in the settings, not in a text)."""

    KEUZE, SLEUTEL, OVERZICHT, BEZIG = range(4)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Populatie opbouwen")
        self.setStyleSheet(STYLE)
        self.resize(760, 600)
        self.store = store
        self.bron = Bron.SLEUTEL
        self.bestand: str | None = None
        self.controle = None                  # the last Sleutelcontrole of the key in the field
        self.manifest: dict | None = None     # the published manifest.json, when it could be read
        self.stappen: list = []               # what the overview showed (all steps, done or not)
        self.bezig = False
        self.klaar = False
        self.geslaagd = False
        self.stop = threading.Event()
        self._sluit_na_stop = False
        self._threads: list[QThread] = []
        self._schatter = Schatter()
        self._t0 = 0.0
        self._fractie: float | None = None
        self._tik = QTimer(self)
        self._tik.timeout.connect(self._klaar_regel)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)
        self.stack = QStackedWidget()
        for scherm in (self._scherm_keuze, self._scherm_sleutel, self._scherm_overzicht,
                       self._scherm_bezig):
            self.stack.addWidget(scherm())
        lay.addWidget(self.stack, 1)
        row = QHBoxLayout()
        self.cancel_btn = QPushButton("Annuleren")
        self.cancel_btn.clicked.connect(self.afbreken)
        self.back_btn = QPushButton("Terug")
        self.back_btn.clicked.connect(self.terug)
        self.next_btn = _primary("Verder")
        self.next_btn.clicked.connect(self.verder)
        row.addWidget(self.cancel_btn)
        row.addStretch(1)
        row.addWidget(self.back_btn)
        row.addWidget(self.next_btn)
        lay.addLayout(row)
        self._toon(self.KEUZE)
        self._start_worker(lambda: opbouw.haal_pakket_manifest(), self._manifest_binnen,
                           lambda message: None)

    # --- screens -------------------------------------------------------------------------------
    def _scherm(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(_label(title, "h1", wrap=True))
        return page, lay

    def _scherm_keuze(self) -> QWidget:
        page, lay = self._scherm("Populatie opbouwen")
        lay.addWidget(_label(opbouw.UITLEG_EP, "lead", wrap=True))
        bewaard = " (bewaarde sleutel gevonden)" if opbouw.bewaarde_sleutel(self.store) else ""
        self.radio_sleutel = QRadioButton(opbouw.KEUZE_SLEUTEL + " (aanbevolen)" + bewaard)
        self.radio_bestand = QRadioButton(opbouw.KEUZE_BESTAND)
        self.radio_geen = QRadioButton(opbouw.KEUZE_GEEN)
        self.radio_sleutel.setChecked(True)
        for r in (self.radio_sleutel, self.radio_bestand, self.radio_geen):
            r.toggled.connect(self._keuze_veranderd)
        lay.addWidget(self.radio_sleutel)
        lay.addWidget(self.radio_bestand)
        self.bestand_rij = QWidget()
        rij = QHBoxLayout(self.bestand_rij)
        rij.setContentsMargins(24, 0, 0, 0)
        kies = QPushButton("Bestand kiezen…")
        kies.clicked.connect(self.kies_bestand)
        self.bestand_label = _label("nog geen bestand gekozen", "note")
        rij.addWidget(kies)
        rij.addWidget(self.bestand_label, 1)
        lay.addWidget(self.bestand_rij)
        lay.addWidget(self.radio_geen)
        self.geen_gevolg = _label(opbouw.ZONDER_EP_GEVOLG, "note", wrap=True)
        lay.addWidget(self.geen_gevolg)
        self.keuze_melding = _label("", "note", wrap=True)
        lay.addWidget(self.keuze_melding)
        lay.addStretch(1)
        self._keuze_veranderd()
        return page

    def _scherm_sleutel(self) -> QWidget:
        page, lay = self._scherm("Je eigen EP-online-sleutel")
        for i, tekst in enumerate(opbouw.STAPPEN_SLEUTEL, 1):
            lay.addWidget(_label(f"{i}. {tekst}", "", wrap=True))
        lay.addWidget(_label(opbouw.SLEUTEL_VERVALT, "note", wrap=True))
        aanvraag = QPushButton("Aanvraagformulier openen")
        aanvraag.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(opbouw.EP_AANVRAAG_URL)))
        rij = QHBoxLayout()
        rij.addWidget(aanvraag)
        rij.addStretch(1)
        lay.addLayout(rij)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("plak hier de sleutel")
        self.key_edit.textChanged.connect(self._sleutel_veranderd)
        self.key_toon = QCheckBox("tonen")
        self.key_toon.toggled.connect(lambda on: self.key_edit.setEchoMode(
            QLineEdit.Normal if on else QLineEdit.Password))
        self.check_btn = QPushButton("Controleren")
        self.check_btn.clicked.connect(self.controleer)
        sleutel = QHBoxLayout()
        sleutel.addWidget(self.key_edit, 1)
        sleutel.addWidget(self.key_toon)
        sleutel.addWidget(self.check_btn)
        lay.addLayout(sleutel)
        self.check_bar = QProgressBar()
        self.check_bar.setRange(0, 0)
        self.check_bar.setTextVisible(False)
        self.check_bar.setFixedHeight(6)
        self.check_bar.hide()
        lay.addWidget(self.check_bar)
        self.key_melding = _label("", "note", wrap=True)
        lay.addWidget(self.key_melding)
        self.onthoud = QCheckBox("Onthouden op deze computer")
        lay.addWidget(self.onthoud)
        lay.addWidget(_label(opbouw.PRIVACY_SLEUTEL.format(pad=self.store.root / ".env"), "note",
                             wrap=True))
        lay.addStretch(1)
        return page

    def _scherm_overzicht(self) -> QWidget:
        page, lay = self._scherm("Dit gaat AnonyMate doen")
        self.overzicht = _label("", "", wrap=True)
        self.overzicht.setTextFormat(Qt.RichText)
        lay.addWidget(self.overzicht)
        lay.addStretch(1)
        return page

    def _scherm_bezig(self) -> QWidget:
        page, lay = self._scherm("Bezig met opbouwen")
        self.bezig_titel = page.findChildren(QLabel, "h1")[0]
        self.balk = VoortgangBalk()
        lay.addWidget(self.balk)
        self.klaar_label = _label("", "note", wrap=True)
        lay.addWidget(self.klaar_label)
        self.status = _label("", "", wrap=True)
        lay.addWidget(self.status)
        lay.addStretch(1)
        return page

    # --- navigation ----------------------------------------------------------------------------
    def _toon(self, scherm: int) -> None:
        self.stack.setCurrentIndex(scherm)
        self.back_btn.setVisible(scherm in (self.SLEUTEL, self.OVERZICHT))
        self.cancel_btn.setVisible(True)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Afbreken" if scherm == self.BEZIG else "Annuleren")
        self.next_btn.setVisible(scherm != self.BEZIG)
        self.next_btn.setText({self.KEUZE: "Verder", self.SLEUTEL: "Verder",
                               self.OVERZICHT: "Beginnen", self.BEZIG: "Sluiten"}[scherm])
        self.next_btn.setEnabled(scherm != self.SLEUTEL or self._sleutel_mag_verder())

    def verder(self) -> None:
        scherm = self.stack.currentIndex()
        if scherm == self.KEUZE:
            self.bron = (Bron.SLEUTEL if self.radio_sleutel.isChecked() else
                         Bron.BESTAND if self.radio_bestand.isChecked() else Bron.GEEN)
            if self.bron is Bron.BESTAND and not self.bestand:
                self.keuze_melding.setText("Kies eerst het EP-online-bestand.")
                return
            if self.bron is Bron.SLEUTEL:
                self._toon(self.SLEUTEL)
                bewaard = opbouw.bewaarde_sleutel(self.store)
                if bewaard and not self.key_edit.text():
                    self.key_edit.setText(bewaard)
                    self.controleer()
            else:
                self._naar_overzicht()
        elif scherm == self.SLEUTEL:
            if self.controle is not None and self.controle.geldig is None and \
                    QMessageBox.question(self, "anonymate", self.controle.melding + "\n\nToch "
                                         "doorgaan zonder de sleutel te controleren?"
                                         ) != QMessageBox.Yes:
                return
            self._naar_overzicht()
        elif scherm == self.OVERZICHT:
            self.beginnen()
        elif self.klaar:
            self.accept()

    def terug(self) -> None:
        scherm = self.stack.currentIndex()
        if scherm == self.OVERZICHT:
            self._toon(self.SLEUTEL if self.bron is Bron.SLEUTEL else self.KEUZE)
        elif scherm == self.BEZIG and not self.bezig:
            self._naar_overzicht()
        else:
            self._toon(self.KEUZE)

    def _keuze_veranderd(self, *_args) -> None:
        self.bestand_rij.setVisible(self.radio_bestand.isChecked())
        self.geen_gevolg.setVisible(self.radio_geen.isChecked())
        self.keuze_melding.setText("")

    def kies_bestand(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "EP-online-bestand kiezen", str(Path.home()),
                                              "EP-online (*.zip *.csv)")
        if path:
            self.bestand = path
            self.bestand_label.setText(Path(path).name)
            self.keuze_melding.setText("")

    # --- the key -------------------------------------------------------------------------------
    def _sleutel_mag_verder(self) -> bool:
        return self.controle is not None and self.controle.geldig is not False

    def _sleutel_veranderd(self, *_args) -> None:
        self.controle = None
        self.key_melding.setText("")
        self.next_btn.setEnabled(self.stack.currentIndex() != self.SLEUTEL)

    def controleer(self) -> None:
        key = self.key_edit.text()
        self.check_btn.setEnabled(False)
        self.check_bar.show()
        self.key_melding.setText("Bezig met controleren…")

        def klaar(controle) -> None:
            self.check_btn.setEnabled(True)
            self.check_bar.hide()
            if key != self.key_edit.text():       # changed meanwhile: that answer is not this key's
                return
            self.controle = controle
            self.key_melding.setText(controle.melding)
            self.next_btn.setEnabled(self._sleutel_mag_verder())

        def mislukt(message: str) -> None:
            klaar(opbouw.Sleutelcontrole(None, opbouw.NIET_BEREIKBAAR))

        self._start_worker(lambda: opbouw.controleer_sleutel(key), klaar, mislukt)

    # --- overview and run ----------------------------------------------------------------------
    def _plan_args(self) -> dict:
        key = self.key_edit.text() if self.bron is Bron.SLEUTEL else None
        return dict(key=key, bestand=self.bestand if self.bron is Bron.BESTAND else None,
                    pakket_manifest=self.manifest,
                    ep_zip=self.controle.bestand if self.controle else None)

    def _naar_overzicht(self) -> None:
        try:
            self.stappen = opbouw.overzicht(self.store, opbouw.toestand(self.store), self.bron,
                                            **self._plan_args())
        except ValueError as e:
            self.keuze_melding.setText(str(e))
            self._toon(self.KEUZE)
            return
        todo = [s for s in self.stappen if not s.klaar]
        regels = []
        for i, s in enumerate(self.stappen, 1):
            regels.append(f"<span style='color:#8A8A85'>{i}. {escape(s.naam)} (al klaar)</span>"
                          if s.klaar else f"{i}. {escape(s.naam)}")
        tekst = ["<br>".join(regels) if regels else escape(opbouw.NIETS_TE_DOEN)]
        ruimte = None
        if todo:
            ruimte = opbouw.controleer_ruimte(self.store, self.manifest)
            tekst.append(f"{escape(vooraf_schatting(todo))}. {escape(opbouw.DOWNLOADS_GESCHAT)}")
            tekst.append(f"Opslag: {escape(str(self.store.root))}<br>"
                         f"Downloads: {escape(str(self.store.downloads))}<br>"
                         f"{escape(opbouw.ruimte_regel(self.store, self.manifest))}")
            tekst.append(escape(opbouw.DOORLOPEN))
            if ruimte:
                tekst.append(f"<b>{escape(ruimte)}</b>")
        self.overzicht.setText("<br><br>".join(tekst))
        self._toon(self.OVERZICHT)
        self.next_btn.setEnabled(bool(todo) and not ruimte)

    def beginnen(self) -> None:
        try:         # again from the state now: after a stop or an error, done steps are skipped
            todo = opbouw.plan(self.store, opbouw.toestand(self.store), self.bron,
                               **self._plan_args())
        except ValueError as e:
            self.status.setText(str(e))
            return
        key = self.key_edit.text() if self.bron is Bron.SLEUTEL else ""
        self.stop.clear()
        self.bezig, self.klaar, self.geslaagd = True, False, False
        self._toon(self.BEZIG)
        self.bezig_titel.setText("Bezig met opbouwen")
        self.status.setText("")
        self._schatter, self._fractie, self._t0 = Schatter(), None, time.monotonic()
        self._todo = todo
        self.balk.start("voorbereiden…")
        self._tik.start(1000)
        self._klaar_regel()

        def work(report):
            opbouw.voer_uit(todo, report, stop=self.stop)

        def gelukt(_result) -> None:
            self._einde()
            if key and self.onthoud.isChecked():
                try:
                    opbouw.bewaar_sleutel(self.store, key)
                except OSError as e:
                    self.status.setText(f"De sleutel kon niet worden bewaard ({e}).")
            self.key_edit.clear()                 # the key is not needed in memory any more
            self.klaar = self.geslaagd = True
            self.bezig_titel.setText("Klaar")
            self.status.setText("Klaar: " + opbouw.toestand_regel(opbouw.toestand(self.store)))
            self.cancel_btn.hide()
            self.next_btn.setText("Sluiten")
            self.next_btn.show()

        def mislukt(message: str) -> None:
            self._einde()
            if self.stop.is_set() or message.startswith("Geannuleerd"):
                self.bezig_titel.setText("Afgebroken")
                self.status.setText("De volgende keer gaat AnonyMate verder waar het bleef.")
            else:
                self.bezig_titel.setText("Er ging iets mis")
                self.status.setText(_readable(message))
            if self._sluit_na_stop:
                super(PopulatieOpbouw, self).reject()
                return
            self.cancel_btn.setText("Sluiten")
            self.cancel_btn.setEnabled(True)
            self.back_btn.show()
            self.next_btn.setText("Opnieuw proberen")
            self.next_btn.setEnabled(True)
            self.next_btn.show()

        self._start_worker(work, gelukt, mislukt, self._voortgang)

    def _einde(self) -> None:
        self.bezig = False
        self._tik.stop()
        self.balk.stop()
        self.klaar_label.setText("")

    def _voortgang(self, fraction, text: str) -> None:
        self.balk.report(fraction, text)
        if fraction is not None:
            self._fractie = fraction

    def _klaar_regel(self) -> None:
        """The finishing time under the bar; the reference estimate until the bar knows more."""
        rest = self._schatter.remaining(self._fractie, time.monotonic() - self._t0)
        if rest is None:
            self.klaar_label.setText(vooraf_schatting(self._todo))
        else:
            self.klaar_label.setText(klaar_rond(rest, datetime.now()))

    def afbreken(self) -> None:
        """Cancel (Annuleren) before the run; stop it while it runs; Sluiten after a stop."""
        if self.bezig:
            self.stop.set()
            self.cancel_btn.setText("Bezig met afbreken…")
            self.cancel_btn.setEnabled(False)
        else:
            super().reject()

    def reject(self) -> None:
        if self.bezig:
            if QMessageBox.question(self, "anonymate", "AnonyMate is nog bezig. Afbreken? De "
                                    "volgende keer gaat het verder waar het bleef."
                                    ) == QMessageBox.Yes:
                self._sluit_na_stop = True
                self.afbreken()
            return
        super().reject()

    def _manifest_binnen(self, manifest) -> None:
        self.manifest = manifest

    # --- thread --------------------------------------------------------------------------------
    def _start_worker(self, fn, on_done, on_failed, on_progress=None) -> None:
        thread = QThread(self)
        worker = Worker(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # bound methods of the dialog (and closures made here): Qt then runs them in this thread
        worker.done.connect(on_done)
        worker.failed.connect(on_failed)
        if on_progress is not None:
            worker.progress.connect(on_progress)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread._worker = worker
        self._threads.append(thread)
        thread.start()


class MainWindow(QMainWindow):
    def __init__(self, population_factory=None):
        super().__init__()
        self.setWindowTitle(f"AnonyMate {__version__}: herleidbaarheidstoets")
        self.resize(1320, 860)
        self.setStyleSheet(STYLE)
        self.population_factory = population_factory
        self._population: Population | None = None
        self.df: pd.DataFrame | None = None
        self.path: Path | None = None
        self.assessment = None
        self.steps = None
        self.current_df = None
        self.lezing_vast: dict = {}          # column -> reading taken over with a step
        self.lezing_rijen: list = []         # the readings and what another one gives
        self.norm_locked = False
        self.weather_tolerance = 0.0
        self.weather_seed: int | None = None
        self.uhi_path: str | None = None
        self._map_data = None
        self._threads: list[QThread] = []

        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(central)
        outer.addWidget(self._rail())
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        for build in (self._page_dataset, self._page_norm, self._page_columns,
                      self._page_signature, self._page_weather, self._page_attacker,
                      self._page_outcome):
            self.pages.addWidget(self._scrolling(build()))
        self.step_list.currentRowChanged.connect(self._row_changed)

        self.pop_card.setVisible(population_factory is None)     # its text: on reaching step 6
        self._update_k()
        self._set_busy(False)
        self._refresh_rail()
        self.go(0)

    # --- layout --------------------------------------------------------------------------------
    def _rail(self) -> QWidget:
        rail = QWidget()
        rail.setObjectName("rail")
        rail.setFixedWidth(260)
        lay = QVBoxLayout(rail)
        lay.setContentsMargins(18, 22, 18, 18)
        lay.setSpacing(16)
        lay.addWidget(_label("AnonyMate", "brand"))
        lay.addWidget(_label("herleidbaarheidstoets", "brandSub"))
        self.dataset_card = _label("nog geen dataset", "datasetCard", wrap=True)
        lay.addWidget(self.dataset_card)
        self.practice_banner = QWidget()
        self.practice_banner.setObjectName("practiceBanner")
        self.practice_banner.setAttribute(Qt.WA_StyledBackground, True)
        self.practice_banner.setToolTip("Verzonnen woningen in een verzonnen Nederland: de "
                                        "uitkomsten zeggen niets over echte woningen.")
        bl = QHBoxLayout(self.practice_banner)
        bl.setContentsMargins(10, 6, 6, 6)
        bl.addWidget(_label("OEFENMODUS", "practiceTitle"), 1)
        stop = QPushButton("Stoppen")
        stop.setToolTip("Terug naar de echte populatie; open daarna je eigen dataset")
        stop.clicked.connect(self.stop_practice)
        bl.addWidget(stop)
        self.practice_banner.hide()
        lay.addWidget(self.practice_banner)
        self.step_list = QListWidget()
        self.step_list.setObjectName("steps")
        self.step_list.setFocusPolicy(Qt.NoFocus)
        # the rail never scrolls: seven steps always fit, also on a small laptop screen
        self.step_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.step_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.step_list.setTextElideMode(Qt.ElideRight)
        for _ in STEPS:
            self.step_list.addItem(QListWidgetItem())
        lay.addWidget(self.step_list, 1)
        lay.addWidget(_label("Alles blijft op deze computer: geen netwerk, geen upload.",
                             "railNote", wrap=True))
        return rail

    def _scrolling(self, page: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setWidget(page)
        return area

    def _page(self, number: int, eyebrow: str, title: str, lead: str) -> tuple[QWidget,
                                                                              QVBoxLayout]:
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 18, 32, 18)
        lay.setSpacing(12)
        lay.addWidget(_label(f"STAP {number} VAN {len(STEPS)} · {eyebrow.upper()}", "eyebrow"))
        lay.addWidget(_label(title, "h1", wrap=True))
        if lead:
            lead_label = _label(lead, "lead", wrap=True)
            lead_label.setMaximumWidth(860)
            lay.addWidget(lead_label)
        return page, lay

    def _next(self, lay: QVBoxLayout, text: str, target: int) -> QPushButton:
        row = QHBoxLayout()
        row.addStretch(1)
        b = _primary(text)
        b.clicked.connect(lambda: self.go(target))
        row.addWidget(b)
        lay.addLayout(row)
        return b

    def _page_dataset(self) -> QWidget:
        page, lay = self._page(1, "dataset", "Welke dataset wil je publiceren?",
                               "Open een tabel met één rij per woning (csv, Excel of parquet). "
                               "AnonyMate leest hem alleen; er gaat niets van deze computer af.")
        card, cl = _card()
        row = QHBoxLayout()
        self.open_btn = _primary("Dataset openen…")
        self.open_btn.clicked.connect(self.choose_file)
        self.file_label = _label("nog geen bestand gekozen", "note")
        row.addWidget(self.open_btn)
        row.addWidget(self.file_label, 1)
        cl.addLayout(row)
        lay.addWidget(card)
        practice, pl = _card()
        prow = QHBoxLayout()
        text = QVBoxLayout()
        text.addWidget(_label("Nieuw hier? Oefen eerst", "h2"))
        text.addWidget(_label("Met 62 verzonnen woningen, hun weer en een verzonnen Nederland om "
                              "ze in te zoeken. Alles werkt, zonder downloads; de uitkomsten "
                              "zeggen niets over echte woningen. Stoppen kan altijd; je eigen "
                              "dataset openen stopt de oefenmodus ook.", "note", wrap=True))
        prow.addLayout(text, 1)
        self.practice_btn = QPushButton("Oefenen met het voorbeeld")
        self.practice_btn.clicked.connect(self.start_practice)
        prow.addWidget(self.practice_btn)
        pl.addLayout(prow)
        lay.addWidget(practice)
        region, rl = _card()
        rl.addWidget(_label("Uit welke regio komen de woningen?", "h2"))
        rl.addWidget(_label("Is bekend dat deelnemers alleen uit bepaalde provincies of gemeenten "
                            "komen (bijvoorbeeld omdat de werving dat vermeldt), vink die dan "
                            "aan: een aanvaller zoekt dan alleen daar, en de toets telt alleen "
                            "daar. Standaard: heel Nederland.", "note", wrap=True))
        self.region_all = QCheckBox("heel Nederland")
        self.region_all.setChecked(True)
        rl.addWidget(self.region_all)
        grid = QGridLayout()
        self.region_boxes = {}
        for i, name in enumerate(PROVINCES):
            box = QCheckBox(name)
            box.setEnabled(False)
            box.toggled.connect(self._region_changed)
            grid.addWidget(box, i // 4, i % 4)
            self.region_boxes[name] = box
        rl.addLayout(grid)
        self.region_municipalities = QLineEdit()
        self.region_municipalities.setPlaceholderText("en/of gemeenten, met komma's: Zwolle, "
                                                      "Deventer")
        self.region_municipalities.setEnabled(False)
        self.region_municipalities.editingFinished.connect(self._region_changed)
        rl.addWidget(self.region_municipalities)

        def toggle_all(checked: bool) -> None:
            for box in self.region_boxes.values():
                box.setEnabled(not checked)
            self.region_municipalities.setEnabled(not checked)
            self._region_changed()
        self.region_all.toggled.connect(toggle_all)
        lay.addWidget(region)
        lay.addStretch(1)
        self.dataset_next = self._next(lay, "Verder naar de norm", 1)
        return page

    def _page_norm(self) -> QWidget:
        page, lay = self._page(2, "privacynorm", "Leg de norm vast, vóór je naar uitkomsten kijkt",
                               "Hoe klein moet de kans zijn dat iemand een woning in je dataset "
                               "terugvindt? Kies die grens nu. Daarna ligt hij vast voor deze "
                               "dataset, zodat je hem niet ongemerkt aanpast aan de uitkomst.")
        card, cl = _card()
        cl.addWidget(_label("Maximale kans op heridentificatie p", "h2"))
        prow = QHBoxLayout()
        self.p_slider = QSlider(Qt.Horizontal)
        self.p_slider.setRange(round(P_MIN * 100), round(P_MAX * 100))
        self.p = QDoubleSpinBox()
        self.p.setRange(P_MIN, P_MAX)
        self.p.setSingleStep(0.01)
        self.p.setDecimals(2)
        self.p.setValue(P_DEFAULT)
        self.p_slider.setValue(round(P_DEFAULT * 100))
        self.p.valueChanged.connect(self._update_k)
        self.p.valueChanged.connect(lambda v: self.p_slider.setValue(round(v * 100)))
        self.p_slider.valueChanged.connect(lambda v: self.p.setValue(v / 100))
        prow.addWidget(self.p_slider, 1)
        prow.addWidget(self.p)
        cl.addLayout(prow)
        marks = QGridLayout()
        for i, (pv, text) in enumerate(NORM_MARKS):
            t = Threshold(pv)
            lab = _label(f"<b>{_nl(pv, 2)} · k ≥ {t.k}</b><br>{text}", "note", wrap=True)
            lab.setTextFormat(Qt.RichText)
            marks.addWidget(lab, 0, i)
        cl.addLayout(marks)
        soft = QFrame()
        soft.setObjectName("soft")
        sl = QHBoxLayout(soft)
        sl.setContentsMargins(16, 14, 16, 14)
        self.k_big = _label("", "big")
        sl.addWidget(self.k_big)
        right = QVBoxLayout()
        self.norm_houses = HouseArray(30)
        right.addWidget(self.norm_houses)
        self.k_label = _label("", "note", wrap=True)
        right.addWidget(self.k_label)
        sl.addLayout(right, 1)
        cl.addWidget(soft)
        self.lock_label = _label("nog niet vastgelegd: toetsen kan pas daarna", "note", wrap=True)
        cl.addWidget(self.lock_label)
        lay.addWidget(card)
        why, wl = _card()
        wl.addWidget(_label("Waarom eerst de norm?", "h2"))
        wl.addWidget(_label("Wie de uitkomst al kent, is geneigd de lat te verleggen tot het "
                            "past. Een vooraf vastgelegde norm is ethisch en juridisch de juiste "
                            "volgorde. Afwegen gebeurt daarna, binnen de norm: grover publiceren "
                            "of woningen weglaten.", "note", wrap=True))
        lay.addWidget(why)
        lay.addStretch(1)
        # one button: it fixes the norm and goes on; the only way past this step
        row = QHBoxLayout()
        row.addStretch(1)
        self.lock_btn = _primary(LOCK_TEXT)
        self.lock_btn.clicked.connect(self.lock_and_continue)
        self.lock_btn.setEnabled(False)          # until a dataset is open
        row.addWidget(self.lock_btn)
        lay.addLayout(row)
        return page

    def _page_columns(self) -> QWidget:
        page, lay = self._page(3, "kolommen", "Wat verraadt elke kolom?",
                               "AnonyMate stelt per kolom een rol voor. Controleer die: jij weet "
                               "wat er echt in staat. Directe identificatoren gaan er altijd uit; "
                               "kenmerken die ook in een register staan, tellen mee in de toets.")
        self.columns = QTableWidget(0, 5)
        self.columns.setHorizontalHeaderLabels(["kolom", "voorstel", "behandelen als", "lezing",
                                                "reden"])
        self.columns.horizontalHeaderItem(3).setToolTip(
            "Afgeronde waarden en klassen die een grens delen zijn niet aan de waarden te zien. "
            "Kies wat het codeboek zegt; het rapport laat zien wat een andere lezing geeft.")
        self.columns.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.columns.horizontalHeader().setStretchLastSection(True)
        self.columns.verticalHeader().setVisible(False)
        self.columns.setMinimumHeight(360)
        lay.addWidget(self.columns, 1)
        self._next(lay, "Verder", 3)
        return page

    def _page_signature(self) -> QWidget:
        page, lay = self._page(4, "signatuur (optioneel)",
                               "Een warmtesignatuur uit het adres meepubliceren?",
                               "Per woning een uit openbare registers berekende signatuur, "
                               "afgerond. Iedereen kan die voor elke woning uitrekenen: afronden "
                               "is de enige bescherming. Het adres zelf wordt nooit gepubliceerd.")
        card, cl = _card()
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        self.sig_on = QCheckBox("signatuur toevoegen")
        form.addRow(self.sig_on)
        self.koppel = QLineEdit()
        self.koppel.setPlaceholderText("postcode,huisnummer  ·  of één kolom met BAG-ID  ·  of postcode=..,toevoeging=..  ·  of auto")
        self.koppel.setToolTip("Welke kolom is welk adresdeel. Op volgorde: postcode,huisnummer,"
                               "huisletter,toevoeging, met een lege plek als een deel ontbreekt "
                               "(pc,nr,,toev). Of bij naam: postcode=pc,huisnummer=nr,"
                               "toevoeging=toev. 'auto' laat AnonyMate zoeken.")
        form.addRow("koppelkolommen", self.koppel)
        self.sig_method = QComboBox()
        for m, label in (("passend", "passend: per woning ep (met label) of best"),
                         ("ep", "ep: schil en isolatie uit het energielabel"),
                         ("best", "best: huidige staat, gekalibreerd op het label"),
                         ("mwa", "mwa: bouwstaat met Maatwerkadvies-correcties"),
                         ("nta8800", "nta8800: bouwstaat, forfaitair")):
            self.sig_method.addItem(label, m)
        form.addRow("methode", self.sig_method)
        srow = QHBoxLayout()
        self.sig_steps = {}
        for output, default, top in (("H", 50.0, 1000.0), ("C", 5000.0, 100000.0),
                                     ("tau", 0.0, 500.0), ("Asol", 0.0, 200.0),
                                     ("Ainf", 0.0, 1000.0)):
            symbol, unit, meaning = SIGNATURE_OUTPUTS[output]
            box = QDoubleSpinBox()
            box.setRange(0, top)
            box.setDecimals(0)
            box.setValue(default)
            box.setSuffix(f" {unit}")
            box.setToolTip(f"{meaning}; afrondstap in {unit}, 0 = niet publiceren")
            label = QLabel(symbol)
            label.setTextFormat(Qt.RichText)
            label.setToolTip(meaning)
            srow.addWidget(label)
            srow.addWidget(box)
            self.sig_steps[output] = box
        form.addRow("afrondstappen (0 = niet)", srow)
        cl.addLayout(form)
        items = [f"{sym}: {meaning}" for sym, _, meaning in SIGNATURE_OUTPUTS.values()]
        legend = QLabel(" · ".join(items[:2]) + "<br>" + " · ".join(items[2:]))
        legend.setTextFormat(Qt.RichText)
        legend.setWordWrap(True)
        legend.setObjectName("note")
        cl.addWidget(legend)
        lay.addWidget(card)
        lay.addStretch(1)
        self._next(lay, "Verder naar de weerlocatie", 4)
        return page

    def _page_weather(self) -> QWidget:
        page, lay = self._page(5, "weerlocatie (optioneel)", "Weer bij de woning, zonder de woning "
                               "te verraden", "Heeft de dataset een adres, BAG-ID of GPS-locatie, "
                               "dan kun je een weerlocatie toevoegen: het dichtstbijzijnde "
                               "KNMI-station, of een H3-cel van de locatie na willekeurige ruis. "
                               "De locatie zelf wordt nooit gepubliceerd.")
        body = QHBoxLayout()
        left = QVBoxLayout()
        src, sl = _card()
        sl.addWidget(_label("Locatie uit", "h2"))
        self.w_source = QComboBox()
        self.w_source.addItem("koppelkolommen uit stap 4 (adres of BAG-ID)", "koppel")
        self.w_source.addItem("GPS-kolommen (breedte- en lengtegraad)", "gps")
        sl.addWidget(self.w_source)
        gps = QHBoxLayout()
        self.w_lat, self.w_lon = QComboBox(), QComboBox()
        gps.addWidget(_label("breedte", "note"))
        gps.addWidget(self.w_lat, 1)
        gps.addWidget(_label("lengte", "note"))
        gps.addWidget(self.w_lon, 1)
        sl.addLayout(gps)
        tab_add = QWidget()
        tal = QVBoxLayout(tab_add)
        tal.setContentsMargins(0, 6, 0, 0)
        tal.addWidget(src)
        kind, kl = _card()
        kl.addWidget(_label("Weerlocatie", "h2"))
        self.w_none = QRadioButton("geen weerlocatie toevoegen")
        self.w_station = QRadioButton("dichtstbijzijnd KNMI-station")
        self.w_h3 = QRadioButton("H3-cel na ruis (weer geïnterpoleerd op het celmidden)")
        self.w_none.setChecked(True)
        for b in (self.w_none, self.w_station, self.w_h3):
            b.toggled.connect(self._weather_view)
            kl.addWidget(b)
        form = QFormLayout()
        self.w_level = QSpinBox()
        self.w_level.setRange(4, 8)
        self.w_level.setValue(5)
        self.w_level.valueChanged.connect(self._weather_view)
        self.w_sigma = QSpinBox()
        self.w_sigma.setRange(0, 50)
        self.w_sigma.setValue(10)
        self.w_sigma.setSuffix(" km")
        self.w_sigma.valueChanged.connect(self._weather_view)
        form.addRow("H3-niveau", self.w_level)
        form.addRow("ruis σ (per richting)", self.w_sigma)
        kl.addLayout(form)
        self.w_count_noise = QCheckBox("ruis meetellen in de toets (bovengrens)")
        self.w_count_noise.setToolTip("De aanvaller zoekt in de cel en haar buren binnen σ. Dat "
                                      "overschat de bescherming: wie σ kent, weegt de kandidaten "
                                      "(zie de statistiek per cel op de kaart).")
        self.w_count_noise.setChecked(True)
        kl.addWidget(self.w_count_noise)
        self.w_level_note = _label("", "note", wrap=True)
        kl.addWidget(self.w_level_note)
        tal.addWidget(kind)
        tal.addStretch(1)
        uhi, ul = _card()
        self.w_uhi = QCheckBox("stedelijk hitte-eiland (UHI) als kolom toevoegen")
        ul.addWidget(self.w_uhi)
        self.w_uhi_bron = _label("", "note", wrap=True)
        ul.addWidget(self.w_uhi_bron)
        urow = QHBoxLayout()
        self.w_uhi_file = QLineEdit()
        self.w_uhi_file.setPlaceholderText("eigen bestand gebruiken (optioneel): csv/parquet met pc6, uhi")
        browse = QPushButton("Kiezen…")
        browse.clicked.connect(self._choose_uhi)
        urow.addWidget(self.w_uhi_file, 1)
        urow.addWidget(browse)
        ul.addLayout(urow)
        form2 = QFormLayout()
        self.w_uhi_step = QDoubleSpinBox()
        self.w_uhi_step.setRange(0.1, 2.0)
        self.w_uhi_step.setSingleStep(0.1)
        self.w_uhi_step.setDecimals(1)
        self.w_uhi_step.setValue(0.5)
        self.w_uhi_step.setSuffix(" °C")
        form2.addRow("klassen van", self.w_uhi_step)
        ul.addLayout(form2)
        ul.addWidget(_label("Liever niet publiceren: binnen een weerzone wijst een fijne UHI-"
                            "waarde een wijk aan. Verwerk UHI liever in de berekening zelf.",
                            "note", wrap=True))
        tab_uhi = QWidget()
        tul = QVBoxLayout(tab_uhi)
        tul.setContentsMargins(0, 6, 0, 0)
        tul.addWidget(uhi)
        tul.addStretch(1)
        trace, tl = _card()
        tl.addWidget(_label("Zit er al weer in de dataset?", "h2"))
        tl.addWidget(_label("Buitentemperatuur per woning en uur verraadt waar die vandaan komt. "
                            "AnonyMate zoekt, zoals een aanvaller, het best passende KNMI-station "
                            "of de best passende H3-cel (niveau 4 of 5) en toetst die als "
                            "verborgen locatie. Nodig: KNMI-uurgegevens (anonymate ingest "
                            "knmi-uur --jaar ...).", "note", wrap=True))
        trow = QHBoxLayout()
        self.t_file = QLineEdit()
        self.t_file.setPlaceholderText("bestand, map of zip met weerreeksen")
        tb = QPushButton("Bestand…")
        tb.clicked.connect(lambda: self._choose_series(folder=False))
        tm = QPushButton("Map…")
        tm.clicked.connect(lambda: self._choose_series(folder=True))
        trow.addWidget(self.t_file, 1)
        trow.addWidget(tb)
        trow.addWidget(tm)
        tl.addLayout(trow)
        tform = QFormLayout()
        self.t_idfrom = QComboBox()
        self.t_idfrom.addItem("een kolom", "kolom")
        self.t_idfrom.addItem("de bestandsnaam (IM_customer_<id>.csv, home_id=<id>)", "bestand")
        self.t_idfrom.addItem("de mapnaam (woning_7/knmi.csv)", "map")
        self.t_pattern = QLineEdit("*")
        self.t_sample = QSpinBox()
        self.t_sample.setRange(10, 5000)
        self.t_sample.setValue(300)
        self.t_id, self.t_time, self.t_value, self.t_key = (QComboBox(), QComboBox(),
                                                           QComboBox(), QComboBox())
        def pair(a, la, b, lb):
            row = QHBoxLayout()
            row.addWidget(a, 1)
            row.addWidget(_label(lb, "note"))
            row.addWidget(b, 1)
            tform.addRow(la, row)
        tform.addRow("woning-ID uit", self.t_idfrom)
        pair(self.t_pattern, "bestanden", self.t_sample, "steekproef")
        pair(self.t_id, "ID-kolom", self.t_key, "in dataset")
        pair(self.t_time, "tijd", self.t_value, "buitentemp.")
        tl.addLayout(tform)
        self.t_run = QPushButton("Weerlocatie terugleiden")
        self.t_run.clicked.connect(self.run_trace)
        tl.addWidget(self.t_run)
        tab_trace = QWidget()
        ttl = QVBoxLayout(tab_trace)
        ttl.setContentsMargins(0, 6, 0, 0)
        ttl.addWidget(trace)
        ttl.addStretch(1)
        self.w_tabs = QTabWidget()
        self.w_tabs.addTab(tab_add, "Toevoegen")
        self.w_tabs.addTab(tab_trace, "Weer al in de data?")
        self.w_tabs.addTab(tab_uhi, "Hitte-eiland")
        left.addWidget(self.w_tabs, 1)
        row = QHBoxLayout()
        self.w_apply = _primary("Weerlocatie toevoegen")
        self.w_apply.clicked.connect(self.apply_weather)
        row.addWidget(self.w_apply)
        self.w_status = _label("", "note", wrap=True)
        row.addWidget(self.w_status, 1)
        left.addLayout(row)
        self.weer_bar = VoortgangBalk(vertical=True)      # weerspoor, weerlocatie en UHI
        left.addWidget(self.weer_bar)
        left.addStretch(1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(460)
        body.addWidget(lw)
        right = QVBoxLayout()
        self.map_band = _label("", "note", wrap=True)      # no weather location added yet
        self.map_band.setStyleSheet("background:#EEF1F5; color:#5B6573; padding:4px 8px; "
                                    "border-radius:6px;")
        self.map_band.hide()
        right.addWidget(self.map_band)
        self.map = MapWidget()
        self.map.cellClicked.connect(self._cell_clicked)
        right.addWidget(self.map, 1)
        self.map_busy = VoortgangBalk(6, vertical=True)   # a cell being calculated
        right.addWidget(self.map_busy)
        stats, stl = _card()
        self.cell_title = _label("Klik een cel op de kaart", "h2")
        stl.addWidget(self.cell_title)
        self.cell_text = _label("Scrol om in te zoomen, sleep om te schuiven.", "note", wrap=True)
        stl.addWidget(self.cell_text)
        right.addWidget(stats)
        body.addLayout(right, 1)
        lay.addLayout(body, 1)
        nxt = _primary("Verder")
        nxt.clicked.connect(lambda: self.go(5))
        row.addWidget(nxt)
        return page

    def _choose_series(self, folder: bool = False) -> None:
        if folder:
            path = QFileDialog.getExistingDirectory(self, "Map met weerreeksen")
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Weerreeksen", "",
                                                  "Data (*.csv *.xlsx *.parquet *.zip)")
        if path:
            self._series_chosen(path)

    def _series_chosen(self, path: str) -> None:
        from .weerspoor import (ID_HINT, TIME_HINT, VALUE_HINT, _header, guess_column,
                                members)
        self.t_file.setText(path)
        files = members(path, self.t_pattern.text() or "*")
        if len(files) > 1:
            self.t_idfrom.setCurrentIndex(1)
        cols = []
        if files:
            name, opener = files[0]
            with opener() as h:
                cols = _header(h, name)
        auto = "(automatisch)"
        for box, hint in ((self.t_id, ID_HINT), (self.t_time, TIME_HINT),
                          (self.t_value, VALUE_HINT)):
            box.clear()
            box.addItems([auto] + cols)
            box.setCurrentText(guess_column(cols, hint) or auto)
        self.t_key.clear()
        if self.df is not None:
            self.t_key.addItems(list(self.df.columns))
            guess = next((c for c in self.df.columns if c == self.t_id.currentText()), None)
            if guess:
                self.t_key.setCurrentText(guess)

    def run_trace(self) -> None:
        """Trace the weather series back to a station or cell, in the background."""
        if self.df is None or not self.t_file.text():
            self._failed("open eerst een dataset en kies het bestand met weerreeksen")
            return
        auto = lambda box: None if box.currentText() in ("", "(automatisch)") \
            else box.currentText()  # noqa: E731
        path, id_col, time_col, value_col = (self.t_file.text(), auto(self.t_id),
                                             auto(self.t_time), auto(self.t_value))
        id_from, pattern = self.t_idfrom.currentData(), self.t_pattern.text() or "*"
        sample = self.t_sample.value()
        population = self.population()
        practice = self.synthetic.isChecked()

        def work(report):
            from .store import Store
            from .weerspoor import (grid_from, investigate, load_hourly, read_series_source,
                                    utc_hours)
            report(0.0, "weerreeksen lezen")
            series = read_series_source(path, id_from=id_from, id_col=id_col, time_col=time_col,
                                        value_col=value_col, pattern=pattern, max_homes=sample)
            if practice:        # the KNMI hours of the example ship with anonymate
                from . import voorbeeld
                hourly, grid = voorbeeld.hourly(), voorbeeld.grid()
            else:
                years = sorted({str(y) for y in
                                utc_hours(series["tijd"]).dt.year.dropna().astype(int)})
                store = Store.open()
                hourly, grid = load_hourly(store, years), grid_from(store, population)
            return investigate(series, hourly, grid, id_col="woning", time_col="tijd",
                               value_col="waarde",
                               progress=Voortgang(None, report, lo=0.2).callback())
        self._run(work, self._show_trace, self.weer_bar)

    def _show_trace(self, found) -> None:
        key = self.t_key.currentText()
        df, self.weather_tolerance, summary = apply_trace(self.df, key, found, self.population)
        self.df = self.current_df = df
        self.assessment = None
        self._add_column_rows(summary["added"])
        self.w_status.setText(summary["status"])
        if "verdict" in summary:
            notes = summary["notes"]
            self.cell_title.setText("Wat het weer verraadt")
            self.cell_text.setTextFormat(Qt.RichText)
            extra = "".join(f"<br>• {n}" for n in notes[:8])
            more = f"<br>… en nog {len(notes) - 8}" if len(notes) > 8 else ""
            self.cell_text.setText(f"<b>Conclusie.</b> {summary['verdict']}<br><br>"
                                   f"<b>Advies.</b> {summary['advice']}"
                                   + (f"<br><br><b>Bevindingen.</b>{extra}{more}" if notes
                                      else ""))
        self._update_dataset_cells()
        self._refresh_rail()

    def _weather_view(self) -> None:
        import h3
        level = self.w_level.value()
        edge = h3.average_hexagon_edge_length(level, unit="km")
        area = h3.average_hexagon_area(level, unit="km^2")
        self.w_level_note.setText(
            f"Niveau {level}: cellen van gemiddeld {area:,.0f} km² (rand {edge:.1f} km). "
            .replace(",", ".") + ("Advies: niveau 5 met σ ≈ 10 km; zonder ruis is niveau 5 te "
                                  "herkenbaar." if level >= 5 else ""))
        on = self.w_h3.isChecked()
        for w in (self.w_level, self.w_sigma, self.w_count_noise):
            w.setEnabled(on)
        self.map.mode = "h3" if on else ("knmi" if self.w_station.isChecked() else "none")
        self.map.level, self.map.sigma = level, float(self.w_sigma.value())
        if self.map.selected and h3.get_resolution(self.map.selected) != level:
            self.map.selected = None
        self._update_dataset_cells()
        self.map.update()
        self._uhi_source_note()

    def _uhi_source_note(self) -> None:
        """Say where the UHI comes from, without loading a population just for this."""
        pop = self._population if self.population_factory is None else None
        if pop is None and self.population_factory is None and self.synthetic.isChecked() \
                and _practice_cache:
            pop = _practice_cache[0]
        if pop is not None and "uhi__degC" in pop.columns and "postcode6__str" in pop.columns:
            text = "Bron: " + UHI_FROM_POPULATION + ". Een eigen bestand hieronder is optioneel."
        else:
            text = ("Bron: de UHI uit de populatie, als die er is; anders een eigen bestand "
                    "(per postcode: pc6 en uhi).")
        self.w_uhi_bron.setText(text)

    def _region_changed(self, *_args) -> None:
        self._map_data = None
        if hasattr(self, "map"):
            self.map.data = None
            self.map.update()
        self._refresh_rail()

    def _scope(self, population):
        return merge_scope(self._region_scope(), self.scope.text(), population)

    def _ensure_map(self) -> None:
        if self._map_data is not None or not hasattr(self, "map"):
            return
        try:
            population = self.population(aanbieden=False)
        except Exception as e:  # noqa: BLE001 (no population yet: say so on the map)
            self.cell_text.setText(f"Geen populatie: {e}")
            return
        if not available(population):
            self.map.data = None
            self.map.update()
            return
        scope = self._scope(population)
        if not scope.is_everything():
            population = population.within(scope)
        stations = None
        try:
            from .store import Store
            stations = pd.read_parquet(Store.open().raw / "knmi_stations.parquet")
        except Exception:  # noqa: BLE001 (stations are a nicety on the map)
            stations = None
        if stations is None or self.synthetic.isChecked():
            from . import voorbeeld
            stations = voorbeeld.stations()
        local = _local_maps()
        borders = border_rings(local)
        land = land_layer(local)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._map_data = ScopedMapData(population, stations, borders, land)
        finally:
            QApplication.restoreOverrideCursor()
        self.map.data = self._map_data
        self._weather_view()

    def _choose_uhi(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "UHI per postcode", "",
                                              "Data (*.csv *.parquet)")
        if path:
            self.w_uhi_file.setText(path)
            self.w_uhi.setChecked(True)

    def _locations(self, progress=None) -> pd.DataFrame:
        """lat, lon (and postcode6 when linked) per record, from the chosen source."""
        gps = self.w_source.currentData() == "gps"
        return locations(self.df, self.population() if not gps else None,
                         source="gps" if gps else "koppel", link_cols=self.koppel.text(),
                         gps=(self.w_lat.currentText(), self.w_lon.currentText()),
                         progress=progress)

    def apply_weather(self) -> None:
        """Add the weather location (and UHI) as published columns; hide the source."""
        if self.w_none.isChecked() and not self.w_uhi.isChecked():
            self.w_status.setText("Niets toe te voegen: kies een weerlocatie of UHI.")
            return
        self.weer_bar.start("weerlocatie toevoegen")
        try:
            self._apply_weather()
        finally:
            self.weer_bar.stop()

    def _apply_weather(self) -> None:
        from .voortgang import monotoon
        pump = monotoon(self.weer_bar.pump)      # the work runs here: keep the window painting
        vg = Voortgang(None, pump)
        try:
            loc = self._locations(vg.stage(0.0, 0.3).callback())
        except ValueError as e:
            self._failed(str(e))
            return
        method = "h3" if self.w_h3.isChecked() else ("knmi" if self.w_station.isChecked()
                                                    else None)
        if method == "h3" and self.weather_seed is None:
            import secrets
            self.weather_seed = secrets.randbits(32)
        try:
            df, added, tolerance = add_weather(
                self.df, self.population() if method == "knmi" else None, method=method,
                level=self.w_level.value(), sigma=float(self.w_sigma.value()),
                seed=self.weather_seed, count_noise=self.w_count_noise.isChecked(),
                locations=loc, source=self.w_source.currentData(),
                link_cols=self.koppel.text(), progress=vg.stage(0.3, 0.9).callback())
        except ValueError as e:
            self._failed(str(e))
            return
        if tolerance is not None:
            self.weather_tolerance = tolerance
        if self.w_uhi.isChecked():
            try:
                if self.w_uhi_file.text().strip():
                    table = read_uhi(self.w_uhi_file.text())
                    self.uhi_path = self.w_uhi_file.text()
                else:
                    frame = uhi_from_population(self.population())
                    if frame is None:
                        raise ValueError("de populatie heeft geen UHI: kies een UHI-bestand "
                                         "(per postcode: pc6 en uhi)")
                    table = uhi_table(frame)
                    self.uhi_path = None
            except ValueError as e:
                self._failed(str(e))
                return
            vg.set(0.9, "UHI per woning bepalen")
            df = add_uhi(df, loc, table, float(self.w_uhi_step.value()))
            added[UHI] = "uhi"
        vg.set(1.0)
        self.df = self.current_df = df
        self.assessment = None
        self._add_column_rows(added)
        self._update_dataset_cells()
        n = int(loc["lat"].notna().sum())
        self.w_status.setText(f"Toegevoegd: {', '.join(added) or 'niets'} (locatie gevonden voor "
                              f"{n} van {len(df)} records). De bronkolommen worden weggelaten.")
        self._refresh_rail()

    def _add_column_rows(self, added: dict[str, str]) -> None:
        """Show the new columns in step 3 with their role, and mark the source as direct."""
        source = ([self.w_lat.currentText(), self.w_lon.currentText()]
                  if self.w_source.currentData() == "gps" else [])
        for i in reversed(range(self.columns.rowCount())):
            if self.columns.item(i, 0).text() in (WEATHER_H3, WEATHER_STATION, UHI):
                self.columns.removeRow(i)
            elif self.columns.item(i, 0).text() in source:
                self.columns.cellWidget(i, 2).setCurrentText(DIRECT)
        for col, qid in added.items():
            i = self.columns.rowCount()
            self.columns.insertRow(i)
            self.columns.setItem(i, 0, QTableWidgetItem(col))
            self.columns.setItem(i, 1, QTableWidgetItem(f"weerlocatie: {qid}"))
            combo = QComboBox()
            combo.addItems([NO_QID, DIRECT] + list(CATALOGUE))
            combo.setCurrentText(qid)
            self.columns.setCellWidget(i, 2, combo)
            self.columns.setItem(i, 3, QTableWidgetItem(""))
            self.columns.setItem(i, 4, QTableWidgetItem("toegevoegd in stap 5"))

    def _update_dataset_cells(self) -> None:
        if hasattr(self, "map_band"):
            band = weather_band(self.df, self.map.mode)
            self.map_band.setText(band or "")
            self.map_band.setVisible(band is not None)
        if not hasattr(self, "map") or self.df is None or WEATHER_H3 not in self.df.columns:
            if hasattr(self, "map"):
                self.map.dataset_cells = {}
            return
        import h3
        cells = self.df[WEATHER_H3].dropna()
        level = self.w_level.value()
        cells = cells[[h3.get_resolution(c) == level for c in cells]]
        self.map.dataset_cells = cells.value_counts().to_dict()

    def _cell_clicked(self, lat: float, lng: float) -> None:
        import h3
        if self._map_data is None:
            return
        if self.w_station.isChecked():
            station, count = self._map_data.station_at(lat, lng)
            if station is None:
                return
            name = self._map_data.station_name(station)
            self.cell_title.setText(f"KNMI-station {name}")
            in_data = int((self.df[WEATHER_STATION] == station).sum()) \
                if self.df is not None and WEATHER_STATION in self.df.columns else None
            self.cell_text.setTextFormat(Qt.RichText)
            self.cell_text.setText(html(station_text(count, in_data)))
            return
        if not self.w_h3.isChecked():
            return
        cell = h3.latlng_to_cell(lat, lng, self.w_level.value())
        self.map.selected = cell
        self.map.heat = {}
        self.map.update()
        self.cell_title.setText("Bezig met rekenen…")
        self.cell_text.setText("Waar kan een woning in deze cel werkelijk liggen? Dat wordt nu "
                               "uitgerekend.")
        self.map_busy.start("waar de woning kan liggen uitrekenen")
        sigma = float(self.w_sigma.value())
        data = self._map_data
        thread = QThread(self)
        worker = Worker(lambda report: data.cell_stats(cell, sigma, report))
        worker.progress.connect(self._cell_progress)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # bound methods of the window: Qt then runs them in the window's (main) thread
        self._pending_cell = cell
        worker.done.connect(self._cell_done)
        worker.failed.connect(self._cell_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread._worker = worker
        self._threads.append(thread)
        thread.start()

    def _cell_progress(self, fraction, text: str) -> None:
        self.map_busy.report(fraction, text)

    def _cell_done(self, stats: dict) -> None:
        self._show_cell(stats.get("cel"), stats)

    def _cell_failed(self, message: str) -> None:
        self.map_busy.stop()
        self._failed(message)

    def _show_cell(self, cell: str, stats: dict) -> None:
        self.map_busy.stop()
        if self.map.selected != cell:          # another cell was clicked meanwhile
            return
        self.map.heat = stats.get("heat", {})
        import h3
        la, lo = h3.cell_to_latlng(cell)
        edge = h3.average_hexagon_edge_length(h3.get_resolution(cell), unit="km")
        self.map.focus(la, lo, max(8 * edge, 6 * float(self.w_sigma.value())))
        sigma = self.w_sigma.value()
        zones, other = weather_zones(self.df, stats["niveau"])
        in_dataset = None if zones is None else zones.get(cell, 0)
        card = cell_text(stats, stats["niveau"], sigma, Threshold(round(self.p.value(), 2)).k,
                         land_share=self._map_data.land_share(cell), in_dataset=in_dataset,
                         other_levels=other)
        self.cell_title.setText(card["title"])
        self.cell_text.setTextFormat(Qt.RichText)
        self.cell_text.setText(cell_html(card))

    def _page_attacker(self) -> QWidget:
        page, lay = self._page(6, "aanvaller en populatie", "Wie probeert het, en tussen welke "
                               "woningen?", "De toets telt voor elke woning hoeveel woningen in "
                               "Nederland dezelfde gepubliceerde kenmerken hebben, voor een "
                               "aanvaller met de kennis die je hier kiest.")
        self.pop_card, pc = _card()
        pc.addWidget(_label("Populatie", "h2"))
        self.pop_regel = _label("", "note", wrap=True)
        pc.addWidget(self.pop_regel)
        prow = QHBoxLayout()
        self.pop_btn = QPushButton("Populatie opbouwen…")
        self.pop_btn.clicked.connect(self.opbouw_openen)
        prow.addWidget(self.pop_btn)
        prow.addStretch(1)
        pc.addLayout(prow)
        lay.addWidget(self.pop_card)
        card, cl = _card()
        form = QFormLayout()
        self.scenario = QComboBox()
        self.scenario.addItem("openbare registers (BAG, EP-online)", "register")
        self.scenario.addItem("+ zichtbaar van buitenaf", "zichtbaar")
        self.scenario.addItem("+ insiderkennis (installateur, leverancier, buren)", "insider")
        form.addRow("aanvaller weet", self.scenario)
        self.scope = QLineEdit()
        self.scope.setPlaceholderText("bv.  gemeente=Zwolle,Deventer; bouwjaar=1900-1989; "
                                      "woningtype!=appartement")
        form.addRow("populatie-afbakening", self.scope)
        # the practice mode: switched on and off from step 1 and the rail, never here
        self.synthetic = QCheckBox("oefenmodus", self)
        self.synthetic.hide()
        self.synthetic.toggled.connect(self._synthetic_changed)
        cl.addLayout(form)
        lay.addWidget(card)
        row = QHBoxLayout()
        row.addStretch(1)
        self.assess_btn = _primary("Toetsen")
        self.assess_btn.clicked.connect(self.run_assess)
        row.addWidget(self.assess_btn)
        lay.addLayout(row)
        lay.addStretch(1)
        return page

    def _page_outcome(self) -> QWidget:
        page, lay = self._page(7, "uitkomst", "Nog niet getoetst", "")
        self.outcome_title = page.findChildren(QLabel, "h1")[0]
        buttons = QHBoxLayout()
        self.explore_btn = QPushButton("Afronding verkennen")
        self.explore_btn.clicked.connect(self.run_explore)
        self.suggest_btn = QPushButton("Generalisaties zoeken")
        self.suggest_btn.clicked.connect(self.run_suggest)
        self.save_btn = _primary("Opslaan…")
        self.save_btn.clicked.connect(self.save)
        self.adopt_btn = QPushButton("Overnemen")
        self.adopt_btn.setToolTip("Neem de gekozen generalisatie of afronding over en toets opnieuw")
        self.adopt_btn.clicked.connect(self.adopt)
        self.adopt_btn.setEnabled(False)
        self.verken_standaard = QCheckBox("standaardrooster")
        self.verken_standaard.setToolTip(
            "Aan: H 10/25, C 1.000/2.500, A_sol 1/2/5 en A_inf 25/50/100, zoals --verken "
            "standaard op de opdrachtregel. Uit: rond de afrondstappen van stap 4 (de helft, "
            "dezelfde, twee en vier keer).")
        buttons.addWidget(self.explore_btn)
        buttons.addWidget(self.verken_standaard)
        buttons.addWidget(self.suggest_btn)
        self.target_spin = QSpinBox()
        self.target_spin.setRange(50, 100)
        self.target_spin.setSingleStep(1)
        self.target_spin.setSuffix("%")
        self.target_spin.setValue(round(100 * TARGET_SHARE))
        self.target_spin.setToolTip("Het aandeel woningen dat publiceerbaar moet zijn: de "
                                    "zoektocht stopt zodra dat is bereikt.")
        self.target_spin.valueChanged.connect(self._target_changed)
        buttons.addWidget(_label("doel", "note"))
        buttons.addWidget(self.target_spin)
        buttons.addWidget(self.adopt_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.save_btn)
        lay.addLayout(buttons)
        self.target_count = _label("", "note")
        lay.addWidget(self.target_count)
        self._target_changed()
        self.bar = VoortgangBalk()
        self._active_bar = self.bar          # where the worker's progress goes
        lay.addWidget(self.bar)
        top = QHBoxLayout()
        stats_w = QWidget()
        stats = QGridLayout(stats_w)
        stats.setContentsMargins(0, 0, 0, 0)
        stats.setSpacing(8)
        stats_w.setFixedWidth(380)
        self.stat_values = {}
        for key, text in (("ok", "publiceerbaar"), ("risk", "niet publiceren"),
                          ("k", "gelijke woningen, mediaan"), ("bits", "nog te raden, mediaan")):
            card, cl = _card()
            cl.addWidget(_label(text, "statLabel"))
            value = _label(DASH, "big")
            value.setEnabled(False)               # greyed: nothing assessed yet
            cl.addWidget(value)
            self.stat_values[key] = value
            cl.setContentsMargins(12, 8, 12, 8)
            cl.setSpacing(2)
            stats.addWidget(card, len(self.stat_values) // 3, (len(self.stat_values) - 1) % 2)
        top.addWidget(stats_w)
        bits_card, bl = _card()
        bl.addWidget(_label("Wie is het? Wat de kenmerken prijsgeven", "h2", wrap=True))
        self.bits_note = _label("", "note", wrap=True)
        bl.addWidget(self.bits_note)
        self.bits_bar = BitsBar()
        bl.addWidget(self.bits_bar)
        top.addWidget(bits_card, 1)
        lay.addLayout(top)

        self.tabs = QTabWidget()
        records = QWidget()
        rl = QHBoxLayout(records)
        rl.setContentsMargins(0, 8, 0, 0)
        self.results = QTableWidget(0, 0)
        self.results.verticalHeader().setVisible(False)
        self.results.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results.setMinimumHeight(170)
        self.results.itemSelectionChanged.connect(self._show_record)
        rl.addWidget(self.results, 1)
        side = QVBoxLayout()
        hist_card, hl = _card()
        hl.addWidget(_label("Hoeveel gelijke woningen?", "h2"))
        self.k_hist = KHistogram()
        hl.addWidget(self.k_hist)
        self.hist_note = _label("", "note", wrap=True)
        hl.addWidget(self.hist_note)
        hist_card.setFixedWidth(250)
        top.addWidget(hist_card)
        self.record_card, rc = _card()
        self.record_title = _label("Kies een woning in de tabel", "h2", wrap=True)
        rc.addWidget(self.record_title)
        self.record_houses = HouseArray(22)
        rc.addWidget(self.record_houses)
        self.record_text = _label("", "note", wrap=True)
        rc.addWidget(self.record_text)
        side.addWidget(self.record_card)
        side.addStretch(1)
        side_w = QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(330)
        rl.addWidget(side_w)
        self.tabs.addTab(records, "Woningen")
        weigh = QWidget()
        wl = QVBoxLayout(weigh)
        wl.setContentsMargins(0, 8, 0, 0)
        wl.addWidget(_label("De norm ligt vast. Elke stap maakt één kenmerk grover: meer woningen "
                            "worden publiceerbaar, maar er gaat informatie verloren.", "note",
                            wrap=True))
        self.view_box = QComboBox()
        for v in TRADEOFF_VIEWS:
            self.view_box.addItem(TRADEOFF_TEXTS[v]["toggle"], v)
        self.view_box.currentIndexChanged.connect(self._view_chosen)
        vrow = QHBoxLayout()
        vrow.addWidget(_label("weergave", "note"))
        vrow.addWidget(self.view_box)
        vrow.addStretch(1)
        wl.addLayout(vrow)
        wrow = QHBoxLayout()
        self.tradeoff = TradeoffChart()
        saved = tradeoff_view(str(QSettings("anonymate", "anonymate").value("afweging/weergave", "")))
        self.view_box.blockSignals(True)
        self.view_box.setCurrentIndex(TRADEOFF_VIEWS.index(saved))
        self.view_box.blockSignals(False)
        self.tradeoff.set_view(saved)
        wrow.addWidget(self.tradeoff, 1)
        self.gen_steps = QListWidget()
        self.gen_steps.setFixedWidth(300)
        self.gen_steps.currentRowChanged.connect(self._gen_step_chosen)
        wrow.addWidget(self.gen_steps)
        wl.addLayout(wrow, 1)
        self.target_note = _label(target_note(), "note", wrap=True)
        wl.addWidget(self.target_note)
        wl.addWidget(_label(LOSS_NOTE, "note", wrap=True))
        wl.addWidget(_label("Kies een stap in de lijst en klik 'Overnemen': de dataset krijgt die "
                            "generalisatie, en wordt opnieuw getoetst.", "note", wrap=True))
        self.tabs.addTab(weigh, "Afweging")
        details = QWidget()
        dl = QVBoxLayout(details)
        dl.setContentsMargins(0, 8, 0, 0)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        dl.addWidget(self.summary)
        self.tabs.addTab(details, "Toelichting")
        lay.addWidget(self.tabs, 1)

        return page

    # --- navigation ---------------------------------------------------------------------------
    def go(self, index: int) -> None:
        self.step_list.setCurrentRow(index)

    def _row_changed(self, index: int) -> None:
        """The rail or a "Verder" button moved to step ``index``. Past step 2 only with a locked
        norm: otherwise stay on (or return to) the norm, or on step 1 while no dataset is open."""
        if index < 0:
            return
        if index >= STEPS.index("Kolommen") and not self.norm_locked:
            self.step_list.setCurrentRow(1 if self.df is not None else 0)
            return
        self.pages.setCurrentIndex(index)
        self._step_changed(index)
        if index == STEPS.index("Weerlocatie"):
            self._ensure_map()
        if index == STEPS.index("Aanvaller"):
            self._refresh_pop_card()

    def _step_changed(self, index: int) -> None:
        if hasattr(self, "target_count"):
            self._target_changed()
        if self.df is not None:
            self._furthest = max(getattr(self, "_furthest", 0), index)
        self._refresh_rail()

    def _refresh_rail(self) -> None:
        t = Threshold(round(self.p.value(), 2))
        n_qid = sum(1 for v in self.mapping().values() if v not in ("geen", "direct")) \
            if self.df is not None else 0
        n_direct = sum(1 for v in self.mapping().values() if v == "direct") \
            if self.df is not None else 0
        subs = [self.path.name if self.path else "nog niet gekozen",
                f"p {_nl(t.p, 2)} · k ≥ {t.k}" + (" · vast" if self.norm_locked else ""),
                f"{n_qid} kenmerken, {n_direct} weglaten" if self.df is not None else "",
                "aan" if self.sig_on.isChecked() else "niet gebruikt",
                self._weather_sub(),
                self.scenario.currentText().split(" (")[0],
                self._outcome_sub()]
        passed = lambda i: self.df is not None and getattr(self, "_furthest", 0) > i  # noqa: E731
        done = [self.df is not None, self.norm_locked, passed(2), passed(3), passed(4),
                passed(5) or self.assessment is not None, self.assessment is not None]
        for i, (name, sub) in enumerate(zip(STEPS, subs)):
            mark = f"{i + 1} ✓" if done[i] else f"{i + 1}   "
            item = self.step_list.item(i)
            item.setText(f"{mark}  {name}\n        {sub}")
            item.setForeground(QColor("#FFFFFF" if done[i] else "#C9D2DE"))
            # past the norm only with a locked norm (see _row_changed)
            enabled = i < 2 or self.norm_locked
            flags = item.flags() | Qt.ItemIsEnabled if enabled else item.flags() & ~Qt.ItemIsEnabled
            item.setFlags(flags)
        if self.df is not None:
            self.dataset_card.setText(f"<b>{self.path.name}</b><br>{len(self.df)} woningen · "
                                      f"{len(self.df.columns)} kolommen<br>regio: "
                                      f"{self._region_text()}"
                                      + (f"<br>norm p = {_nl(t.p, 2)} · k ≥ {t.k}"
                                         if self.norm_locked else ""))

    def _synthetic_changed(self, on: bool) -> None:
        if on and self.sig_on.isChecked():
            self.sig_on.setChecked(False)
        self.sig_on.setEnabled(not on)
        self.sig_on.setToolTip("Niet in de oefenmodus: het verzonnen Nederland heeft geen "
                               "signaturen." if on else "")
        self.practice_banner.setVisible(on)
        self._refresh_pop_card()
        self.assessment = self.steps = None
        self._region_changed()

    def start_practice(self) -> None:
        """Practice mode: the example dwellings and weather, against a made-up Netherlands."""
        from . import voorbeeld
        self.synthetic.setChecked(True)
        # making the made-up Netherlands takes a while: start now, in the background
        threading.Thread(target=_practice_population, daemon=True).start()
        self.load(voorbeeld.WONINGEN)
        self._series_chosen(str(voorbeeld.WEER))
        self.t_key.setCurrentText(voorbeeld.KEY)

    def stop_practice(self) -> None:
        """Back to the real population; the example stays open until another dataset is."""
        self.synthetic.setChecked(False)
        self.go(0)
        self.file_label.setText("Oefenmodus gestopt. Open nu je eigen dataset.")

    def _region_text(self) -> str:
        return region_text(self._region_scope())

    def _region_scope(self) -> dict:
        return region_scope(self.region_all.isChecked(),
                            [n for n, b in self.region_boxes.items() if b.isChecked()],
                            self.region_municipalities.text())

    def _weather_sub(self) -> str:
        if self.df is None:
            return ""
        parts = []
        if WEATHER_H3 in self.df.columns:
            parts.append(f"H3 niveau {self.w_level.value()}, σ {self.w_sigma.value()} km")
        elif WEATHER_STATION in self.df.columns:
            parts.append("KNMI-station")
        if UHI in self.df.columns:
            parts.append("UHI")
        return " + ".join(parts) if parts else "niet toegevoegd"

    def _outcome_sub(self) -> str:
        if self.assessment is None:
            return "nog niet getoetst"
        s = self.assessment.summary()
        return f"{s['ok']} van {s['records']} publiceerbaar"

    # -------------------------------------------------------------------------------------------
    def _update_k(self) -> None:
        t = Threshold(round(self.p.value(), 2))
        self.k_label.setText(f"Elke woning in de dataset moet lijken op minstens {t.k} woningen "
                             f"in de populatie: wie er één zoekt, heeft hooguit 1 op {t.k} kans. "
                             f"Van zo'n groep mag hooguit {t.p:.0%} in de dataset zitten "
                             f"(anders verraadt de groep dat een woning meedoet: "
                             f"{DEELNAME}).")
        self.k_big.setText(f"k ≥ {t.k}")
        self.norm_houses.set(min(t.k, 20), min(t.k, 20))
        if hasattr(self, "step_list"):
            self._refresh_rail()

    def lock_and_continue(self) -> None:
        """The button of step 2: fix the norm (once), then go to step 3."""
        if self.df is None:
            return
        if not self.norm_locked:
            self.lock_norm()
        self.go(STEPS.index("Kolommen"))

    def lock_norm(self) -> None:
        """Fix the norm. It stays fixed until a new dataset is opened, so it cannot be tuned to
        the outcome."""
        self.norm_locked = True
        self.p.setEnabled(False)
        self.p_slider.setEnabled(False)
        self.lock_btn.setText(LOCKED_TEXT)
        self.lock_btn.setEnabled(self.df is not None)
        t = Threshold(round(self.p.value(), 2))
        self.lock_label.setText(f"Vastgelegd: p = {t.p:g} (k ≥ {t.k}); blijft vast voor deze "
                                "dataset.")
        self._set_busy(False)
        self._refresh_rail()

    def _set_busy(self, busy: bool) -> None:
        has = self.df is not None
        ready = has and self.norm_locked and not busy
        self.assess_btn.setEnabled(ready)
        self.explore_btn.setEnabled(ready)
        self.suggest_btn.setEnabled(ready)
        self.save_btn.setEnabled(self.assessment is not None and not busy)
        self.open_btn.setEnabled(not busy)
        if busy:
            self.summary.setPlainText("bezig…")
            self.outcome_title.setText("Bezig met toetsen…")
            self._active_bar.start("aan het rekenen…")
        elif hasattr(self, "bar"):
            self._active_bar.stop()

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Dataset openen", "",
                                              "Data (*.csv *.xlsx *.xls *.parquet)")
        if path:
            if self.synthetic.isChecked():
                self.synthetic.setChecked(False)
            self.load(path)

    def load(self, path: str | Path) -> None:
        self.path = Path(path)
        self.df, derived = derive_h3_columns(read_dataset(self.path))
        self.current_df = self.df
        self.assessment = self.steps = None
        self.norm_locked = False  # a new dataset: fix the norm again before assessing
        self._furthest = 0
        self.p.setEnabled(True)
        self.p_slider.setEnabled(True)
        self.lock_btn.setText(LOCK_TEXT)
        self.lock_btn.setEnabled(True)
        self.lock_label.setText("nog niet vastgelegd: toetsen kan pas daarna")
        self.file_label.setText(f"{self.path.name}: {len(self.df)} records, "
                                f"{len(self.df.columns)} kolommen")
        found = detect(self.df)
        self.lezing_vast = {}
        self.columns.setRowCount(len(found))
        for i, d in enumerate(found):
            self.columns.setItem(i, 0, QTableWidgetItem(d.column))
            proposal = ROLE_LABELS[d.role] + (f": {d.qid}" if d.qid else "")
            self.columns.setItem(i, 1, QTableWidgetItem(proposal))
            combo = QComboBox()
            combo.addItems([NO_QID, DIRECT] + list(CATALOGUE))
            if d.column in derived:
                combo.setCurrentText(derived[d.column] if derived[d.column] != "geen" else NO_QID)
            elif d.role == Role.DIRECT:
                combo.setCurrentText(DIRECT)
            elif d.role in (Role.QID, Role.IMPLICIT_LOCATION) and d.qid:
                combo.setCurrentText(d.qid)
            combo.currentTextChanged.connect(lambda _t: self._refresh_rail())
            combo.currentTextChanged.connect(lambda _t, c=d.column: self._refresh_lezing(c))
            self.columns.setCellWidget(i, 2, combo)
            self.columns.setItem(i, 4, QTableWidgetItem(d.reason))
            self._refresh_lezing(d.column)
        numeric = numeric_columns(self.df)
        for box, guess in zip((self.w_lat, self.w_lon), guess_gps(numeric)):
            box.clear()
            box.addItems([""] + numeric)
            box.setCurrentText(guess)
        has_gps = bool(self.w_lat.currentText() and self.w_lon.currentText())
        self.w_source.setCurrentIndex(1 if has_gps else 0)
        self.koppel.setText(",".join(link_columns(found)))
        # with a way to find the dwelling, propose the recommended weather location
        (self.w_h3 if has_gps or self.koppel.text() else self.w_none).setChecked(True)
        self.weather_seed, self.weather_tolerance, self.uhi_path = None, 0.0, None
        self.w_status.setText("")
        self._update_dataset_cells()
        self._set_busy(False)
        self._refresh_rail()
        self.go(1)

    def _row_of(self, column: str) -> int | None:
        for i in range(self.columns.rowCount()):
            if self.columns.item(i, 0) and self.columns.item(i, 0).text() == column:
                return i
        return None

    def _refresh_lezing(self, column: str) -> None:
        """The reading of a numeric column (kladbloknotitie 17): a choice when the values look
        rounded or classes share a boundary, otherwise "zoals gepubliceerd"."""
        i = self._row_of(column)
        if i is None or self.df is None:
            return
        self.columns.removeCellWidget(i, 3)
        key = self.columns.cellWidget(i, 2).currentText()
        spec = CATALOGUE.get(key)
        if spec is None or spec.kind != Kind.NUMERIC or column not in self.df.columns:
            self.columns.setItem(i, 3, QTableWidgetItem(""))
            return
        if column in self.lezing_vast:
            item = QTableWidgetItem((self.lezing_vast[column] or Lezing()).tekst())
            item.setToolTip("overgenomen met de gekozen generalisatiestap")
            self.columns.setItem(i, 3, item)
            return
        o = onderzoek(self.df[column], spec)
        if not o.iets_te_melden:
            self.columns.setItem(i, 3, QTableWidgetItem(Lezing().tekst()))
            return
        self.columns.setItem(i, 3, QTableWidgetItem(""))
        box = QComboBox()
        first = o.voorstel() or Lezing()
        for lz in [first] + o.alternatieven(first):
            box.addItem(lz.tekst(), lz)
        box.setToolTip("\n\n".join(o.meldingen()))
        self.columns.setCellWidget(i, 3, box)

    def lezing(self, column: str):
        """The chosen reading of ``column``, or None when its values are read as published."""
        if column in self.lezing_vast:
            return self.lezing_vast[column]
        i = self._row_of(column)
        box = self.columns.cellWidget(i, 3) if i is not None else None
        lz = box.currentData() if isinstance(box, QComboBox) else None
        return None if lz is None or lz.exact else lz

    def mapping(self) -> dict[str, str]:
        out = {}
        for i in range(self.columns.rowCount()):
            col = self.columns.item(i, 0).text()
            choice = self.columns.cellWidget(i, 2).currentText()
            out[col] = {NO_QID: "geen", DIRECT: "direct"}.get(choice, choice)
        return out

    def population(self, aanbieden: bool = True) -> Population:
        """The population; without one on this computer, ``aanbieden`` opens the guidance to
        build it (off where merely looking would make the dialog pop up, like the map)."""
        if self.population_factory is not None:
            return self.population_factory()
        if self.synthetic.isChecked():
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                return _practice_population()
            finally:
                QApplication.restoreOverrideCursor()
        if self._population is None:
            from .store import Store
            store = Store.open()
            try:
                self._population = store.population()
            except FileNotFoundError:       # no population yet: offer to build it, then go on
                if not aanbieden or not self.opbouw_openen():
                    raise
                self._population = store.population()
        return self._population

    def _refresh_pop_card(self) -> None:
        """The "Populatie" card of step 6: one line about what is on this computer and the button
        to build it. In the practice mode the button is off, with why; not shown at all with a
        population of the caller's own."""
        if not hasattr(self, "pop_card"):
            return
        show = self.population_factory is None
        self.pop_card.setVisible(show)
        if not show:
            return
        practice = self.synthetic.isChecked()
        self.pop_btn.setEnabled(not practice)
        if practice:
            self.pop_regel.setText(OEFEN_POPULATIE)
            self.pop_btn.setText("Populatie opbouwen…")
            return
        from .store import Store
        t = opbouw.toestand(Store.open())
        self.pop_regel.setText(opbouw.toestand_regel(t))
        self.pop_btn.setText("EP-online toevoegen…" if t.populatie and not t.populatie_met_labels
                             else "Populatie opbouwen…")

    def opbouw_openen(self) -> bool:
        """The guidance for building the population; True when it was built (the population is
        then loaded again)."""
        from .store import Store
        dialog = PopulatieOpbouw(Store.open(), self)
        built = bool(dialog.exec())
        if built:
            self._population = None
        self._refresh_pop_card()
        return built

    def _with_uhi(self, population):
        """The population with a UHI column from the chosen file, when UHI is published."""
        if self.df is None or UHI not in self.df.columns or "uhi__degC" in population.columns \
                or not self.uhi_path or "postcode6__str" not in population.columns:
            return population
        return population_with_uhi(population, read_uhi_frame(self.uhi_path))

    def _link_kwargs(self) -> dict:
        return link_kwargs(self.koppel.text(), self.df.columns)

    def _plan(self):
        from .publicatie import Plan
        steps = {o: b.value() for o, b in self.sig_steps.items() if b.value() > 0}
        return Plan(self.sig_method.currentData(), steps)

    def _inputs(self):
        mapping = self.mapping()
        if self.sig_on.isChecked():
            link_cols = set(self._link_kwargs().values())
            for c in link_cols:
                mapping[c] = "direct"
            for i in range(self.columns.rowCount()):  # show it too
                if self.columns.item(i, 0).text() in link_cols:
                    self.columns.cellWidget(i, 2).setCurrentText(DIRECT)
        qids, direct = qids_from(self.df, mapping, auto=False)
        qids = [replace(q, lezing=self.lezing(q.column)) for q in qids]
        if self.weather_tolerance:
            from .risk import QidColumn
            qids = [QidColumn(q.column, q.spec, self.weather_tolerance)
                    if q.column == WEATHER_H3 else q for q in qids]
        threshold = Threshold(round(self.p.value(), 2))
        scenario = SCENARIOS[self.scenario.currentData()]
        population = self._with_uhi(self.population())
        scope = self._scope(population)
        if not scope.is_everything():
            population = population.within(scope)
        self._scoped_population = population
        return qids, direct, threshold, scenario, population

    def _run(self, fn, on_done, bar: "VoortgangBalk | None" = None) -> None:
        """Run ``fn`` (given a progress callback when it takes one) off the window's thread;
        the progress shows in ``bar`` (default: the one of step 7)."""
        self._active_bar = bar or self.bar
        self._set_busy(True)
        thread = QThread(self)
        worker = Worker(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(on_done)
        worker.failed.connect(self._failed)
        worker.progress.connect(self._on_progress)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(lambda: self._set_busy(False))
        thread._worker = worker  # keep a reference
        self._threads.append(thread)
        thread.start()

    def _failed(self, message: str) -> None:
        readable = _readable(message)
        self.summary.setPlainText(readable + ("\n\n(technisch: " + message + ")"
                                              if readable != message else ""))
        self.outcome_title.setText("Er ging iets mis")
        QMessageBox.warning(self, "anonymate", readable)

    # -------------------------------------------------------------------------------------------
    def run_assess(self) -> None:
        if not self.norm_locked:
            self._failed("Leg eerst de privacynorm vast (stap 2).")
            return
        try:
            self._run_assess()
        except (ValueError, FileNotFoundError) as e:     # no population, and none was built
            self._failed(str(e))

    def _signature_available(self, population) -> bool:
        return signature_available(population.columns, self.sig_method.currentData())

    def _run_assess(self) -> None:
        qids, direct, threshold, scenario, population = self._inputs()
        if self.sig_on.isChecked() and not self._signature_available(population):
            raise ValueError("De signatuur (stap 4) kan niet met deze populatie: die heeft geen "
                             "berekende signaturen" + (" (het verzonnen Nederland van de "
                             "oefenmodus heeft ze nooit)" if self.synthetic.isChecked() else
                             "; bouw ze met 'anonymate build --signaturen'") + ". Zet de "
                             "signatuur in stap 4 uit" + (", of stop met oefenen."
                             if self.synthetic.isChecked() else "."))
        df = self.df
        self.direct = direct
        self.steps = None
        with_sig = self.sig_on.isChecked()
        plan = self._plan() if with_sig else None
        link_kw = self._link_kwargs() if with_sig else {}

        def work(report):
            vg = Voortgang(None, report)
            data, all_qids = df, list(qids)
            if with_sig:
                from .publicatie import add_baseline
                vg.set(0.0, "signatuur bepalen")
                data, sig_qids, never = add_baseline(df, population, plan, **link_kw)
                all_qids += sig_qids
                self.direct = sorted(set(self.direct) | set(never))
            vg.set(0.3, "woningen toetsen")
            a = assess(data, all_qids, population, threshold, scenario)
            vg.set(0.6, "andere lezingen van de kolommen")
            onderzoeken = {q.column: onderzoek(df[q.column], q.spec) for q in qids
                           if q.spec.kind == Kind.NUMERIC and q.column not in self.lezing_vast}
            rows = gevoeligheid(data, all_qids, population, threshold, scenario, onderzoeken,
                                progress=vg.stage(0.6, 0.9).callback())
            vg.set(0.9, "uitkomst opstellen")
            return data, a, _bits(data, a, population), rows
        self.go(6)
        self._run(work, self._show_assessment)

    def run_explore(self) -> None:
        if not self.norm_locked:
            self._failed("Leg eerst de privacynorm vast (stap 2).")
            return
        try:
            self._run_explore()
        except ValueError as e:
            self._failed(str(e))

    def _run_explore(self) -> None:
        """Rounding steps around the chosen ones: how many dwellings can be published at the
        fixed norm, and at what loss of precision."""
        if not self.sig_on.isChecked():
            self.summary.setPlainText("Afronding verkennen gaat over de adresgebaseerde "
                                      "signatuur: zet stap 4 aan.")
            self.tabs.setCurrentIndex(2)
            return
        qids, _, threshold, scenario, population = self._inputs()
        if not self._signature_available(population):
            raise ValueError("Afronding verkennen gaat over de signatuur, en die heeft deze "
                             "populatie niet. Gebruik de echte populatie met signaturen.")
        plan = self._plan()
        candidates = verken_rooster(plan.steps, self.verken_standaard.isChecked())
        link_kw = self._link_kwargs()
        df = self.df

        def work(report):
            from .publicatie import explore
            return explore(df, population, plan.method, candidates, threshold, qids, scenario,
                           progress=report, **link_kw)
        self.go(6)
        self._run(work, self._show_table)

    def _show_table(self, table) -> None:
        self.outcome_title.setText("Afronding verkend")
        self.summary.setPlainText(
            f"Afweging bij de vastgelegde norm p = {round(self.p.value(), 2):g}: per combinatie "
            "van afrondstappen hoeveel woningen gepubliceerd kunnen worden en hoeveel precisie "
            "dat kost. Kies, en zet de stappen in stap 4; woningen die de toets niet halen "
            "worden niet gepubliceerd.")
        self.results.setColumnCount(len(table.columns))
        self.results.setRowCount(len(table))
        self.results.setHorizontalHeaderLabels([_header(str(c)) for c in table.columns])
        for i, row in enumerate(table.itertuples(index=False)):
            for j, v in enumerate(row):
                text = (DASH if is_unknown(v) else str(int(v)) if isinstance(v, float)
                        and v.is_integer() else _g(v) if isinstance(v, float) else str(v))
                item = QTableWidgetItem(text)
                if text == DASH:
                    item.setToolTip(UNKNOWN_TIP)
                self.results.setItem(i, j, item)
        _align_numeric(self.results)
        self.results.resizeColumnsToContents()
        self._shown = None
        self._explored = table
        self._adopt_mode = "afronding"
        self.adopt_btn.setEnabled(True)
        self.adopt_btn.setText("Afronding overnemen")
        if len(table):
            self.results.selectRow(0)
        self.tabs.setCurrentIndex(0)

    def run_suggest(self) -> None:
        if not self.norm_locked:
            self._failed("Leg eerst de privacynorm vast (stap 2).")
            return
        try:
            self._run_suggest()
        except ValueError as e:
            self._failed(str(e))

    def _run_suggest(self) -> None:
        qids, direct, threshold, scenario, population = self._inputs()
        df = self.df
        self.direct = direct
        share = self.target_spin.value() / 100
        self._steps_target = share

        def work(report):
            steps = suggest(df, qids, population, threshold, scenario, target_share=share,
                            progress=report)
            last = steps[-1]
            a = assess(last.df, last.qids, population, threshold, scenario)
            return last.df, a, _bits(last.df, a, population), steps
        self.go(6)
        self._run(work, self._show_suggestion)

    def _show_suggestion(self, result) -> None:
        df, a, bits, steps = result
        self.steps = steps
        self._show_assessment((df, a, bits))
        lines = ["", "Generalisatiestappen:"]
        rows = []
        for s in steps:
            r = s.row()
            lines.append(f"  {r['stap']}: {r['publiceerbaar_%']:.0f}% publiceerbaar, "
                         f"informatieverlies {r['informatieverlies']:.2f}")
            rows.append((str(r["stap"]).split(" / ")[0], float(r["publiceerbaar_%"]),
                         float(r["informatieverlies"])))
        self.summary.appendPlainText("\n".join(lines))
        share = getattr(self, "_steps_target", TARGET_SHARE)
        self.tradeoff.set(rows, 100 * share)
        self.target_note.setText(target_note(share))
        self.gen_steps.blockSignals(True)
        self.gen_steps.clear()
        for i, (label, pct, _loss) in enumerate(rows):
            self.gen_steps.addItem(f"{i}. {label} · {pct:.0f}%")
        self.gen_steps.setCurrentRow(len(rows) - 1)
        self.gen_steps.blockSignals(False)
        self._adopt_mode = "generalisatie"
        self.adopt_btn.setEnabled(len(rows) > 1)
        self.adopt_btn.setText("Generalisatie overnemen")
        self.outcome_title.setText(f"{a.summary()['ok']} van de {a.summary()['records']} "
                                   "woningen publiceerbaar, na generalisatie")
        self.tabs.setCurrentIndex(1)

    def _representativeness(self, df, a) -> list[str]:
        """What leaving out the risky records does to the published columns (notitie 7)."""
        drop = set(getattr(self, "direct", None) or [])
        cols = [c for c in df.columns if c not in drop]
        return representativeness_lines(df, a.ok, cols)

    def _set_stat(self, key: str, text: str, tip: str = "") -> None:
        """A tile of the outcome: an unknown figure is "–", greyed, with the reason as tooltip."""
        label = self.stat_values[key]
        label.setText(text)
        label.setEnabled(text != DASH)
        label.setToolTip(tip)

    def _show_assessment(self, result) -> None:
        df, a, bits, *rest = result
        self.lezing_rijen = rest[0] if rest else []
        self.assessment, self.current_df = a, df
        s = a.summary()
        n = s["records"] or 1
        text = [f"{s['ok']} van {s['records']} records publiceerbaar ({100 * s['ok'] / n:.0f}%), "
                f"{s['risico']} met risico, {s['geen_match']} zonder match in de populatie.",
                k_line(s),
                f"populatie: {s['populatie']:,} woningen ({s['afbakening']}); "
                f"bronnen: {s['snapshot']}"]
        n_out = s["records"] - s["ok"]
        if n_out:
            text.append(f"{n_out} woningen blijven te herleidbaar: die worden NIET opgenomen in "
                        "publiceerbaar.csv. Grover afronden of meer kenmerken grover maken kan "
                        "dat aantal verkleinen; de norm blijft staan.")
            if s["ok"]:
                text += self._representativeness(df, a)
        text += [f"let op: {w}" for w in a.warnings]
        for r in self.lezing_rijen:
            text.append(f"{r['kolom']} gelezen als: {r['lezing']}" + "".join(
                f"; met {alt['lezing']}: {alt['publiceerbaar']} publiceerbaar"
                for alt in r["alternatieven"]))
        self.summary.setPlainText("\n".join(text))

        self.outcome_title.setText(f"{s['ok']} van de {s['records']} woningen publiceerbaar")
        norm_k = s["k_drempel"]
        self.k_hist.set(list(a.records["k"]), norm_k)
        self.hist_note.setText(histogram_note(s["geen_match"]))
        median = None      # the remaining bits: unknown (not 0) without a match
        if bits is not None and bits[2].notna().any():
            median = float(bits[2].median())
        for key, (text, tip) in stat_tiles(s, median).items():
            self._set_stat(key, text, tip)
        if bits is not None:
            needed, parts, _remaining = bits
            self.bits_bar.set(needed, parts, median, math.log2(norm_k))
            self.bits_note.setText(bits_note(needed, s["populatie"], median))

        shown = df[[q.column for q in a.qids]].join(
            a.records[["k", "delta", "status", "redenen"]])
        self._shown = shown
        self.results.setColumnCount(len(shown.columns))
        self.results.setRowCount(len(shown))
        self.results.setHorizontalHeaderLabels([str(c) for c in shown.columns])
        for j, c in enumerate(shown.columns):
            if c in COLUMN_TIPS:
                self.results.horizontalHeaderItem(j).setToolTip(COLUMN_TIPS[c])
        status_col = list(shown.columns).index("status")
        names = [str(c) for c in shown.columns]
        for i, row in enumerate(shown.itertuples(index=False)):
            colour = QColor(STATUS_COLOURS.get(row[status_col], "#FFFFFF"))
            for j, v in enumerate(row):
                text, tip = table_cell(v, names[j], row[status_col])
                item = QTableWidgetItem(text)
                item.setBackground(colour)
                if tip:
                    item.setToolTip(tip)
                self.results.setItem(i, j, item)
        _align_numeric(self.results)
        self.results.resizeColumnsToContents()
        self._refresh_rail()
        self.tabs.setCurrentIndex(0)
        risky = [i for i, st in enumerate(shown["status"]) if st != Status.OK]
        if len(shown):
            first = risky[0] if risky else 0
            self.results.selectRow(first)
            self.results.scrollToItem(self.results.item(first, 0))

    def _on_progress(self, fraction, text) -> None:
        """Progress from the computation: fraction 0..1 (None: unknown) and text."""
        self._active_bar.report(fraction, text)

    def _target_changed(self, *_args) -> None:
        """The count under the target field: what the share means for the open dataset."""
        n = 0 if self.df is None else len(self.df)
        self.target_count.setText(target_count_text(n, self.target_spin.value() / 100))

    def _view_chosen(self, index: int) -> None:
        view = self.view_box.itemData(index)
        self.tradeoff.set_view(view)
        QSettings("anonymate", "anonymate").setValue("afweging/weergave", view)

    def _gen_step_chosen(self, index: int) -> None:
        if index >= 0:
            self.tradeoff.select(index)

    def adopt(self) -> None:
        """Take over the chosen generalisation (into the dataset) or rounding (into step 4), and
        assess again."""
        mode = getattr(self, "_adopt_mode", None)
        if mode == "generalisatie" and self.steps:
            i = self.gen_steps.currentRow()
            if i <= 0:
                self._failed("Kies in de lijst een stap na de uitgangssituatie.")
                return
            step = self.steps[i]
            self.df = self.current_df = step.df
            keys = {q.column: q.spec.key for q in step.qids}
            for q in step.qids:          # rewritten columns keep the reading the step used
                if not self.df[q.column].equals(self.steps[0].df[q.column]):
                    self.lezing_vast[q.column] = q.lezing
            for r in range(self.columns.rowCount()):
                col = self.columns.item(r, 0).text()
                if col in keys:
                    self.columns.cellWidget(r, 2).setCurrentText(keys[col])
                    self._refresh_lezing(col)
                    self.columns.setItem(r, 4, QTableWidgetItem(
                        f"gegeneraliseerd tot en met stap {i}"))
            self.summary.setPlainText(f"Overgenomen: stap {i} ({step.description}). De dataset is "
                                      "gegeneraliseerd; opnieuw getoetst.")
        elif mode == "afronding" and getattr(self, "_explored", None) is not None:
            rows = self.results.selectionModel().selectedRows()
            if not rows:
                self._failed("Kies in de tabel een regel met afrondstappen.")
                return
            chosen = self._explored.iloc[rows[0].row()]
            for output, box in self.sig_steps.items():
                box.setValue(float(chosen.get(f"stap_{output}", 0) or 0))
            self.summary.setPlainText("Overgenomen: de afrondstappen staan in stap 4; opnieuw "
                                      "getoetst.")
        else:
            return
        self.adopt_btn.setEnabled(False)
        self.run_assess()

    def _show_record(self) -> None:
        shown = getattr(self, "_shown", None)
        rows = self.results.selectionModel().selectedRows() if self.results.selectionModel() \
            else []
        if shown is None or not rows or self.assessment is None:
            return
        i = rows[0].row()
        rec = shown.iloc[i]
        norm_k = self.assessment.summary()["k_drempel"]
        k = rec["k"]
        k_int = 0 if pd.isna(k) else int(k)
        self.record_houses.set(*houses_for(k_int, norm_k))
        status = rec["status"]
        self.record_card.setObjectName("card" if status == Status.OK else "cardRisk")
        self.record_card.style().unpolish(self.record_card)
        self.record_card.style().polish(self.record_card)
        title, body = record_card(rec, k, norm_k, rec["delta"], status, index=i)
        self.record_title.setText(title)
        self.record_text.setText(body)

    def save(self) -> None:
        if self.assessment is None:
            return
        default = str(self.path.with_suffix("")) + "_anonymate" if self.path else ""
        out = QFileDialog.getExistingDirectory(self, "Uitvoermap kiezen", default)
        if not out:
            return
        write(out, self.current_df, self.assessment, drop_columns=self.direct, steps=self.steps,
              dataset_name=self.path.name if self.path else "dataset",
              population=getattr(self, "_scoped_population", None),
              target_share=getattr(self, "_steps_target", None) if self.steps else None,
              lezingen=getattr(self, "lezing_rijen", None))
        QMessageBox.information(
            self, "anonymate",
            f"Opgeslagen in {out}:\n\npubliceerbaar.csv: om te publiceren\n"
            "rapport.md en samenvatting.json: verantwoording\n"
            "rapport_per_record.csv: INTERN, niet publiceren")



def _local_maps():
    """The map layers of the local store ('anonymate ingest gebieden'), when it has any."""
    try:
        from .store import Store
        return Store.open().raw
    except Exception:  # noqa: BLE001 (a map layer is a nicety)
        return None


def _map_layer(name: str) -> list:
    """Polygons of a map layer (lists of rings), from the local store when it has them, else
    the copy that ships with anonymate."""
    return map_layer(name, _local_maps())


_practice_lock = threading.Lock()
_practice_cache: list = []


OEFEN_POPULATIE = ("In de oefenmodus niet nodig: je oefent tegen een verzonnen Nederland. Stop met "
                   "oefenen (links, \"Stoppen\") om de echte populatie op te bouwen.")


def _practice_population() -> Population:
    """The made-up Netherlands of the practice mode (the example dwellings come from it), made
    once; with made-up coordinates, so the map and the weather step work too."""
    with _practice_lock:
        if not _practice_cache:
            from . import voorbeeld
            _practice_cache.append(Population.from_dataframe(voorbeeld.population()))
        return _practice_cache[0]


_link_columns = link_columns
_read_uhi = read_uhi


def _bits(df, assessment, population):
    """Bits needed, per attribute (name, median) and remaining per record; None if it fails."""
    from .explain import information_bits
    try:
        needed, parts, remaining = information_bits(df, assessment, population)
    except Exception:  # noqa: BLE001 (the picture is optional; the assessment stands)
        return None
    return needed, [(b.column, b.median) for b in parts], remaining


_readable = readable_error


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    def hook(kind, value, tb):  # escaped from a Qt slot: show it instead of going silent
        import traceback
        detail = "".join(traceback.format_exception(kind, value, tb))[-1500:]
        QMessageBox.warning(None, "anonymate", _readable(f"{kind.__name__}: {value}")
                            + "\n\n" + detail)
    sys.excepthook = hook
    w = MainWindow()
    w.show()
    if len(sys.argv) > 1:
        w.load(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
