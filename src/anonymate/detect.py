"""Suggest which columns of a dataset are identifiers or quasi-identifiers.

Detection is a *proposal*: the user confirms or overrides every column. It looks at column names
(Dutch and English, snake_case, physiquant-style ``name__unit``) and at the values themselves, and
classifies each column as one of:

``direct``
    Identifies a dwelling or person on its own (address, house number, exact coordinates, BAG id,
    name, e-mail). Must never be published; remove it before anything else.
``qid``
    Quasi-identifier with a known catalogue entry (see :mod:`anonymate.qids`).
``implicit_location``
    Reveals location without saying so: a weather station, H3 cell, grid cell, or the (lat, lon)
    of a weather interpolation target. Converted to a location QID where possible.
``derived``
    Functionally determined by another (quasi-)identifier column in this dataset, e.g. the rated
    capacity of an appliance model. It leaks exactly what its source leaks.
``measurement``
    Probably time-varying measurement data or an unremarkable attribute; not a QID by default.

Nothing here touches the network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from .qids import CATALOGUE, ENERGY_LABELS, Knowledge, normalise_dwelling_type


class Role:
    DIRECT = "direct"
    QID = "qid"
    IMPLICIT_LOCATION = "implicit_location"
    DERIVED = "derived"
    MEASUREMENT = "measurement"


@dataclass(frozen=True)
class Detection:
    column: str
    role: str
    qid: str | None  # catalogue key, if any
    confidence: float  # 0..1
    reason: str

    @property
    def knowledge(self) -> Knowledge | None:
        return CATALOGUE[self.qid].knowledge if self.qid else None


def _name(column: str) -> str:
    """Lower-case, strip physiquant unit suffix (``__degC``), separators to underscores."""
    base = str(column).split("__", 1)[0]
    base = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", base)  # camelCase
    return re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")


# (pattern on normalised name, role, catalogue key, reason)
_NAME_RULES: list[tuple[str, str, str | None, str]] = [
    # direct identifiers first
    (r"(^|_)(straat|street|straatnaam|openbare_ruimte|adres|address)(_|$)", Role.DIRECT, None,
     "adresgegeven"),
    (r"(^|_)(huisnummer|huisnr|home_nr|house_number|housenumber|huisletter|toevoeging|"
     r"home_nr_add_on|add_on)(_|$)", Role.DIRECT, None, "huisnummer(toevoeging)"),
    (r"(^|_)(naam|name|voornaam|achternaam|surname|email|e_mail|telefoon|phone|iban|bsn)(_|$)",
     Role.DIRECT, None, "persoonsgegeven"),
    (r"(^|_)(vbo|verblijfsobject|nummeraanduiding|pand|bag)_?id(_|$)|(^|_)bag(_|$)",
     Role.DIRECT, None, "BAG-identificatie"),
    (r"(^|_)(rd_x|rd_y|x_rd|y_rd)(_|$)", Role.DIRECT, None, "RD-coördinaat"),
    (r"(^|_)(ean|ean_code|meter_id|meternummer|serial|serienummer)(_|$)", Role.DIRECT, None,
     "meter- of apparaatnummer"),
    (r"meterstand|meter_reading|cumulati|(^|_)(e|v|g)(_[a-z]+)?_(consumed|delivered|geleverd|"
     r"verbruikt)(_|$)|(^|_)(stand|teller)_", Role.DIRECT, None,
     "absolute meterstand: bekend bij leverancier/netbeheerder, koppelt aan het adres"),
    # implicit location
    (r"(^|_)(knmi|weerstation|weather_station|station)(_|$)", Role.IMPLICIT_LOCATION,
     "knmi_station", "weerstation onthult regio"),
    (r"(^|_)h3(_|$)|h3_?(cel|cell|index|id)", Role.IMPLICIT_LOCATION, "h3_cel",
     "H3-cel onthult locatie"),
    (r"(^|_)(weather|weer|interpolation|interpolatie)_(lat|lon|latitude|longitude)",
     Role.IMPLICIT_LOCATION, "h3_cel", "doel van weerinterpolatie onthult locatie"),
    # quasi-identifiers
    (r"bouwjaar|construction_year|build(ing)?_year|year_built|bouw_jaar", Role.QID, "bouwjaar",
     "bouwjaar"),
    (r"(gebruiks|vloer_?)?oppervlak|floor_?area|surface|usable_area|(^|_)ag(_|$)|(^|_)area(_|$)",
     Role.QID, "oppervlakte", "oppervlakte"),
    (r"energie_?label|energy_?label|(^|_)label(_|$)|labelklasse", Role.QID, "energielabel",
     "energielabel"),
    (r"woning_?type|house_?type|dwelling_?type|building_?type|gebouw_?type|bouwvorm", Role.QID,
     "woningtype", "woningtype"),
    (r"(^|_)(pc6|postcode6|postcode|zip|zipcode|postal_?code)(_|$)", Role.QID, "postcode6",
     "postcode"),
    (r"(^|_)(pc4|postcode4|postcode_4)(_|$)", Role.QID, "postcode4", "postcode (4)"),
    (r"(^|_)(gemeente|municipality|woonplaats|city|plaats)(_|$)", Role.QID, "gemeente",
     "gemeente/woonplaats"),
    (r"(^|_)(provincie|province)(_|$)", Role.QID, "provincie", "provincie"),
    (r"(^|_)(uhi|hitte_?eiland|urban_heat)", Role.QID, "uhi", "hitte-eiland"),
    (r"heat_tr|h_bldng|warmteverlies|warmteoverdracht|(^|_)h_?tr(_|$)|heat_loss_coef",
     Role.QID, "warmteverlies", "warmteoverdrachtscoëfficiënt (signatuur)"),
    (r"th_mass|thermal_mass|thermische_massa|c_bldng", Role.QID, "thermische_massa",
     "thermische massa (signatuur)"),
    (r"inertia|tijdconstante|(^|_)tau(_|$)|time_constant", Role.QID, "tijdconstante",
     "thermische tijdconstante (signatuur)"),
    (r"aperture_sol|a_?sol(_|$)|solar_aperture|zonnetoetreding", Role.QID, "zonnetoetreding",
     "zonnetoetreding (signatuur)"),
    (r"dak_?type|dak_?vorm|roof_?(type|shape)", Role.QID, "daktype", "daktype"),
    (r"bouwlagen|verdiepingen|(^|_)floors|storeys|stories", Role.QID, "bouwlagen",
     "aantal bouwlagen"),
    (r"(^|_)(hoogte|gebouwhoogte|nokhoogte|goothoogte|building_height|height)(_|$)", Role.QID,
     "hoogte", "hoogte gebouw"),
    (r"aaneen|attached|scheidingsmuur|party_?wall", Role.QID, "aaneengebouwd",
     "aaneengebouwd"),
    (r"zon_?panel|pv_?(panel|install|aanwezig)|solar|(^|_)has_pv", Role.QID, "zonnepanelen",
     "zonnepanelen"),
    (r"glas|glazing|glass", Role.QID, "glastype", "type glas"),
    (r"isolat|insulat", Role.QID, "isolatie", "isolatie"),
    (r"install(atie)?_?(datum|date|jaar|year)|datum_install|commissioning", Role.QID,
     "installatiedatum", "installatiedatum"),
    (r"merk|brand|model|toestel|appliance|boiler_type|ketel_type|heat_?pump_type", Role.QID,
     "toestel", "merk/type toestel"),
    (r"vermogen|capacity|(^|_)isde|(^|_)kw(_|$)|rated_power|nominal_power", Role.QID, "vermogen",
     "(nominaal) vermogen"),
    (r"(jaar|annual|yearly)_?(verbruik|use|consumption)|(gas|elek|elec)\w*_?(voor|before|jaar)",
     Role.QID, "jaarverbruik", "jaarverbruik"),
    # exact coordinates (after the weather rule above)
    (r"(^|_)(lat|lon|lng|latitude|longitude|gps_lat|gps_lon)(_|$)", Role.DIRECT, None,
     "coördinaat"),
]

_PC6 = re.compile(r"^\s*\d{4}\s?[A-Za-z]{2}\s*$")
_PC4 = re.compile(r"^\s*\d{4}\s*$")
_H3 = re.compile(r"^[0-9a-f]{15}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
_BAG_ID = re.compile(r"^\d{16}$")


def _share(values: pd.Series, pred) -> float:
    vals = values.dropna().astype(str)
    vals = vals[vals.str.strip() != ""]
    if vals.empty:
        return 0.0
    sample = vals.head(500)
    return float(sample.map(lambda v: bool(pred(v))).mean())


def _by_values(s: pd.Series) -> tuple[str, str | None, float, str] | None:
    if _share(s, _EMAIL.match) > 0.8:
        return Role.DIRECT, None, 0.9, "waarden zijn e-mailadressen"
    if _share(s, _PC6.match) > 0.8:
        return Role.QID, "postcode6", 0.9, "waarden zijn 6-positie-postcodes"
    if _share(s, _H3.match) > 0.8:
        return Role.IMPLICIT_LOCATION, "h3_cel", 0.9, "waarden zijn H3-cel-ID's"
    if _share(s, _BAG_ID.match) > 0.8:
        return Role.DIRECT, None, 0.8, "waarden lijken op BAG-ID's (16 cijfers)"
    labels = set(ENERGY_LABELS)
    if _share(s, lambda v: re.sub(r"\s", "", v).upper() in labels) > 0.8:
        return Role.QID, "energielabel", 0.8, "waarden zijn energielabels"
    if _share(s, lambda v: normalise_dwelling_type(v) is not None) > 0.8 and \
            s.dropna().astype(str).str.len().median() > 3:
        return Role.QID, "woningtype", 0.6, "waarden lijken op woningtypen"
    num = pd.to_numeric(s, errors="coerce").dropna()
    if len(num) and len(num) >= 0.8 * s.notna().sum():
        if num.between(1500, 2030).all() and (num % 1 == 0).all() and num.nunique() > 3:
            return Role.QID, "bouwjaar", 0.4, "gehele getallen tussen 1500 en 2030 (jaartal?)"
        if _share(s, _PC4.match) > 0.8 and num.between(1000, 9999).all():
            return Role.QID, "postcode4", 0.3, "viercijferige getallen (PC4?)"
    return None


def detect_column(name: str, values: pd.Series) -> Detection:
    n = _name(name)
    for pat, role, key, reason in _NAME_RULES:
        if re.search(pat, n):
            by_val = _by_values(values)
            conf = 0.7
            if by_val and by_val[1] == key:
                conf = 0.95
            return Detection(name, role, key, conf, f"kolomnaam: {reason}")
    by_val = _by_values(values)
    if by_val:
        role, key, conf, reason = by_val
        return Detection(name, role, key, conf, reason)
    return Detection(name, Role.MEASUREMENT, None, 0.5, "geen aanwijzing voor (quasi-)identificatie")


def detect(df: pd.DataFrame) -> list[Detection]:
    """One :class:`Detection` per column, plus functional-dependency checks between columns."""
    found = [detect_column(c, df[c]) for c in df.columns]
    return _mark_derived(df, found)


def _mark_derived(df: pd.DataFrame, found: list[Detection]) -> list[Detection]:
    """Columns fully determined by an identifying column leak the same thing.

    Only checked for columns not already classified, against columns that are, and only when the
    source has repeated values (otherwise every column trivially "depends" on a unique key).
    """
    sources = [d for d in found if d.role in (Role.QID, Role.IMPLICIT_LOCATION, Role.DIRECT)]
    out = []
    for d in found:
        if d.role != Role.MEASUREMENT:
            out.append(d)
            continue
        col = df[d.column]
        if col.nunique(dropna=True) < 2:
            out.append(d)
            continue
        hit = None
        for s in sources:
            src = df[s.column]
            both = pd.DataFrame({"s": src.astype(str), "c": col.astype(str)})[
                src.notna() & col.notna()]
            if len(both) < 5 or both["s"].nunique() >= len(both) or both["s"].nunique() < 2:
                continue
            if (both.groupby("s")["c"].nunique() <= 1).all() and \
                    both["c"].nunique() <= both["s"].nunique():
                hit = s
                break
        if hit:
            out.append(Detection(d.column, Role.DERIVED, hit.qid, 0.7,
                                 f"volledig bepaald door {hit.column!r}: lekt hetzelfde"))
        else:
            out.append(d)
    return out


def h3_center_resolution(lat: pd.Series, lon: pd.Series, *, tol_m: float = 5.0,
                         max_res: int = 10) -> int | None:
    """Coarsest H3 resolution at which every (lat, lon) is the centre of its cell, if any.

    Coordinates that were snapped to H3 cell centres before publication reveal exactly that
    cell; this recovers which resolution was used. (Any point is close to the centre of some
    very fine cell, hence the coarsest match, and nothing finer than ``max_res``: below ~70 m
    these are simply exact coordinates.)
    """
    import h3

    from .rd import haversine_km
    pts = pd.DataFrame({"lat": pd.to_numeric(lat, errors="coerce"),
                        "lon": pd.to_numeric(lon, errors="coerce")}).dropna().drop_duplicates()
    if pts.empty:
        return None
    for res in range(0, max_res + 1):
        ok = True
        for la, lo in pts.itertuples(index=False):
            c = h3.cell_to_latlng(h3.latlng_to_cell(la, lo, res))
            if haversine_km(la, lo, c[0], c[1]) * 1000 > tol_m:
                ok = False
                break
        if ok:
            return res
    return None


def derive_h3_columns(df: pd.DataFrame, found: list[Detection] | None = None
                      ) -> tuple[pd.DataFrame, dict[str, str]]:
    """Turn implicit-location lat/lon pairs into an explicit H3 cell column.

    Returns the dataset with an added ``<stem>_h3_cel`` column and a mapping that marks the
    new column as ``h3_cel`` and the lat/lon columns as ``geen`` (they reveal nothing beyond the
    cell). Pairs that are not cell centres are left alone: those are exact coordinates, which
    detection already flags as direct identifiers.
    """
    found = found if found is not None else detect(df)
    implicit = [d.column for d in found if d.role == Role.IMPLICIT_LOCATION and d.qid == "h3_cel"]
    lats = [c for c in implicit if re.search(r"lat", _name(c))]
    lons = [c for c in implicit if re.search(r"lon|lng", _name(c))]
    mapping: dict[str, str] = {}
    out = df
    for la in lats:
        stem = re.sub(r"lat(itude)?", "", _name(la))
        lo = next((c for c in lons if re.sub(r"lon(gitude)?|lng", "", _name(c)) == stem), None)
        if lo is None:
            continue
        res = h3_center_resolution(df[la], df[lo])
        if res is None:
            continue
        import h3
        col = f"{stem.strip('_')}_h3_cel".lstrip("_")
        out = out.copy() if out is df else out
        lat_v = pd.to_numeric(df[la], errors="coerce")
        lon_v = pd.to_numeric(df[lo], errors="coerce")
        out[col] = [h3.latlng_to_cell(a, b, res) if pd.notna(a) and pd.notna(b) else None
                    for a, b in zip(lat_v, lon_v)]
        mapping.update({col: "h3_cel", la: "geen", lo: "geen"})
    return out, mapping


def to_frame(found: list[Detection]) -> pd.DataFrame:
    return pd.DataFrame([{
        "kolom": d.column, "rol": d.role, "qid": d.qid or "",
        "kennis": d.knowledge.label_nl if d.knowledge else "",
        "zekerheid": d.confidence, "reden": d.reason,
    } for d in found])
