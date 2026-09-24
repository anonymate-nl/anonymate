"""Which dwellings could a record be? The candidate list behind a small k.

For records that fail the test, :func:`candidates` lists the population dwellings that match all
of the record's register QIDs (with the same tolerance and the same handling of unknown values as
:func:`~anonymate.risk.assess`), with their address. That is what a data holder needs to check
the finding: is the participating dwelling really among them, and how few are there?

**This list is itself a re-identification aid.** It names the handful of addresses a published
record points to. Give it only to the data holder (who already knows the addresses), never publish
it, and keep it out of version control.
"""
from __future__ import annotations

import pandas as pd

from .population import Population, _quote, sql_condition
from .risk import Assessment, Status, parse_constraints

ADDRESS = ["vbo_id", "postcode6", "huisnummer", "huisletter", "toevoeging", "woonplaats"]


def candidates(df: pd.DataFrame, assessment: Assessment, population: Population, *,
               max_per_record: int = 100, only_at_risk: bool = True,
               unknown_matches: bool = False) -> pd.DataFrame:
    """One row per (record, candidate dwelling), for the records that failed the test.

    Only register QIDs (counted against the population) select candidates; QIDs without a
    register (e.g. annual use) only lower the estimated k and cannot narrow an address list.
    Records whose class holds more than ``max_per_record`` dwellings are listed with their count
    only (``kandidaat_nr`` empty): a long list checks nothing and exposes many addresses.
    """
    counted = [q for q in assessment.qids if q.counted]
    records = assessment.records
    rows = records.index[records["status"] == Status.AT_RISK] if only_at_risk else records.index
    cons = parse_constraints(df.loc[rows], counted)
    shown = [c for c in ADDRESS if c in population.columns]
    qcols = list(dict.fromkeys(q.spec.population_column for q in counted))
    out = []
    for i in rows:
        n = int(records.at[i, "k_populatie"])
        base = {"record": i, "status": records.at[i, "status"], "k_populatie": n,
                "k": float(records.at[i, "k"]), "delta": float(records.at[i, "delta"])}
        if n > max_per_record or n == 0:
            out.append({**base, "kandidaat_nr": pd.NA})
            continue
        params: list = []
        conds = [population.where(params)]
        for q in counted:
            c = cons.at[i, q.column]
            if c is None:
                continue
            col = q.spec.population_column
            cond = sql_condition(col, c, params)
            if unknown_matches:
                cond = f"({_quote(col)} IS NULL OR {cond})"
            conds.append(cond)
        select = ", ".join(_quote(c) for c in shown + [c for c in qcols if c not in shown])
        sql = (f"SELECT {select} FROM {population.relation} WHERE {' AND '.join(conds)} "
               f"ORDER BY {', '.join(_quote(c) for c in shown) or '1'} LIMIT {max_per_record}")
        found = population.con.execute(sql, params).fetchdf()
        for j, cand in enumerate(found.to_dict("records"), start=1):
            out.append({**base, "kandidaat_nr": j, **cand})
    return pd.DataFrame(out)
