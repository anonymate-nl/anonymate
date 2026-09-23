"""Explanations that make a risk assessment readable for non-specialists.

Bits of information
    Singling out one dwelling among N takes log2(N) bits: 23 bits for the ~8 million Dutch
    dwellings, like the five yes/no questions that pick one face out of 24 in *Guess Who?*. Every
    quasi-identifier "answers questions": knowing the construction-year class leaves N/F_q
    dwellings, i.e. log2(N/F_q) bits. The report shows, per attribute, how many bits it gives
    away, and how many bits all attributes together leave to go.

Insiders per source
    A published time series is a fingerprint for whoever holds the same series: the grid operator
    and energy supplier for smart-meter data, the manufacturer's cloud for boiler, heat-pump or
    thermostat data. No register is needed for that attack, so no k can express it; the report
    names the parties instead.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .constraints import render
from .detect import Detection, Role, _name
from .population import Population
from .qids import Knowledge
from .risk import Assessment, QidColumn, _count_population, parse_constraints


@dataclass(frozen=True)
class Bits:
    column: str
    median: float
    maximum: float
    estimated: bool


def information_bits(df: pd.DataFrame, assessment: Assessment, population: Population, *,
                     unknown_matches: bool = False) -> tuple[float, list[Bits], pd.Series]:
    """(bits needed, bits per attribute, remaining bits per record).

    Per counted attribute the population is counted on that attribute alone; per estimated
    attribute the bits follow from the value's frequency in the dataset. Remaining bits per
    record: log2(k), what is still needed after everything the record reveals.
    """
    n = max(assessment.population_size, 1)
    needed = math.log2(n)
    cons = parse_constraints(df, assessment.qids)
    out: list[Bits] = []
    for q in assessment.qids:
        rendered = cons[q.column].map(render)
        known = rendered != ""
        if not known.any():
            continue
        if q.counted:
            reps = cons.loc[known, [q.column]].groupby(rendered[known]).head(1)
            keys = rendered.loc[reps.index]
            reps.index = range(len(reps))
            counts = _count_population(reps, [q], population, unknown_matches)
            per_value = dict(zip(keys, counts))
            f = rendered[known].map(per_value).astype(float)
            bits = np.log2(n / f.clip(lower=1))
        else:
            freq = rendered[known].map(rendered[known].value_counts()) / known.sum()
            bits = -np.log2(freq)
        out.append(Bits(q.column, float(bits.median()), float(bits.max()), not q.counted))
    remaining = np.log2(assessment.records["k"].clip(lower=1))
    return needed, out, remaining


# (pattern on the normalised column name, who holds the same series)
_INSIDERS: list[tuple[str, str]] = [
    (r"p1|dsmr|slimme_?meter|smart_?meter|(^|_)e_(consumed|delivered|net|import|export)|"
     r"(^|_)p_(consumed|delivered)|elektr|electric|stroom|(^|_)(v_)?gas|(^|_)g_",
     "netbeheerder en energieleverancier (slimme meter)"),
    (r"boiler|ketel|(^|_)cv(_|$)|thermostat|thermostaat|setpoint|(^|_)opentherm",
     "fabrikant van ketel of thermostaat (cloud-data)"),
    (r"heat_?pump|warmtepomp|(^|_)wp(_|$)|(^|_)hp(_|$)|compressor|(^|_)cop(_|$)",
     "warmtepompfabrikant (cloud-data)"),
    (r"(^|_)pv(_|$)|solar|zon_?pan|omvormer|inverter",
     "omvormerfabrikant of monitoringportaal zonnepanelen"),
    (r"(^|_)ev(_|$)|laadpaal|charge|charging|laadsessie", "exploitant van de laadpaal"),
    (r"kamstrup|warmtemeter|heat_?meter|(^|_)flow|debiet|aanvoer|retour",
     "leverancier of uitlezer van de warmtemeter"),
]


def insider_sources(detections: list[Detection]) -> dict[str, list[str]]:
    """Parties for whom published measurement columns are a fingerprint: {party: [columns]}."""
    out: dict[str, list[str]] = {}
    for d in detections:
        if d.role not in (Role.MEASUREMENT, Role.DIRECT, Role.DERIVED):
            continue
        n = _name(d.column)
        for pat, who in _INSIDERS:
            if re.search(pat, n):
                out.setdefault(who, []).append(d.column)
                break
    return out


def markdown(needed: float, bits: list[Bits], remaining: pd.Series,
             insiders: dict[str, list[str]], scenario: Knowledge) -> str:
    lines = ["## Hoeveel geeft elk kenmerk prijs? / information per attribute", "",
             f"Om één woning aan te wijzen in deze populatie zijn **{needed:.1f} bits** nodig "
             f"(log₂ van het aantal woningen). Elk kenmerk geeft een deel daarvan prijs:", "",
             "| kenmerk | bits (mediaan) | bits (maximaal) | |", "|---|---|---|---|"]
    for b in sorted(bits, key=lambda b: -b.median):
        lines.append(f"| {b.column} | {b.median:.1f} | {b.maximum:.1f} | "
                     f"{'geschat uit de dataset' if b.estimated else 'geteld in de registers'} |")
    lines += ["", f"Na alles wat een record prijsgeeft, resteren mediaan **{remaining.median():.1f} "
              f"bits** (minimaal {remaining.min():.1f}); 0 bits betekent: precies één woning. "
              "Kenmerken samen geven minder prijs dan de optelsom als ze samenhangen "
              "(bouwjaar en woningtype bijvoorbeeld).", ""]
    if insiders:
        lines += ["## Tijdreeksen en insiders / time series and insiders", "",
                  "Voor wie dezelfde meetreeks heeft, is een gepubliceerde reeks een vingerafdruk "
                  "die direct naar het adres leidt, los van alle woningkenmerken. Dat risico "
                  "drukt geen k uit:", ""]
        for who, cols in insiders.items():
            lines.append(f"- **{who}**: {', '.join(cols)}")
        if scenario < Knowledge.INSIDER:
            lines += ["", "*Dit valt buiten het gekozen aanvallersscenario; overweeg het "
                      "scenario `insider`, of publiceer reeksen grover in tijd of als verschil "
                      "in plaats van meterstand.*"]
        lines.append("")
    return "\n".join(lines)
