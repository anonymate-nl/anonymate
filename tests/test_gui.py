import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from anonymate import Population, synthetic  # noqa: E402
from anonymate.gui import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_for(app, condition, timeout=120):
    end = time.time() + timeout
    while not condition():
        app.processEvents()
        if time.time() > end:
            raise TimeoutError
        time.sleep(0.05)


def test_open_assess_and_save(app, tmp_path, monkeypatch):
    pop = synthetic.population(20_000, seed=9)
    ds = synthetic.sample(pop, 40, seed=1, gemeente="Zwolle")
    path = tmp_path / "ds.csv"
    ds[["postcode6", "huisnummer", "gemeente", "bouwjaar", "oppervlakte", "energielabel"]] \
        .to_csv(path, index=False)
    w = MainWindow(population_factory=lambda: Population.from_dataframe(pop))
    w.load(path)
    mapping = w.mapping()
    assert mapping["huisnummer"] == "direct"
    assert mapping["bouwjaar"] == "bouwjaar"
    w.columns.cellWidget(0, 2).setCurrentText("(geen)")  # postcode6 not published
    w.scope.setText("gemeente=Zwolle")
    w.p.setValue(0.2)
    w.lock_norm()
    w.run_assess()
    wait_for(app, lambda: w.assessment is not None)
    assert w.results.rowCount() == 40
    assert "records publiceerbaar" in w.summary.toPlainText()

    out = tmp_path / "uit"
    monkeypatch.setattr("anonymate.gui.QFileDialog.getExistingDirectory",
                        lambda *a, **k: str(out))
    monkeypatch.setattr("anonymate.gui.QMessageBox.information", lambda *a, **k: None)
    w.save()
    assert (out / "publiceerbaar.csv").exists()
    assert "huisnummer" not in (out / "publiceerbaar.csv").read_text(encoding="utf-8")


def test_norm_first_and_address_signature(app, tmp_path, monkeypatch):
    from tests.test_publicatie import dataset, make_population
    pop_df, population = make_population()
    ds = dataset(pop_df, list(range(0, 400, 40)))
    path = tmp_path / "ds.csv"
    ds.to_csv(path, index=False)
    w = MainWindow(population_factory=lambda: population)
    w.load(path)
    assert not w.assess_btn.isEnabled()          # the norm is not fixed yet
    w.p.setValue(0.2)
    w.lock_norm()
    assert w.assess_btn.isEnabled() and not w.p.isEnabled()
    w.sig_on.setChecked(True)
    w.koppel.setText("pc,nr")
    w.sig_steps["H"].setValue(50)
    w.run_assess()
    wait_for(app, lambda: w.assessment is not None)
    cols = [w.results.horizontalHeaderItem(j).text() for j in range(w.results.columnCount())]
    assert "adres_H__W_K_1" in cols
    assert set(w.direct) >= {"pc", "nr"}
    w.load(path)                                   # a new dataset: fix the norm again
    assert w.p.isEnabled() and not w.assess_btn.isEnabled()


def test_missing_link_columns_give_a_message(app, tmp_path, monkeypatch):
    from tests.test_publicatie import dataset, make_population
    pop_df, population = make_population()
    path = tmp_path / "ds.csv"
    dataset(pop_df, [0, 1]).to_csv(path, index=False)
    w = MainWindow(population_factory=lambda: population)
    shown = []
    monkeypatch.setattr("anonymate.gui.QMessageBox.warning", lambda *a, **k: shown.append(a))
    w.load(path)
    w.lock_norm()
    w.sig_on.setChecked(True)
    w.koppel.setText("bestaat,niet")
    w.run_assess()
    assert shown and "koppelkolommen" in shown[0][2]


def test_signature_steps_show_units_and_symbols(app):
    from anonymate.gui import _header
    w = MainWindow(population_factory=lambda: None)
    assert w.sig_steps["H"].suffix() == " W/K"
    assert w.sig_steps["C"].suffix() == " Wh/K"
    assert w.sig_steps["tau"].suffix() == " h"
    assert w.sig_steps["Asol"].suffix() == " m²"
    assert _header("stap_tau") == "stap τ [h]"
    assert _header("stap_Asol") == "stap A_sol [m²]"
    assert _header("publiceerbaar_%") == "publiceerbaar_%"
