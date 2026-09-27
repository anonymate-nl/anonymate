"""Where does a weather series come from? Tracing a dataset's weather back to a location.

A dataset without addresses can still reveal where each dwelling is: through the weather that
comes with it. Outdoor temperature (and solar irradiance) per hour differ from place to place,
so a series taken from the nearest KNMI station, or interpolated to a point, is a fingerprint of
that station or point. Whoever has the public KNMI hourly data can match it.

This module plays that attacker. Per dwelling it compares the dataset's series with

* every KNMI station's own series (a dataset that uses the nearest station), and
* the series interpolated to the centre of every H3 cell of level 4 and 5 (a dataset that
  interpolates to a cell centre, possibly after noise), by inverse distance weighting over the
  stations: close to, though not the same as, the radial basis functions a dataset may use,

and picks the best match (smallest root mean square difference). A near-perfect match (below
EXACT_RMS) means the dataset used that station or that cell: the attacker knows it exactly. Else
the best candidate point (level 6, ~36 km²) is where the weather most likely comes from; checked
on real KNMI data, that is typically 5 to 25 km off when the dataset interpolates differently, so
it enters the assessment as a level-5 cell with an uncertainty of APPROX_KM. Hours
are aligned in UTC; because datasets are often in local time, shifts of up to two hours either
way are tried and the best kept. The winning regime and location then enter the assessment as a
hidden-location quasi-identifier: ``weer_knmi_station`` or ``weerzone_h3``.

The KNMI hourly data come from :func:`download_hourly` (``anonymate ingest knmi-uur --jaar``):
the only network step, like every other ingest.
"""
from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

MIN_HOURS = 200          # too few overlapping hours: no verdict
SHIFTS = (0, -1, 1, -2, 2)
EXACT_RMS = 0.05         # °C: a match this close means the same source, not a neighbour
# checked on KNMI 2024 data: a series interpolated differently (4 nearest stations, power 3)
# was placed 6-25 km from its true point (median ~11 km) by the best level-6 point
APPROX_KM = 15.0
PUBLISH_LEVEL = 5


def hourly_path(store, year: int) -> Path:
    return store.raw / f"knmi_uur_{year}.parquet"


def parse_hourly(payload: bytes) -> pd.DataFrame:
    """KNMI hourly JSON -> station, time (UTC, start of the hour), T [°C], Q [W/m²].

    KNMI's hour ``HH`` covers the hour ending at HH UT; T is in 0.1 °C, Q in J/cm² per hour.
    """
    rows = json.loads(payload.decode("utf-8"))
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["station", "time", "T", "Q"])
    time = (pd.to_datetime(df["date"], utc=True).dt.tz_convert(None)
            + pd.to_timedelta(df["hour"].astype(int) - 1, unit="h"))
    return pd.DataFrame({"station": df["station_code"].astype(str), "time": time,
                         "T": pd.to_numeric(df.get("T"), errors="coerce") / 10.0,
                         "Q": pd.to_numeric(df.get("Q"), errors="coerce") * 10000 / 3600})


def download_hourly(store, year: int, *, fetcher=None, progress=lambda m: None) -> Path:
    """KNMI hourly temperature and irradiance of all stations for ``year``, a month per request
    (larger requests are refused)."""
    from .store import KNMI_URL, fetch
    fetcher = fetcher or fetch
    parts = []
    for month in range(1, 13):
        start = f"{year}{month:02d}0101"
        end_day = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
        end = f"{year}{month:02d}{end_day.day:02d}24"
        body = f"start={start}&end={end}&vars=T:Q&stns=ALL&fmt=json".encode()
        parts.append(parse_hourly(fetcher(KNMI_URL, data=body)))
        progress(f"KNMI-uurgegevens {year}-{month:02d}: {len(parts[-1]):,} rijen")
    out = hourly_path(store, year)
    pd.concat(parts, ignore_index=True).to_parquet(out, index=False)
    store.record(f"knmi-uur-{year}", version=str(year), rows=sum(len(p) for p in parts),
                 url=KNMI_URL)
    return out


