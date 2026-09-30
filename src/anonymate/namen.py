"""Column names of the population and the data package, after the physiquant__unit convention.

The convention (https://github.com/energietransitie/physiquant__unit): the unit as a postfix
after a double underscore (``oppervlakte__m2``), compound units joined by single underscores,
negative exponents with an underscore before them (``sig_H__W_K_1``), ``__0`` for a fraction or
a count, ``__cat`` for a categorical from a fixed set, ``__str`` for free text and identifiers,
``__bool`` for a boolean. It applies to names we define: the population, the data package and the
signature columns. Source data keeps its own field names up to where we translate it (the
ingest and build steps); the translation is written down per column in ``docs/variabelen.md``,
and :data:`OUD_NAAR_NIEUW` here is the same table in code. A user's own dataset is never
renamed.

Before this convention the columns had plain names (``bouwjaar``, ``sig_H``). The data package
published up to and including 2026-09-30 and a population built before then carry those; they
are mapped to the new names on reading (:func:`naar_nieuw`, :func:`parquet_relatie`).
"""
from __future__ import annotations

from pathlib import Path

NAMEN_VERSIE = "physiquant__unit"

# signature outputs (short keys, used as identifiers in publicatie.Plan and in the interface) and
# the unit of the column they give
UITVOER_EENHEID = {"H": "W_K_1", "C": "Wh_K_1", "tau": "h", "Asol": "m2", "Ainf": "cm2"}
METHODEN = ("nta8800", "mwa", "best", "ep", "ep_3dbag", "passend", "ep_cbag", "passend_cbag")
H3_NIVEAUS = (4, 5, 6, 7, 8)


def uitvoer_kolom(uitvoer: str) -> str:
    """``H`` -> ``H__W_K_1``: the column of a signature output."""
    return f"{uitvoer}__{UITVOER_EENHEID[uitvoer]}"


def sig_kolom(uitvoer: str, methode: str = "nta8800") -> str:
    """``("H", "mwa")`` -> ``sig_mwa_H__W_K_1``; nta8800 has no method in its name."""
    stam = "sig" if methode == "nta8800" else f"sig_{methode}"
    return f"{stam}_{uitvoer_kolom(uitvoer)}"


def h3_kolom(niveau: int) -> str:
    return f"h3_r{niveau}__str"


# old name -> new name, for every column of the population / the data package
OUD_NAAR_NIEUW: dict[str, str] = {
    # identifiers and address (BAG)
    "vbo_id": "vbo_id__str", "nummeraanduiding_id": "nummeraanduiding_id__str",
    "pand_id": "pand_id__str", "postcode6": "postcode6__str", "postcode4": "postcode4__str",
    "huisnummer": "huisnummer__str", "huisletter": "huisletter__str",
    "toevoeging": "toevoeging__str", "woonplaats": "woonplaats__cat",
    "gemeente_code": "gemeente_code__str", "gemeente": "gemeente__cat",
    "provincie": "provincie__cat", "status": "status__cat",
    # dwelling (BAG)
    "bouwjaar": "bouwjaar__yr", "oppervlakte": "oppervlakte__m2",
    "pand_woningen": "pand_woningen__0", "eengezins": "eengezins__bool",
    "rd_x": "rd_x__m", "rd_y": "rd_y__m", "lat": "lat__degN", "lon": "lon__degE",
    # label (EP-online)
    "energielabel": "energielabel__cat", "woningtype": "woningtype__cat",
    "woningtype_bron": "woningtype_bron__cat", "energie_index": "energie_index__0",
    "compactheid": "compactheid__m2_m_2", "label_oppervlakte": "label_oppervlakte__m2",
    "warmtebehoefte": "warmtebehoefte__kWh_m_2_a_1", "nta8800": "nta8800__bool",
    # building shape (3D-BAG)
    "daktype": "daktype__cat", "bouwlagen": "bouwlagen__0", "hoogte": "hoogte__m",
    "aaneengebouwd": "aaneengebouwd__bool", "pand_volume": "pand_volume__m3",
    "opp_grond": "opp_grond__m2", "opp_dak_plat": "opp_dak_plat__m2",
    "opp_dak_schuin": "opp_dak_schuin__m2", "opp_buitenmuur": "opp_buitenmuur__m2",
    "opp_scheidingsmuur": "opp_scheidingsmuur__m2",
    # derived / other sources
    "uhi": "uhi__degC", "knmi_station": "knmi_station__cat",
    **{f"h3_r{n}": h3_kolom(n) for n in H3_NIVEAUS},
    # signatures
    **{f"sig_{o}": sig_kolom(o) for o in UITVOER_EENHEID},
    **{f"sig_{m}_{o}": sig_kolom(o, m) for m in METHODEN if m != "nta8800"
       for o in UITVOER_EENHEID},
}
NIEUW_NAAR_OUD = {v: k for k, v in OUD_NAAR_NIEUW.items()}


def is_oud(kolommen) -> bool:
    """True when these columns are in the pre-convention format (an old name, no new one)."""
    kol = set(kolommen)
    return any(o in kol and OUD_NAAR_NIEUW[o] not in kol for o in OUD_NAAR_NIEUW)


def naar_nieuw(df):
    """``df`` with old column names renamed to the new ones; new names and any other column are
    left alone."""
    return df.rename(columns={c: OUD_NAAR_NIEUW[c] for c in df.columns
                              if c in OUD_NAAR_NIEUW and OUD_NAAR_NIEUW[c] not in df.columns})


def zonder_eenheid(kolom: str) -> str:
    """``bouwjaar__yr`` -> ``bouwjaar``: the plain name, as a user's own dataset would have it."""
    return kolom.split("__", 1)[0]


def parquet_relatie(path: str | Path, kolommen=None) -> str:
    """SQL relation over a population Parquet that exposes the new names also when the file still
    has old ones (a population built before the convention): ``(SELECT ..., "old" AS "new" ...)``.
    Without old names this is a plain ``read_parquet``. ``kolommen``: the file's column names,
    if already known."""
    import duckdb
    q = str(path).replace("'", "''")
    rel = f"read_parquet('{q}')"
    if kolommen is None:
        kolommen = [r[0] for r in duckdb.connect().execute(
            f"DESCRIBE SELECT * FROM {rel}").fetchall()]
    kolommen = list(kolommen)
    if not is_oud(kolommen):
        return rel
    kol = set(kolommen)
    sel = ", ".join(
        f'"{c}" AS "{OUD_NAAR_NIEUW[c]}"' if c in OUD_NAAR_NIEUW and OUD_NAAR_NIEUW[c] not in kol
        else f'"{c}"' for c in kolommen)
    return f"(SELECT {sel} FROM {rel})"
