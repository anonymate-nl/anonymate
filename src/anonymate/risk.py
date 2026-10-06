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
is the product over those attributes of how often the record's value occurs in the dataset;
i.e. we assume the value distribution in the population resembles the one in the dataset and
is independent of the register attributes. The report marks such numbers as estimates.

No network I/O happens in this module.
"""
from __future__ import annotations

import bisect

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from .constraints import Constraint, OneOf, Range, render
from .lezing import Lezing
from .namen import h3_kolom
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
    """A dataset column interpreted as a quasi-identifier.

    ``tolerance`` records that published values were perturbed by at most that much (noise), and
    an attacker who knows the method reads each value as "the true value lies within
    ``tolerance``". Numeric attributes: in their own unit. H3 cells: in kilometres, for locations
    that got noise *before* being snapped to a cell (the true dwelling may lie in a neighbouring
    cell).

    ``lezing`` records how the published values are to be read beyond their face value: rounded
    to a step, or classes that share a boundary (kladbloknotitie 17, :mod:`anonymate.lezing`).
    """

    column: str
    spec: QidSpec
    tolerance: float = 0.0
    lezing: Lezing | None = None

    @property
    def counted(self) -> bool:
        """True if the population can be counted exactly on this attribute."""
        return self.spec.population_column is not None

    def parse(self, value: object, *, with_tolerance: bool = True) -> Constraint:
        c = self.spec.parse(value)
        if not with_tolerance or c is None:
            return c
        if self.lezing is not None:
            c = self.lezing.apply(c, self.spec.integer)
        return widen(c, self.tolerance, self.spec) if self.tolerance else c


def widen(c: Constraint, tolerance: float, spec: QidSpec) -> Constraint:
    """What an attacker learns from a value perturbed by at most ``tolerance``."""
    if isinstance(c, Range):
        return Range(None if c.lo is None else c.lo - tolerance,
                     None if c.hi is None else c.hi + tolerance)
    if isinstance(c, OneOf) and spec.key == "h3_cel":
        import math

        import h3
        cells = set()
        for cell in c.values:
            if not h3.is_valid_cell(cell):
                cells.add(cell)
                continue
            res = h3.get_resolution(cell)
            spacing = math.sqrt(3) * h3.average_hexagon_edge_length(res, unit="km")
            cells |= set(h3.grid_disk(cell, math.ceil(tolerance / spacing)))
        return OneOf(frozenset(cells))
    return c


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
        """The counts and the k / delta figures. k and delta are taken over the records that
        have a match in the population: for a record without match k is not "0 equal
        dwellings" but unknown (delta infinite), so it does not drag the minimum or the median
        down; without any match they are None."""
        r = self.records
        matched = r[r["status"] != Status.NO_MATCH]
        return {
            "records": len(r),
            "ok": int((r["status"] == Status.OK).sum()),
            "risico": int((r["status"] == Status.AT_RISK).sum()),
            "geen_match": int((r["status"] == Status.NO_MATCH).sum()),
            "k_min": _num_or_none(matched["k"].min()),
            "k_mediaan": _num_or_none(matched["k"].median()),
            "delta_max": _num_or_none(matched["delta"].replace(np.inf, np.nan).max()),
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


def parse_constraints(df: pd.DataFrame, qids: list[QidColumn], *,
                      with_tolerance: bool = True) -> pd.DataFrame:
    """One column of :class:`~anonymate.constraints.Constraint` objects per QID.

    ``with_tolerance=False`` gives the values as published (for rewriting them); the default
    gives what an attacker can conclude from them (for counting).
    """
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
                    c = cache[v] = q.parse(v, with_tolerance=with_tolerance)
                except ValueError as e:
                    raise ValueError(f"rij/row {i!r}, kolom/column {q.column!r}: {e}") from None
            except TypeError:  # unhashable cell
                c = q.parse(v, with_tolerance=with_tolerance)
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
    active = [_resolve_h3(q, df, population) for q in qids if q.spec.knowledge <= scenario]
    counted = [q for q in active if q.counted]
    estimated = [q for q in active if not q.counted]
    warnings: list[str] = []
    # an H3 column without any cell and a population without H3 columns: nothing to count on
    counted = [q for q in counted if not (q.spec.key == "h3_cel"
                                          and q.spec.population_column == "h3_cel")]
    for q in counted:
        population.require(q.spec.population_column)  # type: ignore[arg-type]

    warnings += _historical_stations(df, active)
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


def _historical_stations(df: pd.DataFrame, qids: list[QidColumn]) -> list[str]:
    """A note per stopped KNMI station in the data: it is counted as its successor."""
    from .qids import HISTORICAL_STATIONS
    notes = []
    for q in qids:
        if q.spec.key != "knmi_station":
            continue
        seen = {str(int(float(v))) if str(v).replace(".", "", 1).isdigit() else str(v).strip()
                for v in df[q.column].dropna().astype(str).str.split("|").explode()}
        for old, (new, why) in HISTORICAL_STATIONS.items():
            if old in seen or f"6{old}" in seen:
                notes.append(f"{q.column}: historisch KNMI-station {old} ({why}); geteld als "
                             f"{new}, het station dat nu dat gebied dekt.")
    return notes


def _resolve_h3(q: QidColumn, df: pd.DataFrame, population: Population) -> QidColumn:
    """An H3 cell is counted against the population column of the same resolution."""
    if q.spec.key != "h3_cel" or q.spec.population_column in population.columns:
        return q
    import h3
    for v in df[q.column].dropna().astype(str):
        c = q.spec.parse(v)
        if isinstance(c, OneOf):
            cell = next(iter(c.values))
            if h3.is_valid_cell(cell):
                col = h3_kolom(h3.get_resolution(cell))
                return QidColumn(q.column, replace(q.spec, population_column=col), q.tolerance)
    # no cell at all (suppressed, or no dwelling located): the column constrains nothing, so
    # any H3 column of the population will do for the bookkeeping
    have = sorted(c for c in population.columns if c.startswith("h3_r"))
    if have:
        return QidColumn(q.column, replace(q.spec, population_column=have[0]), q.tolerance)
    return q


_NULL = "<<anonymate:onbekend>>"  # stands in for an unknown categorical value, so it can be joined on


# at most this many distinct class bounds per numeric attribute are grouped as intervals; more
# (a dataset of exact values) and comparing every dwelling with each costs more than it saves
BUCKETS_MAX = 64


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
    buckets: dict[int, tuple[list[float], list[float]]] = {}
    maps: dict[int, pd.DataFrame] = {}
    joins: list[str] = []
    rows = [{"cid": int(cid)} for cid in reps.index]
    for j, q in enumerate(used):
        col = '"' + q.spec.population_column.replace('"', '""') + '"'
        by_cid = dict(zip(reps.index.astype(int), reps[q.column]))
        if q.spec.kind == Kind.CATEGORICAL:
            select.append(f"coalesce(CAST({col} AS VARCHAR), '{_NULL}') AS q{j}")
            on.append(f"c.v{j} = a.q{j}")
            expanded = []
            # rows may already be unnested by an earlier attribute: look up by class id,
            # never pair by position
            for row in rows:
                c = by_cid[row["cid"]]
                values = sorted(c.values) + ([_NULL] if unknown_matches else [])
                expanded += [{**row, f"v{j}": v} for v in values]
            rows = expanded
        else:
            unknown = f"a.q{j} IS NULL OR " if unknown_matches else ""
            ranges = [c for c in reps[q.column] if c is not None]
            lows = sorted({float(c.lo) for c in ranges if c.lo is not None})
            highs = sorted({float(c.hi) for c in ranges if c.hi is not None})
            if len(lows) + len(highs) <= BUCKETS_MAX:
                # group the population on the elementary intervals the classes' bounds make,
                # not on the exact value: a few hundred groups instead of millions (exact year
                # times exact m²), with the same counts. l = #(lows <= x), h = #(highs < x):
                # lo <= x <= hi exactly when l >= #(lows <= lo) and h <= #(highs < hi).
                # per distinct value (a few hundred years, a few thousand m²) once, in Python;
                # then one hash lookup per dwelling instead of a comparison per bound
                buckets[j] = (lows, highs)
                vals = [v for (v,) in population.con.execute(
                    f"SELECT DISTINCT {col} FROM {population.relation} WHERE {col} IS NOT NULL"
                ).fetchall()]
                maps[j] = pd.DataFrame({
                    "v": vals,
                    "l": [bisect.bisect_right(lows, float(v)) for v in vals],
                    "h": [bisect.bisect_left(highs, float(v)) for v in vals]})
                joins.append(f"LEFT JOIN anonymate_vak{j} m{j} ON p.{col} = m{j}.v")
                select.append(f"m{j}.l AS q{j}")
                select.append(f"m{j}.h AS r{j}")
                filters.append(f"({unknown}((c.lo{j} IS NULL OR a.q{j} >= c.pl{j}) AND "
                               f"(c.hi{j} IS NULL OR a.r{j} <= c.ph{j}) AND a.q{j} IS NOT NULL))")
            else:
                select.append(f"{col} AS q{j}")
                filters.append(f"({unknown}((c.lo{j} IS NULL OR a.q{j} >= c.lo{j}) AND "
                               f"(c.hi{j} IS NULL OR a.q{j} <= c.hi{j}) AND a.q{j} IS NOT NULL))")
    bounds = {int(cid): c for cid, c in zip(reps.index, zip(*[reps[q.column] for q in used]))}
    for row in rows:
        for j, q in enumerate(used):
            if q.spec.kind == Kind.NUMERIC:
                c = bounds[row["cid"]][j]
                row[f"lo{j}"], row[f"hi{j}"] = c.lo, c.hi
                if j in buckets:
                    lows, highs = buckets[j]
                    row[f"pl{j}"] = None if c.lo is None else bisect.bisect_right(lows, c.lo)
                    row[f"ph{j}"] = None if c.hi is None else bisect.bisect_left(highs, c.hi)
    classes = pd.DataFrame(rows)
    for j, q in enumerate(used):
        if q.spec.kind == Kind.NUMERIC:
            classes[f"lo{j}"] = classes[f"lo{j}"].astype("Float64")
            classes[f"hi{j}"] = classes[f"hi{j}"].astype("Float64")
            if j in buckets:
                classes[f"pl{j}"] = classes[f"pl{j}"].astype("Int64")
                classes[f"ph{j}"] = classes[f"ph{j}"].astype("Int64")
        else:
            classes[f"v{j}"] = classes[f"v{j}"].astype(object)

    agg_sql = (f"SELECT {', '.join(select)}, count(*) AS n FROM {population.relation} p "
               f"{' '.join(joins)} WHERE {where} GROUP BY ALL")
    join = f"JOIN a ON {' AND '.join(on)}" if on else "CROSS JOIN a"
    filt = " AND ".join(filters) or "TRUE"
    con = population.con
    con.register("anonymate_classes", classes)
    for j, m in maps.items():
        con.register(f"anonymate_vak{j}", m)
    try:
        sql = (f"WITH a AS ({agg_sql}) SELECT c.cid, sum(a.n) AS n "
               f"FROM anonymate_classes c {join} WHERE {filt} GROUP BY c.cid")
        res = con.execute(sql, params).fetchdf()
    finally:
        con.unregister("anonymate_classes")
        for j in maps:
            con.unregister(f"anonymate_vak{j}")
    return res.set_index("cid")["n"].astype("int64").reindex(reps.index, fill_value=0)


def _estimated_share(cons: pd.DataFrame, class_id: pd.Series,
                     estimated: list[QidColumn]) -> pd.Series:
    """Estimated fraction of population dwellings sharing the record's uncounted values.

    Per attribute: how often the record's value occurs among the dataset records that have a
    value (the dataset as sample of the population), multiplied over attributes (assumed
    independent of each other and of the register attributes). A missing value reveals nothing
    (factor 1). Using the whole dataset rather than only the record's own class matters: in a
    small dataset most classes hold one record, and within-class shares would then always be 1,
    hiding that e.g. an exact annual gas use is as good as unique to an energy supplier.
    """
    share = pd.Series(1.0, index=cons.index)
    for q in estimated:
        rendered = cons[q.column].map(render)
        known = rendered[rendered != ""]
        if known.empty:
            continue
        freq = known.map(known.value_counts()) / len(known)
        share.loc[freq.index] *= freq
    return share
