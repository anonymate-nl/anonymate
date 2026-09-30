import time

import pandas as pd
import pytest

from anonymate import CATALOGUE, Population, QidColumn, Scope, Threshold, assess, synthetic
from anonymate.generalize import (Bin, Edges, Group, LocationUp, Suppress, information_loss,
                                  suggest, tradeoff)

BJ = QidColumn("bouwjaar", CATALOGUE["bouwjaar"])
OPP = QidColumn("oppervlakte", CATALOGUE["oppervlakte"])
LBL = QidColumn("energielabel", CATALOGUE["energielabel"])
PC4 = QidColumn("postcode4", CATALOGUE["postcode4"])


def apply(action, values, q=BJ, population=None):
    df = pd.DataFrame({q.column: values})
    out, _ = action.apply(df, [q], population)
    return list(out[q.column])


def test_bin_decades():
    assert apply(Bin("bouwjaar", 10), [1974, "1960-1969", "1965-1972", None]) == \
        ["1970-1979", "1960-1969", "1960-1979", None]


def test_bin_tails():
    b = Bin("bouwjaar", 20, below=1945, above=2015)
    assert apply(b, [1900, 1950, 2018, 1944, 2005, "1930-1950"]) == \
        ["<=1944", "1945-1959", ">=2015", "<=1944", "2000-2014", "<=1959"]


def test_bin_on_open_class():
    assert apply(Bin("bouwjaar", 10), ["<1945"]) == ["<=1949"]


def test_bin_non_integer():
    q = QidColumn("uhi", CATALOGUE["uhi"])
    assert apply(Bin("uhi", 0.5), [1.3, 0.2], q) == ["1-1.5", "0-0.5"]


def test_edges():
    e = Edges("bouwjaar", (1945, 1965, 1975, 1992, 2006, 2015))
    assert apply(e, [1930, 1965, 1974, 2020, "1970-1980"]) == \
        ["<=1944", "1965-1974", "1965-1974", ">=2015", "1965-1991"]


def test_group():
    g = Group.of("energielabel", {"A", "B"}, {"C", "D"})
    assert apply(g, ["A", "C", "E", "B|C"], LBL) == ["A|B", "C|D", "E", "A|B|C|D"]


def test_suppress():
    assert apply(Suppress("bouwjaar"), [1970, 1980]) == [None, None]


def test_location_up():
    pop = Population.from_dataframe(pd.DataFrame({
        "postcode4": ["8011", "8011", "8012", "7411"],
        "gemeente": ["Zwolle", "Zwolle", "Zwolle", "Deventer"]}))
    df = pd.DataFrame({"postcode4": ["8011", "7411"]})
    out, qids = LocationUp("postcode4", "gemeente").apply(df, [PC4], pop)
    assert list(out["postcode4"]) == ["Zwolle", "Deventer"]
    assert qids[0].spec.key == "gemeente"
    a = assess(out, qids, pop, Threshold(0.33))
    assert list(a.records["k_populatie"]) == [3, 1]


def test_information_loss():
    df = pd.DataFrame({"bouwjaar": [1970, None]})
    assert information_loss(df, [BJ]) == pytest.approx(0.5)
    df = pd.DataFrame({"energielabel": ["A|B|C|D|E|F|G|A+|A++|A+++|A++++|A+++++"]})
    assert information_loss(df, [LBL]) == pytest.approx(1.0)


GEM = QidColumn("gemeente", CATALOGUE["gemeente"])
PC6 = QidColumn("postcode6", CATALOGUE["postcode6"])


