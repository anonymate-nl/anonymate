"""Zet de webversie klaar in web/dist/: de pagina, de schil, de worker, de wheel van anonymate en
Pyodide zelf (fase 2 van docs/werk/webversie.md: geen CDN, alles van dezelfde herkomst).

    python web/maak.py
    python -m http.server -d web/dist 8000        # en open http://localhost:8000

De wheel wordt gebouwd met SOURCE_DATE_EPOCH uit de laatste commit, zodat twee builds van
dezelfde commit dezelfde bytes geven. wheel.json vertelt de worker welke wheel hij moet laden,
met de SHA-256 erbij.

Pyodide staat op EEN plek vastgepind: PYODIDE_VERSION. De bestanden komen van jsDelivr (alleen bij
het bouwen, nooit in de browser), in web/.pyodide-cache/<versie>/ zodat een tweede build niets
downloadt, en landen in dist/pyodide/. Elk pakket (wheel) moet kloppen met de sha256 in
pyodide-lock.json; de runtimebestanden hebben daar geen hash, dus die staan in
web/pyodide-sha256.json (eenmalig gemaakt met `python web/maak.py --pyodide-hashes`, in de
repository vastgelegd). Een afwijking laat de build mislukken.

manifest.json somt elk bestand van dist op met grootte en sha256 (voor de controlepagina van
fase 6), plus de versies van Pyodide en AnonyMate. sw.js krijgt de lijst van te cachen bestanden
en een bouw-id uit die inhoud, zodat hij nooit verouderd kan zijn.

oefenpopulatie.parquet is het verzonnen Nederland van de oefenmodus, vooraf gemaakt (zstd, vaste
seed, dus dezelfde bytes elke build): de browser hoeft het dan niet zelf te verzinnen
(kladbloknotitie 15, stap 2).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DIST = HERE / "dist"
CACHE = HERE / ".pyodide-cache"
HASHES = HERE / "pyodide-sha256.json"
FILES = ["index.html", "app.js", "worker.js", "sw.js"]

# de enige plek waar de versie van Pyodide staat (de worker leest hem uit wheel.json)
PYODIDE_VERSION = "314.0.7"
PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v{versie}/full/{naam}"
# wat loadPyodide in een classic worker vraagt: pyodide.js (importScripts), dat laadt
# pyodide.asm.mjs en pyodide.asm.wasm, de standaardbibliotheek en het lock-bestand.
# (pyodide.mjs is de ES-module-ingang; de worker gebruikt die niet.)
RUNTIME = ["pyodide.js", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip",
           "pyodide-lock.json"]
# wat de worker laadt (worker.js: PACKAGES bij het opstarten, h3 daarna op de achtergrond);
# de rest volgt uit de `depends` in pyodide-lock.json. Geen pyarrow, micropip of tzdata.
PAKKETTEN = ["numpy", "pandas", "duckdb", "h3"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pakketten_oplossen(lock: dict, namen: list[str]) -> list[str]:
    """De namen met, recursief, alles waar ze van afhangen (volgorde: eerst gevraagd)."""
    pakketten = lock["packages"]
    uit: list[str] = []

    def loop(naam: str) -> None:
        naam = naam.lower()
        if naam in uit:
            return
        if naam not in pakketten:
            raise SystemExit(f"pakket {naam!r} staat niet in pyodide-lock.json")
        uit.append(naam)
        for dep in pakketten[naam].get("depends", []):
            loop(dep)

    for naam in namen:
        loop(naam)
    return uit


def _download(url: str, doel: Path) -> None:
    doel.parent.mkdir(parents=True, exist_ok=True)
    tmp = doel.with_name(doel.name + ".deel")
    with urllib.request.urlopen(url, timeout=120) as r:
        tmp.write_bytes(r.read())
    tmp.replace(doel)


def ophalen(naam: str, verwacht: str | None, cache: Path, versie: str = PYODIDE_VERSION) -> Path:
    """Het bestand uit de cache, gedownload als het er nog niet is, en gecontroleerd tegen de hash.

    Een bestand in de cache dat niet klopt, is een fout (geen stille nieuwe download): dan is de
    cache stuk of aangepast, en dat moet iemand zien.
    """
    pad = cache / naam
    if not pad.exists():
        print(f"downloaden: {naam}")
        _download(PYODIDE_URL.format(versie=versie, naam=naam), pad)
    if verwacht is not None:
        echt = sha256(pad.read_bytes())
        if echt != verwacht:
            raise SystemExit(f"sha256 van {naam} klopt niet: verwacht {verwacht}, gevonden {echt} "
                             f"({pad}); verwijder het bestand als de cache stuk is")
    return pad


def vastgepinde_hashes() -> dict[str, str]:
    data = json.loads(HASHES.read_text(encoding="utf-8"))
    if data.get("version") != PYODIDE_VERSION:
        raise SystemExit(f"{HASHES.name} is voor Pyodide {data.get('version')}, maak.py pint "
                         f"{PYODIDE_VERSION}: maak hem opnieuw met --pyodide-hashes")
    return data["files"]


def hashes_schrijven() -> None:
    """Eenmalig, bij het vastpinnen van een nieuwe Pyodide-versie: de hashes van de runtime."""
    cache = CACHE / PYODIDE_VERSION
    files = {n: sha256(ophalen(n, None, cache).read_bytes()) for n in RUNTIME}
    HASHES.write_text(json.dumps({"version": PYODIDE_VERSION, "files": files}, indent=2) + "\n",
                      encoding="utf-8")
    print(f"geschreven: {HASHES}")


def pyodide_klaarzetten(doel: Path, cache: Path | None = None) -> list[str]:
    """dist/pyodide/: de runtime en de pakketten, allemaal gecontroleerd. Geeft de pakketnamen."""
    cache = cache or CACHE / PYODIDE_VERSION
    pinned = vastgepinde_hashes()
    ontbreekt = [n for n in RUNTIME if n not in pinned]
    if ontbreekt:
        raise SystemExit(f"{HASHES.name} mist: {', '.join(ontbreekt)}")
    doel.mkdir(parents=True, exist_ok=True)
    for naam in RUNTIME:
        shutil.copy2(ophalen(naam, pinned[naam], cache), doel / naam)
    lock = json.loads((doel / "pyodide-lock.json").read_text(encoding="utf-8"))
    namen = pakketten_oplossen(lock, PAKKETTEN)
    for naam in namen:
        info = lock["packages"][naam]
        shutil.copy2(ophalen(info["file_name"], info["sha256"], cache), doel / info["file_name"])
    return namen


def bestanden(dist: Path) -> dict[str, dict]:
    """Elk bestand onder dist met grootte en sha256 (paden met /), behalve manifest.json zelf."""
    uit = {}
    for f in sorted(p for p in dist.rglob("*") if p.is_file() and p.name != "manifest.json"):
        data = f.read_bytes()
        uit[f.relative_to(dist).as_posix()] = {"size": len(data), "sha256": sha256(data)}
    return uit


def bouw_id(files: dict[str, dict]) -> str:
    regels = "\n".join(f"{p} {i['sha256']}" for p, i in sorted(files.items()))
    return sha256(regels.encode("utf-8"))[:16]


def sw_invullen(dist: Path) -> str:
    """Zet de bestandenlijst (zonder sw.js zelf) en het bouw-id in dist/sw.js; geeft het bouw-id.

    De lijst wijst elk bestand naar zijn sha256 (de service worker controleert die bij het
    binnenhalen); manifest.json staat erbij zonder hash (hij kan zichzelf niet bevatten).
    """
    sw = dist / "sw.js"
    tekst = sw.read_text(encoding="utf-8")
    files = {p: i for p, i in bestanden(dist).items() if p != "sw.js"}
    bouw = bouw_id(files)
    lijst = {p: i["sha256"] for p, i in files.items()}
    lijst["manifest.json"] = None
    for marker, waarde in (('/*BOUW*/""', json.dumps(bouw)),
                           ("/*PRECACHE*/{}", json.dumps(lijst, indent=1))):
        if marker not in tekst:
            raise SystemExit(f"sw.js mist de plaats {marker}")
        tekst = tekst.replace(marker, waarde)
    sw.write_text(tekst, encoding="utf-8", newline="\n")
    return bouw


def manifest_schrijven(dist: Path, anonymate: str, bouw: str) -> dict:
    manifest = {"anonymate": anonymate, "pyodide": PYODIDE_VERSION, "bouw": bouw,
                "files": bestanden(dist)}
    (dist / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    if "--pyodide-hashes" in sys.argv:
        hashes_schrijven()
        return 0
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    env = dict(os.environ)
    try:
        env["SOURCE_DATE_EPOCH"] = subprocess.run(
            ["git", "log", "-1", "--format=%ct"], cwd=ROOT, capture_output=True, text=True,
            check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--quiet", "-w", str(DIST),
                    str(ROOT)], check=True, env=env)
    wheel = next(DIST.glob("anonymate-*.whl"))
    for name in FILES:
        shutil.copy2(HERE / name, DIST / name)
    sys.path.insert(0, str(ROOT / "src"))
    from anonymate import voorbeeld
    populatie = voorbeeld.write_population(DIST / "oefenpopulatie.parquet")
    version = wheel.name.split("-")[1]
    sha = sha256(wheel.read_bytes())
    (DIST / "wheel.json").write_text(json.dumps(
        {"wheel": wheel.name, "version": version, "sha256": sha, "pyodide": PYODIDE_VERSION},
        indent=2), encoding="utf-8")
    namen = pyodide_klaarzetten(DIST / "pyodide")
    bouw = sw_invullen(DIST)
    manifest = manifest_schrijven(DIST, version, bouw)
    totaal = sum(i["size"] for i in manifest["files"].values())
    print(f"klaar: {DIST} ({wheel.name}, sha256 {sha[:16]}...; {populatie.name} "
          f"{populatie.stat().st_size / 1e6:.1f} MB; Pyodide {PYODIDE_VERSION} met "
          f"{', '.join(namen)}; {len(manifest['files'])} bestanden, {totaal / 1e6:.1f} MB; "
          f"bouw {bouw})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
