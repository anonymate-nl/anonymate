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
