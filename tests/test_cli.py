import json

import pandas as pd
import pytest

from anonymate import Population, cli, synthetic


@pytest.fixture(scope="module")
def pop_df():
    return synthetic.population(20_000, seed=7)


@pytest.fixture
def small_population(monkeypatch, pop_df):
    monkeypatch.setattr(cli, "open_population",
                        lambda args, cfg: Population.from_dataframe(pop_df))


@pytest.fixture
def dataset(tmp_path, pop_df):
    ds = synthetic.sample(pop_df, 60, seed=3, gemeente="Zwolle")
    ds = ds.rename(columns={"oppervlakte": "surface", "bouwjaar": "construction_year"})
    path = tmp_path / "data.csv"
    ds[["postcode6", "huisnummer", "gemeente", "construction_year", "surface", "energielabel",
        "installatiedatum"]].to_csv(path, sep=";", index=False)
    return path


def test_detect_prints_table(dataset, capsys):
    assert cli.main(["detect", str(dataset)]) == 0
    out = capsys.readouterr().out
    assert "huisnummer" in out and "direct" in out and "bouwjaar" in out


def test_assess_writes_outputs_without_direct_identifiers(dataset, tmp_path, small_population,
                                                          capsys):
    out = tmp_path / "uit"
    rc = cli.main(["assess", str(dataset), "--auto", "--qid", "postcode6=geen",
                   "--scope", "gemeente=Zwolle", "--p", "0.2", "--out", str(out)])
    assert rc == 0
    pub = pd.read_csv(out / "publiceerbaar.csv", sep=",")
    assert "huisnummer" not in pub.columns
    s = json.loads((out / "samenvatting.json").read_text(encoding="utf-8"))
    assert s["records"] == 60 and s["p"] == 0.2 and s["afbakening"] == "gemeente=Zwolle"
    assert "postcode6" not in s["qids"]
    assert len(pub) == s["ok"]
    assert (out / "rapport.md").read_text(encoding="utf-8").startswith("# Herleidbaarheidstoets")


def test_config_file_with_actions(dataset, tmp_path, small_population):
    cfg = tmp_path / "cfg.toml"
    cfg.write_text(f'''
dataset = "{dataset.as_posix()}"
p = 0.1
scenario = "register"
weglaten = ["postcode6"]
[qids]
construction_year = "bouwjaar"
surface = "oppervlakte"
gemeente = "gemeente"
[afbakening]
gemeente = ["Zwolle"]
[[acties]]
type = "bin"
column = "construction_year"
width = 20
[[acties]]
type = "suppress"
column = "surface"
''', encoding="utf-8")
    out = tmp_path / "uit"
    assert cli.main(["assess", "--config", str(cfg), "--out", str(out)]) == 0
    s = json.loads((out / "samenvatting.json").read_text(encoding="utf-8"))
    assert s["qids"] == ["construction_year", "surface", "gemeente"]
    assert len(s["stappen"]) == 3
    pub = pd.read_csv(out / "publiceerbaar.csv")
    assert "postcode6" not in pub.columns
    assert pub["surface"].isna().all()
    assert pub["construction_year"].astype(str).str.fullmatch(r"\d{4}-\d{4}").all()


def test_suggest_runs(dataset, small_population, capsys):
    assert cli.main(["suggest", str(dataset), "--auto", "--qid", "postcode6=geen",
                     "--scope", "gemeente=Zwolle", "--doel", "0.8"]) == 0
    assert "uitgangssituatie" in capsys.readouterr().out


def test_bad_p_is_reported(dataset, small_population, capsys):
    assert cli.main(["assess", str(dataset), "--auto", "--p", "0.5"]) == 1
    assert "p moet tussen" in capsys.readouterr().err


def test_scope_parsing():
    s = cli.parse_scope({"bouwjaar": "1900-1989", "eengezins": True,
                         "gemeente": ["Zwolle", "Deventer"]}, None)
    assert s.criteria["bouwjaar"].lo == 1900 and s.criteria["bouwjaar"].hi == 1989
    assert s.criteria["eengezins"].values == {"true"}
    assert s.criteria["gemeente"].values == {"Zwolle", "Deventer"}


def test_link_adds_register_values_and_never_publishes_address(tmp_path, pop_df,
                                                                small_population):
    base = pop_df.drop_duplicates(["postcode6", "huisnummer"], keep=False)
    base = base[base["gemeente"] == "Zwolle"].head(30)
    ds = pd.DataFrame({"pc": base["postcode6"].str[:4] + " " + base["postcode6"].str[4:],
                       "nr": base["huisnummer"].astype(str),
                       "verbruik__kWh": 3000})
    path = tmp_path / "adressen.csv"
    ds.to_csv(path, index=False)
    out = tmp_path / "uit"
    assert cli.main(["assess", str(path), "--koppel", "pc,nr",
                     "--qid", "register_bouwjaar=bouwjaar", "--qid", "register_gemeente=gemeente",
                     "--p", "0.2", "--out", str(out)]) == 0
    pub = pd.read_csv(out / "publiceerbaar.csv")
    assert not {"pc", "nr", "register_gekoppeld"} & set(pub.columns)
    per = pd.read_csv(out / "rapport_per_record.csv")
    assert list(per["register_bouwjaar"]) == list(base["bouwjaar"])


