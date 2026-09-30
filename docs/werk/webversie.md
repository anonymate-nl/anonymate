# Webversie: technisch ontwerp (kladbloknotitie 12)

Stand: de webversie draait op <https://anonymate.nl/app/>, de landingspagina linkt ernaar als
eerste knop. Alle zeven stappen van de Windows-app zitten erin, met dezelfde uitkomsten en teksten
(in de oefenmodus tegen het verzonnen Nederland; de stap Signatuur is daar uitgeschakeld, zoals in
de Windows-app). Het rekenwerk dat eerst in de GUI zat, staat in de Qt-vrije kern (`kaart.py`,
`stappen.py`, `voortgang.py`); de Windows-app gebruikt dezelfde functies. Nog open (fase 3 en 4, en
het Windows-programma): zie kladbloknotitie 12.

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
| populatie | verzonnen Nederland (200.000 woningen), in de browser gemaakt | datapakket (notitie 13), van dezelfde herkomst als de app |
| EP-online | niet nodig | het totaalbestand van de gebruiker, gesleept (route 4 van notitie 13) |

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

- **Content-Security-Policy** in de pagina: `connect-src 'self'`, `script-src 'self' 'wasm-unsafe-eval'`,
  `worker-src 'self' blob:`, geen formulieren (`form-action 'none'`), geen enkele externe host
  (sinds fase 2 staat Pyodide zelf bij de pagina). `wasm-unsafe-eval` alleen voor WebAssembly.
  De app toont de policy leesbaar onder "Wat deze pagina mag". In de console staat een bekende,
  onschuldige melding over `data:text/javascript,`: `pyodide.js` probeert dat te laden om te
  zien of het in een classic worker draait; de policy weigert het (`data:` staat bewust niet in
  `script-src`) en dat is het verwachte antwoord.
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

