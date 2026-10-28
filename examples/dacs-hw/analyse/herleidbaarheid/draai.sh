#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Herleidbaarheidstoets van de DACS-HW-woningdata, van verwerkte data tot rapportgetallen.
# Vooraf: de pijplijn gedraaid (data/processed/household_monthly.parquet) en AnonyMate geinstalleerd
# met een lokale populatie (anonymate ingest pakket of ingest all, daarna build).
# Gebruik: bash analyse/herleidbaarheid/draai.sh   (uitvoer naar uitvoer/, gitignored)
set -euo pipefail
hier=$(cd "$(dirname "$0")" && pwd)
uit="$hier/uitvoer"
anonymate=${ANONYMATE:-anonymate}
python "$hier/maak_invoer.py"
mkdir -p "$uit"
"$anonymate" status > "$uit/bronnen.txt"
for cfg in "$hier"/scenarios/*.toml; do
  s=$(basename "$cfg" .toml)
  "$anonymate" assess --config "$cfg" --out "$uit/uit_$s" > "$uit/$s.log" 2>&1
  echo "$s: $(head -1 "$uit/$s.log")  $(sed -n 3p "$uit/$s.log")"
done
# gevoeligheid voor de norm (alleen ter informatie: de norm zelf ligt vooraf vast op p = 0,09)
sc="$hier/scenarios"
for run in "s1b_register_dorp 0.05" "s1c_register_dorp_eengezins 0.2" "s3d_insider_verbruik_staarten 0.05"; do
  set -- $run
  "$anonymate" assess --config "$sc/$1.toml" --p "$2" --out "$uit/gevoeligheid_$1_p$2" > "$uit/gevoeligheid_$1_p$2.log" 2>&1
  echo "gevoeligheid $1 p=$2: $(head -1 "$uit/gevoeligheid_$1_p$2.log")  $(sed -n 3p "$uit/gevoeligheid_$1_p$2.log")"
done
