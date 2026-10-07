import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
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


def test_weather_location_from_gps(app, tmp_path):
    import h3
    import pandas as pd
    from anonymate.gui import WEATHER_H3
    pop = synthetic.population(5_000, seed=2)
    df = pd.DataFrame({"gps_lat": [52.51, 52.09, 53.21], "gps_lon": [6.09, 5.12, 6.56],
                       "bouwjaar": [1970, 1985, 2001]})
    path = tmp_path / "gps.csv"
    df.to_csv(path, index=False)
    w = MainWindow(population_factory=lambda: Population.from_dataframe(pop))
    w.load(path)
    assert w.w_source.currentData() == "gps"
    assert (w.w_lat.currentText(), w.w_lon.currentText()) == ("gps_lat", "gps_lon")
    w.w_h3.setChecked(True)
    w.w_level.setValue(5)
    w.w_sigma.setValue(10)
    w.apply_weather()
    cells = w.df[WEATHER_H3]
    assert all(h3.get_resolution(c) == 5 for c in cells)
    assert w.weather_tolerance == 10
    mapping = w.mapping()
    assert mapping[WEATHER_H3] == "h3_cel"
    assert mapping["gps_lat"] == "direct" and mapping["gps_lon"] == "direct"
    first = list(cells)
    w.apply_weather()                     # the noise is drawn once per dataset
    assert list(w.df[WEATHER_H3]) == first


