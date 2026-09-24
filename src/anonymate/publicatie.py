"""Publishing an address-based heat performance signature next to a dataset, safely.

The scenario: a monitoring dataset is published without addresses, but *with* a baseline
signature per dwelling that anyone could have derived from its address (see
:mod:`anonymate.signature`), so that a learned, data-driven signature can be compared
transparently with "what the address alone would have told you". The baseline algorithm is
published too.

That makes the published baseline an *exact* key for an attacker: he runs the same algorithm for
every dwelling, rounds the same way and looks up who falls in the same bucket. Rounding is the
privacy-utility trade-off; leaving out the dwellings that stay too identifiable is the other
lever. The order matters, ethically and legally:

1. fix the privacy norm ``p`` (maximum acceptable re-identification probability) first;
2. then assess;
3. then trade off rounding steps against precision, and dwellings left out against dwellings
   published, within that norm — never adjust the norm to the outcome.

Functions: :func:`add_baseline` adds the rounded baseline columns and the QIDs that describe
them; :func:`explore` assesses a grid of rounding steps.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Mapping

import numpy as np
import pandas as pd

from . import signature as sg
from .link import link
from .population import Population
from .qids import CATALOGUE, Knowledge
from .risk import QidColumn, Status, Threshold, assess

# published column name and unit per output
COLUMN = {"H": "adres_H__W_K_1", "C": "adres_C__Wh_K_1", "tau": "adres_tau__h",
          "Asol": "adres_Asol__m2", "Ainf": "adres_Ainf__cm2"}
# catalogue key per (method, output); Ainf is a national constant and no QID
_QID = {
    ("nta8800", "H"): "warmteverlies", ("mwa", "H"): "warmteverlies_mwa",
    ("best", "H"): "warmteverlies_best",
    ("nta8800", "tau"): "tijdconstante", ("mwa", "tau"): "tijdconstante_mwa",
    ("best", "tau"): "tijdconstante_best",
    ("nta8800", "Asol"): "zonnetoetreding", ("mwa", "Asol"): "zonnetoetreding_mwa",
    ("best", "Asol"): "zonnetoetreding_best",
}


def _qid_key(method: str, output: str) -> str | None:
    if method in ("ep", "passend"):   # label-based: its own columns, C included
        base = {"H": "warmteverlies", "C": "thermische_massa", "tau": "tijdconstante",
                "Asol": "zonnetoetreding"}.get(output)
        return f"{base}_{method}" if base else None
    if output == "C":
        return "thermische_massa"
    return _QID.get((method, output))


@dataclass(frozen=True)
class Plan:
    """Which baseline to publish, and how coarsely: ``steps`` maps an output (H, C, tau, Asol,
    Ainf) to its rounding step; outputs not in ``steps`` are not published."""

    method: str = "passend"
    steps: Mapping[str, float] = field(default_factory=lambda: {"H": 50.0, "C": 5000.0})

    def describe(self) -> str:
        parts = ", ".join(f"{o} per {s:g}" for o, s in self.steps.items())
        return f"adres-signatuur ({self.method}): {parts}"


def _round(values: pd.Series, step: float) -> pd.Series:
    # the same bucketing as the rainbow tables: floor(x/s + 0.5) * s
    return np.floor(values / step + 0.5) * step


def add_baseline(df: pd.DataFrame, population: Population, plan: Plan, *,
                 vbo_id: str | None = None, postcode: str | None = None,
                 huisnummer: str | None = None, huisletter: str | None = None,
                 toevoeging: str | None = None) -> tuple[pd.DataFrame, list[QidColumn], list[str]]:
    """Add the rounded address-based signature to ``df``.

    Returns the extended dataset, the QIDs of the published signature columns (tolerance =
    half the rounding step) and the columns that must never be published (address, BAG id).
    Dwellings that cannot be linked, or are not single-family, get empty values.
    """
    linked = link(df, population, vbo_id=vbo_id, postcode=postcode, huisnummer=huisnummer,
                  huisletter=huisletter, toevoeging=toevoeging)
    ids = linked["register_vbo_id"].dropna().astype(str).unique().tolist()
    have = [c for c in ["vbo_id"] + sg.INPUT if c in population.columns]
    cols = ", ".join(f'"{c}"' for c in have)
    inputs = population.con.execute(
        f"SELECT {cols} FROM {population.relation} WHERE list_contains(?, vbo_id)", [ids]
    ).fetchdf().drop_duplicates("vbo_id").set_index("vbo_id")
    sig = sg.compute(inputs, plan.method) if len(inputs) else \
        pd.DataFrame(columns=sg.OUTPUTS)
    out = df.copy()
    rows = linked["register_vbo_id"]
    qids: list[QidColumn] = []
    for output, step in plan.steps.items():
        col = COLUMN[output]
        values = rows.map(sig[output]) if len(sig) else pd.Series(np.nan, index=df.index)
        out[col] = _round(pd.to_numeric(values, errors="coerce"), float(step))
        key = _qid_key(plan.method, output)
        if key is not None and CATALOGUE[key].population_column not in population.columns:
            raise ValueError(
                f"de populatie heeft nog geen kolom {CATALOGUE[key].population_column!r} voor "
                f"methode {plan.method!r}: draai 'anonymate build --signaturen' / the population "
                f"lacks this signature column; run 'anonymate build --signaturen'")
        if key is not None:
            qids.append(QidColumn(col, CATALOGUE[key], tolerance=float(step) / 2))
    never = [c for c in (vbo_id, postcode, huisnummer, huisletter, toevoeging) if c]
    return out, qids, never


def precision_loss(df: pd.DataFrame, plan: Plan) -> float:
    """Mean relative rounding error of the published values (uniform within a step: s/√12)."""
    losses = []
    for output, step in plan.steps.items():
        v = pd.to_numeric(df.get(COLUMN[output]), errors="coerce").abs()
        v = v[v > 0]
        if len(v):
            losses.append(float((step / math.sqrt(12) / v).mean()))
    return float(np.mean(losses)) if losses else 0.0


def explore(df: pd.DataFrame, population: Population, method: str,
            candidates: Mapping[str, list[float]], threshold: Threshold,
            other_qids: list[QidColumn] = (), scenario: Knowledge = Knowledge.REGISTER, *,
            unknown_matches: bool = False, **link_kwargs) -> pd.DataFrame:
    """Assess every combination of rounding steps: how many dwellings can be published at the
    given norm, and how precise the published baseline is. Coarsest first is not assumed; the
    table is sorted by share publishable, then by precision."""
    names = list(candidates)
    rows = []
    for combo in itertools.product(*(sorted(candidates[n]) for n in names)):
        plan = Plan(method, dict(zip(names, combo)))
        extended, sig_qids, _ = add_baseline(df, population, plan, **link_kwargs)
        a = assess(extended, list(other_qids) + sig_qids, population, threshold, scenario,
                   unknown_matches=unknown_matches)
        st = a.records["status"]
        n = len(st) or 1
        rows.append({**{f"stap_{o}": s for o, s in plan.steps.items()},
                     "publiceerbaar": int((st == Status.OK).sum()),
                     "publiceerbaar_%": round(100 * (st == Status.OK).sum() / n, 1),
                     "niet_publiceren": int((st != Status.OK).sum()),
                     "k_mediaan": a.summary()["k_mediaan"],
                     "precisieverlies_%": round(100 * precision_loss(extended, plan), 1)})
    return pd.DataFrame(rows).sort_values(["publiceerbaar_%", "precisieverlies_%"],
                                          ascending=[False, True]).reset_index(drop=True)
