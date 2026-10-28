# SPDX-License-Identifier: EUPL-1.2
"""Representativiteit: hoeveel verschuift de dataset als de niet-publiceerbare woningen wegvallen?

Per scenario: de woningen met status 'ok' vormen het gepubliceerde deel. Per kenmerk de
totale-variatieafstand (TVD, categorieën) of het gestandaardiseerde verschil in gemiddelde (SMD,
getallen) tussen de hele dataset en het gepubliceerde deel. Uitleg in ../herleidbaarheid.md; de maat komt uit kladbloknotitie 8 van anonymate.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parents[2] / "data/analyse/herleidbaarheid"
versie = sys.argv[1]  # map met de uitvoer van draai.sh, genoemd naar de anonymate-versie
SCENARIOS = {
    "huidige publicatie, register + weerstation": "uit_s2_register_met_weerstation",
    "advies, register": "uit_s2b_staarten_grover",
    "advies, register + zichtbaar": "uit_s3b_zichtbaar_staarten_grover",
    "advies, insider (zonder jaarverbruik)": "uit_s4c_insider_zonder_verbruik",
}
CAT = ["woningtype__cat", "bouwjaar_klasse__cat", "oppervlak_klasse__cat", "energielabel__cat",
       "weerstation_nr"]
NUM = ["gas_voor_1__m3", "gas_voor_2__m3", "elektra_voor_1__kWh", "elektra_voor_2__kWh"]

alle = pd.read_csv(DATA / "dph_woningen.csv", dtype={"weerstation_nr": str})


def tvd(a: pd.Series, b: pd.Series) -> float:
    pa = a.fillna("(leeg)").value_counts(normalize=True)
    pb = b.fillna("(leeg)").value_counts(normalize=True)
    return 0.5 * float(pa.subtract(pb, fill_value=0).abs().sum())


def smd(a: pd.Series, b: pd.Series) -> float:
    return float((b.mean() - a.mean()) / a.std())


def tvd_toeval(a: pd.Series, n: int, herhalingen: int = 2000) -> float:
    """95e percentiel van de TVD bij het willekeurig weglaten van evenveel woningen."""
    codes, _ = pd.factorize(a.fillna("(leeg)"))
    m = codes.max() + 1
    p_alle = np.bincount(codes, minlength=m) / len(codes)
    rng = np.random.default_rng(0)
    uit = []
    for _ in range(herhalingen):
        deel = codes[rng.permutation(len(codes))[:n]]
        uit.append(0.5 * np.abs(np.bincount(deel, minlength=m) / n - p_alle).sum())
    return float(np.percentile(uit, 95))


rijen = []
for naam, map_ in SCENARIOS.items():
    r = pd.read_csv(DATA / versie / map_ / "rapport_per_record.csv")
    deel = alle.loc[r.loc[r["status"] == "ok", "rij"]]
    rij = {"scenario": naam, "gepubliceerd": len(deel), "weggelaten": len(alle) - len(deel)}
    for c in CAT:
        rij[f"TVD {c}"] = tvd(alle[c], deel[c])
        rij[f"toeval95 {c}"] = tvd_toeval(alle[c], len(deel)) if len(deel) < len(alle) else 0.0
    for c in NUM:
        rij[f"SMD {c}"] = smd(alle[c], deel[c])
    rijen.append(rij)

uit = pd.DataFrame(rijen)
uit.to_csv(DATA / versie / "representativiteit.csv", index=False)
with pd.option_context("display.width", 250, "display.max_columns", 50):
    print(uit.set_index("scenario").T.round(3).to_string())
