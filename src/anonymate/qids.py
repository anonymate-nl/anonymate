"""Catalogue of quasi-identifiers (QIDs) and who can know them.

A quasi-identifier is an attribute that does not name a dwelling by itself but, combined with
others and with background knowledge, can single it out. What matters is not only *what* the
attribute is, but *who* can know it for every dwelling in the country:

``REGISTER``
    Anyone: it is in a public register that covers the whole population (BAG, EP-online, a public
    map). For these we can count the real population exactly.
``OBSERVABLE``
    Anyone who walks past or looks at aerial imagery: solar panels, glazing, dwelling type.
    No complete register exists, so the population frequency has to be estimated.
``INSIDER``
    Someone with privileged knowledge of a subset: an installer, a subsidy provider, an energy
    supplier, a neighbour. Installation date, heat pump capacity, annual gas use.

An attacker scenario is simply "attacker knows everything up to level X".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable

from .constraints import Constraint, parse_categorical, parse_numeric


class Knowledge(IntEnum):
    REGISTER = 1
    OBSERVABLE = 2
    INSIDER = 3

    @property
    def label_nl(self) -> str:
        return {1: "openbaar register", 2: "zichtbaar van buitenaf", 3: "insiderkennis"}[self.value]

    @property
    def label_en(self) -> str:
        return {1: "public register", 2: "observable", 3: "insider knowledge"}[self.value]


class Kind:
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"


ENERGY_LABELS = ("A+++++", "A++++", "A+++", "A++", "A+", "A", "B", "C", "D", "E", "F", "G")


def normalise_label(s: str) -> str | None:
    t = re.sub(r"\s+", "", str(s)).upper()
    t = t.removeprefix("LABEL")
    return t if t in ENERGY_LABELS else None


DWELLING_TYPES = ("vrijstaand", "twee_onder_een_kap", "hoekwoning", "tussenwoning", "appartement")

_DWELLING_PATTERNS: list[tuple[str, str]] = [
    # order matters: "semi-detached" before "detached", "galerijflat" before "rij",
    # "rijwoning hoek" before "rij"
    (r"2.?onder.?1|twee.?onder.?een|semi.?detached|2/1", "twee_onder_een_kap"),
    (r"vrijstaand|detached|free.?standing", "vrijstaand"),
    (r"appartement|apartment|flat|galerij|portiek|maisonnette|etage|bovenwoning|benedenwoning|"
     r"meergezins|multi.?family", "appartement"),
    (r"hoek|end.?of.?terrace|corner", "hoekwoning"),
    (r"tussen|rij|mid.?terrace|terraced|row", "tussenwoning"),
]


def normalise_dwelling_type(s: str) -> str | None:
    t = str(s).strip().lower()
    if t in DWELLING_TYPES:
        return t
    for pat, canon in _DWELLING_PATTERNS:
        if re.search(pat, t):
            return canon
    return None


def normalise_postcode(s: str) -> str | None:
    t = re.sub(r"\s+", "", str(s)).upper()
    return t if re.fullmatch(r"\d{4}([A-Z]{2})?", t) else None


def normalise_postcode4(s: str) -> str | None:
    p = normalise_postcode(s)
    return p[:4] if p else None


def normalise_roof(s: str) -> str | None:
    t = str(s).strip().lower()
    if re.search(r"meerdere|multiple", t):
        return "plat_meerdere"
    if re.search(r"schuin|slanted|pitched|hellend|zadel|schild|mansard", t):
        return "schuin"
    if re.search(r"plat|flat|horizontal", t):
        return "plat"
    return None


def normalise_bool(s: str) -> str | None:
    t = str(s).strip().lower()
    if t in ("true", "1", "ja", "yes", "j", "y", "waar"):
        return "true"
    if t in ("false", "0", "nee", "no", "n", "onwaar"):
        return "false"
    return None


def normalise_text(s: str) -> str | None:
    t = str(s).strip()
    return t or None


@dataclass(frozen=True)
class QidSpec:
    """How to read one QID and where the attacker can look it up.

    ``population_column`` is the column in the reference population holding this attribute; it is
    ``None`` for attributes no complete register knows (OBSERVABLE/INSIDER), whose population
    frequency is then estimated (see :mod:`anonymate.risk`).
    """

    key: str
    kind: str
    knowledge: Knowledge
    population_column: str | None
    label_nl: str
    label_en: str
    source: str = ""
    integer: bool = True
    normalise: Callable[[str], str | None] | None = None
    domain: tuple = field(default=())  # numeric: (lo, hi); categorical: all values

    def parse(self, value: object) -> Constraint:
        if self.kind == Kind.NUMERIC:
            return parse_numeric(value, integer=self.integer)
        return parse_categorical(value, normalise=self.normalise)


def _spec(*args, **kw) -> QidSpec:
    return QidSpec(*args, **kw)


CATALOGUE: dict[str, QidSpec] = {
    s.key: s
    for s in [
        # --- public registers -----------------------------------------------------------------
        _spec("bouwjaar", Kind.NUMERIC, Knowledge.REGISTER, "bouwjaar",
              "bouwjaar", "construction year", "BAG (oorspronkelijk bouwjaar pand)",
              domain=(1000, 2100)),
        _spec("oppervlakte", Kind.NUMERIC, Knowledge.REGISTER, "oppervlakte",
              "gebruiksoppervlakte [m²]", "usable floor area [m²]", "BAG (verblijfsobject)",
              domain=(1, 2000)),
        _spec("energielabel", Kind.CATEGORICAL, Knowledge.REGISTER, "energielabel",
              "energielabel", "energy label", "EP-online",
              normalise=normalise_label, domain=ENERGY_LABELS),
        _spec("woningtype", Kind.CATEGORICAL, Knowledge.REGISTER, "woningtype",
              "woningtype", "dwelling type", "EP-online / afgeleid uit BAG-geometrie",
              normalise=normalise_dwelling_type, domain=DWELLING_TYPES),
        _spec("postcode6", Kind.CATEGORICAL, Knowledge.REGISTER, "postcode6",
              "postcode (6 posities)", "postcode (6 characters)", "BAG",
              normalise=normalise_postcode),
        _spec("postcode4", Kind.CATEGORICAL, Knowledge.REGISTER, "postcode4",
              "postcode (4 cijfers)", "postcode (4 digits)", "BAG",
              normalise=normalise_postcode4),
        _spec("gemeente", Kind.CATEGORICAL, Knowledge.REGISTER, "gemeente",
              "gemeente", "municipality", "BAG / CBS", normalise=normalise_text),
        _spec("provincie", Kind.CATEGORICAL, Knowledge.REGISTER, "provincie",
              "provincie", "province", "CBS", normalise=normalise_text),
        _spec("h3_cel", Kind.CATEGORICAL, Knowledge.REGISTER, "h3_cel",
              "H3-cel", "H3 cell", "afgeleid uit BAG-coördinaten",
              normalise=lambda s: str(s).strip().lower() or None),
        _spec("knmi_station", Kind.CATEGORICAL, Knowledge.REGISTER, "knmi_station",
              "dichtstbijzijnde KNMI-station", "nearest KNMI station",
              "KNMI-stationslijst + BAG-coördinaten", normalise=normalise_text),
        _spec("daktype", Kind.CATEGORICAL, Knowledge.REGISTER, "daktype",
              "daktype", "roof type", "3D-BAG", normalise=normalise_roof,
              domain=("schuin", "plat", "plat_meerdere")),
        _spec("bouwlagen", Kind.NUMERIC, Knowledge.REGISTER, "bouwlagen",
              "aantal bouwlagen", "number of floors", "3D-BAG (geschat)", domain=(1, 5)),
        _spec("hoogte", Kind.NUMERIC, Knowledge.REGISTER, "hoogte",
              "hoogte gebouw [m]", "building height [m]", "3D-BAG", integer=False,
              domain=(0, 60)),
        _spec("aaneengebouwd", Kind.CATEGORICAL, Knowledge.REGISTER, "aaneengebouwd",
              "aaneengebouwd", "attached", "3D-BAG (scheidingsmuur)",
              normalise=normalise_bool, domain=("true", "false")),
        # baseline heat performance signature, computable for every single-family home from
        # BAG + 3D-BAG + NTA 8800 (anonymate.signature): published signatures are QIDs
        _spec("warmteverlies", Kind.NUMERIC, Knowledge.REGISTER, "sig_H",
              "warmteoverdrachtscoëfficiënt H [W/K]", "heat transfer capacity H [W/K]",
              "berekend uit BAG + 3D-BAG (warmteprestatiesignatuur)", integer=False,
              domain=(0, 1500)),
        _spec("thermische_massa", Kind.NUMERIC, Knowledge.REGISTER, "sig_C",
              "thermische massa C [Wh/K]", "thermal mass C [Wh/K]",
              "berekend uit BAG (warmteprestatiesignatuur)", integer=False,
              domain=(0, 150000)),
        _spec("tijdconstante", Kind.NUMERIC, Knowledge.REGISTER, "sig_tau",
              "thermische tijdconstante τ [h]", "thermal inertia τ [h]",
              "berekend uit BAG + 3D-BAG (warmteprestatiesignatuur)", integer=False,
              domain=(0, 1000)),
        _spec("zonnetoetreding", Kind.NUMERIC, Knowledge.REGISTER, "sig_Asol",
              "zonnetoetreding A_sol [m²]", "solar aperture A_sol [m²]",
              "berekend uit BAG + 3D-BAG (warmteprestatiesignatuur)", integer=False,
              domain=(0, 300)),
        _spec("warmteverlies_mwa", Kind.NUMERIC, Knowledge.REGISTER, "sig_mwa_H",
              "warmteoverdrachtscoëfficiënt H, MWA [W/K]", "heat transfer capacity H, MWA [W/K]",
              "berekend uit BAG + 3D-BAG met Maatwerkadvies-parameters", integer=False,
              domain=(0, 1500)),
        _spec("tijdconstante_mwa", Kind.NUMERIC, Knowledge.REGISTER, "sig_mwa_tau",
              "thermische tijdconstante τ, MWA [h]", "thermal inertia τ, MWA [h]",
              "berekend uit BAG + 3D-BAG met Maatwerkadvies-parameters", integer=False,
              domain=(0, 1000)),
        _spec("zonnetoetreding_mwa", Kind.NUMERIC, Knowledge.REGISTER, "sig_mwa_Asol",
              "zonnetoetreding A_sol, MWA [m²]", "solar aperture A_sol, MWA [m²]",
              "berekend uit BAG + 3D-BAG met Maatwerkadvies-parameters", integer=False,
              domain=(0, 300)),
        _spec("warmteverlies_best", Kind.NUMERIC, Knowledge.REGISTER, "sig_best_H",
              "warmteoverdrachtscoëfficiënt H, beste schatting [W/K]",
              "heat transfer capacity H, best estimate [W/K]",
              "berekend uit BAG + 3D-BAG + EP-online-label + RVO-voorbeeldwoningen",
              integer=False, domain=(0, 1500)),
        _spec("tijdconstante_best", Kind.NUMERIC, Knowledge.REGISTER, "sig_best_tau",
              "thermische tijdconstante τ, beste schatting [h]",
              "thermal inertia τ, best estimate [h]",
              "berekend uit BAG + 3D-BAG + EP-online-label + RVO-voorbeeldwoningen",
              integer=False, domain=(0, 1000)),
        _spec("zonnetoetreding_best", Kind.NUMERIC, Knowledge.REGISTER, "sig_best_Asol",
              "zonnetoetreding A_sol, beste schatting [m²]", "solar aperture A_sol, best [m²]",
              "berekend uit BAG + 3D-BAG + EP-online-label + RVO-voorbeeldwoningen",
              integer=False, domain=(0, 300)),
        _spec("uhi", Kind.NUMERIC, Knowledge.REGISTER, "uhi",
              "stedelijk hitte-eiland [°C]", "urban heat island [°C]",
              "RIVM hitte-eilandkaart", integer=False, domain=(0, 4)),
        # --- observable from outside ----------------------------------------------------------
        _spec("zonnepanelen", Kind.CATEGORICAL, Knowledge.OBSERVABLE, None,
              "zonnepanelen", "solar panels", "zichtbaar / luchtfoto", normalise=normalise_text),
        _spec("glastype", Kind.CATEGORICAL, Knowledge.OBSERVABLE, None,
              "type glas", "glazing type", "zichtbaar", normalise=normalise_text),
        _spec("buitenunit", Kind.CATEGORICAL, Knowledge.OBSERVABLE, None,
              "buitenunit warmtepomp", "heat pump outdoor unit", "zichtbaar",
              normalise=normalise_text),
        # --- insider knowledge ----------------------------------------------------------------
        _spec("installatiedatum", Kind.NUMERIC, Knowledge.INSIDER, None,
              "installatiedatum (jaar)", "installation date (year)",
              "installateur / subsidieverstrekker"),
        _spec("toestel", Kind.CATEGORICAL, Knowledge.INSIDER, None,
              "merk/type toestel", "appliance make/model",
              "fabrikant / installateur / servicemonteur", normalise=normalise_text),
        _spec("vermogen", Kind.NUMERIC, Knowledge.INSIDER, None,
              "vermogen installatie [kW]", "installed capacity [kW]",
              "installateur / subsidieverstrekker", integer=False),
        _spec("isolatie", Kind.CATEGORICAL, Knowledge.INSIDER, None,
              "isolatie (dak/muur/vloer)", "insulation (roof/wall/floor)",
              "aannemer / buren / eigen opgave", normalise=normalise_text),
        _spec("jaarverbruik", Kind.NUMERIC, Knowledge.INSIDER, None,
              "jaarverbruik gas/stroom", "annual gas/electricity use",
              "energieleverancier / netbeheerder", integer=False),
    ]
}

# the label-based signatures (anonymate.signature: ep, and passend = ep where the label allows,
# best otherwise); their C differs from nta8800's, so it has its own column too
for _m, _what in (("ep", "EP-online-label (schil uit het label)"),
                  ("passend", "per woning ep of best, vaste regel")):
    for _key, _out, _nl, _en, _dom in (
            ("warmteverlies", "H", "warmteoverdrachtscoëfficiënt H", "heat transfer capacity H",
             (0, 1500)),
            ("thermische_massa", "C", "thermische massa C", "thermal mass C", (0, 150000)),
            ("tijdconstante", "tau", "thermische tijdconstante τ", "thermal inertia τ",
             (0, 1000)),
            ("zonnetoetreding", "Asol", "zonnetoetreding A_sol", "solar aperture A_sol",
             (0, 300))):
        _s = _spec(f"{_key}_{_m}", Kind.NUMERIC, Knowledge.REGISTER, f"sig_{_m}_{_out}",
                   f"{_nl}, {_m}", f"{_en}, {_m}",
                   f"berekend uit BAG + EP-online + RVO-voorbeeldwoningen ({_what})",
                   integer=False, domain=_dom)
        CATALOGUE[_s.key] = _s


def custom_qid(key: str, kind: str, knowledge: Knowledge, *, integer: bool = True) -> QidSpec:
    """A QID the catalogue does not know; its population frequency is always estimated."""
    return QidSpec(key, kind, knowledge, None, key, key, "door gebruiker opgegeven",
                   integer=integer, normalise=normalise_text if kind == Kind.CATEGORICAL else None)
