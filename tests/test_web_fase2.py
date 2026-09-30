"""Fase 2 van de webversie: Pyodide zelf gehost, controleerbaar en offline (web/maak.py, web/sw.js).

Alles hier draait in CPython, zonder netwerk en zonder browser: de bouwfuncties van maak.py met
kleine nepbestanden, en de tekst van index.html, worker.js en sw.js.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"


@pytest.fixture(scope="module")
def maak():
    spec = importlib.util.spec_from_file_location("web_maak", WEB / "maak.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---- pakketten oplossen ----

NEP_LOCK = {"packages": {
    "numpy": {"depends": []},
    "pandas": {"depends": ["numpy", "python-dateutil", "pytz"]},
    "python-dateutil": {"depends": ["six"]},
    "six": {"depends": []},
    "pytz": {"depends": []},
    "duckdb": {"depends": []},
    "h3": {"depends": []},
    "pyarrow": {"depends": ["numpy"]},
    "micropip": {"depends": []},
}}


def test_afhankelijkheden_van_pandas_zitten_erbij_en_pyarrow_niet(maak):
    namen = maak.pakketten_oplossen(NEP_LOCK, maak.PAKKETTEN)
    assert {"numpy", "pandas", "python-dateutil", "six", "pytz", "duckdb", "h3"} <= set(namen)
    assert not {"pyarrow", "micropip", "tzdata"} & set(namen)


def test_echte_lock_van_de_gepinde_versie(maak):
    lock = WEB / ".pyodide-cache" / maak.PYODIDE_VERSION / "pyodide-lock.json"
    if not lock.exists():
        pytest.skip("pyodide-lock.json niet in de cache (nog geen build gedraaid)")
    namen = maak.pakketten_oplossen(json.loads(lock.read_text(encoding="utf-8")), maak.PAKKETTEN)
    assert {"numpy", "pandas", "duckdb", "h3", "pytz", "python-dateutil", "six"} <= set(namen)
    assert not {"pyarrow", "micropip", "tzdata"} & set(namen)


def test_worker_laadt_alleen_gebouwde_pakketten(maak):
    worker = (WEB / "worker.js").read_text(encoding="utf-8")
    boot = re.search(r"const PACKAGES = \[(.*?)\]", worker).group(1)
    genoemd = set(re.findall(r'"(\w+)"', boot)) | set(re.findall(r'loadPackage\("(\w+)"\)', worker))
    assert genoemd <= set(maak.PAKKETTEN), genoemd


# ---- hashes ----

def _klaar(maak, tmp_path, monkeypatch):
    """Een cache met nepbestanden voor de hele runtime en een nep-lock, en de vastgepinde hashes."""
    cache = tmp_path / "cache"
    cache.mkdir()
    wheels = {}
    for naam in ("numpy", "pandas", "duckdb", "h3", "python-dateutil", "six", "pytz"):
        bestand = f"{naam}-1.whl"
        data = f"wheel {naam}".encode()
        (cache / bestand).write_bytes(data)
        wheels[naam] = {"file_name": bestand, "sha256": sha(data),
                        "depends": NEP_LOCK["packages"].get(naam, {}).get("depends", [])}
    lock = json.dumps({"packages": wheels}).encode()
    inhoud = {n: f"runtime {n}".encode() for n in maak.RUNTIME}
    inhoud["pyodide-lock.json"] = lock
    for n, d in inhoud.items():
        (cache / n).write_bytes(d)
    pin = tmp_path / "pyodide-sha256.json"
    pin.write_text(json.dumps({"version": maak.PYODIDE_VERSION,
                               "files": {n: sha(d) for n, d in inhoud.items()}}), encoding="utf-8")
    monkeypatch.setattr(maak, "HASHES", pin)
    monkeypatch.setattr(maak, "_download", lambda *a: pytest.fail("geen download verwacht"))
    return cache


def test_pyodide_klaarzetten_kopieert_runtime_en_pakketten(maak, tmp_path, monkeypatch):
    cache = _klaar(maak, tmp_path, monkeypatch)
    namen = maak.pyodide_klaarzetten(tmp_path / "dist" / "pyodide", cache)
    assert "pandas" in namen and "pyarrow" not in namen
    geleverd = {p.name for p in (tmp_path / "dist" / "pyodide").iterdir()}
    assert set(maak.RUNTIME) <= geleverd
    assert "pandas-1.whl" in geleverd and "six-1.whl" in geleverd


def test_beschadigde_wheel_in_de_cache_laat_de_build_mislukken(maak, tmp_path, monkeypatch):
    cache = _klaar(maak, tmp_path, monkeypatch)
    (cache / "pandas-1.whl").write_bytes(b"aangepast")
    with pytest.raises(SystemExit, match="pandas-1.whl"):
        maak.pyodide_klaarzetten(tmp_path / "dist" / "pyodide", cache)


def test_beschadigde_runtime_in_de_cache_laat_de_build_mislukken(maak, tmp_path, monkeypatch):
    cache = _klaar(maak, tmp_path, monkeypatch)
    (cache / "pyodide.asm.wasm").write_bytes(b"aangepast")
    with pytest.raises(SystemExit, match="pyodide.asm.wasm"):
        maak.pyodide_klaarzetten(tmp_path / "dist" / "pyodide", cache)


def test_hashbestand_van_een_andere_versie_wordt_geweigerd(maak, tmp_path, monkeypatch):
    pin = tmp_path / "h.json"
    pin.write_text(json.dumps({"version": "0.0.1", "files": {}}), encoding="utf-8")
    monkeypatch.setattr(maak, "HASHES", pin)
    with pytest.raises(SystemExit, match="0.0.1"):
        maak.vastgepinde_hashes()


def test_vastgepinde_hashes_dekken_de_hele_runtime(maak):
    data = json.loads((WEB / "pyodide-sha256.json").read_text(encoding="utf-8"))
    assert data["version"] == maak.PYODIDE_VERSION
    assert set(data["files"]) == set(maak.RUNTIME)
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in data["files"].values())


# ---- manifest en service worker ----

def _nep_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "pyodide").mkdir(parents=True)
    (dist / "index.html").write_text("<html>", encoding="utf-8")
    (dist / "pyodide" / "pyodide.js").write_bytes(b"js")
    (dist / "sw.js").write_text((WEB / "sw.js").read_text(encoding="utf-8"), encoding="utf-8")
    return dist


def test_manifest_somt_elk_bestand_op_met_juiste_hash(maak, tmp_path):
    dist = _nep_dist(tmp_path)
    bouw = maak.sw_invullen(dist)
    maak.manifest_schrijven(dist, "1.2.3", bouw)
    manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["anonymate"] == "1.2.3" and manifest["pyodide"] == maak.PYODIDE_VERSION
    echt = {p.relative_to(dist).as_posix() for p in dist.rglob("*")
            if p.is_file() and p.name != "manifest.json"}
    assert set(manifest["files"]) == echt
    for pad, info in manifest["files"].items():
        data = (dist / pad).read_bytes()
        assert info == {"size": len(data), "sha256": sha(data)}


def test_sw_krijgt_bouwid_en_lijst_van_de_dist(maak, tmp_path):
    dist = _nep_dist(tmp_path)
    bouw = maak.sw_invullen(dist)
    tekst = (dist / "sw.js").read_text(encoding="utf-8")
    assert f'const BOUW = "{bouw}"' in tekst
    lijst = json.loads(re.search(r"const PRECACHE = (\{.*?\});", tekst, re.S).group(1))
    assert set(lijst) == {"index.html", "pyodide/pyodide.js", "manifest.json"}
    assert lijst["index.html"] == sha(b"<html>") and lijst["manifest.json"] is None
    # een andere inhoud geeft een ander bouw-id
    (dist / "index.html").write_text("<html>anders", encoding="utf-8")
    (dist / "sw.js").write_text((WEB / "sw.js").read_text(encoding="utf-8"), encoding="utf-8")
    assert maak.sw_invullen(dist) != bouw


# ---- CSP en verwijzingen ----

def test_csp_heeft_geen_externe_host():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]*)"', html).group(1)
    assert not re.search(r"https?:|//|jsdelivr|\*", csp), csp
    delen = dict(d.strip().split(" ", 1) for d in csp.split(";"))
    assert delen["script-src"] == "'self' 'wasm-unsafe-eval'"
    assert delen["connect-src"] == "'self'"
    assert delen["worker-src"] == "'self' blob:"
    assert delen["default-src"] == "'self'"
    assert "data:" not in delen["script-src"]
    for sleutel, waarde in (("form-action", "'none'"), ("base-uri", "'none'"),
                            ("object-src", "'none'")):
        assert delen[sleutel] == waarde


@pytest.mark.parametrize("naam", ["worker.js", "sw.js", "index.html"])
def test_geen_externe_url_in_de_bronbestanden(naam):
    tekst = (WEB / naam).read_text(encoding="utf-8")
    tekst = re.sub(r"<!--.*?-->", "", tekst, flags=re.S)
    if naam == "index.html":
        # de bronvermelding en links in de tekst zijn geen verzoeken: alleen src/href/action tellen
        assert not re.findall(r'(?:src|action)="https?:', tekst)
    else:
        assert not re.search(r"https?://", tekst), naam


def test_worker_verwijst_naar_pyodide_naast_de_pagina():
    tekst = (WEB / "worker.js").read_text(encoding="utf-8")
    assert 'new URL("pyodide/", base)' in tekst
    assert "jsdelivr" not in tekst


def test_verwijzingen_van_worker_en_sw_bestaan_in_dist(maak):
    """Wat worker.js en sw.js noemen, moet maak.py leveren (getest tegen een echte dist, als die er is)."""
    dist = WEB / "dist"
    if not (dist / "manifest.json").exists():
        pytest.skip("web/dist nog niet gebouwd")
    manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
    worker = (WEB / "worker.js").read_text(encoding="utf-8")
    genoemd = set(re.findall(r'"([\w.]+\.(?:json|parquet|js))"', worker))
    assert {"wheel.json", "oefenpopulatie.parquet"} <= genoemd
    for naam in genoemd:
        assert (dist / naam).is_file() or (dist / "pyodide" / naam).is_file(), naam
    for pad in maak.RUNTIME:
        assert f"pyodide/{pad}" in manifest["files"]
    sw = (dist / "sw.js").read_text(encoding="utf-8")
    lijst = json.loads(re.search(r"const PRECACHE = (\{.*?\});", sw, re.S).group(1))
    for pad in lijst:
        assert (dist / pad).is_file(), pad
    assert "pyodide/pyodide.js" in lijst and "manifest.json" in lijst
    assert not any("pyarrow" in p or "micropip" in p for p in lijst)
