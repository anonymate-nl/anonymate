"""Heat signature of every single-family home, from its address and public data only.

The *heat signature* (warmtesignatuur) of a dwelling is a small set of
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
``passend``
    Per dwelling the most suitable method at the time of publication: ``ep`` for a dwelling with
    a label that has a compactness, ``best`` otherwise. A fixed, public rule: an attacker who
    applies it to the same register version gets the same values, so the rainbow table holds.
    With ``detail=True`` the column ``methode_gebruikt__cat`` says which one was used.
``ep_cbag``, ``passend_cbag``
    As ``ep`` and ``passend``, but with the thermal mass C from the BAG usable area instead of
    the label's. A published C then agrees with a published (BAG) floor-area class, instead of
    being a second, independent floor-area figure that can single out a dwelling whose label and
    BAG area differ.

Assumptions, all deliberately simple and open: party walls adiabatic; ground floor 70%
effective; window share and door area from the reference dwelling; façade orientations averaged
(the RVO reference dwellings do so as well); thermal mass from the NTA 8800 table by period;
Ainf from the forfaitary air tightness of NTA 8800 per dwelling (see :func:`infiltration`); the
RVO notes that its reference dwellings are not meant to calculate individual homes; here that is
precisely the point, since this is what anyone *can* calculate.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import namen

# Exposed façade area per orientation of the dwelling's building (BAG pand footprint x wall
# height; see :mod:`anonymate.gevel`): eight 45-degree sectors, compass, clockwise from north.
# ``gevel_<richting>__m2`` the exposed wall (party walls excluded), ``gevelzij_<richting>__m2``
# the part of it that is a side façade (normal perpendicular to the building's main axis).
RICHTING_CODES = ("n", "no", "o", "zo", "z", "zw", "w", "nw")
GEVEL_COLUMNS = [f"gevel_{r}__m2" for r in RICHTING_CODES]
GEVEL_ZIJ_COLUMNS = [f"gevelzij_{r}__m2" for r in RICHTING_CODES]

METHODS = namen.METHODEN
# The short keys of the outputs: identifiers of a choice (publicatie.Plan steps, the interface).
# The columns they give carry a unit: ``H`` -> ``H__W_K_1`` (see :func:`namen.uitvoer_kolom`).
OUTPUTS = list(namen.UITVOER_EENHEID)
OUTPUT_COLUMNS = [namen.uitvoer_kolom(o) for o in OUTPUTS]
DETAIL = ["A_gevel__m2", "A_raam__m2", "A_deur__m2", "A_grond__m2", "A_dak__m2",
          "U_gevel__W_m_2_K_1", "U_raam__W_m_2_K_1", "U_deur__W_m_2_K_1",
          "U_grond__W_m_2_K_1", "U_dak__W_m_2_K_1", "g_raam__0", "woningtype_gebruikt__cat",
          "referentiewoning__str", "isolatieniveau__0", "bron__cat", "methode_gebruikt__cat",
          "oppervlakte_gebruikt__m2", "oppervlakte_bron__str", "qv10__dm3_s_1_m_2", "ELA__cm2",
          "bouwlagenklasse__cat", "Ainf_bron__str", "asol_bron__str"]
INPUT = ["bouwjaar__yr", "oppervlakte__m2", "woningtype__cat", "pand_woningen__0",
         "aaneengebouwd__bool", "daktype__cat", "bouwlagen__0",
         "opp_buitenmuur__m2", "opp_grond__m2", "opp_dak_plat__m2", "opp_dak_schuin__m2",
         "opp_scheidingsmuur__m2", "energielabel__cat", "warmtebehoefte__kWh_m_2_a_1",
         "nta8800__bool", "compactheid__m2_m_2", "label_oppervlakte__m2"]
INPUT += GEVEL_COLUMNS + GEVEL_ZIJ_COLUMNS
KEYS = ["vbo_id__str", "postcode6__str", "huisnummer__str", "huisletter__str", "toevoeging__str"]
_TEXT_DETAIL = ("woningtype_gebruikt__cat", "referentiewoning__str", "bron__cat",
                "methode_gebruikt__cat", "oppervlakte_bron__str", "Ainf_bron__str",
                "asol_bron__str")
# kept in the functional table so it can be narrowed down later (region, inclusion criteria)
CONTEXT = ["postcode4__str", "woonplaats__cat", "gemeente__cat", "provincie__cat",
           "knmi_station__cat", "h3_r4__str", "h3_r5__str", "h3_r6__str", "h3_r7__str",
           "h3_r8__str", "bouwjaar__yr", "oppervlakte__m2", "woningtype__cat", "daktype__cat",
           "bouwlagen__0", "hoogte__m", "aaneengebouwd__bool", "energielabel__cat"]

# National average, used only as a fallback when the inputs for the per-dwelling infiltration
# are missing (construction year, usable area, dwelling type); detail column ``Ainf_bron__str``.
A_INF_NL_AVG__cm2 = 108.0
GROUND_FACTOR__0 = 0.7
R_SI__m2_K_W_1 = {"wall": 0.13, "floor": 0.17, "roof": 0.10}
R_SE__m2_K_W_1 = 0.04
ALPHA_SOL__0 = 0.6
# Solar gains through glazing, NTA 8800: A_sol = A_w · (1 − F_F) · g_gl;n · F_w · F_sh, with the
# default frame fraction F_F 0.30, non-perpendicular incidence F_w 0.9 and shading F_sh 0.9
GLASS_SHARE__0 = 1 - 0.30
F_W__0 = 0.9
F_SH__0 = 0.9
# A signature's A_sol multiplies the *global horizontal* irradiance, so a vertical surface counts
# with irradiance(vertical) / irradiance(horizontal): energy-weighted over the heating season
# (October-April) of the NTA 8800 reference climate (De Bilt, monthly means), windows equally
# divided over north, east, south and west, as in the RVO reference dwellings. An earlier value
# (1.1543) was the inverse ratio (horizontal / vertical), averaged per month instead of
# energy-weighted; it put A_sol about 1.6 times too high.
VERTICAL_IRRADIANCE_RATIO__W0 = 0.731

# Orientation-dependent A_sol (docs/warmtesignatuur.md, "A_sol per gevelrichting"). For a dwelling whose exposed façades
# are known (BAG pand footprint), the methods best, ep, ep_3dbag, ep_cbag, passend and
# passend_cbag replace the single ratio above with R_o per orientation o: energy on a vertical
# plane facing o / energy on a horizontal plane, summed over the heating season hours
# (October-April 2025-26) of KNMI De Bilt (260), hourly global radiation Q. Method
# (anonymate.instraling; recomputed by tests/test_signature.py from
# docs/data/knmi_260_straling_2025-26.csv, script tools/instraling_r.py): NOAA solar position,
# Erbs (1982) diffuse fraction, Hay & Davies (1980) transposition, ground albedo 0.2. Order N,
# NE, E, SE, S, SW, W, NW. The plain mean of N/E/S/W of these computed values is 0.700, against
# 0.731 for NTA 8800 (other climate year and other sky model). They are therefore scaled so that
# that mean equals VERTICAL_IRRADIANCE_RATIO__W0: the pattern over the orientations comes from KNMI,
# the level from NTA 8800, so a difference between nta8800 and best comes from the orientation of
# the façades only, not from the climate year. nta8800 and mwa stay orientation-averaged on
# purpose: standard-conform and comparable with the RVO reference dwellings.
R_VERTICAAL_KNMI_260_2025_26__W0 = (0.2982, 0.3838, 0.6550, 1.0085, 1.1884, 1.0165, 0.6596,
                                    0.3822)
_R_SCHAAL__0 = VERTICAL_IRRADIANCE_RATIO__W0 / (sum(R_VERTICAAL_KNMI_260_2025_26__W0[0::2]) / 4)
R_VERTICAAL_PER_RICHTING__W0 = tuple(round(r * _R_SCHAAL__0, 4)
                                     for r in R_VERTICAAL_KNMI_260_2025_26__W0)
# Windows are distributed over the exposed façades in proportion to their area, but a side
# façade (hoekwoning, twee-onder-een-kap, not vrijstaand) counts with this weight: side walls
# have fewer and smaller windows than front and back.
GEVEL_ZIJ_GEWICHT__0 = 0.5
ASOL_BRON_RICHTING__str = "gevelrichting (BAG-pand, R_o De Bilt)"
ASOL_BRON_GEMIDDELD__str = "gemiddelde verhouding (gevelrichting onbekend)"
ASOL_BRON_STANDAARD__str = "gemiddelde verhouding (methode is richtingsgemiddeld)"

# Maatwerkadvies corrections (Van den Brom et al., 2022, table p. 24-25)
MWA_RC_SURCHARGE__m2_K_W_1 = 0.15
MWA_U_WINDOW_DOOR__0 = 0.9
MWA_B_UNHEATED__0 = 0.7
MWA_INFILTRATION__0 = 0.5          # on qv10, Van den Brom et al. (2022), p. 26-27

# --- infiltration per dwelling -----------------------------------------------------------------
# Forfaitary air tightness qv10 [dm³/(s·m²) of usable area A_g] of NTA 8800 eq. (11.86):
# qv10 = f_type · f_y · q_spec. Referenced to the usable floor area (NTA 8800 §11.2.5, eq. 11.85,
# NOTE 2; NEN 2686), not to the envelope.
# f_y, table 11.13, by construction year (lower bound of the interval)
_F_Y = [(0, 1970, 3.0), (1970, 1980, 2.5), (1980, 1990, 2.0), (1990, 2000, 1.5),
        (2000, 2010, 1.0), (2010, 9999, 0.7)]
# q_spec, table 11.14, single-family: pitched roof 1.0, flat roof 0.7. Roof type from 3D-BAG
# (``daktype__cat``: plat / plat_meerdere = flat); unknown -> pitched, the higher (conservative) value.
Q_SPEC_PITCHED__dm3_s_1_m_2 = 1.0
Q_SPEC_FLAT__dm3_s_1_m_2 = 0.7
# f_type, table 11.14, single-family
F_TYPE__0 = {"tussenwoning": 1.0, "hoekwoning": 1.2, "twee_onder_een_kap": 1.2, "vrijstaand": 1.4}
# Sanity check: these values reproduce the qv10 ladder 3.0 / 1.8 / 1.2 / 0.7 / 0.4 of PBL's public
# Hestia model (element KR, "Qv10 3.0" ... "Qv10 0.4") and the RVO reference dwellings (0.7 and
# 0.4 for their packages).
# Flow law q ~ dp^n, n = 0.67, from 10 Pa back to 4 Pa; effective leakage area (ELA, discharge
# coefficient 1) at dp = 4 Pa, rho = 1.2 kg/m³.
FLOW_EXPONENT__0 = 0.67
ELA_DP__Pa = 4.0
AIR_DENSITY__kg_m3 = 1.2
# LBL model (Sherman & Grimsrud), ASHRAE Handbook - Fundamentals, infiltration chapter, shelter
# class 3 (suburban): flow [L/s] = ELA [cm²] · sqrt(C_s · dT + C_w · v²), dT in K, v (10 m) in
# m/s; per number of storeys 1 / 2 / 3.
LBL_CS = {1: 0.000145, 2: 0.000290, 3: 0.000435}
LBL_CW = {1: 0.000319, 2: 0.000420, 3: 0.000494}
# Linearisation to the signature's A_inf, the learning model's flow = v · A_inf (heat loss =
# rho · c_p · v · A_inf · dT; A_inf in cm², so flow [L/s] = 0.1 · v [m/s] · A_inf [cm²]): choose
# A_inf so the heat loss matches over a heating season,
#   A_inf = 10 · sum_h flow_LBL(dT_h, v_h) · dT_h / sum_h v_h · dT_h = ELA · k_storeys.
# k per storey class computed with :func:`lbl_linearisation` (tools/infiltratie_k.py) from KNMI
# hourly data, station De Bilt (260), heating season October 2025 - April 2026, T_in 20 degrees,
# hours with dT > 0 (docs/data/knmi_260_uur_2025-26.csv; test_signature recomputes them).
LBL_K__0 = {1: 0.2300, 2: 0.2877, 3: 0.3310}
LBL_T_IN__degC = 20.0

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


# Share of party wall in all wall area, per registered type (EP-online, single-family homes,
# population of 2026-09; 10th / 50th / 90th percentile): semi-detached 0.24 / 0.31 / 0.38,
# corner 0.24 / 0.31 / 0.37, mid-terrace 0.50 / 0.62 / 0.70. Between the two groups: 0.44.
# Corner and semi-detached cannot be told apart this way (both one party wall); see
# kladbloknotitie 8.
MID_TERRACE_SHARE__0 = 0.44


def infer_dwelling_type(attached, party_wall: pd.Series, outer_wall: pd.Series) -> pd.Series:
    """Rough single-family type from 3D-BAG when no registered type exists: not attached ->
    detached; otherwise by the share of party wall in all wall area."""
    share = party_wall / (party_wall + outer_wall).replace(0, np.nan)
    out = pd.Series("tussenwoning", index=party_wall.index, dtype=object)
    out[share < MID_TERRACE_SHARE__0] = "twee_onder_een_kap"
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


def qv10_forfaitary(year, dwelling_type, roof=None) -> np.ndarray:
    """Forfaitary air tightness qv10 [dm³/(s·m²) usable area], NTA 8800 eq. (11.86):
    f_type · f_y · q_spec. ``roof``: 3D-BAG daktype (plat / plat_meerdere = flat; anything else,
    also unknown, pitched). NaN for an unknown year or type."""
    year = np.asarray(year, dtype=float)
    f_type = pd.Series(np.asarray(dwelling_type, dtype=object)).map(F_TYPE__0).to_numpy(dtype=float)
    flat = (pd.Series(np.asarray(roof if roof is not None else [None] * len(year), dtype=object))
            .isin(["plat", "plat_meerdere"]).to_numpy())
    q_spec = np.where(flat, Q_SPEC_FLAT__dm3_s_1_m_2, Q_SPEC_PITCHED__dm3_s_1_m_2)
    return f_type * _lookup(year, _F_Y, 2) * q_spec


def effective_leakage_area(qv10, usable_area) -> np.ndarray:
    """ELA [cm²] at 4 Pa (discharge coefficient 1) from qv10 [dm³/(s·m²)] and the usable area
    [m²]: q10 = qv10 · A_g [L/s] at 10 Pa, q4 = q10 · (4/10)^n, ELA = q4 / sqrt(2 dp / rho)."""
    q10 = np.asarray(qv10, dtype=float) * np.asarray(usable_area, dtype=float)      # L/s
    q4 = q10 * (ELA_DP__Pa / 10.0) ** FLOW_EXPONENT__0
    return q4 / 1000.0 / np.sqrt(2 * ELA_DP__Pa / AIR_DENSITY__kg_m3) * 1e4


def storey_class(storeys) -> np.ndarray:
    """Number of storeys clamped to 1..3; unknown -> 2 (the middle class)."""
    s = pd.to_numeric(pd.Series(np.asarray(storeys, dtype=object)), errors="coerce")
    return s.fillna(2).clip(1, 3).round().astype(int).to_numpy()


def lbl_flow(ela, delta_t, wind, storeys=2) -> np.ndarray:
    """LBL infiltration flow [L/s]: ELA [cm²] · sqrt(C_s dT + C_w v²) (see LBL_CS, LBL_CW)."""
    cls = pd.Series(storey_class(np.atleast_1d(storeys)))
    cs, cw = cls.map(LBL_CS).to_numpy(), cls.map(LBL_CW).to_numpy()
    return np.asarray(ela, dtype=float) * np.sqrt(cs * np.asarray(delta_t)
                                                  + cw * np.asarray(wind) ** 2)


def lbl_linearisation(temperature, wind, storeys: int, t_in: float = LBL_T_IN__degC) -> float:
    """k such that A_inf [cm²] = ELA [cm²] · k: heat-loss-equivalent linearisation of the LBL flow
    to flow = v · A_inf over the given hours (hours with dT > 0 only):
    k = 10 · sum sqrt(C_s dT + C_w v²) · dT / sum v · dT."""
    dt = t_in - np.asarray(temperature, dtype=float)
    v = np.asarray(wind, dtype=float)
    m = (dt > 0) & np.isfinite(dt) & np.isfinite(v)
    dt, v = dt[m], v[m]
    flow = np.sqrt(LBL_CS[storeys] * dt + LBL_CW[storeys] * v ** 2)
    return float(10.0 * np.sum(flow * dt) / np.sum(v * dt))


def infiltration(year, usable_area, dwelling_type, roof, storeys, *, maatwerk: bool) -> pd.DataFrame:
    """Per dwelling: qv10, ELA, storey class and A_inf [cm²] = ELA · k (x 0.5 on qv10 for the
    Maatwerkadvies methods). NaN where the year, area or type is unknown."""
    qv10 = qv10_forfaitary(year, dwelling_type, roof)
    if maatwerk:
        qv10 = qv10 * MWA_INFILTRATION__0
    ela = effective_leakage_area(qv10, usable_area)
    cls = storey_class(storeys)
    k = np.array([LBL_K__0[c] for c in cls])
    return pd.DataFrame({"qv10__dm3_s_1_m_2": qv10, "ELA__cm2": ela,
                         "bouwlagenklasse__cat": cls.astype(float), "Ainf__cm2": ela * k})


# ------------------------------------------------------------------------------------------------
# computation
# ------------------------------------------------------------------------------------------------

def _irradiance_ratios(df: pd.DataFrame, dwelling_type: np.ndarray, windows, walls, door):
    """Per dwelling the vertical / horizontal irradiance ratio of its windows (and door) and of
    its opaque walls, from the exposed façade per orientation: ``(r_win, r_wall, known)``.

    Windows and door follow the exposed façade with the side façades at
    :data:`GEVEL_ZIJ_GEWICHT__0` (weight 1 for a vrijstaand dwelling); the opaque wall is the
    gross wall (exposed area per orientation) minus what the windows and door take. ``known`` is
    False where the façades are missing or empty: the caller then uses the averaged ratio.
    """
    n = len(df)
    cols = lambda names: np.column_stack([  # noqa: E731
        pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float) if c in df
        else np.full(n, np.nan) for c in names])
    total, side = cols(GEVEL_COLUMNS), cols(GEVEL_ZIJ_COLUMNS)
    known = np.isfinite(total).all(axis=1) & (np.nansum(total, axis=1) > 0)
    total = np.where(known[:, None], total, 0.0)
    side = np.clip(np.nan_to_num(side), 0.0, total)
    weight_side = np.where(dwelling_type == "vrijstaand", 1.0, GEVEL_ZIJ_GEWICHT__0)[:, None]
    w = total - side + weight_side * side
    r = np.asarray(R_VERTICAAL_PER_RICHTING__W0)
    with np.errstate(divide="ignore", invalid="ignore"):
        f_win = w / w.sum(axis=1, keepdims=True)
        f_gross = total / total.sum(axis=1, keepdims=True)
        gross = walls + windows + door
        wall_o = np.maximum(gross[:, None] * f_gross - (windows + door)[:, None] * f_win, 0.0)
        wall_o = wall_o * (walls / wall_o.sum(axis=1))[:, None]     # back to the net wall area
        r_win = f_win @ r
        r_wall = np.where(wall_o.sum(axis=1) > 0, (wall_o @ r) / walls, f_gross @ r)
    return r_win, r_wall, known & np.isfinite(r_win) & np.isfinite(r_wall)


def compute(df: pd.DataFrame, method: str = "nta8800", *, detail: bool = False) -> pd.DataFrame:
    """The signature for every row of ``df`` (columns :data:`INPUT`; missing EP-online columns
    are treated as unknown). Returns :data:`OUTPUT_COLUMNS`, ``H__W_K_1`` and so on (and
    :data:`DETAIL` with ``detail=True``).
    Rows that are not single-family or lack envelope data get NaN."""
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}, got {method!r}")
    if method in ("passend", "passend_cbag"):
        ep = compute(df, "ep" if method == "passend" else "ep_cbag", detail=detail)
        best = compute(df, "best", detail=detail)
        h = namen.uitvoer_kolom("H")
        use_ep = ep[h].notna()
        out = ep.where(use_ep, best)
        if detail:
            out["methode_gebruikt__cat"] = np.where(use_ep, "ep",
                                                    np.where(best[h].notna(), "best", None))
        return out
    df = df.copy()
    for c in INPUT:
        if c not in df:
            df[c] = None
    n = len(df)
    idx = df.index
    year = pd.to_numeric(df["bouwjaar__yr"], errors="coerce").to_numpy(dtype=float)
    gbo = pd.to_numeric(df["oppervlakte__m2"], errors="coerce").to_numpy(dtype=float)
    num = {c.removesuffix("__m2"): pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
           for c in ("opp_buitenmuur__m2", "opp_grond__m2", "opp_dak_plat__m2",
                     "opp_dak_schuin__m2", "opp_scheidingsmuur__m2")}
    single = pd.to_numeric(df["pand_woningen__0"], errors="coerce").to_numpy() == 1

    dtype = df["woningtype__cat"].astype(object).where(df["woningtype__cat"].isin(_TYPES))
    guess = infer_dwelling_type(df["aaneengebouwd__bool"],
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
        u["gevel"] = 1 / (_lookup(year, _RC, 2) + R_SI__m2_K_W_1["wall"] + R_SE__m2_K_W_1)
        u["vloer"] = 1 / (_lookup(year, _RC, 3) + R_SI__m2_K_W_1["floor"])
        u["dak"] = 1 / (_lookup(year, _RC, 4) + R_SI__m2_K_W_1["roof"] + R_SE__m2_K_W_1)
        u["deur"] = _lookup(year, _DOOR_U, 2)
        g = _lookup(year, _GGL, 2)
        b_floor[:] = GROUND_FACTOR__0
        level[:] = 0.0
        source[:] = "bouwjaar"
    else:
        refs = reference_dwellings()
        prepared: dict = {}
        label = df["energielabel__cat"].astype(object).tolist()
        heat = pd.to_numeric(df["warmtebehoefte__kWh_m_2_a_1"], errors="coerce").to_numpy(dtype=float)
        is_nta = df["nta8800__bool"].astype("boolean").fillna(False).to_numpy(dtype=bool)
        compact = pd.to_numeric(df["compactheid__m2_m_2"], errors="coerce").to_numpy(dtype=float)
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

    if method in ("mwa", "best", "ep", "ep_3dbag", "ep_cbag"):
        with np.errstate(divide="ignore"):
            for k in ("gevel", "vloer", "dak"):
                u[k] = 1 / (1 / u[k] + MWA_RC_SURCHARGE__m2_K_W_1)
        u["raam"] = u["raam"] * MWA_U_WINDOW_DOOR__0
        u["deur"] = u["deur"] * MWA_U_WINDOW_DOOR__0
        b_floor = b_floor * MWA_B_UNHEATED__0

    # Two floor areas, kept apart: the usable floor area of the dwelling in the BAG (a_bag), and
    # the usable floor area of the heated zone the energy label is computed for (A_g, NTA 8800;
    # the label's "gebruiksoppervlakte"). They can differ by tens of m² either way. The envelope
    # (loss area) always comes from A_g when there is a label, falling back on the BAG area
    # otherwise; the thermal mass (gbo below) uses A_g too, except for *_cbag, which keeps the
    # BAG area so C agrees with a published (BAG) floor-area class instead of being a second,
    # independent one (kladbloknotitie 4).
    a_bag = gbo
    area_source = np.where(np.isfinite(a_bag), "BAG", None).astype(object)

    def _a_g():
        ag = pd.to_numeric(df["label_oppervlakte__m2"], errors="coerce").to_numpy(dtype=float)
        return np.where(np.isfinite(ag), ag, a_bag), np.isfinite(ag)

    if method in ("ep", "ep_cbag"):
        # the envelope from the label: loss area = compactness (A_ls / A_g) x A_g, divided like
        # the reference dwelling; nothing from 3D-BAG
        a_g, from_label = _a_g()
        a_ls = pd.to_numeric(df["compactheid__m2_m_2"], errors="coerce").to_numpy(dtype=float) * a_g
        windows, walls, door = a_ls * shares["raam"], a_ls * shares["gevel"], a_ls * shares["deur"]
        ground = a_ls * shares["vloer"] * b_floor
        roof = a_ls * shares["dak"]
        if method == "ep":
            gbo = a_g            # ep_cbag keeps the BAG usable area for the thermal mass
            area_source = np.where(from_label, "label (A_g, NTA 8800)", area_source)
    else:
        windows = num["opp_buitenmuur"] * frac
        walls = num["opp_buitenmuur"] - windows - door
        ground = num["opp_grond"] * b_floor
        roof = num["opp_dak_plat"] + num["opp_dak_schuin"]
        if method == "ep_3dbag":
            # the shape from 3D-BAG, the size of the thermal envelope from the label
            a_g, from_label = _a_g()
            a_ls = pd.to_numeric(df["compactheid__m2_m_2"], errors="coerce").to_numpy(dtype=float) * a_g
            with np.errstate(divide="ignore", invalid="ignore"):
                scale = a_ls / (num["opp_buitenmuur"] + num["opp_grond"] + roof)
            windows, walls, ground, roof = (x * scale for x in (windows, walls, ground, roof))
            door = door * scale
            gbo = a_g
            area_source = np.where(from_label, "label (A_g, NTA 8800)", area_source)
    H = walls * u["gevel"] + windows * u["raam"] + door * u["deur"] + ground * u["vloer"] \
        + roof * u["dak"]
    C = _lookup(year, _MASS, 2) * 1000 / 3600 * gbo
    opaque = ALPHA_SOL__0 * R_SE__m2_K_W_1
    if method in ("nta8800", "mwa"):
        r_win = r_wall = np.full(n, VERTICAL_IRRADIANCE_RATIO__W0)
        asol_bron = np.full(n, ASOL_BRON_STANDAARD__str, dtype=object)
    else:
        r_win, r_wall, known = _irradiance_ratios(df, dtype.to_numpy(dtype=object), windows,
                                                  walls, door)
        r_win = np.where(known, r_win, VERTICAL_IRRADIANCE_RATIO__W0)
        r_wall = np.where(known, r_wall, VERTICAL_IRRADIANCE_RATIO__W0)
        asol_bron = np.where(known, ASOL_BRON_RICHTING__str, ASOL_BRON_GEMIDDELD__str)
    A_sol = (windows * GLASS_SHARE__0 * g * F_W__0 * F_SH__0 * r_win
             + walls * opaque * u["gevel"] * r_wall
             + door * opaque * u["deur"] * r_win
             + roof * opaque * u["dak"])
    mwa_method = method in ("mwa", "best", "ep", "ep_3dbag", "ep_cbag")
    inf = infiltration(year, gbo, dtype.to_numpy(dtype=object), df["daktype__cat"].to_numpy(),
                       df["bouwlagen__0"].to_numpy(), maatwerk=mwa_method)
    a_inf = inf["Ainf__cm2"].to_numpy()
    inf_missing = ~np.isfinite(a_inf)
    a_inf = np.where(inf_missing,
                     A_INF_NL_AVG__cm2 * (MWA_INFILTRATION__0 if mwa_method else 1.0), a_inf)
    ok = single & np.isfinite(H) & (H > 0) & np.isfinite(C) & (walls > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        tau = C / H
    col = namen.uitvoer_kolom
    out = pd.DataFrame({
        col("H"): np.where(ok, H, np.nan), col("C"): np.where(ok, C, np.nan),
        col("tau"): np.where(ok, tau, np.nan), col("Asol"): np.where(ok, A_sol, np.nan),
        col("Ainf"): np.where(ok, a_inf, np.nan),
    }, index=idx).round({col("H"): 2, col("C"): 1, col("tau"): 3, col("Asol"): 3,
                         col("Ainf"): 1})
    if detail:
        extra = pd.DataFrame({
            "A_gevel__m2": walls, "A_raam__m2": windows, "A_deur__m2": door,
            "A_grond__m2": ground, "A_dak__m2": roof,
            "U_gevel__W_m_2_K_1": u["gevel"], "U_raam__W_m_2_K_1": u["raam"],
            "U_deur__W_m_2_K_1": u["deur"], "U_grond__W_m_2_K_1": u["vloer"],
            "U_dak__W_m_2_K_1": u["dak"], "g_raam__0": g,
            "woningtype_gebruikt__cat": dtype.to_numpy(dtype=object),
            "referentiewoning__str": ref_id,
            "isolatieniveau__0": level, "bron__cat": source,
            "oppervlakte_gebruikt__m2": gbo, "oppervlakte_bron__str": area_source,
            "qv10__dm3_s_1_m_2": inf["qv10__dm3_s_1_m_2"].to_numpy(),
            "ELA__cm2": inf["ELA__cm2"].to_numpy(),
            "bouwlagenklasse__cat": inf["bouwlagenklasse__cat"].to_numpy(),
            "Ainf_bron__str": np.where(inf_missing, "landelijk gemiddelde (gegevens ontbreken)",
                                  "woning (NTA 8800 qv10, LBL)"),
            "asol_bron__str": asol_bron,
        }, index=idx)
        num_cols = [c for c in extra.columns
                    if c.startswith(("A_", "U_", "g_", "iso", "oppervlakte_gebruikt", "qv10",
                                     "ELA", "bouwlagenklasse"))]
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


# Mean indoor temperature per energy label class that explains the gap between calculated and
# actual gas use (Majcen, 2016, PhD thesis TU Delft, summary): 18 + 2.7 = 20.7 °C for label A and
# 18 - 5.6 = 12.4 °C for label G, against 18 °C assumed by the calculation method; intermediate
# classes interpolated linearly here. The gap also has a physical part (too pessimistic thermal
# resistances), which Maatwerkadvies corrects separately: on top of the MWA corrections these
# temperatures are an upper bound for the behavioural effect. Caution: they are the mean
# temperatures needed to explain gas use, not the difference between the thermostat room and the
# rest of the dwelling, which is what sets the H a learning model sees; for label A the mean
# (20.7 °C) is above the usual thermostat setting. Tested against learned signatures, they did
# not bring an address-based signature closer.
T_INDOOR_BY_LABEL_MAJCEN__degC = {"A": 20.7, "G": 12.4}
_LABEL_ORDER = "ABCDEFG"


def mean_indoor_temperature(labels, assumption: str = "nta") -> np.ndarray:
    """Assumed dwelling-mean indoor temperature in the heating season [°C], per label class.

    ``"nta"``: :data:`T_INDOOR_MEAN__degC` for every dwelling. ``"majcen"``: by label class
    between A (20.7) and G (12.4), A+ and better as A, no label as ``"nta"``. ``"midden"``: halfway
    between the two. This is an assumption about *use*, part of an address-based algorithm, not
    something measured in the dwelling.
    """
    labels = pd.Series(labels, dtype=object)
    nta = np.full(len(labels), T_INDOOR_MEAN__degC)
    if assumption == "nta":
        return nta
    lo, hi = T_INDOOR_BY_LABEL_MAJCEN__degC["G"], T_INDOOR_BY_LABEL_MAJCEN__degC["A"]
    klasse = labels.astype("string").str.upper().str.strip().str[:1]
    pos = klasse.map({k: i for i, k in enumerate(_LABEL_ORDER)}).astype(float).to_numpy()
    majcen = np.where(np.isnan(pos), nta, hi - (hi - lo) * pos / (len(_LABEL_ORDER) - 1))
    if assumption == "majcen":
        return majcen
    if assumption == "midden":
        return (majcen + nta) / 2
    raise ValueError(f"assumption must be 'nta', 'majcen' or 'midden', got {assumption!r}")


def as_learned(sig: pd.DataFrame, usable_area, *, ventilation: float | None = MWA_VENTILATION_C__0,
               room_temperature: bool = True, mean_indoor=None, construction_year=None,
               tau: str = "berekend") -> pd.DataFrame:
    """A *computed* (address-based) signature, expressed as the quantity a learning model
    estimates. Learned values are never touched: this only decides what the address-based side
    estimates, so the two can be compared.

    A model that learns H from gas use and one measured indoor temperature, without a measured
    ventilation flow, finds a single H that holds *all* losses proportional to indoor minus
    outdoor temperature, relative to *that* room. The computed H is transmission through the
    envelope, relative to the dwelling's mean temperature. To estimate the same quantity:

    - ``ventilation``: add the ventilation loss (:func:`ventilation_H` with this factor;
      ``None`` leaves it out);
    - ``room_temperature``: scale by (mean indoor − outdoor) / (thermostat room − outdoor),
      since a warmer measuring room makes the same loss look like a smaller H. ``mean_indoor``
      [°C, scalar or per dwelling] is the assumed dwelling mean (default
      :data:`T_INDOOR_MEAN__degC`); see :func:`mean_indoor_temperature` for assumptions per
      label class. Which assumption is used is part of the address-based algorithm.

    A_sol is defined alike on both sides (gains = global horizontal irradiance × A_sol) and C is
    left as is; τ follows from C / H. Infiltration stays out on both sides (a learning model
    typically fixes it at a national average).

    ``tau="gemeten"`` (needs ``construction_year``): an algorithm that takes τ from the time
    constant measured from smart-thermostat data for the construction period
    (:data:`TAU_MEASURED__h`) and C = τ · H, instead of from the tabulated thermal mass.
    """
    out = sig.copy()
    col = namen.uitvoer_kolom
    h = out[col("H")].astype(float)
    if ventilation is not None:
        h = h + ventilation_H(usable_area, ventilation)
    if room_temperature:
        t_mean = T_INDOOR_MEAN__degC if mean_indoor is None else np.asarray(mean_indoor, float)
        h = h * ((t_mean - T_OUTDOOR_MEAN__degC)
                 / (T_THERMOSTAT_ROOM__degC - T_OUTDOOR_MEAN__degC))
    out[col("H")] = h
    if tau == "gemeten":
        if construction_year is None:
            raise ValueError("tau='gemeten' needs construction_year")
        t = _lookup(np.asarray(construction_year, dtype=float), TAU_MEASURED__h, 2)
        out[col("tau")] = t
        out[col("C")] = t * h
    elif tau == "berekend":
        out[col("tau")] = out[col("C")] / h
    else:
        raise ValueError(f"tau must be 'berekend' or 'gemeten', got {tau!r}")
    return out


# signature columns in the population: all outputs of nta8800 as sig_*, and per other method
# sig_<method>_* (C only where it differs from nta8800: the label-based methods)
POPULATION_METHODS = {"mwa": ("H", "tau", "Asol", "Ainf"), "best": ("H", "tau", "Asol", "Ainf"),
                      "ep": ("H", "C", "tau", "Asol", "Ainf"),
                      "passend": ("H", "C", "tau", "Asol", "Ainf"),
                      # H and A_sol as passend; C (and so τ) differ, and A_inf: its ELA uses the
                      # BAG area where passend uses the label's A_g
                      "passend_cbag": ("C", "tau", "Ainf")}


def population_columns(inputs: pd.DataFrame) -> pd.DataFrame:
    """Every ``sig_*`` column the population carries, for these register rows."""
    out = baseline(inputs)
    for method, outputs in POPULATION_METHODS.items():
        sig = compute(inputs, method)
        for o in outputs:
            out[namen.sig_kolom(o, method)] = sig[namen.uitvoer_kolom(o)].to_numpy()
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
    column (``nta8800_H__W_K_1``, ``best_tau__h``, ...), keyed by BAG id and address; streamed to
    Parquet so memory stays small. With ``context`` the table also carries region and
    dwelling attributes (:data:`CONTEXT`), so a rainbow table for a subset can be made from it
    (``anonymate signatuur regenboog --bron ... --scope ...``)."""
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq

    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'")
    src = Path(population_path).as_posix()
    rel = namen.parquet_relatie(src)
    have = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {rel}").fetchall()}
    wanted = KEYS + INPUT + (CONTEXT if context else [])
    cols = [c for c in dict.fromkeys(wanted) if c in have]
    reader = con.execute(f"SELECT {', '.join(cols)} FROM {rel} "
                         "WHERE eengezins__bool").fetch_record_batch(batch_rows)
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
    rel = namen.parquet_relatie(src)
    have = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {rel}").fetchall()}
    cols = [c for c in KEYS + INPUT if c in have]
    sql = (f"SELECT {', '.join(cols)} FROM {rel} WHERE postcode6__str = ? "
           "AND CAST(huisnummer__str AS VARCHAR) = ?")
    params: list = [postcode.replace(" ", "").upper(), str(int(huisnummer))]
    if huisletter:
        sql += " AND upper(coalesce(CAST(huisletter__str AS VARCHAR), '')) = ?"
        params.append(huisletter.upper())
    if toevoeging:
        sql += " AND upper(coalesce(CAST(toevoeging__str AS VARCHAR), '')) = ?"
        params.append(toevoeging.upper())
    df = con.execute(sql, params).fetchdf()
    res = df[[c for c in KEYS if c in df]].copy()
    for m in methods:
        res = res.join(compute(df, m, detail=detail).add_prefix(f"{m}_"))
    return res
