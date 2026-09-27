"""Maakt de verzonnen voorbeelddata om anonymate mee te oefenen.

* ``woningen.csv``: 60 woningen uit de synthetische populatie (het verzonnen Nederland van de
  oefenmodus en van ``--synthetic``, zelfde startwaarde), dus de toets tegen die populatie klopt.
  De postcodes eindigen op SA, SD of SS: die lettercombinaties gebruikt PostNL niet, dus geen enkel
  adres in dit bestand bestaat echt. ``woning_id`` koppelt aan het weer.
* ``weer.csv``: per woning de buitentemperatuur per uur, januari en februari 2024. Elke woning
  heeft haar plek in het verzonnen Nederland (``synthetic.with_places``); het weer is, zoals een
  dataset dat zou doen, met inverse afstandsweging (macht 2) uit echte KNMI-uurwaarden
  geïnterpoleerd naar het midden van de H3-cel van niveau 4 waarin die plek ligt, afgerond op
  0,1 °C. Zonder ruis: dan klopt de teruggeleide cel met de oefenpopulatie. De rechercheur hoort
  dat terug te vinden.
* ``knmi_uur_voorbeeld.parquet`` en ``knmi_stations.parquet``: de KNMI-uurwaarden (T, Q) en de
  stations van die twee maanden, openbare KNMI-gegevens, zodat oefenen zonder download kan.

De bestanden komen in ``docs/voorbeeld/`` (de csv's) en in het pakket
(``src/anonymate/data/voorbeeld/``, alles). Het weer vraagt de KNMI-uurgegevens van 2024 in de
lokale opslag: ``anonymate ingest knmi-uur --jaar 2024``.

    python docs/voorbeeld/maak_voorbeeld.py
"""
from pathlib import Path

import h3
import numpy as np
import pandas as pd

from anonymate import synthetic
from anonymate.store import Store
from anonymate.weerspoor import interpolate, load_hourly

HIER = Path(__file__).parent
PAKKET = HIER.parents[1] / "src" / "anonymate" / "data" / "voorbeeld"
PAKKET.mkdir(parents=True, exist_ok=True)

pop = synthetic.population(200_000)            # zoals de oefenmodus en `--synthetic`
ds = synthetic.sample(pop, 60, seed=3, gemeente="Zwolle")
rng = np.random.default_rng(3)
ds["postcode"] = ds["postcode4"] + rng.choice(["SA", "SD", "SS"], len(ds))
ds["woning_id"] = [f"W{i:02d}" for i in range(1, len(ds) + 1)]
cols = ["woning_id", "postcode", "huisnummer", "gemeente", "bouwjaar", "oppervlakte",
        "woningtype", "energielabel", "installatiedatum", "jaarverbruik_gas__m3"]
for folder in (HIER, PAKKET):
    ds[cols].to_csv(folder / "woningen.csv", index=False)

# the weather, as a dataset would derive it
store = Store.open()
hourly = load_hourly(store, [2024])
hourly = hourly[(hourly["time"] >= "2024-01-01") & (hourly["time"] < "2024-03-01")]
stations = pd.read_parquet(store.raw / "knmi_stations.parquet")
stations["knmi_station"] = stations["knmi_station"].astype(str)
hourly = hourly[hourly["station"].isin(stations["knmi_station"])]
wide = hourly.pivot_table(index="time", columns="station", values="T")
# each dwelling's place in the made-up Netherlands of the practice mode, so the traced
# weather cell and the practice population agree
places = synthetic.with_places(pop).set_index("vbo_id")
lat = places.loc[ds["vbo_id"], "lat"].to_numpy()
lon = places.loc[ds["vbo_id"], "lon"].to_numpy()
cells = [h3.latlng_to_cell(a, b, 4) for a, b in zip(lat, lon)]
points = np.array([h3.cell_to_latlng(c) for c in cells])
series = interpolate(wide, stations, points, power=2.0)
weer = pd.concat([pd.DataFrame({"woning_id": wid, "tijd": wide.index.strftime("%Y-%m-%dT%H:%MZ"),
                                "buitentemperatuur__degC": np.round(series[:, i], 1)})
                  for i, wid in enumerate(ds["woning_id"])], ignore_index=True)
for folder in (HIER, PAKKET):
    weer.to_csv(folder / "weer.csv", index=False)
hourly.to_parquet(PAKKET / "knmi_uur_voorbeeld.parquet", index=False)
stations.to_parquet(PAKKET / "knmi_stations.parquet", index=False)
print(f"{len(ds)} verzonnen woningen, {len(weer):,} weerwaarden, {len(hourly):,} KNMI-uurwaarden")
