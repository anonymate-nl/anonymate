"""The prefilter in the population count (risk.PREFILTER) only drops dwellings that match no class:
assess and suggest give exactly the same answers with and without it."""
import numpy as np
import pandas as pd
import pytest

from anonymate import CATALOGUE, Population, QidColumn, Threshold, assess, risk, synthetic
from anonymate.generalize import suggest


@pytest.fixture(scope="module")
def population():
    df = synthetic.with_places(synthetic.population(20_000))
    rng = np.random.default_rng(7)
    for col in ("bouwjaar__yr", "oppervlakte__m2"):        # unknown numeric values
        df[col] = df[col].astype("float64").mask(rng.random(len(df)) < 0.05)
    for col in ("gemeente__cat", "woningtype__cat"):       # unknown categorical values
        df[col] = df[col].mask(rng.random(len(df)) < 0.05)
    return Population.from_dataframe(df)


@pytest.fixture(scope="module")
def dataset(population):
    pop = population.con.execute("SELECT * FROM population USING SAMPLE 120 ROWS (reservoir, 3)").fetchdf()
    rng = np.random.default_rng(11)
    bj = pop["bouwjaar__yr"].astype("object")
    m2 = pop["oppervlakte__m2"].astype("object")
    for i in range(len(pop)):                              # exact values, classes, open ends
        r = rng.random()
        if pd.notna(bj[i]) and r < 0.2:
            bj[i] = f"{int(bj[i]) // 10 * 10}-{int(bj[i]) // 10 * 10 + 9}"
        elif r < 0.25:
            bj[i] = "<1945"
        elif r < 0.3:
            bj[i] = ">=2015"
        if pd.notna(m2[i]) and rng.random() < 0.2:
            m2[i] = f"{int(m2[i]) // 25 * 25}-{int(m2[i]) // 25 * 25 + 24}"
    label = pop["energielabel__cat"].astype("object")
    label[::7] = "A|B"                                     # sets of categories
    return pd.DataFrame({"bouwjaar": bj, "oppervlakte": m2, "energielabel": label,
                         "gemeente": pop["gemeente__cat"], "woningtype": pop["woningtype__cat"]})


QIDS = [QidColumn(c, CATALOGUE[c]) for c in ("bouwjaar", "oppervlakte", "energielabel",
                                             "gemeente", "woningtype")]


def _both(monkeypatch, fn):
    monkeypatch.setattr(risk, "PREFILTER", False)
    zonder = fn()
    monkeypatch.setattr(risk, "PREFILTER", True)
    return zonder, fn()


@pytest.mark.parametrize("unknown_matches", [False, True])
@pytest.mark.parametrize("buckets_max", [risk.BUCKETS_MAX, 0])   # 0: exact values, never buckets
def test_assess_is_the_same_with_and_without_prefilter(monkeypatch, population, dataset,
                                                       unknown_matches, buckets_max):
    monkeypatch.setattr(risk, "BUCKETS_MAX", buckets_max)
    zonder, met = _both(monkeypatch, lambda: assess(
        dataset, QIDS, population, Threshold(0.2), unknown_matches=unknown_matches).records)
    pd.testing.assert_frame_equal(zonder, met)
    assert (met["k_populatie"] > 0).any() and (met["k_populatie"] == 0).any()


def test_suggest_is_the_same_with_and_without_prefilter(monkeypatch, population, dataset):
    zonder, met = _both(monkeypatch, lambda: suggest(dataset, QIDS, population, Threshold(0.2),
                                                     max_steps=6))
    assert [s.description for s in zonder] == [s.description for s in met]
    for a, b in zip(zonder, met):
        assert (a.ok, a.log_k, a.loss) == (b.ok, b.log_k, b.loss)


def test_suggest_is_the_same_with_and_without_the_cache(monkeypatch, population, dataset):
    class NothingKept(dict):
        def __setitem__(self, key, value):
            pass
    monkeypatch.setattr(population, "cache", NothingKept())
    zonder = suggest(dataset, QIDS, population, Threshold(0.2), max_steps=4)
    monkeypatch.setattr(population, "cache", {})
    met = suggest(dataset, QIDS, population, Threshold(0.2), max_steps=4)
    assert any(k[0] == "count" for k in population.cache)
    assert [s.description for s in zonder] == [s.description for s in met]
    for a, b in zip(zonder, met):
        assert (a.ok, a.log_k, a.loss) == (b.ok, b.log_k, b.loss)


def test_distinct_values_are_asked_once_per_column(population):
    population.cache.clear()
    first = population.distinct("bouwjaar__yr")
    population.con.execute("SELECT 1")                     # nothing else touches the cache
    assert population.distinct("bouwjaar__yr") is first
    assert population.within(population.scope).distinct("bouwjaar__yr") is first
    assert sorted(first) == sorted(v for (v,) in population.con.execute(
        "SELECT DISTINCT bouwjaar__yr FROM population WHERE bouwjaar__yr IS NOT NULL").fetchall())
