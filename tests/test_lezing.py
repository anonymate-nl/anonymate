import json

import pandas as pd
import pytest

from anonymate import Population, cli, synthetic
from anonymate.constraints import Range
from anonymate.generalize import Bin
from anonymate.lezing import BENEDEN, BOVEN, ONDER, Lezing, onderzoek, uit_config
from anonymate.qids import CATALOGUE
from anonymate.risk import QidColumn, parse_constraints

YEAR = CATALOGUE["bouwjaar"]
AREA = CATALOGUE["oppervlakte"]


def test_rounded_to_nearest_reads_half_a_step_either_side():
    lz = Lezing(5)
    assert lz.apply(Range(1965, 1965), integer=True) == Range(1963, 1967)
    assert Lezing(10).apply(Range(1970, 1970), integer=True) == Range(1965, 1974)
    # a class made later from rounded values: the true values reach half a step further
    assert lz.apply(Range(1960, 1969), integer=True) == Range(1958, 1971)
    assert lz.apply(Range(None, 1944), integer=True) == Range(None, 1946)


def test_rounded_down_and_lower_bound_labels():
    lz = Lezing(10, BENEDEN)
    assert lz.apply(Range(1970, 1970), integer=True) == Range(1970, 1979)
    assert lz.apply(Range(2.5, 2.5), integer=False) == Range(2.5, 12.5)


def test_shared_boundary_goes_to_one_class():
    shared = frozenset({150.0})
    up = Lezing(grens=BOVEN, gedeeld=shared)
    assert up.apply(Range(100, 150), integer=True) == Range(100, 149)
    assert up.apply(Range(150, 200), integer=True) == Range(150, 200)
    down = Lezing(grens=ONDER, gedeeld=shared)
    assert down.apply(Range(100, 150), integer=True) == Range(100, 150)
    assert down.apply(Range(150, 200), integer=True) == Range(151, 200)
    assert up.na_herschrijven() is None


def test_onderzoek_finds_rounding():
    o = onderzoek(pd.Series([1965, 1970, 1985, 2000, 1965], name="bouwjaar_afgerond"), YEAR)
    assert o.stap == 5 and o.naamhint and o.voorstel() == Lezing(5)
    assert [a.tekst() for a in o.alternatieven(o.voorstel())] == [
        "afgerond op 5, naar beneden", "zoals gepubliceerd"]
    assert "veelvouden van 5" in o.meldingen()[0]
    # exact years, a multiple of 10 among them: no rounding
    assert onderzoek(pd.Series([1961, 1970, 1985], name="bouwjaar"), YEAR).stap == 0
    # two values say nothing yet
    assert onderzoek(pd.Series([1960, 1970], name="bouwjaar"), YEAR).stap == 0
    # rounding the user already allowed for as tolerance is not proposed again
    assert onderzoek(pd.Series([1965, 1970, 1985], name="x"), YEAR, tolerance=2.5).stap == 0
    assert onderzoek(pd.Series([1900, 1950, 2000], name="x"), YEAR).stap == 50


def test_onderzoek_checks_classes():
    o = onderzoek(pd.Series(["<100", "100-150", "150-200", "201-249", "260-300", ">=280"],
                            name="opp"), AREA)
    assert (o.raken, o.aansluitend, o.gaten, o.overlap) == (1, 2, 1, 1)
    assert o.gedeeld == frozenset({150.0}) and o.stap == 0
    assert o.voorstel() is None
    assert {a.grens for a in o.alternatieven(None)} == {BOVEN, ONDER}
    text = " ".join(o.meldingen())
    assert "100-150 en 150-200" in text and "201-249 en 260-300" in text


def test_uit_config():
    assert uit_config(5) == Lezing(5)
    assert uit_config("5 beneden") == Lezing(5, BENEDEN)
    assert uit_config(0).exact
    assert uit_config(None, "boven", {150.0}) == Lezing(grens=BOVEN, gedeeld=frozenset({150.0}))
    assert uit_config(None, None) is None
    with pytest.raises(ValueError):
        uit_config("5 zijwaarts")


