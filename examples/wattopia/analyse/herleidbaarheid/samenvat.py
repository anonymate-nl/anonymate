# SPDX-License-Identifier: EUPL-1.2
"""Aggregeert de uitvoer van de toets tot tellingen van woningen per scenario en per k-klasse.

Leest uitvoer/<scenario>_<groep>/rapport_per_record.csv (regels per woning, gitignored) en schrijft
alleen tellingen naar uitvoer/samenvatting.md en samenvatting.json. Die tellingen gaan in
docs/herleidbaarheid.md; er staat niets per woning in.
"""
import json
import sys
from pathlib import Path

import pandas as pd

UIT = Path(__file__).with_name("uitvoer")
GROEPEN = ("gg", "pf", "onb")
KLASSEN = [("k < 11", 0, 11), ("k 11 tot 100", 11, 100), ("k 100 tot 1.000", 100, 1000),
           ("k 1.000 of meer", 1000, float("inf"))]


def lees(scenario: str) -> pd.DataFrame:
    delen = []
    for g in GROEPEN:
        pad = UIT / f"{scenario}_{g}" / "rapport_per_record.csv"
        if pad.exists():
            d = pd.read_csv(pad)
            inv = pd.read_csv(UIT / f"woningen_{g}.csv", dtype=str)
            d["woningen_project"] = inv.groupby("project")["project"].transform("size").to_numpy()
            d["groep"] = g
            delen.append(d)
    return pd.concat(delen, ignore_index=True)


def samenvat(d: pd.DataFrame) -> dict:
    n = len(d)
    ok = d.status == "ok"
    k_laag = (d.k < 11) & ~ok
    alleen_delta = ~ok & ~k_laag
    kl = {naam: int(((d.k >= lo) & (d.k < hi)).sum()) for naam, lo, hi in KLASSEN}
    return {
        "woningen": n, "haalt_norm": int(ok.sum()), "te_herleidbaar_k": int(k_laag.sum()),
        "alleen_delta_te_hoog": int(alleen_delta.sum()),
        "geen_match": int(d.k.isna().sum()),
        "k_klassen": kl, "k_min": float(d.k.min()), "k_mediaan": float(d.k.median()),
        "delta_max": float(d.delta.max()),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    scenarios = sorted({p.parent.name.rsplit("_", 1)[0] for p in UIT.glob("*/rapport_per_record.csv")})
    res = {s: samenvat(lees(s)) for s in scenarios}
    # s1 naar projectgrootte: waar zit het delta-probleem?
    d = lees("s1_register")
    d["grootte"] = pd.cut(d.woningen_project, [0, 10, 40, 1000], labels=["tot 10", "11 tot 40", "meer dan 40"])
    res["s1_naar_projectgrootte"] = {
        str(g): {"woningen": len(x), "haalt_norm": int((x.status == "ok").sum())}
        for g, x in d.groupby("grootte", observed=True)}
    (UIT / "samenvatting.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    regels = ["| scenario | woningen | haalt de norm | te herleidbaar (k<11) | alleen δ te hoog | k mediaan | δ max |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for s, r in res.items():
        if s.startswith("s1_naar"):
            continue
        regels.append(f"| {s} | {r['woningen']} | {r['haalt_norm']} | {r['te_herleidbaar_k']} | "
                      f"{r['alleen_delta_te_hoog']} | {r['k_mediaan']:,.0f} | {r['delta_max']:.3f} |")
    regels += ["", "k-klassen (woningen):", "", "| scenario | " + " | ".join(n for n, *_ in KLASSEN) + " |",
               "|---|" + "---:|" * len(KLASSEN)]
    for s, r in res.items():
        if not s.startswith("s1_naar"):
            regels.append(f"| {s} | " + " | ".join(str(v) for v in r["k_klassen"].values()) + " |")
    regels += ["", "s1 naar projectgrootte: " + json.dumps(res["s1_naar_projectgrootte"])]
    (UIT / "samenvatting.md").write_text("\n".join(regels) + "\n", encoding="utf-8")
    print("\n".join(regels))


if __name__ == "__main__":
    main()
