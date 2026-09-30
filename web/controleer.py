"""Controleer dat wat op https://anonymate.nl/app/ draait, gebouwd is uit de openbare broncode.

    git checkout <commit>                      # de commit uit het live manifest (dit script zegt welke)
    python web/controleer.py [--url https://anonymate.nl/app/] [--dist web/dist] [--zonder-bouwen]

Wat het doet:
  1. haalt manifest.json van de live site (met bron.commit: de commit waaruit hij gebouwd is);
  2. bouwt web/dist opnieuw uit deze checkout (python web/maak.py), tenzij --zonder-bouwen;
  3. vergelijkt bestand voor bestand (grootte en sha256) met het live manifest, en de twee
     manifest.json-bestanden zelf byte voor byte;
  4. downloadt elk live bestand en controleert de sha256 tegen het live manifest (dus dat de site
     echt levert wat het manifest zegt).

Uitkomst: exitcode 0 als alles gelijk is, 1 bij een verschil, 2 als de checkout niet de
uitgerolde commit is of het live manifest niet te lezen is.

Voor een gelijke build: dezelfde omgeving als de referentiebuild (Linux, Python 3.13, de versies
in web/bouw-constraints.txt): pip install -e . -c web/bouw-constraints.txt. Zie
https://anonymate.nl/controleer.html. Alleen standaardbibliotheek; het script schrijft alleen in
web/dist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STANDAARD_URL = "https://anonymate.nl/app/"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def vergelijk(lokaal: dict, live: dict) -> dict:
    """Vergelijk twee lijsten {pad: {"size", "sha256"}} (het veld `files` van manifest.json).

    Geeft {"gelijk": bool, "verschillend": [...], "ontbreekt_live": [...], "extra_live": [...]}:
    verschillend = in beide maar andere sha256 of grootte; ontbreekt_live = wel lokaal gebouwd,
    niet live; extra_live = live, maar niet in de lokale build.
    """
    verschillend = sorted(p for p in lokaal.keys() & live.keys()
                          if lokaal[p]["sha256"] != live[p]["sha256"]
                          or lokaal[p]["size"] != live[p]["size"])
    ontbreekt_live = sorted(lokaal.keys() - live.keys())
    extra_live = sorted(live.keys() - lokaal.keys())
    return {"gelijk": not (verschillend or ontbreekt_live or extra_live),
            "verschillend": verschillend, "ontbreekt_live": ontbreekt_live,
            "extra_live": extra_live}


def haal(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "anonymate-controleer"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def live_bestanden_controleren(basis: str, files: dict) -> list[str]:
    """Download elk bestand van de live site; geeft de paden waarvan de sha256 niet klopt."""
    fout = []
    for pad in sorted(files):
        try:
            data = haal(basis + pad)
        except OSError as e:
            print(f"  {pad}: niet op te halen ({e})")
            fout.append(pad)
            continue
        if sha256(data) != files[pad]["sha256"] or len(data) != files[pad]["size"]:
            fout.append(pad)
    return fout


def huidige_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default=STANDAARD_URL, help=f"standaard {STANDAARD_URL}")
    ap.add_argument("--dist", default=str(HERE / "dist"), help="de map om te bouwen/vergelijken")
    ap.add_argument("--zonder-bouwen", action="store_true",
                    help="gebruik de bestaande dist in plaats van opnieuw te bouwen")
    args = ap.parse_args(argv)
    basis = args.url if args.url.endswith("/") else args.url + "/"
    dist = Path(args.dist)

    print(f"Live manifest ophalen: {basis}manifest.json")
    try:
        live_raw = haal(basis + "manifest.json")
        live = json.loads(live_raw)
    except (OSError, ValueError) as e:
        print(f"Kan het live manifest niet lezen: {e}")
        return 2
    commit = (live.get("bron") or {}).get("commit", "")
    if not commit:
        print("Het live manifest noemt geen commit (bron.commit): deze versie is van voor "
              "de verifieerbare build. Er valt niets te vergelijken.")
        return 2
    print(f"De live site is gebouwd uit commit {commit}")
    hier = huidige_commit()
    if hier != commit:
        print(f"Deze checkout staat op {hier or 'een onbekende commit'}, niet op {commit}.\n"
              f"Controleer die commit: git checkout {commit}   (en draai dit script opnieuw)")
        return 2

    if not args.zonder_bouwen:
        print("Opnieuw bouwen uit deze checkout (python web/maak.py)...")
        r = subprocess.run([sys.executable, str(HERE / "maak.py"), "--uit", str(dist)])
        if r.returncode != 0:
            print("De build zelf is mislukt.")
            return 2
    try:
        lokaal_raw = (dist / "manifest.json").read_bytes()
        lokaal = json.loads(lokaal_raw)
    except (OSError, ValueError) as e:
        print(f"Geen lokale manifest.json in {dist}: {e}")
        return 2

    verschil = vergelijk(lokaal["files"], live["files"])
    print(f"Live bestanden downloaden en tegen het live manifest houden ({len(live['files'])})...")
    onjuist = live_bestanden_controleren(basis, live["files"])

    fouten = False
    if not verschil["gelijk"]:
        fouten = True
        print("\nVERSCHIL: wat op de site staat, is niet wat deze broncode bouwt.")
        for titel, sleutel in (("Andere inhoud", "verschillend"),
                               ("Alleen in de eigen build", "ontbreekt_live"),
                               ("Alleen live", "extra_live")):
            for p in verschil[sleutel]:
                print(f"  {titel}: {p}")
    if lokaal_raw != live_raw:
        print("  manifest.json zelf verschilt" + (" (alleen door de bestanden hierboven)"
                                                  if not verschil["gelijk"] else ""))
        fouten = True
    if onjuist:
        fouten = True
        print("\nVERSCHIL: de site levert bestanden die niet kloppen met zijn eigen manifest:")
        for p in onjuist:
            print(f"  {p}")
    if fouten:
        print("\nLet op: een gelijke build vraagt dezelfde omgeving (Linux, Python 3.13, "
              "web/bouw-constraints.txt). Zie https://anonymate.nl/controleer.html")
        return 1
    print(f"\ngelijk: wat op {basis} draait, is gebouwd uit commit {commit}\n"
          f"({len(live['files'])} bestanden, alle sha256-waarden gelijk aan de eigen build "
          f"en aan wat de site levert)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
