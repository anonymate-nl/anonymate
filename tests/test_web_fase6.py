"""Fase 6 van de webversie: verifieerbaar (web/maak.py, web/controleer.py, website/controleer.html).

Alles in CPython, zonder netwerk en zonder browser.
"""
from __future__ import annotations

import importlib.util
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
SITE = ROOT / "website"


def _laad(naam: str, pad: Path):
    spec = importlib.util.spec_from_file_location(naam, pad)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def maak():
    return _laad("web_maak6", WEB / "maak.py")


@pytest.fixture(scope="module")
def controleer():
    return _laad("web_controleer", WEB / "controleer.py")


# ---- maak.py: manifest en regeleinden ----

def test_manifest_bevat_bron_met_commit_en_repo(maak, tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    sha = "0123456789abcdef0123456789abcdef01234567"
    m = maak.manifest_schrijven(tmp_path, "1.2.3", "bouwid", commit=sha)
    assert m["bron"] == {"repo": "https://github.com/anonymate-nl/anonymate", "commit": sha}
    opgeslagen = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert opgeslagen == m
    assert "manifest.json" not in opgeslagen["files"]


def test_commit_uit_omgeving_of_git(maak, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "ab" * 20)
    assert maak.commit_van_checkout() == "ab" * 20
    monkeypatch.delenv("GITHUB_SHA")
    assert re.fullmatch(r"[0-9a-f]{40}|onbekend", maak.commit_van_checkout())


def test_schrijf_tekst_schrijft_alleen_lf(maak, tmp_path):
    maak.schrijf_tekst(tmp_path / "x.txt", "a\r\nb\nc\r\n")
    assert (tmp_path / "x.txt").read_bytes() == b"a\nb\nc\n"


def test_kopieer_tekst_maakt_van_crlf_lf(maak, tmp_path):
    (tmp_path / "van.js").write_bytes("// é\r\nlet x;\r\n".encode("utf-8"))
    maak.kopieer_tekst(tmp_path / "van.js", tmp_path / "naar.js")
    assert (tmp_path / "naar.js").read_bytes() == "// é\nlet x;\n".encode("utf-8")


def test_manifest_json_heeft_lf_en_is_gelijk_bij_herhaling(maak, tmp_path):
    (tmp_path / "a.txt").write_bytes(b"a\n")
    maak.manifest_schrijven(tmp_path, "1", "b", commit="c" * 40)
    eerste = (tmp_path / "manifest.json").read_bytes()
    assert b"\r" not in eerste
    maak.manifest_schrijven(tmp_path, "1", "b", commit="c" * 40)
    assert (tmp_path / "manifest.json").read_bytes() == eerste


def test_bronkopie_voor_de_wheel_heeft_lf_in_tekst_en_laat_binair_ongemoeid(maak, tmp_path):
    bron = maak.broncode_klaarzetten(tmp_path)
    assert (bron / "pyproject.toml").is_file()
    assert b"\r\n" not in (bron / "src" / "anonymate" / "web.py").read_bytes()
    for p in (ROOT / "src").rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts and b"\0" in p.read_bytes()[:4096]:
            assert (bron / p.relative_to(ROOT)).read_bytes() == p.read_bytes()


def test_bouwgereedschap_staat_vast(maak):
    tekst = maak.CONSTRAINTS.read_text(encoding="utf-8")
    for naam in ("setuptools", "wheel", "duckdb", "pyarrow", "pandas", "numpy"):
        assert re.search(rf"^{naam}==[\w.]+$", tekst, re.M), naam


# ---- controleer.py: vergelijken ----

def test_vergelijk_gelijk(controleer):
    a = {"a.js": {"size": 1, "sha256": "x"}, "b.js": {"size": 2, "sha256": "y"}}
    r = controleer.vergelijk(a, dict(a))
    assert r == {"gelijk": True, "verschillend": [], "ontbreekt_live": [], "extra_live": []}


def test_vergelijk_een_bestand_verschilt(controleer):
    lokaal = {"a.js": {"size": 1, "sha256": "x"}, "b.js": {"size": 2, "sha256": "y"}}
    live = {"a.js": {"size": 1, "sha256": "x"}, "b.js": {"size": 2, "sha256": "ANDERS"}}
    r = controleer.vergelijk(lokaal, live)
    assert not r["gelijk"] and r["verschillend"] == ["b.js"]
    assert not r["ontbreekt_live"] and not r["extra_live"]


def test_vergelijk_zelfde_hash_andere_grootte_telt_als_verschil(controleer):
    r = controleer.vergelijk({"a": {"size": 1, "sha256": "x"}}, {"a": {"size": 2, "sha256": "x"}})
    assert r["verschillend"] == ["a"]


def test_vergelijk_ontbrekend_en_extra(controleer):
    lokaal = {"a.js": {"size": 1, "sha256": "x"}, "b.js": {"size": 2, "sha256": "y"}}
    live = {"a.js": {"size": 1, "sha256": "x"}, "c.js": {"size": 3, "sha256": "z"}}
    r = controleer.vergelijk(lokaal, live)
    assert not r["gelijk"]
    assert r["ontbreekt_live"] == ["b.js"] and r["extra_live"] == ["c.js"]


def _serveer(controleer, monkeypatch, live_bestanden: dict, manifest: dict):
    urls = {"https://x.test/app/" + p: d for p, d in live_bestanden.items()}
    urls["https://x.test/app/manifest.json"] = json.dumps(manifest).encode()
    monkeypatch.setattr(controleer, "haal", lambda u: urls[u])


def test_live_bestanden_controleren_vindt_afwijkende_inhoud(controleer, monkeypatch):
    goed = b"goed"
    files = {"a.js": {"size": 4, "sha256": controleer.sha256(goed)},
             "b.js": {"size": 4, "sha256": controleer.sha256(goed)}}
    _serveer(controleer, monkeypatch, {"a.js": goed, "b.js": b"slecht"}, {})
    assert controleer.live_bestanden_controleren("https://x.test/app/", files) == ["b.js"]


def test_main_zegt_welke_commit_uitchecken_als_head_afwijkt(controleer, monkeypatch, capsys):
    commit = "1" * 40
    _serveer(controleer, monkeypatch, {}, {"bron": {"commit": commit}, "files": {}})
    monkeypatch.setattr(controleer, "huidige_commit", lambda: "2" * 40)
    assert controleer.main(["--url", "https://x.test/app/"]) == 2
    assert f"git checkout {commit}" in capsys.readouterr().out


def test_main_gelijk_en_verschil_met_bestaande_dist(controleer, monkeypatch, tmp_path, capsys):
    commit = "1" * 40
    data = b"inhoud"
    files = {"a.js": {"size": len(data), "sha256": controleer.sha256(data)}}
    manifest = {"bron": {"commit": commit}, "files": files}
    _serveer(controleer, monkeypatch, {"a.js": data}, manifest)
    monkeypatch.setattr(controleer, "huidige_commit", lambda: commit)
    (tmp_path / "manifest.json").write_bytes(json.dumps(manifest).encode())
    args = ["--url", "https://x.test/app/", "--dist", str(tmp_path), "--zonder-bouwen"]
    assert controleer.main(args) == 0
    uit = capsys.readouterr().out
    assert "gelijk: wat op https://x.test/app/ draait, is gebouwd uit commit " + commit in uit
    lokaal = {"bron": {"commit": commit},
              "files": {"a.js": {"size": len(data), "sha256": "ander"}}}
    (tmp_path / "manifest.json").write_bytes(json.dumps(lokaal).encode())
    assert controleer.main(args) == 1
    assert "Andere inhoud: a.js" in capsys.readouterr().out


# ---- de pagina's ----

class _Bronnen(HTMLParser):
    """Alles wat de browser zelf ophaalt (src, href van link, url() in stijlen) en de a-links."""

    def __init__(self):
        super().__init__()
        self.extern: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for sleutel in ("src", "srcset", "poster", "data"):
            if a.get(sleutel):
                self.extern.append(a[sleutel])
        if tag == "link" and a.get("href"):
            self.extern.append(a["href"])
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if a.get("style"):
            self.extern += re.findall(r"url\(([^)]*)\)", a["style"])


def _parse(pad: Path) -> _Bronnen:
    p = _Bronnen()
    tekst = pad.read_text(encoding="utf-8")
    p.feed(tekst)
    stijlen = "".join(re.findall(r"<style>(.*?)</style>", tekst, re.S))
    p.extern += re.findall(r"url\(([^)]*)\)", stijlen)
    return p


def test_controlepagina_laadt_niets_van_buiten():
    for bron in _parse(SITE / "controleer.html").extern:
        bron = bron.strip("'\" ")
        assert not re.match(r"(https?:)?//", bron), bron


def test_controlepagina_heeft_geen_scripts():
    assert "<script" not in (SITE / "controleer.html").read_text(encoding="utf-8")


def test_landing_en_app_linken_naar_de_controlepagina():
    assert "controleer.html" in _parse(SITE / "index.html").links
    assert "../controleer.html" in _parse(WEB / "index.html").links


def test_controlepagina_noemt_de_commandos():
    tekst = (SITE / "controleer.html").read_text(encoding="utf-8")
    assert "python web/controleer.py" in tekst
    assert "gh attestation verify manifest.json --repo anonymate-nl/anonymate" in tekst


def test_controlepagina_toont_de_csp_en_pyodide_hashes_van_nu():
    tekst = (SITE / "controleer.html").read_text(encoding="utf-8")
    app = (WEB / "index.html").read_text(encoding="utf-8")
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]*)"', app).group(1)
    assert csp in tekst
    pin = json.loads((WEB / "pyodide-sha256.json").read_text(encoding="utf-8"))
    for naam, h in pin["files"].items():
        assert naam in tekst and h in tekst
    assert pin["version"] in tekst


