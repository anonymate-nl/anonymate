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

        cols_box = QGroupBox("2. Kolommen: controleer de voorstellen")
        cl = QVBoxLayout(cols_box)
        self.columns = QTableWidget(0, 4)
        self.columns.setHorizontalHeaderLabels(["kolom", "voorstel", "behandelen als", "reden"])
        self.columns.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.columns.horizontalHeader().setStretchLastSection(True)
        cl.addWidget(self.columns)
        splitter.addWidget(cols_box)

        settings = QGroupBox("3. Instellingen")
        form = QFormLayout(settings)
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
        form.addRow("maximale kans op heridentificatie p", prow)
        self.scenario = QComboBox()
        self.scenario.addItem("openbare registers (BAG, EP-online)", "register")
        self.scenario.addItem("+ zichtbaar van buitenaf", "zichtbaar")
        self.scenario.addItem("+ insiderkennis (installateur, leverancier, buren)", "insider")
        form.addRow("aanvaller weet", self.scenario)
        self.scope = QLineEdit()
        self.scope.setPlaceholderText("bv.  gemeente=Zwolle,Deventer; oppervlakte=50-250; "
                                      "eengezins=true")
        form.addRow("populatie-afbakening", self.scope)
        self.synthetic = QCheckBox("synthetische populatie gebruiken (alleen om te proberen)")
        form.addRow("", self.synthetic)
        buttons = QHBoxLayout()
        self.assess_btn = QPushButton("4. Toetsen")
        self.assess_btn.clicked.connect(self.run_assess)
        self.suggest_btn = QPushButton("Generalisaties zoeken")
        self.suggest_btn.clicked.connect(self.run_suggest)
        self.save_btn = QPushButton("5. Opslaan…")
        self.save_btn.clicked.connect(self.save)
        for b in (self.assess_btn, self.suggest_btn, self.save_btn):
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

    def _set_busy(self, busy: bool) -> None:
        has = self.df is not None
        self.assess_btn.setEnabled(has and not busy)
        self.suggest_btn.setEnabled(has and not busy)
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

    def _inputs(self):
        qids, direct = qids_from(self.df, self.mapping(), auto=False)
        threshold = Threshold(round(self.p.value(), 2))
        scenario = SCENARIOS[self.scenario.currentData()]
        population = self.population()
        pairs = [p.strip() for p in self.scope.text().split(";") if p.strip()]
        scope = parse_scope(_scope_from_args(pairs), population)
        if not scope.is_everything():
            population = population.within(scope)
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
        qids, direct, threshold, scenario, population = self._inputs()
        df = self.df
        self.direct = direct
        self.steps = None

        def work():
            return df, assess(df, qids, population, threshold, scenario)
        self._run(work, self._show_assessment)

    def run_suggest(self) -> None:
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
              dataset_name=self.path.name if self.path else "dataset")
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
