"""k-map and δ-presence on a hand-built population whose answers can be counted by hand."""
import pandas as pd
import pytest

from anonymate import (CATALOGUE, Knowledge, OneOf, Population, QidColumn, Range, Scope, Status,
                       Threshold, assess)


def rows(n, **kw):
    return [dict(kw) for _ in range(n)]


@pytest.fixture
def population():
    data = (
        rows(10, bouwjaar=1970, oppervlakte=100, energielabel="C", gemeente="Zwolle")
        + rows(3, bouwjaar=1971, oppervlakte=100, energielabel="C", gemeente="Zwolle")
        + rows(1, bouwjaar=1850, oppervlakte=300, energielabel="G", gemeente="Zwolle")
        + rows(5, bouwjaar=1970, oppervlakte=100, energielabel=None, gemeente="Zwolle")
        + rows(20, bouwjaar=1970, oppervlakte=100, energielabel="C", gemeente="Deventer")
    )
    return Population.from_dataframe(pd.DataFrame(data))


QIDS = [QidColumn("bouwjaar", CATALOGUE["bouwjaar"]),
        QidColumn("oppervlakte", CATALOGUE["oppervlakte"]),
        QidColumn("energielabel", CATALOGUE["energielabel"])]


def one(**kw):
    return pd.DataFrame([kw])


def k_of(a):
    return a.records["k_populatie"].iloc[0]


def test_k_map_counts_whole_population(population):
    a = assess(one(bouwjaar=1970, oppervlakte=100, energielabel="C"), QIDS, population)
    assert k_of(a) == 30  # 10 in Zwolle + 20 in Deventer


def test_scope_narrows_population(population):
    a = assess(one(bouwjaar=1970, oppervlakte=100, energielabel="C"), QIDS,
               population.within(Scope.region("gemeente", "Zwolle")))
    assert k_of(a) == 10
    assert a.population_size == 19


def test_scope_criteria_range(population):
    assert population.within(Scope({"oppervlakte": Range(50, 250)})).size() == 38


def test_scope_oneof(population):
    assert population.within(Scope({"energielabel": OneOf.of("C", "G")})).size() == 34


def test_binned_value_matches_interval(population):
    a = assess(one(bouwjaar="1970-1979", oppervlakte="95-104", energielabel="C"), QIDS,
               population.within(Scope.region("gemeente", "Zwolle")))
    assert k_of(a) == 13


def test_label_set_matches_any(population):
    assert k_of(assess(one(bouwjaar=1970, oppervlakte=100, energielabel="C|G"), QIDS,
                       population)) == 30


def test_missing_value_is_wildcard(population):
    assert k_of(assess(one(bouwjaar=None, oppervlakte=300, energielabel=None), QIDS,
                       population)) == 1


def test_unknown_population_values_conservative_by_default(population):
    ds = one(bouwjaar=1970, oppervlakte=100, energielabel="C")
    zwolle = population.within(Scope.region("gemeente", "Zwolle"))
    assert k_of(assess(ds, QIDS, zwolle)) == 10
    assert k_of(assess(ds, QIDS, zwolle, unknown_matches=True)) == 15


def test_unique_dwelling_is_at_risk(population):
    r = assess(one(bouwjaar=1850, oppervlakte=300, energielabel="G"), QIDS,
               population).records.iloc[0]
    assert r["k"] == 1 and r["risico"] == 1.0 and r["status"] == Status.AT_RISK


def test_threshold_uses_k_equals_round_one_over_p(population):
    ds = one(bouwjaar=1970, oppervlakte=100, energielabel="C")
    zwolle = population.within(Scope.region("gemeente", "Zwolle"))  # k = 10
    status = lambda pop, p: assess(ds, QIDS, pop, Threshold(p)).records["status"].iloc[0]
    assert status(population, 0.05) == Status.OK  # k=30 >= 20
    assert status(zwolle, 0.09) == Status.AT_RISK  # k=10 < 11
    assert status(zwolle, 0.1) == Status.OK  # k=10 >= 10


def test_delta_presence_flags_class_largely_in_dataset(population):
    # all 3 dwellings of this class take part: k=3 passes p=0.33, but δ = 3/3 = 1
    ds = pd.DataFrame(rows(3, bouwjaar=1971, oppervlakte=100, energielabel="C"))
    a = assess(ds, QIDS, population, Threshold(0.33))
    assert (a.records["k"] == 3).all()
    assert (a.records["delta"] == 1.0).all()
    assert (a.records["status"] == Status.AT_RISK).all()
    assert "δ" in a.records["redenen"].iloc[0]


