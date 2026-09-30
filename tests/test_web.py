"""The web facade (anonymate.web) in CPython, and the guard that the computing core does no network.

The same facade runs in Pyodide in the browser (web/worker.js); what it returns must survive a
JSON round trip, because that is all the page ever sees.
"""
from __future__ import annotations

import ast
import io
import json
import zipfile
from pathlib import Path

import pytest

from anonymate import web

SRC = Path(web.__file__).parent

# the modules the browser runs; none of them may reach the network or the local store
CORE = ["candidates", "constraints", "detect", "explain", "generalize", "link", "population",
        "publicatie", "qids", "report", "representativiteit", "risk", "rounding", "synthetic",
        "voorbeeld", "web", "invoer", "tabel", "kaart", "stappen"]
NETWORK = {"urllib", "http", "socket", "ssl", "requests", "ftplib", "smtplib", "subprocess"}


@pytest.mark.parametrize("module", CORE)
def test_core_imports_no_network(module):
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
            assert name.split(".")[0] not in NETWORK, f"{module} importeert {name}"
            assert name.lstrip(".") != "store", f"{module} importeert de lokale opslag"


@pytest.fixture(scope="module")
def population_file(tmp_path_factory):
    from anonymate import voorbeeld
    return voorbeeld.write_population(tmp_path_factory.mktemp("web") / "oefenpopulatie.parquet")


@pytest.fixture()
def practice(population_file):
    """The practice dataset opened from the prebuilt population, norm not yet locked."""
    web.S.population = None
    web.S.region, web.S.scope_text, web.S.scenario = {}, "", "register"
    return web.open_practice(str(population_file))


@pytest.fixture()
def locked(practice):
    web.lock_norm(0.09)
    return practice


def test_open_practice(practice):
    json.dumps(practice)
    assert practice["records"] == 62 and practice["population"] > 100_000
    roles = {d["column"]: d["role"] for d in practice["detections"]}
    assert roles["huisnummer"] == "direct" and roles["postcode"] == "qid"


def test_open_preselects_like_the_desktop(practice):
    """Every column gets the role the desktop combo boxes start with (MainWindow.load)."""
    from anonymate import voorbeeld
    from anonymate.detect import Role, derive_h3_columns, detect
    from anonymate.invoer import read_dataset
    df, derived = derive_h3_columns(read_dataset(voorbeeld.WONINGEN))
    for d in detect(df):
        want = (derived[d.column] if d.column in derived else "direct" if d.role == Role.DIRECT
                else d.qid if d.role in (Role.QID, Role.IMPLICIT_LOCATION) and d.qid else "geen")
        got = next(x for x in practice["detections"] if x["column"] == d.column)
        assert got["default"] == want and got["proposal"]
    assert practice["norm"]["marks"][1] == {"p": 0.09, "k": 11, "text": "standaard van AnonyMate"}
    assert len(practice["provinces"]) == 12 and practice["region"] == "heel Nederland"
    assert web.S.mapping == web.S.proposal


def test_open_derives_h3_columns():
    """Cell-centre lat/lon columns become an H3 column; the pair itself is no QID any more."""
    h3 = pytest.importorskip("h3")
    lines = ["weather_lat__degN;weather_lon__degE;e_net__W"]
    for i in range(4):
        lat, lon = h3.cell_to_latlng(h3.latlng_to_cell(52.1 + i * 0.3, 5.1 + i * 0.2, 4))
        lines.append(f"{lat};{lon};{i + 1}")
    o = web.open_bytes("h3.csv", "\n".join(lines).encode())
    assert "weather_h3_cel" in o["columns"]
    default = {d["column"]: d["default"] for d in o["detections"]}
    assert default["weather_h3_cel"] == "h3_cel"
    assert default["weather_lat__degN"] == "geen" and default["weather_lon__degE"] == "geen"


def test_excel_without_openpyxl_gives_a_clear_message(tmp_path, monkeypatch):
    def no_excel(path, sheet=None):
        raise ImportError("Missing optional dependency 'openpyxl'.")
    monkeypatch.setattr(web, "read_dataset", no_excel)
    p = tmp_path / "x.xlsx"
    p.write_bytes(b"x")
    with pytest.raises(ValueError, match="Excel-bestanden"):
        web.open_file(str(p), "x.xlsx")
    assert not p.exists()


def test_region_and_scope_stay_in_the_session(locked):
    from anonymate import stappen
    from anonymate.invoer import SCENARIOS, qids_from
    from anonymate.risk import assess
    assert web.set_region(False, ["Utrecht"], "Zwolle")["text"] == "Utrecht, Zwolle"
    assert web.set_region(True)["text"] == "heel Nederland"
    web.set_region(False, [], "Zwolle")
    r = web.run(scope="bouwjaar=1900-1989")
    scope = stappen.merge_scope(stappen.region_scope(False, [], "Zwolle"),
                                "bouwjaar=1900-1989", web.S.population)
    pop = web.S.population.within(scope)
    qids, _ = qids_from(web.S.df, web.S.proposal, auto=False)
    want = assess(web.S.df, qids, pop, web.S.threshold, SCENARIOS["register"]).summary()
    assert r["summary"] == json.loads(json.dumps(want))
    assert r["summary"]["populatie"] < web.S.population.size()
    assert "Zwolle" in r["summary"]["afbakening"]
    # export uses the same (smaller) population as the assessment
    assert web.S.scoped.size() == pop.size()
    assert zipfile.ZipFile(io.BytesIO(web.export())).namelist()
    web.set_region(True)