def load_hourly(store, years) -> pd.DataFrame:
    frames = []
    for y in years:
        p = hourly_path(store, int(y))
        if not p.exists():
            raise FileNotFoundError(f"geen KNMI-uurgegevens voor {y}: draai eerst "
                                    f"'anonymate ingest knmi-uur --jaar {y}'")
        frames.append(pd.read_parquet(p))
    return pd.concat(frames, ignore_index=True)


@dataclass
class Grid:
    """Stations and candidate cells: where interpolated series are made."""
    stations: pd.DataFrame            # knmi_station, lat, lon
    cells: dict[int, list[str]]       # level -> H3 cells


def _km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def interpolate(wide: pd.DataFrame, stations: pd.DataFrame, points: np.ndarray,
                power: float = 2.0) -> np.ndarray:
    """Inverse-distance-weighted series at ``points`` (n x [lat, lon]) from station columns of
    ``wide`` (hours x stations); stations without a value in an hour are left out that hour."""
    pos = stations.set_index("knmi_station").loc[wide.columns, ["lat", "lon"]].to_numpy(float)
    d = _km(points[:, :1], points[:, 1:2], pos[None, :, 0], pos[None, :, 1])   # n x s
    w = 1.0 / np.maximum(d, 0.5) ** power
    values = wide.to_numpy(float)                                                # h x s
    have = ~np.isnan(values)
    num = np.nan_to_num(values) @ w.T                                            # h x n
    den = have.astype(float) @ w.T
    with np.errstate(invalid="ignore", divide="ignore"):
        return num / den


def _rms(a: np.ndarray, b: np.ndarray) -> tuple[float, int]:
    ok = ~(np.isnan(a) | np.isnan(b))
    n = int(ok.sum())
    return (math.sqrt(float(np.mean((a[ok] - b[ok]) ** 2))) if n else math.inf), n


def trace(series: pd.DataFrame, hourly: pd.DataFrame, grid: Grid, *, id_col: str,
          time_col: str, value_col: str, variable: str = "T") -> pd.DataFrame:
    """Per dwelling: the best-matching station and cell per level, and the most likely regime.

    ``series`` is long: one row per dwelling and time. Times with a time zone are converted to
    UTC; naive times are taken as UTC, with shifts of up to two hours tried.
    """
    wide = hourly.pivot_table(index="time", columns="station", values=variable)
    wide = wide[[c for c in wide.columns if c in set(grid.stations["knmi_station"].astype(str))]]
    cell_series = {}
    import h3
    for level, cells in grid.cells.items():
        pts = np.array([h3.cell_to_latlng(c) for c in cells])
        cell_series[level] = (cells, interpolate(wide, grid.stations, pts))
    t = pd.to_datetime(series[time_col], utc=True).dt.tz_convert(None).dt.floor("h")
    s = pd.DataFrame({"id": series[id_col], "time": t,
                      "v": pd.to_numeric(series[value_col], errors="coerce")})
    s = s.groupby(["id", "time"], as_index=False)["v"].mean()
    rows = []
    for home, g in s.groupby("id"):
        best = None
        for shift in SHIFTS:
            v = g.set_index(g["time"] + pd.Timedelta(hours=shift))["v"]
            v = v[~v.index.duplicated()].reindex(wide.index).to_numpy(float)
            n_hours = int((~np.isnan(v)).sum())
            if n_hours < MIN_HOURS:
                continue
            st = [(_rms(v, wide[c].to_numpy(float))[0], c) for c in wide.columns]
            st.sort()
            out = {"woning": home, "uren": n_hours, "verschuiving_uur": shift,
                   "station": st[0][1], "rms_station": st[0][0],
                   "rms_station_2e": st[1][0] if len(st) > 1 else math.inf}
            for level, (cells, mat) in cell_series.items():
                cs = sorted((_rms(v, mat[:, j])[0], cells[j]) for j in range(len(cells)))
                out[f"cel_r{level}"], out[f"rms_r{level}"] = cs[0][1], cs[0][0]
                out[f"rms_r{level}_2e"] = cs[1][0] if len(cs) > 1 else math.inf
            score = min([out["rms_station"]] + [out[f"rms_r{lv}"] for lv in cell_series])
            if best is None or score < best[0]:
                best = (score, out)
        if best is None:
            rows.append({"woning": home, "uren": int(g["v"].notna().sum()),
                         "regime": "onbekend (te weinig uren)"})
            continue
        out = best[1]
        options = [("station", out["station"], out["rms_station"], out["rms_station_2e"])]
        options += [(f"h3_r{lv}", out[f"cel_r{lv}"], out[f"rms_r{lv}"], out[f"rms_r{lv}_2e"])
                    for lv in cell_series]
        regime, where, rms, second = min(options, key=lambda o: o[2])
        # level 6 is only a search grid: a close fit there is a good guess, not the source
        exact = rms < EXACT_RMS and regime in ("station", "h3_r4", "h3_r5")
        if not exact and regime != "station":
            import h3
            level = h3.get_resolution(where)
            where = h3.cell_to_parent(where, min(level, PUBLISH_LEVEL)) \
                if level >= PUBLISH_LEVEL else where
        out.update({"regime": regime, "locatie": where, "rms": rms,
                    "zekerheid": (second / rms) if rms > 0 else math.inf,
                    "exact": exact, "onzekerheid_km": 0.0 if exact else APPROX_KM})
        rows.append(out)
    result = pd.DataFrame(rows)
    result.attrs["stations"] = grid.stations.set_index("knmi_station")[["lat", "lon"]]
    return result


