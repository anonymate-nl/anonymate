# Webversie: technisch ontwerp (kladbloknotitie 13)

Stand: 29-09-2026. Een ontwerp en een prototype, nog niet op anonymate.nl. De landingspagina
blijft wat hij is tot de webversie klaar is.

## Doel

AnonyMate in de browser, zonder installatie, met dezelfde rekenkern als het Windows-programma en
de opdrachtregel. De belofte is dezelfde als nu, maar dan aantoonbaar: **alles rekent op het eigen
apparaat, er wordt alleen gedownload, nooit geüpload.**

## Keuze: Pyodide, de Python-kern ongewijzigd

De rekenkern (`risk`, `detect`, `explain`, `generalize`, `report`, `constraints`, `qids`,
`population`, `representativiteit`, `synthetic`, `voorbeeld`) doet geen netwerk en leest alleen
tabellen. Alles wat hij nodig heeft, zit in Pyodide (gecontroleerd voor 314.0.7, met Python 3.14):

| pakket | lokaal | Pyodide 314.0.7 |
|---|---|---|
| pandas | 3.0.6 | 3.0.2 |
| numpy | 2.5.3 | 2.4.6 |
| duckdb | 1.5.5 | 1.5.1 |
| pyarrow | 25.0.1 | 22.0.0 |
| h3 | 4.5.0 | 4.4.2 |
| openpyxl | 3.1 | niet meegeleverd: pure Python, zelf meeleveren als wheel |

Een herschrijving in JavaScript of een tweede kern in Rust valt daarmee af: dat zijn twee
implementaties om gelijk te houden, en de tests dekken er maar één. Nu draait dezelfde code, met
dezelfde tests, in CPython en in de browser.

Nadelen, bewust aanvaard: een eerste download van rond 30 MB (Python, numpy, pandas, DuckDB,
pyarrow, gecomprimeerd), een paar seconden opstarten, en rekenen dat enkele keren trager is dan
native. Voor een toets die je één keer per dataset doet, is dat geen bezwaar.

## Opbouw

```
browser
├── index.html + app.js      de schil: stappen, tabellen, kaart; geen rekenwerk
│      │  postMessage (JSON; bestanden als ArrayBuffer)
│      ▼
└── worker.js                Web Worker: laadt Pyodide, roept anonymate.web aan
       └── Pyodide ── anonymate (wheel) ── pandas / DuckDB / h3
                        │
                        └── anonymate/web.py: de facade, JSON erin en eruit
```

- **Een Web Worker**, zodat de pagina niet bevriest terwijl er gerekend wordt.
- **`anonymate/web.py`** is de enige nieuwe Python: een dunne laag die JSON-achtige dicts
  aanneemt en teruggeeft, en verder de bestaande functies aanroept (`detect`, `qids_from`,
  `assess`, `information_bits`, `suggest`, `report.write`). Hij draait ook gewoon in CPython en
  wordt daar getest.
- **De schil** is gewone HTML en JavaScript, zonder framework en zonder bouwstap. Minder om te
  controleren, en niets dat van een npm-registry komt.

## Gegevens: wat komt waarvandaan

| gegevens | oefenmodus | echte toets |
|---|---|---|
| dataset van de gebruiker | voorbeeldbestand uit de wheel | gekozen of gesleept bestand, via `FileReader`, blijft in het geheugen van de worker |
| populatie | verzonnen Nederland (200.000 woningen), in de browser gemaakt | datapakket (notitie 14), van dezelfde herkomst als de app |
| EP-online | niet nodig | het totaalbestand van de gebruiker, gesleept (route 4 van notitie 14) |

**De populatie in de browser.** De echte populatie telt 8,4 miljoen woningen. Het datapakket
wordt naar schatting 300 à 400 MB, in stukken onder de 100 MB (de grens per bestand van GitHub
Pages). Het plan:

1. **Altijd het hele land ophalen**, alle stukken, ook bij een toets voor één gemeente: per regio
   ophalen vertelt de server welke regio iemand bekijkt.
2. **Bewaren in OPFS** (Origin Private File System), zodat het één keer per maand hoeft. De app
   toont versie, datum en SHA-256 van wat er ligt, en vergelijkt die met het manifest.