def test_qid_column_reads_with_lezing_but_rewrites_as_published():
    df = pd.DataFrame({"bj": ["1965", "1970"]})
    q = QidColumn("bj", YEAR, lezing=Lezing(5))
    assert list(parse_constraints(df, [q])["bj"]) == [Range(1963, 1967), Range(1968, 1972)]
    raw = parse_constraints(df, [q], with_tolerance=False)["bj"]
    assert list(raw) == [Range(1965, 1965), Range(1970, 1970)]
    out, qids = Bin("bj", 10).apply(df, [q], None)
    assert list(out["bj"]) == ["1960-1969", "1970-1979"]
    assert qids[0].lezing == Lezing(5)
    shared = QidColumn("bj", YEAR, lezing=Lezing(grens=BOVEN, gedeeld=frozenset({1970.0})))
    assert Bin("bj", 10).apply(df, [shared], None)[1][0].lezing is None


@pytest.fixture(scope="module")
def pop_df():
    return synthetic.population(20_000, seed=7)


@pytest.fixture
def small_population(monkeypatch, pop_df):
    monkeypatch.setattr(cli, "open_population",
                        lambda args, cfg: Population.from_dataframe(pop_df))


def _rounded_dataset(tmp_path, pop_df):
    ds = synthetic.sample(pop_df, 60, seed=3, gemeente="Zwolle")
    ds["bouwjaar"] = (ds["bouwjaar"] / 5).round().astype(int) * 5
    path = tmp_path / "afgerond.csv"
    ds[["bouwjaar", "oppervlakte"]].to_csv(path, sep=";", index=False)
    return path


def test_cli_proposes_rounding_and_reports_the_other_reading(tmp_path, pop_df, small_population,
                                                             capsys):
    path = _rounded_dataset(tmp_path, pop_df)
    out = tmp_path / "uit"
    assert cli.main(["assess", str(path), "--qid", "bouwjaar=bouwjaar",
                     "--qid", "oppervlakte=oppervlakte", "--scope", "gemeente=Zwolle",
                     "--out", str(out)]) == 0
    err = capsys.readouterr()
    assert "veelvouden van 5" in err.err and "naar beneden" in err.out
    s = json.loads((out / "samenvatting.json").read_text(encoding="utf-8"))
    (row,) = s["lezingen"]
    assert row["kolom"] == "bouwjaar" and row["lezing"] == "afgerond op 5, naar het dichtstbij"
    exact = next(a for a in row["alternatieven"] if a["lezing"] == "zoals gepubliceerd")
    assert exact["publiceerbaar"] <= s["ok"]     # read as exact, k is smaller
    assert "## Lezing van de kolommen" in (out / "rapport.md").read_text(encoding="utf-8")


def test_cli_config_overrides_the_proposal(tmp_path, pop_df, small_population, capsys):
    path = _rounded_dataset(tmp_path, pop_df)
    cfg = tmp_path / "cfg.toml"
    cfg.write_text(f'dataset = "{path.as_posix()}"\nauto = false\n[qids]\nbouwjaar = "bouwjaar"\n'
                   'oppervlakte = "oppervlakte"\n[afronding]\nbouwjaar = "5 beneden"\n',
                   encoding="utf-8")
    out = tmp_path / "uit"
    assert cli.main(["assess", "--config", str(cfg), "--out", str(out)]) == 0
    assert "veelvouden" not in capsys.readouterr().err
    s = json.loads((out / "samenvatting.json").read_text(encoding="utf-8"))
    assert s["lezingen"][0]["lezing"] == "afgerond op 5, naar beneden"
    bad = tmp_path / "fout.toml"
    bad.write_text(f'dataset = "{path.as_posix()}"\nauto = false\n[qids]\nbouwjaar = "bouwjaar"\n'
                   '[afronding]\nbestaat_niet = 5\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.main(["assess", "--config", str(bad)])
