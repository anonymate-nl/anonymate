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

REGISTER_COLUMNS = ["bouwjaar", "oppervlakte", "energielabel", "woningtype", "postcode6",
                    "postcode4", "gemeente", "provincie", "eengezins", "pand_woningen",
                    "knmi_station", "uhi"]


def _norm_pc(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    t = re.sub(r"\s+", "", str(v)).upper()
    return t or None


def _norm_str(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip().upper()


def link(df: pd.DataFrame, population: Population, *, vbo_id: str | None = None,
         postcode: str | None = None, huisnummer: str | None = None,
         huisletter: str | None = None, toevoeging: str | None = None,
         prefix: str = "register_") -> pd.DataFrame:
    """Return ``df`` with register attributes added as ``register_<attribute>`` columns.

    Link on ``vbo_id`` when given, otherwise on postcode + huisnummer (+ letter/addition).
    Adds ``register_gekoppeld`` (True/False). Ambiguous address matches (several dwellings, e.g. a
    missing house letter) are left unlinked rather than guessed.
    """
    have = [c for c in REGISTER_COLUMNS if c in population.columns]
    key_cols = ["vbo_id"] if vbo_id else ["postcode6", "huisnummer", "huisletter", "toevoeging"]
    for c in key_cols:
        population.require(c)
    left = pd.DataFrame(index=df.index)
    if vbo_id:
        left["k_vbo"] = df[vbo_id].map(lambda v: None if pd.isna(v) else str(v).strip().zfill(16))
        on = ["k_vbo"]
        sel = "vbo_id AS k_vbo"
    else:
        if not (postcode and huisnummer):
            raise ValueError("geef vbo_id of postcode + huisnummer op / give vbo_id or "
                             "postcode + huisnummer")
        left["k_pc"] = df[postcode].map(_norm_pc)
        left["k_nr"] = pd.to_numeric(df[huisnummer], errors="coerce").astype("Int64")
        left["k_let"] = df[huisletter].map(_norm_str) if huisletter else ""
        left["k_toe"] = df[toevoeging].map(_norm_str) if toevoeging else ""
        on = ["k_pc", "k_nr", "k_let", "k_toe"]
        sel = ("postcode6 AS k_pc, CAST(huisnummer AS BIGINT) AS k_nr, "
               "upper(coalesce(CAST(huisletter AS VARCHAR), '')) AS k_let, "
               "upper(coalesce(CAST(toevoeging AS VARCHAR), '')) AS k_toe")
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
    out[prefix + "gekoppeld"] = rows.isin(res.index)
    return out
