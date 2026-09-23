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
