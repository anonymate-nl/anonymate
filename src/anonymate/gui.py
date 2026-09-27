"""Desktop window for people who do not use a terminal.

A plain local Qt application: no web server, no network port. It drives the same library
functions as the CLI, in the same order:

1. open a dataset; the detected role of every column is shown and can be changed;
2. choose threshold p, attacker scenario and population scope;
3. assess, optionally search generalisations;
4. save publishable data and reports.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
                               QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import __version__
from .cli import SCENARIOS, _scope_from_args, parse_scope, qids_from, read_dataset
from .detect import Role, derive_h3_columns, detect
from .generalize import suggest
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
STATUS_COLOURS = {Status.OK: "#d8f0d8", Status.AT_RISK: "#f8d7d4", Status.NO_MATCH: "#f5ecc8"}


def _g(x) -> str:
    return "–" if x is None else f"{x:.3g}"


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


class MainWindow(QMainWindow):
    def __init__(self, population_factory=None):
        super().__init__()
        self.setWindowTitle(f"anonymate {__version__}: herleidbaarheidstoets")
        self.resize(1200, 800)
        self.population_factory = population_factory
        self._population: Population | None = None
        self.df: pd.DataFrame | None = None
        self.path: Path | None = None
        self.assessment = None
        self.steps = None
        self.current_df = None
        self._threads: list[QThread] = []

        central = QWidget()
        layout = QVBoxLayout(central)
        self.setCentralWidget(central)

        # 1. dataset
        top = QHBoxLayout()
        self.open_btn = QPushButton("1. Dataset openen…")
        self.open_btn.clicked.connect(self.choose_file)
        self.file_label = QLabel("nog geen bestand gekozen")
        top.addWidget(self.open_btn)
        top.addWidget(self.file_label, 1)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter, 1)

        # 2. the norm first: ethically and legally it is fixed before looking at any outcome
        norm = QGroupBox("2. Privacynorm — eerst vaststellen, vóór je naar uitkomsten kijkt")
        nf = QFormLayout(norm)
        self.p = QDoubleSpinBox()
        self.p.setRange(P_MIN, P_MAX)
        self.p.setSingleStep(0.01)
        self.p.setDecimals(2)
        self.p.setValue(P_DEFAULT)
        self.p.valueChanged.connect(self._update_k)
        self.k_label = QLabel()
        prow = QHBoxLayout()
        prow.addWidget(self.p)
        prow.addWidget(self.k_label, 1)
        nf.addRow("maximale kans op heridentificatie p", prow)
        self.lock_btn = QPushButton("Norm vastleggen")
        self.lock_btn.clicked.connect(self.lock_norm)
        self.lock_label = QLabel("nog niet vastgelegd: toetsen kan pas daarna")
        lrow = QHBoxLayout()
        lrow.addWidget(self.lock_btn)
        lrow.addWidget(self.lock_label, 1)
        nf.addRow(lrow)
        splitter.addWidget(norm)

        cols_box = QGroupBox("3. Kolommen: controleer de voorstellen")
        cl = QVBoxLayout(cols_box)
        self.columns = QTableWidget(0, 4)
        self.columns.setHorizontalHeaderLabels(["kolom", "voorstel", "behandelen als", "reden"])
        self.columns.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.columns.horizontalHeader().setStretchLastSection(True)
        cl.addWidget(self.columns)
        splitter.addWidget(cols_box)

        # 4. optional: an address-based heat performance signature as published baseline
        sig_box = QGroupBox("4. Adresgebaseerde warmteprestatiesignatuur meepubliceren "
                            "(optioneel)")
        sf = QFormLayout(sig_box)
        self.sig_on = QCheckBox("per woning een uit het adres berekende signatuur toevoegen, "
                                "afgerond; het adres zelf wordt nooit gepubliceerd")
        sf.addRow(self.sig_on)
        self.koppel = QLineEdit()
        self.koppel.setPlaceholderText("postcode,huisnummer  (of één kolom met BAG-ID)")
        sf.addRow("koppelkolommen", self.koppel)
        self.sig_method = QComboBox()
        for m, label in (("passend", "passend: per woning ep (met label) of best"),
                         ("ep", "ep: schil en isolatie uit het energielabel"),
                         ("best", "best: huidige staat, gekalibreerd op het label"),
                         ("mwa", "mwa: bouwstaat met Maatwerkadvies-correcties"),
                         ("nta8800", "nta8800: bouwstaat, forfaitair")):
            self.sig_method.addItem(label, m)
        sf.addRow("methode", self.sig_method)
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
        sf.addRow("afrondstappen (0 = niet)", srow)
        items = [f"{sym}: {meaning}" for sym, _, meaning in SIGNATURE_OUTPUTS.values()]
        legend = QLabel(" · ".join(items[:2]) + "<br>" + " · ".join(items[2:]))
        legend.setTextFormat(Qt.RichText)
        legend.setWordWrap(True)
        legend.setStyleSheet("color: gray")
        sf.addRow(legend)
        splitter.addWidget(sig_box)

        settings = QGroupBox("5. Aanvaller en afbakening")
        form = QFormLayout(settings)
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
        buttons = QHBoxLayout()
        self.assess_btn = QPushButton("6. Toetsen")
        self.assess_btn.clicked.connect(self.run_assess)
        self.explore_btn = QPushButton("Afronding verkennen")
        self.explore_btn.clicked.connect(self.run_explore)
        self.suggest_btn = QPushButton("Generalisaties zoeken")
        self.suggest_btn.clicked.connect(self.run_suggest)
        self.save_btn = QPushButton("7. Opslaan…")
        self.save_btn.clicked.connect(self.save)
        for b in (self.assess_btn, self.explore_btn, self.suggest_btn, self.save_btn):
            buttons.addWidget(b)
        form.addRow(buttons)
        splitter.addWidget(settings)

        res_box = QGroupBox("Uitkomst")
        rl = QVBoxLayout(res_box)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(140)
        rl.addWidget(self.summary)
        self.results = QTableWidget(0, 0)
        rl.addWidget(self.results, 1)
        splitter.addWidget(res_box)

        self._update_k()
        self._set_busy(False)

    # -------------------------------------------------------------------------------------------
    def _update_k(self) -> None:
        t = Threshold(round(self.p.value(), 2))
        self.k_label.setText(f"→ elk record moet op minstens {t.k} woningen lijken; "
                             f"hooguit {t.p:.0%} van zo'n groep mag in de dataset zitten")

    def lock_norm(self) -> None:
        """Fix the norm. It stays fixed until a new dataset is opened, so it cannot be tuned to
        the outcome."""
        self.norm_locked = True
        self.p.setEnabled(False)
        self.lock_btn.setEnabled(False)
        t = Threshold(round(self.p.value(), 2))
        self.lock_label.setText(f"vastgelegd: p = {t.p:g} (k ≥ {t.k}); blijft vast voor deze "
                                "dataset")
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        has = self.df is not None
        ready = has and getattr(self, "norm_locked", False) and not busy
        self.assess_btn.setEnabled(ready)
        self.explore_btn.setEnabled(ready)
        self.suggest_btn.setEnabled(ready)
        self.save_btn.setEnabled(self.assessment is not None and not busy)
        self.open_btn.setEnabled(not busy)
        if busy:
            self.summary.setPlainText("bezig…")

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
            self.columns.setCellWidget(i, 2, combo)
            self.columns.setItem(i, 3, QTableWidgetItem(d.reason))
        self._set_busy(False)

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
        QMessageBox.warning(self, "anonymate", message)

    # -------------------------------------------------------------------------------------------
    def run_assess(self) -> None:
        if not getattr(self, "norm_locked", False):
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
            return data, assess(data, all_qids, population, threshold, scenario)
        self._run(work, self._show_assessment)

    def run_explore(self) -> None:
        if not getattr(self, "norm_locked", False):
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
        self._run(work, self._show_table)

    def _show_table(self, table) -> None:
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

    def run_suggest(self) -> None:
        if not getattr(self, "norm_locked", False):
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
            return last.df, assess(last.df, last.qids, population, threshold, scenario), steps
        self._run(work, self._show_suggestion)

    def _show_suggestion(self, result) -> None:
        df, a, steps = result
        self.steps = steps
        self._show_assessment((df, a))
        lines = ["", "Generalisatiestappen:"]
        for s in steps:
            r = s.row()
            lines.append(f"  {r['stap']}: {r['publiceerbaar_%']:.0f}% publiceerbaar, "
                         f"informatieverlies {r['informatieverlies']:.2f}")
        self.summary.appendPlainText("\n".join(lines))

    def _show_assessment(self, result) -> None:
        df, a = result
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
        shown = df[[q.column for q in a.qids]].join(
            a.records[["k", "delta", "status", "redenen"]])
        self.results.setColumnCount(len(shown.columns))
        self.results.setRowCount(len(shown))
        self.results.setHorizontalHeaderLabels([str(c) for c in shown.columns])
        status_col = list(shown.columns).index("status")
        for i, row in enumerate(shown.itertuples(index=False)):
            colour = QColor(STATUS_COLOURS.get(row[status_col], "#ffffff"))
            for j, v in enumerate(row):
                text = "" if v is None or (isinstance(v, float) and pd.isna(v)) else (
                    f"{v:.3g}" if isinstance(v, float) else str(v))
                item = QTableWidgetItem(text)
                item.setBackground(colour)
                self.results.setItem(i, j, item)
        self.results.resizeColumnsToContents()

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


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    w = MainWindow()
    w.show()
    if len(sys.argv) > 1:
        w.load(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
