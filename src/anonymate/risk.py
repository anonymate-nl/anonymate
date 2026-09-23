"""Re-identification risk of a dataset, measured against the whole reference population.

Two population-based metrics (not k-anonymity *within* the dataset, which systematically
underestimates risk for small datasets drawn from a large population):

k-map
    For each published record: how many dwellings in the population match everything the record
    reveals about its quasi-identifiers? An attacker who knows a target's attributes can narrow
    the target down to those ``k`` dwellings, so the chance of a correct re-identification is
    ``1/k``. A record is at risk when ``k < round(1/p)``.

δ-presence
    For each equivalence class: which fraction ``δ = f/F`` of the ``F`` matching dwellings in the
    population appears in the dataset? This is the probability that an attacker correctly infers
    "this dwelling takes part", even without pinpointing its record. A class is at risk when
    ``δ > δ_max`` (default ``δ_max = p``). δ grows quickly when the population is narrowed by
    known inclusion criteria, which is exactly why those criteria must be part of the scope.

Attributes without a complete public register (``OBSERVABLE``/``INSIDER``) cannot be counted in
the population. For those the population count is *estimated* as ``F × share``, where ``share``
is the fraction of dataset records in the same register class that share the record's values;
i.e. we assume the value distribution in the population resembles the one in the dataset. The
report marks such numbers as estimates.

No network I/O happens in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .constraints import Constraint, OneOf, Range, render
from .population import Population
from .qids import Kind, Knowledge, QidSpec

P_MIN, P_MAX, P_DEFAULT = 0.05, 0.33, 0.09


@dataclass(frozen=True)
class Threshold:
    """Maximum acceptable re-identification probability ``p`` and derived ``k``."""

    p: float = P_DEFAULT
    delta_max: float | None = None  # None: same as p

    def __post_init__(self) -> None:
        if not (P_MIN <= self.p <= P_MAX):
            raise ValueError(f"p moet tussen {P_MIN} en {P_MAX} liggen / p must be in "
                             f"[{P_MIN}, {P_MAX}], got {self.p}")
        if self.delta_max is not None and not (0 < self.delta_max <= 1):
            raise ValueError(f"delta_max must be in (0, 1], got {self.delta_max}")

    @property
    def k(self) -> int:
        return round(1 / self.p)

    @property
    def delta(self) -> float:
        return self.p if self.delta_max is None else self.delta_max


@dataclass(frozen=True)
class QidColumn:
    """A dataset column interpreted as a quasi-identifier."""

    column: str
    spec: QidSpec

    @property
    def counted(self) -> bool:
        """True if the population can be counted exactly on this attribute."""
        return self.spec.population_column is not None


class Status:
    OK = "ok"
    AT_RISK = "risico"
    NO_MATCH = "geen_match"


@dataclass
class Assessment:
    """Outcome of :func:`assess`. ``records`` is aligned with the input dataset's index."""

    records: pd.DataFrame
    threshold: Threshold
    qids: list[QidColumn]
    scenario: Knowledge
    population_size: int
    population_snapshot: str
    scope: str
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> pd.Series:
        return self.records["status"] == Status.OK

    def summary(self) -> dict:
        r = self.records
        return {
            "records": len(r),
            "ok": int((r["status"] == Status.OK).sum()),
            "risico": int((r["status"] == Status.AT_RISK).sum()),
            "geen_match": int((r["status"] == Status.NO_MATCH).sum()),
            "k_min": _num_or_none(r["k"].min()),
            "k_mediaan": _num_or_none(r["k"].median()),
            "delta_max": _num_or_none(r["delta"].replace(np.inf, np.nan).max()),
            "p": self.threshold.p,
            "k_drempel": self.threshold.k,
            "delta_drempel": self.threshold.delta,
            "scenario": self.scenario.name,
            "qids": [q.column for q in self.qids],
            "populatie": self.population_size,
            "afbakening": self.scope or "heel Nederland / all of the Netherlands",
            "snapshot": self.population_snapshot,
        }


def _num_or_none(x) -> float | None:
    return None if x is None or pd.isna(x) else float(x)


