"""Zet de webversie klaar in web/dist/: de pagina, de schil, de worker en de wheel van anonymate.

    python web/maak.py
    python -m http.server -d web/dist 8000        # en open http://localhost:8000

De wheel wordt gebouwd met SOURCE_DATE_EPOCH uit de laatste commit, zodat twee builds van
dezelfde commit dezelfde bytes geven. wheel.json vertelt de worker welke wheel hij moet laden,
met de SHA-256 erbij (voor de controlepagina van later; docs/werk/webversie.md).

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
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DIST = HERE / "dist"
FILES = ["index.html", "app.js", "worker.js"]


def main() -> int:
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
    sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    (DIST / "wheel.json").write_text(json.dumps(
        {"wheel": wheel.name, "version": version, "sha256": sha}, indent=2), encoding="utf-8")
    print(f"klaar: {DIST} ({wheel.name}, sha256 {sha[:16]}…; "
          f"{populatie.name} {populatie.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
