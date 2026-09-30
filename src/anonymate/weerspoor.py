"""Where does a weather series come from? Tracing a dataset's weather back to a location.

A dataset without addresses can still reveal where each dwelling is: through the weather that
comes with it. Outdoor temperature (and solar irradiance) per hour differ from place to place,
so a series taken from the nearest KNMI station, or interpolated to a point, is a fingerprint of
that station or point. Whoever has the public KNMI hourly data can match it.

This module plays that attacker, in two ways. :func:`investigate`, the detective, assumes the
dataset derived the weather of all its dwellings the same way and tests hypotheses on all of them
at once: the nearest station; interpolation to the centres of H3 cells of level 4, 5 or 6, with
inverse distance weighting (power 1, 2, 3) or radial basis functions (linear, thin plate,
multiquadric); or interpolation at the dwelling itself (a point off every grid that fits better
than any cell centre). The hypothesis that explains most dwellings exactly is the verdict, with
advice for whoever publishes. :func:`trace` does the same per dwelling, without that assumption.

Per dwelling, :func:`trace` compares the dataset's series with

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

from .tabel import lees_parquet

MIN_HOURS = 200          # too few overlapping hours: no verdict
SHIFTS = (0, -1, 1, -2, 2)
EXACT_RMS = 0.05         # °C: a match this close means the same source, not a neighbour
# checked on KNMI 2024 data: a series interpolated differently (4 nearest stations, power 3)
# was placed 6-25 km from its true point (median ~11 km) by the best level-6 point
APPROX_KM = 15.0
PUBLISH_LEVEL = 5


def utc_hours(values) -> pd.Series:
    """Times as naive UTC, floored to the hour. Datasets mix formats (IM3: dates for day and
    month rows, full timestamps for hours), so each value is parsed on its own; values without a
    zone are taken as UTC (the per-period shift finds local clock time)."""
    t = pd.to_datetime(values, utc=True, format="mixed", errors="coerce")
    return t.dt.tz_convert(None).dt.floor("h")


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
        part = parse_hourly(fetcher(KNMI_URL, data=body))
        # 'end=...24' also returns the next month's first day: keep this month only
        parts.append(part[part["time"].dt.month == month])
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
        frames.append(lees_parquet(p))
    # files downloaded before the month filter hold each month's first day twice
    return pd.concat(frames, ignore_index=True).drop_duplicates(["station", "time"])


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
    t = utc_hours(series[time_col])
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


def grid_from(store=None, population=None, levels=(4, 5)) -> Grid:
    """Stations from the store; candidate cells: the cells of each level that hold dwellings."""
    stations = lees_parquet(store.raw / "knmi_stations.parquet")
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
        return lees_parquet(p)
    if p.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(p)
    return pd.read_csv(io.StringIO(p.read_text(encoding="utf-8-sig")), sep=None,
                       engine="python")


# ------------------------------------------------------------------------------------------------
# the detective: one method for the whole dataset
# ------------------------------------------------------------------------------------------------
# A dataset usually derives the weather of all its dwellings the same way. Testing hypotheses on
# all dwellings at once is far stronger than per dwelling: a method that reproduces most series
# exactly is almost certainly the one used, and then every dwelling's weather point is known.

METHODS = {
    "idw1": ("idw", 1.0), "idw2": ("idw", 2.0), "idw3": ("idw", 3.0),
    "rbf_lineair": ("rbf", "linear"), "rbf_thin_plate": ("rbf", "thin_plate"),
    "rbf_multiquadric": ("rbf", "multiquadric"),
}
AREA_KM2 = {4: 1770.0, 5: 253.0, 6: 36.1}
POINT_KM = 0.5           # a level-8 cell: the dwelling's own location, give or take


def _xy(lat, lon):
    lat = np.asarray(lat, float)
    return np.stack([np.asarray(lon, float) * 111.32 * np.cos(np.radians(52.2)), lat * 110.57], -1)


def _kernel(r: np.ndarray, kind: str, eps: float) -> np.ndarray:
    if kind == "linear":
        return r
    if kind == "thin_plate":
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(r > 0, r ** 2 * np.log(r), 0.0)
    return np.sqrt((r / eps) ** 2 + 1)          # multiquadric, as scipy's Rbf default


def interpolate_rbf(wide: pd.DataFrame, stations: pd.DataFrame, points: np.ndarray,
                    kind: str = "multiquadric") -> np.ndarray:
    """Radial basis function interpolation per hour from the stations with a value that hour
    (a linear polynomial term for the linear and thin-plate kernels)."""
    pos = stations.set_index("knmi_station").loc[wide.columns, ["lat", "lon"]].to_numpy(float)
    sxy = _xy(pos[:, 0], pos[:, 1])
    pxy = _xy(points[:, 0], points[:, 1])
    values = wide.to_numpy(float)
    have = ~np.isnan(values)
    out = np.full((len(values), len(points)), np.nan)
    patterns = {}
    for h, row in enumerate(have):
        patterns.setdefault(row.tobytes(), []).append(h)
    for key, hours in patterns.items():
        mask = np.frombuffer(key, dtype=bool)
        n = int(mask.sum())
        if n < 4:
            continue
        s = sxy[mask]
        d = np.hypot(*(s[:, None, :] - s[None, :, :]).transpose(2, 0, 1))
        eps = float(np.mean(d[d > 0])) if n > 1 else 1.0
        phi = _kernel(d, kind, eps)
        dp = np.hypot(*(pxy[:, None, :] - s[None, :, :]).transpose(2, 0, 1))
        phip = _kernel(dp, kind, eps)
        rhs = values[np.ix_(hours, np.where(mask)[0])].T              # n x h
        if kind in ("linear", "thin_plate"):
            poly = np.column_stack([np.ones(n), s])
            a = np.block([[phi, poly], [poly.T, np.zeros((3, 3))]])
            sol = np.linalg.lstsq(a, np.vstack([rhs, np.zeros((3, len(hours)))]), rcond=None)[0]
            pp = np.column_stack([np.ones(len(points)), pxy])
            out[hours] = (phip @ sol[:n] + pp @ sol[n:]).T
        else:
            sol = np.linalg.lstsq(phi, rhs, rcond=None)[0]
            out[hours] = (phip @ sol).T
    return out


def _interp(method: str, wide, stations, points) -> np.ndarray:
    family, arg = METHODS[method]
    if family == "idw":
        return interpolate(wide, stations, points, power=arg)
    return interpolate_rbf(wide, stations, points, arg)


@dataclass
class Findings:
    """What the detective concluded: hypotheses tested, the verdict, per-dwelling locations, and
    findings about the data itself (time keeping, station switches)."""
    hypotheses: pd.DataFrame
    verdict: str
    advice: str
    per_home: pd.DataFrame
    findings: list = None


# Matching is robust on purpose. KNMI's hours are UT without daylight saving time; a dataset in
# local clock time without a zone is an hour off for half the year, has a missing hour in March
# and a doubled one in October (averaged into one bad value). So: the 24 hours around every
# switch are left out, the shift is chosen per period between switches (summer and winter time
# each their own), and a match counts as exact when nearly all hours agree within KNMI's rounding
# (0.1 °C), not by the mean difference, which a handful of bad hours would spoil. The ranking uses
# the root mean square without the largest 2% of differences.
CLOSE_C = 0.06           # |difference| within KNMI's 0.1 °C rounding
EXACT_SHARE = 0.95       # share of hours that must agree for an exact match
TRIM = 0.02              # largest differences left out of the ranking
SWITCH_MARGIN_H = 24     # hours left out around a daylight-saving switch
SCREEN = 15              # dwellings every hypothesis is screened on
FINALISTS = 4            # hypotheses then tested on all dwellings
SCREEN_HOURS = 480       # hours of each dwelling used when screening
TRIM_BEST = 8            # candidates per dwelling that get the (slow) trimmed rms
MONTH_MIN_HOURS = 100    # hours a month needs to name its station


def _periods(index: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per UTC hour: period number between Dutch clock switches, whether it is summer time, and
    whether it lies within SWITCH_MARGIN_H of a switch."""
    local = index.tz_localize("UTC").tz_convert("Europe/Amsterdam").tz_localize(None)
    offset = ((local - index) / pd.Timedelta(hours=1)).to_numpy()
    switches = np.flatnonzero(np.diff(offset)) + 1
    period = np.zeros(len(index), int)
    near = np.zeros(len(index), bool)
    for s in switches:
        period[s:] += 1
        near[max(0, s - SWITCH_MARGIN_H):s + SWITCH_MARGIN_H] = True
    return period, offset == 2, near


