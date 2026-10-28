# SPDX-License-Identifier: EUPL-1.2
"""Aanvulling op de k-map-toets: hoeveel postcodegebieden (PC4) komen in aanmerking voor een project?

De toets telt woningen. Een aanvaller zoekt echter een **blok** woningen: alle woningen van een
project delen bouwjaar, oppervlak, type en weerstation. Wie weet hoeveel woningen het project telt
(minimaal het aantal woningen met monitoring), zoekt postcodegebieden waar ten minste zoveel
woningen met die kenmerken staan. Hoe minder gebieden, hoe scherper de aanwijzing.

Alleen het register wordt gebruikt (populatie van anonymate, alleen gelezen). Schrijft per projectgroep
naar uitvoer/kandidaatgebieden.csv (gitignored); in de documentatie staan alleen samenvattende
aantallen.
"""
import sys
from pathlib import Path

import pandas as pd
from anonymate.store import Store

UIT = Path(__file__).with_name("uitvoer")
# eerste argument: "" (afgerond op 5, zoals gepubliceerd) of "_advies" (op 10 jaar en 20 m2)
SUFFIX = sys.argv[1] if len(sys.argv) > 1 else ""
bron = pd.concat([pd.read_csv(UIT / f"woningen_{g}.csv", dtype=str) for g in ("gg", "pf")])
pop = Store.open().population()

bron = bron.rename(columns={f"bouwjaar{SUFFIX}": "bj", f"oppervlak{SUFFIX}": "opp"})
per_project = bron.groupby(["project", "groep", "station", "bj", "opp"]).size()
per_project = per_project.rename("woningen_project").reset_index()

rijen = []
for r in per_project.itertuples():
    lo, hi = (int(x) for x in r.bj.split("-"))
    alo, ahi = (int(x) for x in r.opp.split("-"))
    gg = "true" if r.groep == "gg" else "false"
    q = f"""select postcode4__str pc4, count(*) n from population
            where knmi_station__cat = '{r.station}' and bouwjaar__yr between {lo} and {hi}
              and oppervlakte__m2 between {alo} and {ahi} and eengezins__bool = {gg}
            group by 1"""
    d = pop.con.execute(q).df()
    rijen.append(dict(
        project=r.project, woningen_project=r.woningen_project, groep=r.groep,
        pc4_met_match=len(d), pc4_met_minstens_projectgrootte=int((d.n >= r.woningen_project).sum()),
        pc4_met_minstens_helft=int((d.n >= r.woningen_project / 2).sum()),
        woningen_match=int(d.n.sum())))
uit = pd.DataFrame(rijen)
uit.to_csv(UIT / f"kandidaatgebieden{SUFFIX}.csv", index=False)
print(uit.sort_values("woningen_project").to_string(index=False))
