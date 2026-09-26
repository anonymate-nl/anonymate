import math

import pandas as pd
import pytest

from anonymate import Population, Scope
from anonymate.rounding import grid, group_sizes


@pytest.fixture
def population():
    # H spread evenly 100..199.5 in steps of 0.5 (200 homes), half in each of two stations
    df = pd.DataFrame({"sig_H": [100 + i * 0.5 for i in range(200)],
                       "knmi_station": ["260", "278"] * 100,
                       "eengezins": [True] * 190 + [False] * 10})
    df.loc[5, "sig_H"] = None
    return Population.from_dataframe(df)


def test_group_sizes(population):
    fine = group_sizes(population, {"sig_H": 1}, k=11)
    assert fine["woningen"] == 199
    assert fine["aandeel_te_klein"] == 1.0          # groups of 2
    coarse = group_sizes(population, {"sig_H": 10}, k=11)
    assert coarse["aandeel_te_klein"] < 0.2          # groups of ~20
    assert coarse["groep_mediaan"] == pytest.approx(20)


def test_exact_columns_split_groups(population):
    without = group_sizes(population, {"sig_H": 10}, k=11)
    with_station = group_sizes(population, {"sig_H": 10}, exact=["knmi_station"], k=11)
    assert with_station["groepen"] > without["groepen"]
    assert with_station["aandeel_te_klein"] > without["aandeel_te_klein"]


def test_scope_applies(population):
    s = group_sizes(population.within(Scope({"eengezins": None})), {"sig_H": 5})
    assert s["woningen"] == 199
    from anonymate.constraints import OneOf
    s = group_sizes(population.within(Scope({"eengezins": OneOf.of("true")})), {"sig_H": 5})
    assert s["woningen"] == 189


def test_grid(population):
    g = grid(population, {"sig_H": [20, 1, 5]}, k=11)
    assert list(g["stap_sig_H"]) == [1, 5, 20]
    assert g["aandeel_te_klein"].is_monotonic_decreasing


def test_rainbow_frequency_table_matches_python_key(population):
    from anonymate.rounding import rainbow, rainbow_key
    steps = {"sig_H": 10}
    freq = rainbow(population, steps, exact=["knmi_station"])
    assert "postcode6" not in freq.columns and set(freq.columns) == {"hash", "n"}
    assert freq["n"].sum() == 199
    # a record at H = 147.0 (bucket 15 -> 145..154.99), station 260
    key = rainbow_key({"sig_H": 147.0, "knmi_station": "260"}, steps, ["knmi_station"])
    n = int(freq.set_index("hash").loc[key, "n"])
    df = population.con.execute("SELECT count(*) FROM population WHERE sig_H >= 145 "
                                "AND sig_H < 155 AND knmi_station = '260'").fetchone()[0]
    assert n == df


def test_rainbow_rounds_half_up_consistently():
    from anonymate.rounding import _bucket
    assert [_bucket(v, 10) for v in (144.99, 145.0, 154.99, -5.0)] == [14, 15, 15, 0]


def test_exclusion_scope(population):
    from anonymate.constraints import OneOf
    excl = population.within(Scope({}, "zonder 278", {"knmi_station": OneOf.of("278")}))
    assert excl.size() == 100


def test_rainbow_metadata_roundtrip(population, tmp_path):
    from anonymate.rounding import rainbow, rainbow_metadata
    out = tmp_path / "r.parquet"
    rainbow(population, {"sig_H": 10}, ["knmi_station"], out=str(out), description="test")
    meta = rainbow_metadata(str(out))
    assert meta["stappen"] == {"sig_H": 10} and meta["exact"] == ["knmi_station"]
    assert meta["afbakening"] == "test" and meta["woningen"] == 199


def test_entropy_bits():
    # 64 homes: 4 equal groups of 16 -> 2 bits published, log2(16) = 4 bits to go, sum log2(64)
    pop = Population.from_dataframe(pd.DataFrame({"x": [g * 10.0 for g in range(4)] * 16}))
    s = group_sizes(pop, {"x": 1})
    assert s["bits_onthuld"] == pytest.approx(2)
    assert s["bits_resterend"] == pytest.approx(4)


def test_entropy_adds_up(population):
    for step in (1, 5, 20):
        s = group_sizes(population, {"sig_H": step}, exact=["knmi_station"])
        assert s["bits_onthuld"] + s["bits_resterend"] == pytest.approx(math.log2(s["woningen"]))
    fine, coarse = (group_sizes(population, {"sig_H": st}) for st in (1, 20))
    assert fine["bits_onthuld"] > coarse["bits_onthuld"]
