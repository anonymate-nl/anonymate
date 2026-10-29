# SPDX-License-Identifier: EUPL-1.2
"""Invoer voor de herleidbaarheidstoets: één rij per woning, zoals de dataset ze openbaar maakt.

Bron: `resultaten.parquet` uit de uitvoer van de preprocessing (212 woningen). Alleen die tabel
bevat woningkenmerken; `boiler_temp`, `thermostat_temp` en `etmaal` hebben er geen.

Gebruik: python maak_invoer.py <uitvoermap van de preprocessing>
(of zet de omgevingsvariabele WARMINGUP_UITVOER). Schrijft naar `uitvoer/` naast dit script;
die map staat in .gitignore, want het bestand heeft een regel per woning.

Afgeleid, met de aannames erbij:
- `bouwjaar_klasse`: de smalste klasse uit `bouwjaar_klasse__cat` en
  `bouwjaar_klasse_eindrapport__cat` (beide staan in de dataset; een aanvaller gebruikt allebei).
- `vermogen_kW`: geïnstalleerd radiatorvermogen (75/65/20 °C), W omgerekend naar kW.
- `H_model__W_K_1` = 1 / (R_ie + R_ea): de warmteoverdrachtscoëfficiënt van het 2R2C-model
  (binnen-schil plus schil-buiten in serie). Aanname van deze toets, niet van Deltares.
- `C_model__Wh_K_1` = (C_i + C_e) / 3600: bron-eenheid J/K (de brontabel zegt J/C; het eindrapport
  Wh/C, zie docs/datacatalogus.md §5.5). Dat de getallen J/K zijn, volgt uit de grootte-orde.
"""
import math
import os
import re
import sys
from pathlib import Path

import pandas as pd

HIER = Path(__file__).resolve().parent
UIT = HIER / "uitvoer"
INF = math.inf


def bereik(label):
    """Klasse als tekst -> (laagste, hoogste) jaar of m2; None bij een lege cel."""
    if label is None or (isinstance(label, float) and math.isnan(label)):
        return None
    s = str(label).strip().lower()
    if m := re.fullmatch(r"(\d+)\s*-\s*(\d+)", s):
        return float(m[1]), float(m[2])
    if m := re.fullmatch(r"(?:<|voor)\s*(\d+)", s):
        return -INF, float(m[1]) - 1
    if m := re.fullmatch(r"(?:na|>)\s*(\d+)", s):
        return float(m[1]) + 1, INF
    raise ValueError(f"klasse niet te lezen: {label!r}")


def smalste(a, b):
    """Doorsnede van twee klassen; bij tegenstrijdigheid de eerste (geteld als bevinding)."""
    ra, rb = bereik(a), bereik(b)
    if ra is None:
        return b if rb is not None else None, False
    if rb is None:
        return a, False
    lo, hi = max(ra[0], rb[0]), min(ra[1], rb[1])
    if lo > hi:
        return a, True
    if lo == -INF:
        return f"<={int(hi)}", False
    if hi == INF:
        return f">={int(lo)}", False
    return f"{int(lo)}-{int(hi)}", False


def main():
    bron = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ["WARMINGUP_UITVOER"])
    r = pd.read_parquet(bron / "resultaten.parquet")
    uit = pd.DataFrame({"home_id__str": r["home_id__str"], "woningtype": r["woningtype__cat"]})
    paren = [smalste(a, b) for a, b in zip(r["bouwjaar_klasse__cat"],
                                           r["bouwjaar_klasse_eindrapport__cat"])]
    uit["bouwjaar_klasse"] = [p[0] for p in paren]
    uit["bouwjaar_grof"] = r["bouwjaar_klasse_eindrapport__cat"]
    uit["oppervlakte_klasse"] = r["oppervlak_klasse__cat"]
    uit["jaarverbruik_gas__m3"] = r["g_jaarverbruik_indicatief__m3"]
    uit["vermogen__kW"] = r["p_afgifte_geinstalleerd__W"] / 1000
    uit["H_model__W_K_1"] = 1 / (r["r_binnen_schil__K_W_1"] + r["r_schil_buiten__K_W_1"])
    uit["C_model__Wh_K_1"] = (r["c_binnen__J_K_1"] + r["c_schil__J_K_1"]) / 3600
    UIT.mkdir(exist_ok=True)
    uit.to_csv(UIT / "wu_woningen.csv", index=False)
    print(f"{len(uit)} woningen -> {UIT / 'wu_woningen.csv'}")
    print(f"tegenstrijdige bouwjaarklassen: {sum(p[1] for p in paren)}")
    for k in ["woningtype", "bouwjaar_klasse", "oppervlakte_klasse", "jaarverbruik_gas__m3",
              "vermogen__kW", "H_model__W_K_1"]:
        print(f"{k}: {uit[k].notna().sum()} ingevuld, {uit[k].nunique()} verschillende waarden")


if __name__ == "__main__":
    main()
