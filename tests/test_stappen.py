"""The steps of the window as plain functions (anonymate.stappen), on the practice data."""
import ast
import functools
import math
import re
from pathlib import Path

import pandas as pd
import pytest

from anonymate import stappen, voorbeeld
from anonymate.detect import derive_h3_columns, detect
from anonymate.population import Population
from anonymate.risk import Status
from anonymate.stappen import (WEATHER_H3, WEATHER_STATION, add_uhi, add_weather, bin_uhi, cell_text,
                               guess_gps, houses_for, k_histogram, link_columns, link_kwargs,
                               locations, merge_scope, population_with_uhi, read_uhi,
                               readable_error, record_card, region_scope, region_text,
                               representativeness_lines)

SRC = Path(stappen.__file__).parent

# what the browser runs: no network, no Qt, no local store
NETWORK = {"urllib", "http", "socket", "ssl", "requests", "ftplib", "smtplib", "subprocess"}
QT = {"PySide6", "PyQt5", "PyQt6", "shiboken6"}


@pytest.mark.parametrize("module", ["kaart", "stappen"])
def test_core_imports_no_network_no_qt_no_store(module):
    tree = ast.parse((SRC / f"{module}.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):          # also imports inside functions
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [("." * node.level) + (node.module or "")]
            if node.level and not node.module:
                names = ["." + a.name for a in node.names]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            assert top not in NETWORK, f"{module} importeert {name}"
            assert top not in QT, f"{module} importeert Qt: {name}"
            assert not name.lstrip(".").startswith("gui"), f"{module} importeert {name}"
            assert name.lstrip(".") != "store", f"{module} importeert de lokale opslag"


@functools.lru_cache(maxsize=1)
def _frame() -> pd.DataFrame:
    return voorbeeld.population()          # takes a while: once for all tests here


@pytest.fixture(scope="module")
def practice():
    pop = Population.from_dataframe(_frame())
    df, _ = derive_h3_columns(pd.read_csv(voorbeeld.WONINGEN, dtype={"postcode": str}))
    return df, pop


def test_link_columns_and_gps_guess(practice):
    df, _ = practice
    found = detect(df)
    assert link_columns(found) == ["postcode", "huisnummer"]
    assert link_columns([]) == []
    assert guess_gps(["installatiedatum", "gps_lat", "salon_m2", "Longitude"]) \
        == ("gps_lat", "Longitude")
    assert guess_gps(["a", "b"]) == ("", "")
    assert not re.search(stappen.GPS_LAT, "installatiedatum", re.I)
    assert stappen.numeric_columns(df) == ["huisnummer", "bouwjaar", "oppervlakte",
                                          "installatiedatum", "jaarverbruik_gas__m3"]


def test_link_kwargs_messages(practice):
    df, _ = practice
    assert link_kwargs("postcode, huisnummer", df.columns) == {"postcode": "postcode",
                                                                "huisnummer": "huisnummer"}
    assert link_kwargs(["woning_id"], df.columns) == {"vbo_id": "woning_id"}
    with pytest.raises(ValueError, match="koppelkolommen zijn leeg"):
        link_kwargs("", df.columns)
    with pytest.raises(ValueError, match="niet in de dataset: nope"):
        link_kwargs("nope,huisnummer", df.columns)


def test_locations_from_the_link_and_from_gps(practice):
    df, pop = practice
    loc = locations(df, pop, source="koppel", link_cols="postcode,huisnummer")
    assert list(loc.columns) == ["lat", "lon", "postcode6"] and len(loc) == len(df)
    assert loc["lat"].notna().sum() > 0.8 * len(df)
    assert loc["lat"].dropna().between(50, 54).all()
    gps = df.assign(la=loc["lat"], lo=loc["lon"])
    same = locations(gps, pop, source="gps", gps=("la", "lo"))
    assert same["lat"].equals(loc["lat"]) and same["postcode6"].isna().all()
    with pytest.raises(ValueError, match="GPS-kolommen"):
        locations(df, pop, source="gps", gps=("", ""))


def test_add_weather_h3_gives_a_zone_column(practice):
    df, pop = practice
    new, added, tol = add_weather(df, pop, method="h3", level=4, sigma=5.0, seed=7,
                                  count_noise=True, source="koppel",
                                  link_cols="postcode,huisnummer")
    assert added == {WEATHER_H3: "h3_cel"} and tol == 5.0
    assert WEATHER_H3 in new.columns and WEATHER_H3 not in df.columns
    cells = new[WEATHER_H3].dropna()
    assert len(cells) > 0.8 * len(df) and cells.str.startswith("84").all()
    again, _, _ = add_weather(df, pop, method="h3", level=4, sigma=5.0, seed=7,
                              locations=locations(df, pop, link_cols="postcode,huisnummer"))
    assert again[WEATHER_H3].equals(new[WEATHER_H3])                 # the seed fixes the noise
    _, _, none = add_weather(df, pop, method="h3", level=4, sigma=5.0, seed=7,
                             count_noise=False, link_cols="postcode,huisnummer")
    assert none == 0.0


def test_add_weather_knmi_and_errors(practice):
    df, pop = practice
    nowhere = pd.DataFrame({"lat": math.nan, "lon": math.nan, "postcode6": None}, index=df.index)
    # the made-up Netherlands has no station per dwelling
    with pytest.raises(ValueError, match="de populatie kent geen KNMI-stations"):
        add_weather(df, pop, method="knmi", link_cols="postcode,huisnummer")
    with_stations = Population.from_dataframe(
        _frame().head(len(df)).assign(vbo_id=[str(i).zfill(16) for i in range(len(df))],
                                      knmi_station="260"))
    with pytest.raises(ValueError, match="KNMI-station vanuit GPS"):
        add_weather(df, with_stations, method="knmi", source="gps", locations=nowhere)
    ids = df.assign(vbo=[str(i).zfill(16) for i in range(len(df))])
    new, added, tol = add_weather(ids, with_stations, method="knmi", link_cols="vbo")
    assert added == {WEATHER_STATION: "knmi_station"} and tol == 0.0
    assert (new[WEATHER_STATION] == "260").all()
    stale = df.assign(**{WEATHER_H3: "x", "uhi": 1.0})
    cleared, added, tol = add_weather(stale, pop, method=None,
                                      locations=pd.DataFrame(index=df.index))
    assert WEATHER_H3 not in cleared.columns and "uhi" not in cleared.columns
    assert added == {} and tol is None


def test_uhi_read_bin_and_join(tmp_path, practice):
    df, pop = practice
    path = tmp_path / "uhi.csv"
    path.write_text("pc6,uhi\n1234AB,0.4\n5678 CD,1.7\n", encoding="utf-8")
    assert read_uhi(str(path)) == {"1234AB": 0.4, "5678CD": 1.7}
    with pytest.raises(ValueError, match="kies een UHI-bestand"):
        read_uhi("")
    with pytest.raises(ValueError, match="niet gevonden"):
        read_uhi(str(tmp_path / "nee.csv"))
    (tmp_path / "kaal.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="pc6"):
        read_uhi(str(tmp_path / "kaal.csv"))
    raw = pd.DataFrame({"uhi": [0.4, 0.74, 1.7, None]})
    binned = bin_uhi(raw, 0.5)
    assert binned["uhi"].notna().tolist() == [True, True, True, False]
    assert binned["uhi"].iloc[0] == binned["uhi"].iloc[0] and binned["uhi"].iloc[0] != raw["uhi"].iloc[2]
    loc = pd.DataFrame({"postcode6": ["1234AB", "5678CD", "9999ZZ"]})
    out = add_uhi(pd.DataFrame(index=loc.index), loc, read_uhi(str(path)), 0.5)
    assert out["uhi"].notna().tolist() == [True, True, False]
    # the join from a table the caller read itself
    table = pd.read_csv(path)
    bare = Population.from_dataframe(_frame().drop(columns=["uhi"], errors="ignore"))
    joined = population_with_uhi(bare, table)
    assert "uhi" in joined.columns and "uhi" not in bare.columns
    pop = bare
    pcs = pop.con.execute(f"SELECT postcode6 FROM {pop.relation} LIMIT 1").fetchone()[0]
    table = pd.DataFrame({"PC6": [pcs], "UHI_gem": [1.25]})
    joined = population_with_uhi(pop, table)
    row = joined.con.execute(f"SELECT uhi FROM {joined.relation} WHERE postcode6 = ? "
                             "LIMIT 1", [pcs]).fetchone()
    assert row == (1.25,)
    assert population_with_uhi(joined, table) is joined              # already has one


def test_region_and_scope(practice):
    df, pop = practice
    assert region_scope(True, ["Utrecht"], "Zwolle") == {}
    assert region_scope(False, ["Utrecht"], "Zwolle, Deventer ,") == {
        "provincie": ["Utrecht"], "gemeente": ["Zwolle", "Deventer"]}
    assert region_scope(False, [], "") == {}
    assert region_text({}) == "heel Nederland"
    assert region_text({"provincie": ["Utrecht"], "gemeente": ["Zwolle"]}) == "Utrecht, Zwolle"
    assert region_text({"gemeente": ["a", "b", "c"]}) == "3 gebieden"
    assert merge_scope({}, "", pop).is_everything()
    scope = merge_scope({"provincie": ["Utrecht"]}, "bouwjaar=1900-1989", pop)
    assert not scope.is_everything()
    assert pop.within(scope).size() < pop.size()


def test_cell_text_verdict_thresholds():
    stats = {"niveau": 5, "woningen": 40, "met_buren": 300, "gebied_km2": 210.0, "k_eff": 30.0,
             "heat_km2": 31.0, "heat_woningen": 62}
    for k_eff, verdict in ((30, "ruim genoeg"), (29.9, "genoeg"), (15, "genoeg"),
                           (14.9, "te weinig")):
        card = cell_text({**stats, "k_eff": k_eff}, 5, 10, 15)
        assert card["verdict"] == verdict
        assert f"voor de locatie alleen {verdict}." in stappen.plain(card["after"][-1][1])
    assert stappen.cell_verdict(30, 15) == "ruim genoeg" and stappen.cell_verdict(15, 15) == "genoeg"
    card = cell_text(stats, 5, 10, 15, land_share=0.5, in_dataset=1)
    assert card["title"] == "Cel van niveau 5 · 210 km², waarvan ~105 km² land"
    assert dict(card["rows"]) == {"In deze cel": "**40** woningen",
                                  "Met de zes buurcellen": "300 woningen",
                                  "Uit je dataset": "1 woning kreeg deze cel als weerzone"}
    assert [a for a, _ in card["after"]] == ["Zonder ruis", "Met ruis (σ 10 km)",
                                             "Waar de woning dan ligt", "Tegen je norm (k ≥ 15)"]
    assert cell_text(stats, 5, 10, 15, land_share=1.0)["title"] == "Cel van niveau 5 · 210 km²"
    assert "nog onbekend" in dict(cell_text(stats, 5, 10, 15)["rows"])["Uit je dataset"]
    # no noise: only what the cell holds; no dwellings: nothing after
    assert cell_text(stats, 5, 0, 15)["after"][0][0] == "Als deze cel gepubliceerd wordt"
    assert cell_text({**stats, "woningen": 0}, 5, 10, 15)["after"] == []
    html = stappen.cell_html(cell_text({**stats, "k_eff": 3.0}, 5, 10, 15))
    assert "<b>te weinig</b>" in html and "<span style='color:#C05A12'><b>oranje</b></span>" in html
    assert html.startswith("<b>Wat er ligt</b><table")


def test_cell_text_from_a_real_cell(practice):
    from anonymate.kaart import MapData, border_rings, land_layer
    _, pop = practice
    data = MapData(pop, voorbeeld.stations(), border_rings(), True, land_layer())
    cell = "85196817fffffff"
    card = cell_text(data.cell_stats(cell, 10.0), 5, 10, 11, land_share=data.land_share(cell))
    assert card["title"].startswith("Cel van niveau 5 · 209 km², waarvan ~")
    assert card["verdict"] == "ruim genoeg"                         # k_eff 64.7 against k = 11


def test_record_card():
    row = pd.Series({"bouwjaar": 1988, "woningtype": "twee_onder_een_kap", "energielabel": None,
                     "k": 4.0, "delta": 0.25, "status": Status.AT_RISK, "redenen": ""})
    title, text = record_card(row, 4.0, 11, 0.25, Status.AT_RISK, index=2)
    assert title == "Woning 3 · te herleidbaar"
    assert text == ("1988, twee onder een kap. In de populatie: 4 zulke woningen. Van die woningen "
                    "zit 25% in de dataset. De norm vraagt er 11: deze woning komt niet in "
                    "publiceerbaar.csv.")
    title, text = record_card(row, 2500.0, 11, math.nan, Status.OK, index=0)
    assert title == "Woning 1 · publiceerbaar"
    assert text.endswith("In de populatie: 2.500 zulke woningen. Dat haalt de norm.")
    title, text = record_card(row, math.nan, 11, math.nan, Status.NO_MATCH, index=0)
    assert title == "Woning 1 · geen match" and "geen enkele woning in de populatie past" in text


def test_houses_and_k_histogram():
    assert houses_for(5, 11) == (5, 11, 0)
    assert houses_for(11, 11) == (11, 11, 0)
    assert houses_for(500, 11) == (20, 20, 480)
    assert houses_for(500, 30, cap=40) == (40, 40, 460)
    assert houses_for(math.nan, 11) == (0, 11, 0) and houses_for(None, 11) == (0, 11, 0)
    bins = k_histogram([0, 3, 10, 11, 50, 120, 5000, math.nan], 11)
    assert [(a, b) for a, b, _ in bins] == [(0, 10), (11, 30), (31, 100), (101, 300),
                                             (301, 1000), (1001, math.inf)]
    assert [c for *_, c in bins] == [4, 1, 1, 1, 0, 1]
    bins = k_histogram([1, 20, 40, 400], 50)                        # a higher norm drops classes
    assert [(a, b) for a, b, _ in bins] == [(0, 49), (50, 100), (101, 300), (301, 1000),
                                             (1001, math.inf)]
    assert [c for *_, c in bins] == [3, 0, 0, 1, 0]
    from anonymate.gui_tekening import houses_for as old_houses_for
    assert old_houses_for is houses_for


def test_representativeness_lines(practice):
    df, _ = practice
    keep = pd.Series([True] * len(df))
    keep.iloc[:5] = False
    lines = representativeness_lines(df, keep, ["bouwjaar", "oppervlakte", "woningtype"])
    assert len(lines) == 1 and lines[0].startswith("Representativiteit: ")
    assert representativeness_lines(df, keep, ["bestaat_niet"]) == []


def test_readable_error():
    assert readable_error("ValueError: kies iets / technisch") == "kies iets"
    assert readable_error(ValueError("kies iets")) == "kies iets"
    assert readable_error("FileNotFoundError: weg") == "weg"
    assert readable_error("gewone tekst") == "gewone tekst"
    assert readable_error(KeyError("x")).startswith("Er ging iets onverwachts mis.")
    assert readable_error("KeyError: 'x'").endswith("KeyError: 'x'")


def test_markup():
    assert stappen.html("a **b** !!c!!") == "a <b>b</b> <span style='color:#C05A12'><b>c</b></span>"
    assert stappen.plain("a **b** !!c!!") == "a b c"
    assert stappen.nr(12345.6) == "12.346" and stappen.nl(0.5, 2) == "0,50"


def test_numeric_column():
    from anonymate.stappen import numeric_column, numeric_flags
    assert numeric_column(["1.234", "0,35", "", "12k", "45%", "-3", "1e-05", "3.5"])
    assert numeric_column([1, 2.5, None, float("nan")])
    assert numeric_column(["2020", "2021"])
    assert not numeric_column(["1960-1969", "1970-1979"])
    assert not numeric_column(["12", "onbekend"])
    assert not numeric_column(["", None]) and not numeric_column([])
    assert not numeric_column([True, False])
    assert numeric_flags([["a", "1", ""], ["b", "0,5", "x"]], 3) == [False, True, False]


def test_target_share_is_shared():
    import inspect
    from anonymate import cli, generalize, gui, web
    assert generalize.TARGET_SHARE == 0.95
    assert inspect.signature(web.suggest).parameters["target_share"].default is None  # = the constant
    assert gui.TARGET_SHARE is generalize.TARGET_SHARE and cli.TARGET_SHARE == generalize.TARGET_SHARE
    assert stappen.target_label() == "doel zoektocht: 95% publiceerbaar"
    assert stappen.target_note().startswith("De zoektocht stopt zodra 95% van de woningen")
