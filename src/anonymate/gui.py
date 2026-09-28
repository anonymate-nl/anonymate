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
import re
import sys
import threading
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QRadioButton, QScrollArea,
                               QSlider, QSpinBox,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from . import __version__
from .cli import SCENARIOS, _scope_from_args, parse_scope, qids_from, read_dataset
from .detect import Role, derive_h3_columns, detect
from .generalize import suggest
from .gui_kaart import MapData, MapWidget, available, noisy_cells
from .gui_tekening import (STYLE, BitsBar, HouseArray, KHistogram, TradeoffChart, houses_for)
from .population import Population
from .qids import CATALOGUE
from .report import write
from .risk import P_DEFAULT, P_MAX, P_MIN, Status, Threshold, assess

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
STATUS_TEXT = {Status.OK: "publiceerbaar", Status.AT_RISK: "te herleidbaar",
               Status.NO_MATCH: "geen match"}
# the norm's reference points, shown under the slider (El Emam & Arbuckle 2013; grid operators)
NORM_MARKS = [(0.05, "streng: openbare publicatie van gevoelige gegevens"),
              (0.09, "standaard van AnonyMate"),
              (0.10, "netbeheerders, verbruik per PC6"),
              (0.20, "medisch, gecontroleerde toegang"),
              (0.33, "ondergrens, gecontroleerde toegang")]
STEPS = ["Dataset", "Norm", "Kolommen", "Signatuur", "Weerlocatie", "Aanvaller", "Uitkomst"]
PROVINCES = ["Drenthe", "Flevoland", "Fryslân", "Gelderland", "Groningen", "Limburg",
             "Noord-Brabant", "Noord-Holland", "Overijssel", "Utrecht", "Zeeland", "Zuid-Holland"]
WEATHER_H3 = "weerzone_h3"
WEATHER_STATION = "weer_knmi_station"
UHI = "uhi"


def _g(x) -> str:
    return "–" if x is None else f"{x:.3g}"


def _nl(x: float, digits: int = 1) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


class Worker(QObject):
    """Runs one long computation off the UI thread."""

    done = Signal(object)
    failed = Signal(str)
    progress = Signal(float, str)

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


# symbol (rich text), unit and meaning of each published signature output
SIGNATURE_OUTPUTS = {
    "H": ("H", "W/K", "warmteverlies per graad verschil tussen binnen en buiten"),
    "C": ("C", "Wh/K", "warmtecapaciteit: hoeveel warmte de woning vasthoudt"),
    "tau": ("τ", "h", "tijdconstante C/H: hoe snel de woning afkoelt"),
    "Asol": ("A<sub>sol</sub>", "m²", "effectief zonoppervlak: hoeveel zonnewarmte binnenkomt"),
}


