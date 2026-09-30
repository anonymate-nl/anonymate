"""Step 5 of the web facade (weather location, map, UHI, weather trace) against the desktop paths.

Every function is compared with the code the Windows app runs (kaart, stappen, weerspoor), and every
answer must survive a JSON round trip: that is all the page ever sees.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from anonymate import kaart, stappen, voorbeeld, web

WEB = Path(web.__file__).parents[2] / "web"


@pytest.fixture(scope="module")
def population_file(tmp_path_factory):
    return voorbeeld.write_population(tmp_path_factory.mktemp("weer") / "oefenpopulatie.parquet")


@pytest.fixture()
def practice(population_file):
    web.S.population = None
    web.S.region, web.S.scope_text, web.S.scenario = {}, "", "register"
    return web.open_practice(str(population_file))


def _roundtrip(x):
    assert json.loads(json.dumps(x)) == x
    return x


def test_map_layers_are_the_desktop_layers(practice):
    L = _roundtrip(web.map_layers())
    md = kaart.ScopedMapData(web.S.population, voorbeeld.stations(), kaart.border_rings(),
                             kaart.land_layer())
    assert len(L["base"]) == len(md.base) and len(L["land"]) == len(md.land)
    assert [c[0] for c in L["cities"]] == [c[0] for c in md.cities]
    assert [v["id"] for v in L["voronoi"]] == list(md.voronoi)
    assert [s["id"] for s in L["stations"]] == list(voorbeeld.stations()["knmi_station"])
    assert L["bbox"] == [round(x, 4) for x in md.bbox]
    assert all(len(p) == 2 for p in L["base"][0]) and L["colours"]["stations"]
    assert web.map_layers() is L              # made once


def test_weather_h3_equals_add_weather(practice):
    before = web.S.df.copy()
    link = ",".join(practice["link_columns"])
    r = _roundtrip(web.weather(source="koppel", link_cols=link, method="h3", level=5, sigma=10,
                               count_noise=True))
    seed = web.S.seed
    want, added, tol = stappen.add_weather(before, None, method="h3", level=5, sigma=10.0,
                                           seed=seed, count_noise=True, source="koppel",
                                           link_cols=link, locations=stappen.locations(
                                               before, web.S.population, link_cols=link))
    assert list(web.S.df["weerzone_h3"]) == list(want["weerzone_h3"])
    assert r["added"] == {"weerzone_h3": "h3_cel"} and added == {"weerzone_h3": "h3_cel"}
    assert r["rows"] == [{"column": "weerzone_h3", "proposal": "weerlocatie: h3_cel",
                          "default": "h3_cel", "reason": "toegevoegd in stap 5"}]
    assert web.S.tolerance == tol == 10.0 and r["sub"] == "H3 niveau 5, σ 10 km"
    assert r["found"] == 62 and "62 van 62" in r["status"]
    assert web.S.mapping["weerzone_h3"] == "h3_cel"
    web.weather(source="koppel", link_cols=link, method="h3", level=5, sigma=10,
                count_noise=False)
    assert web.S.seed == seed and web.S.tolerance == 0.0        # the noise is drawn once
    assert list(web.S.df["weerzone_h3"]) == list(want["weerzone_h3"])
    assert web.weather_sub(5, 10) == "H3 niveau 5, σ 10 km"
    off = web.weather(source="koppel", link_cols=link, method=None)
    assert off["added"] == {} and off["sub"] == "niet toegevoegd"
    assert "weerzone_h3" not in web.S.df.columns and "weerzone_h3" not in web.S.mapping


def test_weather_gps_marks_the_source_columns(practice):
    df = web.S.df
    web.S.df = df.assign(lat=52.1, lon=5.1)
    web.S.mapping.update(lat="geen", lon="geen")
    r = web.weather(source="gps", gps=["lat", "lon"], method="h3", level=6, sigma=5)
    assert r["direct"] == ["lat", "lon"] and web.S.mapping["lat"] == "direct"
    assert set(web.S.df["weerzone_h3"].dropna()) and r["sub"] == "H3 niveau 6, σ 5 km"


def test_weather_needs_link_columns(practice):
    with pytest.raises(ValueError, match="koppelkolommen"):
        web.weather(source="koppel", link_cols="", method="h3")


def test_map_cells_cell_and_station_equal_the_desktop(practice):
    link = ",".join(practice["link_columns"])
    assert web.map_cells(5)["dataset"] == []
    web.weather(source="koppel", link_cols=link, method="h3", level=5, sigma=10)
    cells = _roundtrip(web.map_cells(5))
    counts = web.S.df["weerzone_h3"].value_counts().to_dict()
    assert {d["cell"]: d["n"] for d in cells["dataset"]} == counts
    md = kaart.ScopedMapData(web.S.population, voorbeeld.stations(), [], kaart.land_layer())
    assert len(cells["population"]) == len(md.counts(5))
    assert web.map_cells(6)["population"] == [] and len(web.map_layers()["base"]) == len(md.base)

    cell = cells["dataset"][0]["cell"]
    r = _roundtrip(web.map_cell(cell, 10, 0.09))
    want = md.cell_stats(cell, 10.0)
    for k in ("woningen", "met_buren", "k_eff", "gebied_km2", "niveau", "heat_woningen",
              "heat_km2"):
        assert r["stats"][k] == pytest.approx(want[k])
    assert {h["cell"] for h in r["heat"]} == set(want["heat"])
    assert max(h["weight"] for h in r["heat"]) == pytest.approx(1.0)
    assert len(r["neighbours"]) == 6 and r["ring"][0] and r["focus"]["km"] > 0
    card = stappen.cell_text(want, 5, 10, 11, land_share=md.land_share(cell),
                             in_dataset=counts[cell])
    assert r["card"] == json.loads(json.dumps(card))
    assert web.map_cell(cell, 0, 0.09)["card"]["verdict"] is None       # without noise
    with pytest.raises(ValueError):
        web.map_cell("geen-cel", 10)
    hit = _roundtrip(web.map_hit(52.1, 5.1, 5))
    assert hit["cell"] == web.map_cell(hit["cell"], 0)["cell"] and len(hit["neighbours"]) == 6

    s = _roundtrip(web.map_station(52.1, 5.1))
    station, count = md.station_at(52.1, 5.1)
    assert s["station"] == station and s["title"] == f"KNMI-station {md.station_name(station)}"
    assert s["text"] == (f"Woningen waarvoor dit het dichtstbijzijnde station is: "
                         f"{stappen.nr(count)}. Woningen uit de dataset: "
                         "~~nog onbekend: voeg eerst de weerlocatie toe~~")


def test_knmi_weather_in_practice_mode_and_the_station_card(practice):
    link = ",".join(practice["link_columns"])
    before = _roundtrip(web.map_station(52.1, 5.18))                 # De Bilt
    assert before["count"] > 0 and before["in_dataset"] is None
    assert "nog onbekend" in before["text"] and "dataset: 0" not in before["text"]
    web.weather(source="koppel", link_cols=link, method="knmi")
    assert web.S.df[stappen.WEATHER_STATION].notna().any()
    home = web.S.df[stappen.WEATHER_STATION].dropna().index[0]
    station = web.S.df.loc[home, stappen.WEATHER_STATION]
    row = voorbeeld.stations().set_index("knmi_station").loc[station]
    after = _roundtrip(web.map_station(float(row["lat"]), float(row["lon"])))
    assert after["station"] == station and after["count"] > 0
    assert after["in_dataset"] == int((web.S.df[stappen.WEATHER_STATION] == station).sum()) > 0
    assert f"Woningen uit de dataset: {after['in_dataset']}." in after["text"]


def test_tolerance_reaches_the_assessment(practice):
    link = ",".join(practice["link_columns"])
    web.weather(source="koppel", link_cols=link, method="h3", level=5, sigma=10)
    web.lock_norm(0.09)
    qids, _direct, _pop = web._inputs(dict(web.S.mapping), None, None)
    assert [q.tolerance for q in qids if q.column == "weerzone_h3"] == [10.0]


def test_uhi_joins_like_population_with_uhi(practice, tmp_path):
    pop = voorbeeld.population().drop(columns=["uhi"])
    web.S.population = web.Population.from_dataframe(pop, web.Snapshot({"t": "t"}))
    link = ",".join(practice["link_columns"])
    frame = pd.DataFrame({"pc6": sorted(set(pop["postcode6"]))[:2000]})
    frame["uhi"] = [(i % 30) / 10 for i in range(len(frame))]
    f = tmp_path / "uhi.csv"
    frame.to_csv(f, index=False)
    r = _roundtrip(web.uhi("uhi.csv", str(f), 0.5, source="koppel", link_cols=link))
    assert not f.exists() and r["added"] == {"uhi": "uhi"} and r["sub"] == "UHI"
    loc = stappen.locations(web.S.df, web.S.population, link_cols=link)
    want = stappen.add_uhi(web.S.df.drop(columns=["uhi"]), loc, stappen.uhi_table(frame), 0.5)
    assert list(web.S.df["uhi"]) == list(want["uhi"])
    web.lock_norm(0.09)
    _q, _d, scoped = web._inputs(dict(web.S.mapping), None, None)
    direct = stappen.population_with_uhi(web.S.population, frame)
    sql = "SELECT count(uhi), sum(uhi) FROM {}"
    assert scoped.con.execute(sql.format(scoped.relation)).fetchone() == \
        direct.con.execute(sql.format(direct.relation)).fetchone()
    assert "uhi" in scoped.columns


def test_uhi_needs_no_file_when_the_population_has_it(practice):
    assert "uhi" in web.S.population.columns
    assert "populatie" in web.uhi_bron()
    link = ",".join(practice["link_columns"])
    r = _roundtrip(web.uhi("", None, 0.5, source="koppel", link_cols=link))
    assert r["added"] == {"uhi": "uhi"} and r["sub"] == "UHI"
    assert web.S.df["uhi"].notna().any()
    frame = stappen.uhi_from_population(web.S.population)
    loc = stappen.locations(web.S.df, web.S.population, link_cols=link)
    want = stappen.add_uhi(web.S.df.drop(columns=["uhi"]), loc, stappen.uhi_table(frame), 0.5)
    assert list(web.S.df["uhi"]) == list(want["uhi"])
    # the population has the column itself: no joined copy needed
    assert web.S.uhi_frame is None


def test_uhi_without_file_and_without_population_uhi_says_so(practice):
    pop = voorbeeld.population().drop(columns=["uhi"])
    web.S.population = web.Population.from_dataframe(pop, web.Snapshot({"t": "t"}))
    assert "geen UHI" in web.uhi_bron()
    with pytest.raises(ValueError, match="geen UHI"):
        web.uhi("", None, 0.5, source="koppel", link_cols=",".join(practice["link_columns"]))


def test_trace_equals_investigate_and_applies(practice):
    from anonymate.weerspoor import investigate, read_series_source
    info = _roundtrip(web.trace_open())
    assert info["example"] and info["key"] == voorbeeld.KEY and info["files"] == 1
    assert (info["id_col"], info["id_from"]) == ("woning_id", "kolom") and info["value_col"]
    with pytest.raises(ValueError, match="woning-ID"):
        web.trace(options={**info, "key": ""})
    seen = []
    r = _roundtrip(web.trace(options=info, progress=lambda f, t: seen.append((f, t))))
    series = read_series_source(voorbeeld.WEER, id_col=info["id_col"], time_col=info["time_col"],
                                value_col=info["value_col"], max_homes=300)
    want = investigate(series, voorbeeld.hourly(), voorbeeld.grid(), id_col="woning",
                       time_col="tijd", value_col="waarde")
    assert r["verdict"] == want.verdict and r["advice"] == want.advice and seen
    fractions = [f for f, _ in seen if f is not None]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0     # never back, ends at 100%
    assert any(0.2 < f < 1.0 for f in fractions)                        # investigate reports too
    assert len(r["findings"]) <= 8 and r["homes"] == len(want.per_home)
    before = web.S.df.copy()
    a = _roundtrip(web.trace_apply(5, 10))
    df, tol, summary = stappen.apply_trace(before, voorbeeld.KEY, want, web.S.population)
    assert list(web.S.df["weerzone_h3"]) == list(df["weerzone_h3"])
    assert a["tolerance"] == tol == web.S.tolerance and a["status"] == summary["status"]
    assert set(a["added"]) <= {"weerzone_h3", "weer_knmi_station"} and a["verdict"] == want.verdict


def test_trace_apply_needs_a_trace(practice):
    with pytest.raises(ValueError, match="weerspoor"):
        web.trace_apply()


def test_the_page_matches_the_facade():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'\$\("#([\w-]+)"\)', js)) | set(re.findall(r"\$\(`#([\w-]+)`\)", js))
    assert ids <= set(re.findall(r'id="([\w-]+)"', html))
    assert "volgt" not in re.search(r"const subs = \[.*?\];", js, re.S).group(0)
    import h3
    edge = {int(k): float(v) for k, v in
            re.findall(r"(\d): ([\d.]+)", re.findall(r"H3_EDGE = \{([^}]*)\}", js, re.S)[0])}
    area = {int(k): float(v) for k, v in
            re.findall(r"(\d): ([\d.]+)", re.findall(r"H3_AREA = \{([^}]*)\}", js, re.S)[0])}
    for level in range(4, 9):
        assert edge[level] == pytest.approx(h3.average_hexagon_edge_length(level, unit="km"))
        assert area[level] == pytest.approx(h3.average_hexagon_area(level, unit="km^2"))
    worker = (WEB / "worker.js").read_text(encoding="utf-8")
    for cmd in ("map_layers", "map_cells", "map_hit", "map_cell", "map_station", "weather", "uhi",
                "uhi_bron", "trace_open", "trace", "trace_apply"):
        assert f'case "{cmd}"' in worker and hasattr(web, cmd)


CHILD = r"""
import importlib.abc, json, sys

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "pyarrow":
            raise ImportError(f"{name} is niet beschikbaar (test)")

