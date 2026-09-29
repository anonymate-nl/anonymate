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
        "voorbeeld", "web"]
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
