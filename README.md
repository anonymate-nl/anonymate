# anonymate

**Herleidbaarheidstoets voor woning- en energiedata, tegen de volledige Nederlandse
woningvoorraad, lokaal en offline.** *[English below](#english)*

Wil je meetdata van woningen beschikbaar stellen (energieverbruik, temperaturen, warmtepompen) en
twijfel je of woningen er te herleiden zijn? anonymate rekent per record uit hoeveel woningen in
heel Nederland passen bij wat dat record prijsgeeft, en laat zien welke records je veilig kunt
publiceren, eventueel na grover maken van kenmerken.

Licentie: [EUPL-1.2](LICENSE).

## Waarom zo

- **Tegen de hele populatie, niet binnen je dataset.** k-anonimiteit *binnen* een kleine dataset
  onderschat het risico systematisch. anonymate berekent **k-map** en **δ-presence** tegen alle
  ~8 miljoen woningen uit de BAG.
- **Alles lokaal.** De publieke registers worden één keer in bulk gedownload. Daarna gebeurt alles
  op je eigen computer: de adressen die je toetst gaan nooit naar een server. Er is geen webserver
  en geen netwerkpoort.
- **Reproduceerbaar.** Elk rapport vermeldt de exacte versie van BAG, EP-online en de andere bronnen.
- **Aanvallersmodel expliciet.** Je kiest wat een aanvaller weet: alleen openbare registers, ook
  wat je van buitenaf ziet, of ook insiderkennis (installateur, leverancier, buren). Publiek
  bekende inclusiecriteria ("eengezinswoningen van 50-250 m²") horen in de populatie-afbakening.

## Installeren

Vereist Python 3.11 of nieuwer.

```bash
pipx install anonymate          # of: pip install anonymate
pipx install "anonymate[gui]"   # met desktopvenster
```

Vanuit de broncode: `pip install -e ".[dev,gui]"`.

## Eénmalig: de populatie opbouwen

```bash
anonymate ingest all        # BAG (~7,8 GB), gemeenten, KNMI-stations, EP-online
anonymate build             # -> één compact bestand met alle woningen
anonymate status            # welke bronnen, welke versies
```

- **Grote downloads elders bewaren** (externe schijf, NAS): `--downloads <map>` of
  `ANONYMATE_DOWNLOADS=<map>`. Alleen het compacte eindbestand (~enkele honderden MB) staat in
  `%LOCALAPPDATA%\anonymate` (of `ANONYMATE_HOME`) en wordt bij de analyse gelezen.
- **EP-online** vraagt een gratis API-sleutel, aan te vragen via [ep-online.nl](https://www.ep-online.nl).
  Zet die in de omgevingsvariabele `EPONLINE_API_KEY` of in een `.env`-bestand
  (`EPONLINE_API_KEY=...`). Zonder sleutel werkt alles, maar zonder energielabels.
- Een al gedownload bestand gebruiken: `anonymate ingest bag --file bag-light.gpkg`.

Uitproberen zonder downloads kan met `--synthetic` (een verzonnen populatie).

## Toetsen

```bash
anonymate detect mijn-dataset.csv                       # welke kolommen zijn verdacht?
anonymate assess mijn-dataset.csv --auto --out uitvoer  # toetsen met gedetecteerde QID's
anonymate suggest mijn-dataset.csv --auto               # welke generalisaties helpen?
anonymate wizard mijn-dataset.csv                       # stap voor stap met vragen
anonymate-gui                                           # desktopvenster
```

Veelgebruikte opties:

| optie | betekenis |
|---|---|
| `--qid kolom=bouwjaar` | kolom als quasi-identifier (ook `direct` of `geen`) |
| `--p 0.09` | maximale kans op heridentificatie, 0,05-0,33; k = round(1/p) |
| `--scenario register\|zichtbaar\|insider` | wat de aanvaller weet |
| `--scope gemeente=Zwolle,Deventer` | populatie afbakenen (regio, `oppervlakte=50-250`, `eengezins=true`) |
| `--config analyse.toml` | alles vastleggen in een bestand, zie [voorbeeld](docs/config-voorbeeld.toml) |

Invoer: CSV, Excel of Parquet. Kenmerken mogen exact zijn (`1974`) of al in klassen (`1960-1979`,
`115-124`, `<1945`, `A|B`). Staan er adressen of BAG-ID's in, dan kan anonymate lokaal de
registerwaarden erbij zoeken; de adreskolommen worden nooit in de publiceerbare uitvoer opgenomen.

Uitvoer (`--out`):

| bestand | inhoud |
|---|---|
| `publiceerbaar.csv` | records die de toets doorstaan, zonder directe identificatoren |
| `rapport.md` | samenvatting, drempel, bronversies, generalisatiestappen |
| `samenvatting.json` | idem, machineleesbaar |
| `rapport_per_record.csv` | per record k, δ, status en reden: **intern, niet publiceren** |

## Hoe het rekent

- **Een gepubliceerde waarde is een voorwaarde op de populatie.** `bouwjaar 1960-1979` betekent
  "elke woning met een bouwjaar in dat bereik"; een lege cel betekent "elke woning".
- **k-map**: het aantal woningen in de (afgebakende) populatie dat aan alle voorwaarden van een
  record voldoet. De kans op juiste heridentificatie is 1/k. Een record heeft risico als
  k < round(1/p).
- **δ-presence**: het deel δ = f/k van die woningen dat in de dataset zit. Is δ groot, dan kan een
  aanvaller concluderen *dát* een woning meedoet, ook zonder het record aan te wijzen. Risico als
  δ > δ_max (standaard p).
- **Onbekende registerwaarden** (bijvoorbeeld woningen zonder geregistreerd label) tellen
  standaard *niet* mee als match. Dat maakt klassen kleiner en de toets dus strenger.
- **Kenmerken zonder volledig register** (zonnepanelen, installatiedatum, verbruik) kunnen niet
  geteld worden. Hun populatiefrequentie wordt geschat uit de verdeling in de dataset zelf; het
  rapport markeert dat als schatting.

Waarom geen ARX of τ-ARGUS? Beide zijn Java, lastig te bundelen, en rekenen standaard binnen de
dataset. De populatietelling die hier nodig is, is met DuckDB-joins over de lokale BAG compact,
snel en volledig te testen.

## Bronnen

| bron | wat | licentie |
|---|---|---|
| [BAG](https://www.pdok.nl/pdok-downloads) (Kadaster, via PDOK) | adressen, bouwjaar, oppervlakte, ligging | CC0 |
| [Bestuurlijke gebieden](https://www.pdok.nl/pdok-downloads) (PDOK) | gemeente, provincie | CC0 |
| [EP-online](https://www.ep-online.nl) (RVO) | energielabels | open data, API-sleutel |
| [KNMI](https://www.daggegevens.knmi.nl) | weerstations | open data |

## Herleidbaarheidstoets op aanvraag

Wil je een dataset laten toetsen die je (nog) niet zelf wilt of kunt analyseren? Neem contact op
via een issue in deze repository.

---

## English

**Re-identification risk assessment for Dutch dwelling and energy data, against the full Dutch
housing stock, locally and offline.**

anonymate computes, for every record of a dataset you want to publish, how many dwellings in the
whole country match what that record reveals (**k-map**), and what share of those dwellings is in
your dataset (**δ-presence**). It uses a local copy of the public registers (BAG, EP-online), so
the addresses you assess never leave your machine, and it records the exact register versions in
every report.

```bash
pipx install anonymate
anonymate ingest all && anonymate build     # once: ~8 GB download, compact local population
anonymate assess data.csv --auto --out out  # risk per record + publishable subset
anonymate suggest data.csv --auto           # generalisations that make records pass
```

The risk threshold `p` (0.05-0.33, default 0.09) gives `k = round(1/p)`. Attacker scenarios:
public registers only, plus what is observable from outside, plus insider knowledge. Known
inclusion criteria of the study belong in the population scope (`--scope`), because they are
background knowledge. Command-line help and reports are bilingual (Dutch first).

License: EUPL-1.2.