def test_uhi_without_file_comes_from_the_population(app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from anonymate.gui import UHI
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    w = MainWindow()
    w.start_practice()                   # the practice population has a uhi column
    assert "uhi__degC" in w.population().columns
    w.w_none.setChecked(True)
    w.w_uhi.setChecked(True)
    assert not w.w_uhi_file.text()
    w.apply_weather()
    assert UHI in w.df.columns and w.df[UHI].notna().any()
    assert w.uhi_path is None
    assert w._with_uhi(w.population()) is w.population()   # the population has it itself
    # a population without UHI and no file: a clear message, no column
    from anonymate import voorbeeld
    bare = Population.from_dataframe(voorbeeld.population().drop(columns=["uhi__degC"]))
    w.df = w.df.drop(columns=[UHI])
    w._population = None
    w.population_factory = lambda: bare
    w.apply_weather()
    assert UHI not in w.df.columns
    assert "geen UHI" in w.summary.toPlainText()


def test_region_scope(app):
    w = MainWindow(population_factory=lambda: None)
    assert w._region_scope() == {}
    w.region_all.setChecked(False)
    w.region_boxes["Utrecht"].setChecked(True)
    w.region_municipalities.setText("Zwolle, Deventer")
    assert w._region_scope() == {"provincie": ["Utrecht"], "gemeente": ["Zwolle", "Deventer"]}


def test_read_uhi(tmp_path):
    import pandas as pd
    from anonymate.gui import _read_uhi
    path = tmp_path / "uhi.csv"
    pd.DataFrame({"pc6": ["1234 ab", "5678CD"], "uhi__degC": [0.4, 1.7]}).to_csv(path, index=False)
    assert _read_uhi(str(path)) == {"1234AB": 0.4, "5678CD": 1.7}


def test_traced_weather_joins_into_dataset(app, tmp_path):
    import pandas as pd
    from anonymate.gui import WEATHER_H3, WEATHER_STATION
    path = tmp_path / "ds.csv"
    pd.DataFrame({"id": ["a", "b", "c"], "bouwjaar": [1970, 1985, 2001]}).to_csv(path, index=False)
    w = MainWindow(population_factory=lambda: None)
    w.load(path)
    w.t_key.addItems(["id", "bouwjaar"])
    w.t_key.setCurrentText("id")
    traced = pd.DataFrame({"woning": ["a", "b", "c"],
                           "regime": ["station", "h3_r5", "onbekend (te weinig uren)"],
                           "locatie": ["260", "85196807fffffff", None]})
    w._show_trace(traced)
    assert list(w.df[WEATHER_STATION]) == ["260", None, None]
    assert list(w.df[WEATHER_H3]) == [None, "85196807fffffff", None]
    mapping = w.mapping()
    assert mapping[WEATHER_STATION] == "knmi_station" and mapping[WEATHER_H3] == "h3_cel"


def test_link_columns_are_filled_and_the_h3_cell_is_proposed(app, tmp_path):
    w = MainWindow(population_factory=lambda: None)
    w.load("docs/voorbeeld/woningen.csv")
    assert w.koppel.text() == "postcode,huisnummer"
    assert w.w_h3.isChecked() and w.w_lat.currentText() == ""
    # nothing to find the dwelling with: no weather location
    path = tmp_path / "kaal.csv"
    path.write_text("bouwjaar,oppervlakte\n1970,100\n1980,120\n")
    w.load(path)
    assert w.koppel.text() == "" and w.w_none.isChecked()


def test_voronoi_cells_hold_their_own_station():
    import pandas as pd
    from anonymate.gui_kaart import voronoi
    st = pd.DataFrame({"knmi_station": ["A", "B", "C"], "lat": [52.0, 52.0, 53.0],
                       "lon": [4.5, 6.5, 5.5]})
    cells = voronoi(st, (4.0, 51.5, 7.0, 53.5))
    for name, poly in cells.items():
        lats, lons = [p[0] for p in poly], [p[1] for p in poly]
        row = st[st["knmi_station"] == name].iloc[0]
        assert min(lats) <= row["lat"] <= max(lats) and min(lons) <= row["lon"] <= max(lons)


def test_signature_with_synthetic_population_is_switched_off(app):
    w = MainWindow(population_factory=lambda: None)
    w.sig_on.setChecked(True)
    w.synthetic.setChecked(True)
    assert not w.sig_on.isChecked() and not w.sig_on.isEnabled()


def test_simplify_keeps_a_closed_ring_recognisable():
    import math
    from anonymate.store import simplify
    ring = [(math.cos(t / 100 * 2 * math.pi), math.sin(t / 100 * 2 * math.pi)) for t in range(101)]
    out = simplify(ring, 0.01)
    assert 8 <= len(out) < len(ring)


def test_suggest_reports_progress_and_can_be_adopted(app, tmp_path, monkeypatch):
    import anonymate.gui as g
    monkeypatch.setattr(g.QMessageBox, "warning", lambda *a, **k: None)
    pop = Population.from_dataframe(synthetic.population(200_000, seed=3))
    w = MainWindow(population_factory=lambda: pop)
    w.load("docs/voorbeeld/woningen.csv")
    w.lock_norm()
    seen = []
    w._on_progress = lambda f, t: seen.append((f, t))   # the worker reports here
    w.run_suggest()
    wait_for(app, lambda: w.steps is not None and not any(t.isRunning() for t in w._threads))
    assert w.adopt_btn.isEnabled() and w.gen_steps.count() == len(w.steps)
    assert any(f is not None and f > 0 for f, _ in seen)
    before = w.df.copy()
    w.gen_steps.setCurrentRow(len(w.steps) - 1)
    w.adopt()
    assert not w.df.equals(before)                      # the dataset got the generalisation
    wait_for(app, lambda: w.assessment is not None and not any(t.isRunning() for t in w._threads))


def test_practice_mode_opens_the_example_and_stops_cleanly(app, monkeypatch):
    import anonymate.gui as g
    from anonymate import voorbeeld
    monkeypatch.setattr(g, "_practice_population", lambda: None)
    w = MainWindow()
    w.start_practice()
    assert w.synthetic.isChecked() and not w.practice_banner.isHidden()
    assert len(w.df) == 62 and w.path == voorbeeld.WONINGEN
    assert w.t_file.text() == str(voorbeeld.WEER) and w.t_key.currentText() == voorbeeld.KEY
    assert w.t_time.currentText() == "tijd"
    w.stop_practice()
    assert not w.synthetic.isChecked() and w.practice_banner.isHidden()


def test_example_weather_names_its_cells():
    from anonymate import voorbeeld, synthetic as syn
    from anonymate.weerspoor import investigate, read_series_source
    series = read_series_source(voorbeeld.WEER, id_col="woning_id", time_col="tijd",
                                value_col="buitentemperatuur__degC", max_homes=20)
    found = investigate(series, voorbeeld.hourly(), voorbeeld.grid(levels=(4,)),
                        id_col="woning", time_col="tijd", value_col="waarde",
                        methods=("idw1", "idw2"))
    assert "niveau 4 (idw2)" in found.verdict
    # the example dwellings are dwellings of the made-up Netherlands, with a place on the map
    pop = syn.with_places(syn.population(2_000))
    assert pop["lat__degN"].between(51, 54).all() and pop["h3_r4__str"].notna().all()


def test_gps_columns_are_guessed_by_whole_word():
    import re
    from anonymate.gui import GPS_LAT, GPS_LON
    assert not re.search(GPS_LAT, "installatiedatum", re.I)
    assert not re.search(GPS_LON, "salon_m2", re.I)
    assert re.search(GPS_LAT, "gps_lat", re.I) and re.search(GPS_LON, "Longitude", re.I)


def test_map_accepts_a_population_without_stations():
    from anonymate.gui_kaart import MapData
    pop = Population.from_dataframe(synthetic.with_places(synthetic.population(3_000)))
    data = MapData(pop, None)
    assert data.base and all(s is None for _, _, s, _ in data.base)


def test_practice_holds_a_home_on_the_sea_coast_and_one_on_vlieland():
    import numpy as np
    import pandas as pd
    from anonymate import voorbeeld
    extra = voorbeeld.extra_areas()
    coast = extra[extra["gemeente__cat"] == "Schagen"]
    assert (coast["h3_r4__str"] == voorbeeld.KUSTCEL).all() and 40 <= len(coast) <= 100
    st = voorbeeld.stations()
    island = extra[extra["gemeente__cat"] == "Vlieland"]
    nearest = {st.iloc[int(np.argmin(np.hypot(st["lat"] - a, (st["lon"] - b) * 0.6)))]["knmi_station"]
               for a, b in zip(island["lat__degN"], island["lon__degE"])}
    assert nearest == {"242"}
    ds = pd.read_csv(voorbeeld.WONINGEN, dtype=str)
    assert set(ds["gemeente"]) >= {"Schagen", "Vlieland"}
    assert set(ds["postcode"]) & set(coast["postcode6__str"]) and set(ds["postcode"]) & set(island["postcode6__str"])


def test_norm_button_locks_and_continues_and_nothing_passes_step_2_unlocked(app):
    from anonymate.gui import LOCK_TEXT, LOCKED_TEXT
    pop = Population.from_dataframe(synthetic.population(20_000, seed=3))
    w = MainWindow(population_factory=lambda: pop)
    assert not w.lock_btn.isEnabled()                    # no dataset yet: nothing to fix
    w.go(4)
    assert w.step_list.currentRow() == 0                 # the rail does not go past the norm
    w.load("docs/voorbeeld/woningen.csv")
    assert w.step_list.currentRow() == 1 and w.lock_btn.text() == LOCK_TEXT
    assert w.lock_btn.isEnabled() and not w.norm_locked
    for i in range(2, 7):
        assert not w.step_list.item(i).flags() & Qt.ItemIsEnabled
        w.go(i)
        assert w.step_list.currentRow() == 1 and w.pages.currentIndex() == 1
    w.lock_btn.click()                                   # one button: lock and go on
    assert w.norm_locked and w.step_list.currentRow() == 2
    assert w.lock_btn.text() == LOCKED_TEXT and w.lock_btn.isEnabled()
    assert not w.p.isEnabled()
    w.go(1)
    w.lock_btn.click()                                   # locked: it only navigates
    assert w.norm_locked and w.step_list.currentRow() == 2
    w.go(4)
    assert w.step_list.currentRow() == 4
    w.load("docs/voorbeeld/woningen.csv")                # a new dataset: the norm is open again
    assert not w.norm_locked and w.lock_btn.text() == LOCK_TEXT
    w.go(3)
    assert w.step_list.currentRow() == 1


def test_numeric_columns_are_right_aligned(app):
    pop = Population.from_dataframe(synthetic.population(20_000, seed=3))
    w = MainWindow(population_factory=lambda: pop)
    w.load("docs/voorbeeld/woningen.csv")
    w.lock_norm()
    w.run_assess()
    wait_for(app, lambda: w.assessment is not None)
    cols = [w.results.horizontalHeaderItem(j).text() for j in range(w.results.columnCount())]
    right = Qt.AlignRight | Qt.AlignVCenter
    for name, numeric in (("k", True), ("status", False), ("redenen", False)):
        j = cols.index(name)
        assert bool(w.results.item(0, j).textAlignment() & Qt.AlignRight) is numeric
        assert bool(w.results.horizontalHeaderItem(j).textAlignment() & Qt.AlignRight) is numeric
    assert w.results.item(0, cols.index("k")).textAlignment() & right == right


def test_progress_bar_shows_the_shared_time_text(app):
    from anonymate.gui import VoortgangBalk
    bar = VoortgangBalk()
    bar.start("stap 1")
    assert bar.label.text() == "stap 1"      # no fraction: the label only, no time
    assert bar.time.text() == ""
    bar._t0 -= 60                                    # a minute in, halfway: a minute to go
    bar.report(0.5, "stap 2")
    assert bar.label.text() == "stap 2"      # the text on line 1, the time in its own slot
    assert bar.time.text() == "nog ongeveer 1:00"
    assert "bezig" not in bar.label.text()
    bar.report(0.1)                                  # never back
    assert bar.bar.value() == 500
    bar.stop()
    assert not bar.isVisible()


def test_map_band_and_cell_card_before_and_after_the_weather(app, monkeypatch):
    import anonymate.gui as g
    from anonymate import stappen
    monkeypatch.setattr(g, "_practice_population", lambda: None)
    w = MainWindow()
    w.start_practice()
    w._map_data = type("MD", (), {"land_share": lambda self, cell: None})()
    w._weather_view()
    assert not w.map_band.isHidden() and w.map_band.text() == stappen.WEATHER_BAND
    stats = {"niveau": 5, "woningen": 40, "met_buren": 300, "gebied_km2": 210.0, "k_eff": 30.0}
    import h3
    cell = h3.latlng_to_cell(52.78, 4.80, 5)
    w.map.selected = cell
    w._show_cell(cell, {**stats, "cel": cell})
    assert "nog onbekend: voeg eerst de weerlocatie toe" in w.cell_text.text()
    assert "color:#8A93A0" in w.cell_text.text() and "woningen kreeg" not in w.cell_text.text()
    w.df = w.df.assign(**{stappen.WEATHER_H3: [cell] * len(w.df)})
    w._weather_view()
    assert w.map_band.isHidden()
    w._show_cell(cell, {**stats, "cel": cell})
    assert f"{len(w.df)} woningen kreeg deze cel als weerzone" in w.cell_text.text()


def test_stat_tiles_are_greyed_dashes_until_there_is_something_to_show(app):
    w = MainWindow(population_factory=lambda: None)
    assert all(v.text() == "–" and not v.isEnabled() for v in w.stat_values.values())
    w._set_stat("k", "12", "")
    assert w.stat_values["k"].isEnabled()
    w._set_stat("k", "–", "geen match")
    assert not w.stat_values["k"].isEnabled() and w.stat_values["k"].toolTip() == "geen match"


def test_target_field_shows_the_count_and_the_chart_has_two_views(app):
    from anonymate.stappen import TRADEOFF_VIEWS
    w = MainWindow()
    w.load("docs/voorbeeld/woningen.csv")
    assert w.target_spin.value() == 95
    assert w.target_count.text() == "95% van 62 woningen: minstens 59 publiceerbaar"
    w.target_spin.setValue(80)
    assert w.target_count.text() == "80% van 62 woningen: minstens 50 publiceerbaar"
    assert (w.target_spin.minimum(), w.target_spin.maximum()) == (50, 100)
    rows = [("baseline", 40.0, 0.0), ("stap 1", 70.0, 0.1), ("stap 2", 96.0, 0.3)]
    w.tradeoff.resize(600, 340)
    w.tradeoff.set(rows, 80.0)
    for view in TRADEOFF_VIEWS:
        w.tradeoff.set_view(view)
        img = w.tradeoff.grab().toImage()
        assert not img.isNull() and img.width() >= 420
        w.tradeoff.select(1)
    assert [w.view_box.itemData(i) for i in range(w.view_box.count())] == list(TRADEOFF_VIEWS)


# -- populatie opbouwen (docs/werk/ontwerp-ep-online-gui.md) -----------------------------------

@pytest.fixture(autouse=True)
def opbouw_hermetisch(tmp_path, monkeypatch):
    """Own home and downloads (never the developer's .env), and no network."""
    from anonymate import opbouw
    monkeypatch.setenv("ANONYMATE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANONYMATE_DOWNLOADS", str(tmp_path / "downloads"))
    monkeypatch.delenv("EPONLINE_API_KEY", raising=False)
    monkeypatch.setattr(opbouw, "haal_pakket_manifest", lambda fetcher=None: None)


def _afsluiten(dialog):
    for thread in dialog._threads:
        thread.quit()
        thread.wait(3000)


def _dataset(tmp_path, pop):
    ds = synthetic.sample(pop, 40, seed=1, gemeente="Zwolle")
    path = tmp_path / "ds.csv"
    ds[["postcode6", "huisnummer", "gemeente", "bouwjaar", "oppervlakte", "energielabel"]] \
        .to_csv(path, index=False)
    return path


def _toets_klaarzetten(w, path):
    w.load(path)
    w.columns.cellWidget(0, 2).setCurrentText("(geen)")      # postcode6 not published
    w.scope.setText("gemeente=Zwolle")
    w.p.setValue(0.2)
    w.lock_norm()


def test_assessing_without_a_population_opens_the_guidance(app, tmp_path, monkeypatch):
    from anonymate.gui import PopulatieOpbouw
    pop = synthetic.population(20_000, seed=9)
    opened, shown = [], []
    monkeypatch.setattr(PopulatieOpbouw, "exec", lambda self: opened.append(self) or 0)
    monkeypatch.setattr("anonymate.gui.QMessageBox.warning", lambda *a, **k: shown.append(a))
    w = MainWindow()
    _toets_klaarzetten(w, _dataset(tmp_path, pop))
    w.run_assess()
    assert len(opened) == 1 and shown and "geen populatie" in shown[0][2]
    assert w.assessment is None                              # cancelled: no assessment
    _afsluiten(opened[0])


def test_without_ep_online_the_population_is_built_and_assessing_goes_on(app, tmp_path,
                                                                          monkeypatch):
    from anonymate import opbouw
    from anonymate.gui import PopulatieOpbouw
    pop = synthetic.population(20_000, seed=9)
    manifest = {"zip": {"bytes": 1000}}
    monkeypatch.setattr(opbouw, "haal_pakket_manifest", lambda fetcher=None: manifest)
    monkeypatch.setattr(opbouw, "controleer_ruimte", lambda store, m: None)
    uitgevoerd = []

    def voer_uit(stappen, progress, stop=None, **kw):        # builds nothing: writes a population
        uitgevoerd.append([s.naam for s in stappen])
        progress(0.5, "1 van 2: iets")
        from anonymate.store import Store
        pop.to_parquet(Store.open().population_path, index=False)

    monkeypatch.setattr(opbouw, "voer_uit", voer_uit)
    dialogen = []

    def doorloop(d):                                         # what the user does, without the loop
        dialogen.append(d)
        wait_for(app, lambda: d.manifest is not None, timeout=20)
        d.radio_geen.setChecked(True)
        d.verder()
        assert d.stack.currentIndex() == d.OVERZICHT and d.next_btn.isEnabled()
        assert "Datapakket downloaden" in d.overzicht.text()
        d.verder()                                           # Beginnen
        wait_for(app, lambda: d.klaar, timeout=60)
        assert d.geslaagd and d.next_btn.text() == "Sluiten"
        d.verder()                                           # Sluiten
        return 1

    monkeypatch.setattr(PopulatieOpbouw, "exec", doorloop)
    w = MainWindow()
    _toets_klaarzetten(w, _dataset(tmp_path, pop))
    w.run_assess()
    wait_for(app, lambda: w.assessment is not None)
    assert w.results.rowCount() == 40
    assert len(dialogen) == 1 and uitgevoerd == [["Datapakket downloaden en controleren",
                                                   "Populatie en signaturen uitrekenen"]]
    _afsluiten(dialogen[0])


def test_the_key_screen_goes_on_only_after_a_valid_check(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QLineEdit, QMessageBox
    from anonymate import opbouw
    from anonymate.gui import PopulatieOpbouw
    from anonymate.store import Store
    GOED = "de-goede-sleutel-123"

    def controleer(key, fetcher=None):
        if key == GOED:
            return opbouw.Sleutelcontrole(True, "De sleutel is geldig.", "totaal.zip")
        if key == "offline":
            return opbouw.Sleutelcontrole(None, opbouw.NIET_BEREIKBAAR)
        return opbouw.Sleutelcontrole(False, opbouw.SLEUTEL_ONBEKEND)

    monkeypatch.setattr(opbouw, "controleer_sleutel", controleer)
    d = PopulatieOpbouw(Store.open())
    assert d.radio_sleutel.isChecked()                       # the recommended one is preselected
    d.verder()
    assert d.stack.currentIndex() == d.SLEUTEL and not d.next_btn.isEnabled()
    assert d.key_edit.echoMode() == QLineEdit.Password
    d.key_toon.setChecked(True)
    assert d.key_edit.echoMode() == QLineEdit.Normal
    d.key_edit.setText("fout")
    d.controleer()
    wait_for(app, lambda: d.controle is not None, timeout=20)
    assert d.controle.geldig is False and not d.next_btn.isEnabled()
    assert "5 minuten" in d.key_melding.text()
    d.key_edit.setText(GOED)
    assert d.controle is None and not d.next_btn.isEnabled()  # a new key must be checked again
    d.controleer()
    wait_for(app, lambda: d.controle is not None, timeout=20)
    assert d.controle.geldig is True and d.next_btn.isEnabled()
    d.verder()
    assert d.stack.currentIndex() == d.OVERZICHT
    assert "EP-online downloaden" in d.overzicht.text()
    # no network: on only after an explicit warning
    d.terug()
    d.key_edit.setText("offline")
    d.controleer()
    wait_for(app, lambda: d.controle is not None, timeout=20)
    assert d.controle.geldig is None and d.next_btn.isEnabled()
    monkeypatch.setattr("anonymate.gui.QMessageBox.question", lambda *a, **k: QMessageBox.No)
    d.verder()
    assert d.stack.currentIndex() == d.SLEUTEL
    monkeypatch.setattr("anonymate.gui.QMessageBox.question", lambda *a, **k: QMessageBox.Yes)
    d.verder()
    assert d.stack.currentIndex() == d.OVERZICHT
    # the key is in no setting
    settings = QSettings("anonymate", "anonymate")
    assert not any(GOED in str(settings.value(k)) for k in settings.allKeys())
    _afsluiten(d)


def test_the_population_card_says_why_in_practice_mode_and_is_hidden_with_a_factory(app):
    from anonymate.gui import OEFEN_POPULATIE
    w = MainWindow()
    w._refresh_pop_card()
    assert not w.pop_card.isHidden()
    assert w.pop_regel.text() == "Nog geen populatie op deze computer"
    assert w.pop_btn.text() == "Populatie opbouwen…" and w.pop_btn.isEnabled()
    w.synthetic.setChecked(True)
    assert not w.pop_card.isHidden() and not w.pop_btn.isEnabled()
    assert w.pop_regel.text() == OEFEN_POPULATIE
    w.synthetic.setChecked(False)
    assert w.pop_btn.isEnabled() and w.pop_regel.text() == "Nog geen populatie op deze computer"
    assert MainWindow(population_factory=lambda: None).pop_card.isHidden()


def test_rounded_column_gets_a_reading_and_the_other_reading_in_the_report(app, tmp_path,
                                                                           monkeypatch):
    from PySide6.QtWidgets import QComboBox
    pop = synthetic.population(20_000, seed=9)
    ds = synthetic.sample(pop, 40, seed=1, gemeente="Zwolle")
    ds["bouwjaar"] = (ds["bouwjaar"] / 5).round().astype(int) * 5
    path = tmp_path / "afgerond.csv"
    ds[["bouwjaar", "oppervlakte"]].to_csv(path, index=False)
    w = MainWindow(population_factory=lambda: Population.from_dataframe(pop))
    w.load(path)
    row = w._row_of("bouwjaar")
    box = w.columns.cellWidget(row, 3)
    assert isinstance(box, QComboBox)
    assert box.currentText() == "afgerond op 5, naar het dichtstbij"
    assert "veelvouden van 5" in box.toolTip()
    assert w.lezing("bouwjaar").stap == 5
    assert w.lezing("oppervlakte") is None
    w.columns.cellWidget(row, 2).setCurrentText("(geen)")    # not a QID: no reading
    assert w.columns.cellWidget(row, 3) is None
    w.columns.cellWidget(row, 2).setCurrentText("bouwjaar")
    w.scope.setText("gemeente=Zwolle")
    w.p.setValue(0.2)
    w.lock_norm()
    w.run_assess()
    wait_for(app, lambda: w.assessment is not None)
    assert "bouwjaar gelezen als: afgerond op 5" in w.summary.toPlainText()
    out = tmp_path / "uit"
    monkeypatch.setattr("anonymate.gui.QFileDialog.getExistingDirectory",
                        lambda *a, **k: str(out))
    monkeypatch.setattr("anonymate.gui.QMessageBox.information", lambda *a, **k: None)
    w.save()
    assert "met afgerond op 5, naar beneden" in (out / "rapport.md").read_text(encoding="utf-8")
