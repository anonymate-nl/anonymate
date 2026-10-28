# SPDX-License-Identifier: EUPL-1.2
"""Invoer voor de herleidbaarheidstoets: een rij per woning, zoals de publieke dataset die prijsgeeft.

De DACS-HW-dataset publiceert per woning alleen `household_monthly` (pseudoniem plus maandtotalen
van stroom, teruglevering en gas). Uit die maandtotalen volgen drie kenmerken die een aanvaller kan
kennen of zien:

- `zonnepanelen__cat`   ja/nee: er is in minstens één maand elektriciteit teruggeleverd (zichtbaar).
- `gemeente__cat`      altijd Coevorden: de publieke locatie (eindrapport), hetzelfde voor elke woning;
                        AnonyMate heeft minstens één kenmerk nodig, en dit is wat de aanvaller al weet.
- `buitenunit__cat`     altijd ja: elke woning in de set heeft een hybride warmtepomp (zichtbaar;
                        een inclusiecriterium, geen onderscheidend kenmerk binnen de set).
- `gas_kw1__m3`, `elektra_kw1__kWh`  verbruik jan t/m mrt 2025, voor woningen met alle drie de
                        maanden (insider: leverancier, netbeheerder); plus afgeronde varianten
                        (klassen, en klassen met open staarten).

De uitvoer staat in uitvoer/ (gitignored) en bevat regels per woning; dit script print alleen
aantallen.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
UIT = Path(__file__).with_name("uitvoer")
UIT.mkdir(exist_ok=True)

h = pd.read_parquet(ROOT / "data/processed/household_monthly.parquet")
# Insiderkenmerk: verbruik in het eerste kwartaal van 2025 (jan t/m mrt), de maanden waarvoor de
# meeste woningen een volledige reeks hebben. Een leverancier of netbeheerder kent de maandstanden.
kwartaal = h[(h["maand_start"] >= "2025-01-01") & (h["maand_start"] <= "2025-03-01")]

per = h.groupby("custom_id__str").agg(
    maanden=("maand_start", "count"),
    teruglevering=("e_teruglevering_tot__kWh", lambda s: s.dropna().gt(0).any() if s.notna().any() else np.nan),
)
per["zonnepanelen__cat"] = per["teruglevering"].map({True: "ja", False: "nee"})
per["buitenunit__cat"] = "ja"
per["gemeente__cat"] = "Coevorden"   # publiek bekend uit het eindrapport; hetzelfde voor elke woning

som = kwartaal.groupby("custom_id__str").agg(
    n_e=("e_geleverd_tot__kWh", "count"), n_g=("g_geleverd_tot__m3", "count"),
    elektra=("e_geleverd_tot__kWh", "sum"), gas=("g_geleverd_tot__m3", "sum"),
)
per = per.join(som)
per["elektra_kw1__kWh"] = per["elektra"].where(per["n_e"] == 3).round(3)
per["gas_kw1__m3"] = per["gas"].where(per["n_g"] == 3).round(3)

def afronden(s: pd.Series, stap: int) -> pd.Series:
    """Naar een klasse met de breedte `stap`, in de schrijfwijze `[a - b]` die AnonyMate leest."""
    lo = (s // stap) * stap
    return lo.map(lambda x: "" if pd.isna(x) else f"[{int(x)} - {int(x) + stap - 1}]")

per["gas_kw1_klasse__m3"] = afronden(per["gas_kw1__m3"], 50)
per["elektra_kw1_klasse__kWh"] = afronden(per["elektra_kw1__kWh"], 250)
per["gas_kw1_grof__m3"] = afronden(per["gas_kw1__m3"], 100)
per["elektra_kw1_grof__kWh"] = afronden(per["elektra_kw1__kWh"], 500)

def met_staarten(s: pd.Series, stap: int, onder: int, boven: int) -> pd.Series:
    """Klassen met de breedte `stap`, behalve de uiterste: `<onder` en `boven=>` (open staarten)."""
    lo = (s // stap) * stap
    def tekst(x):
        if pd.isna(x):
            return ""
        if x < onder:
            return f"<{onder}"
        if x >= boven:
            return f"{boven}=>"
        return f"[{int(x)} - {int(x) + stap - 1}]"
    return lo.map(tekst)


per["gas_kw1_staart__m3"] = met_staarten(per["gas_kw1__m3"], 100, 100, 400)
per["elektra_kw1_staart__kWh"] = met_staarten(per["elektra_kw1__kWh"], 500, 1000, 2000)

kol = ["gemeente__cat", "zonnepanelen__cat", "buitenunit__cat", "gas_kw1__m3", "elektra_kw1__kWh",
       "gas_kw1_klasse__m3", "elektra_kw1_klasse__kWh", "gas_kw1_grof__m3", "elektra_kw1_grof__kWh",
       "gas_kw1_staart__m3", "elektra_kw1_staart__kWh"]
uit = per[kol].reset_index()
uit.to_csv(UIT / "dacs_hw_woningen.csv", index=False)

print(f"{len(uit)} woningen; zonnepanelen ja/nee/onbekend: "
      f"{(uit.zonnepanelen__cat=='ja').sum()}/{(uit.zonnepanelen__cat=='nee').sum()}/"
      f"{uit.zonnepanelen__cat.isna().sum()}")
print(f"verbruik jan-mrt 2025 bekend: gas {uit.gas_kw1__m3.notna().sum()}, "
      f"elektra {uit.elektra_kw1__kWh.notna().sum()}, beide "
      f"{(uit.gas_kw1__m3.notna() & uit.elektra_kw1__kWh.notna()).sum()}")
print(f"woningen met alle 15 maanden: {(per.maanden == 15).sum()}")
