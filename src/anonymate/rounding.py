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
    number of dwellings that are unique (group of 1), median group size, number of groups.
    """
    exact = list(exact)
    for c in list(steps) + exact:
        population.require(c)
    keys = [f"round({_q(c)} / {float(s)!r})" for c, s in steps.items()] + [_q(c) for c in exact]
    known = " AND ".join(f"{_q(c)} IS NOT NULL" for c in list(steps) + exact) or "TRUE"
    params: list = []
    where = population.where(params)
    sql = f"""
        WITH g AS (
            SELECT count(*) AS n FROM {population.relation}
            WHERE {where} AND {known}
            GROUP BY {', '.join(keys) if keys else '1'}
        )
        SELECT sum(n), sum(n) FILTER (WHERE n < {int(k)}), sum(n) FILTER (WHERE n = 1),
               quantile_cont(n, 0.5), count(*)
        FROM g
    """
    total, small, unique, median, groups = population.con.execute(sql, params).fetchone()
    total = int(total or 0)
    return {"woningen": total,
            "aandeel_te_klein": (small or 0) / total if total else math.nan,
            "uniek": int(unique or 0),
            "groep_mediaan": float(median) if median is not None else math.nan,
            "groepen": int(groups or 0)}


def grid(population: Population, candidates: Mapping[str, list[float]],
         exact: Iterable[str] = (), k: int = 11) -> pd.DataFrame:
    """:func:`group_sizes` for every combination of candidate steps, most detailed first."""
    names = list(candidates)
    rows = []
    for combo in itertools.product(*(sorted(candidates[n]) for n in names)):
        stats = group_sizes(population, dict(zip(names, combo)), exact, k)
        rows.append({**{f"stap_{n}": s for n, s in zip(names, combo)}, **stats})
    return pd.DataFrame(rows)
