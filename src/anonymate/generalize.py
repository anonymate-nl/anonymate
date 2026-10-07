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
import re
from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Protocol

import numpy as np
import pandas as pd

from .constraints import Constraint, OneOf, Range, render
from .population import Population
from .qids import CATALOGUE, ENERGY_LABELS, Kind, Knowledge, QidSpec
from .risk import QidColumn, Status, Threshold, assess, parse_constraints

# The search of the windows and the browser version stops once this share of the records is
# publishable; after that every step mostly costs information. The orange dashed line of the
# trade-off chart is drawn at this value (a share: 0.95 is 95%).
TARGET_SHARE = 0.95

# One sentence next to the trade-off chart (desktop and browser) and in rapport.md.
LOSS_NOTE = ("Informatieverlies: hoeveel detail de kenmerken kwijtraken ten opzichte van de "
             "aangeleverde dataset; 0% = zoals aangeleverd, 100% = alle kenmerken weggelaten.")


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
    cons = parse_constraints(df, [q], with_tolerance=False)[q.column]
    return _with_column(df, q.column, [fn(c) if c is not None else None for c in cons])


def _rewritten(qids: list[QidColumn], q: QidColumn) -> list[QidColumn]:
    """The QIDs once ``q``'s column holds classes of AnonyMate's own: a reading of the class
    boundaries as published no longer applies, a rounding of the underlying values still does."""
    if q.lezing is None:
        return qids
    new_q = replace(q, lezing=q.lezing.na_herschrijven())
    return [new_q if x.column == q.column else x for x in qids]


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
    unit: str = ""          # for the description only: "klassen van 10 m²"

    def describe(self) -> str:
        u = f" {self.unit}" if self.unit else ""
        ut = "" if self.unit == "jaar" else u        # "<1945", not "<1945 jaar"
        tail = ""
        if self.below is not None:
            tail += f", <{self.below:g}{ut}"
        if self.above is not None:
            tail += f", >={self.above:g}{ut}"
        return f"{self.column}: klassen van {self.width:g}{u}{tail}"

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

        return _rewrite(df, q, widen), _rewritten(qids, q)


@dataclass(frozen=True)
class Edges:
    """Widen numeric values to the classes delimited by ``edges`` (each edge starts a class)."""

    column: str
    edges: tuple[float, ...]
    unit: str = ""

    def describe(self) -> str:
        u = f" {self.unit}" if self.unit else ""
        return f"{self.column}: klassen vanaf {', '.join(f'{e:g}' for e in self.edges)}{u}"

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

        return _rewrite(df, q, widen), _rewritten(qids, q)


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

        return _rewrite(df, q, widen), _rewritten(qids, q)