def test_norm_and_lock(practice):
    n = web.norm(0.09)
    json.dumps(n)
    assert n["k"] == 11 and n["big"] == "k ≥ 11" and n["houses"] == [11, 11, 0]
    assert "1 op 11" in n["text"] and "9%" in n["text"]
    assert web.norm(0.05)["k"] == 20 and web.norm(0.05)["houses"] == [20, 20, 0]
    with pytest.raises(ValueError):
        web.norm(0.9)
    with pytest.raises(ValueError, match="norm vast"):
        web.run()                                    # assessing needs the locked norm
    out = web.lock_norm(0.2)
    assert out["locked"] and out["k"] == 5 and "p = 0.2 (k ≥ 5)" in out["label"]
    assert web.norm(0.05)["p"] == 0.2                # locked: the slider cannot change it
    web.open_practice()                              # a new dataset: fix the norm again
    assert not web.S.norm_locked


def test_run_equals_the_desktop_path(locked):
    from anonymate import stappen
    from anonymate.invoer import SCENARIOS, qids_from
    from anonymate.risk import Threshold, assess
    r = web.run(scenario="register")
    json.dumps(r)
    qids, direct = qids_from(web.S.df, web.S.proposal, auto=False)
    a = assess(web.S.df, qids, web.S.population, Threshold(0.09), SCENARIOS["register"])
    assert r["summary"] == json.loads(json.dumps(a.summary()))
    assert r["direct"] == direct and r["threshold"]["k"] == 11
    t = r["table"]
    assert t["columns"] == [q.column for q in a.qids] + ["k", "delta", "status", "redenen"]
    assert len(t["rows"]) == 62 and t["status"] == list(a.records["status"])
    assert t["selected"] == next(i for i, s in enumerate(t["status"]) if s != "ok")
    assert t["numeric"] == stappen.numeric_flags(t["rows"], len(t["columns"]))
    assert t["numeric"][t["columns"].index("k")] and not t["numeric"][t["columns"].index("status")]
    ks = list(a.records["k"])
    assert r["histogram"] == web._clean(
        [{"lo": lo, "hi": hi, "n": n} for lo, hi, n in stappen.k_histogram(ks, 11)])
    assert r["histogram"][0]["lo"] == 0 and r["histogram"][0]["hi"] == 10
    assert r["histogram"][-1]["hi"] is None                       # infinity is not JSON
    s = a.summary()
    assert r["stats"]["ok"] == f"{s['ok']} · {100 * s['ok'] / 62:.0f}%"
    assert r["stats"]["risk"] == str(62 - s["ok"]) and r["stats"]["bits"].endswith(" bits")
    assert r["title"] == f"{s['ok']} van de 62 woningen publiceerbaar"
    assert r["bits"]["needed"] > 10 and r["bits"]["norm_bits"] == pytest.approx(3.4594, abs=1e-3)
    text = "\n".join(r["toelichting"])
    assert "populatie: " in text and "verzonnen" in text and "worden NIET opgenomen" in text


def test_run_and_export(locked):
    r = web.run(scenario="register")
    s = r["summary"]
    assert s["records"] == 62 and s["ok"] + s["risico"] + s["geen_match"] == 62
    assert "huisnummer" in r["direct"] and len(r["table"]["rows"]) == 62
    names = zipfile.ZipFile(io.BytesIO(web.export())).namelist()
    assert {"publiceerbaar.csv", "rapport.md", "samenvatting.json",
            "rapport_per_record.csv"} <= set(names)


def test_mapping_overrides_detection(locked):
    m = dict(web.S.proposal, energielabel="geen", postcode="direct")
    r = web.run(mapping=m)
    assert "energielabel" not in r["table"]["columns"] and "postcode" in r["direct"]
    with pytest.raises(ValueError, match="onbekende QID"):
        web.run(mapping=dict(web.S.proposal, postcode="bestaat_niet"))


def test_record_card_equals_the_stappen_texts(locked):
    from anonymate import stappen
    r = web.run()
    i = r["table"]["selected"]
    card = web.record(i)
    json.dumps(card)
    rec = web.S.shown.iloc[i]
    title, body = stappen.record_card(rec, rec["k"], 11, rec["delta"], rec["status"], index=i)
    assert card["title"] == title and card["text"] == body
    k = 0 if rec["k"] != rec["k"] else int(rec["k"])
    assert card["houses"] == list(stappen.houses_for(k, 11))
    assert card["title"].startswith(f"Woning {i + 1} ·")
    with pytest.raises(IndexError):
        web.record(999)


