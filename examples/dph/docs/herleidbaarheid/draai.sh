#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Herleidbaarheidstoets van de DPH-woningkenmerken, van ruwe data tot rapportgetallen.
# Vooraf: de ruwe dataset in data/raw/, de pijplijn gedraaid (data/processed/homes.parquet), en
# anonymate geïnstalleerd met een lokale populatie (anonymate ingest ... && anonymate build).
# Gebruik: bash docs/herleidbaarheid/draai.sh <anonymate-versie>, bv. 9c59a48 (de git-commit).
set -euo pipefail
hier=$(cd "$(dirname "$0")" && pwd)
versie=${1:?geef de anonymate-versie (commit) als naam van de uitvoermap}
uit="$hier/../../data/analyse/herleidbaarheid/v$versie"
python "$hier/maak_invoer.py"
mkdir -p "$uit"
anonymate status > "$uit/bronnen.txt"
for cfg in "$hier"/scenarios/*.toml; do
  s=$(basename "$cfg" .toml)
  echo "== $s"
  anonymate assess --config "$cfg" --out "$uit/uit_$s" --kandidaten > "$uit/$s.log" 2>&1
  head -1 "$uit/$s.log"
done
# gevoeligheid voor de norm (alleen ter informatie: de norm zelf ligt vooraf vast)
sc="$hier/scenarios"
for run in "s2b_staarten_grover 0.05" "s2_register_met_weerstation 0.2"; do
  set -- $run
  anonymate assess --config "$sc/$1.toml" --p "$2" --out "$uit/gevoeligheid_$1_p$2"     > "$uit/gevoeligheid_$1_p$2.log" 2>&1
  echo "gevoeligheid $1 p=$2: $(head -1 "$uit/gevoeligheid_$1_p$2.log")"
done
anonymate assess --config "$sc/s2_register_met_weerstation.toml" --unknown-matches   --out "$uit/gevoeligheid_s2_onbekend_telt_mee" > "$uit/gevoeligheid_s2_onbekend.log" 2>&1
echo "gevoeligheid s2 onbekend telt mee: $(head -1 "$uit/gevoeligheid_s2_onbekend.log")"
python "$hier/representativiteit.py" "v$versie"
python "$hier/bijlage.py" "v$versie"