def parse_constraints(df: pd.DataFrame, qids: list[QidColumn]) -> pd.DataFrame:
    """One column of :class:`~anonymate.constraints.Constraint` objects per QID."""
    out = {}
    for q in qids:
        if q.column not in df.columns:
            raise KeyError(f"kolom {q.column!r} niet in dataset / column not in dataset")
        cache: dict = {}  # datasets repeat values a lot; parse each distinct value once
        vals = []
        for i, v in zip(df.index, df[q.column].tolist()):
            try:
                c = cache[v]
            except KeyError:
                try:
                    c = cache[v] = q.spec.parse(v)
                except ValueError as e:
                    raise ValueError(f"rij/row {i!r}, kolom/column {q.column!r}: {e}") from None
            except TypeError:  # unhashable cell
                c = q.spec.parse(v)
            vals.append(c)
        out[q.column] = pd.Series(vals, index=df.index, dtype=object)
    return pd.DataFrame(out, index=df.index)


def assess(
    df: pd.DataFrame,
    qids: list[QidColumn],
    population: Population,
    threshold: Threshold = Threshold(),
    scenario: Knowledge = Knowledge.REGISTER,
    *,
    unknown_matches: bool = False,
) -> Assessment:
    """Assess every record of ``df`` against ``population``.

    Only QIDs whose knowledge level is within ``scenario`` are used. With
    ``unknown_matches=False`` (default, conservative) a population dwelling with an unknown value
    (e.g. no registered energy label) does *not* count as a match; this can only make classes
    smaller, i.e. the risk estimate larger.
    """
    active = [q for q in qids if q.spec.knowledge <= scenario]
    counted = [q for q in active if q.counted]
    estimated = [q for q in active if not q.counted]
    warnings: list[str] = []
    for q in counted:
        population.require(q.spec.population_column)  # type: ignore[arg-type]

    cons = parse_constraints(df, active)
    columns = [[render(c) for c in cons[q.column].tolist()] for q in counted]
    keys = ["\x1f".join(parts) for parts in zip(*columns)] if counted else [""] * len(df)
    class_id = pd.Series(pd.factorize(pd.Series(keys, dtype=object))[0] if len(df) else [],
                         index=df.index, dtype="int64")
    f_class = class_id.map(class_id.value_counts())

    representatives = cons.groupby(class_id).head(1)
    representatives.index = class_id.loc[representatives.index].values
    F = _count_population(representatives, counted, population, unknown_matches)
    F_rec = class_id.map(F).astype("int64")

    share = _estimated_share(cons, class_id, estimated) if estimated else \
        pd.Series(1.0, index=df.index)
    k = F_rec * share
    delta = pd.Series(np.where(F_rec > 0, f_class / F_rec.clip(lower=1), np.inf), index=df.index)

    status, reasons = [], []
    for F_i, k_i, d_i, f_i in zip(F_rec.tolist(), k.tolist(), delta.tolist(), f_class.tolist()):
        why = []
        if F_i == 0:
            status.append(Status.NO_MATCH)
            reasons.append("geen enkele woning in de populatie past bij dit record / "
                           "no dwelling in the population matches this record")
            continue
        if k_i < threshold.k:
            why.append(f"k={k_i:.3g} < {threshold.k}")
        if d_i > threshold.delta:
            why.append(f"δ={d_i:.3g} > {threshold.delta:g}")
        if f_i > F_i:
            why.append("meer records dan woningen in deze klasse: klopt de afbakening? / "
                       "more records than dwellings in this class: is the scope right?")
        status.append(Status.AT_RISK if why else Status.OK)
        reasons.append("; ".join(why))

    n_inconsistent = int((f_class > F_rec).sum())
    if n_inconsistent:
        warnings.append(f"{n_inconsistent} records vallen in een klasse met meer records dan "
                        "woningen; de populatie-afbakening is waarschijnlijk te krap of de "
                        "data wijkt af van de registers.")
    if estimated:
        warnings.append("k is geschat voor kenmerken zonder volledig register: "
                        + ", ".join(q.column for q in estimated))

    records = pd.DataFrame({
        "klasse": class_id,
        "f_dataset": f_class.astype("int64"),
        "k_populatie": F_rec,
        "k": k.astype(float),
        "k_geschat": bool(estimated),
        "delta": delta,
        "risico": np.where(k > 0, 1 / k.clip(lower=1e-12), 1.0).clip(max=1.0),
        "status": status,
        "redenen": reasons,
    }, index=df.index)
    return Assessment(records, threshold, active, scenario, population.size(),
                      population.snapshot.describe(), population.scope.description, warnings)


_NULL = "<<anonymate:onbekend>>"  # stands in for an unknown categorical value, so it can be joined on


