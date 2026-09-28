import json

import h3
import numpy as np
import pandas as pd

from anonymate.weerspoor import Grid, as_columns, interpolate, parse_hourly, trace

STATIONS = pd.DataFrame({"knmi_station": ["A", "B", "C", "D"],
                         "lat": [52.0, 52.0, 53.0, 53.0], "lon": [4.5, 6.5, 4.5, 6.5]})


def hourly(hours=24 * 40, seed=1):
    rng = np.random.default_rng(seed)
    t = pd.date_range("2024-01-01", periods=hours, freq="h")
    base = 5 + 4 * np.sin(np.arange(hours) * 2 * np.pi / 24)
    rows = []
    for st in STATIONS["knmi_station"]:
        own = base + rng.normal(0, 1.5, hours).cumsum() * 0.05 + rng.normal(0, 0.8, hours)
        rows.append(pd.DataFrame({"station": st, "time": t, "T": own, "Q": 0.0}))
    return pd.concat(rows, ignore_index=True)


def long(home, times, values):
    return pd.DataFrame({"woning": home, "tijd": times, "T_buiten": values})


def test_parse_hourly():
    payload = json.dumps([{"station_code": 260, "date": "2024-01-01T00:00:00.000Z", "hour": 1,
                           "T": 67, "Q": 36}]).encode()
    df = parse_hourly(payload)
    assert df["station"][0] == "260"
    assert df["time"][0] == pd.Timestamp("2024-01-01 00:00")
    assert df["T"][0] == 6.7 and round(df["Q"][0], 1) == 100.0


def test_trace_station_cell_and_shift():
    hw = hourly()
    wide = hw.pivot_table(index="time", columns="station", values="T")
    cells = [h3.latlng_to_cell(52.5, 5.5, 5), h3.latlng_to_cell(52.1, 4.6, 5),
             h3.latlng_to_cell(52.9, 6.4, 5)]
    grid = Grid(STATIONS, {5: cells})
    at_cell = interpolate(wide, STATIONS, np.array([h3.cell_to_latlng(cells[0])]))[:, 0]
    series = pd.concat([
        long("uit_station_B", wide.index, wide["B"].to_numpy()),
        long("uit_cel", wide.index, at_cell),
        # local time (UTC+1): the same hours one hour later on the clock
        long("lokale_tijd", wide.index + pd.Timedelta(hours=1), wide["C"].to_numpy()),
    ])
    out = trace(series, hw, grid, id_col="woning", time_col="tijd",
                value_col="T_buiten").set_index("woning")
    assert out.loc["uit_station_B", "regime"] == "station"
    assert out.loc["uit_station_B", "locatie"] == "B"
    assert out.loc["uit_cel", "regime"] == "h3_r5"
    assert out.loc["uit_cel", "locatie"] == cells[0]
    assert out.loc["lokale_tijd", "locatie"] == "C"
    assert out.loc["lokale_tijd", "verschuiving_uur"] == -1
    cols = as_columns(out.reset_index()).set_index("woning")
    assert cols.loc["uit_station_B", "weer_knmi_station"] == "B"
    assert cols.loc["uit_cel", "weerzone_h3"] == cells[0]


def test_too_few_hours():
    hw = hourly()
    wide = hw.pivot_table(index="time", columns="station", values="T")
    series = long("kort", wide.index[:50], wide["A"].to_numpy()[:50])
    out = trace(series, hw, Grid(STATIONS, {}), id_col="woning", time_col="tijd",
                value_col="T_buiten")
    assert out["regime"][0].startswith("onbekend")


# --- the detective: one method for the whole dataset --------------------------------------------
STATIONS6 = pd.DataFrame({"knmi_station": list("ABCDEF"),
                          "lat": [52.0, 52.1, 52.5, 52.6, 53.0, 53.1],
                          "lon": [4.6, 6.4, 5.0, 6.0, 4.8, 6.3]})


def hourly6(hours=24 * 30, seed=3):
    rng = np.random.default_rng(seed)
    t = pd.date_range("2024-01-01", periods=hours, freq="h")
    base = 5 + 4 * np.sin(np.arange(hours) * 2 * np.pi / 24)
    return pd.concat([pd.DataFrame({"station": st, "time": t, "T": base + lat_shift
                                    + rng.normal(0, 1.0, hours), "Q": 0.0})
                      for st, lat_shift in zip(STATIONS6["knmi_station"], range(6))],
                     ignore_index=True)


def cells_in_box(level):
    import h3
    poly = h3.LatLngPoly([(51.9, 4.5), (51.9, 6.5), (53.2, 6.5), (53.2, 4.5)])
    return sorted(h3.polygon_to_cells(poly, level))


