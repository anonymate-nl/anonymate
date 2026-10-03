"""Write the results of an assessment: publishable data, per-record report, summary.

Output directory layout::

    publiceerbaar.csv        records that pass, without direct identifiers   (to publish)
    rapport_per_record.csv   every record: class, k, δ, status, reasons      (internal!)
    samenvatting.json        machine-readable summary incl. source versions
    rapport.md               human-readable summary (Dutch + English)

``rapport_per_record.csv`` keeps the dataset's own row index so the data holder can trace
records; it is an internal document, not something to publish.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

import pandas as pd

from .risk import Assessment, Status


def publishable(df: pd.DataFrame, assessment: Assessment,
                drop_columns: Iterable[str] = ()) -> pd.DataFrame:
    """Records that passed, minus ``drop_columns`` (direct identifiers, linking columns)."""
    drop = [c for c in drop_columns if c in df.columns]
    return df.loc[assessment.ok].drop(columns=drop)


def write(out_dir: str | Path, df: pd.DataFrame, assessment: Assessment, *,
          drop_columns: Iterable[str] = (), steps: list | None = None,
          dataset_name: str = "dataset", population=None,
          unknown_matches: bool = False, target_share: float | None = None,
          progress=None) -> Path:
    """Write all outputs. With ``population`` the report also explains, per attribute, how many
    bits of information it gives away, and names insiders for published time series.
    ``progress(fraction, text)`` hears how far it is; counting the population per attribute takes
    most of the time."""
    from .voortgang import Voortgang
    vg = Voortgang(None, progress)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    vg.set(0.0, "publiceerbare woningen wegschrijven")
    pub = publishable(df, assessment, drop_columns)
    pub.to_csv(out / "publiceerbaar.csv", index=False)
    per = df[[q.column for q in assessment.qids]].join(assessment.records)
    per.to_csv(out / "rapport_per_record.csv", index_label="rij")
    summary = assessment.summary()
    summary.update({"dataset": dataset_name, "weggelaten_kolommen": sorted(set(drop_columns)
                    & set(df.columns)), "waarschuwingen": assessment.warnings})
    if steps:
        summary["stappen"] = [s.row() for s in steps]
        if target_share is not None:
            summary["doel_publiceerbaar"] = target_share
    text = markdown(summary, assessment)
    vg.set(0.05, "representativiteit")
    if len(df):
        # what leaving out records does to the published columns (kladbloknotitie 7)
        from . import representativiteit
        table = representativiteit.shift(df, assessment.ok, list(pub.columns))
        summary["representativiteit"] = table.to_dict("records")
        text += "\n" + representativiteit.markdown(table)
    if population is not None and len(df):
        from . import explain
        from .detect import detect
        needed, bits, remaining = explain.information_bits(
            df, assessment, population, unknown_matches=unknown_matches,
            progress=vg.stage(0.1, 0.95).callback())
        vg.set(0.95, "insiders zoeken")
        kept = df.drop(columns=[c for c in drop_columns if c in df.columns])
        insiders = explain.insider_sources(detect(kept), kept)
        summary["bits_nodig"] = round(needed, 2)
        summary["bits_per_kenmerk"] = {b.column: round(b.median, 2) for b in bits}
        median = remaining.median()          # NaN: no record has a match, so nothing to guess
        summary["bits_resterend_mediaan"] = None if pd.isna(median) else round(float(median), 2)
        summary["insiders"] = insiders
        text += "\n" + explain.markdown(needed, bits, remaining, insiders, assessment.scenario)
    (out / "samenvatting.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False,
                                                      default=str), encoding="utf-8")
    (out / "rapport.md").write_text(text, encoding="utf-8")
    vg.set(1.0, "rapport klaar")
    return out


def _fmt(x) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "–"
    if isinstance(x, float):
        return f"{x:.3g}"
    return str(x)


def markdown(summary: dict, assessment: Assessment) -> str:
    s = summary
    n = s["records"] or 1
    lines = [
        f"# Herleidbaarheidstoets / Re-identification risk: {s.get('dataset', '')}",
        "",
        "| | |",
        "|---|---|",
        f"| records | {s['records']} |",
        f"| publiceerbaar / publishable | {s['ok']} ({100 * s['ok'] / n:.0f}%) |",
        f"| risico / at risk | {s['risico']} |",
        f"| geen match in populatie / no match | {s['geen_match']} |",
        f"| drempel / threshold | p = {s['p']:g} → k ≥ {s['k_drempel']}, "
        f"δ ≤ {s['delta_drempel']:g} |",
        f"| k minimaal / mediaan (records met een match) | "
        f"{_fmt(s['k_min'])} / {_fmt(s['k_mediaan'])} |",
        f"| δ maximaal (records met een match) | {_fmt(s['delta_max'])} |",
        f"| aanvallersscenario / attacker | {s['scenario']} |",
        f"| quasi-identifiers | {', '.join(s['qids']) or '–'} |",
        f"| populatie / population | {s['populatie']:,} woningen ({s['afbakening']}) |",
        f"| bronnen / sources | {s['snapshot']} |",
        "",
    ]
    if s.get("weggelaten_kolommen"):
        lines += ["Niet in de publiceerbare dataset (directe identificatoren) / removed: "
                  + ", ".join(s["weggelaten_kolommen"]), ""]
    if assessment.warnings:
        lines += ["## Waarschuwingen / warnings", ""] + [f"- {w}" for w in assessment.warnings] \
            + [""]
    if s.get("stappen"):
        from .generalize import LOSS_NOTE
        lines += ["## Generalisatiestappen / generalisation steps", "",
                  "| stap | ok | risico | publiceerbaar | k mediaan | informatieverlies |",
                  "|---|---|---|---|---|---|"]
        for r in s["stappen"]:
            lines.append(f"| {r['stap']} | {r['ok']} | {r['risico']} | "
                         f"{r['publiceerbaar_%']:.0f}% | {_fmt(r['k_mediaan'])} | "
                         f"{r['informatieverlies']:.2f} |")
        if s.get("doel_publiceerbaar") is not None:
            lines += ["", f"Doel van de zoektocht / search target: {s['doel_publiceerbaar']:.0%} "
                          "publiceerbaar."]
        lines += ["", f"*{LOSS_NOTE}*", ""]
    reasons = assessment.records.loc[assessment.records["status"] != Status.OK, "redenen"]
    if len(reasons):
        lines += ["## Meest voorkomende redenen / most common reasons", ""]
        top = reasons.str.split("; ").explode().str.replace(r"=[\d.e+-]+", "=…", regex=True)
        for reason, count in top.value_counts().head(5).items():
            lines.append(f"- {count}× {reason}")
        lines.append("")
    lines += [
        "## Hoe te lezen / how to read",
        "",
        "- **k** is het aantal woningen in de populatie dat past bij wat een record prijsgeeft; "
        "de kans op juiste heridentificatie is 1/k.",
        "- **δ** is het deel van die woningen dat in de dataset zit: de kans dat een aanvaller "
        "terecht concludeert dat een woning meedoet.",
        "- Geschatte k (kenmerken zonder volledig register) is een schatting, geen telling.",
        "- *k counts matching dwellings in the population (re-identification chance 1/k); δ is "
        "the share of those dwellings present in the dataset (membership disclosure).*",
        "",
    ]
    return "\n".join(lines)
