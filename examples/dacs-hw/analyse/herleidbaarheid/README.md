# Herleidbaarheidstoets

Configuratie van de herleidbaarheidstoets op de DACS-HW-woningdata, uitgevoerd met de publieke tool
`anonymate` (AnonyMate). De bevindingen en het advies staan in
[`docs/herleidbaarheid.md`](../../docs/herleidbaarheid.md).

- **In git:** de scripts, de scenarioconfiguraties (`scenarios/*.toml`: kenmerken, aanvaller,
  populatie-afbakening, norm p) en geaggregeerde bevindingen (in het rapport).
- **Niet in git:** `uitvoer/`. Daar staan de invoer per woning en de rapporten per woning; die zijn
  per woning en horen niet in versiebeheer. Een eventuele adressenlijst heet
  `bijlage_NIET_PUBLICEREN...` en blijft ook buiten git. Beide staan in `.gitignore`. Voor deze
  toets is geen adressenlijst gemaakt: zie het rapport.

## Privacynorm

**p = 0,09**: hoogstens ongeveer 1 op 11 kans op heridentificatie, dus k ≥ 11 en δ ≤ 0,09. Dat is
de standaard van AnonyMate en dezelfde norm als bij andere woningdatasets. De norm is vooraf vast
gelegd en wordt niet aangepast aan de uitkomst; afwegen gebeurt binnen de norm.

## Bestanden

| bestand | wat |
|---|---|
| `maak_invoer.py` | maakt uit `data/processed/household_monthly.parquet` de invoer per woning (`uitvoer/dacs_hw_woningen.csv`) |
| `scenarios/*.toml` | een aanvallersscenario per bestand: `s1*` register, `s2` zichtbaar, `s3*` insider, `g*` gevoeligheid van de afbakening |
| `draai.sh` | draait alles en de gevoeligheid voor de norm; schrijft naar `uitvoer/` |

## Draaien

Vooraf: de pijplijn is gedraaid, AnonyMate is geïnstalleerd en de populatie is opgebouwd
(`anonymate ingest pakket`, of `ingest all`, en dan `anonymate build`).

```bash
ANONYMATE=<pad naar anonymate> bash analyse/herleidbaarheid/draai.sh
```
