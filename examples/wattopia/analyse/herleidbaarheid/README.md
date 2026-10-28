# Herleidbaarheidstoets

Configuratie en bevindingen van de herleidbaarheidstoets op deze dataset, uitgevoerd met
[AnonyMate](https://github.com/anonymate-nl/anonymate). Het eindrapport met het advies aan de
bronhouder staat in [`../../docs/herleidbaarheid.md`](../../docs/herleidbaarheid.md).

- **In git:** de scripts, de configuraties (QID-keuze, aanvallersscenario's, populatie-afbakening,
  drempel p) en de geaggregeerde bevindingen in het rapport.
- **Niet in git:** `uitvoer/`, want die bevat regels per woning. Een eventuele kandidaten-adressenlijst
  heet `bijlage_NIET_PUBLICEREN...` en blijft ook buiten git.

**Privacynorm:** p = 0,09 (k ≥ 11 en δ ≤ 0,09), de standaard van AnonyMate; niet aangepast aan de uitkomst.

| bestand | wat |
|---|---|
| `maak_invoer.py` | één rij per woning met de gepubliceerde kenmerken, in drie groepen (grondgebonden, portiekflat, typologie onbekend); schrijft naar `uitvoer/` |
| `maak_configs.py` | schrijft de TOML-configuraties naar `scenarios/` (scenario's s0 tot s4 en het advies a1, a2) |
| `draai.sh` | alles achter elkaar: invoer, configuraties, toetsen, samenvatten |
| `samenvat.py` | tellingen van woningen per scenario en k-klasse; geen regels per woning |
| `kandidaatgebieden.py` | aanvulling: voor hoeveel postcodegebieden past een heel project |
