#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Herleidbaarheidstoets van de WarmingUP-woningkenmerken, van uitvoer van de preprocessing tot
# rapportgetallen. Vooraf: de preprocessing gedraaid (resultaten.parquet in de uitvoermap) en
# AnonyMate geïnstalleerd met een lokale populatie (anonymate ingest ... && anonymate build).
# Gebruik: bash analyse/herleidbaarheid/draai.sh <uitvoermap van de preprocessing>
# Alles wat regels per woning bevat komt in uitvoer/ (gitignored).
set -euo pipefail
hier=$(cd "$(dirname "$0")" && pwd)
bron=${1:?geef de uitvoermap van de preprocessing (met resultaten.parquet)}
uit="$hier/uitvoer"
python "$hier/maak_invoer.py" "$bron"
mkdir -p "$uit"
anonymate status > "$uit/bronnen.txt"
cd "$hier"
for cfg in scenarios/*.toml; do
  s=$(basename "$cfg" .toml)
  anonymate assess --config "$cfg" --out "$uit/uit_$s" > "$uit/$s.log" 2>&1
  echo "$s: $(head -1 "$uit/$s.log")"
done
# Gevoeligheid (alleen ter informatie: de norm zelf, p = 0,09, ligt vooraf vast).
gev() { # naam, scenario, opties...
  n=$1; s=$2; shift 2
  anonymate assess --config "scenarios/$s.toml" "$@" --out "$uit/uit_gev_$n" > "$uit/gev_$n.log" 2>&1
  echo "gev_$n: $(head -1 "$uit/gev_$n.log")"
}
gev s1_p005                 s1_register               --p 0.05
gev s1_onbekend_telt_mee    s1_register               --unknown-matches
gev s1_deelen               s1_register               --scope knmi_station=275
gev s2_p020                 s2_insider                --p 0.2
gev s2_onbekend_telt_mee    s2_insider                --unknown-matches
gev s4a_p005                s4a_insider_beide_grof    --p 0.05
gev s4a_deelen              s4a_insider_beide_grof    --scope knmi_station=275
gev s4b_deelen              s4b_insider_beide_grover  --scope knmi_station=275
gev s4c_deelen              s4c_insider_verbruik_grof_zonder_vermogen --scope knmi_station=275
python "$hier/samenvatting.py"
