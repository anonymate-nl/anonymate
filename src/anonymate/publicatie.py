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
them; :func:`explore` assesses a grid of rounding steps and reports the precision lost per
output (:func:`precision_losses`) next to their mean.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Mapping

import numpy as np
import pandas as pd

from . import signature as sg
from .namen import uitvoer_kolom
from .link import link
from .population import Population
from .qids import CATALOGUE, Knowledge
from .risk import QidColumn, Status, Threshold, assess

# published column name and unit per output
COLUMN = {"H": "adres_H__W_K_1", "C": "adres_C__Wh_K_1", "tau": "adres_tau__h",
          "Asol": "adres_Asol__m2", "Ainf": "adres_Ainf__cm2"}
# catalogue key per (method, output)
_QID = {
    ("nta8800", "H"): "warmteverlies", ("mwa", "H"): "warmteverlies_mwa",
    ("best", "H"): "warmteverlies_best",
    ("nta8800", "tau"): "tijdconstante", ("mwa", "tau"): "tijdconstante_mwa",
    ("best", "tau"): "tijdconstante_best",
    ("nta8800", "Asol"): "zonnetoetreding", ("mwa", "Asol"): "zonnetoetreding_mwa",
    ("best", "Asol"): "zonnetoetreding_best",
    ("nta8800", "Ainf"): "infiltratie", ("mwa", "Ainf"): "infiltratie_mwa",
    ("best", "Ainf"): "infiltratie_best",
}


def _qid_key(method: str, output: str) -> str | None:
    if method in ("ep", "passend", "passend_cbag"):   # label-based: own columns, C included
        base = {"H": "warmteverlies", "C": "thermische_massa", "tau": "tijdconstante",
                "Asol": "zonnetoetreding", "Ainf": "infiltratie"}.get(output)
        if base is None:
            return None
        if method == "passend_cbag" and output in ("H", "Asol"):
            return f"{base}_passend"                     # the same as passend
        return f"{base}_{method}"
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


def baseline_values(df: pd.DataFrame, population: Population, method: str, outputs, *,
                    vbo_id: str | None = None, postcode: str | None = None,
                    huisnummer: str | None = None, huisletter: str | None = None,
                    toevoeging: str | None = None) -> pd.DataFrame:
    """The unrounded address-based signature per dwelling of ``df``: one column per output, on
    the index of ``df``. Dwellings that cannot be linked, or are not single-family, get NaN."""
    linked = link(df, population, vbo_id=vbo_id, postcode=postcode, huisnummer=huisnummer,
                  huisletter=huisletter, toevoeging=toevoeging)
    ids = linked["register_vbo_id__str"].dropna().astype(str).unique().tolist()
    have = [c for c in ["vbo_id__str"] + sg.INPUT if c in population.columns]
    cols = ", ".join(f'"{c}"' for c in have)
    inputs = population.con.execute(
        f"SELECT {cols} FROM {population.relation} WHERE list_contains(?, vbo_id__str)", [ids]
    ).fetchdf().drop_duplicates("vbo_id__str").set_index("vbo_id__str")
    sig = sg.compute(inputs, method) if len(inputs) else         pd.DataFrame(columns=sg.OUTPUT_COLUMNS)
    rows = linked["register_vbo_id__str"]
    values = pd.DataFrame(index=df.index)
    for output in outputs:
        key = _qid_key(method, output)
        if key is not None and CATALOGUE[key].population_column not in population.columns:
            raise ValueError(
                f"de populatie heeft nog geen kolom {CATALOGUE[key].population_column!r} voor "
                f"methode {method!r}: draai 'anonymate build --signaturen' / the population "
                f"lacks this signature column; run 'anonymate build --signaturen'")
        mapped = rows.map(sig[uitvoer_kolom(output)]) if len(sig) else np.nan
        values[output] = pd.to_numeric(pd.Series(mapped, index=df.index), errors="coerce")
    return values


def _apply(df: pd.DataFrame, values: pd.DataFrame, plan: Plan
           ) -> tuple[pd.DataFrame, list[QidColumn]]:
    """``df`` with the baseline ``values`` rounded per ``plan``, and the QIDs describing them."""
    out = df.copy()
    qids: list[QidColumn] = []
    for output, step in plan.steps.items():
        out[COLUMN[output]] = _round(values[output], float(step))
        key = _qid_key(plan.method, output)
        if key is not None:
            qids.append(QidColumn(COLUMN[output], CATALOGUE[key], tolerance=float(step) / 2))
    return out, qids