sys.meta_path.insert(0, Blocker())
from anonymate import web
o = web.open_practice(sys.argv[1])
web.lock_norm(0.09)
web.run()
first = "h3" in sys.modules
web.map_layers()
after_map = "h3" in sys.modules
web.weather(source="koppel", link_cols="postcode,huisnummer", method="h3")
web.trace_open()
LAZY = ("anonymate.cli", "anonymate.generalize", "anonymate.report", "anonymate.signature",
        "pyarrow")
print(json.dumps({"before": first, "after_map": after_map,
                  "lazy": [m for m in LAZY if m in sys.modules]}))
"""


def test_h3_only_loads_with_the_map_or_the_weather(population_file):
    done = subprocess.run([sys.executable, "-c", CHILD, str(population_file)],
                          capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["before"] is False and out["after_map"] is True
    assert out["lazy"] == []


def test_amsterdam_ships_with_anonymate():
    """The browser has no time zone database; anonymate carries Europe/Amsterdam itself."""
    import zoneinfo
    old = zoneinfo.TZPATH
    try:
        zoneinfo.reset_tzpath([str(web.ZONEINFO)])
        z = zoneinfo.ZoneInfo.no_cache("Europe/Amsterdam")
        assert z.key == "Europe/Amsterdam"
        stamp = pd.Timestamp("2026-01-15 12:00", tz="UTC").tz_convert(z)
        assert stamp.hour == 13
        summer = pd.Timestamp("2026-07-15 12:00", tz="UTC").tz_convert(z)
        assert summer.hour == 14
        web.alleen_amsterdam()
        assert zoneinfo.TZPATH[0] == str(web.ZONEINFO)
    finally:
        zoneinfo.reset_tzpath(list(old))


def test_background_loading_is_wired_and_its_imports_work():
    """The worker loads h3 and the modules of the later steps after the start, one shared promise
    per item; the imports it runs must exist."""
    worker = (WEB / "worker.js").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'case "background"' in worker and 'call("background")' in js
    assert worker.count('py.loadPackage("h3")') == 1          # one place, behind the shared promise
    imports = re.search(r'py\.runPython\("(import h3[^"]*)"(?: \+\s*"([^"]*)")*', worker, re.S)
    assert imports
    line = "".join(re.findall(r'"(import h3[^"]*|[^"]*anonymate[^"]*)"', worker.split("laadModules")[1]))
    exec(compile(line, "worker", "exec"), {})                  # noqa: S102 (our own import line)
    # the text "alles is geladen" is hidden until the worker reports every item as loaded
    assert re.search(r'id="klaaroffline" hidden>Alles is geladen: je kunt nu de internetverbinding '
                     r'verbreken\.<', html)
    assert 'alleGeladen = alles;' in js
    assert '$("#klaaroffline").hidden = !alleGeladen || offlineKlaar' in js
    assert "De rest wordt op de achtergrond geladen" in js


def test_a_cell_before_the_weather_is_unknown_and_after_it_a_number(practice):
    link = ",".join(practice["link_columns"])
    before = _roundtrip(web.map_cell(web.map_hit(52.78, 4.80, 5)["cell"], 10, 0.09))
    assert before["card"]["rows"][2] == [
        "Uit je dataset", "~~nog onbekend: voeg eerst de weerlocatie toe~~"]
    web.weather(source="koppel", link_cols=link, method="h3", level=5, sigma=10)
    cell = web.map_cells(5)["dataset"][0]["cell"]
    after = _roundtrip(web.map_cell(cell, 10, 0.09))
    assert re.fullmatch(r"\d+ woningen? kreeg deze cel als weerzone", after["card"]["rows"][2][1])
    # the dataset has zones of level 5: asking level 6 says so instead of 0
    other = _roundtrip(web.map_cell(web.map_hit(52.78, 4.80, 6)["cell"], 10, 0.09))
    assert "dataset heeft weerzones op niveau 5, niet op niveau 6" in other["card"]["rows"][2][1]


def test_the_page_greys_unknown_values_and_shows_the_band():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "~~.+?~~" in js and 'class: "onbekend"' in js and ".onbekend { color: var(--muted)" in html
    assert "function updateBand" in js and 'id="kaart-band"' in html
