"""How coarsely must a computable quantity be published? A population-wide rounding analysis.

Some published quantities can be computed by anyone for every dwelling, e.g. the baseline heat
performance signature (see :mod:`anonymate.signature`). Publishing such a value rounded to a
step ``s`` groups dwellings by ``round(value / s)``. This module counts, over the whole
(scoped) population, how large those groups are for a grid of rounding steps, optionally
together with other published attributes (e.g. a weather station), so a step can be chosen
*before* anything is published.

The numbers describe the population, not a dataset: "if a home's rounded values are
published, how many homes share them?". A dataset of homes drawn from that population inherits
this risk; :func:`anonymate.assess` then gives the per-record answer.
"""
from __future__ import annotations

import itertools
import math
from typing import Iterable, Mapping

import pandas as pd

from .population import Population


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def group_sizes(population: Population, steps: Mapping[str, float],
                exact: Iterable[str] = (), k: int = 11) -> dict:
    """Group statistics when ``steps`` columns are rounded and ``exact`` columns published as-is.

    Returns: dwellings considered (all columns known), share in groups smaller than ``k``,
    number of dwellings that are unique (group of 1), the group size of the median dwelling,
    number of groups.
    """
    exact = list(exact)
    for c in list(steps) + exact:
        population.require(c)
    keys = [_bucket_sql(c, s) for c, s in steps.items()] + [_q(c) for c in exact]
    known = " AND ".join(f"{_q(c)} IS NOT NULL" for c in list(steps) + exact) or "TRUE"
    params: list = []
    where = population.where(params)
    sql = f"""
        WITH g AS (
            SELECT count(*) AS n FROM {population.relation}
            WHERE {where} AND {known}
            GROUP BY {', '.join(keys) if keys else '1'}
        )
        , c AS (SELECT n, sum(n) OVER (ORDER BY n ROWS UNBOUNDED PRECEDING) AS cum,
                       sum(n) OVER () AS tot FROM g)
        SELECT (SELECT sum(n) FROM g), (SELECT sum(n) FROM g WHERE n < {int(k)}),
               (SELECT sum(n) FROM g WHERE n = 1),
               -- group size of the median dwelling (not the median over groups)
               (SELECT min(n) FROM c WHERE cum >= tot / 2.0),
               (SELECT count(*) FROM g)
    """
    total, small, unique, median, groups = population.con.execute(sql, params).fetchone()
    total = int(total or 0)
    return {"woningen": total,
            "aandeel_te_klein": (small or 0) / total if total else math.nan,
            "uniek": int(unique or 0),
            "groep_mediaan": float(median) if median is not None else math.nan,
            "groepen": int(groups or 0)}


# ------------------------------------------------------------------------------------------------
# rainbow table as a frequency table: hash of the rounded values -> number of dwellings
# ------------------------------------------------------------------------------------------------

def _bucket_sql(col: str, step: float) -> str:
    # floor(x/s + 0.5): the same rule as :func:`_bucket`, so SQL and Python agree on every value
    return f"CAST(floor({_q(col)} / {float(step)!r} + 0.5) AS BIGINT)"


def _bucket(value: float, step: float) -> int:
    return int(math.floor(float(value) / float(step) + 0.5))


def rainbow_key(values: Mapping[str, object], steps: Mapping[str, float],
                exact: Iterable[str] = ()) -> str:
    """Hash of one record's published values under a rounding scheme; matches :func:`rainbow`.

    ``values`` are the published (or exact) numbers per population column."""
    import hashlib
    parts = [str(_bucket(values[c], s)) for c, s in steps.items()]
    parts += [str(values[c]) for c in exact]
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def rainbow(population: Population, steps: Mapping[str, float], exact: Iterable[str] = (),
            out: str | None = None) -> pd.DataFrame:
    """Frequency table of the rainbow table: ``hash -> n`` dwellings sharing those rounded
    values. No addresses: enough to tell how many homes a published record could be, not which.

    Look up a record with :func:`rainbow_key` and the same ``steps`` and ``exact``."""
    exact = list(exact)
    for c in list(steps) + exact:
        population.require(c)
    parts = [_bucket_sql(c, s) for c, s in steps.items()] + \
        [f"CAST({_q(c)} AS VARCHAR)" for c in exact]
    known = " AND ".join(f"{_q(c)} IS NOT NULL" for c in list(steps) + exact) or "TRUE"
    params: list = []
    where = population.where(params)
    sql = (f"SELECT md5(concat_ws('|', {', '.join(parts)})) AS hash, count(*) AS n "
           f"FROM {population.relation} WHERE {where} AND {known} GROUP BY 1")
    df = population.con.execute(sql, params).fetchdf()
    if out:
        df.to_parquet(out, index=False)
    return df


def grid(population: Population, candidates: Mapping[str, list[float]],
         exact: Iterable[str] = (), k: int = 11) -> pd.DataFrame:
    """:func:`group_sizes` for every combination of candidate steps, most detailed first."""
    names = list(candidates)
    rows = []
    for combo in itertools.product(*(sorted(candidates[n]) for n in names)):
        stats = group_sizes(population, dict(zip(names, combo)), exact, k)
        rows.append({**{f"stap_{n}": s for n, s in zip(names, combo)}, **stats})
    return pd.DataFrame(rows)