def test_app_toont_versie_en_commit_uit_het_manifest():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "manifest.json" in js and "bron.commit" in js
    assert 'id="broncommit"' in (WEB / "index.html").read_text(encoding="utf-8")


def test_workflows_attesteren_en_controleren_wekelijks():
    wf = ROOT / ".github" / "workflows"
    pages = (wf / "pages.yml").read_text(encoding="utf-8")
    assert "actions/attest-build-provenance@" in pages and "attestations: write" in pages
    assert "web/dist/manifest.json" in pages
    controle = (wf / "controle.yml").read_text(encoding="utf-8")
    assert "cron:" in controle and "web/controleer.py" in controle
    assert "herbouw:" in (wf / "tests.yml").read_text(encoding="utf-8")


def test_wheel_normaliseren_zet_vaste_metadata(maak, tmp_path):
    import zipfile
    pad = tmp_path / "x-1-py3-none-any.whl"
    with zipfile.ZipFile(pad, "w") as z:
        for naam in ("x-1.dist-info/RECORD", "x/b.py", "x-1.dist-info/METADATA", "x/a.py"):
            info = zipfile.ZipInfo(naam, (2030, 5, 5, 5, 5, 4))
            info.external_attr = 0o666 << 16
            info.create_system = 0
            z.writestr(info, naam.encode())
    maak.wheel_normaliseren(pad, 1_800_000_000)
    with zipfile.ZipFile(pad) as z:
        namen = [i.filename for i in z.infolist()]
        assert namen == ["x/a.py", "x/b.py", "x-1.dist-info/METADATA", "x-1.dist-info/RECORD"]
        assert {i.date_time for i in z.infolist()} == {(2027, 1, 15, 8, 0, 0)}
        assert {i.external_attr >> 16 for i in z.infolist()} == {0o644}
        assert {i.create_system for i in z.infolist()} == {3}
        assert z.read("x/a.py") == b"x/a.py"
    eerste = pad.read_bytes()
    maak.wheel_normaliseren(pad, 1_800_000_000)
    assert pad.read_bytes() == eerste
