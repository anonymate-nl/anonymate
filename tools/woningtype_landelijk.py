"""Woningtype uit de vorm van het pand, landelijk getoetst tegen de NTA 8800-energielabels.

Vergelijkt voor alle woningen in de populatie met een EP-online-label volgens NTA 8800 (vanaf 2021)
het geregistreerde woningtype met het type dat AnonyMate uit de BAG-pandcontouren afleidt, met en
zonder de muurhoogte-regel (een gedeelde muur telt als buurmuur als minstens 2 m ervan minstens
4 m hoog is, 3D-BAG LoD1.3). De variant zonder muurhoogte wordt in een tijdelijke store berekend
uit dezelfde gedeelde muren; de echte store blijft onaangeroerd.

Gebruik::

    python tools/woningtype_landelijk.py --uit <map buiten de repo>

Schrijft alleen tellingen (geen adressen of woningen): ``landelijk.csv`` (kruistabel label x
afgeleid type per regel) en ``samenvatting.md``.
"""
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

import duckdb
import pandas as pd

from anonymate import store as st

TYPES = ("vrijstaand", "twee_onder_een_kap", "hoekwoning", "tussenwoning", "appartement")
VORM = ("CASE WHEN p.pand_woningen__0 > 1 THEN 'appartement' "
        "WHEN nb.buren__0 = 0 THEN 'vrijstaand' "
        "WHEN nb.blok_panden__0 = 2 THEN 'twee_onder_een_kap' "
        "WHEN nb.buren__0 = 1 THEN 'hoekwoning' "
        "WHEN nb.buren__0 >= 2 THEN 'tussenwoning' END")


def buren_zonder_muurhoogte(store: st.Store, tmp: Path) -> Path:
    """``bag_pand_buren.parquet`` zonder muurhoogte, in een tijdelijke store."""
    t = st.Store.open(tmp / "home", tmp / "downloads")
    for f in ("bag_pand_gevel.parquet", "bag_pand_muren.parquet"):
        shutil.copy(store.raw / f, t.raw / f)
    man = store.manifest()["sources"]
    t.record("bag_pand_gevel", **{k: v for k, v in man["bag_pand_gevel"].items() if k != "ingested"})
    t.record("bag_pand_buren", version=man["bag_pand_buren"]["version"])
    return st.neighbours_from_walls(t, progress=print)


def kruistabel(pop: Path, buren: Path, regel: str) -> pd.DataFrame:
    df = duckdb.connect().execute(f"""
        SELECT p.woningtype__cat AS label, {VORM} AS afgeleid, count(*) AS n
        FROM read_parquet('{pop.as_posix()}') p
        LEFT JOIN read_parquet('{buren.as_posix()}') nb ON nb.pand_id = p.pand_id__str
        WHERE p.woningtype_bron__cat = 'ep-online' AND p.nta8800__bool
        GROUP BY ALL""").df()
    df["afgeleid"] = df["afgeleid"].fillna("onbekend")
    df.insert(0, "regel", regel)
    return df


def samenvatting(tab: pd.DataFrame) -> str:
    rows = []
    for regel, d in tab.groupby("regel", sort=False):
        known = d[d.afgeleid != "onbekend"]
        juist = known[known.label == known.afgeleid].n.sum()
        per = {t: (known[(known.label == t) & (known.afgeleid == t)].n.sum()
                   / max(known[known.label == t].n.sum(), 1)) for t in TYPES}
        eengezins = known[known.label != "appartement"]
        rows.append({"regel": regel, "woningen": int(d.n.sum()), "zonder type": int(d.n.sum() - known.n.sum()),
                     "alle": juist / known.n.sum(),
                     "eengezins": (eengezins[eengezins.label == eengezins.afgeleid].n.sum()
                                   / eengezins.n.sum()),
                     **per})
    s = pd.DataFrame(rows)
    pct = lambda x: f"{100 * x:.1f}%".replace(".", ",")
    lines = ["| regel | woningen | alle | eengezins | " + " | ".join(TYPES) + " |",
             "|---|---:|---:|---:|" + "---:|" * len(TYPES)]
    for r in s.itertuples(index=False):
        d = r._asdict()
        lines.append(f"| {d['regel']} | {d['woningen']:,} | {pct(d['alle'])} | {pct(d['eengezins'])} | "
                     + " | ".join(pct(d[t]) for t in TYPES) + " |")
    # waar gaan de twee-onder-een-kappen heen
    tok = tab[tab.label == "twee_onder_een_kap"].pivot_table(index="regel", columns="afgeleid",
                                                              values="n", sort=False, fill_value=0)
    tok = tok.div(tok.sum(axis=1), axis=0)
    lines += ["", "Twee-onder-een-kap volgens het label, afgeleid als:", "",
              "| regel | " + " | ".join(tok.columns) + " |", "|---|" + "---:|" * len(tok.columns)]
    for regel, r in tok.iterrows():
        lines.append(f"| {regel} | " + " | ".join(pct(v) for v in r) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--uit", required=True, help="map voor de tellingen (buiten de repo)")
    args = ap.parse_args()
    uit = Path(args.uit)
    uit.mkdir(parents=True, exist_ok=True)
    store = st.Store.open()
    regel = store.manifest()["sources"]["bag_pand_buren"].get("muurhoogte", "?")
    with tempfile.TemporaryDirectory(dir=uit) as tmp:
        zonder = buren_zonder_muurhoogte(store, Path(tmp))
        tab = pd.concat([kruistabel(store.population_path, zonder, "zonder muurhoogte"),
                         kruistabel(store.population_path, store.raw / "bag_pand_buren.parquet",
                                    f"muurhoogte {regel}")])
    tab.to_csv(uit / "landelijk.csv", index=False)
    text = ("# Woningtype uit de vorm, landelijk tegen NTA 8800-labels\n\n"
            "Aandeel juist per type volgens het label (woningen met een afgeleid type).\n\n"
            + samenvatting(tab))
    (uit / "samenvatting.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
