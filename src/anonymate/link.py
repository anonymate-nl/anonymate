"""Link dataset records to their dwelling in the local population, entirely offline.

If the data holder still has addresses (postcode + house number) or BAG ids, linking fetches the
*registered* attributes of each dwelling from the local store. That answers the question
"what could I safely add to my publication?" with register values rather than self-reported ones,
and shows mismatches between the dataset and the registers.

The address columns themselves are direct identifiers: :func:`anonymate.report.publishable`
drops them from anything written for publication.
"""
from __future__ import annotations

import re

import pandas as pd

from .population import Population

REGISTER_COLUMNS = ["vbo_id__str", "bouwjaar__yr", "oppervlakte__m2", "energielabel__cat",
                    "woningtype__cat", "postcode6__str", "postcode4__str", "gemeente__cat",
                    "provincie__cat", "eengezins__bool", "pand_woningen__0", "knmi_station__cat",
                    "uhi__degC"]


def _missing(v) -> bool:
    """None, NaN and pandas' NA (from nullable string columns) all mean: no value."""
    return v is None or (not isinstance(v, (list, tuple)) and bool(pd.isna(v)))


def _norm_pc(v) -> str | None:
    if _missing(v):
        return None
    t = re.sub(r"\s+", "", str(v)).upper()
    return t or None


def _norm_str(v) -> str:
    if _missing(v):
        return ""
    return str(v).strip().upper()


def link(df: pd.DataFrame, population: Population, *, vbo_id: str | None = None,
         postcode: str | None = None, huisnummer: str | None = None,
         huisletter: str | None = None, toevoeging: str | None = None,
         prefix: str = "register_") -> pd.DataFrame:
    """Return ``df`` with register attributes added as ``register_<population column>`` columns
    (``register_bouwjaar__yr``; see :mod:`anonymate.namen`).

    Link on ``vbo_id`` when given, otherwise on postcode + huisnummer (+ letter/addition).
    Adds ``register_gekoppeld__bool`` (True/False). Ambiguous address matches (several dwellings, e.g. a
    missing house letter) are left unlinked rather than guessed.
    """
    have = [c for c in REGISTER_COLUMNS if c in population.columns]
    key_cols = ["vbo_id__str"] if vbo_id else ["postcode6__str", "huisnummer__str",
                                               "huisletter__str", "toevoeging__str"]
    for c in key_cols:
        population.require(c)
    left = pd.DataFrame(index=df.index)
    if vbo_id:
        left["k_vbo"] = df[vbo_id].map(lambda v: None if pd.isna(v) else str(v).strip().zfill(16))
        on = ["k_vbo"]
        sel = "vbo_id__str AS k_vbo"
    else:
        if not (postcode and huisnummer):
            raise ValueError("geef vbo_id of postcode + huisnummer op / give vbo_id or "
                             "postcode + huisnummer")
        left["k_pc"] = df[postcode].map(_norm_pc)
        left["k_nr"] = pd.to_numeric(df[huisnummer], errors="coerce").astype("Int64")
        left["k_let"] = df[huisletter].map(_norm_str) if huisletter else ""
        left["k_toe"] = df[toevoeging].map(_norm_str) if toevoeging else ""
        on = ["k_pc", "k_nr", "k_let", "k_toe"]
        sel = ("postcode6__str AS k_pc, TRY_CAST(huisnummer__str AS BIGINT) AS k_nr, "
               "upper(coalesce(CAST(huisletter__str AS VARCHAR), '')) AS k_let, "
               "upper(coalesce(CAST(toevoeging__str AS VARCHAR), '')) AS k_toe")
    left["_row"] = range(len(df))
    con = population.con
    con.register("anonymate_link", left)
    try:
        params: list = []
        where = population.where(params)
        cols = ", ".join(f'p."{c}"' for c in have)
        res = con.execute(f"""
            WITH p AS (SELECT {sel}, * FROM {population.relation} WHERE {where})
            SELECT l._row, {cols}, count(*) OVER (PARTITION BY l._row) AS _n
            FROM anonymate_link l JOIN p USING ({', '.join(on)})
        """, params).fetchdf()
    finally:
        con.unregister("anonymate_link")
    res = res[res["_n"] == 1].set_index("_row")
    out = df.copy()
    rows = pd.Series(range(len(df)), index=df.index)
    for c in have:
        out[prefix + c] = rows.map(res[c]) if len(res) else None
    out[prefix + "gekoppeld__bool"] = rows.isin(res.index)
    return out
