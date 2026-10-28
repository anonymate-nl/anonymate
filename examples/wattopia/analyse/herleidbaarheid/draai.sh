#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Draait de herleidbaarheidstoets: invoer maken, configuraties schrijven, elk scenario toetsen.
# Gebruik: bash draai.sh [pad naar anonymate.exe]   (standaard: anonymate in het zoekpad)
# Voor kandidaatgebieden.py is de Python nodig waarin AnonyMate is geinstalleerd (zet PYANON).
# Uitvoer (met regels per woning) komt in uitvoer/, dat in .gitignore staat.
set -euo pipefail
cd "$(dirname "$0")"
ANONYMATE="${1:-anonymate}"
PYANON="${PYANON:-python}"
python maak_invoer.py
python maak_configs.py
for cfg in scenarios/*.toml; do
  naam=$(basename "$cfg" .toml)
  echo "== $naam"
  "$ANONYMATE" assess --config "$cfg" --out "uitvoer/$naam" > "uitvoer/$naam.log" 2>&1 || echo "mislukt: $naam"
done
python samenvat.py
"$PYANON" kandidaatgebieden.py "" > uitvoer/kandidaatgebieden.log
"$PYANON" kandidaatgebieden.py _advies > uitvoer/kandidaatgebieden_advies.log
