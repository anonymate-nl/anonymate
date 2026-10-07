"""How a numeric column is read: rounded values and class boundaries (kladbloknotitie 17).

A published ``1965`` can mean "built in 1965", "built in 1963..1967" (rounded to the nearest 5) or
"built in 1965..1969" (rounded down, or a class labelled by its lower bound). Classes ``100-150``
and ``150-200`` share the boundary 150, which in reality belongs to only one of them. Neither is
visible in the values; it is in the codebook, if anywhere. Read wrongly, the first makes k far too
small (risk overestimated), the second a little too large (risk underestimated).

:func:`onderzoek` looks at the values of one column and proposes a :class:`Lezing`; the other
plausible readings are returned as alternatives, so the report can show whether the choice matters
("with rounding down: N publishable").
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from .constraints import Constraint, Range

DICHTSTBIJ = "dichtstbij"
BENEDEN = "beneden"
BOVEN = "boven"          # a shared boundary belongs to the class above
ONDER = "onder"          # ... to the class below

# rounding steps that are recognised, largest first; 2 is left out (half of all integers are even)
STAPPEN = (100, 50, 25, 10, 5)
MIN_DISTINCT = 3         # fewer distinct values say nothing: three multiples of 5 by chance: 1/125
NAAMHINT = ("afgerond", "rounded", "klasse", "class", "bin", "ca", "circa", "ongeveer", "approx")


@dataclass(frozen=True)
class Lezing:
    """What an attacker reads into a value, beyond the value itself.

    ``stap``: the values are rounded to this step (0: exact), ``richting`` says how. It widens
    every value, also classes made from rounded values later on (by binning): a class ``1960-1969``
    made of values rounded to the nearest 5 holds dwellings from 1958 to 1971.
    ``grens``: for classes that share a boundary, which class it belongs to; ``gedeeld`` holds those
    boundaries. Only for the classes as published: a column that AnonyMate rewrites into its own
    classes drops it (:meth:`na_herschrijven`).
    """

    stap: float = 0.0
    richting: str = DICHTSTBIJ
    grens: str = ""
    gedeeld: frozenset = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.stap < 0:
            raise ValueError(f"afrondstap kan niet negatief zijn: {self.stap:g}")
        if self.richting not in (DICHTSTBIJ, BENEDEN):
            raise ValueError(f"afronding {self.richting!r}: kies {DICHTSTBIJ} of {BENEDEN}")
        if self.grens not in ("", BOVEN, ONDER):
            raise ValueError(f"klassegrens {self.grens!r}: kies {BOVEN} of {ONDER}")

    @property
    def exact(self) -> bool:
        return not self.stap and not (self.grens and self.gedeeld)

    def apply(self, c: Constraint, integer: bool) -> Constraint:
        if not isinstance(c, Range) or self.exact:
            return c
        unit = 1.0 if integer else 0.0
        lo, hi = c.lo, c.hi
        if self.grens and self.gedeeld and lo is not None and hi is not None and lo < hi:
            if self.grens == BOVEN and hi in self.gedeeld:
                hi -= unit
            elif self.grens == ONDER and lo in self.gedeeld:
                lo += unit
        if self.stap:
            s = self.stap
            if self.richting == DICHTSTBIJ:     # [x - s/2, x + s/2): half up
                if lo is not None:
                    lo = math.ceil(lo - s / 2) if integer else lo - s / 2
                if hi is not None:
                    hi = math.ceil(hi + s / 2) - 1 if integer else hi + s / 2
            elif hi is not None:                # [x, x + s)
                hi = hi + s - unit
        return Range(lo, hi)

    def na_herschrijven(self) -> "Lezing | None":
        """The reading once AnonyMate has rewritten the column into classes of its own."""
        return Lezing(self.stap, self.richting) if self.stap else None

    def tekst(self) -> str:
        parts = []
        if self.stap:
            how = "naar het dichtstbij" if self.richting == DICHTSTBIJ else "naar beneden"
            parts.append(f"afgerond op {self.stap:g}, {how}")
        if self.grens and self.gedeeld:
            which = "erboven" if self.grens == BOVEN else "eronder"
            parts.append(f"gedeelde klassegrens hoort bij de klasse {which}")
        return "; ".join(parts) or "zoals gepubliceerd"


def uit_config(afronding=None, grens=None, gedeeld=frozenset()) -> Lezing | None:
    """A reading from the configuration: ``afronding`` is ``5``, ``"5"``, ``"5 beneden"`` or
    ``0`` (exact: no proposal), ``grens`` is ``"boven"``, ``"onder"`` or ``"beide"``. None when
    neither is given."""
    if afronding is None and grens is None:
        return None
    stap, richting = 0.0, DICHTSTBIJ
    if afronding is not None:
        words = str(afronding).replace(",", ".").split()
        try:
            stap = float(words[0]) if words else 0.0
        except ValueError:
            raise ValueError(f"afronding {afronding!r}: verwacht een stap, bijvoorbeeld 5 of "
                             f"'5 beneden'") from None
        if len(words) > 1:
            richting = words[1].lower()
    g = "" if grens in (None, "", "beide") else str(grens).lower()
    return Lezing(stap, richting, g, frozenset(gedeeld) if g else frozenset())


@dataclass
class Onderzoek:
    """What the values of one numeric column say about how to read them."""

    kolom: str
    integer: bool
    exact: int = 0                  # distinct exact values
    klassen: int = 0                # distinct classes (ranges with two different bounds)
    aansluitend: int = 0            # neighbouring classes that join (100-149, 150-199)
    raken: int = 0                  # ... that share a boundary (100-150, 150-200)
    gaten: int = 0                  # ... with a gap between them
    overlap: int = 0                # ... that overlap
    gedeeld: frozenset = field(default_factory=frozenset)
    voorbeelden: dict = field(default_factory=dict)   # kind -> "100-150 / 150-200"
    stap: float = 0.0               # all exact values are multiples of this
    naamhint: bool = False

    def voorstel(self) -> Lezing | None:
        """The default reading: rounded to the nearest step when the values look rounded; shared
        class boundaries are read as published (in both classes) until the user says otherwise."""
        return Lezing(self.stap, DICHTSTBIJ) if self.stap else None

    def alternatieven(self, gekozen: Lezing | None) -> list[Lezing]:
        """The other plausible readings, for the sensitivity line in the report."""
        gekozen = gekozen or Lezing()
        out = []
        if self.stap:
            for r in (DICHTSTBIJ, BENEDEN):
                alt = Lezing(self.stap, r, gekozen.grens, gekozen.gedeeld)
                if alt != gekozen:
                    out.append(alt)
            if gekozen.stap:
                out.append(Lezing(0.0, DICHTSTBIJ, gekozen.grens, gekozen.gedeeld))
        if self.raken and self.integer:
            for g in ("", BOVEN, ONDER):
                alt = Lezing(gekozen.stap, gekozen.richting, g, self.gedeeld if g else frozenset())
                if alt != gekozen:
                    out.append(alt)
        return out

    def meldingen(self) -> list[str]:
        out = []
        if self.stap:
            hint = " (de kolomnaam wijst er ook op)" if self.naamhint else ""
            out.append(f"{self.kolom}: alle {self.exact} verschillende waarden zijn veelvouden van "
                       f"{self.stap:g}{hint}; gelezen als afgerond op {self.stap:g} naar het "
                       f"dichtstbij. Rondt het codeboek naar beneden af (of noemt het alleen de "
                       f"ondergrens), kies dan 'beneden'.")
        if self.raken:
            out.append(f"{self.kolom}: {self.raken}× klassen die een grens delen (bijvoorbeeld "
                       f"{self.voorbeelden['raken']}); die grenswaarde telt nu in beide klassen "
                       f"mee. Zegt het codeboek bij welke klasse hij hoort, kies dan 'boven' of "
                       f"'onder'.")
        if self.gaten:
            out.append(f"{self.kolom}: {self.gaten}× een gat tussen klassen (bijvoorbeeld "
                       f"{self.voorbeelden['gaten']}); klopt dat met het codeboek?")
        if self.overlap:
            out.append(f"{self.kolom}: {self.overlap}× klassen die overlappen (bijvoorbeeld "
                       f"{self.voorbeelden['overlap']}); zijn er twee indelingen door elkaar "
                       f"gebruikt?")
        return out

    def regel(self) -> str:
        """One short line for a table cell in the window."""
        parts = []
        if self.stap:
            parts.append(f"veelvouden van {self.stap:g}: afgerond?")
        if self.raken:
            parts.append(f"{self.raken}× gedeelde klassegrens")
        if self.gaten:
            parts.append(f"{self.gaten}× gat tussen klassen")
        if self.overlap:
            parts.append(f"{self.overlap}× overlap")
        return "; ".join(parts)

    @property
    def iets_te_melden(self) -> bool:
        return bool(self.stap or self.raken or self.gaten or self.overlap)


def _fmt(x: float | None) -> str:
    return "" if x is None else (str(int(x)) if float(x).is_integer() else f"{x:g}")


def onderzoek(values: pd.Series, spec, *, tolerance: float = 0.0) -> Onderzoek:
    """Look at the distinct values of a numeric column (``spec`` a numeric
    :class:`~anonymate.qids.QidSpec`). Values that cannot be parsed are left out; the assessment
    reports them. With a ``tolerance`` of at least half a step (noise, or rounding the user already
    configured) no rounding is proposed for that step."""
    o = Onderzoek(str(values.name), spec.integer)
    o.naamhint = any(h in str(values.name).lower().replace("-", "_").split("_")
                     or (len(h) > 3 and h in str(values.name).lower()) for h in NAAMHINT)
    exact: set[float] = set()
    classes: set[tuple] = set()
    for v in pd.unique(values.dropna()):
        try:
            c = spec.parse(v)
        except (ValueError, TypeError):
            continue
        if not isinstance(c, Range):
            continue
        if c.lo is not None and c.lo == c.hi:
            exact.add(c.lo)
        else:
            classes.add((c.lo, c.hi))
    o.exact, o.klassen = len(exact), len(classes)
    if not classes and len(exact) >= MIN_DISTINCT:
        for s in STAPPEN:
            if tolerance >= s / 2:
                break
            if all(abs(x / s - round(x / s)) < 1e-9 for x in exact):
                o.stap = float(s)
                break
    unit = 1.0 if spec.integer else 0.0
    order = sorted(classes, key=lambda c: (-math.inf if c[0] is None else c[0],
                                           math.inf if c[1] is None else c[1]))
    shared = set()
    for a, b in zip(order, order[1:]):
        if a[1] is None or b[0] is None:
            kind = "overlap"
        elif b[0] == a[1] + unit and unit:
            kind = "aansluitend"
        elif b[0] == a[1]:
            kind = "raken" if unit else "aansluitend"
        elif b[0] > a[1]:
            kind = "gaten"
        else:
            kind = "overlap"
        setattr(o, kind, getattr(o, kind) + 1)
        if kind == "raken":
            shared.add(a[1])
        o.voorbeelden.setdefault(kind, f"{_label(a)} en {_label(b)}")
    o.gedeeld = frozenset(shared)
    return o


def _label(c: tuple) -> str:
    lo, hi = c
    if lo is None:
        return f"<={_fmt(hi)}"
    if hi is None:
        return f">={_fmt(lo)}"
    return f"{_fmt(lo)}-{_fmt(hi)}"


def gevoeligheid(df: pd.DataFrame, qids: list, population, threshold, scenario,
                 onderzoeken: dict[str, Onderzoek], *, unknown_matches: bool = False,
                 progress=None) -> list[dict]:
    """Per column with something to report: the reading used and, for each other plausible reading
    (one column at a time), how many records would be publishable. One assessment per
    alternative."""
    from dataclasses import replace

    from .risk import assess
    by_col = {q.column: q for q in qids}
    todo = [(col, o) for col, o in onderzoeken.items() if o.iets_te_melden and col in by_col]
    total = sum(len(o.alternatieven(by_col[col].lezing)) for col, o in todo) or 1
    done = 0
    out = []
    for col, o in todo:
        q = by_col[col]
        row = {"kolom": col, "lezing": (q.lezing or Lezing()).tekst(),
               "meldingen": o.meldingen(), "alternatieven": []}
        for alt in o.alternatieven(q.lezing):
            if progress:
                progress(done / total, f"andere lezing van {col}")
            other = [replace(x, lezing=None if alt.exact else alt) if x.column == col else x
                     for x in qids]
            a = assess(df, other, population, threshold, scenario,
                       unknown_matches=unknown_matches)
            row["alternatieven"].append({"lezing": alt.tekst(),
                                         "publiceerbaar": int(a.ok.sum())})
            done += 1
        out.append(row)
    return out


def markdown(rows: list[dict], publishable: int) -> str:
    """The section of the report: per column the reading and what another reading gives."""
    if not rows:
        return ""
    lines = ["## Lezing van de kolommen / how columns were read", "",
             "Afronding en klassegrenzen zijn niet aan de waarden te zien. Per kolom de gekozen "
             "lezing, en wat een andere lezing zou geven (de rest gelijk). Maakt de keuze veel "
             "uit, zoek het dan op in het codeboek.", "",
             f"*Rounding and class boundaries are not visible in the values; the alternatives show "
             f"whether the choice matters. Now publishable: {publishable}.*", ""]
    for r in rows:
        lines.append(f"- **{r['kolom']}**: {r['lezing']}")
        for m in r["meldingen"]:
            lines.append(f"  - {m}")
        for alt in r["alternatieven"]:
            lines.append(f"  - met {alt['lezing']}: {alt['publiceerbaar']} publiceerbaar "
                         f"(nu {publishable})")
    lines.append("")
    return "\n".join(lines)