@dataclass(frozen=True)
class Noise:
    """Add uniform noise of at most ``amount`` to exact numeric values.

    The published value is then off by up to ``amount``; the column's tolerance grows by
    ``amount``, so the assessment assumes an attacker who knows the method and reads each value
    as a range. Values that are already classes are left alone. ``seed`` makes it reproducible.
    """

    column: str
    amount: float
    seed: int = 0

    def describe(self) -> str:
        return f"{self.column}: ruis tot ±{self.amount:g}"

    def apply(self, df, qids, population=None):
        q = _qid(qids, self.column)
        if q.spec.kind != Kind.NUMERIC:
            raise ValueError(f"ruis kan alleen op getallen / noise needs a numeric attribute: "
                             f"{self.column!r}")
        rng = np.random.default_rng(self.seed)
        cons = parse_constraints(df, [q], with_tolerance=False)[q.column]
        out = []
        for c in cons:
            if isinstance(c, Range) and c.lo is not None and c.lo == c.hi:
                v = c.lo + rng.uniform(-self.amount, self.amount)
                v = float(round(v)) if q.spec.integer else round(v, 3)
                out.append(Range(v, v))
            else:
                out.append(c)
        # integer rounding can move a value half a unit further than the noise itself
        extra = 0.5 if q.spec.integer else 0.0
        new_q = replace(q, tolerance=q.tolerance + self.amount + extra)
        return (_with_column(df, q.column, out),
                [new_q if x.column == q.column else x for x in qids])


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
                     reference: pd.DataFrame | None = None, *,
                     reference_qids: list[QidColumn] | None = None) -> float:
    """Mean loss over records and QIDs: 0 = as delivered, 1 = every attribute left out.

    With ``reference`` (the original, delivered dataset) the loss is *relative* to it, per record
    and attribute: with ``l_ref`` the loss of the original value and ``l_cur`` that of the current
    value, the loss is 0 when the original was already empty (``l_ref >= 1``) and otherwise
    ``max(0, (l_cur - l_ref) / (1 - l_ref))``. So the unchanged dataset scores exactly 0, whatever
    its own granularity or gaps. Without ``reference`` the loss is absolute (exact = 0).

    Per value: numeric = class width relative to the attribute's domain; categorical =
    (|set|-1)/(|domain|-1); location = a fixed scale per level (``LOCATION_LOSS``); empty = 1.
    ``reference`` also supplies domains the catalogue does not know. ``reference_qids`` are the
    original QID columns; only for locations they matter (the current column may since have been
    rewritten to a coarser level by :class:`LocationUp`); default: the current ones.
    """
    if not qids or df.empty:
        return 0.0
    cons = parse_constraints(df, qids)
    ref_by_col = {q.column: q for q in (reference_qids or [])}
    losses = []
    for q in qids:
        rq = ref_by_col.get(q.column, q)
        ref_cons = parse_constraints(reference, [rq])[q.column] if reference is not None else None
        if q.spec.key in LOCATION_LOSS or rq.spec.key in LOCATION_LOSS:
            cur = cons[q.column].map(
                lambda c: 1.0 if c is None else LOCATION_LOSS.get(q.spec.key, 0.0))
            ref = None if ref_cons is None else ref_cons.map(
                lambda c: 1.0 if c is None else LOCATION_LOSS.get(rq.spec.key, 0.0))
        else:
            domain = _domain(q.spec, ref_cons if ref_cons is not None else cons[q.column])
            cur = cons[q.column].map(lambda c: _loss(c, domain))
            ref = None if ref_cons is None else ref_cons.map(lambda c: _loss(c, domain))
        losses.append(_relative(cur, ref).mean())
    return float(np.mean(losses))


def _relative(cur: pd.Series, ref: pd.Series | None) -> pd.Series:
    """Per record: the loss on top of what the original already lacked, rescaled to 0..1."""
    if ref is None:
        return cur
    ref = ref.reindex(cur.index).fillna(1.0).astype(float)
    cur = cur.astype(float)
    rel = ((cur - ref) / (1.0 - ref).where(ref < 1.0, 1.0)).clip(lower=0.0, upper=1.0)
    return rel.where(ref < 1.0, 0.0)


def _domain(spec: QidSpec, observed: pd.Series):
    if spec.kind == Kind.NUMERIC:
        # the range actually present in the original data; the catalogue's theoretical domain
        # (e.g. 1-2000 m²) would make every class look nearly free
        los = [c.lo for c in observed if isinstance(c, Range) and c.lo is not None]
        his = [c.hi for c in observed if isinstance(c, Range) and c.hi is not None]
        if los and his and max(his) > min(los):
            return (min(los), max(his))
        return spec.domain or (0, 1)
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
    assessment: object = None  # the Assessment behind the numbers, so nobody assesses it twice

    def row(self) -> dict:
        n = self.ok + self.at_risk + self.no_match
        return {"stap": self.description, "ok": self.ok, "risico": self.at_risk,
                "geen_match": self.no_match, "publiceerbaar_%": 100 * self.ok / n if n else 0.0,
                "k_mediaan": self.k_median, "informatieverlies": self.loss}


def _evaluate(desc, df, qids, original, population, threshold, scenario, unknown_matches,
              original_qids=None):
    a = assess(df, qids, population, threshold, scenario, unknown_matches=unknown_matches)
    st = a.records["status"]
    return Step(desc, df, qids, int((st == Status.OK).sum()), int((st == Status.AT_RISK).sum()),
                int((st == Status.NO_MATCH).sum()), a.summary()["k_mediaan"],
                information_loss(df, [q for q in qids if q.spec.knowledge <= scenario], original,
                                 reference_qids=original_qids),
                float(np.log(a.records["k"].clip(lower=1)).mean()) if len(df) else 0.0, a)


def tradeoff(df: pd.DataFrame, qids: list[QidColumn], population: Population,
             actions: Iterable[Action], threshold: Threshold = Threshold(),
             scenario: Knowledge = Knowledge.REGISTER, *,
             unknown_matches: bool = False) -> list[Step]:
    """Apply ``actions`` cumulatively; evaluate risk and information loss after each."""
    steps = [_evaluate("uitgangssituatie / baseline", df, qids, df, population, threshold,
                       scenario, unknown_matches, qids)]
    cur, cq = df, qids
    for act in actions:
        cur, cq = act.apply(cur, cq, population)
        steps.append(_evaluate(act.describe(), cur, cq, df, population, threshold, scenario,
                               unknown_matches, qids))
    return steps


