# SPDX-License-Identifier: EUPL-1.2
"""Invoer voor de herleidbaarheidstoets: één rij per woning, zoals die gepubliceerd zou worden.

Woningkenmerken uit homes.parquet, plus het weerstation per woning uit knmi.csv (de ruwe dataset
publiceert per woning de uurreeks van het dichtstbijzijnde station, en dus impliciet de regio).
"""
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
UIT = ROOT / "data/analyse/herleidbaarheid"
homes = pd.read_parquet(ROOT / "data/processed/homes.parquet")

stations = set()
with zipfile.ZipFile(ROOT / "data/raw/dph-dataset.zip") as z:
    with z.open("knmi.csv") as f:
        for chunk in pd.read_csv(f, usecols=["location_id", "station_code"], dtype=str,
                                 chunksize=500_000):
            pairs = chunk[["location_id", "station_code"]].drop_duplicates()  # usecols keeps
            stations |= set(map(tuple, pairs.itertuples(index=False)))       # file order
st = pd.DataFrame(sorted(stations), columns=["home_id__str", "weerstation_nr"])
per_home = st.groupby("home_id__str")["weerstation_nr"].agg(lambda s: "|".join(sorted(set(s))))

df = homes.merge(per_home, left_on="home_id__str", right_index=True, how="left")
UIT.mkdir(parents=True, exist_ok=True)
out = UIT / "dph_woningen.csv"
df.to_csv(out, index=False)
print(f"{len(df)} woningen, {df['weerstation_nr'].notna().sum()} met weerstation, "
      f"{(df['weerstation_nr'].str.contains('[|]', na=False)).sum()} met meer dan één station")
print(df["weerstation_nr"].value_counts().head(8).to_string())
print(f"-> {out}")
