"""Maakt docs/voorbeeld/woningen.csv: een kleine, verzonnen dataset om anonymate mee te proberen.

60 woningen uit de synthetische populatie die `--synthetic` ook gebruikt (zelfde startwaarde), dus
de toets tegen die populatie klopt. De postcodes eindigen op SA, SD of SS: die lettercombinaties
gebruikt PostNL niet, dus geen enkel adres in dit bestand bestaat echt.

    python docs/voorbeeld/maak_voorbeeld.py
"""
from pathlib import Path

import numpy as np

from anonymate import synthetic

pop = synthetic.population(200_000)            # zoals `anonymate ... --synthetic`
ds = synthetic.sample(pop, 60, seed=3, gemeente="Zwolle")
rng = np.random.default_rng(3)
ds["postcode"] = ds["postcode4"] + rng.choice(["SA", "SD", "SS"], len(ds))
cols = ["postcode", "huisnummer", "gemeente", "bouwjaar", "oppervlakte", "woningtype",
        "energielabel", "installatiedatum", "jaarverbruik_gas__m3"]
out = Path(__file__).with_name("woningen.csv")
ds[cols].to_csv(out, index=False)
print(f"{len(ds)} verzonnen woningen -> {out}")
