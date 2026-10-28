# SPDX-License-Identifier: EUPL-1.2
"""Bijlage voor de bronhouder: per te herleidbare woning de passende adressen. Uitvoer NIET publiceren.

Voegt de kandidatenlijsten van twee scenario's samen die de dataset beschrijven zoals hij nu
openbaar is: register + weerstation, en hetzelfde zonder energielabel (een aanvaller laat een
label dat niet bij het register past gewoon weg). Schrijft CSV en Parquet naast de uitvoer, in
data/ en dus buiten git.
"""
import sys
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parents[2] / "data/analyse/herleidbaarheid"
versie = sys.argv[1]
SCENARIOS = {
    "s2_register_met_weerstation": "register + weerstation, zoals gepubliceerd",
    "s2c_register_zonder_label": "idem, energielabel weggelaten door de aanvaller",
}

delen = []
for s, uitleg in SCENARIOS.items():
    c = pd.read_parquet(DATA / versie / f"uit_{s}" / "kandidaten_NIET_PUBLICEREN" /
                        "kandidaten.parquet")
    delen.append(c.assign(scenario=s, scenario_uitleg=uitleg))
b = pd.concat(delen, ignore_index=True)
# een woning die in beide scenario's valt, één keer tonen: met de kortste lijst
kortst = b.groupby("dataset_home_id__str")["k_populatie"].transform("min")
b = b[b["k_populatie"] == kortst]
b = b[b["scenario"] == b.groupby("dataset_home_id__str")["scenario"].transform("first")]
voor = ["dataset_home_id__str", "scenario", "scenario_uitleg", "k_populatie", "delta",
        "kandidaat_nr"]
b = b[voor + [c for c in b.columns if c not in voor + ["record", "status", "k"]]]
doel = DATA / versie / "bijlage_NIET_PUBLICEREN"
doel.mkdir(exist_ok=True)
b.to_csv(doel / "kandidaten_te_herleidbare_woningen.csv", index=False)
b.to_parquet(doel / "kandidaten_te_herleidbare_woningen.parquet", index=False)
print(f"{b['dataset_home_id__str'].nunique()} woningen, {len(b)} kandidaat-adressen -> {doel}")
print(b.groupby("dataset_home_id__str")["k_populatie"].first().value_counts().sort_index()
      .rename("woningen met zoveel kandidaten").to_string())
