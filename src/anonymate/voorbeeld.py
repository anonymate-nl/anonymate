"""The practice data that ships with anonymate: fictitious dwellings, their weather, and the public
KNMI hourly data of the same two months, so everything can be tried without downloads.

Made by ``docs/voorbeeld/maak_voorbeeld.py``; see there for how the weather was derived (the
detective should find it: interpolation to H3 cell centres of level 4 after noise).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

HERE = Path(__file__).with_name("data") / "voorbeeld"
WONINGEN = HERE / "woningen.csv"
WEER = HERE / "weer.csv"
KEY = "woning_id"
NL = (3.2, 50.7, 7.3, 53.6)       # lon/lat box of the Netherlands


def available() -> bool:
    return WONINGEN.exists()


def hourly() -> pd.DataFrame:
    """KNMI hourly T and Q of the practice months (public KNMI data)."""
    return pd.read_parquet(HERE / "knmi_uur_voorbeeld.parquet")


def stations() -> pd.DataFrame:
    st = pd.read_parquet(HERE / "knmi_stations.parquet")
    st["knmi_station"] = st["knmi_station"].astype(str)
    return st


def grid(levels=(4, 5)):
    """Candidate cells for the detective without a population: every cell of the Dutch box."""
    import h3

    from .weerspoor import Grid
    x0, y0, x1, y1 = NL
    poly = h3.LatLngPoly([(y0, x0), (y0, x1), (y1, x1), (y1, x0)])
    return Grid(stations(), {lv: sorted(h3.polygon_to_cells(poly, lv)) for lv in levels})


def population() -> pd.DataFrame:
    """The made-up Netherlands of the practice mode: the synthetic population with made-up
    coordinates, in which the example dwellings carry their example postcodes (letters PostNL
    does not use), so linking them by address works as it would with real data."""
    from . import synthetic
    pop = synthetic.with_places(synthetic.population(200_000))
    drawn = synthetic.sample(pop, 60, seed=3, gemeente="Zwolle")   # as maak_voorbeeld.py did
    example = pd.read_csv(WONINGEN, dtype=str)
    postcode = dict(zip(drawn["vbo_id"], example["postcode"]))
    pop["postcode6"] = pop["vbo_id"].map(postcode).fillna(pop["postcode6"])
    return pop