def unit_of(spec: QidSpec) -> str:
    """The unit a class width is in, for texts: "jaar" for the construction year, else what the
    label ends with in brackets ("gebruiksoppervlakte [m²]" -> "m²")."""
    if spec.key == "bouwjaar":
        return "jaar"
    m = re.search(r"\[([^\]]+)\]\s*$", spec.label_nl)
    return m[1] if m else ""


def default_hierarchy(q: QidColumn) -> list[Action]:
    """Successively coarser actions for a QID, ending with suppression; numeric classes carry
    the unit of the QID for their description."""
    u = unit_of(q.spec)
    return [replace(a, unit=u) if isinstance(a, (Bin, Edges)) and u else a
            for a in _default_hierarchy(q)]


def _default_hierarchy(q: QidColumn) -> list[Action]:
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
    if key == "hoogte":
        return [Bin(c, 3.0), Bin(c, 6.0, above=12.0), Suppress(c)]
    if key == "bouwlagen":
        return [Bin(c, 2, origin=1, above=3), Suppress(c)]
    if key == "daktype":
        return [Group.of(c, {"plat", "plat_meerdere"}), Suppress(c)]
    if key == "uhi":
        return [Bin(c, 0.5), Bin(c, 1.0), Suppress(c)]
    if q.spec.kind == Kind.NUMERIC and not q.spec.integer:
        return [Suppress(c)]
    return [Suppress(c)]


def suggest(df: pd.DataFrame, qids: list[QidColumn], population: Population,
            threshold: Threshold = Threshold(), scenario: Knowledge = Knowledge.REGISTER, *,
            target_share: float = 1.0, max_steps: int = 20,
            hierarchies: Mapping[str, list[Action]] | None = None,
            unknown_matches: bool = False, progress=None) -> list[Step]:
    """Greedy search: repeatedly take the next hierarchy step that buys most publishable records
    per unit of information loss, until ``target_share`` of records passes or nothing helps.

    "Buys" counts newly passing records first; mean log(k) breaks the tie, so the search still
    moves when a record is unique on several attributes and no single step frees it.

    A heuristic, not an optimum; every step is shown so a human can stop earlier or pick
    differently. ``progress(fraction, text)``, when given, hears how far the search is: the share
    of the work done (assessments tried, out of an estimate of how many the search needs), never
    going back. Not the share of the target reached: a dataset that is nearly there would show a
    full bar for the whole, slow search.
    """
    active = [q for q in qids if q.spec.knowledge <= scenario]
    ladders = {q.column: list((hierarchies or {}).get(q.column) or default_hierarchy(q))
               for q in active}
    cur = _evaluate("uitgangssituatie / baseline", df, qids, df, population, threshold,
                    scenario, unknown_matches, qids)
    steps = [cur]
    n = len(df)
    # the work, estimated: one assessment per attribute per round, for at most as many rounds as
    # there are attributes (each round coarsens one), records still failing, or rungs left
    rounds = max(1, min(max_steps, len(ladders), n - cur.ok,
                        sum(len(ladder) for ladder in ladders.values())))
    work = 1 + rounds * max(len(ladders), 1)
    tried = 1

    def report(text: str) -> None:
        if progress is not None and n:
            progress(min(tried / work, 0.99), f"{text} · {cur.ok} van {n} publiceerbaar")

    report("uitgangssituatie getoetst")
    for _ in range(max_steps):
        if n == 0 or cur.ok / n >= target_share:
            break
        best, best_score, best_col, best_idx = None, -math.inf, None, 0
        for i, (col, ladder) in enumerate(ladders.items(), 1):
            # the first rung that helps at all; a finer rung may help nothing where a coarser does
            for idx, act in enumerate(ladder):
                report(f"ronde {len(steps)}, kenmerk {i} van {len(ladders)}: {act.describe()} "
                       "proberen")
                nxt_df, nxt_q = act.apply(cur.df, cur.qids, population)
                cand = _evaluate(act.describe(), nxt_df, nxt_q, df, population, threshold,
                                 scenario, unknown_matches, qids)
                tried += 1
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
        report(f"stap {len(steps) - 1}: {cur.description}")
    if progress is not None:
        progress(1.0, "klaar")
    return steps
