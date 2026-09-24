"""Heat performance signature of every single-family home, from its address and public data only.

The *heat performance signature* (warmteprestatiesignatuur) of a dwelling is a small set of
effective building parameters:

``H``      effective conductive heat transfer capacity of the envelope   [W/K]
``C``      effective thermal mass                                        [Wh/K]
``tau``    effective thermal inertia, C / H                              [h]
``Asol``   effective horizontal solar aperture                           [m²]
``Ainf``   effective wind infiltration aperture                          [cm²]

Monitoring data lets a model *learn* these per home. This module *computes* them for every
single-family home in the Netherlands from public data only: construction year and usable
area (BAG), envelope areas (3D-BAG), the registered energy label (EP-online) and standard
knowledge (NTA 8800, RVO reference dwellings, Maatwerkadvies). It is useful on its own, e.g. as
a quick first estimate for any address, and it is exactly what an attacker can compute for all
~5 million single-family homes: a rainbow table. Published signatures are therefore
quasi-identifiers (see :mod:`anonymate.rounding` and the ``warmteverlies`` etc. QIDs).

Functions
---------
:func:`compute`
    one method on a DataFrame of register attributes; all outputs as separate columns, and
    with ``detail=True`` also the intermediate areas, U-values and the evidence used.
:func:`table`
    all methods for every dwelling in the local population, keyed by BAG id and address,
    streamed to a Parquet file.
:func:`lookup`
    the signature of one address from the local population (offline).

Methods
-------
``nta8800``
    Envelope areas from 3D-BAG (outer wall including windows and doors, ground floor counted for
    70%, flat and sloped roof; party walls adiabatic). Windows and doors from the RVO reference
    dwelling of the same type and period; U-values from NTA 8800 default thermal resistances by
    construction period, i.e. the building *as built*. Conservative by design: NTA 8800 is an
    enforcement instrument.
``mwa``
    ``nta8800`` with the Maatwerkadvies corrections (Van den Brom, Berben, Valk & Nuiten, 2022,
    RVO, pp. 24-29): Rc + 0.15 m²K/W on opaque parts, window and door U × 0.9, b-factor of the
    floor above a crawl space × 0.7, infiltration × 0.5.
``best``
    The best public estimate. The *current* state of the matching RVO reference dwelling
    (WoON2018) instead of the as-built state, calibrated per dwelling with its registered label:
    if the label was calculated with NTA 8800 (about 3.4 million labels) its net heat demand
    per m², corrected for the difference in compactness with the reference dwelling, places the
    dwelling on the scale *as built → current → package 1 → package 3* of that reference
    dwelling, and U-values and glazing are interpolated there. Older labels only nudge by label
    class; without a label the current state is used. Maatwerkadvies corrections on top, as the
    estimate should describe real behaviour, not a regulatory calculation.
``ep``
    ``best`` without 3D-BAG: the envelope comes from the energy label itself. Loss area =
    compactness × usable area (both public in EP-online), divided over wall, window, door, roof
    and floor in the proportions of the matching reference dwelling; thermal mass from the
    label's usable area. Only for dwellings with a label that has a compactness. The difference
    ``best`` − ``ep`` is what 3D-BAG adds to the label.
``ep_3dbag``
    3D-BAG for the *proportions* of the envelope (walls, ground floor, roof of this building),
    the label for its *size*: the 3D-BAG envelope scaled to the label's loss area. 3D-BAG
    measures the whole building (unheated attic, attached sheds, walls up to the ridge), the
    label only the thermal envelope. Only for dwellings with a label that has a compactness.

Assumptions, all deliberately simple and open: party walls adiabatic; ground floor 70%
effective; window share and door area from the reference dwelling; façade orientations averaged
(the RVO reference dwellings do so as well); thermal mass from the NTA 8800 table by period;
Ainf a national average (it carries no information about a dwelling). The RVO notes that its
reference dwellings are not meant to calculate individual homes; here that is precisely the
point, since this is what anyone *can* calculate.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

METHODS = ("nta8800", "mwa", "best", "ep", "ep_3dbag")
OUTPUTS = ["H", "C", "tau", "Asol", "Ainf"]
DETAIL = ["A_gevel", "A_raam", "A_deur", "A_grond", "A_dak", "U_gevel", "U_raam", "U_deur",
          "U_grond", "U_dak", "g_raam", "woningtype_gebruikt", "referentiewoning",
          "isolatieniveau", "bron"]
INPUT = ["bouwjaar", "oppervlakte", "woningtype", "pand_woningen", "aaneengebouwd",
         "opp_buitenmuur", "opp_grond", "opp_dak_plat", "opp_dak_schuin", "opp_scheidingsmuur",
         "energielabel", "warmtebehoefte", "nta8800", "compactheid", "label_oppervlakte"]
KEYS = ["vbo_id", "postcode6", "huisnummer", "huisletter", "toevoeging"]
_TEXT_DETAIL = ("woningtype_gebruikt", "referentiewoning", "bron")
# kept in the functional table so it can be narrowed down later (region, inclusion criteria)
CONTEXT = ["postcode4", "woonplaats", "gemeente", "provincie", "knmi_station", "h3_r4", "h3_r5",
           "h3_r6", "h3_r7", "h3_r8", "bouwjaar", "oppervlakte", "woningtype", "daktype",
           "bouwlagen", "hoogte", "aaneengebouwd", "energielabel"]

A_INF_NL_AVG__cm2 = 108.0
GROUND_FACTOR = 0.7
R_SI = {"wall": 0.13, "floor": 0.17, "roof": 0.10}
R_SE = 0.04
ALPHA_SOL = 0.6
# Solar gains through glazing, NTA 8800: A_sol = A_w · (1 − F_F) · g_gl;n · F_w · F_sh, with the
# default frame fraction F_F 0.30, non-perpendicular incidence F_w 0.9 and shading F_sh 0.9
GLASS_SHARE = 1 - 0.30
F_W = 0.9
F_SH = 0.9
# A signature's A_sol multiplies the *global horizontal* irradiance, so a vertical surface counts
# with irradiance(vertical) / irradiance(horizontal): energy-weighted over the heating season
# (October-April) of the NTA 8800 reference climate (De Bilt, monthly means), windows equally
# divided over north, east, south and west, as in the RVO reference dwellings. An earlier value
# (1.1543) was the inverse ratio (horizontal / vertical), averaged per month instead of
# energy-weighted; it put A_sol about 1.6 times too high.
VERTICAL_IRRADIANCE_RATIO = 0.731

# Maatwerkadvies corrections (Van den Brom et al., 2022, table p. 24-25)
MWA_RC_SURCHARGE = 0.15
MWA_U_WINDOW_DOOR = 0.9
MWA_B_UNHEATED = 0.7
MWA_INFILTRATION = 0.5

# NTA 8800 default Rc [m²K/W] by construction period [from, to): wall, ground floor, roof
_RC = [
    (0, 1965, 0.19, 0.15, 0.22), (1965, 1975, 0.43, 0.17, 0.86), (1975, 1983, 1.3, 0.52, 1.3),
    (1983, 1988, 1.3, 1.3, 1.3), (1988, 1992, 2.0, 1.3, 2.0), (1992, 2014, 2.5, 2.5, 2.5),
    (2014, 2015, 3.5, 3.5, 3.5), (2015, 2021, 4.5, 3.5, 6.0), (2021, 9999, 4.7, 3.7, 6.3),
]
# glazing g-value (ggl;n) by construction period: the typical glazing of the (larger share of)
# bedroom windows: single glass until 1992, double, HR++, triple
_GGL = [(0, 1992, 0.85), (1992, 2014, 0.75), (2014, 2021, 0.6), (2021, 9999, 0.4)]
_GGL_BY_TYPE = {"enkel": 0.85, "dubbel": 0.75, "hr": 0.75, "hr_p": 0.75, "hr_pp": 0.6,
                "triple": 0.4, "hr_ppp": 0.4}
# specific internal heat capacity [kJ/(m²K)] by construction period
_MASS = [(0, 1950, 180.0), (1950, 1995, 360.0), (1995, 9999, 450.0)]
# door U [W/(m²K)] by construction period
_DOOR_U = [(0, 2005, 1.4925), (2005, 9999, 2.9930)]

# RVO reference dwellings 2022, as used by the nta8800/mwa methods: window fraction of the outer
# wall excluding doors, door area [m²], window U [W/(m²K)]
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

VARIANTS = ["oorspronkelijk", "huidig", "besparingspakket_1", "besparingspakket_3"]
_HOOFDVORM = {"vrijstaand": "vrijstaande woning", "twee_onder_een_kap": "2-onder-1-kap",
              "hoekwoning": "rijwoning hoek", "tussenwoning": "rijwoning tussen"}
_TYPES = tuple(_HOOFDVORM)


# ------------------------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------------------------

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
    """Reference dwelling (nta8800/mwa) for this type and period; nearest period if none."""
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


@lru_cache(maxsize=1)
def reference_dwellings() -> dict:
    """RVO reference dwellings 2022 (single-family, median variants), keyed by
    (dwelling type, construction period label)."""
    path = Path(__file__).with_name("data") / "rvo_voorbeeldwoningen_2022_grondgebonden.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    back = {v: k for k, v in _HOOFDVORM.items()}
    return {(back[w["hoofdvorm"]], w["bouwjaarklasse"]): w for w in data["woningen"]}


def _ref_class(dwelling_type: str, year: float) -> str:
    rij = dwelling_type in ("hoekwoning", "tussenwoning")
    if year < (1946 if rij else 1965):
        return "< 1946" if rij else "< 1965"
    for lo, hi, label in ((1946, 1965, "1946–1964"), (1965, 1975, "1965–1974"),
                          (1975, 1992, "1975–1991"), (1992, 2006, "1992–2005"),
                          (2006, 2015, "2006–2014")):
        if lo <= year < hi:
            return label
    return "2015–2018"


def _ref_arrays(ref: dict) -> dict:
    """Per variant: U per component, glazing g, heat demand; plus areas and compactness."""
    parts = ref["bouwdelen"]
    areas = {k: parts[k]["oppervlak__m2"] for k in parts}
    a_ls = sum(areas.values())
    return {
        "U": {k: [parts[k]["u__W_m_2_K_1"].get(v) for v in VARIANTS] for k in parts},
        "g": [_GGL_BY_TYPE.get(parts["raam"]["glastype"].get(v), 0.75) for v in VARIANTS],
        "q": [ref["warmtebehoefte_qhnd__kWh_m_2"][v] for v in VARIANTS],
        "b_floor": parts.get("vloer", {}).get("b_factor__0", 1.0),
        "window_frac": areas["raam"] / (areas["gevel"] + areas["raam"] + areas.get("deur", 0)),
        "door": areas.get("deur", 0.0),
        "compactness": a_ls / ref["gebruiksoppervlak__m2"],
        "shares": {k: areas[k] / a_ls for k in areas},
        "id": ref["id"],
    }


def _level_from_heat_demand(q: list[float], w: float) -> float:
    """Position 0..3 on the reference dwelling's variant scale for heat demand ``w``."""
    if w >= q[0]:
        return 0.0
    if w <= q[-1]:
        return float(len(q) - 1)
    for i in range(len(q) - 1):
        hi, lo = q[i], q[i + 1]
        if lo <= w <= hi:
            return i + (0.0 if hi == lo else (hi - w) / (hi - lo))
    return 1.0


