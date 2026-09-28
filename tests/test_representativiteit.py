import numpy as np
import pandas as pd

from anonymate import representativiteit as rp


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
