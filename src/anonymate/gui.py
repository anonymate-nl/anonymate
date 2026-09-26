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
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSlider, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from . import __version__
from .cli import SCENARIOS, _scope_from_args, parse_scope, qids_from, read_dataset
from .detect import Role, derive_h3_columns, detect
from .generalize import suggest
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
STEPS = ["Dataset", "Norm", "Kolommen", "Signatuur", "Aanvaller", "Uitkomst"]


def _g(x) -> str:
    return "–" if x is None else f"{x:.3g}"


def _nl(x: float, digits: int = 1) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


class Worker(QObject):
    """Runs one long computation off the UI thread."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self.fn())
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
                      self._page_signature, self._page_attacker, self._page_outcome):
            self.pages.addWidget(self._scrolling(build()))
        self.step_list.currentRowChanged.connect(self.pages.setCurrentIndex)

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
        self.step_list = QListWidget()
        self.step_list.setObjectName("steps")
        self.step_list.setFocusPolicy(Qt.NoFocus)
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
        lay.setContentsMargins(40, 32, 40, 32)
        lay.setSpacing(18)
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
        cl.addWidget(_label("Tip: probeer eerst woningen.csv (60 verzonnen woningen) met een "
                            "synthetische populatie (stap 5).", "note", wrap=True))
        lay.addWidget(card)
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
                               "Een warmteprestatiesignatuur uit het adres meepubliceren?",
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
        self._next(lay, "Verder naar de aanvaller", 4)
        return page

    def _page_attacker(self) -> QWidget:
        page, lay = self._page(5, "aanvaller en populatie", "Wie probeert het, en tussen welke "
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
        self.synthetic = QCheckBox("synthetische populatie gebruiken (alleen om te proberen)")
        form.addRow("", self.synthetic)
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
        page, lay = self._page(6, "uitkomst", "Nog niet getoetst", "")
        self.outcome_title = page.findChildren(QLabel, "h1")[0]
        buttons = QHBoxLayout()
        self.explore_btn = QPushButton("Afronding verkennen")
        self.explore_btn.clicked.connect(self.run_explore)
        self.suggest_btn = QPushButton("Generalisaties zoeken")
        self.suggest_btn.clicked.connect(self.run_suggest)
        self.save_btn = _primary("Opslaan…")
        self.save_btn.clicked.connect(self.save)
        buttons.addWidget(self.explore_btn)
        buttons.addWidget(self.suggest_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.save_btn)
        lay.addLayout(buttons)
        stats = QHBoxLayout()
        self.stat_values = {}
        for key, text in (("ok", "publiceerbaar"), ("risk", "te herleidbaar, niet publiceren"),
                          ("k", "gelijke woningen (mediaan k)"), ("bits", "nog te raden (mediaan)")):
            card, cl = _card()
            cl.addWidget(_label(text, "statLabel"))
            value = _label("–", "big")
            cl.addWidget(value)
            self.stat_values[key] = value
            stats.addWidget(card)
        lay.addLayout(stats)
        bits_card, bl = _card()
        bl.addWidget(_label("Wie is het? Wat de kenmerken prijsgeven", "h2"))
        self.bits_note = _label("", "note", wrap=True)
        bl.addWidget(self.bits_note)
        self.bits_bar = BitsBar()
        bl.addWidget(self.bits_bar)
        lay.addWidget(bits_card)

        self.tabs = QTabWidget()
        records = QWidget()
        rl = QHBoxLayout(records)
        rl.setContentsMargins(0, 8, 0, 0)
        self.results = QTableWidget(0, 0)
        self.results.verticalHeader().setVisible(False)
        self.results.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results.setMinimumHeight(300)
        self.results.itemSelectionChanged.connect(self._show_record)
        rl.addWidget(self.results, 1)
        side = QVBoxLayout()
        hist_card, hl = _card()
        hl.addWidget(_label("Hoeveel gelijke woningen?", "h2"))
        self.k_hist = KHistogram()
        hl.addWidget(self.k_hist)
        side.addWidget(hist_card)
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
        self.tradeoff = TradeoffChart()
        wl.addWidget(self.tradeoff, 1)
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
                self.scenario.currentText().split(" (")[0],
                self._outcome_sub()]
        done = [self.df is not None, self.norm_locked, self.df is not None and self.norm_locked,
                self.norm_locked, self.assessment is not None, self.assessment is not None]
        for i, (name, sub) in enumerate(zip(STEPS, subs)):
            mark = "✓" if done[i] else str(i + 1)
            item = self.step_list.item(i)
            item.setText(f"{mark}   {name}\n      {sub}")
            item.setForeground(QColor("#FFFFFF" if done[i] else "#C9D2DE"))
        if self.df is not None:
            self.dataset_card.setText(f"<b>{self.path.name}</b><br>{len(self.df)} woningen · "
                                      f"{len(self.df.columns)} kolommen"
                                      + (f"<br>norm p = {_nl(t.p, 2)} · k ≥ {t.k}"
                                         if self.norm_locked else ""))

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

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Dataset openen", "",
                                              "Data (*.csv *.xlsx *.xls *.parquet)")
        if path:
            self.load(path)

    def load(self, path: str | Path) -> None:
        self.path = Path(path)
        self.df, derived = derive_h3_columns(read_dataset(self.path))
        self.current_df = self.df
        self.assessment = self.steps = None
        self.norm_locked = False  # a new dataset: fix the norm again before assessing
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
            from . import synthetic
            return Population.from_dataframe(synthetic.population(200_000))
        if self._population is None:
            from .store import Store
            self._population = Store.open().population()
        return self._population

    def _link_kwargs(self) -> dict:
        cols = [c.strip() for c in self.koppel.text().split(",") if c.strip()]
        if not cols:
            raise ValueError("geef de koppelkolommen op (postcode,huisnummer of een BAG-ID-kolom)")
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
        threshold = Threshold(round(self.p.value(), 2))
        scenario = SCENARIOS[self.scenario.currentData()]
        population = self.population()
        pairs = [p.strip() for p in self.scope.text().split(";") if p.strip()]
        scope = parse_scope(_scope_from_args(pairs), population)
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
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(lambda: self._set_busy(False))
        thread._worker = worker  # keep a reference
        self._threads.append(thread)
        thread.start()

    def _failed(self, message: str) -> None:
        self.summary.setPlainText(message)
        self.outcome_title.setText("Er ging iets mis")
        QMessageBox.warning(self, "anonymate", message)

    # -------------------------------------------------------------------------------------------
    def run_assess(self) -> None:
        if not self.norm_locked:
            self._failed("Leg eerst de privacynorm vast (stap 2).")
            return
        try:
            self._run_assess()
        except ValueError as e:
            self._failed(str(e))

    def _run_assess(self) -> None:
        qids, direct, threshold, scenario, population = self._inputs()
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
        self.go(5)
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
        plan = self._plan()
        candidates = {o: sorted({s / 2, s, 2 * s, 4 * s}) for o, s in plan.steps.items()}
        link_kw = self._link_kwargs()
        df = self.df

        def work():
            from .publicatie import explore
            return explore(df, population, plan.method, candidates, threshold, qids, scenario,
                           **link_kw)
        self.go(5)
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

        def work():
            steps = suggest(df, qids, population, threshold, scenario, target_share=0.95)
            last = steps[-1]
            a = assess(last.df, last.qids, population, threshold, scenario)
            return last.df, a, _bits(last.df, a, population), steps
        self.go(5)
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
        self.outcome_title.setText(f"{a.summary()['ok']} van de {a.summary()['records']} "
                                   "woningen publiceerbaar, na generalisatie")
        self.tabs.setCurrentIndex(1)

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


def _bits(df, assessment, population):
    """Bits needed, per attribute (name, median) and remaining per record; None if it fails."""
    from .explain import information_bits
    try:
        needed, parts, remaining = information_bits(df, assessment, population)
    except Exception:  # noqa: BLE001 (the picture is optional; the assessment stands)
        return None
    return needed, [(b.column, b.median) for b in parts], remaining


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    w = MainWindow()
    w.show()
    if len(sys.argv) > 1:
        w.load(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