def test_investigate_finds_the_grid_and_method():
    from anonymate.weerspoor import Grid, _interp, investigate
    hw = hourly6()
    wide = hw.pivot_table(index="time", columns="station", values="T")
    grid = Grid(STATIONS6, {5: cells_in_box(5), 6: cells_in_box(6)})
    rng = np.random.default_rng(1)
    chosen = list(rng.choice(grid.cells[5], 8, replace=False))
    pts = np.array([h3.cell_to_latlng(c) for c in chosen])
    at = _interp("idw3", wide, STATIONS6, pts)
    series = pd.concat([long(f"w{i}", wide.index, at[:, i]) for i in range(len(chosen))])
    f = investigate(series, hw, grid, id_col="woning", time_col="tijd", value_col="T_buiten",
                    methods=("idw2", "idw3", "rbf_multiquadric"))
    top = f.hypotheses.iloc[0]
    assert (top["methode"], top["niveau"], top["verklaard"]) == ("idw3", 5, 8)
    assert list(f.per_home.sort_values("woning")["locatie"]) == chosen
    assert "niveau 5" in f.verdict


def test_investigate_nearest_station():
    from anonymate.weerspoor import Grid, investigate
    hw = hourly6()
    wide = hw.pivot_table(index="time", columns="station", values="T")
    series = pd.concat([long(f"w{st}", wide.index, wide[st].to_numpy()) for st in "ABE"])
    f = investigate(series, hw, Grid(STATIONS6, {5: cells_in_box(5)}), id_col="woning",
                    time_col="tijd", value_col="T_buiten", methods=("idw2",))
    assert f.hypotheses.iloc[0]["hypothese"].startswith("dichtstbij")
    assert set(f.per_home["locatie"]) == {"A", "B", "E"}


def test_investigate_own_location():
    from anonymate.weerspoor import Grid, _interp, investigate
    hw = hourly6()
    wide = hw.pivot_table(index="time", columns="station", values="T")
    homes = np.array([[52.31, 5.37], [52.77, 5.62], [52.44, 6.11]])   # not cell centres
    at = _interp("idw2", wide, STATIONS6, homes)
    series = pd.concat([long(f"w{i}", wide.index, at[:, i]) for i in range(3)])
    grid = Grid(STATIONS6, {5: cells_in_box(5), 6: cells_in_box(6)})
    f = investigate(series, hw, grid, id_col="woning", time_col="tijd", value_col="T_buiten",
                    methods=("idw2",), search_km=12)
    assert "eigen" in f.hypotheses.iloc[-1]["hypothese"]
    assert f.per_home["regime"].eq("punt").all()
    for (la, lo), cell in zip(homes, f.per_home.sort_values("woning")["locatie"]):
        clat, clon = h3.cell_to_latlng(cell)
        assert abs(clat - la) * 111 < 1.5 and abs(clon - lo) * 68 < 1.5
    assert "0.5 km" in f.verdict or "0,5" in f.verdict or "~0.5" in f.verdict


# --- reading series the way datasets ship them --------------------------------------------------
def test_read_zip_with_a_file_per_home(tmp_path):
    import zipfile
    from anonymate.weerspoor import read_series_source
    z = tmp_path / "dataset_openbaar.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for home in ("101", "202"):
            text = "datetime;temp_buiten__degC;e_use\n2024-01-01 00:00;5.1;1\n2024-01-01 01:00;4.9;2\n"
            zf.writestr(f"dataset/IM_customer_{home}.csv", text)
        zf.writestr("dataset/metadata.csv", "a,b\n1,2\n")
    out = read_series_source(z, id_from="bestand", pattern="IM_customer_*.csv")
    assert sorted(out["woning"].unique()) == ["101", "202"]
    assert list(out.columns) == ["woning", "tijd", "waarde"] and len(out) == 4


def test_read_hive_folder_and_folder_per_home(tmp_path):
    from anonymate.weerspoor import read_series_source
    hive = tmp_path / "boiler_temp"
    hive.mkdir()
    for home in ("WU1", "WU2"):
        pd.DataFrame({"tijdstip": pd.date_range("2024-01-01", periods=3, freq="h"),
                      "T_out": [1.0, 2.0, 3.0]}).to_parquet(hive / f"home_id={home}.parquet")
    out = read_series_source(hive, id_from="bestand")
    assert sorted(out["woning"].unique()) == ["WU1", "WU2"]
    for home in ("7", "8"):
        d = tmp_path / "per_woning" / f"woning_{home}"
        d.mkdir(parents=True)
        (d / "knmi.csv").write_text("timestamp,T\n2024-01-01T00:00,3.0\n", encoding="utf-8")
    out = read_series_source(tmp_path / "per_woning", id_from="map", pattern="knmi.csv")
    assert sorted(out["woning"].unique()) == ["7", "8"]