def test_delta_counts_dataset_records_per_class(population):
    ds = pd.DataFrame(rows(2, bouwjaar=1970, oppervlakte=100, energielabel="C")
                      + rows(1, bouwjaar=1850, oppervlakte=300, energielabel="G"))
    a = assess(ds, QIDS, population)
    assert list(a.records["f_dataset"]) == [2, 2, 1]
    assert a.records["delta"].iloc[0] == pytest.approx(2 / 30)


def test_no_match_status(population):
    a = assess(one(bouwjaar=2020, oppervlakte=100, energielabel="C"), QIDS, population)
    assert a.records["status"].iloc[0] == Status.NO_MATCH


def test_more_records_than_dwellings_warns(population):
    ds = pd.DataFrame(rows(2, bouwjaar=1850, oppervlakte=300, energielabel="G"))
    a = assess(ds, QIDS, population, Threshold(0.33))
    assert any("afbakening" in w for w in a.warnings)


def test_uncounted_qid_only_in_matching_scenario(population):
    ds = pd.DataFrame(rows(4, bouwjaar=1970, oppervlakte=100, energielabel="C"))
    ds["installatiedatum"] = [2019, 2020, 2020, 2020]
    qids = QIDS + [QidColumn("installatiedatum", CATALOGUE["installatiedatum"])]
    reg = assess(ds, qids, population, scenario=Knowledge.REGISTER)
    assert (reg.records["k"] == 30).all() and not reg.records["k_geschat"].any()
    ins = assess(ds, qids, population, scenario=Knowledge.INSIDER)
    # estimated F × share: 30 × 1/4 and 30 × 3/4
    assert list(ins.records["k"]) == pytest.approx([7.5, 22.5, 22.5, 22.5])
    assert ins.records["k_geschat"].all()
    assert ins.records["status"].iloc[0] == Status.AT_RISK


def test_uncounted_missing_value_gives_no_information(population):
    ds = pd.DataFrame(rows(2, bouwjaar=1970, oppervlakte=100, energielabel="C"))
    ds["toestel"] = ["X", None]
    qids = QIDS + [QidColumn("toestel", CATALOGUE["toestel"])]
    a = assess(ds, qids, population, scenario=Knowledge.INSIDER)
    assert list(a.records["k"]) == pytest.approx([30, 30])  # only known value: no information


def test_uncounted_values_use_whole_dataset_distribution(population):
    # two register classes; the exact annual use is unique for every record
    ds = pd.DataFrame(rows(2, bouwjaar=1970, oppervlakte=100, energielabel="C")
                      + rows(2, bouwjaar=1971, oppervlakte=100, energielabel="C"))
    ds["jaarverbruik"] = [1501, 1720, 1650, 1501]
    qids = QIDS + [QidColumn("jaarverbruik", CATALOGUE["jaarverbruik"])]
    a = assess(ds, qids, population, Threshold(0.2), scenario=Knowledge.INSIDER)
    # 1501 occurs 2/4, the others 1/4; class sizes 30 and 3
    assert list(a.records["k"]) == pytest.approx([15, 7.5, 0.75, 1.5])


def test_several_categorical_sets_and_unknowns_stay_aligned():
    # regression: unnesting one categorical attribute must not shift the next one's constraints
    data = (rows(4, woningtype="vrijstaand", energielabel="A", gemeente="Zwolle")
            + rows(3, woningtype="vrijstaand", energielabel="B", gemeente="Zwolle")
            + rows(2, woningtype="tussenwoning", energielabel="A", gemeente="Zwolle")
            + rows(5, woningtype="vrijstaand", energielabel=None, gemeente="Zwolle")
            + rows(6, woningtype=None, energielabel="A", gemeente="Zwolle")
            + rows(7, woningtype="vrijstaand", energielabel="A", gemeente="Deventer"))
    pop = Population.from_dataframe(pd.DataFrame(data))
    ds = pd.DataFrame({"woningtype": ["vrijstaand|tussenwoning", "vrijstaand", "vrijstaand"],
                       "energielabel": ["A", "A|B", None],
                       "gemeente": ["Zwolle", "Zwolle", "Deventer"]})
    q = [QidColumn(c, CATALOGUE[c]) for c in ds.columns]
    strict = assess(ds, q, pop, Threshold(0.33)).records["k_populatie"]
    assert list(strict) == [6, 7, 7]
    lenient = assess(ds, q, pop, Threshold(0.33), unknown_matches=True).records["k_populatie"]
    # + unknown label (5) and unknown type (6) where they could match
    assert list(lenient) == [6 + 5 + 6, 7 + 5 + 6, 7]