def _header(column: str) -> str:
    """Table header for an exploration column: stap_H -> stap H [W/K] (plain text, so A_sol)."""
    if column.startswith("stap_") and column[5:] in SIGNATURE_OUTPUTS:
        symbol, unit, _ = SIGNATURE_OUTPUTS[column[5:]]
        return f"stap {symbol.replace('<sub>', '_').replace('</sub>', '')} [{unit}]"
    return column


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
        self.step_list.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.step_list.currentRowChanged.connect(self._step_changed)
        self.step_list.currentRowChanged.connect(
            lambda i: self._ensure_map() if i == STEPS.index("Weerlocatie") else None)

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
        lrow = QHBoxLayout()
        self.lock_btn = _primary("Norm vastleggen")
        self.lock_btn.clicked.connect(self.lock_norm)
        self.lock_label = _label("nog niet vastgelegd: toetsen kan pas daarna", "note", wrap=True)
        lrow.addWidget(self.lock_btn)
        lrow.addWidget(self.lock_label, 1)
        cl.addLayout(lrow)
        lay.addWidget(card)
        why, wl = _card()
        wl.addWidget(_label("Waarom eerst de norm?", "h2"))
        wl.addWidget(_label("Wie de uitkomst al kent, is geneigd de lat te verleggen tot het "
                            "past. Een vooraf vastgelegde norm is ethisch en juridisch de juiste "
                            "volgorde. Afwegen gebeurt daarna, binnen de norm: grover publiceren "
                            "of woningen weglaten.", "note", wrap=True))
        lay.addWidget(why)
        lay.addStretch(1)
        self._next(lay, "Verder naar de kolommen", 2)
        return page

    def _page_columns(self) -> QWidget:
        page, lay = self._page(3, "kolommen", "Wat verraadt elke kolom?",
                               "AnonyMate stelt per kolom een rol voor. Controleer die: jij weet "
                               "wat er echt in staat. Directe identificatoren gaan er altijd uit; "
                               "kenmerken die ook in een register staan, tellen mee in de toets.")
        self.columns = QTableWidget(0, 4)
        self.columns.setHorizontalHeaderLabels(["kolom", "voorstel", "behandelen als", "reden"])
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
        self.koppel.setPlaceholderText("postcode,huisnummer  (of één kolom met BAG-ID)")
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
                                     ("tau", 0.0, 500.0), ("Asol", 0.0, 200.0)):
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
        urow = QHBoxLayout()
        self.w_uhi_file = QLineEdit()
        self.w_uhi_file.setPlaceholderText("UHI per postcode (csv/parquet: pc6, uhi)")
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
        left.addStretch(1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(460)
        body.addWidget(lw)
        right = QVBoxLayout()
        self.map = MapWidget()
        self.map.cellClicked.connect(self._cell_clicked)
        right.addWidget(self.map, 1)
        self.map_busy = QProgressBar()
        self.map_busy.setRange(0, 0)
        self.map_busy.setTextVisible(False)
        self.map_busy.setFixedHeight(6)
        self.map_busy.hide()
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

        def work():
            from .store import Store
            from .weerspoor import (grid_from, investigate, load_hourly, read_series_source,
                                    utc_hours)
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
                               value_col="waarde")
        self._run(work, self._show_trace)

    def _show_trace(self, found) -> None:
        from .weerspoor import as_columns
        traced = getattr(found, "per_home", found)
        key = self.t_key.currentText()
        cols = as_columns(traced)
        cols["woning"] = cols["woning"].astype(str)
        df = self.df.drop(columns=[c for c in (WEATHER_H3, WEATHER_STATION)
                                   if c in self.df.columns])
        by_home = cols.set_index("woning")
        for col in (WEATHER_STATION, WEATHER_H3):
            values = df[key].astype(str).map(by_home[col])
            df[col] = pd.Series([v if pd.notna(v) else None for v in values], index=df.index,
                                dtype=object)
        added = {c: q for c, q in ((WEATHER_STATION, "knmi_station"), (WEATHER_H3, "h3_cel"))
                 if df[c].notna().any()}
        df = df.drop(columns=[c for c in (WEATHER_STATION, WEATHER_H3) if c not in added])
        notes = list(getattr(found, "findings", None) or [])
        if WEATHER_STATION in df.columns:
            try:
                from .weerspoor import check_assignment
                stations = traced.attrs.get("stations")
                widened, extra = check_assignment(df, key, traced, self.population(), stations)
                merged = [w if w is not None and pd.notna(w) else v
                          for w, v in zip(widened, df[WEATHER_STATION])]
                df[WEATHER_STATION] = pd.Series(
                    [x if x is not None and pd.notna(x) else None for x in merged],
                    index=df.index, dtype=object)
                notes += extra
            except Exception:  # noqa: BLE001 (the check is extra; the traced station stands)
                pass
        self.df = self.current_df = df
        # an approximate match leaves the attacker some kilometres of doubt
        self.weather_tolerance = float(cols["onzekerheid_km"].max()) \
            if "onzekerheid_km" in cols and cols["onzekerheid_km"].notna().any() else 0.0
        self.assessment = None
        self._add_column_rows(added)
        counts = traced["regime"].value_counts().to_dict()
        self.w_status.setText("Teruggeleid: " + ", ".join(f"{k}: {v}" for k, v in counts.items())
                              + ". De afgeleide weerlocatie telt mee als verborgen locatie.")
        if hasattr(found, "verdict"):
            self.cell_title.setText("Wat het weer verraadt")
            self.cell_text.setTextFormat(Qt.RichText)
            extra = "".join(f"<br>• {n}" for n in notes[:8])
            more = f"<br>… en nog {len(notes) - 8}" if len(notes) > 8 else ""
            self.cell_text.setText(f"<b>Conclusie.</b> {found.verdict}<br><br>"
                                   f"<b>Advies.</b> {found.advice}"
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

    def _region_changed(self, *_args) -> None:
        self._map_data = None
        if hasattr(self, "map"):
            self.map.data = None
            self.map.update()
        self._refresh_rail()

    def _scope(self, population):
        pairs = [p.strip() for p in self.scope.text().split(";") if p.strip()]
        items = {**_scope_from_args(pairs), **self._region_scope()}
        return parse_scope(items, population)

    def _ensure_map(self) -> None:
        if self._map_data is not None or not hasattr(self, "map"):
            return
        try:
            population = self.population()
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
        borders = [ring for rings in _map_layer("gemeentegrenzen.parquet") for ring in rings]
        land = _map_layer("nederland_land.parquet")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._map_data = _ScopedMapData(population, stations, borders, land)
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

    def _locations(self) -> pd.DataFrame:
        """lat, lon (and postcode6 when linked) per record, from the chosen source."""
        if self.w_source.currentData() == "gps":
            la, lo = self.w_lat.currentText(), self.w_lon.currentText()
            if not la or not lo:
                raise ValueError("kies de GPS-kolommen (breedte- en lengtegraad)")
            return pd.DataFrame({"lat": pd.to_numeric(self.df[la], errors="coerce"),
                                 "lon": pd.to_numeric(self.df[lo], errors="coerce"),
                                 "postcode6": None}, index=self.df.index)
        from .link import link
        population = self.population()
        if not available(population):
            raise ValueError("Een weerlocatie via het adres vraagt een populatie met "
                             "coördinaten; bouw de populatie op ('anonymate build'), of kies "
                             "GPS als bron.")
        linked = link(self.df, population, **self._link_kwargs())
        ids = linked["register_vbo_id"].astype(str).tolist()
        lat = population.lookup("lat", "vbo_id", ids)
        lon = population.lookup("lon", "vbo_id", ids)
        pc6 = population.lookup("postcode6", "vbo_id", ids)
        return pd.DataFrame({"lat": [float(lat[v]) if v in lat else math.nan for v in ids],
                             "lon": [float(lon[v]) if v in lon else math.nan for v in ids],
                             "postcode6": [pc6.get(v) for v in ids]}, index=self.df.index)

    def apply_weather(self) -> None:
        """Add the weather location (and UHI) as published columns; hide the source."""
        if self.w_none.isChecked() and not self.w_uhi.isChecked():
            self.w_status.setText("Niets toe te voegen: kies een weerlocatie of UHI.")
            return
        try:
            loc = self._locations()
        except ValueError as e:
            self._failed(str(e))
            return
        df = self.df.drop(columns=[c for c in (WEATHER_H3, WEATHER_STATION, UHI)
                                   if c in self.df.columns])
        added = {}
        if self.w_h3.isChecked():
            if self.weather_seed is None:
                import secrets
                self.weather_seed = secrets.randbits(32)
            sigma = float(self.w_sigma.value())
            df[WEATHER_H3] = noisy_cells(loc["lat"], loc["lon"], self.w_level.value(), sigma,
                                         self.weather_seed)
            added[WEATHER_H3] = "h3_cel"
            self.weather_tolerance = sigma if self.w_count_noise.isChecked() else 0.0
        elif self.w_station.isChecked():
            population = self.population()
            if "knmi_station" not in population.columns:
                self._failed("de populatie kent geen KNMI-stations")
                return
            from .link import link
            if self.w_source.currentData() == "gps":
                self._failed("KNMI-station vanuit GPS: kies de koppelkolommen als bron")
                return
            linked = link(self.df, population, **self._link_kwargs())
            ids = linked["register_vbo_id"].astype(str).tolist()
            st = population.lookup("knmi_station", "vbo_id", ids)
            df[WEATHER_STATION] = [st.get(v) for v in ids]
            added[WEATHER_STATION] = "knmi_station"
            self.weather_tolerance = 0.0
        if self.w_uhi.isChecked():
            try:
                table = _read_uhi(self.w_uhi_file.text())
            except ValueError as e:
                self._failed(str(e))
                return
            self.uhi_path = self.w_uhi_file.text()
            raw = loc["postcode6"].map(table)
            from .generalize import Bin
            from .risk import QidColumn
            q = QidColumn(UHI, CATALOGUE["uhi"])
            tmp = pd.DataFrame({UHI: raw.astype(object)}, index=df.index)
            binned, _ = Bin(UHI, float(self.w_uhi_step.value())).apply(tmp, [q])
            df[UHI] = binned[UHI]
            added[UHI] = "uhi"
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
            self.columns.setItem(i, 3, QTableWidgetItem("toegevoegd in stap 5"))

    def _update_dataset_cells(self) -> None:
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
        nr = lambda x: f"{x:,.0f}".replace(",", ".")  # noqa: E731
        if self.w_station.isChecked():
            station, count = self._map_data.station_at(lat, lng)
            if station is None:
                return
            name = self._map_data.station_name(station)
            self.cell_title.setText(f"KNMI-station {name}")
            in_data = int((self.df[WEATHER_STATION] == station).sum()) \
                if self.df is not None and WEATHER_STATION in self.df.columns else 0
            self.cell_text.setText(f"Woningen waarvoor dit het dichtstbijzijnde station is: "
                                   f"{nr(count)}. Woningen uit de dataset: {in_data}.")
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
        self.map_busy.show()
        sigma = float(self.w_sigma.value())
        data = self._map_data
        thread = QThread(self)
        worker = Worker(lambda: data.cell_stats(cell, sigma))
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

    def _cell_done(self, stats: dict) -> None:
        self._show_cell(stats.get("cel"), stats)

    def _cell_failed(self, message: str) -> None:
        self.map_busy.hide()
        self._failed(message)

    def _show_cell(self, cell: str, stats: dict) -> None:
        self.map_busy.hide()
        if self.map.selected != cell:          # another cell was clicked meanwhile
            return
        self.map.heat = stats.get("heat", {})
        import h3
        la, lo = h3.cell_to_latlng(cell)
        edge = h3.average_hexagon_edge_length(h3.get_resolution(cell), unit="km")
        self.map.focus(la, lo, max(8 * edge, 6 * float(self.w_sigma.value())))
        nr = lambda x: f"{x:,.0f}".replace(",", ".")  # noqa: E731
        in_data = self.map.dataset_cells.get(cell, 0)
        factor = stats["met_buren"] / stats["woningen"] if stats["woningen"] else math.inf
        sigma = self.w_sigma.value()
        self.cell_title.setText(f"Cel van niveau {stats['niveau']} · "
                                f"{nr(stats['gebied_km2'])} km²")
        own, ring = stats["woningen"], stats["met_buren"]
        lines = [f"<b>{nr(own)}</b> woningen in deze cel, <b>{nr(ring)}</b> met de zes buren"
                 + (f" ({factor:.0f}× zoveel)" if own else "") + ". "
                 f"Uit de dataset liggen er {in_data} in deze cel."]
        if own:
            lines.append("<br><br>Stel dat deze cel bij een woning gepubliceerd is. Zonder ruis "
                         f"ligt de woning zeker in de cel: {nr(own)} kandidaten.")
            if sigma > 0:
                lines.append(f"Met ruis van σ = {sigma} km kan de woning ook van buiten de cel "
                             "komen. Een aanvaller die σ kent, weegt elke woning naar de kans "
                             "dat haar ruis in deze cel uitkomt: dat zijn effectief "
                             f"<b>{nr(stats['k_eff'])}</b> kandidaten.")
                if "heat_km2" in stats:
                    lines.append(f"Het oranje gebied op de kaart, ~{nr(stats['heat_km2'])} km² met "
                                 f"{nr(stats['heat_woningen'])} woningen, bevat 95% van de kans "
                                 "waar de woning werkelijk ligt; hoe donkerder, hoe "
                                 "waarschijnlijker.")
            lines.append("Dit gaat alleen over de locatie: type, label en de andere "
                         "gepubliceerde kenmerken maken de groep kleiner. De toets rekent dat "
                         "per woning uit.")
        self.cell_text.setTextFormat(Qt.RichText)
        self.cell_text.setText(" ".join(lines))

    def _page_attacker(self) -> QWidget:
        page, lay = self._page(6, "aanvaller en populatie", "Wie probeert het, en tussen welke "
                               "woningen?", "De toets telt voor elke woning hoeveel woningen in "
                               "Nederland dezelfde gepubliceerde kenmerken hebben, voor een "
                               "aanvaller met de kennis die je hier kiest.")
        card, cl = _card()
        form = QFormLayout()
        self.scenario = QComboBox()
        self.scenario.addItem("openbare registers (BAG, EP-online)", "register")
        self.scenario.addItem("+ zichtbaar van buitenaf", "zichtbaar")
        self.scenario.addItem("+ insiderkennis (installateur, leverancier, buren)", "insider")
        form.addRow("aanvaller weet", self.scenario)
        self.scope = QLineEdit()
        self.scope.setPlaceholderText("bv.  gemeente=Zwolle,Deventer; oppervlakte=50-250; "
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
        buttons.addWidget(self.explore_btn)
        buttons.addWidget(self.suggest_btn)
        buttons.addWidget(self.adopt_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.save_btn)
        lay.addLayout(buttons)
        prow = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(10)
        self.progress_label = _label("", "note")
        prow.addWidget(self.progress, 1)
        prow.addWidget(self.progress_label)
        lay.addLayout(prow)
        self.progress.hide()
        self.progress_label.hide()
        self._tick = QTimer(self)
        self._tick.timeout.connect(lambda: self._on_progress(None, None))
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
            value = _label("–", "big")
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
        wrow = QHBoxLayout()
        self.tradeoff = TradeoffChart()
        wrow.addWidget(self.tradeoff, 1)
        self.gen_steps = QListWidget()
        self.gen_steps.setFixedWidth(300)
        self.gen_steps.currentRowChanged.connect(self._gen_step_chosen)
        wrow.addWidget(self.gen_steps)
        wl.addLayout(wrow, 1)
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

    def _step_changed(self, index: int) -> None:
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
        scope = self._region_scope()
        if not scope:
            return "heel Nederland"
        parts = scope.get("provincie", []) + scope.get("gemeente", [])
        return ", ".join(parts) if len(parts) <= 2 else f"{len(parts)} gebieden"

    def _region_scope(self) -> dict:
        if self.region_all.isChecked():
            return {}
        out = {}
        provinces = [n for n, b in self.region_boxes.items() if b.isChecked()]
        if provinces:
            out["provincie"] = provinces
        towns = [t.strip() for t in self.region_municipalities.text().split(",") if t.strip()]
        if towns:
            out["gemeente"] = towns
        return out

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
                             f"Van zo'n groep mag hooguit {t.p:.0%} in de dataset zitten.")
        self.k_big.setText(f"k ≥ {t.k}")
        self.norm_houses.set(min(t.k, 20), min(t.k, 20))
        if hasattr(self, "step_list"):
            self._refresh_rail()

    def lock_norm(self) -> None:
        """Fix the norm. It stays fixed until a new dataset is opened, so it cannot be tuned to
        the outcome."""
        self.norm_locked = True
        self.p.setEnabled(False)
        self.p_slider.setEnabled(False)
        self.lock_btn.setEnabled(False)
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
            import time as _time
            self._started = _time.monotonic()
            self._fraction = None
            self.progress.setRange(0, 0)           # running, no fraction known yet
            self.progress.show()
            self.progress_label.setText("bezig…")
            self.progress_label.show()
            self._tick.start(1000)
        elif hasattr(self, "progress"):
            self.progress.hide()
            self.progress_label.hide()
            self._tick.stop()

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
        self.lock_btn.setEnabled(True)
        self.lock_label.setText("nog niet vastgelegd: toetsen kan pas daarna")
        self.file_label.setText(f"{self.path.name}: {len(self.df)} records, "
                                f"{len(self.df.columns)} kolommen")
        found = detect(self.df)
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
            self.columns.setCellWidget(i, 2, combo)
            self.columns.setItem(i, 3, QTableWidgetItem(d.reason))
        numeric = [c for c in self.df.columns
                   if pd.to_numeric(self.df[c], errors="coerce").notna().mean() > 0.9]
        for box, pattern in ((self.w_lat, GPS_LAT), (self.w_lon, GPS_LON)):
            box.clear()
            box.addItems([""] + numeric)
            guess = next((c for c in numeric if re.search(pattern, c, re.I)), "")
            box.setCurrentText(guess)
        has_gps = bool(self.w_lat.currentText() and self.w_lon.currentText())
        self.w_source.setCurrentIndex(1 if has_gps else 0)
        self.koppel.setText(",".join(_link_columns(found)))
        # with a way to find the dwelling, propose the recommended weather location
        (self.w_h3 if has_gps or self.koppel.text() else self.w_none).setChecked(True)
        self.weather_seed, self.weather_tolerance, self.uhi_path = None, 0.0, None
        self.w_status.setText("")
        self._update_dataset_cells()
        self._set_busy(False)
        self._refresh_rail()
        self.go(1)

    def mapping(self) -> dict[str, str]:
        out = {}
        for i in range(self.columns.rowCount()):
            col = self.columns.item(i, 0).text()
            choice = self.columns.cellWidget(i, 2).currentText()
            out[col] = {NO_QID: "geen", DIRECT: "direct"}.get(choice, choice)
        return out

    def population(self) -> Population:
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
            self._population = Store.open().population()
        return self._population

    def _with_uhi(self, population):
        """The population with a UHI column from the chosen file, when UHI is published."""
        if self.df is None or UHI not in self.df.columns or "uhi" in population.columns \
                or not self.uhi_path or "postcode6" not in population.columns:
            return population
        p = Path(self.uhi_path)
        reader = "read_parquet" if p.suffix.lower() == ".parquet" else "read_csv_auto"
        cols = [r[0] for r in population.con.execute(
            f"DESCRIBE SELECT * FROM {reader}('{p.as_posix()}')").fetchall()]
        pc = next(c for c in cols if c.lower() in ("pc6", "postcode6", "postcode"))
        val = next(c for c in cols if c.lower().startswith("uhi"))
        rel = (f"(SELECT p.*, u.uhi FROM {population.relation} p LEFT JOIN (SELECT "
               f"upper(replace(CAST(\"{pc}\" AS VARCHAR), ' ', '')) AS pc6, "
               f"CAST(\"{val}\" AS DOUBLE) AS uhi FROM {reader}('{p.as_posix()}')) u "
               f"ON u.pc6 = upper(replace(p.postcode6, ' ', '')))")
        return Population(population.con, rel, population.snapshot, population.scope)

    def _link_kwargs(self) -> dict:
        cols = [c.strip() for c in self.koppel.text().split(",") if c.strip()]
        if not cols:
            raise ValueError("Deze stap heeft het adres nodig, maar de koppelkolommen zijn leeg. "
                             "Vul in stap 4 bij 'koppelkolommen' postcode,huisnummer of een "
                             "BAG-ID-kolom in, of zet de signatuur (stap 4) en de weerlocatie "
                             "(stap 5) uit.")
        missing = [c for c in cols if c not in self.df.columns]
        if missing:
            raise ValueError(f"koppelkolommen niet in de dataset: {', '.join(missing)}")
        if len(cols) == 1:
            return {"vbo_id": cols[0]}
        return dict(zip(["postcode", "huisnummer", "huisletter", "toevoeging"], cols))

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

    def _run(self, fn, on_done) -> None:
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
        except ValueError as e:
            self._failed(str(e))

    def _signature_available(self, population) -> bool:
        method = self.sig_method.currentData()
        return any(c.startswith(f"sig_{method}_") or (method == "nta8800" and c == "sig_H")
                   for c in population.columns)

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

        def work():
            data, all_qids = df, list(qids)
            if with_sig:
                from .publicatie import add_baseline
                data, sig_qids, never = add_baseline(df, population, plan, **link_kw)
                all_qids += sig_qids
                self.direct = sorted(set(self.direct) | set(never))
            a = assess(data, all_qids, population, threshold, scenario)
            return data, a, _bits(data, a, population)
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
        candidates = {o: sorted({s / 2, s, 2 * s, 4 * s}) for o, s in plan.steps.items()}
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
                text = (str(int(v)) if isinstance(v, float) and v.is_integer()
                        else _g(v) if isinstance(v, float) else str(v))
                self.results.setItem(i, j, QTableWidgetItem(text))
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

        def work(report):
            steps = suggest(df, qids, population, threshold, scenario, target_share=0.95,
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
        self.tradeoff.set(rows)
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
        """What leaving out the risky records does to the published columns (notitie 8)."""
        from .representativiteit import shift
        drop = set(getattr(self, "direct", None) or [])
        cols = [c for c in df.columns if c not in drop]
        try:
            table = shift(df, a.ok, cols, draws=100)
        except Exception:  # noqa: BLE001 (an extra; the assessment itself stands)
            return []
        moved = table[(table["oordeel"] != "verwaarloosbaar") & (table["toeval"].fillna(1) < 0.05)]
        if moved.empty:
            return ["Representativiteit: het weglaten verschuift geen enkele kolom meer dan bij "
                    "toeval (details in rapport.md)."]
        parts = [f"{r.kolom} ({r.maat} {r.waarde:+.2f}{'; ' + r.toelichting if r.toelichting else ''})"
                 for r in moved.itertuples()]
        return ["Representativiteit: het weglaten verschuift meer dan bij toeval: "
                + "; ".join(parts) + ". Een analyse op het gepubliceerde deel kan daardoor "
                "afwijken; grover publiceren houdt die woningen erin (details in rapport.md)."]

    def _show_assessment(self, result) -> None:
        df, a, bits = result
        self.assessment, self.current_df = a, df
        s = a.summary()
        n = s["records"] or 1
        text = [f"{s['ok']} van {s['records']} records publiceerbaar ({100 * s['ok'] / n:.0f}%), "
                f"{s['risico']} met risico, {s['geen_match']} zonder match in de populatie.",
                f"k minimaal {_g(s['k_min'])}, mediaan {_g(s['k_mediaan'])}; "
                f"δ maximaal {_g(s['delta_max'])}.",
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
        self.summary.setPlainText("\n".join(text))

        self.outcome_title.setText(f"{s['ok']} van de {s['records']} woningen publiceerbaar")
        self.stat_values["ok"].setText(f"{s['ok']} · {100 * s['ok'] / n:.0f}%")
        self.stat_values["risk"].setText(str(n_out))
        self.stat_values["k"].setText(_g(s["k_mediaan"]))
        norm_k = s["k_drempel"]
        self.k_hist.set(list(a.records["k"]), norm_k)
        if bits is not None:
            needed, parts, remaining = bits
            self.bits_bar.set(needed, parts, float(remaining.median()), math.log2(norm_k))
            self.stat_values["bits"].setText(f"{_nl(float(remaining.median()))} bits")
            population = f"{s['populatie']:,}".replace(",", ".")
            self.bits_note.setText(f"{_nl(needed)} bits wijzen één woning aan uit {population} "
                                   "woningen; per kenmerk de mediaan over de woningen, en wat "
                                   "er daarna nog te raden valt.")

        shown = df[[q.column for q in a.qids]].join(
            a.records[["k", "delta", "status", "redenen"]])
        self._shown = shown
        self.results.setColumnCount(len(shown.columns))
        self.results.setRowCount(len(shown))
        self.results.setHorizontalHeaderLabels([str(c) for c in shown.columns])
        status_col = list(shown.columns).index("status")
        k_col = list(shown.columns).index("k")
        for i, row in enumerate(shown.itertuples(index=False)):
            colour = QColor(STATUS_COLOURS.get(row[status_col], "#FFFFFF"))
            for j, v in enumerate(row):
                text = "" if v is None or (isinstance(v, float) and pd.isna(v)) else (
                    f"{v:.3g}" if isinstance(v, float) else str(v))
                if j == status_col:
                    text = STATUS_TEXT.get(v, text)
                elif j == k_col and text:
                    text = f"{int(v):,}".replace(",", ".")
                item = QTableWidgetItem(text)
                item.setBackground(colour)
                self.results.setItem(i, j, item)
        self.results.resizeColumnsToContents()
        self._refresh_rail()
        self.tabs.setCurrentIndex(0)
        risky = [i for i, st in enumerate(shown["status"]) if st != Status.OK]
        if len(shown):
            first = risky[0] if risky else 0
            self.results.selectRow(first)
            self.results.scrollToItem(self.results.item(first, 0))

    def _on_progress(self, fraction, text) -> None:
        """Progress from the computation (fraction 0..1, text), or a clock tick (None)."""
        import time as _time
        if not hasattr(self, "_started"):
            return
        elapsed = _time.monotonic() - self._started
        if fraction is not None:
            self._fraction = fraction
            self._progress_text = text
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(1000 * fraction))
        clock = lambda s: f"{int(s) // 60}:{int(s) % 60:02d}"  # noqa: E731
        parts = [getattr(self, "_progress_text", None) or "bezig", f"{clock(elapsed)} bezig"]
        f = getattr(self, "_fraction", None)
        if f and f > 0.05:
            parts.append(f"nog ongeveer {clock(elapsed * (1 - f) / f)}")
        self.progress_label.setText(" · ".join(parts))

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
            for r in range(self.columns.rowCount()):
                col = self.columns.item(r, 0).text()
                if col in keys:
                    self.columns.cellWidget(r, 2).setCurrentText(keys[col])
                    self.columns.setItem(r, 3, QTableWidgetItem(
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
        described = ", ".join(str(v).replace("_", " ") for c, v in rec.items()
                              if c not in ("k", "delta", "status", "redenen") and pd.notna(v))
        status = rec["status"]
        self.record_card.setObjectName("card" if status == Status.OK else "cardRisk")
        self.record_card.style().unpolish(self.record_card)
        self.record_card.style().polish(self.record_card)
        self.record_title.setText(f"Woning {i + 1} · {STATUS_TEXT.get(status, status)}")
        if status == Status.NO_MATCH:
            body = (f"{described}: geen enkele woning in de populatie past hierop. Dat is geen "
                    "veiligheid: een aanvaller laat het afwijkende kenmerk weg en zoekt verder.")
        else:
            delta = rec["delta"]
            share = "" if pd.isna(delta) else (
                f" Van die woningen zit {_nl(100 * float(delta), 0)}% in de dataset.")
            verdict = ("Dat haalt de norm." if status == Status.OK else
                       f"De norm vraagt er {norm_k}: deze woning komt niet in publiceerbaar.csv.")
            count = f"{k_int:,}".replace(",", ".")
            body = f"{described}. In de populatie: {count} zulke woningen.{share} {verdict}"
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
              population=getattr(self, "_scoped_population", None))
        QMessageBox.information(
            self, "anonymate",
            f"Opgeslagen in {out}:\n\npubliceerbaar.csv: om te publiceren\n"
            "rapport.md en samenvatting.json: verantwoording\n"
            "rapport_per_record.csv: INTERN, niet publiceren")



class _ScopedMapData(MapData):
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


def _map_layer(name: str) -> list:
    """Polygons of a map layer (lists of rings), from the local store when it has them ('anonymate
    ingest gebieden', newest), else the copy that ships with anonymate (so the practice mode
    has a recognisable map without downloads)."""
    import json
    try:
        from .store import Store
        path = Store.open().raw / name
        if not path.exists():
            path = Path(__file__).with_name("data") / "kaart" / name
        return [json.loads(r) for r in pd.read_parquet(path)["ringen"]]
    except Exception:  # noqa: BLE001 (a map layer is a nicety)
        return []


_practice_lock = threading.Lock()
_practice_cache: list = []


def _practice_population() -> Population:
    """The made-up Netherlands of the practice mode (the example dwellings come from it), made
    once; with made-up coordinates, so the map and the weather step work too."""
    with _practice_lock:
        if not _practice_cache:
            from . import voorbeeld
            _practice_cache.append(Population.from_dataframe(voorbeeld.population()))
        return _practice_cache[0]


# GPS columns by whole word: 'installatiedatum' holds 'lat', 'salon' holds 'lon'
GPS_LAT = r"(^|[^a-z])(lat|latitude|breedte|breedtegraad)([^a-z]|$)"
GPS_LON = r"(^|[^a-z])(lon|lng|long|longitude|lengte|lengtegraad)([^a-z]|$)"


def _link_columns(found) -> list[str]:
    """Columns that point at the address: a BAG-ID, or postcode plus house number (plus letter
    and addition when present), as detection found them."""
    import re
    names = [d.column for d in found]
    bag = next((c for c in names if re.search(r"(^|_)(vbo|verblijfsobject|bag)_?id(_|$)",
                                               c, re.I)), None)
    if bag:
        return [bag]
    pc = next((d.column for d in found if d.qid == "postcode6"), None)
    nr = next((c for c in names if re.fullmatch(r"huis_?nummer|huisnr|house_?number|nr",
                                                c, re.I)), None)
    if not (pc and nr):
        return []
    letter = next((c for c in names if re.fullmatch(r"huis_?letter|letter", c, re.I)), None)
    extra = next((c for c in names if re.fullmatch(r"toevoeging|huisnummer_?toevoeging|"
                                                   r"addition", c, re.I)), None)
    return [pc, nr] + ([letter] if letter else []) + ([extra] if extra and letter else [])


def _read_uhi(path: str) -> dict:
    """postcode6 -> UHI [°C] from a csv or parquet with a postcode and a UHI column."""
    if not path:
        raise ValueError("kies een UHI-bestand (per postcode: pc6 en uhi)")
    p = Path(path)
    if not p.exists():
        raise ValueError(f"UHI-bestand niet gevonden: {path}")
    df = pd.read_parquet(p) if p.suffix.lower() == ".parquet" else pd.read_csv(p)
    pc = next((c for c in df.columns if c.lower() in ("pc6", "postcode6", "postcode")), None)
    val = next((c for c in df.columns if c.lower().startswith("uhi")), None)
    if pc is None or val is None:
        raise ValueError("het UHI-bestand heeft een kolom pc6 (of postcode6) en uhi nodig")
    keys = df[pc].astype(str).str.replace(" ", "").str.upper()
    return dict(zip(keys, pd.to_numeric(df[val], errors="coerce")))

def _bits(df, assessment, population):
    """Bits needed, per attribute (name, median) and remaining per record; None if it fails."""
    from .explain import information_bits
    try:
        needed, parts, remaining = information_bits(df, assessment, population)
    except Exception:  # noqa: BLE001 (the picture is optional; the assessment stands)
        return None
    return needed, [(b.column, b.median) for b in parts], remaining


def _readable(message: str) -> str:
    """A message for people, not programmers: expected problems (ValueError and friends) as
    their own text, anything else as a plain 'something went wrong' with the detail kept."""
    import re
    m = re.match(r"^(\w+(?:Error|Exception)):\s*(.*)$", message, re.S)
    if not m:
        return message
    kind, text = m.groups()
    if kind in ("ValueError", "FileNotFoundError"):
        return text.split(" / ")[0]
    return ("Er ging iets onverwachts mis. Probeer het opnieuw, of meld het met deze tekst: "
            f"{kind}: {text}")


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