def test_loss_is_relative_to_the_delivered_dataset():
    df = pd.DataFrame({"bouwjaar": [1950, 1960, 1970, 1980, 1990, 2000],
                       "gemeente": ["Zwolle"] * 6,
                       "energielabel": ["A", "B", None, None, "C", "D"]})
    qids = [BJ, GEM, LBL]
    assert information_loss(df, qids, df, reference_qids=qids) == 0.0
    assert information_loss(df, qids, df) == 0.0
    assert information_loss(df, qids) > 0                  # absolute: the gaps and gemeente count
    # decades on a dataset without gaps: the same number as before the change (9 of 50 years)
    clean = df[["bouwjaar"]]
    dec, _ = Bin("bouwjaar", 10).apply(clean, [BJ])
    assert information_loss(dec, [BJ], clean) == pytest.approx(9 / 50)
    # gaps in the original lose nothing; the filled rows lose what they lose
    part, _ = Suppress("energielabel").apply(df, qids)
    assert information_loss(part, [LBL], df) == pytest.approx(4 / 6)
    # gemeente stays gemeente: nothing; left out: everything
    assert information_loss(df, [GEM], df, reference_qids=[GEM]) == 0.0
    gone, _ = Suppress("gemeente").apply(df, [GEM])
    assert information_loss(gone, [GEM], df, reference_qids=[GEM]) == pytest.approx(1.0)


def test_loss_of_a_coarser_location():
    pop = Population.from_dataframe(pd.DataFrame({
        "postcode6": ["8011AA", "8012BB", "7411CC"],
        "postcode4": ["8011", "8012", "7411"],
        "gemeente": ["Zwolle", "Zwolle", "Deventer"]}))
    df = pd.DataFrame({"postcode6": ["8011AA", "8012BB", "7411CC"]})
    up, qids = LocationUp("postcode6", "gemeente").apply(df, [PC6], pop)
    assert qids[0].spec.key == "gemeente"
    assert information_loss(up, qids, df, reference_qids=[PC6]) == pytest.approx(0.5)
    steps = tradeoff(df, [PC6], pop, [LocationUp("postcode6", "gemeente")])
    assert [s.loss for s in steps] == pytest.approx([0.0, 0.5])
    # delivered as gemeente, still gemeente
    assert information_loss(up, qids, up, reference_qids=qids) == 0.0


@pytest.fixture(scope="module")
def synth():
    pop = synthetic.population(20_000, seed=1)
    ds = synthetic.sample(pop, 80, seed=2, gemeente="Zwolle",
                          woningtype=["vrijstaand", "twee_onder_een_kap", "hoekwoning",
                                      "tussenwoning"])
    return Population.from_dataframe(pop), ds


def test_generalisation_never_increases_risk(synth):
    population, ds = synth
    zwolle = population.within(Scope.region("gemeente", "Zwolle"))
    steps = tradeoff(ds, [BJ, OPP, LBL], zwolle,
                     [Bin("bouwjaar", 10), Bin("oppervlakte", 25), Suppress("energielabel")])
    oks = [s.ok for s in steps]
    losses = [s.loss for s in steps]
    assert oks == sorted(oks) and losses == sorted(losses)
    assert steps[0].ok < steps[-1].ok


def test_suggest_reaches_target(synth):
    population, ds = synth
    zwolle = population.within(Scope.region("gemeente", "Zwolle"))
    steps = suggest(ds, [BJ, OPP, LBL, PC4], zwolle, target_share=0.9)
    assert steps[-1].ok / len(ds) >= 0.9
    assert len(steps) > 1


def test_performance_realistic_size():
    # the store holds ~8 million dwellings; 500k here keeps CI fast while exercising the join
    pop = synthetic.population(500_000, seed=3)
    population = Population.from_dataframe(pop)
    ds = synthetic.sample(pop, 1000, seed=4)
    t = time.perf_counter()
    assess(ds, [BJ, OPP, LBL, PC4], population)
    assert time.perf_counter() - t < 30


def test_report_explains_information_loss():
    from anonymate.generalize import LOSS_NOTE
    from anonymate.report import markdown
    pop = Population.from_dataframe(synthetic.population(2_000, seed=1))
    ds = synthetic.sample(pop.con.execute("select * from " + pop.relation).df(), 30, seed=2)
    steps = tradeoff(ds, [BJ], pop, [Bin("bouwjaar", 10)])
    a = assess(ds, [BJ], pop, Threshold(0.2))
    s = a.summary()
    s["stappen"] = [x.row() for x in steps]
    assert LOSS_NOTE in markdown(s, a)