@pytest.mark.parametrize("p,k", [(0.05, 20), (0.09, 11), (0.1, 10), (0.2, 5), (0.33, 3)])
def test_threshold_k(p, k):
    assert Threshold(p).k == k


@pytest.mark.parametrize("p", [0.04, 0.34, 0, 1])
def test_threshold_range(p):
    with pytest.raises(ValueError):
        Threshold(p)


def test_summary(population):
    ds = pd.DataFrame(rows(2, bouwjaar=1970, oppervlakte=100, energielabel="C")
                      + rows(1, bouwjaar=1850, oppervlakte=300, energielabel="G"))
    s = assess(ds, QIDS, population).summary()
    assert (s["records"], s["ok"], s["risico"], s["k_min"], s["k_drempel"]) == (3, 2, 1, 1, 11)


def test_empty_dataset(population):
    empty = pd.DataFrame({"bouwjaar": [], "oppervlakte": [], "energielabel": []})
    assert len(assess(empty, QIDS, population).records) == 0


def test_categorical_population_column_not_string():
    pop = Population.from_dataframe(pd.DataFrame({"knmi_station": [260, 260, 290]}))
    a = assess(one(knmi_station="260"), [QidColumn("knmi_station", CATALOGUE["knmi_station"])],
               pop, Threshold(0.33))
    assert k_of(a) == 2


def test_missing_population_column_is_explained(population):
    with pytest.raises(KeyError, match="woningtype"):
        assess(one(woningtype="vrijstaand"), [QidColumn("woningtype", CATALOGUE["woningtype"])],
               population)


def test_bad_value_names_row_and_column(population):
    with pytest.raises(ValueError, match="bouwjaar"):
        assess(one(bouwjaar="ergens in de jaren zeventig", oppervlakte=1, energielabel="C"),
               QIDS, population)


def test_an_empty_h3_column_counts_nothing_and_does_not_fail():
    # the suggestion search suppresses the weather cell: every value empty
    from anonymate import synthetic
    pop = Population.from_dataframe(synthetic.with_places(synthetic.population(3_000)))
    df = pd.DataFrame({"weerzone_h3": [None, None], "bouwjaar": [1970, 1985]})
    qids = [QidColumn("weerzone_h3", CATALOGUE["h3_cel"]), QidColumn("bouwjaar", CATALOGUE["bouwjaar"])]
    a = assess(df, qids, pop)
    assert len(a.records) == 2
    bare = Population.from_dataframe(synthetic.population(3_000))   # no H3 columns at all
    assert len(assess(df, qids, bare).records) == 2


def test_station_numbers_are_normalised_and_a_stopped_station_counts_as_its_successor():
    from anonymate.qids import normalise_station
    assert normalise_station("06260") == normalise_station("260.0") == normalise_station(" 260 ") == "260"
    assert normalise_station("210") == normalise_station("06210") == "215"
    pop = Population.from_dataframe(pd.DataFrame({
        "vbo_id": [str(i) for i in range(30)],
        "knmi_station": ["215"] * 12 + ["260"] * 18}))
    df = pd.DataFrame({"station": ["210", "06260"]})
    a = assess(df, [QidColumn("station", CATALOGUE["knmi_station"])], pop)
    assert a.records["k"].tolist() == [12, 18]
    assert any("historisch KNMI-station 210" in w for w in a.warnings)


def test_no_match_records_have_no_k_in_the_summary_and_unknown_bits(population):
    """k of a record without match is not "0 equal dwellings": it stays out of k_min / median."""
    from anonymate.explain import information_bits
    df = pd.DataFrame([dict(bouwjaar=1970, oppervlakte=100, energielabel="C"),
                       dict(bouwjaar=1500, oppervlakte=100, energielabel="C")])
    a = assess(df, QIDS, population)
    assert list(a.records["status"]) == [Status.OK, Status.NO_MATCH]
    s = a.summary()
    assert s["geen_match"] == 1 and s["k_min"] == s["k_mediaan"] == 30
    assert s["delta_max"] is not None
    _, _, remaining = information_bits(df, a, population)
    assert remaining.iloc[0] > 0 and pd.isna(remaining.iloc[1])
    none = assess(df.iloc[[1]], QIDS, population)
    assert none.summary()["k_min"] is None and none.summary()["delta_max"] is None
    assert information_bits(df.iloc[[1]], none, population)[2].isna().all()
