"""The practice data that ships with anonymate: fictitious dwellings, their weather, and the public
KNMI hourly data of the same two months, so everything can be tried without downloads.

Made by ``docs/voorbeeld/maak_voorbeeld.py``; see there for how the weather was derived (the
detective should find it: interpolation to the centre of each dwelling's H3 cell of level 4).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .tabel import lees_parquet

HERE = Path(__file__).with_name("data") / "voorbeeld"
WONINGEN = HERE / "woningen.csv"
WEER = HERE / "weer.csv"
KEY = "woning_id"
NL = (3.2, 50.7, 7.3, 53.6)       # lon/lat box of the Netherlands


def available() -> bool:
    return WONINGEN.exists()


def hourly() -> pd.DataFrame:
    """KNMI hourly T and Q of the practice months (public KNMI data)."""
    return lees_parquet(HERE / "knmi_uur_voorbeeld.parquet")


def stations() -> pd.DataFrame:
    st = lees_parquet(HERE / "knmi_stations.parquet")
    st["knmi_station"] = st["knmi_station"].astype(str)
    return st


def grid(levels=(4, 5)):
    """Candidate cells for the detective without a population: every cell of the Dutch box."""
    import h3

    from .weerspoor import Grid
    x0, y0, x1, y1 = NL
    poly = h3.LatLngPoly([(y0, x0), (y0, x1), (y1, x1), (y1, x0)])
    return Grid(stations(), {lv: sorted(h3.polygon_to_cells(poly, lv)) for lv in levels})


# Two small, sparsely populated areas added to the made-up Netherlands, each with one example
# dwelling, so practice shows where rare places make a dwelling stand out: the H3 cell of level 4
# on the North Holland coast that is mostly sea (really ~2,650 single-family homes; here 1:40),
# and the area of KNMI station 242 Vlieland. Postcodes end in SA, SD or SS, like the others.
KUSTCEL = "8419681ffffffff"
AREAS = (
    {"gemeente": "Schagen", "provincie": "Noord-Holland", "postcode4": "1759",
     "centre": (52.83, 4.70), "km": 2.5, "n": 65, "seed": 11},
    {"gemeente": "Vlieland", "provincie": "Friesland", "postcode4": "8899",
     "centre": (53.296, 5.075), "km": 0.6, "n": 15, "seed": 12},
)


def _in_area(area: dict, lat: float, lon: float) -> bool:
    import h3
    if area["gemeente"] == "Schagen":
        coast = 4.65 + (lat - 52.766) * 0.55          # rough coastline Petten - Julianadorp
        return h3.latlng_to_cell(lat, lon, 4) == KUSTCEL and lon >= coast
    return 53.28 <= lat <= 53.31 and 5.03 <= lon <= 5.11     # Vlieland village


def extra_areas() -> pd.DataFrame:
    """The dwellings of the two added areas, with places and H3 cells (deterministic)."""
    import h3
    import numpy as np

    from . import synthetic
    frames = []
    for i, area in enumerate(AREAS):
        rng = np.random.default_rng(area["seed"])
        base = synthetic.population(area["n"] * 20, seed=area["seed"])
        la0, lo0 = area["centre"]
        lat = np.round(la0 + rng.normal(0, area["km"], len(base)) / 111.0, 5)
        lon = np.round(lo0 + rng.normal(0, area["km"], len(base)) / 68.0, 5)
        keep = np.array([_in_area(area, a, b) for a, b in zip(lat, lon)])
        part = base[keep].head(area["n"]).reset_index(drop=True)
        part["lat"], part["lon"] = lat[keep][:len(part)], lon[keep][:len(part)]
        part["vbo_id"] = [f"00000{20 + i}{j:09d}" for j in range(len(part))]
        part["gemeente"], part["provincie"] = area["gemeente"], area["provincie"]
        part["postcode4"] = area["postcode4"]
        part["postcode6"] = area["postcode4"] + rng.choice(["SA", "SD", "SS"], len(part))
        for level in (8, 7, 6, 5, 4):
            part[f"h3_r{level}"] = [h3.latlng_to_cell(a, b, level)
                                    for a, b in zip(part["lat"], part["lon"])]
        frames.append(part)
    return pd.concat(frames, ignore_index=True)


def population() -> pd.DataFrame:
    """The made-up Netherlands of the practice mode (and of ``--synthetic``): the synthetic
    population with made-up coordinates plus the two sparse areas, in which the example
    dwellings carry their example postcodes (letters PostNL does not use), so linking them by
    address works as it would with real data."""
    from . import synthetic
    pop = synthetic.with_places(synthetic.population(200_000))
    drawn = synthetic.sample(pop, 60, seed=3, gemeente="Zwolle")   # as maak_voorbeeld.py did
    example = pd.read_csv(WONINGEN, dtype=str)
    postcode = dict(zip(drawn["vbo_id"], example["postcode"]))
    pop["postcode6"] = pop["vbo_id"].map(postcode).fillna(pop["postcode6"])
    extra = extra_areas()
    return pd.concat([pop, extra[pop.columns]], ignore_index=True)


def write_population(path: str | Path) -> Path:
    """The made-up Netherlands as Parquet (zstd), for the web version: the browser reads the file
    instead of making up 200,000 dwellings and a million H3 cells itself. Written by DuckDB on one
    thread, so the same seed gives the same bytes."""
    import duckdb
    out = Path(path)
    out.unlink(missing_ok=True)
    df = population()
    con = duckdb.connect()
    try:
        con.execute("SET threads = 1")
        con.register("pop_df", df)
        target = str(out).replace("'", "''")
        con.execute(f"COPY (SELECT * FROM pop_df) TO '{target}' "
                    "(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 100000)")
    finally:
        con.close()
    return out