def _scores(v: np.ndarray, cand: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Trimmed rms and share of close hours of series ``v`` against every candidate column."""
    ok = ~np.isnan(v)
    d = np.abs(cand[ok] - v[ok][:, None])
    valid = ~np.isnan(d)
    share = (d <= CLOSE_C).sum(0) / np.maximum(valid.sum(0), 1)
    if not len(d):
        return np.full(d.shape[1], math.inf), share
    # plain rms for every candidate; the trimmed rms (largest TRIM of the differences left out)
    # only for the few that can win, as a partial sort over all of them is the slow part
    rms = np.sqrt((np.where(valid, d, 0.0) ** 2).sum(0) / np.maximum(valid.sum(0), 1))
    rms[~valid.any(0)] = math.inf
    best = np.lexsort((rms, -share))[:TRIM_BEST]
    sub = np.where(valid[:, best], d[:, best], np.inf)
    k = max(int(len(sub) * (1 - TRIM)), 1)
    part = np.partition(sub, k - 1, axis=0)[:k]
    finite = np.isfinite(part)
    trimmed = np.sqrt((np.where(finite, part, 0.0) ** 2).sum(0) / np.maximum(finite.sum(0), 1))
    rms[best] = np.where(finite.any(0), trimmed, math.inf)
    return rms, share


def _aligned(series, wide, id_col, time_col, value_col):
    """Per dwelling: the series on the KNMI hours, shifted per period between clock switches to
    fit the stations best, the switch hours left out; and the shift per period."""
    t = utc_hours(series[time_col])
    s = pd.DataFrame({"id": series[id_col], "time": t,
                      "v": pd.to_numeric(series[value_col], errors="coerce")})
    s = s.groupby(["id", "time"], as_index=False)["v"].mean()
    stations = wide.to_numpy(float)
    period, summer, near = _periods(wide.index)
    out = {}
    for home, g in s.groupby("id"):
        shifted = {}
        for shift in SHIFTS:
            v = g.set_index(g["time"] + pd.Timedelta(hours=shift))["v"]
            v = v[~v.index.duplicated()].reindex(wide.index).to_numpy(float, copy=True)
            v[near] = np.nan
            shifted[shift] = v
        aligned = np.full(len(wide), np.nan)
        shifts = {}
        for p in np.unique(period):
            here = period == p
            best = None
            for shift, v in shifted.items():
                part = np.where(here, v, np.nan)
                if int((~np.isnan(part)).sum()) < 24:
                    continue
                rms, _ = _scores(part, stations)
                if best is None or rms.min() < best[0]:
                    best = (rms.min(), shift)
            if best is not None:
                shifts[int(p)] = (best[1], bool(summer[here][0]))
                aligned[here] = shifted[best[1]][here]
        if int((~np.isnan(aligned)).sum()) >= MIN_HOURS:
            out[home] = (shifts, aligned)
    return out


def _time_findings(homes: dict) -> list[str]:
    """What the shifts per period say about how the dataset keeps time."""
    local, fixed, clean = 0, {}, 0
    for shifts, _ in homes.values():
        winter = {s for s, is_summer in shifts.values() if not is_summer}
        summer = {s for s, is_summer in shifts.values() if is_summer}
        if winter and summer and len(winter) == 1 and len(summer) == 1 \
                and next(iter(winter)) - next(iter(summer)) == 1:
            local += 1
        else:
            values = {s for s, _ in shifts.values()}
            if values == {0}:
                clean += 1
            elif len(values) == 1:
                fixed[next(iter(values))] = fixed.get(next(iter(values)), 0) + 1
    out = []
    n = len(homes)
    if local:
        out.append(f"Tijd: {local} van {n} woningen staan in Nederlandse kloktijd zonder "
                   "tijdzone (in de zomer een uur verder dan in de winter). Sla tijden op in UTC "
                   "of met tijdzone; rond de wisseldagen ontbreekt of verdubbelt anders een uur.")
    for shift, count in sorted(fixed.items()):
        out.append(f"Tijd: {count} van {n} woningen liggen het hele jaar {abs(shift)} uur "
                   f"{'achter op' if shift > 0 else 'voor op'} KNMI (UT). Waarschijnlijk een "
                   "eind-gelabeld uur als begin-gelabeld overgenomen, of een vaste tijdzone.")
    return out


def _monthly_stations(homes: dict, wide: pd.DataFrame) -> dict:
    """Per dwelling: the exact station per calendar month, where one fits."""
    stations = wide.to_numpy(float)
    months = wide.index.to_period("M")
    out = {}
    for home, (_, v) in homes.items():
        seq = []
        for m in months.unique():
            here = np.asarray(months == m)
            part = np.where(here, v, np.nan)
            if int((~np.isnan(part)).sum()) < MONTH_MIN_HOURS:
                continue
            _, share = _scores(part, stations)
            j = int(np.argmax(share))
            if share[j] >= EXACT_SHARE:
                seq.append((str(m), wide.columns[j]))
        out[home] = seq
    return out


def border_cells(a: str, b: str, grid: Grid, level: int) -> list[str]:
    """Cells whose two nearest stations are ``a`` and ``b``: where a dwelling that switches
    between them most likely lies."""
    import h3
    cells = grid.cells.get(level, [])
    if not cells:
        return []
    pos = grid.stations.set_index("knmi_station")[["lat", "lon"]]
    pts = np.array([h3.cell_to_latlng(c) for c in cells])
    d = _km(pts[:, :1], pts[:, 1:2], pos["lat"].to_numpy()[None], pos["lon"].to_numpy()[None])
    two = np.argsort(d, axis=1)[:, :2]
    names = pos.index.to_numpy()
    return [c for c, (i, j) in zip(cells, two) if {names[i], names[j]} == {a, b}]


def investigate(series: pd.DataFrame, hourly: pd.DataFrame, grid: Grid, *, id_col: str,
                time_col: str, value_col: str, variable: str = "T",
                methods=tuple(METHODS), search_km: float = 20.0,
                max_hours: int = 24 * 60) -> Findings:
    """Play detective on a whole dataset: which single way of deriving the weather explains the
    most dwellings exactly, and what does that reveal about where each dwelling is?"""
    import h3
    wide = hourly.pivot_table(index="time", columns="station", values=variable)
    wide = wide[[c for c in wide.columns if c in set(grid.stations["knmi_station"].astype(str))]]
    homes = _aligned(series, wide, id_col, time_col, value_col)
    findings = _time_findings(homes)
    monthly = _monthly_stations(homes, wide)
    n = len(homes)
    names = list(homes)
    mat = np.array([homes[h][1] for h in names]) if n else np.zeros((0, len(wide)))
    if n and max_hours and mat.shape[1] > max_hours:
        # the hours most dwellings cover: enough for a fingerprint, light on memory
        keep = np.sort(np.argsort(-(~np.isnan(mat)).sum(0), kind="stable")[:max_hours])
        wide, mat = wide.iloc[keep], mat[:, keep]
    mat = mat.astype(np.float32)     # tenths of a degree: single precision is plenty, and fast
    rows, best_cell = [], {}

    def fit(candidates: np.ndarray, homes_idx=None, hours=None):
        """Per dwelling: best candidate, its trimmed rms, and whether it matches exactly."""
        idx, rms, exact = np.zeros(n, int), np.full(n, np.inf), np.zeros(n, bool)
        candidates = np.asarray(candidates[:hours], np.float32)
        for i in (range(n) if homes_idx is None else homes_idx):
            r, share = _scores(mat[i, :hours], candidates)
            j = int(np.argmin(r))
            idx[i], rms[i], exact[i] = j, r[j], share[j] >= EXACT_SHARE
        return idx, rms, exact

    st_idx, st_rms, st_ex = fit(wide.to_numpy(float))
    # a dwelling whose months each match a station exactly is explained by stations too
    for i, home in enumerate(names):
        if not st_ex[i] and len(monthly.get(home, [])) >= 2:
            st_ex[i] = True
    rows.append({"hypothese": "dichtstbijzijnd KNMI-station", "methode": "-", "niveau": None,
                 "verklaard": int(st_ex.sum()),
                 "rms_mediaan": float(np.median(st_rms)) if n else math.nan})
    # Which stations take part matters as much as the method. The NeedForHeat weather library
    # drops every row with a missing quantity, so asking temperature and irradiance together
    # leaves out stations without irradiance (242 Vlieland, 340 Woensdrecht) altogether; the
    # suffix '+Q' is that station set, per hour.
    variants = {"": wide}
    if variable != "Q" and "Q" in hourly.columns:
        wide_q = hourly.pivot_table(index="time", columns="station", values="Q").reindex(
            index=wide.index, columns=wide.columns)
        masked = wide.where(wide_q.notna())
        if int(masked.notna().sum().sum()) < int(wide.notna().sum().sum()):
            variants["+Q"] = masked

    def interp(name: str, pts: np.ndarray) -> np.ndarray:
        suffix = "+Q" if name.endswith("+Q") else ""
        return _interp(name.removesuffix("+Q"), variants[suffix], grid.stations, pts)

    # screen every hypothesis on a sample of dwellings, then test the best few on all of them
    screen = (sorted(np.random.default_rng(0).choice(n, SCREEN, replace=False))
              if n > SCREEN else None)
    tried = {}
    for m in methods:
        for suffix in variants:
            name = m + suffix
            for level, cells in grid.cells.items():
                pts = np.array([h3.cell_to_latlng(c) for c in cells])
                cand = interp(name, pts)
                idx, rms, ex = fit(cand, screen, SCREEN_HOURS if screen is not None else None)
                sub = screen if screen is not None else list(range(n))
                tried[(name, level)] = (cand, int(ex[sub].sum()), float(np.median(rms[sub])))
    ranked = sorted(tried, key=lambda k: (-tried[k][1], tried[k][2]))
    finalists = [k for k in ranked[:FINALISTS]
                 if tried[k][1] >= tried[ranked[0]][1] - 1]
    for (name, level), (cand, screened, med) in tried.items():
        cells = grid.cells[level]
        if (name, level) in finalists or screen is None:
            idx, rms, ex = fit(cand)
            best_cell[(name, level)] = ([cells[i] for i in idx], rms, ex)
            explained, median, tested = int(ex.sum()), float(np.median(rms)) if n else math.nan, n
        else:
            explained, median, tested = screened, med, len(screen)
        rows.append({"hypothese": f"celmidden H3 niveau {level}", "methode": name,
                     "niveau": level, "verklaard": explained, "getoetst": tested,
                     "rms_mediaan": median})
    rows[0]["getoetst"] = n
    # on a tie the station wins: a cell next to a station only copies that station
    hyp = pd.DataFrame(rows)
    hyp["_eerst"] = hyp["methode"] != "-"
    # coarser grids first on a tie: a level-4 centre is also the centre of a level-5 cell
    hyp["_aandeel"] = hyp["verklaard"] / hyp["getoetst"].clip(lower=1)
    hyp = hyp.sort_values(["_aandeel", "_eerst", "niveau", "rms_mediaan"],
                          ascending=[False, True, True, True]).drop(columns=["_eerst", "_aandeel"])
    hyp = hyp.reset_index(drop=True)
    top = hyp.iloc[0] if len(hyp) else None
    per_home = pd.DataFrame({"woning": names, "verschuiving_uur": [
        ",".join(str(s) for s, _ in homes[h][0].values()) for h in names]})

    def own_location(method: str, starts: list, homes_idx=None):
        """Best point (a level-8 cell) near each start cell, with the given method."""
        locs, rmss, exs = [], [], []
        edge = h3.average_hexagon_edge_length(8, unit="km")
        k = math.ceil(search_km / (1.5 * edge))
        for i in (range(n) if homes_idx is None else homes_idx):
            if starts[i] is None:
                locs.append(None)
                rmss.append(math.inf)
                exs.append(False)
                continue
            around = list(h3.grid_disk(h3.cell_to_center_child(starts[i], 8), k))
            pts = np.array([h3.cell_to_latlng(c) for c in around])
            r, share = _scores(mat[i], interp(method, pts))
            j = int(np.argmin(r))
            locs.append(around[j])
            rmss.append(float(r[j]))
            exs.append(bool(share[j] >= EXACT_SHARE))
        return locs, np.array(rmss), np.array(exs)

    choice = "none"
    own_locs, own_rms, own_ex = [], np.array([]), np.array([], bool)
    if n and top is not None and top["verklaard"] >= max(1, n / 2) \
            and top["hypothese"].startswith("dichtstbij"):
        choice = "station"
    elif n:
        # a grid may win only because a fine cell lies close to the true point: search next to
        # the cell centres too; a point off the grid that fits much better means no grid
        grids = hyp[hyp["methode"] != "-"]
        method = (top["methode"] if top is not None and top["methode"] != "-"
                  else grids.sort_values("rms_mediaan").iloc[0]["methode"]) \
            if len(grids) else "idw2"
        start_level = int(top["niveau"]) if top is not None and top["methode"] != "-" \
            else max(grid.cells)
        starts = best_cell.get((method, start_level), ([None] * n, None, None))[0]
        grid_ok = (top is not None and top["methode"] != "-"
                   and top["verklaard"] >= max(1, n / 2))

        def better(expl, rms, of):
            return expl >= max(1, of / 2) and (
                not grid_ok or float(np.median(rms)) < 0.5 * float(top["rms_mediaan"]))
        # first on a sample: when the grid already explains the data and no point near it does
        # much better, searching around every dwelling tells nothing new
        tested = n
        if screen is not None and grid_ok:
            _, s_rms, s_ex = own_location(method, starts, screen)
            if not better(int(s_ex.sum()), s_rms, len(screen)):
                own_rms, own_ex, tested = s_rms, s_ex, len(screen)
        if tested == n:
            own_locs, own_rms, own_ex = own_location(method, starts)
        own_expl = int(own_ex.sum())
        hyp = pd.concat([hyp, pd.DataFrame([{
            "hypothese": "eigen locatie (willekeurig punt)", "methode": method, "niveau": 8,
            "verklaard": own_expl, "getoetst": tested,
            "rms_mediaan": float(np.median(own_rms))}])], ignore_index=True)
        own_better = tested == n and better(own_expl, own_rms, n)
        choice = "own" if own_better else ("grid" if grid_ok else "none")

    if choice == "station":
        locs = [wide.columns[i] for i in st_idx]
        regime = ["station"] * n
        switched = 0
        level = max(grid.cells) if grid.cells else None
        for i, home in enumerate(names):
            seq = monthly.get(home, [])
            distinct = list(dict.fromkeys(s for _, s in seq))
            if len(distinct) == 2 and level is not None:
                cells = border_cells(distinct[0], distinct[1], grid, level)
                if cells:
                    switched += 1
                    locs[i] = "|".join(cells)
                    regime[i] = "grensstrook"
                    when = next(m for m, s in seq if s == distinct[1])
                    findings.append(f"Stationswissel: woning {home} gebruikt {distinct[0]} en "
                                    f"vanaf {when} {distinct[1]}. Zo'n wissel verraadt dat de "
                                    "woning bij de grens tussen beide stationsgebieden ligt.")
            elif len(distinct) > 2:
                findings.append(f"Stationswissel: woning {home} gebruikt {len(distinct)} "
                                f"stations ({', '.join(distinct)}).")
        per_home["regime"], per_home["locatie"] = regime, locs
        per_home["rms"], per_home["exact"] = st_rms, st_ex
        per_home["onzekerheid_km"] = np.where(st_ex, 0.0, APPROX_KM)
        verdict = (f"{int(top['verklaard'])} van {n} woningen gebruiken exact het weer van "
                   "één KNMI-station: de dataset kiest per woning het dichtstbijzijnde station."
                   + (f" {switched} daarvan wisselen van station." if switched else ""))
        advice = ("Het station wijst een gebied van gemiddeld ~1.000 km² aan; langs de kust en "
                  "rond eilandstations veel minder woningen. Overweeg interpolatie op het "
                  "midden van een H3-cel van niveau 5 na ruis (σ ≈ 10 km): nauwkeuriger weer en "
                  "even veilig. Wissel nooit van station binnen een reeks zonder dat te melden, en "
                  "liever helemaal niet: de wissel zelf is een locatiekenmerk.")
    elif choice == "grid":
        m, level = top["methode"], int(top["niveau"])
        cells, rms, ex = best_cell[(m, level)]
        per_home["regime"], per_home["locatie"] = f"h3_r{level}", cells
        per_home["rms"], per_home["exact"] = rms, ex
        per_home["onzekerheid_km"] = np.where(ex, 0.0, APPROX_KM)
        stations = ", alleen stations die ook straling meten" if m.endswith("+Q") else ""
        area = f"{AREA_KM2.get(level, 0):,.0f}".replace(",", ".")
        verdict = (f"{int(top['verklaard'])} van {n} woningen hebben exact het weer van het "
                   f"midden van een H3-cel van niveau {level} ({m.removesuffix('+Q')}{stations}): "
                   f"elke woning is aan die cel (~{area} km²) te koppelen.")
        advice = ("Zonder ruis ligt de woning in die cel; met ruis vóór het kiezen van de cel "
                  "binnen een paar σ. Uit het weer alleen is niet te zien of er ruis is "
                  "gebruikt: vermeld het, en toets de cel als verborgen locatie. "
                  + ("Niveau 4 geeft een grover weerpunt dan nodig; niveau 5 met ruis "
                     "(σ ≈ 10 km) is nauwkeuriger en even veilig." if level == 4 else
                     "Zonder ruis is niveau 5 of fijner te herkenbaar; gebruik ruis (σ ≈ 10 km)."))
    elif choice == "own":
        per_home["regime"] = np.where(own_ex, "punt", "omgeving")
        per_home["locatie"] = [loc if o else (h3.cell_to_parent(loc, PUBLISH_LEVEL) if loc else None)
                               for loc, o in zip(own_locs, own_ex)]
        per_home["rms"], per_home["exact"] = own_rms, own_ex
        per_home["onzekerheid_km"] = np.where(own_ex, POINT_KM, APPROX_KM)
        verdict = (f"{int(own_ex.sum())} van {n} woningen hebben exact het weer van een eigen "
                   f"punt ({method}), niet van een vast raster: het weer is berekend op (vrijwel) "
                   f"de locatie van de woning zelf. Die is tot op ~{POINT_KM:g} km te herleiden.")
        advice = ("Bereken het weer niet op de woning, maar op het midden van een H3-cel na "
                  "ruis (niveau 5, σ ≈ 10 km). Publiceer deze dataset niet zoals hij is.")
    else:
        per_home["regime"] = "omgeving"
        per_home["locatie"] = [h3.cell_to_parent(loc, PUBLISH_LEVEL) if loc else None
                               for loc in own_locs] if n else []
        per_home["rms"] = own_rms if n else []
        per_home["exact"] = False
        per_home["onzekerheid_km"] = APPROX_KM
        verdict = ("Geen enkele geteste methode verklaart de reeksen exact (een andere bron of "
                   "methode, of bewerkt weer). Een aanvaller schat dan de omgeving: typisch "
                   "5 tot 25 km naast de echte plek.")
        advice = ("Toets de geschatte omgeving als verborgen locatie (cel van niveau 5, "
                  f"onzekerheid {APPROX_KM:g} km). Documenteer de weermethode gewoon: de "
                  "bescherming moet uit de grofheid komen, niet uit geheimhouding.")
    stations = grid.stations.set_index("knmi_station")[["lat", "lon"]]
    per_home.attrs["stations"] = stations
    return Findings(hyp, verdict, advice, per_home, findings)


def check_assignment(dataset: pd.DataFrame, key: str, per_home: pd.DataFrame, population,
                     stations: pd.DataFrame) -> tuple[pd.Series, list[str]]:
    """Station per dwelling as an attacker should read it, given other location columns in the
    dataset (postcode4, gemeente or provincie).

    A station no dwelling of that region has as its nearest is suspicious: an error, a fallback
    when the nearest station had no data, or a deliberate twist. An attacker then trusts the
    region more than the station, so the published station is widened to the stations of that
    region: never "no match, so safe"."""
    import re
    region = next((c for c in dataset.columns
                   if re.fullmatch(r"(postcode4|pc4|gemeente|woonplaats|provincie)", c, re.I)),
                  None)
    station_of = per_home.set_index(per_home["woning"].astype(str))
    out = dataset[key].astype(str).map(
        station_of["locatie"].where(station_of["regime"] == "station"))
    if region is None or "knmi_station" not in population.columns:
        return out, []
    pcol = {"pc4": "postcode4", "woonplaats": "gemeente"}.get(region.lower(), region.lower())
    if pcol not in population.columns:
        return out, []
    table = population.con.execute(
        f"SELECT CAST({pcol} AS VARCHAR), knmi_station, count(*) FROM {population.relation} "
        f"WHERE knmi_station IS NOT NULL GROUP BY 1, 2").fetchall()
    per_region: dict[str, set] = {}
    for r, st, _ in table:
        per_region.setdefault(str(r).lower(), set()).add(str(st))
    notes = []
    widened = []
    for home, st, r in zip(dataset[key].astype(str), out, dataset[region]):
        allowed = per_region.get(str(r).lower())
        if st is None or pd.isna(st) or not allowed or st in allowed:
            widened.append(st)
            continue
        notes.append(f"Verdacht station: woning {home} gebruikt station {st}, maar in {region} "
                     f"{r} is dat voor geen enkele woning het dichtstbijzijnde. Getoetst met de "
                     "stations van die regio.")
        widened.append("|".join(sorted(allowed | {st})))
    return pd.Series(widened, index=dataset.index, dtype=object), notes


# ------------------------------------------------------------------------------------------------
# reading weather series the way datasets ship them
# ------------------------------------------------------------------------------------------------
# One long table (a row per dwelling and time); a folder or zip with a file per dwelling, the
# dwelling's ID in the file name (IM_customer_<id>.csv, home_id=<id>.parquet) or in the folder
# name (woning_7/knmi.csv); weather in the series itself or in a column among many. Large
# datasets (thousands of files) are read as a sample of dwellings: identifying the method needs a
# few hundred, not all.

TIME_HINT = r"tijd|time|timestamp|datum|date|datetime|moment"
VALUE_HINT = (r"buiten_?temp|outdoor_?temp|temp_?buiten|temp_?out|(^|_)t_?(out|outdoor|buiten|"
              r"ambient|amb)(_|$)|^t$|knmi_?t|temperature_?out")
ID_HINT = r"home_?id|woning_?id|location_?id|participant_?id|customer_?id|pseudon|(^|_)id(_|$)"
NAME_ID = r"(?:home_?id=|customer_|woning_?|home_?)?([A-Za-z0-9][A-Za-z0-9-]*?)(?:\.[A-Za-z0-9]+)*$"


def guess_column(columns, pattern: str) -> str | None:
    import re
    return next((c for c in columns if re.search(pattern, str(c), re.I)), None)


def _read_table(handle, name: str, usecols=None) -> pd.DataFrame:
    low = name.lower()
    if low.endswith(".parquet"):
        return pd.read_parquet(handle, columns=usecols)
    if low.endswith((".xlsx", ".xls")):
        return pd.read_excel(handle, usecols=usecols)
    data = handle.read() if hasattr(handle, "read") else Path(handle).read_bytes()
    text = data.decode("utf-8-sig", errors="replace")
    first = text.split("\n", 1)[0]
    sep = max((",", ";", "\t"), key=first.count)
    return pd.read_csv(io.StringIO(text), sep=sep, usecols=usecols)


def _header(handle, name: str) -> list[str]:
    low = name.lower()
    if low.endswith(".parquet"):
        import pyarrow.parquet as pq
        return pq.read_schema(handle).names
    if low.endswith((".xlsx", ".xls")):
        return list(pd.read_excel(handle, nrows=0).columns)
    first = handle.readline().decode("utf-8-sig", errors="replace") if hasattr(handle, "readline") \
        else Path(handle).open(encoding="utf-8-sig").readline()
    sep = max((",", ";", "\t"), key=first.count)
    return [c.strip().strip('"') for c in first.strip().split(sep)]


def _id_from(name: str, id_from: str, regex: str | None) -> str | None:
    import re
    parts = name.replace("\\", "/").split("/")
    target = parts[-1] if id_from == "bestand" else (parts[-2] if len(parts) > 1 else "")
    m = re.search(regex or NAME_ID, target)
    return m.group(1) if m else None


def members(source: str | Path, pattern: str = "*") -> list[tuple[str, object]]:
    """(name, opener) of the data files in a folder or zip, matching ``pattern``."""
    import fnmatch
    import zipfile
    src = Path(source)
    exts = (".csv", ".txt", ".parquet", ".xlsx", ".xls")
    if src.is_file() and zipfile.is_zipfile(src):
        z = zipfile.ZipFile(src)
        names = [n for n in z.namelist() if n.lower().endswith(exts)
                 and fnmatch.fnmatch(n.split("/")[-1], pattern)]
        return [(n, (lambda n=n: z.open(n))) for n in sorted(names)]
    if src.is_dir():
        files = [p for p in src.rglob(pattern) if p.is_file() and p.suffix.lower() in exts]
        return [(str(p.relative_to(src)), (lambda p=p: open(p, "rb"))) for p in sorted(files)]
    return [(src.name, (lambda: open(src, "rb")))]


def read_series_source(source: str | Path, *, id_from: str = "kolom", id_col: str | None = None,
                       time_col: str | None = None, value_col: str | None = None,
                       pattern: str = "*", id_regex: str | None = None,
                       max_homes: int | None = None, seed: int = 0) -> pd.DataFrame:
    """Weather series as one long table ``woning``, ``tijd``, ``waarde`` from a file, folder or
    zip. ``id_from``: ``kolom`` (a column, ``id_col`` or guessed), ``bestand`` (the file name) or
    ``map`` (the folder name). With ``max_homes`` a random sample of dwellings is read."""
    files = members(source, pattern)
    if not files:
        raise FileNotFoundError(f"geen databestanden in {source} (patroon {pattern})")
    rng = np.random.default_rng(seed)
    if id_from in ("bestand", "map"):
        by_home: dict[str, list] = {}
        for name, opener in files:
            home = _id_from(name, id_from, id_regex)
            if home:
                by_home.setdefault(home, []).append((name, opener))
        homes = sorted(by_home)
        if max_homes and len(homes) > max_homes:
            homes = sorted(rng.choice(homes, max_homes, replace=False))
        frames = []
        for home in homes:
            for name, opener in by_home[home]:
                with opener() as h:
                    cols = _header(h, name)
                tc = time_col or guess_column(cols, TIME_HINT)
                vc = value_col or guess_column(cols, VALUE_HINT)
                if tc is None or vc is None or tc not in cols or vc not in cols:
                    continue
                with opener() as h:
                    df = _read_table(h, name, usecols=[tc, vc])
                part = pd.DataFrame({"woning": home, "tijd": df[tc],
                                     "waarde": pd.to_numeric(df[vc], errors="coerce")})
                frames.append(part[part["waarde"].notna()])
        if not frames:
            raise ValueError("geen bestand met een tijd- en een buitentemperatuurkolom gevonden; "
                             "geef de kolommen op")
        return pd.concat(frames, ignore_index=True)
    frames = []
    for name, opener in files:
        with opener() as h:
            cols = _header(h, name)
        ic = id_col or guess_column(cols, ID_HINT)
        tc = time_col or guess_column(cols, TIME_HINT)
        vc = value_col or guess_column(cols, VALUE_HINT)
        if None in (ic, tc, vc) or not {ic, tc, vc} <= set(cols):
            continue
        with opener() as h:
            df = _read_table(h, name, usecols=[ic, tc, vc])
        part = pd.DataFrame({"woning": df[ic].astype(str), "tijd": df[tc],
                             "waarde": pd.to_numeric(df[vc], errors="coerce")})
        frames.append(part[part["waarde"].notna()])
    if not frames:
        raise ValueError("geen woning-, tijd- en buitentemperatuurkolom gevonden; geef ze op")
    out = pd.concat(frames, ignore_index=True)
    if max_homes:
        homes = out["woning"].unique()
        if len(homes) > max_homes:
            keep = set(rng.choice(homes, max_homes, replace=False))
            out = out[out["woning"].isin(keep)]
    return out
