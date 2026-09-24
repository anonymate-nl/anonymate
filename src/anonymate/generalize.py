"""Anonymisation actions and the risk-utility trade-off.

An action rewrites one quasi-identifier column of the dataset into something coarser: a wider
class (:class:`Bin`, :class:`Edges`), a group of categories (:class:`Group`), a coarser region
(:class:`LocationUp`) or nothing at all (:class:`Suppress`). The rewritten column is exactly what
would be published, and the risk module simply re-reads it; there is no hidden state.

:func:`tradeoff` applies a sequence of actions and reports after each step how many records pass
and how much detail was given up. :func:`suggest` searches such a sequence greedily.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol

import numpy as np
import pandas as pd

from .constraints import Constraint, OneOf, Range, render
from .population import Population
from .qids import CATALOGUE, ENERGY_LABELS, Kind, Knowledge, QidSpec
from .risk import QidColumn, Status, Threshold, assess, parse_constraints


class Action(Protocol):
    column: str

    def describe(self) -> str: ...

    def apply(self, df: pd.DataFrame, qids: list[QidColumn],
              population: Population | None) -> tuple[pd.DataFrame, list[QidColumn]]: ...


def _qid(qids: list[QidColumn], column: str) -> QidColumn:
    for q in qids:
        if q.column == column:
            return q
    raise KeyError(f"{column!r} is geen quasi-identifier / is not a quasi-identifier")


def _rewrite(df: pd.DataFrame, q: QidColumn, fn) -> pd.DataFrame:
    cons = parse_constraints(df, [q])[q.column]
    return _with_column(df, q.column, [fn(c) if c is not None else None for c in cons])


def _with_column(df: pd.DataFrame, column: str, constraints: list[Constraint]) -> pd.DataFrame:
    out = df.copy()
    out[column] = pd.Series([render(c) or None for c in constraints], index=df.index,
                            dtype=object)
    return out


@dataclass(frozen=True)
class Bin:
    """Widen numeric values to fixed-width classes (``width=10`` on years: decades).

    ``below``/``above`` fold the tails into open classes (``<=1944``, ``>=2015``).
    """

    column: str
    width: float
    origin: float = 0
    below: float | None = None
    above: float | None = None

    def describe(self) -> str:
        tail = ""
        if self.below is not None:
            tail += f", <{self.below:g}"
        if self.above is not None:
            tail += f", >={self.above:g}"
        return f"{self.column}: klassen van {self.width:g}{tail}"

    def apply(self, df, qids, population=None):
        q = _qid(qids, self.column)
        step = 1 if q.spec.integer else 0
        w, o = self.width, self.origin

        def widen(c: Constraint) -> Constraint:
            assert isinstance(c, Range)
            lo = None if c.lo is None else math.floor((c.lo - o) / w) * w + o
            hi = None if c.hi is None else math.floor((c.hi - o) / w) * w + o + w - step
            # tails are decided on the original value; regular classes are clipped at the tails
            if self.below is not None:
                if c.hi is not None and c.hi < self.below:
                    return Range(None, self.below - step)
                lo = None if c.lo is None or c.lo < self.below else max(lo, self.below)
            if self.above is not None:
                if c.lo is not None and c.lo >= self.above:
                    return Range(self.above, None)
                hi = None if c.hi is None or c.hi >= self.above else min(hi, self.above - step)
            return Range(lo, hi)

        return _rewrite(df, q, widen), qids


@dataclass(frozen=True)
class Edges:
    """Widen numeric values to the classes delimited by ``edges`` (each edge starts a class)."""

    column: str
    edges: tuple[float, ...]

    def describe(self) -> str:
        return f"{self.column}: klassen vanaf {', '.join(f'{e:g}' for e in self.edges)}"

    def apply(self, df, qids, population=None):
        q = _qid(qids, self.column)
        step = 1 if q.spec.integer else 0
        edges = sorted(self.edges)

        def bounds(x: float | None, upper: bool) -> float | None:
            if x is None:
                return None
            i = int(np.searchsorted(edges, x, side="right"))  # class index 0..len(edges)
            if upper:
                return None if i == len(edges) else edges[i] - step
            return None if i == 0 else edges[i - 1]

        def widen(c: Constraint) -> Constraint:
            assert isinstance(c, Range)
            return Range(bounds(c.lo, False), bounds(c.hi, True))

        return _rewrite(df, q, widen), qids


@dataclass(frozen=True)
class Group:
    """Merge categories: a value becomes the union of every group it overlaps."""

    column: str
    groups: tuple[frozenset[str], ...]

    @classmethod
    def of(cls, column: str, *groups: Iterable[str]) -> "Group":
        return cls(column, tuple(frozenset(g) for g in groups))

    def describe(self) -> str:
        return f"{self.column}: groepen " + ", ".join("|".join(sorted(g)) for g in self.groups)

    def apply(self, df, qids, population=None):
        q = _qid(qids, self.column)

        def widen(c: Constraint) -> Constraint:
            assert isinstance(c, OneOf)
            vals = set(c.values)
            for g in self.groups:
                if vals & g:
                    vals |= g
            return OneOf(frozenset(vals))

        return _rewrite(df, q, widen), qids


@dataclass(frozen=True)
class Suppress:
    """Do not publish this attribute at all."""

    column: str

    def describe(self) -> str:
        return f"{self.column}: weglaten"

    def apply(self, df, qids, population=None):
        _qid(qids, self.column)
        out = df.copy()
        out[self.column] = pd.Series([None] * len(df), index=df.index, dtype=object)
        return out, qids


@dataclass(frozen=True)
class LocationUp:
    """Replace a location by a coarser one, e.g. ``postcode4`` -> ``gemeente``.

    The coarser value is looked up in the local population (most common value for the finer
    one). The column keeps its name but changes meaning, so its QID spec is replaced.
    """

    column: str
    to: str

    def describe(self) -> str:
        return f"{self.column}: vergroven naar {self.to}"

    def apply(self, df, qids, population=None):
        if population is None:
            raise ValueError("LocationUp needs the population for its lookup table")
        q = _qid(qids, self.column)
        target = CATALOGUE[self.to]
        cons = parse_constraints(df, [q])[q.column]
        keys = sorted({v for c in cons if isinstance(c, OneOf) for v in c.values})
        table = population.lookup(target.population_column, q.spec.population_column, keys)

        def up(c: Constraint) -> Constraint:
            assert isinstance(c, OneOf)
            vals = {table[v] for v in c.values if v in table}
            return OneOf(frozenset(vals)) if vals else None

        out = _with_column(df, q.column, [up(c) if c is not None else None for c in cons])
        new_qids = [QidColumn(x.column, target) if x.column == q.column else x for x in qids]
        return out, new_qids


# ------------------------------------------------------------------------------------------------
# information loss
# ------------------------------------------------------------------------------------------------

# Location detail lost per level; a hierarchy, so a fixed scale is fairer than set sizes.
LOCATION_LOSS = {"postcode6": 0.0, "h3_cel": 0.25, "postcode4": 0.25, "knmi_station": 0.5,
                 "gemeente": 0.5, "provincie": 0.75}


def information_loss(df: pd.DataFrame, qids: list[QidColumn],
                     reference: pd.DataFrame | None = None) -> float:
    """Mean loss over records and QIDs: 0 = exact values, 1 = attribute suppressed.

    Numeric: class width relative to the attribute's domain. Categorical: (|set|-1)/(|domain|-1).
    ``reference`` (the original dataset) supplies domains the catalogue does not know.
    """
    if not qids or df.empty:
        return 0.0
    cons = parse_constraints(df, qids)
    losses = []
    for q in qids:
        if q.spec.key in LOCATION_LOSS:
            base = LOCATION_LOSS[q.spec.key]
            losses.append(cons[q.column].map(lambda c: 1.0 if c is None else base).mean())
            continue
        ref = parse_constraints(reference, [q]) if reference is not None else cons
        domain = _domain(q.spec, ref[q.column])
        losses.append(cons[q.column].map(lambda c: _loss(c, domain)).mean())
    return float(np.mean(losses))


def _domain(spec: QidSpec, observed: pd.Series):
    if spec.kind == Kind.NUMERIC:
        if spec.domain:
            return spec.domain
        los = [c.lo for c in observed if isinstance(c, Range) and c.lo is not None]
        his = [c.hi for c in observed if isinstance(c, Range) and c.hi is not None]
        return (min(los), max(his)) if los and his else (0, 1)
    if spec.domain:
        return tuple(spec.domain)
    return tuple(sorted({v for c in observed if isinstance(c, OneOf) for v in c.values}))


def _loss(c: Constraint, domain) -> float:
    if c is None:
        return 1.0
    if isinstance(c, Range):
        lo, hi = domain
        span = max(hi - lo, 1e-9)
        return min(1.0, c.width() / span)
    n = len(domain)
    return 0.0 if n <= 1 else min(1.0, (len(c.values) - 1) / (n - 1))


# ------------------------------------------------------------------------------------------------
# trade-off and search
# ------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Step:
    description: str
    df: pd.DataFrame
    qids: list[QidColumn]
    ok: int
    at_risk: int
    no_match: int
    k_median: float | None
    loss: float
    log_k: float = 0.0  # mean log(k): a smooth progress measure while no record passes yet

    def row(self) -> dict:
        n = self.ok + self.at_risk + self.no_match
        return {"stap": self.description, "ok": self.ok, "risico": self.at_risk,
                "geen_match": self.no_match, "publiceerbaar_%": 100 * self.ok / n if n else 0.0,
                "k_mediaan": self.k_median, "informatieverlies": self.loss}


def _evaluate(desc, df, qids, original, population, threshold, scenario, unknown_matches):
    a = assess(df, qids, population, threshold, scenario, unknown_matches=unknown_matches)
    st = a.records["status"]
    return Step(desc, df, qids, int((st == Status.OK).sum()), int((st == Status.AT_RISK).sum()),
                int((st == Status.NO_MATCH).sum()), a.summary()["k_mediaan"],
                information_loss(df, [q for q in qids if q.spec.knowledge <= scenario], original),
                float(np.log(a.records["k"].clip(lower=1)).mean()) if len(df) else 0.0)


def tradeoff(df: pd.DataFrame, qids: list[QidColumn], population: Population,
             actions: Iterable[Action], threshold: Threshold = Threshold(),
             scenario: Knowledge = Knowledge.REGISTER, *,
             unknown_matches: bool = False) -> list[Step]:
    """Apply ``actions`` cumulatively; evaluate risk and information loss after each."""
    steps = [_evaluate("uitgangssituatie / baseline", df, qids, df, population, threshold,
                       scenario, unknown_matches)]
    cur, cq = df, qids
    for act in actions:
        cur, cq = act.apply(cur, cq, population)
        steps.append(_evaluate(act.describe(), cur, cq, df, population, threshold, scenario,
                               unknown_matches))
    return steps


def default_hierarchy(q: QidColumn) -> list[Action]:
    """Successively coarser actions for a QID, ending with suppression."""
    c, key = q.column, q.spec.key
    if key == "bouwjaar":
        return [Bin(c, 5), Bin(c, 10), Bin(c, 20, below=1945, above=2015), Suppress(c)]
    if key == "oppervlakte":
        return [Bin(c, 10), Bin(c, 25), Bin(c, 50, above=250), Suppress(c)]
    if key == "energielabel":
        a_plus = frozenset(ENERGY_LABELS[:6])
        return [Group.of(c, a_plus),
                Group.of(c, a_plus | {"B"}, {"C", "D"}, {"E", "F", "G"}),
                Suppress(c)]
    if key == "woningtype":
        return [Group.of(c, {"vrijstaand", "twee_onder_een_kap", "hoekwoning", "tussenwoning"}),
                Suppress(c)]
    if key == "postcode6":
        return [LocationUp(c, "postcode4"), LocationUp(c, "gemeente"),
                LocationUp(c, "provincie"), Suppress(c)]
    if key == "postcode4":
        return [LocationUp(c, "gemeente"), LocationUp(c, "provincie"), Suppress(c)]
    if key == "gemeente":
        return [LocationUp(c, "provincie"), Suppress(c)]
    if key == "uhi":
        return [Bin(c, 0.5), Bin(c, 1.0), Suppress(c)]
    if q.spec.kind == Kind.NUMERIC and not q.spec.integer:
        return [Suppress(c)]
    return [Suppress(c)]


def suggest(df: pd.DataFrame, qids: list[QidColumn], population: Population,
            threshold: Threshold = Threshold(), scenario: Knowledge = Knowledge.REGISTER, *,
            target_share: float = 1.0, max_steps: int = 20,
            hierarchies: Mapping[str, list[Action]] | None = None,
            unknown_matches: bool = False) -> list[Step]:
    """Greedy search: repeatedly take the next hierarchy step that buys most publishable records
    per unit of information loss, until ``target_share`` of records passes or nothing helps.

    "Buys" counts newly passing records first; mean log(k) breaks the tie, so the search still
    moves when a record is unique on several attributes and no single step frees it.

    A heuristic, not an optimum; every step is shown so a human can stop earlier or pick
    differently.
    """
    active = [q for q in qids if q.spec.knowledge <= scenario]
    ladders = {q.column: list((hierarchies or {}).get(q.column) or default_hierarchy(q))
               for q in active}
    cur = _evaluate("uitgangssituatie / baseline", df, qids, df, population, threshold,
                    scenario, unknown_matches)
    steps = [cur]
    n = len(df)
    for _ in range(max_steps):
        if n == 0 or cur.ok / n >= target_share:
            break
        best, best_score, best_col, best_idx = None, -math.inf, None, 0
        for col, ladder in ladders.items():
            # the first rung that helps at all; a finer rung may help nothing where a coarser does
            for idx, act in enumerate(ladder):
                nxt_df, nxt_q = act.apply(cur.df, cur.qids, population)
                cand = _evaluate(act.describe(), nxt_df, nxt_q, df, population, threshold,
                                 scenario, unknown_matches)
                gain = (cand.ok - cur.ok) + (cand.log_k - cur.log_k)
                if gain <= 1e-9:
                    continue
                score = gain / max(cand.loss - cur.loss, 1e-6)
                if score > best_score:
                    best, best_score, best_col, best_idx = cand, score, col, idx
                break
        if best is None:
            break
        del ladders[best_col][: best_idx + 1]
        cur = best
        steps.append(cur)
    return steps
