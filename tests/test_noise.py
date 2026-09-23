"""Noise and tolerance: a perturbed value is read as a range by an attacker who knows the method."""
import h3
import pandas as pd
import pytest

from anonymate import CATALOGUE, Population, QidColumn, Range, Threshold, assess
from anonymate.generalize import Bin, Noise, tradeoff
from anonymate.risk import parse_constraints

OPP = CATALOGUE["oppervlakte"]


def test_numeric_tolerance_widens_range():
    q = QidColumn("opp", OPP, tolerance=5)
    assert q.parse("100") == Range(95, 105)
    assert q.parse("100-149") == Range(95, 154)
    assert q.parse(">=250") == Range(245, None)
    assert q.parse("100", with_tolerance=False) == Range(100, 100)


def test_tolerance_increases_k():
    pop = Population.from_dataframe(pd.DataFrame({"oppervlakte": [96, 100, 100, 104, 110]}))
    ds = pd.DataFrame({"opp": [100]})
    exact = assess(ds, [QidColumn("opp", OPP)], pop, Threshold(0.33))
    noisy = assess(ds, [QidColumn("opp", OPP, tolerance=5)], pop, Threshold(0.33))
    assert exact.records["k_populatie"].iloc[0] == 2
    assert noisy.records["k_populatie"].iloc[0] == 4


def test_noise_action_bounded_reproducible_and_sets_tolerance():
    df = pd.DataFrame({"opp": list(range(80, 180))})
    qids = [QidColumn("opp", OPP)]
    out, new_q = Noise("opp", 5, seed=3).apply(df, qids)
    again, _ = Noise("opp", 5, seed=3).apply(df, qids)
    assert list(out["opp"]) == list(again["opp"])
    diff = out["opp"].astype(float) - df["opp"]
    assert diff.abs().max() <= 5 and diff.abs().max() > 0
    assert new_q[0].tolerance == pytest.approx(5.5)  # noise + integer rounding
    # the true value always lies inside what an attacker concludes
    cons = parse_constraints(out, new_q)["opp"]
    assert all(c.contains(v) for c, v in zip(cons, df["opp"]))


def test_noise_leaves_classes_alone_and_needs_numbers():
    df = pd.DataFrame({"opp": ["100-149", "120"], "type": ["vrijstaand", "vrijstaand"]})
    out, _ = Noise("opp", 5).apply(df, [QidColumn("opp", OPP)])
    assert out["opp"].iloc[0] == "100-149"
    with pytest.raises(ValueError):
        Noise("type", 5).apply(df, [QidColumn("type", CATALOGUE["woningtype"])])


def test_bin_after_noise_keeps_tolerance():
    df = pd.DataFrame({"opp": [101, 147]})
    steps = tradeoff(df, [QidColumn("opp", OPP)],
                     Population.from_dataframe(pd.DataFrame({"oppervlakte": range(50, 250)})),
                     [Noise("opp", 5, seed=1), Bin("opp", 50)], Threshold(0.33))
    last = steps[-1]
    assert last.qids[0].tolerance == pytest.approx(5.5)
    assert set(last.df["opp"]) <= {"50-99", "100-149", "150-199"}


def test_h3_tolerance_adds_neighbouring_cells():
    cell = h3.latlng_to_cell(52.1, 5.1, 7)  # ~2.4 km between cell centres
    q0 = QidColumn("cel", CATALOGUE["h3_cel"])
    q = QidColumn("cel", CATALOGUE["h3_cel"], tolerance=3)
    assert q0.parse(cell).values == {cell}
    assert len(q.parse(cell).values) == 19  # two rings: ceil(3 km / 2.4 km)
    assert set(h3.grid_disk(cell, 1)) <= q.parse(cell).values


def test_h3_tolerance_counts_more_dwellings():
    centre = h3.latlng_to_cell(52.1, 5.1, 7)
    ring = [c for c in h3.grid_disk(centre, 1) if c != centre]
    pop = Population.from_dataframe(pd.DataFrame({"h3_r7": [centre] * 3 + ring * 2}))
    ds = pd.DataFrame({"cel": [centre]})
    exact = assess(ds, [QidColumn("cel", CATALOGUE["h3_cel"])], pop, Threshold(0.33))
    noisy = assess(ds, [QidColumn("cel", CATALOGUE["h3_cel"], tolerance=2)], pop, Threshold(0.33))
    assert exact.records["k_populatie"].iloc[0] == 3
    assert noisy.records["k_populatie"].iloc[0] == 3 + 2 * 6