def test_config_noise_and_tolerance(dataset, tmp_path, small_population):
    cfg = tmp_path / "ruis.toml"
    cfg.write_text(f'''
dataset = "{dataset.as_posix()}"
p = 0.2
auto = false
[qids]
construction_year = "bouwjaar"
surface = "oppervlakte"
[tolerantie]
construction_year = 2
[[acties]]
type = "ruis"
column = "surface"
max = 10
seed = 4
''', encoding="utf-8")
    out = tmp_path / "uit"
    assert cli.main(["assess", "--config", str(cfg), "--out", str(out)]) == 0
    s = json.loads((out / "samenvatting.json").read_text(encoding="utf-8"))
    assert s["stappen"][1]["stap"] == "surface: ruis tot ±10"
    original = pd.read_csv(dataset, sep=";")
    pub_all = pd.read_csv(out / "rapport_per_record.csv")
    assert (pub_all["surface"] - original["surface"]).abs().max() <= 10


def test_tolerance_for_unknown_column_is_an_error(dataset, tmp_path, small_population):
    cfg = tmp_path / "fout.toml"
    cfg.write_text(f'dataset = "{dataset.as_posix()}"\nauto = false\n[qids]\nsurface = "oppervlakte"\n'
                   '[tolerantie]\nbestaat_niet = 3\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.main(["assess", "--config", str(cfg)])


def test_afronding(monkeypatch, capsys, tmp_path):
    import numpy as np
    rng = np.random.default_rng(1)
    pop = pd.DataFrame({"sig_H": rng.normal(250, 60, 3000).round(2),
                        "knmi_station": rng.choice(["260", "278", "290"], 3000),
                        "eengezins": True})
    monkeypatch.setattr(cli, "open_population",
                        lambda args, cfg: Population.from_dataframe(pop))
    out = tmp_path / "afronding.csv"
    assert cli.main(["afronding", "--kolom", "warmteverlies=1,10,50", "--ook", "knmi_station",
                     "--scope", "eengezins=true", "--out", str(out)]) == 0
    t = pd.read_csv(out)
    assert list(t["stap_sig_H"]) == [1, 10, 50]
    share = t["% in groep < 11"]
    assert share.is_monotonic_decreasing and share.iloc[0] > share.iloc[-1]
    assert "% in groep < 11" in capsys.readouterr().out


def test_help_on_a_windows_console():
    """`anonymate assess --help` crashed on a cp1252 console on the δ in the help text."""
    import os
    import subprocess
    import sys
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    out = subprocess.run([sys.executable, "-m", "anonymate.cli", "assess", "--help"],
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr.decode(errors="replace")
    assert "δ".encode() in out.stdout


def test_config_dataset_relative_to_config_and_candidates(dataset, tmp_path, small_population,
                                                          monkeypatch):
    sub = tmp_path / "configs"
    sub.mkdir()
    (sub / "d.csv").write_text(dataset.read_text(encoding="utf-8"), encoding="utf-8")
    cfg = sub / "c.toml"
    cfg.write_text('''
dataset = "d.csv"
p = 0.33
weglaten = ["postcode6", "huisnummer"]
[qids]
construction_year = "bouwjaar"
surface = "oppervlakte"
energielabel = "energielabel"
gemeente = "gemeente"
''', encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # not the config's directory
    out = tmp_path / "uit"
    assert cli.main(["assess", "--config", str(cfg), "--out", str(out), "--kandidaten"]) == 0
    s = json.loads((out / "samenvatting.json").read_text(encoding="utf-8"))
    assert s["records"] == 60
    per_record = pd.read_csv(out / "rapport_per_record.csv")
    cand = pd.read_parquet(out / "kandidaten_NIET_PUBLICEREN" / "kandidaten.parquet")
    at_risk = per_record[(per_record["status"] == "risico") & (per_record["k_populatie"] <= 100)]
    assert len(at_risk) > 0
    assert len(cand) == at_risk["k_populatie"].sum()
    assert {"dataset_postcode6", "dataset_huisnummer", "vbo_id"} <= set(cand.columns)
    assert "NIET PUBLICEREN" in (out / "kandidaten_NIET_PUBLICEREN" / "LEESMIJ.md").read_text(
        encoding="utf-8")


def test_link_with_nullable_string_columns(pop_df):
    """An empty toevoeging in a pandas 'string' column is pd.NA; it became the text '<NA>' and
    then no address matched at all."""
    from anonymate.link import link
    base = pop_df.drop_duplicates(["postcode6", "huisnummer"], keep=False).head(10)
    ds = pd.DataFrame({"pc": base["postcode6"].values,
                       "nr": base["huisnummer"].values,
                       "letter": pd.array([None] * 10, dtype="string"),
                       "toev": pd.array([None] * 10, dtype="string")})
    got = link(ds, Population.from_dataframe(pop_df), postcode="pc", huisnummer="nr",
               huisletter="letter", toevoeging="toev")
    assert got["register_gekoppeld"].all()


def test_quick_start_example_from_the_readme(tmp_path, small_population):
    """The example file and commands in 'Snel beginnen' keep working."""
    from pathlib import Path
    voorbeeld = Path(__file__).parents[1] / "docs" / "voorbeeld" / "woningen.csv"
    assert cli.main(["detect", str(voorbeeld)]) == 0
    out = tmp_path / "uit"
    assert cli.main(["assess", str(voorbeeld), "--auto", "--qid", "postcode=direct",
                     "--synthetic", "--out", str(out)]) == 0
    s = json.loads((out / "samenvatting.json").read_text(encoding="utf-8"))
    assert s["records"] == 62 and "postcode" not in s["qids"]
    pub = pd.read_csv(out / "publiceerbaar.csv")
    assert not {"postcode", "huisnummer"} & set(pub.columns)
    # the example must never hold a real address: SA, SD and SS are not used by PostNL
    ds = pd.read_csv(voorbeeld, dtype=str)
    assert ds["postcode"].str[-2:].isin(["SA", "SD", "SS"]).all()
