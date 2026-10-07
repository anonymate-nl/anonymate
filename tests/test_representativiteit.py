import json

import numpy as np
import pandas as pd
import pytest

from anonymate import representativiteit as rp
from anonymate import voorbeeld
from anonymate.constraints import Range
from anonymate.population import Population, Scope


def _data(n=400, seed=1):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "oppervlakte": rng.normal(110, 30, n).round(),
        "woningtype": rng.choice(["vrijstaand", "rij", "appartement"], n, p=[0.2, 0.5, 0.3]),
        "verbruik": rng.normal(1200, 300, n).round(),
    })


def test_leaving_out_the_tail_is_notable_and_not_chance():
    df = _data()
    # the assessment drops the largest dwellings: a systematic, not a random, omission
    keep = df["oppervlakte"] < df["oppervlakte"].quantile(0.8)
    t = rp.shift(df, keep).set_index("kolom")
    assert t.loc["oppervlakte", "maat"] == "SMD"
    assert t.loc["oppervlakte", "waarde"] < -rp.SMD_NOTABLE
    assert t.loc["oppervlakte", "oordeel"] == "merkbaar"
    assert t.loc["oppervlakte", "toeval"] < 0.05
    assert t.loc["woningtype", "maat"] == "TVD"


def test_a_random_omission_looks_like_chance():
    df = _data(seed=2)
    rng = np.random.default_rng(5)
    keep = pd.Series(rng.random(len(df)) > 0.1)
    t = rp.shift(df, keep).set_index("kolom")
    assert (t["oordeel"] == "verwaarloosbaar").all()
    assert (t["toeval"] > 0.05).all()


def test_nothing_left_out_and_the_report_section():
    df = _data(50)
    t = rp.shift(df, pd.Series(True, index=df.index))
    assert (t["waarde"] == 0).all() and t["toeval"].isna().all()
    assert "geen records weggelaten" in rp.markdown(t)
    keep = df["oppervlakte"] < df["oppervlakte"].quantile(0.8)
    text = rp.markdown(rp.shift(df, keep))
    assert "| oppervlakte | SMD |" in text and "Let op" in text


# --- the dataset against its target population ---------------------------------------------------

KENMERKEN = [rp.Kenmerk("bouwjaar__yr", grenzen=(1945, 1965, 1975, 1992, 2006)),
             "woningtype__cat", "oppervlakte__m2"]


@pytest.fixture(scope="module")
def doel():
    df = voorbeeld.population()
    return df, Population.from_dataframe(df)


def test_a_random_sample_looks_like_the_population(doel):
    df, pop = doel
    sample = df.sample(400, random_state=3)
    v = rp.vergelijk(sample, pop, KENMERKEN, draws=300)
    t = v.kenmerken.set_index("kenmerk")
    assert list(t["maat"]) == ["SMD", "TVD", "SMD"]
    assert (t["oordeel"] == "verwaarloosbaar").all()
    assert (t["toeval"] > 0.05).all()
    assert not v.waarschuwingen


def test_a_biased_sample_is_notable_and_not_chance(doel):
    df, pop = doel
    old = df[df["bouwjaar__yr"] < 1965].sample(300, random_state=1)
    v = rp.vergelijk(old, pop, KENMERKEN, draws=300)
    t = v.kenmerken.set_index("kenmerk")
    assert t.loc["bouwjaar__yr", "waarde"] < -rp.SMD_NOTABLE
    assert t.loc["bouwjaar__yr", "oordeel"] == "merkbaar"
    assert t.loc["bouwjaar__yr", "toeval"] < 0.05
    assert t.loc["bouwjaar__yr", "wasserstein"] > 0
    cls = v.klassen[v.klassen["kenmerk"] == "bouwjaar__yr"].set_index("klasse")
    assert cls.loc["≥ 2006", "richting"] == "−"
    assert cls.loc["≥ 2006", "dataset"] is None or pd.isna(cls.loc["≥ 2006", "dataset"])


def test_small_classes_get_only_a_direction_and_one_class_warns(doel):
    df, pop = doel
    one = df[df["woningtype__cat"] == df["woningtype__cat"].iloc[0]].sample(30, random_state=2)
    v = rp.vergelijk(one, pop, ["woningtype__cat"], k=11, draws=100)
    cls = v.klassen.set_index("klasse")
    shown = cls["dataset"].dropna()
    assert len(shown) == 1 and shown.iloc[0] == 1.0  # the only class with >= k records
    assert (cls.drop(shown.index)["richting"] == "−").all()
    assert any("per record bekend" in w for w in v.waarschuwingen)


def test_scope_parameters_json_and_report(doel):
    df, pop = doel
    target = pop.within(Scope({"oppervlakte__m2": Range(50, 250)}, "oppervlakte 50-250 m²"))
    sample = df[df["oppervlakte__m2"].between(50, 250)].sample(200, random_state=4)
    v = rp.vergelijk(sample, target, KENMERKEN, draws=100, seed=7)
    p = v.parameters
    assert p["afbakening"] == "oppervlakte 50-250 m²" and p["seed"] == 7
    assert p["populatie_woningen"] == int(df["oppervlakte__m2"].between(50, 250).sum())
    assert p["kenmerken"][0] == {"kolom": "bouwjaar__yr",
                                 "grenzen": [1945.0, 1965.0, 1975.0, 1992.0, 2006.0]}
    json.dumps(v.to_dict())  # publishable as JSON
    text = v.markdown()
    assert "| bouwjaar__yr | 200 | SMD |" in text and "| woningtype__cat |" in text
    assert "Parameters, om na te rekenen" in text
    # the same seed gives the same outcome
    again = rp.vergelijk(sample, target, KENMERKEN, draws=100, seed=7)
    assert again.to_dict() == v.to_dict()


def test_dataset_column_under_another_name(doel):
    df, pop = doel
    sample = df.sample(100, random_state=5).rename(columns={"woningtype__cat": "type"})
    v = rp.vergelijk(sample, pop, [rp.Kenmerk("woningtype__cat", bron="type")], draws=50)
    assert v.kenmerken.loc[0, "n"] == 100