def test_open_bytes_removes_the_file(tmp_path):
    data = "postcode;bouwjaar\n1092SS;1988\n1079SA;1997\n".encode()
    o = web.open_bytes("eigen.csv", data)
    assert o["records"] == 2 and o["columns"] == ["postcode", "bouwjaar"]
    path = tmp_path / "x.csv"
    path.write_bytes(data)
    web.open_file(str(path), "x.csv")
    assert not path.exists()


def test_apply_needs_a_search_first(locked):
    web.run()
    with pytest.raises(ValueError):
        web.apply(1)


def generalize_loss_note():
    from anonymate.generalize import LOSS_NOTE
    return LOSS_NOTE


def test_practice_baseline_information_loss_is_zero(locked):
    r = web.suggest()
    assert r["steps"][0]["loss"] == 0.0
    assert web.S.steps[0].loss == 0.0
    losses = [s["loss"] for s in r["steps"]]
    assert losses == sorted(losses) and losses[-1] > 0


def test_suggest_ends_with_an_assessment_and_apply_keeps_the_list(locked):
    from anonymate.invoer import SCENARIOS
    from anonymate.risk import Threshold, assess
    seen = []
    r = web.suggest(progress=lambda f, t: seen.append(f))
    json.dumps(r)
    steps = web.S.steps
    assert seen and len(r["steps"]) == len(steps) and r["selected_step"] == len(steps) - 1
    assert r["title"].endswith(", na generalisatie")
    last = steps[-1]
    want = assess(last.df, last.qids, web.S.population, Threshold(0.09),
                  SCENARIOS["register"]).summary()
    assert r["summary"] == json.loads(json.dumps(want))
    assert "Generalisatiestappen:" in r["toelichting"]
    assert r["target"]["loss_note"] == generalize_loss_note()
    assert r["steps"][0]["text"].startswith("0. ")
    from anonymate import generalize, stappen
    assert r["target"] == {"pct": 100 * generalize.TARGET_SHARE,
                           "label": stappen.target_label(), "note": stappen.target_note(),
                           "loss_note": generalize.LOSS_NOTE}
    with pytest.raises(ValueError, match="na de uitgangssituatie"):
        web.apply(0)
    assert len(steps) > 1
    out = web.apply(1)
    assert len(web.S.steps) == len(steps)                       # not shortened
    assert out["adopted"]["step"] == 1 and out["adopted"]["reason"].endswith("stap 1")
    for c in out["adopted"]["columns"]:
        assert out["mapping"][c] == next(q.spec.key for q in steps[1].qids if q.column == c)
    chosen = assess(steps[1].df, web.S.qids, web.S.population, Threshold(0.09),
                    SCENARIOS["register"]).summary()
    assert out["summary"] == json.loads(json.dumps(chosen))
    assert web.S.export_steps is None
    assert "publiceerbaar.csv" in zipfile.ZipFile(io.BytesIO(web.export())).namelist()


def test_readable_errors():
    assert web.readable("Traceback (most recent call last):\n  File x\nValueError: Leg eerst de "
                        "norm vast.") == "Leg eerst de norm vast."
    assert "onverwacht" in web.readable("Traceback\nKeyError: 'x'")


def _summary(r):
    return r["summary"], r["bits"]["needed"], r["threshold"]


def test_prebuilt_population_gives_the_same_results(population_file):
    """The practice population read from Parquet assesses exactly like the one made in memory."""
    web.S.population = None
    web.open_practice()
    web.lock_norm(0.09)
    in_memory = _summary(web.run())
    web.S.population = None
    o = web.open_practice(str(population_file))
    web.lock_norm(0.09)
    from_file = _summary(web.run())
    assert o["population"] > 100_000 and from_file == in_memory




# runs in a child process, so blocking pyarrow and h3 does not touch the test process
NO_ARROW = r"""
import importlib.abc, json, sys

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("pyarrow", "h3"):
            raise ImportError(f"{name} is niet beschikbaar (test)")

sys.meta_path.insert(0, Blocker())
from anonymate import web
o = web.open_practice(sys.argv[1])
web.lock_norm(0.09)
r = web.run()
web.record(0)
LAZY = ("anonymate.cli", "anonymate.generalize", "anonymate.report", "anonymate.signature")
before = sorted(m for m in LAZY if m in sys.modules)      # after open, norm, run and record
z = web.export()
print(json.dumps({"records": o["records"], "summary": r["summary"], "bits": r["bits"]["needed"],
                  "zip": len(z), "loaded": sorted(m for m in ("pyarrow", "h3") if m in sys.modules),
                  "lazy": before, "after_export": sorted(m for m in LAZY if m in sys.modules)}))
"""


def test_web_path_works_without_pyarrow_and_h3(population_file):
    import subprocess
    import sys
    done = subprocess.run([sys.executable, "-c", NO_ARROW, str(population_file)],
                          capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["records"] == 62 and out["summary"]["records"] == 62 and out["zip"] > 0
    assert out["summary"]["ok"] == 0 and round(out["bits"], 2) == 17.61
    assert out["loaded"] == [] and out["lazy"] == []
    assert out["after_export"] == ["anonymate.report"]
