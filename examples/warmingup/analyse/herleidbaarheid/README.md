# Herleidbaarheidstoets

Configuraties en scripts van de herleidbaarheidstoets op deze dataset, uitgevoerd met
[AnonyMate](https://github.com/anonymate-nl/anonymate). De bevindingen en het advies staan in
[`../../docs/herleidbaarheid.md`](../../docs/herleidbaarheid.md).

- **In git:** configuraties (QID-keuze, aanvallersscenario's, populatie-afbakening, drempel p),
  scripts en geaggregeerde bevindingen.
- **Niet in git:** `uitvoer/` (gitignored): regels per woning, rapporten per scenario en een eventuele
  adressenlijst. Zo'n lijst heet `bijlage_NIET_PUBLICEREN...` en blijft buiten git.

## Privacynorm

**p = 0,09**: hoogstens ongeveer 1 op 11 kans op heridentificatie, dus k ≥ 11 en δ ≤ 0,09. Vooraf
vastgelegd, gelijk aan de standaard van AnonyMate; niet aangepast aan de uitkomst. De gevoeligheid
voor andere waarden staat in `draai.sh` (`gev_*`) en in het rapport.

## Bestanden

| bestand | wat |
|---|---|
| `maak_invoer.py` | zet `resultaten.parquet` om naar één CSV per woning (`uitvoer/wu_woningen.csv`) |
| `scenarios/*.toml` | één configuratie per scenario (QID's, aanvaller, acties) |
| `draai.sh` | alles in één keer: invoer, scenario's, gevoeligheid, samenvatting |
| `samenvatting.py` | telt woningen per k-klasse uit de uitvoer (alleen aantallen) |

## Scenario's

| scenario | aanvaller | QID's |
|---|---|---|
| s1 | register | woningtype, bouwjaar (smalste van de twee klassen), gebruiksoppervlak |
| s2 | insider | s1 + jaarverbruik gas + geïnstalleerd radiatorvermogen |
| s2a, s2b | insider | s1 + alleen het jaarverbruik, of alleen het radiatorvermogen |
| s3a | register | s1 + H uit het 2R2C-model, met tolerantie (indicatief) |
| s3b | register | s1 + C uit het model; niet te duiden, zie het rapport |
| s4a tot s4d | insider | advies: jaarverbruik en/of radiatorvermogen in klassen of weggelaten |

De dataset heeft geen locatie, geen weer en geen energielabel; daarom zijn er geen scenario's met
weerstation of label.

## Draaien

Vooraf: AnonyMate geïnstalleerd en de populatie gebouwd (`anonymate ingest ...`, `anonymate build`),
en de preprocessing gedraaid (er moet een uitvoermap met `resultaten.parquet` zijn).

```bash
bash analyse/herleidbaarheid/draai.sh <uitvoermap van de preprocessing>
```

`anonymate` moet op het pad staan. De uitvoermap van de preprocessing staat buiten deze repo; de
ruwe data en alles wat eruit volgt blijft buiten git ([`GEBRUIKSVOORWAARDEN.md`](../../GEBRUIKSVOORWAARDEN.md)).
