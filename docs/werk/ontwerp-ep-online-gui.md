# Ontwerp: populatie opbouwen met EP-online, begeleid in de GUI

Uitwerking van [kladbloknotitie 15](KLADBLOK.md#kladbloknotitie-15-ep-online-sleutel-en--download-begeleiden-in-de-gui-todo).
Route B wordt gebouwd; route A en C krijgen alleen de haakjes waaraan ze later vastzitten.

## Uitgangspunten

- **Rekenen buiten de GUI.** Alle logica (welke stappen nodig zijn, sleutelcontrole, uitvoeren,
  tijdschatting, teksten) komt in een nieuwe Qt-vrije module `anonymate/opbouw.py`, zodat CLI en
  later de webversie dezelfde code en teksten gebruiken (zoals `stappen.py`). `gui.py` krijgt alleen
  een dialoogvenster dat die module aanstuurt.
- **De routekeuze op één plek**: `opbouw.plan(...)`. Nergens anders in de GUI een `if ep_online`.
- **De sleutel verlaat de computer alleen richting EP-online.** Hij staat niet in voortgangstekst,
  foutmeldingen, logs, het manifest of `QSettings`. Bewaren alleen op uitdrukkelijk verzoek, in
  `<opslag>/.env` als `EPONLINE_API_KEY=` (de regel die `ingest_eponline` al leest).
- **Hervatbaar en annuleerbaar.** Elke stap slaat over wat al klaar is; downloads hervatten via
  `.part`; annuleren laat een consistente toestand achter.

## Wat bestaat en wat erbij komt

| Bestaat | Gebruik |
|---|---|
| `store.download_datapakket()` | stap 1: zip + manifest, sha256-controle |
| `store.ingest_eponline(store, file, api_key=…)` | stap 2 + 3: DownloadInfo, download, inlezen naar `raw/ep_online.parquet` |
| `datapakket.install(package, store)` | stap 4: populatie + alle signaturen, koppelt `raw/ep_online.parquet` op `vbo_id` |
| `voortgang.Voortgang`, `Schatter`, `VoortgangBalk`, `Worker` | voortgang en draad |

Kleine uitbreidingen aan bestaande functies, alle met een standaardwaarde zodat niets breekt:

1. `store.download(..., on_bytes=None)`: `on_bytes(done, total)` naast de tekst-callback, zodat de
   download een fractie kan melden. Doorgeven via `download_datapakket` en `ingest_eponline`.
2. `store.ingest_eponline(..., fraction=None)`: meldt `fraction(bytes_gelezen / file_size)` tijdens
   het inlezen (ongecomprimeerde grootte uit `ZipInfo.file_size`, gelezen bytes via een dunne
   telwrapper om de stroom). Splits het bestaande deel "DownloadInfo opvragen" af als
   `eponline_info(key, fetcher=fetch) -> dict` zodat de sleutelcontrole hetzelfde verzoek doet.
3. `datapakket.install(..., fraction=None)`: meldt `n / manifest["woningen"]`.

`fraction` en `on_bytes` zijn gewone callables; `opbouw` vertaalt ze naar één `Voortgang`.

## Module `opbouw.py`

### Sleutel

```python
EP_AANVRAAG_URL = "https://apikey.ep-online.nl/"

@dataclass
class Sleutelcontrole:
    geldig: bool | None        # None: niet te bepalen (geen netwerk)
    melding: str               # gewone taal, zonder de sleutel
    bestand: str | None = None # naam van het totaalbestand, bij geldig

def controleer_sleutel(key: str, fetcher=fetch) -> Sleutelcontrole
```

Doet `eponline_info(key)`: HTTP 401/403 → `geldig=False` ("EP-online kent deze sleutel niet. Let op:
een nieuwe sleutel werkt pas ongeveer 5 minuten na het activeren."); `URLError`/time-out →
`geldig=None` ("EP-online is niet bereikbaar; controleer de internetverbinding"); JSON zonder
`downloadUrl` → `geldig=False` met korte uitleg. Spaties en regeleinden rond de geplakte sleutel
worden weggehaald.

```python
def bewaarde_sleutel(store) -> str | None        # omgevingsvariabele, dan <opslag>/.env
def bewaar_sleutel(store, key) -> Path           # schrijft/vervangt alleen de regel EPONLINE_API_KEY
def vergeet_sleutel(store) -> None               # haalt die regel weg
```

`bewaar_sleutel` laat andere regels in `.env` staan. Bewust **niet** `Path.cwd()/.env`: de GUI
schrijft alleen in de eigen opslag.

### Toestand en plan

```python
@dataclass
class Toestand:            # wat er lokaal al is; snel te bepalen, geen netwerk
    populatie: bool
    populatie_met_labels: bool     # manifest: sources.datapakket.ep_online == "eigen opslag", of build uit bronnen met ep-online
    pakket_zip: bool               # downloads/anonymate-datapakket.zip aanwezig (sha256 pas bij uitvoeren)
    ep_parquet: bool               # raw/ep_online.parquet aanwezig
    ep_versie: str | None

def toestand(store) -> Toestand
```

```python
class Bron(Enum):          # waar de EP-gegevens vandaan komen
    GEEN = "geen"          # doorgaan zonder EP-online
    SLEUTEL = "sleutel"    # route B: eigen sleutel, eigen download
    BESTAND = "bestand"    # route B: zelf gedownload zip-bestand
    PAKKET = "pakket"      # route A: al in het pakket (later)

@dataclass
class Stap:
    naam: str              # "EP-online downloaden"
    gewicht_s: float       # referentieduur in seconden, voor verdeling van de balk en de eerste schatting
    doe: Callable[[Voortgang], None]

def plan(store, toestand, bron, *, key=None, bestand=None, pakket_manifest=None) -> list[Stap]
```

`plan` is de enige plek waar de route wordt gekozen:

- `pakket_manifest` (het gepubliceerde `manifest.json`, klein, al opgehaald door de GUI vóór het
  dialoogvenster) bepaalt of route A beschikbaar is: `ep_route(manifest) -> Bron | None`. Vandaag
  geeft dat altijd `None` (het veld `"ep_online"` is een tekst). Afspraak voor later, nu alleen
  gelezen, nergens geschreven: `"ep_online": {"in_pakket": true, ...}` → `Bron.PAKKET`, of
  `"varianten": {"ep": {"naam": "...zip", "manifest": "...json", "toegang": "open" | "sleutel"}}`.
  `"toegang": "sleutel"` is route C; de stap daarvoor (`toegang_ophalen`) bestaat nog niet, dus
  `ep_route` geeft dan `None` en de gebruiker krijgt route B. Een onbekend formaat → `None`.
- Stappen (overgeslagen als de toestand zegt dat ze klaar zijn, behalve 4 die altijd draait):
  1. "Datapakket downloaden en controleren" — `download_datapakket` (alleen als er geen populatie
     is, of als de zip ontbreekt).
  2. "EP-online downloaden" — alleen bij `Bron.SLEUTEL` en als het bestand van de huidige
     DownloadInfo nog niet in `downloads/` staat.
  3. "EP-online inlezen" — bij `SLEUTEL` en `BESTAND`.
  4. "Populatie en signaturen uitrekenen" — `datapakket.install`.
  Bij `Bron.GEEN` met een bestaande populatie is het plan leeg (niets te doen).

Referentieduren (`REFERENTIE_S`, één dict bovenin), gemeten op 2026-10-03 met `anonymate ingest
pakket` op een schone store (laptop met 8 GB RAM, glasvezel thuis) en iets naar boven afgerond:
pakket downloaden 150 s (gemeten 49 en 141 s), EP downloaden 120 s (102 s), EP inlezen 150 s
(124 s), populatie en signaturen 1800 s (1727 s zonder labels; met labels 55 min, maar toen wisselde
de laptop uit door geheugengebrek). Eerst geschat: 600, 300, 900 en 2400 s. Downloads worden niet gemeten maar geschat; dat zegt de tekst.

### Uitvoeren, annuleren, tijd

```python
class Geannuleerd(Exception): ...

def voer_uit(stappen, progress, *, stop: threading.Event | None = None) -> None
```

- Eén `Voortgang(None, progress)`; elke stap krijgt `v.stage(lo, hi)` waarbij lo/hi het aandeel van
  `gewicht_s` in het totaal zijn. Tekst per stap: `"2 van 4: EP-online downloaden · 312 MB"`
  (de stap levert het tweede deel).
- De `progress` die de stappen zien is gewikkeld: bij elke melding wordt `stop` gecontroleerd en
  zo nodig `Geannuleerd` opgegooid. Zo stopt elke bestaande functie bij de volgende melding,
  zonder dat die functie van annuleren weet. Wat achterblijft: een `.part` (hervat later) of een
  `.parquet.part` (wordt later overschreven); `population.parquet` en `raw/ep_online.parquet`
  worden pas aan het eind vervangen, dus nooit half.
- Tijd: de GUI-balk krijgt fracties over het geheel; `Schatter` werkt daar ongewijzigd op. Nieuw in
  `voortgang.py` (Qt-vrij, geen wijziging aan `Schatter` zodat de webport gelijk blijft):

  ```python
  def klaar_rond(remaining_s: float | None, now: datetime) -> str   # "klaar rond 14:35", "" bij None
  def vooraf_schatting(stappen) -> str                             # "ongeveer 1 uur 10 minuten (schatting)"
  ```

  Zolang `Schatter` nog niets weet (< 5%), toont het venster de referentieschatting met "(schatting)".
- Vrije schijfruimte: `controleer_ruimte(store, pakket_manifest)` vóór de start, met
  `shutil.disk_usage` op `downloads` en `root`. Nodig: zip-bytes uit het manifest × 2 (zip + uitgepakt)
  + 2 GB voor EP-online en de populatie. Te weinig → melding vóór het starten, niet halverwege.

### Teksten

Alle zichtbare teksten als constanten in `opbouw.py` (`UITLEG_EP`, `STAPPEN_SLEUTEL`,
`ZONDER_EP_GEVOLG`, …), zodat de webversie ze later kan hergebruiken. Kern:

- Waarom: "Voor een echte toets heeft AnonyMate alle woningen in Nederland nodig. Het datapakket
  van anonymate.nl bevat BAG en 3D-BAG, maar geen energielabels: die mag AnonyMate niet
  doorgeven. Met een eigen, gratis sleutel haalt AnonyMate ze rechtstreeks bij EP-online (RVO)."
- Sleutel aanvragen (`STAPPEN_SLEUTEL`), naar wat apikey.ep-online.nl nu vraagt:
  1. Open het aanvraagformulier (knop).
  2. Vul de naam van je organisatie, het type organisatie en je e-mailadres in; het KvK-nummer is
     niet verplicht.
  3. Je krijgt een e-mail met een activeringslink; klik die binnen 24 uur aan.
  4. **De sleutel staat dan op het scherm en wordt niet gemaild: kopieer hem meteen.**
  5. Plak hem hieronder. Een nieuwe sleutel werkt na ongeveer 5 minuten.
  Onder de stappen: "Een sleutel die een jaar niet wordt gebruikt, vervalt." Geen belofte over
  wachttijd op de e-mail.
- Privacy: "De sleutel blijft op deze computer en gaat alleen naar EP-online. AnonyMate bewaart hem
  niet, tenzij je hieronder 'onthouden' aanvinkt; dan staat hij in <pad>/.env."
- Zonder EP-online: "De toets werkt ook zonder labels. Het woningtype komt dan uit de vorm van het
  pand (3D-BAG) in plaats van uit het label, en signaturen die labeldata gebruiken ontbreken. Een
  aanvaller met toegang tot EP-online weet meer dan deze populatie; de uitkomst is dan wat
  optimistisch." (Woordkeus nalopen tegen `docs/herleidbaarheid-uitleg.md`.)

## GUI

### Waar de gebruiker het ziet

- **Stap 6 (Aanvaller)** krijgt bovenaan een kaart "Populatie" met één regel toestand
  (`opbouw.toestand`): "Nog geen populatie op deze computer", of "6,2 miljoen woningen, datapakket van
  30-09-2026, met EP-online (publicatie …)" / "… zonder EP-online-labels", en een knop
  "Populatie opbouwen…" / "EP-online toevoegen…". Verborgen in de oefenmodus en als
  `population_factory` gezet is (tests).
- **Bij Toetsen zonder populatie**: `population()` gooit nu `FileNotFoundError`. In plaats van de
  foutmelding opent dan het dialoogvenster; na succes gaat het toetsen gewoon door, na annuleren
  niet.
- Niet in de oefenmodus, niet bij verkennen met een eigen populatie-factory.

### Dialoogvenster `PopulatieOpbouw(QDialog)`

Eén venster met een `QStackedWidget`, vier schermen, eigen `Worker`/`QThread`:

1. **Keuze.** De uitleg "waarom", dan drie keuzerondjes: *Met mijn EP-online-sleutel* (aanbevolen;
   voorgeselecteerd, en als er een bewaarde sleutel is staat dat erbij), *Ik heb het
   EP-online-bestand al* (bestandskeuze, `.zip`/`.csv`), *Zonder EP-online* (met `ZONDER_EP_GEVOLG`).
   Als `ep_route(manifest)` route A meldt, wordt dit scherm overgeslagen.
2. **Sleutel** (alleen bij de eerste keuze). `STAPPEN_SLEUTEL`, knop "Aanvraagformulier openen"
   (`QDesktopServices.openUrl`), een `QLineEdit` in `Password`-modus met oogje om te tonen, knop
   "Controleren" (in een `Worker`, met een kleine draaiende balk), uitslag in een regel eronder,
   vinkje "Onthouden op deze computer". Verder kan pas als de controle `geldig=True` gaf, of
   `None` (geen netwerk) na een expliciete waarschuwing. Bewaarde sleutel: veld vooraf gevuld
   (gemaskeerd) en direct gecontroleerd.
3. **Overzicht.** De stappen van `plan(...)` als lijst (overgeslagen stappen grijs met "al klaar"),
   `vooraf_schatting`, benodigde schijfruimte en waar het komt (`store.root`, `store.downloads`),
   en: "De computer kan ondertussen gewoon gebruikt worden; laat hem aan staan. Afbreken kan; de
   volgende keer gaat AnonyMate verder waar het bleef." Knop "Beginnen".
4. **Bezig.** Een `VoortgangBalk` (bestaande klasse, ongewijzigd) en een extra regel
   `klaar_rond(...)`, bijgewerkt door de tik van de balk. Knop "Afbreken" zet het `stop`-event en
   wordt "Bezig met afbreken…". Bij klaar: "Klaar: <toestandsregel>" en "Sluiten". Bij fout:
   `stappen.readable_error` plus "Opnieuw proberen" (hervat).

Sluiten tijdens "Bezig" vraagt eerst of het moet afbreken. De sleutel leeft alleen in het
dialoogvenster en in de closure van de stap; na afloop wordt het veld leeggemaakt.

Na succes: `MainWindow._population = None` (opnieuw laden) en de toestandsregel in stap 6
bijwerken.

## CLI

Geen nieuwe begeleiding, wel dezelfde code: `anonymate ingest pakket` gaat via `opbouw.plan` +
`voer_uit` met `Bron.SLEUTEL` als er een sleutel is, anders `Bron.GEEN` met een regel uitleg
(`UITLEG_EP` + `EP_AANVRAAG_URL`). Bestaand gedrag (`--file`) blijft.

## Webversie

Buiten deze stap. De teksten in `opbouw.py` zijn zo geschreven dat ze er later ook passen. Open:
of de EP-online-API CORS toestaat (één `fetch` uit de browserconsole naar `EPONLINE_URL`).

## Tests

Qt-vrij (`tests/test_opbouw.py`), met een nep-`fetcher` en nep-downloads:

- `controleer_sleutel`: geldig, 401, geen netwerk, rare JSON; de sleutel komt in geen enkele
  melding voor (ook niet als hij in de foutmelding van de server zou staan).
- `bewaar_sleutel`/`vergeet_sleutel`: andere `.env`-regels blijven staan; `bewaarde_sleutel` leest hem.
- `plan`: per toestand en `Bron` de juiste stappen; `ep_route` met het huidige manifest (`None`),
  met de twee toekomstige vormen, met route C (`None`) en met onzin (`None`).
- `voer_uit` met een kleine nagebootste EP-online-zip en een klein datapakket (er zijn fixtures in
  `tests/test_datapakket.py`): eind-toestand `populatie_met_labels`; annuleren halverwege laat de
  oude `population.parquet` intact en een tweede run maakt hem af; fracties stijgen monotoon en
  eindigen op 1.
- `klaar_rond`, `vooraf_schatting` met vaste tijden; Schatter met gesimuleerde snelheid over twee
  stappen met verschillend tempo.
- Geen sleutel in voortgangsteksten: verzamel alle teksten van een run en zoek de sleutel.

GUI (`tests/test_gui.py`, bestaande `app`-fixture): dialoog opent bij Toetsen zonder populatie;
keuze "Zonder EP-online" met een gemonkeypatchte `opbouw.voer_uit` sluit en toetsen gaat door;
sleutelscherm laat "Verder" pas toe na een geldige (nep)controle; de kaart in stap 6 is verborgen
in de oefenmodus.

## Bewust niet nu

- Route A en C uitvoeren (alleen herkennen; C valt terug op B).
- De referentietijden echt meten (aparte taak; de constanten staan op één plek).
- Een achtergronddienst die doorloopt als het venster dicht is.
