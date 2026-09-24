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
