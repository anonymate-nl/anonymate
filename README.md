# AnonyMate: herleidbaarheidstoets voor woningdata

Een lokale tool die toetst of woning- en energiedata **te herleiden** zijn tot een adres, voordat
je ze publiceert. Hij vergelijkt elk record met de volledige Nederlandse woningvoorraad (BAG,
EP-online) en laat zien welke records je veilig kunt delen, eventueel na het grover maken van
kenmerken.

De vraag is telkens dezelfde: **op hoeveel woningen in Nederland lijkt dit record, en weet een
aanvaller daarmee welke woning het is?**

**Nieuw hier?** Kies bij [Gebruiken](#gebruiken) de ingang die bij je past: zonder installeren in de
browser, met het Windows-programma, of als programmeur. In vijf minuten een eerste toets.
*[English summary below](#english).*

## Inhoudsopgave

* [Hoe het werkt](#hoe-het-werkt)
* [Wat doet het](#wat-doet-het)
  * [Herleidbaarheid meten: k-map en δ-presence](#herleidbaarheid-meten-k-map-en-δ-presence)
  * [Verdachte kolommen vinden](#verdachte-kolommen-vinden)
  * [Weer als verborgen locatie](#weer-als-verborgen-locatie)
  * [Aanvallersscenario's en populatie-afbakening](#aanvallersscenarios-en-populatie-afbakening)
  * [Anonimiseren: grover maken en weglaten](#anonimiseren-grover-maken-en-weglaten)
* [Gebruiken](#gebruiken)
  * [Snel beginnen zonder installeren](#snel-beginnen-zonder-installeren)
  * [Snel beginnen met installeren, zonder te programmeren](#snel-beginnen-met-installeren-zonder-te-programmeren)
  * [Snel beginnen als programmeur](#snel-beginnen-als-programmeur)
  * [Eénmalig: de populatie opbouwen](#eénmalig-de-populatie-opbouwen)
  * [Sneller: een datapakket plus je eigen EP-online-bestand](#sneller-een-datapakket-plus-je-eigen-ep-online-bestand)
  * [Toetsen](#toetsen)
  * [Uitvoer](#uitvoer)
* [Hoe het rekent](#hoe-het-rekent)
* [Ontwikkelen](#ontwikkelen)
  * [Inzien](#inzien)
  * [Bijdragen](#bijdragen)
* [Documentatie](#documentatie)
* [Status](#status)
* [Codeondertekening](#codeondertekening)
* [Licentie](#licentie)
* [Met dank aan](#met-dank-aan)
* [English](#english)

## Hoe het werkt

```mermaid
flowchart LR
    subgraph publiek["Publieke registers (bulk, eenmalig)"]
        BAG["BAG<br/>(PDOK, ~7,8 GB)"]
        EP["EP-online<br/>(RVO)"]
        GEB["Gemeenten<br/>(PDOK)"]
        KNMI["KNMI-stations"]
    end
    subgraph lokaal["Jouw computer — offline"]
        POP[("populatie<br/>~8,4 mln woningen")]
        DS["jouw dataset"]
        T{{"toets:<br/>k-map, δ-presence"}}
        OUT["publiceerbare selectie<br/>+ rapport"]
    end
    BAG --> POP
    EP --> POP
    GEB --> POP
    KNMI --> POP
    POP --> T
    DS --> T
    T --> OUT
    DS -. "nooit naar buiten" .-x publiek
```

Het principe is **alles lokaal, tegen de hele populatie**:

1. **Eén keer downloaden, in bulk.** De publieke registers worden in hun geheel opgehaald, niet
   per adres bevraagd. Zo lekt de tool nooit welke adressen je toetst, en rekent hij tegen de
   échte achtergrondpopulatie in plaats van een fragment ervan.
2. **Daarna volledig offline.** Toetsen, grover maken en rapporteren gebeuren op je eigen
   computer. Er is geen webserver en geen netwerkpoort.
3. **Reproduceerbaar.** Elk rapport vermeldt de exacte versie van elke bron.

## Wat doet het

### Herleidbaarheid meten: k-map en δ-presence

Per record telt anonymate hoeveel woningen in de (afgebakende) populatie passen bij alles wat het
record prijsgeeft: **k**. De kans op een juiste heridentificatie is 1/k. Daarnaast berekent het
welk deel **δ** van die woningen in de dataset zit: de kans dat een aanvaller terecht concludeert
*dát* een woning meedoet, ook zonder te weten welke rij de hare is (**deelnameonthulling**). Een
record is publiceerbaar als k ≥ round(1/p) en δ ≤ p, met p vrij
instelbaar tussen 0,05 en 0,33. De standaard is p = 0,09 (k ≥ 11), de waarde die in de medische
wereld gangbaar is; netbeheerders hanteren k ≥ 10 voor verbruiksdata per postcode. Voor k is
die grens onderbouwd; of δ ≤ p de goede grens voor deelnameonthulling is, is nog een open vraag
(zie het [kladblok](docs/werk/KLADBLOK.md)).

Kenmerken mogen exact zijn (`1974`) of al in klassen (`1960-1979`, `[150 - 199]`, `<1945`,
`2000=>`, `A|B`); een klasse telt als het hele bereik.

### Verdachte kolommen vinden

anonymate stelt per kolom voor wat die is, op basis van de naam (Nederlands en Engels) en de
waarden:

| rol | voorbeelden | wat ermee gebeurt |
|---|---|---|
| **directe identificator** | adres, huisnummer, coördinaten, BAG-ID, absolute meterstanden | nooit publiceren |
| **quasi-identifier** | bouwjaar, oppervlakte, energielabel, woningtype, postcode, gemeente | meetellen in de toets |
| **verborgen locatie** | weerstation, H3-cel, lat/lon van een weer-interpolatiepunt | omzetten naar een regio en meetellen |
| **afgeleid** | specificaties die volledig uit een toesteltype volgen | lekt hetzelfde als de bron |
| **meetwaarde** | tijdreeksen, temperaturen | geen quasi-identifier |

Elk voorstel kun je overrulen.

Bij getallen kijkt anonymate ook hoe ze gelezen moeten worden. Zijn alle waarden veelvouden van
5, 10, 25, 50 of 100, dan zijn ze waarschijnlijk afgerond: `1965` betekent dan 1963-1967, niet
precies 1965. Klassen als `100-150` en `150-200` delen een grens die in werkelijkheid bij één van
beide hoort. Dat is niet aan de waarden te zien; anonymate stelt een lezing voor (afgerond naar het
dichtstbij), laat in het rapport zien wat een andere lezing zou geven, en je legt het vast met
`[afronding]` en `[klassegrens]` in de [configuratie](docs/config-voorbeeld.toml) of in de kolom
"lezing" van het venster.

### Weer als verborgen locatie

Weer bij de woning is nuttig, maar wijst de locatie aan. In de stap **Weerlocatie** kies je hoe
grof: het dichtstbijzijnde KNMI-station, of een H3-cel na willekeurige ruis (standaard niveau 5,
σ = 10 km). Een kaart laat per cel zien hoeveel woningen erin staan en, na een klik, waar een woning
met die cel werkelijk kan liggen. Staat er al weer in de dataset, dan speelt anonymate rechercheur:
`anonymate weerspoor` (of "Weer al in de data?" in het venster) zoekt welk station, welke cel of
welk punt de reeksen verklaart, ook bij verschoven uren, zomertijd, stationswissels en afwijkende
stationssets, en toetst die locatie mee. Zie
[`docs/herleidbaarheid-uitleg.md`](docs/herleidbaarheid-uitleg.md), paragraaf 5.

### Representativiteit zonder de kenmerken

Lijkt de dataset op de woningvoorraad waaruit hij komt? `anonymate representativiteit` vergelijkt
per kenmerk de dataset met de doelpopulatie (dezelfde afbakening als bij de toets): SMD en
Wasserstein-afstand voor getallen, TVD voor categorieën, en hoe vaak een aselecte steekproef van
evenveel woningen minstens zoveel afwijkt. Met `--koppel` worden aan beide kanten de
registerwaarden vergeleken. De uitkomst (`--uit rep.json`) bevat alleen maten, aandelen per klasse
(voor de dataset alleen bij klassen van minstens k records) en alle parameters om na te rekenen, dus
geen kenmerken per record. Zo kun je laten zien dat de dataset representatief is zonder bouwjaar,
type of label per woning te publiceren.

```bash
anonymate representativiteit mijn-dataset.csv --koppel postcode,huisnummer \
    --kenmerk bouwjaar=1945,1965,1975,1992,2006 --kenmerk woningtype --kenmerk energielabel \
    --scope eengezins=true --uit representativiteit.json
```

In het venster en de webversie staat de knop **Representativiteit** bij de uitkomst (stap 7). Die
vergelijkt bouwjaar, woningtype, energielabel en oppervlakte uit het register, via de
koppelkolommen van stap 4, met de afbakening van de toets; de uitkomst komt ook in de opgeslagen
map of de zip (`representativiteit.json` en `.md`).

### Aanvallersscenario's en populatie-afbakening

Wat een aanvaller weet, bepaalt wat meetelt:

* **register**: alleen wat in openbare registers staat (BAG, EP-online);
* **zichtbaar**: ook wat je van buitenaf ziet (zonnepanelen, glas, buitenunit);
* **insider**: ook wat een installateur, leverancier of buur weet (installatiedatum, vermogen,
  jaarverbruik).

Kenmerken zonder volledig register worden **geschat** uit de verdeling in de dataset; het rapport
markeert dat. Publiek bekende **inclusiecriteria** ("vrijstaande en twee-onder-een-kapwoningen van vóór
1990 in Gelderland") horen in de populatie-afbakening: ze zijn achtergrondkennis, en wie ze weglaat
onderschat het risico.

### Anonimiseren: grover maken en weglaten

Klassen (`bouwjaar` per 10 jaar, met open staarten), eigen klassegrenzen, categorieën samenvoegen
(labels A-B / C-D / E-G), locatie vergroven (postcode → gemeente → provincie), begrensde ruis
toevoegen en kenmerken weglaten. Ruis telt eerlijk mee: de toets gaat uit van een aanvaller die de
methode kent en een waarde met ruis tot ±n dus als bereik leest. Is een dataset al met ruis
gepubliceerd (bijvoorbeeld een locatie met ruis vóór het snappen naar een H3-cel), dan geef je die
tolerantie op en telt de toets de buurcellen mee.

Na elke stap toont anonymate hoeveel records slagen en hoeveel detail het kost; `suggest` zoekt
zelf een reeks stappen. Weglaten is niet gratis: het rapport meet per kolom hoeveel het
gepubliceerde deel verschuift ten opzichte van de hele dataset, en of dat meer is dan bij
willekeurig weglaten.

## Gebruiken

Drie ingangen, naar wat je wilt doen. Het is steeds dezelfde toets, met dezelfde uitkomsten en
dezelfde teksten; ook overal lokaal: je dataset gaat de computer niet af.

| jij wilt | ingang | wat je nodig hebt |
|---|---|---|
| **niets installeren**: eerst eens kijken, of een dataset snel toetsen | de browserversie op [anonymate.nl/app](https://anonymate.nl/app/) | een recente Chrome, Edge of Firefox, op Windows, macOS of Linux |
| **installeren en instellen, niet programmeren** | het Windows-programma (een venster), of `anonymate-gui` op macOS en Linux | Windows 10 of 11 (zip, geen installatie), of Python 3.11+; eenmalig het datapakket (~430 MB); eventueel een gratis EP-online-sleutel |
| **programmeren of automatiseren** | de opdrachtregel, `anonymate wizard` en `import anonymate` | Python 3.11+ |

### Snel beginnen zonder installeren

1. Open [anonymate.nl/app](https://anonymate.nl/app/). De eerste keer laadt de pagina Python en de
   rekenbibliotheken (ongeveer 20 MB); daarna werkt alles in het browservenster, ook offline.
2. Kies **Oefenmodus**: 62 verzonnen woningen in een verzonnen Nederland. Leg de norm vast en loop
   de stappen door tot de uitkomst.
3. Een eigen dataset (CSV) kies je bij stap 1. Voor een echte toets haal je daar eerst met
   **Populatie ophalen** de woningvoorraad van heel Nederland op (BAG, 3D-BAG, CBS, KNMI; zonder
   energielabels; ongeveer 565 MB, één keer per maand, bewaard in de browser). Energielabels
   voeg je toe met je eigen totaalbestand van EP-online (kaart **Energielabels toevoegen**): dat
   bestand komt nooit van anonymate.nl. Toetsen tegen 8,4 miljoen woningen vraagt ruim 2 GB
   geheugen in de browser; sluit op een laptop met 8 GB eerst andere zware programma's.

Of er echt niets wordt verstuurd, en of wat er draait uit deze broncode komt, kun je zelf nagaan:
[anonymate.nl/controleer.html](https://anonymate.nl/controleer.html).

### Snel beginnen met installeren, zonder te programmeren

**Windows:** download de [zip van de laatste release](https://github.com/anonymate-nl/anonymate/releases),
pak hem uit en start `anonymate-gui.exe`. Beheerrechten zijn niet nodig. Het programma is nog niet
ondertekend, dus Windows waarschuwt: kies *Meer info* en dan *Toch uitvoeren*.
**macOS en Linux:** `pipx install "anonymate[gui] @ git+https://github.com/anonymate-nl/anonymate"`
en dan `anonymate-gui`.

In het venster begin je het snelst met **Oefenen met het voorbeeld** (stap 1): 62 verzonnen
woningen, hun weer ([`docs/voorbeeld/weer.csv`](docs/voorbeeld/weer.csv)) en een verzonnen
Nederland om ze in te zoeken, zonder downloads. Een oranje balk laat zien dat je oefent; je eigen
dataset openen stopt de oefenmodus.

Voor een **echte toets** heeft het programma eenmalig de hele woningvoorraad nodig. Dat is één
opdracht, in een opdrachtprompt in de uitgepakte map (op macOS en Linux zonder `.exe`):

```bash
anonymate.exe ingest pakket     # het datapakket downloaden (~430 MB), controleren en installeren
anonymate.exe status            # welke bronnen en versies er nu staan
```

Wil je ook energielabels meenemen, dan koppel je daarna je eigen EP-online-bestand; zie
[Sneller: een datapakket plus je eigen EP-online-bestand](#sneller-een-datapakket-plus-je-eigen-ep-online-bestand).
Liever stap voor stap in de terminal, met vragen in plaats van opties? Dan is er
`anonymate wizard`.

### Snel beginnen als programmeur

```bash
pipx install "anonymate @ git+https://github.com/anonymate-nl/anonymate"   # of pip install in een venv
```

Op de opdrachtregel probeer je het voorbeeldbestand [`docs/voorbeeld/woningen.csv`](docs/voorbeeld/woningen.csv)
(62 verzonnen woningen, waarvan één aan de dunbevolkte Noord-Hollandse kust en één op Vlieland;
download het, of clone de repo):

```bash
anonymate detect woningen.csv
anonymate assess woningen.csv --auto --qid postcode=direct --synthetic
anonymate suggest woningen.csv --auto --qid postcode=direct --synthetic
```

1. `detect` wijst de verdachte kolommen aan: huisnummer is een directe identificator, bouwjaar,
   oppervlakte en woningtype zijn quasi-identifiers, jaarverbruik kent alleen een insider.
2. `assess` toetst: met exact bouwjaar, exacte oppervlakte, gemeente, type en label is **geen
   enkele** woning publiceerbaar, want elke woning is uniek. `--qid postcode=direct` zegt dat de
   postcode niet gepubliceerd wordt.
3. `suggest` zoekt wat je grover moet maken: bouwjaar in klassen van 10 jaar, oppervlakte per
   25 m² en provincie in plaats van gemeente maken de meeste woningen publiceerbaar.

`--synthetic` gebruikt een verzonnen populatie: handig om de tool te leren kennen, niet om
conclusies aan te verbinden. Voor een echte toets installeer je eerst de populatie
(`anonymate ingest pakket`) en laat je `--synthetic` weg. Alle instellingen van een toets kunnen ook
in een bestand: [`docs/config-voorbeeld.toml`](docs/config-voorbeeld.toml) (`anonymate assess --config …`).

Als library:

```python
from anonymate import Threshold, assess
from anonymate.invoer import qids_from, read_dataset
from anonymate.store import Store

df = read_dataset("woningen.csv")
qids, direct = qids_from(df, {"postcode": "direct"}, auto=True)   # voorstel per kolom, met correctie
a = assess(df, qids, Store.open().population(), Threshold(p=0.09))  # k ≥ 11
print(a.summary())                    # publiceerbaar, met risico, zonder match, k-mediaan, …
publiceerbaar = df.loc[a.ok].drop(columns=direct)
```

### Eénmalig: de populatie opbouwen

```bash
anonymate ingest all        # BAG, gemeenten, KNMI-stations, EP-online
anonymate build             # -> één compact bestand met alle woningen
anonymate status            # welke bronnen, welke versies
```

* **Grote originelen elders bewaren** (externe schijf, NAS): `--downloads <map>` of
  `ANONYMATE_DOWNLOADS=<map>` (ook in een `.env`-bestand). Alleen het compacte eindbestand
  (~0,5 GB) staat in `%LOCALAPPDATA%\anonymate` (of `ANONYMATE_HOME`) en wordt bij de toets
  gelezen.
* **EP-online** vraagt een gratis API-sleutel, aan te vragen via
  [ep-online.nl](https://www.ep-online.nl). Zet die als `EPONLINE_API_KEY` in de omgeving of in
  `.env`. Zonder sleutel werkt alles, maar zonder energielabels.
* **Hitte-eiland (UHI)**: `anonymate ingest uhi` haalt een kleine tabel per postcode op (3 MB;
  het woninggewogen gemiddelde van de RIVM-kaart over de adrespunten van de BAG, zomergemiddelde
  in °C) en `anonymate build` neemt hem op als kolom `uhi`. Het datapakket bevat `uhi` al.
  De waarde is dus per postcode; een variant per woning volgt (`anonymate ingest uhi --raster`
  leest de RIVM-kaart zelf, ~2 GB, en vraagt de optionele extra `pip install anonymate[uhi]`).
  Zonder `uhi` gebruikt het tabblad Hitte-eiland een eigen bestand (pc6, uhi).
* Past op een laptop met 8 GB geheugen: inlezen en opbouwen gebeuren in blokken, met een vaste
  geheugengrens.

### Sneller: een datapakket plus je eigen EP-online-bestand

De hele woningvoorraad zelf opbouwen kost enkele uren (vooral de BAG). Het kan ook in een half
uur: elke maand bouwt GitHub de populatie en publiceert een **datapakket** (BAG, 3D-BAG,
gemeenten, KNMI, het hitte-eiland per postcode van het RIVM en de daaruit berekende
warmtesignatuur; **zonder EP-online**). Downloaden en gebruiken kan zonder GitHub-account:

```bash
anonymate ingest pakket     # downloadt het laatste pakket, controleert de sha256 en bouwt de populatie
anonymate status            # bronnen en versies, ook "(uit datapakket)"
```

Of haal het zelf op:
[anonymate-datapakket.zip](https://github.com/anonymate-nl/anonymate/releases/download/datapakket/anonymate-datapakket.zip)
(met [manifest.json](https://github.com/anonymate-nl/anonymate/releases/download/datapakket/manifest.json)
voor de sha256) en geef het door met `anonymate ingest pakket --file anonymate-datapakket.zip`.
Eerdere maanden staan als release `datapakket-JJJJ-MM`.

In Windows PowerShell 5.1 kan de voortgang in een pipe (bv. `| Tee-Object log.txt`) tekens als `·`
verminkt tonen: AnonyMate schrijft UTF-8, PowerShell leest de oude codetabel. Zet dan eerst
`[Console]::OutputEncoding = [Text.Encoding]::UTF8`.

**Energielabels** zitten (nog) niet in het pakket; die koppel je zelf, lokaal, met je eigen
EP-online-bestand:

1. Vraag een gratis API-sleutel aan bij [apikey.ep-online.nl](https://apikey.ep-online.nl/) en
   zet die als `EPONLINE_API_KEY` in de omgeving of in `.env`. Dan downloadt `anonymate ingest
   ep-online` het totaalbestand met jouw sleutel. Heb je het totaalbestand al (zip of csv), dan
   zonder sleutel: `anonymate ingest ep-online --file <totaalbestand>`.
2. `anonymate ingest pakket` opnieuw: het label en de labelgegevens worden op het BAG-id gekoppeld
   en de op labels gebaseerde signaturen erbij berekend. Die gegevens verlaten je computer niet.
   Is de sleutel bekend, dan doet `anonymate ingest pakket` stap 1 en 2 zelf (pakket, EP-online
   en populatie in één keer, hervatbaar). In het venster (stap 6, kaart "Populatie") staat
   dezelfde route met uitleg, een sleutelcontrole en een tijdschatting.

Zonder energielabels werkt het ook, maar dan onderschat de toets het risico als je dataset een
label of een signatuur uit het label bevat. In het Windows-programma gaat het met dezelfde
opdrachten via `anonymate.exe` in de uitgepakte map; in het venster kies je het totaalbestand bij
"Ik heb het EP-online-bestand al". In de browserversie sleep je het totaalbestand op de kaart
**Energielabels toevoegen**. Zelf ophalen met je sleutel kan de browserversie niet: de API van
EP-online staat verzoeken vanuit een webpagina niet toe (geen CORS; getest 3-10-2026), en je
sleutel hoort ook niet in een webpagina.

### Toetsen

```bash
anonymate assess mijn-dataset.csv --auto --out uitvoer   # toetsen met gedetecteerde kenmerken
anonymate suggest mijn-dataset.csv --auto                # welke generalisaties helpen?
anonymate wizard mijn-dataset.csv                        # stap voor stap met vragen
anonymate weerspoor weer.csv --dataset mijn-dataset.csv # waar komt het weer vandaan?
anonymate representativiteit mijn-dataset.csv --kenmerk woningtype  # lijkt hij op de voorraad?
anonymate-gui                                            # desktopvenster
```

| optie | betekenis |
|---|---|
| `--qid kolom=bouwjaar` | kolom als quasi-identifier (ook `direct` of `geen`) |
| `--p 0.09` | maximale kans op heridentificatie, 0,05-0,33 |
| `--scenario register\|zichtbaar\|insider` | wat de aanvaller weet |
| `--scope gemeente=Zwolle,Deventer` | populatie afbakenen (ook `bouwjaar=1900-1989`, `woningtype=vrijstaand,twee_onder_een_kap`) |
| `--koppel postcode,huisnummer` | registerwaarden lokaal ophalen bij adressen of BAG-ID's; `--koppel auto` zoekt de kolommen zelf, `--koppel postcode=pc,huisnummer=nr,toevoeging=toev` noemt ze bij naam (handig als een deel ontbreekt) |
| `--config analyse.toml` | alles vastleggen in een bestand, zie het [voorbeeld](docs/config-voorbeeld.toml) |

Invoer: CSV, Excel of Parquet.

### Uitvoer

| bestand | inhoud |
|---|---|
| `publiceerbaar.csv` | records die de toets doorstaan, zonder directe identificatoren |
| `rapport.md` | samenvatting, drempel, bronversies, generalisatiestappen, lezing van afgeronde waarden en klassegrenzen (met wat een andere lezing geeft), representativiteit (wat het weglaten verschuift), bits per kenmerk, insiders per databron |
| `samenvatting.json` | idem, machineleesbaar |
| `rapport_per_record.csv` | per record k, δ, status en reden: **intern, niet publiceren** |

## Hoe het rekent

**Eerst de norm, dan toetsen, dan afwegen.** Stel de privacynorm p vast vóór je naar uitkomsten
kijkt, en pas hem daarna niet aan op de uitkomst. Binnen die norm weeg je af: kenmerken grover
maken of afronden (privacy tegen bruikbaarheid), en woningen die te herleidbaar blijven niet
publiceren. Het desktopvenster dwingt die volgorde af; `signatuur publiceer` weigert zonder `--p`.

* **Een gepubliceerde waarde is een voorwaarde op de populatie.** `bouwjaar 1960-1979` betekent
  "elke woning met een bouwjaar in dat bereik"; een lege cel betekent "elke woning".
* **Onbekende registerwaarden** (bijvoorbeeld een woning zonder geregistreerd label) tellen
  standaard *niet* mee als overeenkomst. Dat maakt klassen kleiner en de toets dus strenger.
* **Geschatte k.** Voor kenmerken zonder register wordt het aantal woningen geschat als k uit de
  registers × de frequentie van de waarde in de dataset, per kenmerk vermenigvuldigd.
* **Waarom geen ARX of τ-ARGUS?** Beide zijn Java, lastig mee te leveren, en rekenen standaard
  *binnen* de dataset. De populatietelling die hier nodig is, is met DuckDB-joins over de lokale
  registers compact, snel (seconden voor 8 miljoen woningen) en volledig te testen.

## Ontwikkelen

Het praktische verschil tussen deze twee: inzien kan zonder iets te installeren, bijdragen niet.

### Inzien

Begrijpen hoe het in elkaar zit, zonder iets te wijzigen. De code staat in
[`src/anonymate/`](src/anonymate), één module per verantwoordelijkheid:

| module | wat |
|---|---|
| `constraints` | gepubliceerde waarden als voorwaarde (exact, bereik, verzameling) |
| `lezing` | afgeronde waarden en klassegrenzen herkennen, en wat een andere lezing geeft |
| `qids` | catalogus van quasi-identifiers en wie ze kan kennen |
| `population` | de populatie in DuckDB, met afbakening |
| `risk` | k-map en δ-presence |
| `generalize` | anonimiseringsacties (ook ruis), informatieverlies, zoekfunctie |
| `explain` | uitleg: bits per kenmerk, insiders per databron |
| `signature` | warmtesignatuur uit alleen een adres en openbare gegevens (nta8800, mwa, best, …) |
| `rounding` | afrondingsanalyse en rainbow-frequentietabellen |
| `publicatie` | een afgeronde adres-signatuur per woning toevoegen, toetsen en afwegen |
| `detect` | voorstellen per kolom |
| `weerspoor` | weerreeksen terugleiden naar station, H3-cel of punt (de rechercheur) |
| `representativiteit` | wat het weglaten van records met de gepubliceerde kolommen doet |
| `kaart`, `stappen`, `voortgang` | rekenwerk van de stappen, de kaart en de voortgang, zonder Qt: gedeeld door het venster en de webversie |
| `invoer`, `tabel` | een dataset en Parquet inlezen, zonder pyarrow |
| `synthetic`, `voorbeeld` | het verzonnen Nederland en de voorbeelddata van de oefenmodus |
| `store`, `datapakket` | bronnen downloaden en inlezen, de populatie opbouwen, datapakketten maken en installeren — **de enige modules met netwerkverkeer** |
| `link` | lokaal koppelen via adres of BAG-ID |
| `report`, `cli`, `wizard`, `gui`, `web` | uitvoer en de manieren van gebruik (`gui_kaart`, `gui_tekening`: kaart en grafieken in het venster; `web`: de facade voor de browserversie in [`web/`](web)) |

Hoe de browserversie is opgezet (Pyodide, local-first, verifieerbaar) staat in
[`docs/werk/webversie.md`](docs/werk/webversie.md); wat nog moet gebeuren in
[`docs/werk/KLADBLOK.md`](docs/werk/KLADBLOK.md).

### Bijdragen

Code wijzigen en terugleggen:

```bash
git clone https://github.com/anonymate-nl/anonymate
cd anonymate
python -m venv .venv && .venv/Scripts/pip install -e ".[dev,gui]"   # Linux/macOS: .venv/bin/pip
pytest -q
python web/maak.py                   # de browserversie bouwen in web/dist/
python -m http.server -d web/dist    # en bekijken op http://localhost:8000
```

Tests draaien op synthetische data; een test bewaakt dat de rekenkern geen netwerk gebruikt, en CI
controleert dat twee builds van de browserversie bit voor bit gelijk zijn. Afspraken: teksten voor
gebruikers in het Nederlands en gelijk in venster en browser; namen van grootheden met hun eenheid
volgens de [physiquant__unit-conventie](https://github.com/energietransitie/physiquant__unit)
(bijvoorbeeld `adres_H__W_K_1`); het kladblok is een takenlijst, geen logboek. Bijdragen zijn welkom
via een issue of pull request.

## Documentatie

* [`docs/herleidbaarheid-uitleg.md`](docs/herleidbaarheid-uitleg.md) — begin hier: wat
  herleidbaarheid is, hoe anonymate het meet, en wat er bijzonder is aan woningregisters en
  energiedata.
* [`docs/config-voorbeeld.toml`](docs/config-voorbeeld.toml) — alle instellingen van een toets,
  met uitleg.
* [`docs/herleidbaarheid-uitleg.md`](docs/herleidbaarheid-uitleg.md) — herleidbaarheid van
  woning- en energiedata uitgelegd: meten, aanvallers, verborgen locatie (weer, H3-cellen met
  ruis), afwegen en transparantie, met kaarten.
* [`docs/warmtesignatuur.md`](docs/warmtesignatuur.md) — de signatuur uit
  openbare gegevens, de rainbow table en hoe grof je moet publiceren.
* [`docs/variabelen.md`](docs/variabelen.md) — de variabelenlijst: per kolom van de populatie en het
  datapakket de naam (volgens de physiquant__unit-conventie), bron, eenheid en type.
* [`docs/voorbeeld/`](docs/voorbeeld) — de voorbeelddata van de oefenmodus (verzonnen woningen en
  hun weer) en het script dat ze maakt.
* [`docs/werk/KLADBLOK.md`](docs/werk/KLADBLOK.md) — wat nog moet gebeuren.
* De docstrings bovenaan elke module in [`src/anonymate/`](src/anonymate) — de redenering achter
  elke keuze.

## Status

Project is: _in ontwikkeling_. De kern (toetsen, detecteren, grover maken, ruis, rapporteren met
uitleg in bits en insiders per databron) werkt en is getest; de populatie wordt opgebouwd uit de
actuele BAG en EP-online, en is beproefd op een openbare dataset van ~175 woningen. Nog niet
inhoudelijk gereviewd door derden. Wat nog moet gebeuren staat in het
[kladblok](docs/werk/KLADBLOK.md).

**Herleidbaarheidstoets op aanvraag.** Wil je een dataset laten toetsen die je niet zelf wilt of
kunt analyseren? Neem contact op via een issue in deze repository.

## Verifieerbaar

De browserversie op <https://anonymate.nl/app/> is gebouwd uit deze repository, en dat is na te
gaan: de build is reproduceerbaar, `manifest.json` bevat de commit en de SHA-256 van elk bestand,
en GitHub Actions legt de herkomst vast als attestatie. Rekenen kan met
`python web/controleer.py` (bouwt dezelfde commit opnieuw en vergelijkt met de live site) en
`gh attestation verify manifest.json --repo anonymate-nl/anonymate`. Stap voor stap, ook voor wie
alleen het netwerkverkeer in de browser wil bekijken, staat het op
[anonymate.nl/controleer.html](https://anonymate.nl/controleer.html)
([bron](website/controleer.html)).

## Codeondertekening

Het Windows-programma is nog niet ondertekend; Windows waarschuwt daarom bij de eerste start.
Ondertekening via de [SignPath Foundation](https://signpath.org) (gratis codeondertekening door
[SignPath.io](https://about.signpath.io) voor open source) is aangevraagd; daarvoor moet het project
eerst breder bekend zijn. Zodra het zover is, geldt dit beleid:

Alleen wat GitHub Actions bouwt uit de broncode in deze repository
([`release.yml`](.github/workflows/release.yml)) wordt ondertekend, en elke release pas nadat
een goedkeurder dat op SignPath heeft toegestaan.

* Committers en reviewers: [Henri ter Hofte](https://github.com/henriterhofte)
* Goedkeurders (approvers): [Henri ter Hofte](https://github.com/henriterhofte)

**Privacy.** Dit programma stuurt geen informatie naar andere systemen in een netwerk, tenzij
de gebruiker daar zelf om vraagt: alleen `anonymate ingest` downloadt, op verzoek, de openbare
registers (BAG, EP-online, KNMI). *This program will not transfer any information to other
networked systems unless specifically requested by the user or the person installing or
operating it.*

## Licentie

Deze software is beschikbaar onder de [European Union Public Licence v1.2 (EUPL-1.2)](LICENSE),
© 2026 Henri ter Hofte.

## Met dank aan

Deze software is geschreven door:

* Henri ter Hofte · [@henriterhofte](https://github.com/henriterhofte)

Ontwikkeld met [Claude Code](https://claude.com/claude-code) (Anthropic) als AI-programmeerassistent;
commits waaraan Claude Code heeft bijgedragen hebben een `Co-Authored-By`-regel.

De opzet bouwt voort op ideeën uit *NeedForHeat AnonyMate* (Ter Hofte & Kranenborg, 2025), en op
de drempelwaarden en de afweging tussen risico en bruikbaarheid uit El Emam en Arbuckle (2013).
Het bouwt daarmee voort op eerder werk van de student:

* Alexander Kranenborg · [@AlexanderKranenborg](https://github.com/AlexanderKranenborg)

Bronnen (APA 7):

* El Emam, K., & Arbuckle, L. (2013). *Anonymizing health data: Case studies and methods to get
  you started*. O'Reilly Media.
* Ter Hofte, H., & Kranenborg, A. (2025, 10 april). *NeedForHeat AnonyMate* [Presentatie]. KITE
  Expert Meeting, Rijksdienst voor Ondernemend Nederland.
  https://kennisdelen.rvo.nl/files/view/7917cf4d-ea3a-4fe4-ae7a-30210f7eeb87/20250410_kite_needforheatanonymate.pptx
  (inloggen bij KITE nodig)

We gebruiken databronnen en danken de makers daarvan:

* **BAG** (Kadaster, via [PDOK](https://www.pdok.nl/pdok-downloads)): adressen, bouwjaar,
  oppervlakte en ligging van alle woningen. CC0.
* **Bestuurlijke gebieden** (Kadaster, via [PDOK](https://www.pdok.nl/pdok-downloads)): gemeenten
  en provincies. CC0.
* **EP-online** (RVO, [ep-online.nl](https://www.ep-online.nl)): geregistreerde energielabels. Vrij
  te gebruiken met een gratis API-sleutel, onder de voorwaarden van RVO (geen open licentie).
* **KNMI** ([daggegevens.knmi.nl](https://www.daggegevens.knmi.nl)): weerstations en hun ligging.
* **Stedelijk hitte-eiland effect** (RIVM, via [Atlas Leefomgeving](https://www.atlasleefomgeving.nl)):
  raster van 10 m (RD, 27.000 x 32.500 cellen), zomergemiddelde (juni tot en met augustus) in °C,
  CC Publiek Domein 1.0 (geen beperkingen); versie van 1 juni 2022, zonder maandelijkse verversing.
  Per postcode gemiddeld over de adrespunten van de BAG (CC0): 447.304 postcodes, waarden 0 tot
  2,81 °C (mediaan 0,90); adressen buiten het raster (1.878) hebben geen waarde. De tabel staat in
  de release `bronnen-cache` (`uhi-pc6-rivm-20220601-v2.parquet`, 3 MB).

En software:

* [DuckDB](https://duckdb.org) (MIT), [pandas](https://pandas.pydata.org) (BSD-3),
  [Apache Arrow](https://arrow.apache.org) (Apache-2.0), [H3](https://h3geo.org) (Apache-2.0),
  [PySide6 / Qt for Python](https://doc.qt.io/qtforpython/) (LGPL-3.0),
  [openpyxl](https://openpyxl.readthedocs.io) (MIT).

---

## English

**anonymate** checks, before you publish dwelling or energy data, how re-identifiable each record
is against the *full* Dutch housing stock. It builds a local copy of the public registers (BAG,
EP-online) once, in bulk, and then works entirely offline, so the addresses you assess never leave
your machine. For every record it computes **k-map** (how many dwellings match; re-identification
chance 1/k) and **δ-presence** (what share of those dwellings is in your dataset), with a
configurable threshold p in [0.05, 0.33] (default 0.09, k ≥ 11). It proposes which columns are
identifiers or quasi-identifiers (including hidden location such as weather stations and H3
cells), supports attacker scenarios (public registers / observable / insider) and known inclusion
criteria, and searches generalisations that make records publishable, with a risk-utility report
that also measures how much leaving out records shifts the published data. It traces weather
series already in a dataset back to the KNMI station, H3 cell or point they were computed for, and
has a practice mode with made-up dwellings and weather, so it can be tried without downloads.

```bash
pipx install "anonymate[gui] @ git+https://github.com/anonymate-nl/anonymate"
anonymate ingest all && anonymate build     # once: download registers, build local population
anonymate assess data.csv --auto --out out  # risk per record + publishable subset
anonymate-gui                               # desktop window
```

Command-line help and reports are bilingual (Dutch first). License: EUPL-1.2, © 2026 Henri ter
Hofte. Developed with [Claude Code](https://claude.com/claude-code) as AI coding assistant.

**Code signing policy** (applied for; the Windows program is not signed yet). Free code signing
provided by [SignPath.io](https://about.signpath.io), certificate by
[SignPath Foundation](https://signpath.org), once approved. Only builds made by GitHub Actions
from this repository are signed, each release after manual approval. Committers, reviewers and
approvers: [Henri ter Hofte](https://github.com/henriterhofte). Privacy: this program will not
transfer any information to other networked systems unless specifically requested by the user
or the person installing or operating it.