3. **Niet in het geheugen laden.** De worker koppelt de bestanden uit OPFS met Emscripten
   `WORKERFS` (alleen lezen, zonder kopie) en DuckDB leest ze als Parquet. Zo leest hij alleen de
   kolommen en rijgroepen die een toets nodig heeft. Een geheugengrens voor DuckDB (bijvoorbeeld
   1 GB) houdt het binnen wat wasm32 kan (4 GB adresruimte).
4. **EP-online erbij (route 4)**: het gesleepte totaalbestand ook via `WORKERFS`; DuckDB koppelt
   de labels op `vbo_id` en de labelmethoden van de signatuur rekenen lokaal. Open vraag: hoe lang
   dat in de browser duurt.

## Privacy, zichtbaar gemaakt

- **Content-Security-Policy** in de pagina: `connect-src 'self'` (en in het prototype nog de CDN
  van Pyodide), geen formulieren (`form-action 'none'`), geen externe scripts behalve Pyodide,
  `wasm-unsafe-eval` alleen voor WebAssembly. De app toont de policy leesbaar.
- **Geen fetch met gebruikersgegevens.** De worker krijgt het bestand als bytes; de facade doet
  geen netwerk. Een test bewaakt dat de kernmodules geen netwerkbibliotheek importeren
  (`tests/test_kern.py`).
- **"Je kunt nu de internetverbinding verbreken."** Zodra Pyodide, de wheel en eventueel het
  datapakket binnen zijn, zegt de app dat, en laat hij zien of hij offline is
  (`navigator.onLine` en de gebeurtenissen `online`/`offline`). De toets gaat offline gewoon door.
- **Uitkomsten downloaden, niet versturen.** `publiceerbaar.csv` en `rapport.md` gaan als zip naar
  de gebruiker via een Blob-link. `rapport_per_record.csv` (intern) zit er ook in, met dezelfde
  waarschuwing als nu.

## Verifieerbaar

1. **Pyodide zelf hosten** in de eindversie: alleen de benodigde bestanden uit de vastgezette
   Pyodide-release, met hun SHA-256 uit `pyodide-lock.json`, in hetzelfde Pages-artefact als de
   app. Dan is `connect-src 'self'` genoeg. Het prototype laadt Pyodide nog van jsDelivr,
   vastgezet op één versie.
2. **Reproduceerbare wheel**: `SOURCE_DATE_EPOCH` uit de commit, zodat twee builds bit voor bit
   gelijk zijn. De web-bundel bestaat verder alleen uit statische bestanden.
3. **Subresource Integrity** op `app.js` en `worker.js`; de hashes en die van de wheel in een
   `manifest.json` bij de release, met een attestatie (`actions/attest-build-provenance`).
4. Een pagina "Zo controleer je dit zelf": broncode, build, hashes, en hoe je in de
   ontwikkelhulpmiddelen van de browser ziet dat er niets wordt verstuurd.

## Fasen

| fase | wat | klaar als |
|---|---|---|
| 1. prototype | oefenmodus en eigen CSV tegen het verzonnen Nederland: kolommen, norm, aanvaller, uitkomst, bits, generalisaties, zip downloaden | draait lokaal in Edge en Chrome; zelfde uitkomst als `anonymate assess --synthetic` |
| 2. eigen hosting | Pyodide-subset en wheel in één Pages-artefact onder `/app/`; CSP zonder CDN | werkt offline na de eerste keer (service worker) |
| 3. echte populatie | datapakket in OPFS, `WORKERFS`, DuckDB op Parquet | toets van het voorbeeldbestand tegen heel Nederland binnen een minuut |
| 4. EP-online | totaalbestand slepen, labels lokaal koppelen | labelmethoden van de signatuur in de browser |
| 5. weer en kaart | stap Weerlocatie met kaart (canvas), weerspoor | gelijk aan de Windows-versie |
| 6. verifieerbaar | SRI, manifest, attestaties, controlepagina | iemand anders kan de hashes narekenen |

Excel-bestanden: openpyxl als wheel meeleveren (fase 2); in het prototype alleen CSV.

## Prototype (fase 1)

- `src/anonymate/web.py`: de facade.
- `web/`: `index.html`, `app.js`, `worker.js`; `web/maak.py` zet ze met de wheel in `web/dist/`.
- Lokaal draaien: `python web/maak.py` en dan `python -m http.server -d web/dist 8000`, en
  `http://localhost:8000` openen. Niet op anonymate.nl.
