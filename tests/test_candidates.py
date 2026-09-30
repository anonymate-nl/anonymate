"""The candidate list must be exactly the dwellings that assess() counted."""
import pandas as pd

from anonymate import CATALOGUE, Population, QidColumn, Status, Threshold, assess
from anonymate.candidates import candidates


def population():
    rows = []
    for i in range(40):
        rows.append({"vbo_id__str": f"v{i:03d}", "postcode6__str": "8000AA", "huisnummer__str": str(i + 1),
                     "bouwjaar__yr": 1900 + (i % 4) * 30, "oppervlakte__m2": 90 + (i % 5) * 20,
                     "energielabel__cat": "CCCDG"[i % 5] if i % 7 else None})
    return Population.from_dataframe(pd.DataFrame(rows))


QIDS = [QidColumn("bouwjaar", CATALOGUE["bouwjaar"]),
        QidColumn("oppervlakte", CATALOGUE["oppervlakte"]),
        QidColumn("energielabel", CATALOGUE["energielabel"])]


def test_candidates_are_the_counted_dwellings():
    pop = population()
    df = pd.DataFrame({"bouwjaar": ["1900-1929", "1960", "1990-2000", "1930"],
                       "oppervlakte": ["80-100", "170", "100-150", "110"],
                       "energielabel": ["C", "G", "C|D", None]})
    a = assess(df, QIDS, pop, Threshold(0.2))
    assert (a.records["status"] == Status.AT_RISK).any()
    c = candidates(df, a, pop)
    for i, r in a.records[a.records["status"] == Status.AT_RISK].iterrows():
        got = c[c["record"] == i]
        assert len(got) == r["k_populatie"]
        assert got["vbo_id__str"].is_unique
    assert set(c["record"]) == set(a.records.index[a.records["status"] == Status.AT_RISK])


def test_long_lists_are_not_listed():
    pop = population()
    df = pd.DataFrame({"bouwjaar": ["1900-2000"], "oppervlakte": ["50-200"], "energielabel": ["C"]})
    a = assess(df, QIDS, pop, Threshold(0.05))
    c = candidates(df, a, pop, max_per_record=3, only_at_risk=False)
    assert len(c) == 1 and pd.isna(c["kandidaat_nr"].iloc[0])
    assert c["k_populatie"].iloc[0] > 3
