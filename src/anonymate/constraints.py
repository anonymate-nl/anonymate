"""Constraints: what a published value tells an attacker about a dwelling.

A value in a published dataset is never "just a value" to an attacker; it is a *constraint* on the
population of dwellings that could have produced it. ``1974`` means "built in 1974", ``1960-1979``
means "built somewhere in 1960..1979", ``A|B`` means "label A or B", and an empty cell means
"anything".

Everything downstream (risk computation, generalisation, rendering) works on these three shapes,
so it does not matter whether the input dataset carried exact values, pre-binned classes or a mix.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Union


@dataclass(frozen=True)
class Range:
    """Closed interval ``[lo, hi]``; either bound may be ``None`` (open-ended)."""

    lo: float | None
    hi: float | None

    def __post_init__(self) -> None:
        if self.lo is not None and self.hi is not None and self.lo > self.hi:
            raise ValueError(f"empty range: {self.lo} > {self.hi}")

    def width(self) -> float:
        if self.lo is None or self.hi is None:
            return math.inf
        return self.hi - self.lo

    def contains(self, x: float) -> bool:
        return (self.lo is None or x >= self.lo) and (self.hi is None or x <= self.hi)

    def render(self) -> str:
        lo = _fmt(self.lo)
        hi = _fmt(self.hi)
        if self.lo is not None and self.lo == self.hi:
            return lo
        if self.lo is None:
            return f"<={hi}"
        if self.hi is None:
            return f">={lo}"
        return f"{lo}-{hi}"


@dataclass(frozen=True)
class OneOf:
    """The true value is one of ``values``."""

    values: frozenset[str]

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError("OneOf needs at least one value")

    @classmethod
    def of(cls, *values: str) -> "OneOf":
        return cls(frozenset(values))

    def render(self) -> str:
        return "|".join(sorted(self.values))


# ``None`` means: no information (missing value, or the attribute is suppressed).
Constraint = Union[Range, OneOf, None]


def _fmt(x: float | None) -> str:
    if x is None:
        return ""
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def render(c: Constraint) -> str:
    return "" if c is None else c.render()


_NUM = r"-?\d+(?:[.,]\d+)?"
_RANGE_RE = re.compile(rf"^\s*({_NUM})\s*(?:-|–|—|\.\.|t/m|tot en met|to)\s*({_NUM})\s*$", re.I)
_LE_RE = re.compile(rf"^\s*(?:<=|≤|=<|tot en met|t/m|max\.?|maximaal)\s*({_NUM})\s*$", re.I)
_LT_RE = re.compile(rf"^\s*(?:<|voor|vóór|before|tot)\s*({_NUM})\s*$", re.I)
_GE_RE = re.compile(rf"^\s*(?:>=|≥|=>|vanaf|from|min\.?|minimaal)\s*({_NUM})\s*$", re.I)
_GT_RE = re.compile(rf"^\s*(?:>|na|after)\s*({_NUM})\s*$", re.I)
_PLUS_RE = re.compile(rf"^\s*({_NUM})\s*\+\s*$")
_DECADE_RE = re.compile(r"^\s*(\d{3})0\s*'?s\s*$", re.I)  # 1960s


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def parse_numeric(value: object, *, integer: bool = True) -> Constraint:
    """Parse an exact number or a class such as ``115-124``, ``<1945``, ``>=250``, ``1960s``.

    With ``integer=True`` strict bounds are converted to inclusive ones (``<1945`` -> ``<=1944``),
    which is what we want for years and whole square metres.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Range(float(value), float(value))
    s = str(value).strip()
    if not s or s.lower() in {"nan", "na", "n/a", "none", "null", "onbekend", "unknown", "-", "?"}:
        return None
    step = 1.0 if integer else 0.0
    try:
        x = _num(s)
        return Range(x, x)
    except ValueError:
        pass
    if m := _RANGE_RE.match(s):
        return Range(_num(m[1]), _num(m[2]))
    if m := _LE_RE.match(s):
        return Range(None, _num(m[1]))
    if m := _LT_RE.match(s):
        return Range(None, _num(m[1]) - step)
    if m := _GE_RE.match(s):
        return Range(_num(m[1]), None)
    if m := _GT_RE.match(s):
        return Range(_num(m[1]) + step, None)
    if m := _PLUS_RE.match(s):
        return Range(_num(m[1]), None)
    if m := _DECADE_RE.match(s):
        start = float(m[1] + "0")
        return Range(start, start + 9)
    raise ValueError(f"cannot interpret {value!r} as a number or numeric class")


_SPLIT_RE = re.compile(r"\s*[|/;]\s*|\s+(?:of|or)\s+", re.I)


def parse_categorical(value: object, *, normalise=None) -> Constraint:
    """Parse ``C`` or ``A|B`` / ``A/B`` / ``A of B`` into :class:`OneOf`."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    s = str(value).strip()
    if not s or s.lower() in {"nan", "na", "n/a", "none", "null", "onbekend", "unknown", "-", "?"}:
        return None
    parts = [p for p in _SPLIT_RE.split(s) if p]
    if normalise is not None:
        parts = [normalise(p) for p in parts]
        parts = [p for p in parts if p is not None]
        if not parts:
            return None
    return OneOf(frozenset(parts))


def union(constraints: Iterable[Constraint]) -> Constraint:
    """Smallest constraint covering all of ``constraints`` (``None`` if any is unconstrained)."""
    cs = list(constraints)
    if not cs or any(c is None for c in cs):
        return None
    if all(isinstance(c, Range) for c in cs):
        los = [c.lo for c in cs]  # type: ignore[union-attr]
        his = [c.hi for c in cs]  # type: ignore[union-attr]
        lo = None if any(v is None for v in los) else min(los)  # type: ignore[type-var]
        hi = None if any(v is None for v in his) else max(his)  # type: ignore[type-var]
        return Range(lo, hi)
    if all(isinstance(c, OneOf) for c in cs):
        return OneOf(frozenset().union(*(c.values for c in cs)))  # type: ignore[union-attr]
    raise TypeError("cannot union numeric and categorical constraints")