def _interp(values: list, t: float) -> float:
    vals = [np.nan if v is None else v for v in values]
    i = int(np.floor(t))
    if i >= len(vals) - 1:
        return vals[-1]
    f = t - i
    return vals[i] * (1 - f) + vals[i + 1] * f


# ------------------------------------------------------------------------------------------------
# computation
# ------------------------------------------------------------------------------------------------

def compute(df: pd.DataFrame, method: str = "nta8800", *, detail: bool = False) -> pd.DataFrame:
    """The signature for every row of ``df`` (columns :data:`INPUT`; missing EP-online columns
    are treated as unknown). Returns :data:`OUTPUTS` (and :data:`DETAIL` with ``detail=True``).
    Rows that are not single-family or lack envelope data get NaN."""
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}, got {method!r}")
    df = df.copy()
    for c in INPUT:
        if c not in df:
            df[c] = None
    n = len(df)
    idx = df.index
    year = pd.to_numeric(df["bouwjaar"], errors="coerce").to_numpy(dtype=float)
    gbo = pd.to_numeric(df["oppervlakte"], errors="coerce").to_numpy(dtype=float)
    num = {c: pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
           for c in ("opp_buitenmuur", "opp_grond", "opp_dak_plat", "opp_dak_schuin",
                     "opp_scheidingsmuur")}
    single = pd.to_numeric(df["pand_woningen"], errors="coerce").to_numpy() == 1

    dtype = df["woningtype"].astype(object).where(df["woningtype"].isin(_TYPES))
    guess = infer_dwelling_type(df["aaneengebouwd"],
                                pd.Series(num["opp_scheidingsmuur"], index=idx),
                                pd.Series(num["opp_buitenmuur"], index=idx))
    dtype = dtype.fillna(guess)
    types = dtype.tolist()

    u = {k: np.full(n, np.nan) for k in ("gevel", "raam", "deur", "vloer", "dak")}
    frac, door, g, b_floor = (np.full(n, np.nan) for _ in range(4))
    level = np.full(n, np.nan)
    shares = {k: np.full(n, 0.0) for k in ("gevel", "raam", "deur", "vloer", "dak")}
    ref_id = np.full(n, None, dtype=object)
    source = np.full(n, None, dtype=object)

    if method in ("nta8800", "mwa"):
        cache: dict = {}
        for i, (t, y) in enumerate(zip(types, year)):
            if t is None or (isinstance(t, float) and np.isnan(t)) or np.isnan(y):
                continue
            key = (t, _period(y))
            if key not in cache:
                cache[key] = _rvo(t, y)
            frac[i], door[i], u["raam"][i] = cache[key]
            ref_id[i] = f"{t} {key[1]}"
        u["gevel"] = 1 / (_lookup(year, _RC, 2) + R_SI["wall"] + R_SE)
        u["vloer"] = 1 / (_lookup(year, _RC, 3) + R_SI["floor"])
        u["dak"] = 1 / (_lookup(year, _RC, 4) + R_SI["roof"] + R_SE)
        u["deur"] = _lookup(year, _DOOR_U, 2)
        g = _lookup(year, _GGL, 2)
        b_floor[:] = GROUND_FACTOR
        level[:] = 0.0
        source[:] = "bouwjaar"
    else:
        refs = reference_dwellings()
        prepared: dict = {}
        label = df["energielabel"].astype(object).tolist()
        heat = pd.to_numeric(df["warmtebehoefte"], errors="coerce").to_numpy(dtype=float)
        is_nta = df["nta8800"].astype("boolean").fillna(False).to_numpy(dtype=bool)
        compact = pd.to_numeric(df["compactheid"], errors="coerce").to_numpy(dtype=float)
        for i, (t, y) in enumerate(zip(types, year)):
            if t is None or (isinstance(t, float) and np.isnan(t)) or np.isnan(y):
                continue
            key = (t, _ref_class(t, y))
            if key not in prepared:
                prepared[key] = _ref_arrays(refs[key])
            r = prepared[key]
            if is_nta[i] and heat[i] > 0:
                w = heat[i] * (r["compactness"] / compact[i]) if compact[i] > 0 else heat[i]
                t_level, src = _level_from_heat_demand(r["q"], w), "warmtebehoefte"
            elif isinstance(label[i], str) and label[i]:
                t_level = 2.0 if label[i].startswith("A+") else 1.5 if label[i] in ("A", "B") \
                    else 1.0
                src = "labelklasse"
            else:
                t_level, src = 1.0, "referentie"
            for k in u:
                if k in r["U"]:
                    u[k][i] = _interp(r["U"][k], t_level)
            g[i] = _interp(r["g"], t_level)
            frac[i], door[i], b_floor[i] = r["window_frac"], r["door"], r["b_floor"]
            level[i], ref_id[i], source[i] = t_level, r["id"], src
            for k, v in r["shares"].items():
                shares[k][i] = v

    if method in ("mwa", "best", "ep", "ep_3dbag"):
        with np.errstate(divide="ignore"):
            for k in ("gevel", "vloer", "dak"):
                u[k] = 1 / (1 / u[k] + MWA_RC_SURCHARGE)
        u["raam"] = u["raam"] * MWA_U_WINDOW_DOOR
        u["deur"] = u["deur"] * MWA_U_WINDOW_DOOR
        b_floor = b_floor * MWA_B_UNHEATED

    if method == "ep":
        # the envelope from the label: loss area = compactness x usable area, divided like the
        # reference dwelling; nothing from 3D-BAG
        ag = pd.to_numeric(df["label_oppervlakte"], errors="coerce").to_numpy(dtype=float)
        a_ls = pd.to_numeric(df["compactheid"], errors="coerce").to_numpy(dtype=float) * ag
        windows, walls, door = a_ls * shares["raam"], a_ls * shares["gevel"], a_ls * shares["deur"]
        ground = a_ls * shares["vloer"] * b_floor
        roof = a_ls * shares["dak"]
        gbo = ag
    else:
        windows = num["opp_buitenmuur"] * frac
        walls = num["opp_buitenmuur"] - windows - door
        ground = num["opp_grond"] * b_floor
        roof = num["opp_dak_plat"] + num["opp_dak_schuin"]
        if method == "ep_3dbag":
            # the shape from 3D-BAG, the size of the thermal envelope from the label
            ag = pd.to_numeric(df["label_oppervlakte"], errors="coerce").to_numpy(dtype=float)
            a_ls = pd.to_numeric(df["compactheid"], errors="coerce").to_numpy(dtype=float) * ag
            with np.errstate(divide="ignore", invalid="ignore"):
                scale = a_ls / (num["opp_buitenmuur"] + num["opp_grond"] + roof)
            windows, walls, ground, roof = (x * scale for x in (windows, walls, ground, roof))
            door = door * scale
            gbo = ag
    H = walls * u["gevel"] + windows * u["raam"] + door * u["deur"] + ground * u["vloer"] \
        + roof * u["dak"]
    C = _lookup(year, _MASS, 2) * 1000 / 3600 * gbo
    opaque = ALPHA_SOL * R_SE
    A_sol = (windows * GLASS_SHARE * g * F_W * F_SH * VERTICAL_IRRADIANCE_RATIO
             + walls * opaque * u["gevel"] * VERTICAL_IRRADIANCE_RATIO
             + door * opaque * u["deur"] * VERTICAL_IRRADIANCE_RATIO
             + roof * opaque * u["dak"])
    a_inf = A_INF_NL_AVG__cm2 * (MWA_INFILTRATION if method in ("mwa", "best", "ep", "ep_3dbag")
                                 else 1.0)
    ok = single & np.isfinite(H) & (H > 0) & np.isfinite(C) & (walls > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        tau = C / H
    out = pd.DataFrame({
        "H": np.where(ok, H, np.nan), "C": np.where(ok, C, np.nan),
        "tau": np.where(ok, tau, np.nan), "Asol": np.where(ok, A_sol, np.nan),
        "Ainf": np.where(ok, a_inf, np.nan),
    }, index=idx).round({"H": 2, "C": 1, "tau": 3, "Asol": 3, "Ainf": 1})
    if detail:
        extra = pd.DataFrame({
            "A_gevel": walls, "A_raam": windows, "A_deur": door, "A_grond": ground, "A_dak": roof,
            "U_gevel": u["gevel"], "U_raam": u["raam"], "U_deur": u["deur"],
            "U_grond": u["vloer"], "U_dak": u["dak"], "g_raam": g,
            "woningtype_gebruikt": dtype.to_numpy(dtype=object), "referentiewoning": ref_id,
            "isolatieniveau": level, "bron": source,
        }, index=idx)
        num_cols = [c for c in extra.columns if c.startswith(("A_", "U_", "g_", "iso"))]
        extra[num_cols] = extra[num_cols].astype(float).round(3)
        extra.loc[~ok, :] = None
        out = out.join(extra)
    return out


# ------------------------------------------------------------------------------------------------
# the same quantity as a learned signature
# ------------------------------------------------------------------------------------------------

# NTA 8800 ventilation of a dwelling (§11.2.2, eqs. 11.22, 11.56, 7.19; table 11.8, 11.9): the
# time-averaged outdoor air flow for system C1 (natural supply, mechanical exhaust), the most
# common system in the current stock
AIR_HEAT_CAPACITY__J_m_3_K_1 = 1.205 * 1005.0      # §7.4.3, eq. 7.19
Q_SPEC_DWELLING__dm3_s_1_m_2 = 0.50                # table 11.8
Q_MIN_DWELLING__dm3_s_1 = 35.0                     # eq. 11.63
F_LEA_DUCT__0 = 1.10                               # table 11.9, ducts, airtightness unknown
F_PRAC_REQ__0 = 0.95                               # eq. 11.22
# Maatwerkadvies (Van den Brom et al., 2022, RVO, p. 27): real ventilation is 0.25 (system A)
# to 0.75 (system D) of the NTA 8800 value; system C in the middle
MWA_VENTILATION_C__0 = 0.50
# heating-season mean indoor and outdoor temperature derived from the NTA 8800 reference
# climate (needforheat-diagnosis-software, nfh_constants.py), and the assumed thermostat
# setting of the room where a learning model measures the indoor temperature
T_INDOOR_MEAN__degC = 18.33
T_OUTDOOR_MEAN__degC = 6.44
T_THERMOSTAT_ROOM__degC = 20.0
# Time constant measured from smart-thermostat data (1319 Toon homes, winter 2016-2017; Vosmer,
# 2018, TU Delft master thesis, table 5.4; also TNO 2019 P10600 (VeniVidiFlexi), table 13): per
# home from the night-time cooling of the thermostat room after at least 4 hours with the
# heating off, tau = -t / ln(1 - (T0 - Tt) / (T0 - Te)), averaged per construction period. The
# thesis labels the first class "before 1967", TNO "before 1976"; the classes follow those of
# Milieu Centraal (before 1976, 1976-1988, ...), so 1976. The calculated values Milieu Centraal
# uses for the same classes (Van den Ham & Van der Vliet, 2013) are 14, 28, 49 and 80 h.
TAU_MEASURED__h = [(0, 1976, 40.0), (1976, 1989, 50.0), (1989, 2001, 57.0), (2001, 9999, 71.0)]


def ventilation_H(usable_area, factor: float = MWA_VENTILATION_C__0):
    """Ventilation heat transfer [W/K]: NTA 8800 flow for system C1 times ``factor``."""
    ag = np.asarray(usable_area, dtype=float)
    f_tau = np.minimum(0.38 + 0.006 * ag, 0.8)
    q = np.maximum(Q_SPEC_DWELLING__dm3_s_1_m_2 * ag, Q_MIN_DWELLING__dm3_s_1)  # dm³/s
    flow = F_LEA_DUCT__0 * f_tau * q * 3.6 / F_PRAC_REQ__0                       # m³/h
    return AIR_HEAT_CAPACITY__J_m_3_K_1 * flow / 3600.0 * factor


def as_learned(sig: pd.DataFrame, usable_area, *, ventilation: float | None = MWA_VENTILATION_C__0,
               room_temperature: bool = True, construction_year=None,
               tau: str = "berekend") -> pd.DataFrame:
    """A computed signature expressed as the quantity a learning model estimates.

    A model that learns H from gas use and one measured indoor temperature, without a measured
    ventilation flow, finds a single H that holds *all* losses proportional to indoor minus
    outdoor temperature, relative to *that* room. The computed H is transmission through the
    envelope, relative to the dwelling's mean temperature. To compare like with like:

    - ``ventilation``: add the ventilation loss (:func:`ventilation_H` with this factor;
      ``None`` leaves it out);
    - ``room_temperature``: scale by (mean indoor − outdoor) / (thermostat room − outdoor),
      since a warmer measuring room makes the same loss look like a smaller H.

    A_sol is defined alike on both sides (gains = global horizontal irradiance × A_sol) and C is
    left as is (total, where a learned C is the part that takes part in daily dynamics); τ
    follows from C / H. Infiltration stays out on both sides (a learning model typically fixes it
    at a national average).

    ``tau="gemeten"`` (needs ``construction_year``) replaces τ by the mean time constant measured
    from smart-thermostat data for the construction period (:data:`TAU_MEASURED__h`), and C by
    τ · H: what a learning model sees, where the tabulated thermal mass makes older homes far
    too fast.
    """
    out = sig.copy()
    h = out["H"].astype(float)
    if ventilation is not None:
        h = h + ventilation_H(usable_area, ventilation)
    if room_temperature:
        h = h * ((T_INDOOR_MEAN__degC - T_OUTDOOR_MEAN__degC)
                 / (T_THERMOSTAT_ROOM__degC - T_OUTDOOR_MEAN__degC))
    out["H"] = h
    if tau == "gemeten":
        if construction_year is None:
            raise ValueError("tau='gemeten' needs construction_year")
        t = _lookup(np.asarray(construction_year, dtype=float), TAU_MEASURED__h, 2)
        out["tau"] = t
        out["C"] = t * h
    elif tau == "berekend":
        out["tau"] = out["C"] / h
    else:
        raise ValueError(f"tau must be 'berekend' or 'gemeten', got {tau!r}")
    return out


def baseline(df: pd.DataFrame, method: str = "nta8800") -> pd.DataFrame:
    """:func:`compute` with ``sig_``-prefixed columns, as stored in the population."""
    return compute(df, method).add_prefix("sig_")


# ------------------------------------------------------------------------------------------------
# for all dwellings, or one address, from the local population (offline)
# ------------------------------------------------------------------------------------------------

def table(population_path: str | Path, out: str | Path, *, methods=METHODS,
          detail: bool = False, context: bool = True, batch_rows: int = 250_000,
          progress=lambda _: None) -> Path:
    """The signature of every single-family dwelling, all ``methods``, each output in its own
    column (``nta8800_H``, ``best_tau``, ...), keyed by BAG id and address; streamed to
    Parquet so memory stays small. With ``context`` the table also carries region and
    dwelling attributes (:data:`CONTEXT`), so a rainbow table for a subset can be made from it
    (``anonymate signatuur regenboog --bron ... --scope ...``)."""
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq

    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'")
    src = Path(population_path).as_posix()
    have = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{src}')").fetchall()}
    wanted = KEYS + INPUT + (CONTEXT if context else [])
    cols = [c for c in dict.fromkeys(wanted) if c in have]
    reader = con.execute(f"SELECT {', '.join(cols)} FROM read_parquet('{src}') "
                         "WHERE eengezins").fetch_record_batch(batch_rows)
    out = Path(out)
    part = out.with_suffix(out.suffix + ".part")
    writer, n = None, 0
    try:
        for batch in reader:
            df = batch.to_pandas()
            keep = KEYS + ([c for c in CONTEXT if c in df] if context else [])
            res = df[[c for c in dict.fromkeys(keep) if c in df]].copy()
            for m in methods:
                sig = compute(df, m, detail=detail)
                res = res.join(sig.add_prefix(f"{m}_"))
            if writer is None:
                # a fixed schema: source columns keep their DuckDB types (a column that happens
                # to be empty in one batch must not get a different type there), outputs are
                # float64, the few text details string
                fields = [batch.schema.field(c) for c in res.columns if c in batch.schema.names]
                fields += [pa.field(c, pa.string() if c.endswith(_TEXT_DETAIL) else pa.float64())
                           for c in res.columns if c not in batch.schema.names]
                schema = pa.schema(fields)
            tbl = pa.Table.from_pandas(res, schema=schema, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(part, tbl.schema, compression="zstd")
            writer.write_table(tbl)
            n += len(res)
            progress(f"signatuur: {n:,} woningen")
    finally:
        if writer is not None:
            writer.close()
    part.replace(out)
    return out


def lookup(population_path: str | Path, postcode: str, huisnummer: int, huisletter: str = "",
           toevoeging: str = "", *, methods=METHODS, detail: bool = True) -> pd.DataFrame:
    """Signature(s) for one address, computed from the local population. Several rows if the
    address is ambiguous (e.g. no house letter given)."""
    import duckdb

    src = Path(population_path).as_posix()
    con = duckdb.connect()
    have = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{src}')").fetchall()}
    cols = [c for c in KEYS + INPUT if c in have]
    sql = (f"SELECT {', '.join(cols)} FROM read_parquet('{src}') WHERE postcode6 = ? "
           "AND huisnummer = ?")
    params: list = [postcode.replace(" ", "").upper(), int(huisnummer)]
    if huisletter:
        sql += " AND upper(coalesce(CAST(huisletter AS VARCHAR), '')) = ?"
        params.append(huisletter.upper())
    if toevoeging:
        sql += " AND upper(coalesce(CAST(toevoeging AS VARCHAR), '')) = ?"
        params.append(toevoeging.upper())
    df = con.execute(sql, params).fetchdf()
    res = df[[c for c in KEYS if c in df]].copy()
    for m in methods:
        res = res.join(compute(df, m, detail=detail).add_prefix(f"{m}_"))
    return res