def test_read_long_table_with_sample(tmp_path):
    from anonymate.weerspoor import read_series_source
    p = tmp_path / "derived.parquet"
    pd.DataFrame({"home_id__str": [f"h{i}" for i in range(10) for _ in range(2)],
                  "tijdstip_start": list(pd.date_range("2024-01-01", periods=2, freq="h")) * 10,
                  "temp_buiten__degC": 1.0}).to_parquet(p)
    out = read_series_source(p, max_homes=4)
    assert out["woning"].nunique() == 4


# --- time keeping, station switches, suspicious stations ----------------------------------------
def hourly6_from(start, days, seed=5):
    rng = np.random.default_rng(seed)
    t = pd.date_range(start, periods=24 * days, freq="h")
    base = 5 + 4 * np.sin(np.arange(len(t)) * 2 * np.pi / 24)
    return pd.concat([pd.DataFrame({"station": st, "time": t, "T": np.round(
        base + k + rng.normal(0, 1.0, len(t)), 1), "Q": 0.0})
        for st, k in zip(STATIONS6["knmi_station"], range(6))], ignore_index=True)


def test_local_clock_time_across_the_march_switch():
    from anonymate.weerspoor import Grid, investigate
    hw = hourly6_from("2024-03-10", 40)
    wide = hw.pivot_table(index="time", columns="station", values="T")
    local = wide.index.tz_localize("UTC").tz_convert("Europe/Amsterdam").tz_localize(None)
    series = pd.concat([long(f"w{st}", local, wide[st].to_numpy()) for st in "ACE"])
    f = investigate(series, hw, Grid(STATIONS6, {5: cells_in_box(5)}), id_col="woning",
                    time_col="tijd", value_col="T_buiten", methods=("idw2",))
    assert f.hypotheses.iloc[0]["verklaard"] == 3
    assert set(f.per_home["locatie"]) == {"A", "C", "E"}
    assert any("kloktijd zonder tijdzone" in x for x in f.findings)


def test_station_switch_gives_the_border_strip():
    from anonymate.weerspoor import Grid, investigate
    hw = hourly6_from("2024-01-01", 60)
    wide = hw.pivot_table(index="time", columns="station", values="T")
    half = wide.index < "2024-02-01"
    switching = np.where(half, wide["A"], wide["C"])
    series = pd.concat([long("wissel", wide.index, switching),
                        long("vast", wide.index, wide["E"].to_numpy())])
    grid = Grid(STATIONS6, {5: cells_in_box(5), 6: cells_in_box(6)})
    f = investigate(series, hw, grid, id_col="woning", time_col="tijd", value_col="T_buiten",
                    methods=("idw2",))
    row = f.per_home.set_index("woning").loc["wissel"]
    assert row["regime"] == "grensstrook"
    assert all(h3.get_resolution(c) == 6 for c in row["locatie"].split("|"))
    assert any("Stationswissel" in x for x in f.findings)


def test_suspicious_station_is_widened_to_the_region():
    from anonymate import Population
    from anonymate.weerspoor import check_assignment
    pop = Population.from_dataframe(pd.DataFrame({
        "postcode4": ["8011"] * 5 + ["1011"] * 5,
        "knmi_station": ["278"] * 4 + ["290"] + ["240"] * 5}))
    dataset = pd.DataFrame({"id": ["a", "b"], "postcode4": ["8011", "1011"]})
    per_home = pd.DataFrame({"woning": ["a", "b"], "regime": ["station", "station"],
                             "locatie": ["278", "310"]})
    stations, notes = check_assignment(dataset, "id", per_home, pop, STATIONS6)
    assert stations.iloc[0] == "278"
    assert stations.iloc[1] == "240|310"
    assert len(notes) == 1 and "Verdacht station" in notes[0]


def test_investigate_knows_the_station_set_of_the_weather_library():
    """Interpolating temperature only from stations that also measure irradiance (as the
    NeedForHeat library does when both are asked) is its own hypothesis."""
    from anonymate.weerspoor import Grid, _interp, investigate
    hw = hourly6_from("2024-01-01", 30)
    hw.loc[hw["station"] == "B", "Q"] = np.nan              # B measures no irradiance
    hw.loc[hw["station"] != "B", "Q"] = 1.0
    wide = hw.pivot_table(index="time", columns="station", values="T")
    grid = Grid(STATIONS6, {5: cells_in_box(5)})
    chosen = list(np.random.default_rng(2).choice(grid.cells[5], 6, replace=False))
    pts = np.array([h3.cell_to_latlng(c) for c in chosen])
    without_b = wide.drop(columns="B")
    at = _interp("idw2", without_b, STATIONS6, pts)
    series = pd.concat([long(f"w{i}", wide.index, at[:, i]) for i in range(len(chosen))])
    f = investigate(series, hw, grid, id_col="woning", time_col="tijd", value_col="T_buiten",
                    methods=("idw2",))
    top = f.hypotheses.iloc[0]
    assert top["methode"] == "idw2+Q" and top["verklaard"] == 6
    assert "straling" in f.verdict