def grid_from(store=None, population=None, levels=(4, 5, 6)) -> Grid:
    """Stations from the store; candidate cells: the cells of each level that hold dwellings."""
    stations = pd.read_parquet(store.raw / "knmi_stations.parquet")
    stations["knmi_station"] = stations["knmi_station"].astype(str)
    cells = {}
    for lv in levels:  # level 6: finer candidate points for series that fit no cell exactly
        col = f"h3_r{lv}"
        if population is not None and col in population.columns:
            cells[lv] = [r[0] for r in population.con.execute(
                f"SELECT DISTINCT {col} FROM {population.relation} WHERE {col} IS NOT NULL"
            ).fetchall()]
    return Grid(stations, cells)


def as_columns(traced: pd.DataFrame) -> pd.DataFrame:
    """The traced location as dataset columns per dwelling: ``weer_knmi_station`` where the
    station fits best, else ``weerzone_h3`` (the best cell)."""
    out = pd.DataFrame({"woning": traced["woning"]})
    regime = traced.get("regime", pd.Series(dtype=object))
    exact = traced.get("exact", pd.Series(True, index=traced.index)).fillna(False)
    station = (regime == "station") & exact
    out["weer_knmi_station"] = np.where(station, traced.get("locatie"), None)
    out["weerzone_h3"] = np.where(regime.notna() & ~station
                                  & ~regime.astype(str).str.startswith("onbekend"),
                                  _as_cell(traced), None)
    out["onzekerheid_km"] = traced.get("onzekerheid_km")
    return out


def _as_cell(traced: pd.DataFrame) -> list:
    """A station that fits only approximately becomes the level-5 cell around it."""
    import h3
    stations = getattr(traced, "attrs", {}).get("stations")
    cells = []
    for regime, loc in zip(traced.get("regime"), traced.get("locatie")):
        if regime == "station" and stations is not None and loc in stations.index:
            la, lo = stations.loc[loc, ["lat", "lon"]]
            cells.append(h3.latlng_to_cell(float(la), float(lo), PUBLISH_LEVEL))
        else:
            cells.append(loc)
    return cells


def read_series(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if p.suffix.lower() == ".parquet":
        return pd.read_parquet(p)
    if p.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(p)
    return pd.read_csv(io.StringIO(p.read_text(encoding="utf-8-sig")), sep=None,
                       engine="python")
