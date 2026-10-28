# SPDX-License-Identifier: EUPL-1.2
"""Telt per scenario hoeveel woningen in welke k-klasse vallen, uit `rapport_per_record.csv`.

Alleen aantallen (geaggregeerd); de regels per woning blijven in `uitvoer/`. Gebruik:
python samenvatting.py  (leest alle uitvoer/uit_*/rapport_per_record.csv, schrijft een
markdown-tabel naar stdout en naar uitvoer/k_klassen.md)
"""
import sys
from pathlib import Path

import pandas as pd

UIT = Path(__file__).resolve().parent / "uitvoer"
KLASSEN = [("k < 11", 0, 11), ("11 - 99", 11, 100), ("100 - 999", 100, 1000),
           ("1.000 of meer", 1000, float("inf"))]


def telling(d):
    mm = d["status"] == "geen_match"
    k = d.loc[~mm, "k"]
    rij = {nm: int(((k >= lo) & (k < hi)).sum()) for nm, lo, hi in KLASSEN}
    rij["geen match"] = int(mm.sum())
    rij["δ > 0,09"] = int((d.loc[~mm, "delta"] > 0.09).sum())
    rij["publiceerbaar"] = int((d["status"] == "ok").sum())
    rij["k mediaan"] = f"{k.median():,.0f}".replace(",", ".") if len(k) else "-"
    return rij


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rijen = {}
    for m in sorted(UIT.glob("uit_*")):
        f = m / "rapport_per_record.csv"
        if f.exists():
            rijen[m.name[4:]] = telling(pd.read_csv(f))
    t = pd.DataFrame(rijen).T
    t.index.name = "scenario"
    t = t.reset_index()
    md = "\n".join(["| " + " | ".join(map(str, t.columns)) + " |",
                    "|" + "---|" * len(t.columns)]
                   + ["| " + " | ".join(map(str, r)) + " |" for r in t.itertuples(index=False)])
    (UIT / "k_klassen.md").write_text(md + "\n", encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
