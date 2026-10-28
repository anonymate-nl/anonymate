# SPDX-License-Identifier: EUPL-1.2
"""Wat als de dataset het weer niet via het dichtstbijzijnde KNMI-station had gekoppeld, maar via
geospatiale interpolatie op de H3-cel (niveau 4) van de woning, met of zonder ruis?

De adressen zijn niet bekend, dus per record een verwachting: het record ligt met een kans
evenredig aan het aantal passende woningen in een gebied; de kans op risico is het gewogen
aandeel gebieden waar minder dan k woningen passen:  P = sum(n_u * [n_u < k]) / sum(n_u).
Passend = zelfde woningtype, bouwjaarklasse (20 jaar), oppervlakteklasse (50 m2) en label, zoals
in de toets van de huidige publicatie (register-aanvaller, strenge telling van onbekende waarden,
heel Nederland). delta is niet meegenomen (de dataset-aantallen per gebied zijn onbekend).

Gebieden: weerstationsgebied (dichtstbijzijnde van de KNMI-stations met temperatuur), H3-cel
niveau 4, en H3-cel met de zes buurcellen (bovengrens voor ruis van 5-10 km).
Controle: voor de weerstations is de werkelijke uitkomst bekend.
"""
from pathlib import Path

import duckdb
import h3
import numpy as np
import pandas as pd

from anonymate.store import Store

DATA = Path(__file__).resolve().parents[2] / "data/analyse/herleidbaarheid"
POP = Store.open().population_path.as_posix()
K = 11
TYPE = {"vrijstaand": "vrijstaand", "2-onder-1-kap": "twee_onder_een_kap",
        "tussenwoning": "tussenwoning", "hoekwoning": "hoekwoning", "appartement": "appartement"}


def bj_klasse(s: str):
    if pd.isna(s):
        return None
    if s.startswith("<"):
        return -1
    if s.endswith("=>"):
        return 99
    return (int(s.strip("[]").split("-")[0]) - 1900) // 20


def opp_klasse(s: str):
    if pd.isna(s):
        return None
    if s.endswith("=>"):
        return 10
    return int(s.strip("[]").split("-")[0].strip()) // 50


d = pd.read_csv(DATA / "dph_woningen.csv", dtype=str)
rec = pd.DataFrame({"type": d["woningtype__cat"].map(TYPE),
                    "bj": d["bouwjaar_klasse__cat"].map(bj_klasse),
                    "opp": d["oppervlak_klasse__cat"].map(opp_klasse),
                    "label": d["energielabel__cat"], "station": d["weerstation_nr"]})

con = duckdb.connect()
con.execute("SET memory_limit='1GB'")
# een populatie van na de naamconventie van anonymate heeft de eenheid of het type achter de naam
# (woningtype__cat): onder de oude namen lezen
OUD = ["knmi_station", "h3_r4", "woningtype", "bouwjaar", "oppervlakte", "energielabel"]
kolommen = set(con.execute(f"DESCRIBE SELECT * FROM read_parquet('{POP}')").df()["column_name"])
if "woningtype" not in kolommen:
    from anonymate.namen import OUD_NAAR_NIEUW
    sel = ", ".join(f"{OUD_NAAR_NIEUW[c]} AS {c}" for c in OUD)
    con.execute(f"CREATE VIEW pop AS SELECT {sel} FROM read_parquet('{POP}')")
else:
    con.execute(f"CREATE VIEW pop AS SELECT * FROM read_parquet('{POP}')")
agg = con.execute("""
    SELECT knmi_station AS station, h3_r4 AS cel, woningtype AS type,
           CASE WHEN bouwjaar < 1900 THEN -1 WHEN bouwjaar >= 2000 THEN 99
                ELSE (bouwjaar - 1900) // 20 END AS bj,
           CASE WHEN oppervlakte >= 500 THEN 10 ELSE oppervlakte // 50 END AS opp,
           upper(substr(energielabel, 1, 1)) AS label, count(*) AS n
    FROM pop WHERE h3_r4 IS NOT NULL GROUP BY ALL""").df()
agg["label"] = agg["label"].where(agg["label"].isin(list("ABCDEFG")))


def passend(r) -> pd.Series:
    m = pd.Series(True, index=agg.index)
    for kol in ("type", "bj", "opp", "label"):
        if pd.notna(r[kol]):
            m &= agg[kol] == (r[kol] if kol in ("type", "label") else float(r[kol]))
    return m


def p_risico(n: pd.Series) -> float:
    n = n[n > 0]
    return float((n * (n < K)).sum() / n.sum()) if n.sum() else np.nan


uit = []
for i, r in rec.iterrows():
    m = passend(r)
    per_station = agg[m].groupby("station")["n"].sum()
    per_cel = agg[m].groupby("cel")["n"].sum()
    ring = pd.Series({c: sum(per_cel.get(x, 0) for x in h3.grid_disk(c, 1)) for c in per_cel.index})
    werkelijk = per_station.get(r["station"], 0) if pd.notna(r["station"]) else np.nan
    uit.append({"station, verwacht": p_risico(per_station), "H3 r4, verwacht": p_risico(per_cel),
                "H3 r4 + ruis, verwacht": p_risico(ring),
                "station, werkelijk": float(0 < werkelijk < K) if pd.notna(werkelijk) else np.nan,
                "station, werkelijk geen match": float(werkelijk == 0) if pd.notna(werkelijk) else np.nan})
t = pd.DataFrame(uit)
t.to_csv(DATA / "weerlocatie_alternatieven.csv", index=False)
print(f"{len(t)} records; verwacht aantal met risico (k < {K}), som van de kansen:")
for c in t.columns:
    print(f"  {c:32s} {t[c].sum():6.1f}")
print("records met kans op risico > 50%:",
      {c: int((t[c] > 0.5).sum()) for c in t.columns if "verwacht" in c})