def _count_population(reps: pd.DataFrame, counted: list[QidColumn], population: Population,
                      unknown_matches: bool) -> pd.Series:
    """Number of population dwellings matching each class representative.

    Classes are handled per *pattern* (which QIDs they constrain), so each query aggregates the
    population on only the columns that matter. Categorical constraints are unnested into one
    row per allowed value and hash-joined; numeric ranges filter the joined rows. The unnested
    rows of one class match disjoint sets of dwellings, so summing them never double-counts.
    """
    if reps.empty:
        return pd.Series(dtype="int64")
    result = pd.Series(0, index=reps.index, dtype="int64")
    patterns = reps[[q.column for q in counted]].notna().apply(tuple, axis=1) if counted         else pd.Series([()] * len(reps), index=reps.index)
    for pattern, idx in patterns.groupby(patterns).groups.items():
        used = [q for q, on in zip(counted, pattern) if on]
        result.loc[idx] = _count_pattern(reps.loc[idx], used, population, unknown_matches)
    return result


def _count_pattern(reps: pd.DataFrame, used: list[QidColumn], population: Population,
                   unknown_matches: bool) -> pd.Series:
    params: list = []
    where = population.where(params)
    if not used:
        n = population.con.execute(
            f"SELECT count(*) FROM {population.relation} WHERE {where}", params).fetchone()[0]
        return pd.Series(int(n), index=reps.index)

    select, on, filters = [], [], []
    rows = [{"cid": int(cid)} for cid in reps.index]
    for j, q in enumerate(used):
        col = '"' + q.spec.population_column.replace('"', '""') + '"'
        cs = reps[q.column]
        if q.spec.kind == Kind.CATEGORICAL:
            select.append(f"coalesce(CAST({col} AS VARCHAR), '{_NULL}') AS q{j}")
            on.append(f"c.v{j} = a.q{j}")
            expanded = []
            for row, c in zip(rows, cs):
                values = sorted(c.values) + ([_NULL] if unknown_matches else [])
                expanded += [{**row, f"v{j}": v} for v in values]
            rows = expanded
        else:
            select.append(f"{col} AS q{j}")
            unknown = f"a.q{j} IS NULL OR " if unknown_matches else ""
            filters.append(f"({unknown}((c.lo{j} IS NULL OR a.q{j} >= c.lo{j}) AND "
                           f"(c.hi{j} IS NULL OR a.q{j} <= c.hi{j}) AND a.q{j} IS NOT NULL))")
    bounds = {int(cid): c for cid, c in zip(reps.index, zip(*[reps[q.column] for q in used]))}
    for row in rows:
        for j, q in enumerate(used):
            if q.spec.kind == Kind.NUMERIC:
                c = bounds[row["cid"]][j]
                row[f"lo{j}"], row[f"hi{j}"] = c.lo, c.hi
    classes = pd.DataFrame(rows)
    for j, q in enumerate(used):
        if q.spec.kind == Kind.NUMERIC:
            classes[f"lo{j}"] = classes[f"lo{j}"].astype("Float64")
            classes[f"hi{j}"] = classes[f"hi{j}"].astype("Float64")
        else:
            classes[f"v{j}"] = classes[f"v{j}"].astype(object)

    agg_sql = (f"SELECT {', '.join(select)}, count(*) AS n FROM {population.relation} "
               f"WHERE {where} GROUP BY ALL")
    join = f"JOIN a ON {' AND '.join(on)}" if on else "CROSS JOIN a"
    filt = " AND ".join(filters) or "TRUE"
    con = population.con
    con.register("anonymate_classes", classes)
    try:
        sql = (f"WITH a AS ({agg_sql}) SELECT c.cid, sum(a.n) AS n "
               f"FROM anonymate_classes c {join} WHERE {filt} GROUP BY c.cid")
        res = con.execute(sql, params).fetchdf()
    finally:
        con.unregister("anonymate_classes")
    return res.set_index("cid")["n"].astype("int64").reindex(reps.index, fill_value=0)


def _estimated_share(cons: pd.DataFrame, class_id: pd.Series,
                     estimated: list[QidColumn]) -> pd.Series:
    """Fraction of the record's register class sharing its (known) uncounted values."""
    rendered = pd.DataFrame({q.column: cons[q.column].map(render) for q in estimated})
    share = pd.Series(1.0, index=cons.index)
    for _, members in class_id.groupby(class_id).groups.items():
        sub = rendered.loc[members]
        n = len(sub)
        for i in members:
            known = [c for c in sub.columns if sub.at[i, c] != ""]
            if not known:
                continue
            same = (sub[known] == sub.loc[i, known]).all(axis=1).sum()
            share[i] = same / n
    return share
