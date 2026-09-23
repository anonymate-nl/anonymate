"""Baseline heat performance signature from public registers — the attacker's rainbow table.

The *heat performance signature* (warmteprestatiesignatuur) of a dwelling is a small set of
effective building parameters:

``H``      effective conductive heat transfer capacity of the envelope   [W/K]
``C``      effective thermal mass                                        [Wh/K]
``tau``    effective thermal inertia, C / H                              [h]
``A_sol``  effective horizontal solar aperture                           [m²]
``A_inf``  effective wind infiltration aperture                          [cm²]

Monitoring data lets a model *learn* these per home. The same parameters can also be *computed*
for every single-family dwelling in the country from public data only: construction year and
usable area (BAG), envelope areas (3D-BAG) and standard values (NTA 8800, RVO reference
dwellings). That computation is deterministic, so anyone can run it for all ~5 million
single-family homes: a rainbow table. A published signature, baseline *or* learned (learned
values lie close to the baseline), is therefore a quasi-identifier that can be counted against
the population like any register attribute. :func:`baseline` builds that table; the risk
module does the counting, and a tolerance (half the rounding step, or the model error) says how
precisely a published value pins a home down.

Method (per BAG pand with one dwelling; for multi-dwelling buildings the envelope cannot be
split from 3D-BAG and the signature is left empty):

* Envelope areas from 3D-BAG: outer wall (``opp_buitenmuur``, including windows and doors),
  ground floor (``opp_grond``, counted for 70% as effective ground loss area), flat and sloped
  roof. Party walls count as adiabatic (U = 0).
* Windows = outer wall × window fraction, doors = door area, both from the RVO reference
  dwelling (2022) matching dwelling type and construction period; walls = the rest.
* U-values from the NTA 8800 default thermal resistances per construction period (Rc plus
  surface resistances), window U from the reference dwelling, doors from default values.
* ``H`` = Σ area × U. ``C`` = specific internal heat capacity per construction period
  (180/360/450 kJ/(m²·K), NTA 8800) × usable area. ``tau`` = C / H.
* ``A_sol`` = Σ area × solar conversion factor: windows g-value × 0.9 frame factor × 1.154
  (heating-season irradiance on vertical façades averaged over orientations, relative to
  horizontal); opaque parts α (0.6) × R_se (0.04) × U × orientation factor.
* ``A_inf`` is a national average (108 cm²) and carries no information about a dwelling.

Two variants (``method``):

``nta8800``
    The standard defaults above. NTA 8800 is an enforcement instrument; its defaults are chosen
    conservatively rather than representatively.
``mwa``
    The *Maatwerkadvies* corrections that apply to these parameters (Van den Brom, Berben, Valk &
    Nuiten, 2022, *Maatwerkadvies NTA8800 — Een omschrijving van de aangepaste parameters en de
    validatie procedure*, RVO, pp. 24-29): Rc + 0.15 m²K/W on opaque parts, window and door
    U × 0.9, the b-factor towards an unheated adjacent space (the floor above a crawl space)
    × 0.7, infiltration × 0.5. Closer to real performance, so the fairer baseline to beat with a
    learned signature, and for the same reason the *better* rainbow table: judge how
    identifying a learned signature is by its distance to this variant.

This is a baseline, deliberately simple and fully open; its purpose here is to measure how
identifying a published signature is, not to be the best estimate of a home's performance.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

A_INF_NL_AVG__cm2 = 108.0
GROUND_FACTOR = 0.7
R_SI = {"wall": 0.13, "floor": 0.17, "roof": 0.10}
R_SE = 0.04
ALPHA_SOL = 0.6
FRAME_FACTOR = 0.9
WINDOW_IRRADIANCE_RATIO = 1.1543
WALL_IRRADIANCE_RATIO = 1.4991

# NTA 8800 default Rc [m²K/W] by construction period [from, to): wall, ground floor, roof
_RC = [
    (0, 1965, 0.19, 0.15, 0.22), (1965, 1975, 0.43, 0.17, 0.86), (1975, 1983, 1.3, 0.52, 1.3),
    (1983, 1988, 1.3, 1.3, 1.3), (1988, 1992, 2.0, 1.3, 2.0), (1992, 2014, 2.5, 2.5, 2.5),
    (2014, 2015, 3.5, 3.5, 3.5), (2015, 2021, 4.5, 3.5, 6.0), (2021, 9999, 4.7, 3.7, 6.3),
]
# glazing g-value (ggl;n) by construction period: the typical glazing of the (larger share of)
# bedroom windows: single glass until 1992, double, HR++, triple
_GGL = [(0, 1992, 0.85), (1992, 2014, 0.75), (2014, 2021, 0.6), (2021, 9999, 0.4)]
# specific internal heat capacity [kJ/(m²K)] by construction period
_MASS = [(0, 1950, 180.0), (1950, 1995, 360.0), (1995, 9999, 450.0)]
# door U [W/(m²K)] by construction period
_DOOR_U = [(0, 2005, 1.4925), (2005, 9999, 2.9930)]

# RVO reference dwellings 2022 (median variants): window fraction of the outer wall excluding
# doors, door area [m²], window U [W/(m²K)]
_RVO = {
    ("twee_onder_een_kap", "tot65"): (0.1958, 6.86, 1.8),
    ("twee_onder_een_kap", "75-91"): (0.1939, 6.51, 2.9),
    ("twee_onder_een_kap", "92-05"): (0.1980, 6.93, 2.9),
    ("twee_onder_een_kap", "06-14"): (0.1932, 8.36, 1.8),
    ("hoekwoning", "tot46"): (0.1842, 7.73, 2.9),
    ("hoekwoning", "75-91"): (0.1679, 4.57, 2.9),
    ("tussenwoning", "tot46"): (0.2872, 6.32, 2.9),
    ("tussenwoning", "75-91"): (0.2999, 4.55, 2.9),
    ("tussenwoning", "92-05"): (0.3007, 5.65, 1.8),
    ("vrijstaand", "tot65"): (0.1693, 8.04, 1.8),
    ("vrijstaand", "75-91"): (0.1894, 8.00, 2.9),
    ("vrijstaand", "92-05"): (0.2141, 10.09, 2.9),
    ("vrijstaand", "06-14"): (0.1867, 11.52, 1.8),
}
_PERIODS = ["tot46", "tot65", "75-91", "92-05", "06-14"]
_PERIOD_START = {"tot46": 0, "tot65": 1946, "75-91": 1975, "92-05": 1992, "06-14": 2006}

COLUMNS = ["sig_H", "sig_C", "sig_tau", "sig_Asol", "sig_Ainf"]

METHODS = ("nta8800", "mwa")
# Maatwerkadvies corrections (Van den Brom et al., 2022, table p. 24-25)
MWA_RC_SURCHARGE = 0.15
MWA_U_WINDOW_DOOR = 0.9
MWA_B_UNHEATED = 0.7
MWA_INFILTRATION = 0.5


def _lookup(years: np.ndarray, table, col: int) -> np.ndarray:
    out = np.full(len(years), np.nan)
    for row in table:
        mask = (years >= row[0]) & (years < row[1])
        out[mask] = row[col]
    return out


def _period(year: float) -> str:
    if year < 1946:
        return "tot46"
    if year < 1975:
        return "tot65"
    if year < 1992:
        return "75-91"
    if year < 2006:
        return "92-05"
    return "06-14"


def _rvo(dwelling_type: str, year: float) -> tuple[float, float, float]:
    """Reference dwelling for this type and period; the nearest period if there is none."""
    p = _period(year)
    if (dwelling_type, p) in _RVO:
        return _RVO[(dwelling_type, p)]
    options = [q for q in _PERIODS if (dwelling_type, q) in _RVO]
    if not options:
        return (0.2, 7.0, 2.9)
    nearest = min(options, key=lambda q: abs(_PERIOD_START[q] - _PERIOD_START[p]))
    return _RVO[(dwelling_type, nearest)]


def infer_dwelling_type(attached, party_wall: pd.Series, outer_wall: pd.Series) -> pd.Series:
    """Rough single-family type from 3D-BAG when no registered type exists: not attached ->
    detached; otherwise by the share of party wall in all wall area."""
    share = party_wall / (party_wall + outer_wall).replace(0, np.nan)
    out = pd.Series("tussenwoning", index=party_wall.index, dtype=object)
    out[share < 0.35] = "twee_onder_een_kap"
    out[attached.astype("boolean").fillna(True) == False] = "vrijstaand"  # noqa: E712
    out[party_wall.isna() | outer_wall.isna()] = None
    return out


def baseline(df: pd.DataFrame, method: str = "nta8800") -> pd.DataFrame:
    """Baseline signature per row. Needs ``bouwjaar``, ``oppervlakte`` (usable area),
    ``woningtype``, ``pand_woningen`` and the 3D-BAG envelope columns ``opp_buitenmuur``,
    ``opp_grond``, ``opp_dak_plat``, ``opp_dak_schuin``, ``opp_scheidingsmuur``,
    ``aaneengebouwd``. Rows that are not single-family or lack data get NaN.
    ``method``: ``nta8800`` (standard defaults) or ``mwa`` (Maatwerkadvies corrections)."""
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}, got {method!r}")
    mwa = method == "mwa"
    rc_extra = MWA_RC_SURCHARGE if mwa else 0.0
    u_wd = MWA_U_WINDOW_DOOR if mwa else 1.0
    b_ground = GROUND_FACTOR * (MWA_B_UNHEATED if mwa else 1.0)
    n = len(df)
    year = pd.to_numeric(df["bouwjaar"], errors="coerce").to_numpy(dtype=float)
    gbo = pd.to_numeric(df["oppervlakte"], errors="coerce").to_numpy(dtype=float)
    num = {c: pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
           for c in ("opp_buitenmuur", "opp_grond", "opp_dak_plat", "opp_dak_schuin",
                     "opp_scheidingsmuur")}
    single = pd.to_numeric(df["pand_woningen"], errors="coerce").to_numpy() == 1

    dtype = df["woningtype"].astype(object).where(
        df["woningtype"].isin(["vrijstaand", "twee_onder_een_kap", "hoekwoning",
                               "tussenwoning"]))
    guess = infer_dwelling_type(df["aaneengebouwd"], pd.Series(num["opp_scheidingsmuur"],
                                                               index=df.index),
                                pd.Series(num["opp_buitenmuur"], index=df.index))
    dtype = dtype.fillna(guess)
    frac = np.full(n, np.nan)
    door = np.full(n, np.nan)
    u_win = np.full(n, np.nan)
    cache: dict = {}
    for i, (t, y) in enumerate(zip(dtype.tolist(), year)):
        if t is None or (isinstance(t, float) and np.isnan(t)) or np.isnan(y):
            continue
        key = (t, _period(y))
        if key not in cache:
            cache[key] = _rvo(t, y)
        frac[i], door[i], u_win[i] = cache[key]

    u_wall = 1 / (_lookup(year, _RC, 2) + rc_extra + R_SI["wall"] + R_SE)
    u_floor = 1 / (_lookup(year, _RC, 3) + rc_extra + R_SI["floor"])
    u_roof = 1 / (_lookup(year, _RC, 4) + rc_extra + R_SI["roof"] + R_SE)
    u_door = _lookup(year, _DOOR_U, 2) * u_wd
    u_win = u_win * u_wd
    windows = num["opp_buitenmuur"] * frac
    walls = num["opp_buitenmuur"] - windows - door
    ground = num["opp_grond"] * b_ground
    roof = num["opp_dak_plat"] + num["opp_dak_schuin"]

    H = walls * u_wall + windows * u_win + door * u_door + ground * u_floor + roof * u_roof
    C = _lookup(year, _MASS, 2) * 1000 / 3600 * gbo
    g_gl = _lookup(year, _GGL, 2) * FRAME_FACTOR
    opaque = ALPHA_SOL * R_SE
    A_sol = (windows * g_gl * WINDOW_IRRADIANCE_RATIO
             + walls * opaque * u_wall * WALL_IRRADIANCE_RATIO
             + door * opaque * u_door * WALL_IRRADIANCE_RATIO
             + roof * opaque * u_roof)
    ok = single & np.isfinite(H) & (H > 0) & np.isfinite(C) & (walls > 0)
    out = pd.DataFrame({
        "sig_H": np.where(ok, H, np.nan),
        "sig_C": np.where(ok, C, np.nan),
        "sig_tau": np.where(ok, C / np.where(H > 0, H, np.nan), np.nan),
        "sig_Asol": np.where(ok, A_sol, np.nan),
        "sig_Ainf": np.where(ok, A_INF_NL_AVG__cm2 * (MWA_INFILTRATION if mwa else 1.0),
                             np.nan),
    }, index=df.index)
    return out.round({"sig_H": 2, "sig_C": 1, "sig_tau": 3, "sig_Asol": 3})
