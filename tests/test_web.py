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
def practice():
    return web.open_practice()


def test_open_practice(practice):
    json.dumps(practice)
    assert practice["records"] == 62 and practice["population"] > 100_000
    roles = {d["column"]: d["role"] for d in practice["detections"]}
    assert roles["huisnummer"] == "direct" and roles["postcode"] == "qid"


def test_run_and_export(practice):
    r = web.run(p=0.09, scenario="register")
    json.dumps(r)
    s = r["summary"]
    assert s["records"] == 62 and s["ok"] + s["risico"] + s["geen_match"] == 62
    assert r["threshold"]["k"] == 11 and r["bits"]["needed"] > 10
    assert "huisnummer" in r["direct"] and len(r["rows"]) == 62
    names = zipfile.ZipFile(io.BytesIO(web.export())).namelist()
    assert {"publiceerbaar.csv", "rapport.md", "samenvatting.json"} <= set(names)


def test_mapping_overrides_detection(practice):
    r = web.run(mapping={"energielabel": "geen", "postcode": "direct"})
    assert "energielabel" not in r["columns"] and "postcode" in r["direct"]


def test_open_bytes_removes_the_file(tmp_path, monkeypatch):
    data = "postcode;bouwjaar\n1092SS;1988\n1079SA;1997\n".encode()
    o = web.open_bytes("eigen.csv", data)
    assert o["records"] == 2 and o["columns"] == ["postcode", "bouwjaar"]
    path = tmp_path / "x.csv"
    path.write_bytes(data)
    web.open_file(str(path), "x.csv")
    assert not path.exists()


def test_apply_needs_a_search_first(practice):
    web.run()
    with pytest.raises(ValueError):
        web.apply(1)


@pytest.fixture(scope="module")
def population_file(tmp_path_factory):
    from anonymate import voorbeeld
    return voorbeeld.write_population(tmp_path_factory.mktemp("web") / "oefenpopulatie.parquet")


def _summary(r):
    return r["summary"], r["bits"]["needed"], r["threshold"]


def test_prebuilt_population_gives_the_same_results(population_file):
    """The practice population read from Parquet assesses exactly like the one made in memory."""
    web.S.population = None
    web.open_practice()
    in_memory = _summary(web.run())
    web.S.population = None
    o = web.open_practice(str(population_file))
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
r = web.run()
z = web.export()
print(json.dumps({"records": o["records"], "summary": r["summary"], "bits": r["bits"]["needed"],
                  "zip": len(z), "loaded": sorted(m for m in ("pyarrow", "h3") if m in sys.modules),
                  "lazy": sorted(m for m in ("anonymate.cli", "anonymate.generalize",
                                             "anonymate.signature") if m in sys.modules)}))
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