def add_baseline(df: pd.DataFrame, population: Population, plan: Plan, *,
                 vbo_id: str | None = None, postcode: str | None = None,
                 huisnummer: str | None = None, huisletter: str | None = None,
                 toevoeging: str | None = None) -> tuple[pd.DataFrame, list[QidColumn], list[str]]:
    """Add the rounded address-based signature to ``df``.

    Returns the extended dataset, the QIDs of the published signature columns (tolerance =
    half the rounding step) and the columns that must never be published (address, BAG id).
    Dwellings that cannot be linked, or are not single-family, get empty values.
    """
    values = baseline_values(df, population, plan.method, list(plan.steps), vbo_id=vbo_id,
                             postcode=postcode, huisnummer=huisnummer, huisletter=huisletter,
                             toevoeging=toevoeging)
    out, qids = _apply(df, values, plan)
    never = [c for c in (vbo_id, postcode, huisnummer, huisletter, toevoeging) if c]
    return out, qids, never


def precision_losses(values: pd.DataFrame, plan: Plan) -> dict[str, float]:
    """Mean relative rounding error per published output: the expected error of rounding
    (uniform within a step: s/√12) relative to the *unrounded* value of each dwelling.

    Relative to the unrounded value, because a small output rounded with a coarse step (A_sol
    of 2 m² per 5 m²) mostly rounds to 0 or to the step itself; measured against the rounded
    value it would look precise, or drop out of the mean altogether."""
    losses = {}
    for output, step in plan.steps.items():
        v = pd.to_numeric(values.get(output), errors="coerce").abs()
        v = v[v > 0]
        if len(v):
            losses[output] = float((step / math.sqrt(12) / v).mean())
    return losses


def precision_loss(df: pd.DataFrame, plan: Plan, values: pd.DataFrame | None = None) -> float:
    """Mean of :func:`precision_losses` over the published outputs. Without the unrounded
    ``values``, the rounded columns of ``df`` stand in for them."""
    if values is None:
        values = pd.DataFrame({o: df.get(COLUMN[o]) for o in plan.steps}, index=df.index)
    losses = precision_losses(values, plan)
    return float(np.mean(list(losses.values()))) if losses else 0.0


def explore(df: pd.DataFrame, population: Population, method: str,
            candidates: Mapping[str, list[float]], threshold: Threshold,
            other_qids: list[QidColumn] = (), scenario: Knowledge = Knowledge.REGISTER, *,
            unknown_matches: bool = False, progress=None, **link_kwargs) -> pd.DataFrame:
    """Assess every combination of rounding steps: how many dwellings can be published at the
    given norm, and how precise the published baseline is. Coarsest first is not assumed; the
    table is sorted by share publishable, then by precision."""
    names = list(candidates)
    rows = []
    combos = list(itertools.product(*(sorted(candidates[n]) for n in names)))
    values = baseline_values(df, population, method, names, **link_kwargs)   # once, not per combo
    for i, combo in enumerate(combos):
        if progress is not None:
            progress(i / len(combos), f"afronding {i + 1} van {len(combos)}")
        plan = Plan(method, dict(zip(names, combo)))
        extended, sig_qids = _apply(df, values, plan)
        a = assess(extended, list(other_qids) + sig_qids, population, threshold, scenario,
                   unknown_matches=unknown_matches)
        st = a.records["status"]
        n = len(st) or 1
        rows.append({**{f"stap_{o}": s for o, s in plan.steps.items()},
                     "publiceerbaar": int((st == Status.OK).sum()),
                     "publiceerbaar_%": round(100 * (st == Status.OK).sum() / n, 1),
                     "niet_publiceren": int((st != Status.OK).sum()),
                     "k_mediaan": a.summary()["k_mediaan"],
                     "precisieverlies_%": round(100 * precision_loss(extended, plan, values), 1),
                     **{f"precisieverlies_{o}_%": round(100 * loss, 1)
                        for o, loss in precision_losses(values, plan).items()}})
    return pd.DataFrame(rows).sort_values(["publiceerbaar_%", "precisieverlies_%"],
                                          ascending=[False, True]).reset_index(drop=True)
