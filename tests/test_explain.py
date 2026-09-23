import math

import pandas as pd
import pytest

from anonymate import CATALOGUE, Knowledge, Population, QidColumn, Threshold, assess
from anonymate.detect import detect
from anonymate.explain import information_bits, insider_sources, markdown
from anonymate.report import write


@pytest.fixture
def population():
    # 64 dwellings: 32 built 1970, 16 in 1980, 16 in 1990; labels independent of year
    rows = []
    for year, n in ((1970, 32), (1980, 16), (1990, 16)):
        rows += [{"bouwjaar": year, "energielabel": "A" if i % 4 == 0 else "C"} for i in range(n)]
    return Population.from_dataframe(pd.DataFrame(rows))


def test_bits_per_attribute(population):
    ds = pd.DataFrame({"bouwjaar": [1970, 1980], "energielabel": ["A", "A"]})
    q = [QidColumn(c, CATALOGUE[c]) for c in ds.columns]
    a = assess(ds, q, population, Threshold(0.33))
    needed, bits, remaining = information_bits(ds, a, population)
    assert needed == pytest.approx(6.0)  # 64 dwellings
    by = {b.column: b for b in bits}
    # 1970: 64/32 -> 1 bit; 1980: 64/16 -> 2 bits
    assert (by["bouwjaar"].median, by["bouwjaar"].maximum) == pytest.approx((1.5, 2.0))
    assert by["energielabel"].median == pytest.approx(2.0)  # 16 of 64 have label A
    # 1970 & A: 8 dwellings -> log2(8) = 3 bits left; 1980 & A: 4 -> 2 bits
    assert list(remaining) == pytest.approx([3.0, 2.0])


def test_bits_for_estimated_attribute(population):
    ds = pd.DataFrame({"bouwjaar": [1970] * 4, "jaarverbruik": [1000, 1000, 1500, 2000]})
    q = [QidColumn("bouwjaar", CATALOGUE["bouwjaar"]),
         QidColumn("jaarverbruik", CATALOGUE["jaarverbruik"])]
    a = assess(ds, q, population, Threshold(0.33), scenario=Knowledge.INSIDER)
    _, bits, _ = information_bits(ds, a, population)
    est = {b.column: b for b in bits}["jaarverbruik"]
    assert est.estimated and est.maximum == pytest.approx(math.log2(4))


def test_insider_sources():
    df = pd.DataFrame({"e_net__W": [1.0], "v_gas_consumed": [5.0], "boiler_power__W": [3.0],
                       "temp_aanvoer__degC": [40.0], "hp_power__W": [900.0],
                       "temp_buiten__degC": [5.0]})
    found = insider_sources(detect(df))
    assert found["netbeheerder en energieleverancier (slimme meter)"] == ["e_net__W",
                                                                          "v_gas_consumed"]
    assert found["fabrikant van ketel of thermostaat (cloud-data)"] == ["boiler_power__W"]
    assert found["warmtepompfabrikant (cloud-data)"] == ["hp_power__W"]
    assert "temp_aanvoer__degC" in found["leverancier of uitlezer van de warmtemeter"]
    assert not any("temp_buiten__degC" in cols for cols in found.values())


def test_markdown_mentions_scenario_gap():
    text = markdown(23.0, [], pd.Series([5.0]), {"netbeheerder": ["e_net__W"]},
                    Knowledge.REGISTER)
    assert "23.0 bits" in text and "insider" in text


def test_report_includes_explanations(population, tmp_path):
    ds = pd.DataFrame({"bouwjaar": [1970, 1980], "energielabel": ["A", "C"],
                       "e_net__W": [100.0, 200.0]})
    q = [QidColumn(c, CATALOGUE[c]) for c in ("bouwjaar", "energielabel")]
    a = assess(ds, q, population, Threshold(0.33))
    write(tmp_path, ds, a, population=population)
    text = (tmp_path / "rapport.md").read_text(encoding="utf-8")
    assert "bits" in text and "slimme meter" in text
