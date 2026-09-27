"""Synthetic populations and datasets, for tests, demos and trying the tool without downloads.

The numbers are loosely shaped like the Dutch housing stock (construction-year peaks after the
war and in the 1970s, more terraced houses than detached ones, labels correlated with age) but
are not a model of it. Never draw conclusions about real data from them.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .qids import ENERGY_LABELS

_PROVINCES = {
    "Utrecht": ["Utrecht", "Amersfoort", "Zeist"],
    "Overijssel": ["Zwolle", "Deventer", "Enschede"],
    "Groningen": ["Groningen", "Midden-Groningen"],
}


def population(n: int = 50_000, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    gemeenten = [(g, p) for p, gs in _PROVINCES.items() for g in gs]
    gi = rng.integers(0, len(gemeenten), n)
    gemeente = np.array([gemeenten[i][0] for i in gi])
    provincie = np.array([gemeenten[i][1] for i in gi])
    # ~25 postcode4 areas per municipality, ~20 postcode6 per postcode4
    pc4 = 1000 + gi * 25 + rng.integers(0, 25, n)
    letters = np.array([a + b for a in "ABCDEFGHJK" for b in "ABCD"])
    pc6_suffix = letters[rng.integers(0, 20, n)]

    era = rng.choice([0, 1, 2, 3, 4], n, p=[0.12, 0.2, 0.3, 0.23, 0.15])
    lo = np.array([1880, 1946, 1965, 1985, 2006])[era]
    hi = np.array([1945, 1964, 1984, 2005, 2024])[era]
    bouwjaar = rng.integers(lo, hi + 1)

    woningtype = rng.choice(
        ["vrijstaand", "twee_onder_een_kap", "hoekwoning", "tussenwoning", "appartement"],
        n, p=[0.14, 0.1, 0.16, 0.27, 0.33])
    base = {"vrijstaand": 150, "twee_onder_een_kap": 130, "hoekwoning": 115,
            "tussenwoning": 110, "appartement": 75}
    oppervlakte = np.clip(
        (np.vectorize(base.get)(woningtype) * rng.lognormal(0, 0.25, n)).round(), 15, 800)

    # label: newer is better, with noise; ~15% has no registered label
    score = np.clip((bouwjaar - 1900) / 125 * 9 + rng.normal(0, 1.6, n), 0, 11)
    labels = np.array(ENERGY_LABELS[::-1])  # G .. A+++++
    energielabel = labels[np.floor(score).astype(int)].astype(object)
    energielabel[rng.random(n) < 0.15] = None

    uhi = np.round(np.clip(rng.normal(1.0, 0.5, n), 0, 3), 1)
    return pd.DataFrame({
        "vbo_id": [f"0000010{i:09d}" for i in range(n)],
        "postcode6": [f"{a}{b}" for a, b in zip(pc4, pc6_suffix)],
        "postcode4": pc4.astype(str),
        "huisnummer": rng.integers(1, 200, n),
        "huisletter": None,
        "toevoeging": None,
        "gemeente": gemeente,
        "provincie": provincie,
        "bouwjaar": bouwjaar,
        "oppervlakte": oppervlakte.astype(int),
        "woningtype": woningtype,
        "energielabel": energielabel,
        "uhi": uhi,
    })


def sample(pop: pd.DataFrame, n: int = 200, seed: int = 2, **filters) -> pd.DataFrame:
    """A 'dataset to publish': ``n`` dwellings drawn from ``pop`` after equality ``filters``,
    with a few typical monitoring columns attached."""
    rng = np.random.default_rng(seed)
    sel = pop
    for col, val in filters.items():
        sel = sel[sel[col].isin(val if isinstance(val, (list, tuple, set)) else [val])]
    ds = sel.sample(n=min(n, len(sel)), random_state=seed).reset_index(drop=True)
    ds["installatiedatum"] = rng.integers(2018, 2024, len(ds))
    ds["jaarverbruik_gas__m3"] = rng.normal(1200, 300, len(ds)).round()
    return ds


# rough centres of the municipalities above, so the practice map has somewhere to draw
_CENTRES = {
    "Utrecht": (52.09, 5.12), "Amersfoort": (52.16, 5.39), "Zeist": (52.09, 5.23),
    "Zwolle": (52.51, 6.09), "Deventer": (52.25, 6.16), "Enschede": (52.22, 6.89),
    "Groningen": (53.22, 6.57), "Midden-Groningen": (53.15, 6.80),
}


def with_places(pop: pd.DataFrame, seed: int = 5, km: float = 3.0) -> pd.DataFrame:
    """The population with made-up coordinates (scattered ``km`` around its municipality's
    centre) and their H3 cells of levels 4 to 8, for the map and the weather step. A separate
    random stream: the other columns stay exactly as ``population`` made them."""
    import h3
    rng = np.random.default_rng(seed)
    gemeente = pop["gemeente"]
    out = pop.copy()
    out["lat"] = np.round(gemeente.map({g: c[0] for g, c in _CENTRES.items()}).to_numpy()
                          + rng.normal(0, km, len(pop)) / 111.0, 5)
    out["lon"] = np.round(gemeente.map({g: c[1] for g, c in _CENTRES.items()}).to_numpy()
                          + rng.normal(0, km, len(pop)) / 68.0, 5)
    fine = pd.Series([h3.latlng_to_cell(a, b, 8) for a, b in zip(out["lat"], out["lon"])],
                     index=out.index)
    out["h3_r8"] = fine
    unique = fine.unique()
    for level in (7, 6, 5, 4):
        out[f"h3_r{level}"] = fine.map({c: h3.cell_to_parent(c, level) for c in unique})
    return out