1. **Pyodide zelf hosten** (gedaan, fase 2): alleen de benodigde bestanden uit de vastgezette
   Pyodide-release, in hetzelfde Pages-artefact als de app (`/app/pyodide/`). Dan is
   `connect-src 'self'` genoeg. Zo controleer je het:
   - De versie staat op één plek: `PYODIDE_VERSION` in `web/maak.py` (nu 314.0.7), ook te zien
     in `wheel.json`, `manifest.json` en in de pagina ("Pyodide 314.0.7").
   - Elk pakket (numpy, pandas, duckdb, h3 en wat ze nodig hebben: python-dateutil, six, pytz) moet
     kloppen met de `sha256` in `pyodide-lock.json`; anders faalt de build. Niet meegeleverd:
     pyarrow, micropip, tzdata.
   - De runtimebestanden (`pyodide.js`, `pyodide.asm.mjs`, `pyodide.asm.wasm`, `python_stdlib.zip`,
     `pyodide-lock.json`) hebben in de lock geen hash: hun SHA-256 staat vastgelegd in
     `web/pyodide-sha256.json` (gemaakt met `python web/maak.py --pyodide-hashes` uit de
     vastgepinde release; een afwijking laat de build falen).
   - `manifest.json` in `dist/` (dus ook op https://anonymate.nl/app/manifest.json) somt elk
     bestand op met grootte en sha256, plus de versies van Pyodide en AnonyMate en het bouw-id;
     narekenen kan met `sha256sum`. Fase 6 bouwt hier de controlepagina en attestaties op.
   - De build downloadt van jsDelivr (alleen bij het bouwen) naar `web/.pyodide-cache/<versie>/`
     (genegeerd door git); in `pages.yml` zit daar een `actions/cache` op.
   - Omvang: ongeveer 36 MB in `dist/` (waarvan 30 MB Pyodide, de pakketten en 4 MB oefenpopulatie);
     op GitHub Pages (limiet 1 GB) is dat te verwaarlozen.
2. **Reproduceerbare wheel**: `SOURCE_DATE_EPOCH` uit de commit, zodat twee builds bit voor bit
   gelijk zijn. De web-bundel bestaat verder alleen uit statische bestanden.
3. **Subresource Integrity** op `app.js` en `worker.js`; de hashes en die van de wheel in een
   `manifest.json` bij de release, met een attestatie (`actions/attest-build-provenance`).
4. Een pagina "Zo controleer je dit zelf": broncode, build, hashes, en hoe je in de
   ontwikkelhulpmiddelen van de browser ziet dat er niets wordt verstuurd.

## Fasen

| fase | wat | klaar als |
|---|---|---|
| 1. prototype (klaar) | oefenmodus en eigen CSV tegen het verzonnen Nederland: kolommen, norm, aanvaller, uitkomst, bits, generalisaties, zip downloaden | draait lokaal in Edge en Chrome; zelfde uitkomst als `anonymate assess --synthetic` |
| 2. eigen hosting (klaar) | Pyodide-subset en wheel in één Pages-artefact onder `/app/`; CSP zonder CDN | werkt offline na de eerste keer (service worker) |
| 3. echte populatie | datapakket in OPFS, `WORKERFS`, DuckDB op Parquet | toets van het voorbeeldbestand tegen heel Nederland binnen een minuut |
| 4. EP-online | totaalbestand slepen, labels lokaal koppelen | labelmethoden van de signatuur in de browser |
| 5. weer en kaart (klaar) | stap Weerlocatie met kaart (canvas), weerspoor | gelijk aan de Windows-versie |
| 6. verifieerbaar (klaar) | reproduceerbare build, manifest met commit, attestaties, controlepagina | iemand anders kan de hashes narekenen (SRI is niet gedaan: zie onder) |

### Fase 6: hoe je de webversie controleert

Gebouwd (branch `web-fase6`): drie lagen, elk met een eigen bewijs.

1. **Reproduceerbare build.** Twee builds van dezelfde commit geven byte-identieke bestanden in
   `web/dist/`, dus ook een identiek `manifest.json`. Wat daarvoor is vastgezet: `SOURCE_DATE_EPOCH`
   uit de commit; de wheel wordt gebouwd uit een schone kopie van `git ls-files` (`src/`,
   `pyproject.toml`, `README.md`, `LICENSE`) met LF in tekstbestanden, in een tijdelijke map (geen
   oude `build/`, geen paden); `web/bouw-constraints.txt` pint `setuptools`, `wheel` en de
   pakketten die de oefenpopulatie schrijven (`duckdb`, `numpy`, `pandas`, `pyarrow`, `h3`; DuckDB
   zet zijn versie in het Parquet-bestand). `maak.py` geeft dat bestand als `PIP_CONSTRAINT` aan pip,
   ook voor de geisoleerde build. Alle tekstbestanden (`index.html`, `app.js`, `worker.js`, `sw.js`,
   `wheel.json`, `manifest.json`) gaan met LF naar `dist`, dus een Windows-checkout met CRLF geeft
   dezelfde bytes. Besluit: de **referentiebuild is die van GitHub Actions** (Linux, Python 3.13,
   de pins). Andere machines geven dezelfde bytes zolang Python 3.13 en de pins gelijk zijn; wat
   daarvan afhangt (Python-versie, pakketversies) staat hier, niet stil in de build.
   De wheel wordt na het bouwen herschreven met vaste zip-metadata (volgorde, tijdstempel uit de
   commit, rechten, LF in de dist-info, RECORD opnieuw berekend). Gemeten (30-09-2026): een build op
   Windows 11 (Python 3.13.12, dezelfde pins) is byte-identiek aan die van GitHub Actions (Linux).
   `manifest.json` bevat `bron: {repo, commit}` (volledige sha). De app toont "versie ... · commit
   ..." met een link naar `controleer.html`. CI: job `herbouw` in `tests.yml` bouwt in twee losse
   klonen en `diff -r`t alles, en bewaart `manifest.json` als artefact `manifest-linux`.
2. **Herkomst.** `pages.yml` roept `actions/attest-build-provenance@v4` aan over
   `manifest.json`, de pagina, de scripts en de wheel (`id-token: write`, `attestations: write`).
   Controle: `curl -O https://anonymate.nl/app/manifest.json` en
   `gh attestation verify manifest.json --repo anonymate-nl/anonymate`.
   `controle.yml` draait wekelijks (en handmatig): haalt het live manifest, checkt `bron.commit` uit,
   bouwt opnieuw en vergelijkt met de live site (`web/controleer.py`); het leest alleen.
3. **Narekenen.** `python web/controleer.py [--url ...]` leest `bron.commit` uit het live manifest
   (staat HEAD er niet op: `git checkout <commit>`), bouwt `web/dist` opnieuw, vergelijkt bestand
   voor bestand en `manifest.json` byte voor byte, en downloadt elk live bestand om de sha256 tegen
   het live manifest te houden. Uitkomst: `gelijk: wat op https://anonymate.nl/app/ draait, is
   gebouwd uit commit <sha>`, of de lijst afwijkende bestanden (exitcode 1).

De leesbare uitleg voor niet-ontwikkelaars is `website/controleer.html` (https://anonymate.nl/controleer.html):
wat wordt beloofd, netwerkverkeer bekijken (F12), de CSP, de build narekenen, de attestatie, de
vastgepinde Pyodide met de hashes uit `pyodide-sha256.json`, en wat niet gedekt is (browser, OS,
GitHub Pages als host, nog geen codeondertekening van het Windows-programma).

Bewust niet gedaan: Subresource Integrity op `app.js`/`worker.js` (stap 3 hierboven). `index.html`
en `manifest.json` komen van dezelfde herkomst; SRI voegt daar niets aan toe, en de worker wordt
niet via een `<script integrity>` geladen. Het manifest met de sha256 per bestand en de
service worker (die elk gecachet bestand tegen zijn hash controleert) dekken dat al.

Offline (fase 2): `web/sw.js` is een service worker (scope `/app/`) die na het opstarten alles in
de lijst cachet (pagina, worker, wheel, oefenpopulatie, manifest, `pyodide/`), elk bestand
gecontroleerd tegen zijn sha256, in een cache met het bouw-id in de naam. `maak.py` schrijft de
lijst en het bouw-id in `sw.js`. Onder "Wat deze pagina mag" staat "Offline beschikbaar" zodra
alles geladen en gecachet is; een nieuwe versie meldt zich met "Er is een nieuwe versie: herlaad de
pagina" en neemt niets over midden in een beoordeling. Waar service workers ontbreken werkt de
pagina gewoon, alleen niet offline.

Excel-bestanden: openpyxl als wheel meeleveren (nog te doen); in het prototype alleen CSV.

## Prototype (fase 1)

- `src/anonymate/web.py`: de facade.
- `web/`: `index.html`, `app.js`, `worker.js`; `web/maak.py` zet ze met de wheel in `web/dist/`.
- Lokaal draaien: `python web/maak.py` en dan `python -m http.server -d web/dist 8000`, en
  `http://localhost:8000` openen. Niet op anonymate.nl.

## Pariteit met de Windows-app (ontwerp, 30-09-2026)

Doel: alles wat het Windows-programma kan, ook in de browser, met dezelfde teksten, dezelfde
uitkomsten en dezelfde tekeningen. De oefenmodus heeft alle gegevens al in de wheel
(`data/voorbeeld/`, `data/kaart/`); de echte populatie volgt in fase 3.

### Uitgangspunt: rekenen uit de GUI halen, niet dupliceren

De GUI doet nog een deel van het rekenwerk zelf (en `gui_kaart.py` importeert Qt bovenaan, dus
Pyodide kan hem niet laden). Dat deel gaat naar twee Qt-vrije kernmodules die de Windows-app én
`anonymate.web` gebruiken:

| nieuwe module | wat erin komt (nu in) |
|---|---|
| `anonymate/kaart.py` | `available`, `MapData` (met `cell_stats`, `counts`, `station_at`, `station_name`), `voronoi`, `noisy_cells`, de constanten `N_MC`, `HEAT_SHARE`, `NL_BOX` (nu `gui_kaart.py`); `land_share` zonder `QPainterPath`: een even-oneven-test met numpy op de landringen; het inlezen van de kaartlagen (`_map_layer`, gui.py) en de grootste gemeenten met hun middelpunt (`_cities`) |
| `anonymate/stappen.py` | koppelkolommen en GPS-kolommen raden (`_link_columns`, `GPS_LAT/LON`); locaties per woning (`_locations`); weerlocatie toevoegen (H3 na ruis / KNMI-station, uit `apply_weather`), met de tolerantieregel; UHI inlezen, in klassen, aan de populatie koppelen (`_read_uhi`, `_with_uhi`, het `Bin`-stuk); het weerspoor terugzetten in de dataset (`_show_trace`); afbakening samenvoegen (`_region_scope` + `_scope`); de teksten bij een cel (oordeel "ruim genoeg / genoeg / te weinig") en bij een woning (`_show_record`); `houses_for` en de klassen van het k-histogram (nu `gui_tekening.py`, zonder Qt); de representativiteitsregels voor de Toelichting; `_readable` voor foutmeldingen |

`gui.py`, `gui_kaart.py` en `gui_tekening.py` importeren daarna uit deze modules; hun gedrag
verandert niet. `tests/test_web.py` bewaakt dat ook deze twee modules geen netwerk en geen Qt
importeren.

### De facade (`anonymate/web.py`)

Eén functie per handeling in de app, dicts erin en eruit:

- `open_practice`, `open_file`: ook `derive_h3_columns`, de voorgestelde mapping per kolom (zoals
  de Windows-app voorselecteert) en de voorgestelde koppel- en GPS-kolommen.
- `norm(p)`: k, de huisjes en de uitleg; `lock_norm()`.
- `run(mapping, scenario, regio, afbakening)`: `mapping` is voortaan volledig (zoals de
  Windows-app, `auto=False`); regio en afbakening blijven in de sessie, ook voor `apply` en
  `export`. Het antwoord krijgt `delta` en `redenen` per woning, de klassen van het k-histogram,
  de Toelichting (tekst en representativiteit) en de waarschuwingen.
- `record(i)`: de kaart per woning (huisjes, titel, tekst).
- `suggest` eindigt, zoals in de Windows-app, met een toets van de laatste stap; `apply(i)` neemt
  stap i over zonder de lijst in te korten.
- Kaart: `map_layers()` (land, grenzen, steden, stations, Voronoi, cellen van niveau 6 met
  woningen: alles als lon/lat-ringen, één keer), `map_cells(level)` (cellen met woningen uit de
  dataset), `map_cell(cell, sigma)` (de celstatistiek, de buren, het oranje gebied als ringen, en
  de teksten), `map_station(lat, lon)`.
- `weather(bron, methode, niveau, sigma, meetellen)`: voegt `weerzone_h3` of `weer_knmi_station`
  toe; `uhi(bestand, klasbreedte)`; `trace(bestand, opties)` en `trace_apply()` voor "Weer al in
  de data?". Bestanden komen, zoals nu, via het geheugenbestandssysteem van de worker; een zip mag
  (een map kiezen kan een browser niet).
- `signature(...)` en `explore(...)`: de stap staat erin, maar is net als in de Windows-app
  uitgeschakeld in de oefenmodus ("Niet in de oefenmodus: het verzonnen Nederland heeft geen
  signaturen"). Werkend pas met de echte populatie (fase 3).

H3-grenzen rekent Python uit (`h3.cell_to_boundary`); de browser tekent alleen. Zo is er geen
tweede H3-bibliotheek in JavaScript nodig.

### De schil (`web/`)

- Zeven stappen in de rail, met dezelfde namen, ondertitels en vinkjes als de Windows-app; de
  oefenmodusbalk met "Stoppen".
- Norm: schuif en getal (P_MIN..P_MAX), de vijf ijkpunten, "k ≥ N" groot, de huisjes, "Norm
  vastleggen" (daarna pas toetsen).
- Tekeningen in SVG, naar het voorbeeld van `gui_tekening.py`: huisjes, bitsbalk met labels en
  normstreep, k-histogram, afwegingsgrafiek (informatieverlies tegen publiceerbaar, met de 95%-lijn).
- De kaart in een `<canvas>`: water, land, grenzen, basiscellen, stationsvlakken of H3-cellen,
  de aangeklikte cel met buren en het oranje gebied, stadsnamen en een legenda; zoomen met het
  wiel, slepen, dubbelklik terug, klikken selecteert. Zelfde kleuren als de Windows-app.
- Uitkomst: vier tegels zoals de Windows-app, tabbladen Woningen (met de kaart per woning),
  Afweging en Toelichting; voortgang met verstreken en resterende tijd.

### Volgorde van bouwen

1. Opstarten versnellen (zie "Opstarten" hieronder en kladbloknotitie 14), omdat elke volgende test er baat bij heeft.
2. De kernmodules `kaart.py` en `stappen.py`, met de Windows-app erop overgezet en de tests groen.
3. ~~Facade en schil voor stap 1, 2, 3, 6 en 7 (zonder kaart).~~ Gedaan (30-09-2026): de rail met
   alle zeven stappen, stap 4 zichtbaar maar uitgeschakeld, stap 5 als "volgt" (Verder slaat hem
   over). Excel: openpyxl zit niet in Pyodide; de pagina zegt dat Excel volgt.
4. ~~Stap 5: weerlocatie, kaart, UHI en weerspoor.~~ Gedaan (30-09-2026): `map_layers`, `map_cells`,
   `map_hit`, `map_cell`, `map_station`, `weather`, `uhi`, `trace_open`, `trace`, `trace_apply` in
   `web.py`; de kaart in een canvas, de drie tabbladen en de zijkaart in `web/`. Nog niet gedaan:
   in een echte browser bekeken (canvas en JS zijn alleen syntactisch gecontroleerd); het
   weerspoor kent alleen csv en zip (parquet vraagt pyarrow) en werkt alleen in de oefenmodus
   (de KNMI-uren en de echte populatie volgen met fase 3); `investigate` meldt geen voortgang,
   de pagina toont alleen de verstreken tijd; KNMI-station als weerlocatie geeft in de oefenmodus
   dezelfde melding als de Windows-app (de oefenpopulatie heeft geen stations per woning).
5. ~~Stap 4 (signatuur) zichtbaar maar uitgeschakeld in de oefenmodus.~~ Gedaan, samen met 3.

Elke stap: tests groen, en in Chromium met de oefenmodus dezelfde uitkomst als de Windows-app.

## Opstarten

De pagina is na het opstarten bruikbaar; de oefenmodus start vanuit een vooraf gemaakte
populatie. Wat daarvoor is ingebouwd:

- **Geen pyarrow in de browser.** `anonymate/tabel.py` (`lees_parquet`, via DuckDB, zelfde dtypes
  als `pd.read_parquet`) wordt gebruikt door `voorbeeld.py`, `weerspoor.py` en `read_dataset`;
  `gui.py` en de code die het depot schrijft (`store`, `datapakket`, `rounding`, `signature`)
  gebruiken pyarrow wel. `tests/test_web.py` draait `open_practice`, `run` en `export` in een
  subproces waarin `pyarrow` en `h3` niet te importeren zijn, met dezelfde uitkomst.
- **De oefenpopulatie is vooraf gemaakt.** `voorbeeld.write_population` schrijft
  `web/dist/oefenpopulatie.parquet` (zstd, één thread, vaste seed, dus dezelfde bytes per build;
  4,1 MB); `web.open_practice(population_path)` leest hem met `Population.from_parquet`. h3 wordt
  bij het opstarten niet geladen, maar pas als een aanroep erom vraagt.
- **Lui importeren.** De hulpfuncties van de facade (`read_dataset`, `qids_from`, `parse_scope`,
  `SCENARIOS`) staan in `anonymate/invoer.py`; `import anonymate.web` haalt `cli`, `generalize`,
  `report` en `signature` niet meer binnen.
- **Parallel.** `loadPyodide({packages})`; wheel en oefenpopulatie worden opgehaald terwijl Python
  start; zonder micropip: `unpackArchive(wheel, "wheel", {extractDir: site-packages})`.
- **Pagina meteen bruikbaar.** Stap 1 staat er meteen, de voortgang is een smalle regel bovenaan;
  een klik of bestandskeuze vóór de rekenkern klaar is, komt in de rij ("wacht op de rekenkern…").
  De opstartbalk telt stappen en schat de resterende tijd met de tijden van het vorige bezoek.
  Daarna laden h3 en de modules voor de latere stappen op de achtergrond; "Alles is geladen"
  verschijnt pas als dat klaar is.
- **Zelf hosten met een service worker** (fase 2): offline na het eerste bezoek. Opnieuw laden uit
  de cache is niet sneller: de tijd zit in het laden en importeren van de wasm-bibliotheken, niet
  in het ophalen.
- Het weerspoor gebruikt alleen Europe/Amsterdam, die de wheel zelf meelevert (1,1 kB) in plaats
  van het pakket tzdata.

De worker zet de tijden per fase in de console ("opstarten (s)": `python_pakketten`, `wheel`,
`import`, `oefenpopulatie`, `wheel_ophalen`, `populatie_ophalen`). Gemeten in Chromium: koud
opstarten 17-22 s (`python_pakketten` 12-14 s, `import` 5-7 s), de oefenmodus daarna 1-2 s.
`unpackArchive` en DuckDB's `read_parquet` op het Emscripten-bestandssysteem werken in de browser
zoals in CPython.
