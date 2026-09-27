# KLADBLOK (TODO) — anonymate <!-- omit from toc -->

Losse verbeterpunten, nog niet ingepland. Verplaats naar een issue of PR zodra opgepakt.

**Alleen wat nog moet gebeuren.** Bevindingen en verantwoording achteraf horen hier niet: die staan
in [`../`](..) en in de commitgeschiedenis. Staat er iets in dat alleen vertelt wat er gebeurd is,
dan kan het eruit.

## Inhoudsopgave <!-- omit from toc -->

**A. Warmteprestatiesignatuur**

- [Kladbloknotitie 1: Welke berekende signatuur is de beste? Toetsen tegen gemeten woningen](#kladbloknotitie-1-welke-berekende-signatuur-is-de-beste-toetsen-tegen-gemeten-woningen-todo)
- [Kladbloknotitie 2: Zonnetoetreding naar gevelrichting](#kladbloknotitie-2-zonnetoetreding-naar-gevelrichting-todo)
- [Kladbloknotitie 3: Infiltratie per bouwjaar in plaats van één landelijk getal](#kladbloknotitie-3-infiltratie-per-bouwjaar-in-plaats-van-één-landelijk-getal-todo)
- [Kladbloknotitie 4: Appartementen hebben geen signatuur](#kladbloknotitie-4-appartementen-hebben-geen-signatuur-todo)
- [Kladbloknotitie 10: Thermische massa uit het label of uit de BAG?](#kladbloknotitie-10-thermische-massa-uit-het-label-of-uit-de-bag-todo)
- [Kladbloknotitie 7: Hoort het stedelijk hitte-eiland bij de beste openbare signatuur?](#kladbloknotitie-7-hoort-het-stedelijk-hitte-eiland-bij-de-beste-openbare-signatuur-todo)

**B. Herleidbaarheid**

- [Kladbloknotitie 5: Gevoelige kenmerken (l-diversiteit)](#kladbloknotitie-5-gevoelige-kenmerken-l-diversiteit-todo)
- [Kladbloknotitie 9: Woningtype voor alle woningen, niet alleen die met een label](#kladbloknotitie-9-woningtype-voor-alle-woningen-niet-alleen-die-met-een-label-todo)
- [Kladbloknotitie 8: Representativiteit: welke vertekening geeft het weglaten van woningen?](#kladbloknotitie-8-representativiteit-welke-vertekening-geeft-het-weglaten-van-woningen-todo)
- [Kladbloknotitie 12: Welke KNMI-stations, welk jaar, welke grootheden?](#kladbloknotitie-12-welke-knmi-stations-welk-jaar-welke-grootheden-todo)

**C. Verspreiding**

- [Kladbloknotitie 6: Het Windows-programma via GitHub Releases](#kladbloknotitie-6-het-windows-programma-via-github-releases-todo)
- [Kladbloknotitie 11: Een webversie (WebAssembly): local first en verifieerbaar](#kladbloknotitie-11-een-webversie-webassembly-local-first-en-verifieerbaar-todo)

---

## Kladbloknotitie 1: Welke berekende signatuur is de beste? Toetsen tegen gemeten woningen (TODO)

Opgekomen 24-09-2026, na het toevoegen van de methode `best` aan
[`signature.py`](../../src/anonymate/signature.py).

### De vraag

anonymate berekent drie signaturen uit openbare gegevens: `nta8800` (bouwstaat, forfaitair),
`mwa` (idem met Maatwerkadvies-correcties) en `best` (huidige staat, gekalibreerd op het eigen
label). Dat `best` beter *zou* moeten zijn, is een redenering, geen meting. Of hij het ook is, en
hoeveel beter, is te toetsen met een monitoringdataset van eengezinswoningen waarin per woning de
**binnentemperatuur** en de **meterstanden** (gas, stroom) gemeten zijn, samen met het weer.

### Hoe

Per woning en per signatuurvariant een open, fysisch woningmodel draaien (een eenvoudig 1R1C- of
2R2C-model volstaat; de signatuur *is* de parameterset van zo'n model) en vergelijken met de meting:

1. **Temperatuur simuleren**: gegeven de gemeten warmtetoevoer (uit gasverbruik en
   ketelrendement, of warmtepompvermogen), het weer en een schatting van de interne warmte:
   simuleer de binnentemperatuur en vergelijk met de gemeten binnentemperatuur (RMSE, bias).
2. **Warmtevraag simuleren**: gegeven de gemeten binnentemperatuur en het weer: simuleer de
   benodigde warmte en vergelijk met het gemeten verbruik per dag en per stookseizoen.
3. **Dezelfde maat voor een geleerde signatuur** (uit de meetdata zelf geschat): die geldt als
   bovengrens van wat met dit modeltype haalbaar is.

Toets daarbij ook varianten mét een lokale correctie op de buitentemperatuur voor het stedelijk
hitte-eiland (0, 50 en 100% van de openbare kaartwaarde); zie
[notitie 7](#kladbloknotitie-7-hoort-het-stedelijk-hitte-eiland-bij-de-beste-openbare-signatuur-todo).

Uitkomst: per variant de verdeling van de simulatiefout over de woningen. De volgorde
`nta8800 → mwa → best → geleerd` zou een dalende fout moeten laten zien; als dat niet zo is, weten
we welke aanname in `best` (kalibratie op het label, correctie voor compactheid, MWA-correcties)
het niet waarmaakt.

### Wat dit wel en niet beslist

- **Inhoud, vóór publicatie**: welk algoritme de eerlijke baseline is waartegen een datagedreven
  signatuur zich moet meten. Een flauwe (slechte) baseline maakt elke vergelijking te gunstig.
  Ook de foutmarge die bij `anonymate signatuur adres` vermeld kan worden, komt hieruit.
- **Niet de herleidbaarheid van een gepubliceerde baseline.** Het algoritme is deterministisch en
  openbaar, dus de echte woning zit altijd in het vakje met de gepubliceerde waarde; hoe dicht de
  baseline bij de werkelijkheid ligt, verandert daar niets aan. Voor privacy telt de keuze van het
  algoritme alleen via hoe fijnmazig de uitkomst is (hoeveel invoer, dus hoe kleine vakjes); dat
  meet `anonymate afronding`.
- **Wel de tolerantie** als alléén een geleerde signatuur gepubliceerd wordt, zonder baseline (zie
  [`../warmtesignatuur.md`](../warmtesignatuur.md)).

### Een eerste stap zonder simulatie

Vóór een simulatie is de afstand tussen de signatuurvectoren al informatief: per component
|ln(berekend / geleerd)| over H, C en A_sol (τ volgt uit C/H), en de RMS daarvan per woning, voor
alle varianten op dezelfde woningen. Rapporteer daarnaast de afstand na één kalibratiefactor per
component (systematisch tegenover willekeurig) en de rangcorrelatie. Vergelijk pas nadat de
definities gelijk zijn getrokken: een geleerde A_sol is een effectieve zonne-apertuur (met
g-waarde, beschaduwing, absorptie), een berekende vaak een glasoppervlak; een geleerde H kan met of
zonder ventilatie en infiltratie zijn. De simulatie hieronder is daarna nodig om te bepalen hoe
zwaar een fout in H, C en A_sol weegt.

### Voorwaarden en valkuilen

- **Privacy van de toets zelf**: de fouten per woning zijn gekoppeld aan woningen met een bekend
  adres (anders kun je de signatuur niet berekenen). Resultaten alleen geaggregeerd publiceren; de
  koppeling blijft bij de datahouder, onder diens voorwaarden.
- **Interne warmte en ventilatie** zijn geen onderdeel van de signatuur maar bepalen de fout wel
  mee. Gebruik voor alle varianten dezelfde aannames, anders meet je de aannames en niet de
  signatuur.
- **Kleine aantallen**: met enkele tientallen woningen is een verschil tussen varianten alleen
  zinvol als het per woning consistent is (gepaarde vergelijking), niet alleen gemiddeld.
- **Waar de code landt**: het simuleren en vergelijken is algemeen en kan hier (als
  `anonymate.benchmark` of apart); de meetdata en de uitkomsten per woning horen bij de
  datahouder.

### Volgorde

1. Een open woningmodel kiezen met dezelfde parameters als de signatuur (H, C, A_sol, A_inf) en
   het weer als invoer; bij voorkeur een bestaand, getest model hergebruiken.
2. Een vergelijkingsharnas: per woning en variant simuleren, fout berekenen, verdelingen
   rapporteren. Testen op synthetische woningen met bekende signatuur.
3. Draaien bij de datahouder; alleen de geaggregeerde uitkomst terug.
4. De standaardmethode en de foutmarge vastleggen in `signature.py` en
   `warmtesignatuur.md`.

---

## Kladbloknotitie 2: Zonnetoetreding naar gevelrichting (TODO)

De zonnetoetreding middelt nu over alle gevelrichtingen, net als de RVO-voorbeeldwoningen. De
3D-BAG-plattegronden (op de NAS/downloadmap bewaard) geven de hoofdas van elk pand: voor
rijwoningen liggen de ramen vrijwel altijd in de lange gevels. Met de instraling per richting uit
NTA 8800 wordt A_sol per woning scherper. Let op: een scherpere berekening is ook een scherpere
rainbow table (zie notitie 1, tweede opbrengst).

## Kladbloknotitie 3: Infiltratie per bouwjaar in plaats van één landelijk getal (TODO)

A_inf is nu een landelijk gemiddelde (108 cm², met MWA 54) en zegt dus niets over een woning. NTA
8800 geeft forfaitaire qv10-waarden per bouwperiode; de RVO-voorbeeldwoningen noemen ze per
variant. Drie dingen om goed te doen:

1. **Referentieoppervlak**: qv10 is genormeerd op de **gebruiksoppervlakte** (NTA 8800 §11.2.5,
   vgl. 11.85, OPMERKING 2; ook NEN 2686), niet op het schiloppervlak. Wie het schiloppervlak neemt,
   zit bij eengezinswoningen een factor compactheid (~2) te hoog.
2. **Van lekdebiet naar infiltratie**: qv10 · A_g is het lekdebiet bij 10 Pa; via de stroomwet
   (n ≈ 0,67) terug naar een effectief lekoppervlak bij 4 Pa, en met het Sherman-Grimsrud/LBL-model
   (ASHRAE, stack- en windcoëfficiënt per aantal bouwlagen) naar een debiet. Een leermodel met een
   lineaire wind-apertuur (debiet = wind · A_inf) vraagt daarna een linearisatie bij typische
   wind en temperatuur in het stookseizoen; leg vast welke.
3. **Maatwerkadvies**: × 0,5 op het NTA-infiltratievoud (Van den Brom et al., 2022, p. 26-27).

Pas relevant voor de vergelijking met een geleerde signatuur die A_inf zelf leert; waar een
leermodel A_inf vastzet op een landelijk gemiddelde, zit infiltratie aan beide kanten buiten H.

## Kladbloknotitie 4: Appartementen hebben geen signatuur (TODO)

3D-BAG geeft de schil per pand, niet per woning. Voor appartementen zou de ligging in het gebouw
(tussen, hoek, onder het dak, boven de kruipruimte) bepalend zijn; die is niet openbaar. De
RVO-voorbeeldwoningen kennen die varianten wel (galerij-, portiekflat, maisonnette). Een verdeling
van de pandschil over de woningen naar gebruiksoppervlakte, met de ligging als onbekende, is een
mogelijke route.

## Kladbloknotitie 10: Thermische massa uit het label of uit de BAG? (TODO)

`ep` (en dus `passend`) rekent C uit het gebruiksoppervlak van het energielabel, consequent met
een schil die ook uit het label komt. Maar labeloppervlak en BAG-oppervlak kunnen flink
verschillen (tientallen m², in beide richtingen). Wordt naast de signatuur ook een
oppervlakteklasse gepubliceerd (uit de BAG, of uit een eigen opgave die daarmee overeenkomt), dan
is C een **tweede, onafhankelijk oppervlakgetal**: een C die niet past bij de gepubliceerde klasse
wijst een woning met zo'n afwijking aan, en dat zijn er weinig. In een praktijktoets bleef een
woning daardoor te herleidbaar, ook met ruis op de locatie.

Varianten om te toetsen, naast elkaar (herkenbaarheid én afstand tot een geleerde signatuur):

1. **C uit het BAG-oppervlak** in `ep` en `passend`, de schil wel uit het label. C past dan bij de
   gepubliceerde oppervlakteklasse. De geleerde C hing in een eerste vergelijking toch al niet samen
   met de berekende, dus de eerlijkheid van de baseline lijdt er vermoedelijk weinig onder.
2. **C niet publiceren** (τ volgt dan niet uit C/H), of veel grover afronden.
3. **Zoals nu**, en woningen waar label- en BAG-oppervlak sterk verschillen niet publiceren (of
   grover); dat vraagt een drempel en is zelf weer een selectie.

Meet ook hoe vaak label- en BAG-oppervlak landelijk meer dan bijvoorbeeld 15% verschillen: dat
bepaalt hoeveel woningen dit raakt.

## Kladbloknotitie 7: Hoort het stedelijk hitte-eiland bij de beste openbare signatuur? (TODO)

Opgekomen 24-09-2026. Het uitgangspunt van de signatuur `best` is: *de beste signatuur die je
alleen uit een adres en openbare gegevens kunt halen*. Het stedelijk hitte-eiland hoort daar
mogelijk bij.

**Wat het is.** Geen eigenschap van het gebouw, maar van de plek: in de stad is het buiten warmer
dan op het KNMI-station waarvan het weer komt. Het Maatwerkadvies corrigeert daarom de
buitentemperatuur met een locatiespecifieke toeslag (0-2 °C, studiewaarde 1 °C; bron: de
validatierapportage MWA, RVO 2022), op basis van de RIVM-hitte-eilandkaart. Die kaart is openbaar
en per adres uit te lezen; gemiddeld over de adressen in een postcode geeft ze een kleine
opzoektabel.

**Waarom het ertoe doet.** Een woningmodel dat het weer van een KNMI-station gebruikt, ziet een
stadswoning als "beter geïsoleerd" dan hij is: de lagere warmtevraag komt deels door de warmere
omgeving. Een geleerde signatuur neemt dat effect vanzelf mee in H; een berekende niet. Zonder
correctie is de vergelijking dus niet eerlijk, en mét correctie zou `best` dichter bij de meting
moeten komen. Dat is te toetsen in notitie 1.

**Het voorbehoud.** De RIVM-waarden zijn zomergemiddelden. Voor het stookseizoen is de correctie
niet gevalideerd, en er is geen onderbouwde winterfactor. Vandaar de varianten 0, 50 en 100% in
notitie 1: de meting beslist, niet een aanname.

**Voor de herleidbaarheid.** Als de correctie alleen intern in de simulatie wordt gebruikt, lekt
er niets. Maar een geleerde H van een stadswoning bevat het hitte-eiland-effect al, en draagt dus
een beetje locatie-informatie mee. En als de hitte-eilandwaarde zelf gepubliceerd wordt, is dat
een locatie-QID (`uhi` in de catalogus). Beide zijn mee te nemen in de rainbow table zodra de
waarde per woning in de populatie zit.

**Wat er moet gebeuren.**

1. Een ingest voor de hitte-eilandwaarde per adres: uit de RIVM-kaart (raster, ~2 GB; vraagt een
   rasterbibliotheek) of uit een kant-en-klare tabel per postcode, met bronvermelding en peildatum.
2. `uhi` als kolom in de populatie en in de functionele signatuurtabel (als extra parameter
   ΔT_uhi [K] naast H, C, τ, A_sol, A_inf).
3. De varianten 0/50/100% meenemen in de toets van notitie 1.
4. Afhankelijk van de uitkomst: `best` met of zonder hitte-eilandcorrectie als standaard.

## Kladbloknotitie 5: Gevoelige kenmerken (l-diversiteit) (TODO)

k-map en δ-presence meten of een woning te vinden is, niet of alle woningen in een groep dezelfde
gevoelige waarde delen. Bij de per-record-toets zijn de groepen in de dataset meestal één record
groot, dus l-diversiteit binnen de dataset zegt weinig; eerst doordenken wat de juiste vorm is
(bijvoorbeeld: een gevoelig kenmerk dat binnen een populatieklasse vrijwel constant is).

## Kladbloknotitie 8: Representativiteit: welke vertekening geeft het weglaten van woningen? (TODO)

### De vraag

Na "eerst de norm, dan toetsen" blijven twee knoppen over: grover publiceren en woningen niet
publiceren. Het informatieverlies van grover publiceren meet anonymate al. Het verlies van
*weglaten* niet: dat telt nu alleen als "zoveel records minder". Maar weglaten is geen toeval. De
toets haalt juist de **staarten** weg: grote, oude, vrijstaande woningen, woningen in dunbevolkte
gebieden. Dat zijn vaak ook de woningen met de grootste warmtevraag. Een analyse op de
gepubliceerde rest kan daardoor systematisch afwijken, ook als het maar om een paar procent van
de records gaat.

### Hoe te meten (voorstel, van eenvoudig naar precies)

1. **Verschuiving per kenmerk.** Voor elk gepubliceerd kenmerk de afstand tussen de verdeling in
   de hele dataset en in het gepubliceerde deel: totale-variatieafstand (de helft van de som van
   de absolute verschillen in aandeel) voor categorieën, gestandaardiseerd verschil in gemiddelde
   (SMD, verschil gedeeld door de standaardafwijking) voor getallen. Eenvoudig en uitlegbaar;
   vuistregel uit de epidemiologie: |SMD| < 0,1 is verwaarloosbaar.
2. **Verschuiving op de uitkomst.** Hetzelfde voor de grootheden waar de dataset *voor* is (gas-
   en stroomverbruik, warmteprestatiesignatuur, rendement): verschuift het gemiddelde of de spreiding
   van de uitkomst door het weglaten?
3. **Ten opzichte van de doelpopulatie.** Een dataset is zelden representatief voor de hele
   woningvoorraad; dat hoeft ook niet. Vergelijk daarom de afstand dataset → woningvoorraad vóór en
   na weglaten (de populatie ligt toch al lokaal klaar): wordt de dataset door het weglaten
   minder of juist méér representatief? Het wegen van de verdelingen, zoals in surveyonderzoek,
   geeft ook een correctie die gebruikers kunnen toepassen.
4. **Op het analyseresultaat.** Het strengste: draai een referentieanalyse (bijvoorbeeld een
   regressie van verbruik op bouwjaar en oppervlakte) op de hele dataset en op het gepubliceerde
   deel, en rapporteer het verschil in uitkomst. Dat vraagt een analyse per dataset en is daarom
   eerder iets voor de bronhouder dan voor de tool.

### Wat de tool ermee zou doen

- In `rapport.md` bij "woningen niet publiceren" een tabel met de verschuiving per kenmerk (1 en 2).
- In `suggest` en `signatuur publiceer --verken` de verschuiving naast precisieverlies en aantal
  publiceerbare records, zodat grover publiceren en weglaten op dezelfde manier te vergelijken zijn.
- Weglaten en grover maken vergelijken voor dezelfde records: een staartklasse samenvoegen houdt
  de woning in de dataset (grover, maar zonder vertekening), weglaten niet.

Open punt: bij kleine datasets (honderden records) is de verschuiving door een handvol weglatingen
statistisch nauwelijks van toeval te onderscheiden. Rapporteer dus ook de onzekerheid, niet
alleen het getal.

## Kladbloknotitie 9: Woningtype voor alle woningen, niet alleen die met een label (TODO)

Het woningtype in de populatie komt uit EP-online en is daardoor alleen bekend voor woningen met
een geregistreerd label: 57% van de eengezinswoningen. Standaard tellen woningen zonder type niet
mee als mogelijke match, en dan valt k voor elke toets met woningtype fors te laag uit. Met
`--unknown-matches` tellen ze wel mee, maar dan ook voor het label, waar dat niet terecht is.

Een aanvaller kent het type van vrijwel elke woning (Street View, of afgeleid uit de BAG). De
populatie hoort het dus ook voor elke woning te hebben:

1. Uit 3D-BAG en BAG afleiden: pand met één woning en zonder gedeelde muur → vrijstaand; twee
   woningen in twee panden met één gedeelde muur → twee-onder-een-kap; in een rij → hoek of tussen
   naar het aantal gedeelde muren (`opp_scheidingsmuur` en de buren); meer woningen in één pand
   → appartement.
2. Toetsen tegen de woningen mét label: hoe vaak klopt het afgeleide type met EP-online?
3. `woningtype` = EP-online waar bekend, anders afgeleid; een aparte kolom `woningtype_bron`.
4. Per QID kunnen kiezen of onbekend meetelt (nu één schakelaar voor alles).

## Kladbloknotitie 6: Het Windows-programma via GitHub Releases (TODO)

De workflow staat klaar ([`../../.github/workflows/release.yml`](../../.github/workflows/release.yml)):
een versietag bouwt een zip met GUI en CLI. Wacht op de publieke repo. Daarna een keer handmatig
testen op een schone Windows-machine zonder Python.

## Kladbloknotitie 11: Een webversie (WebAssembly): local first en verifieerbaar (TODO)

Opgekomen 27-09-2026. Naast het Windows-programma een versie die in de browser draait (Python via
Pyodide/WebAssembly), zonder installatie. Juist dan moet overtuigend zijn wat nu al geldt: **alles
rekent op het eigen apparaat; er wordt alleen gedownload, nooit geüpload.** anonymate kan zo
geleidelijk een voorbeeld worden van hoe dat kan: niet alleen open broncode, maar ook een build die
iedereen kan nagaan.

### Uitgangspunten

- **Downloaden mag, uploaden nooit.** Publieke brondata (BAG, EP-online, KNMI, 3D-BAG) komt naar
  het apparaat; de dataset van de gebruiker en alles wat daaruit volgt verlaat het apparaat niet.
- **Een rekenkern zonder netwerk en zonder schijf.** Toetsen, afronden, bits, weerspoor: pure
  functies op tabellen, ongewijzigd in CPython, in tests en in Pyodide. Downloaden en inlezen zit
  in een aparte acquisitielaag; de schil (Windows of web) roept alleen de kern aan.
- **Geen sleutels in de browser.** Alles wat in de browser staat is leesbaar. Een bron die een
  sleutel vraagt (EP-online-API) komt via een vooraf gemaakt, openbaar artefact, niet live.
- **Ook het ophalen mag niets verraden.** Een populatie per regio in stukjes ophalen vertelt de
  server welke regio de gebruiker bekijkt. Dus hele landelijke bestanden, of grove stukken
  (provincie), zodat het verzoek zelf in een menigte opgaat.

### In het ontwerp laten zien

- Een vaste regel in de stappenrail: "Alles blijft op deze computer", met per stap wat er
  gedownload is (bron, grootte, datum) en dat er niets is verstuurd.
- Een stap na het downloaden: **"Je kunt nu de internetverbinding verbreken."** De rest werkt
  offline; wie helemaal zeker wil zijn, zet wifi uit en ziet dat de toets gewoon verder gaat. De
  app ziet zelf of hij offline is en bevestigt dat.
- In de webversie een strikte Content-Security-Policy (`connect-src` alleen naar de
  downloadbronnen, geen formulieren, geen externe scripts) en een service worker die de app
  offline laat draaien. De policy leesbaar tonen in de app.

### Verifieerbaar

1. **Reproduceerbare builds**: vastgezette afhankelijkheden (lockfile met hashes), vaste
   tijdstempels (`SOURCE_DATE_EPOCH`); twee keer bouwen geeft bit voor bit hetzelfde. Voor de
   web-bundel goed haalbaar; voor een PyInstaller-exe lastiger (documenteren wat afwijkt).
2. **Herkomst van de build**: attestaties uit GitHub Actions (`actions/attest-build-provenance`,
   SLSA), SHA-256-controlegetallen bij elke release, ondertekend (Sigstore; voor Windows later ook
   codeondertekening).
3. **Webversie**: statische bestanden met Subresource Integrity; de hashes in de release, zodat
   iedereen kan nagaan dat de geserveerde app die uit de release is. Eventueel een
   inhoudsgeadresseerde kopie.
4. Een korte pagina "Zo controleer je dit zelf": broncode, build, hash, netwerkverkeer.

### Stappen

1. De kern scheiden van netwerk en schijf, en dat met een test bewaken (geen `urllib`, geen
   bestandstoegang in de kernmodules).
2. Een Pyodide-proef met de synthetische populatie (numpy, pandas, h3; DuckDB in de browser of een
   pandas-pad).
3. De populatie als downloadbaar artefact: landelijk, compact, met versie en hash; lazy laden
   zonder regio-verraad (zie boven).
4. De offline-stap en de CSP in de webschil; hetzelfde "alles blijft hier"-overzicht in de
   Windows-versie.
5. Attestaties, controlegetallen en een reproduceerbaarheidscontrole in de release-workflow.

## Kladbloknotitie 12: Welke KNMI-stations, welk jaar, welke grootheden? (TODO)

Opgekomen 27-09-2026. Niet elk KNMI-station meet alles, en de stationslijst verandert in de tijd.
Dat raakt twee dingen: de populatie (welk station is voor elke woning het dichtstbijzijnde) en het
terugleiden van weer (welke stations deden mee aan een interpolatie).

### Wat er speelt

Uit de KNMI-uurgegevens 2022-2025 en de documentatie van de verwerkingsrepo's:

| station | wat | gevolg |
|---|---|---|
| 242 Vlieland, 340 Woensdrecht | temperatuur, geen globale straling (Q) | wie T en Q samen vraagt, verliest deze stations |
| 391 Arcen, 392 (nieuw) | 391 onvolledig in 2025, 392 vanaf 2025 | de stationsverdeling verschilt per jaar |
| 290 Twenthe, 323 Wilhelminadorp | kleine gaten (2022) | per uur ontbreekt soms een station |
| 210 Valkenburg | gestopt in 2016, opgevolgd door 215 Voorschoten | een dataset kan nog woningen aan 210 toekennen |

Hoe de datasets het weer opnemen:

| dataset | weer |
|---|---|
| Installatiemonitor 3 (RVO) | dichtstbijzijnd station uit een lijst van 28, inclusief 210; bij 210, 240 en 340 wijkt de meegeleverde reeks af van KNMI (oorzaak onbekend) |
| DPH | dichtstbijzijnd station (25 stations), eind-gelabeld uur als begin-gelabeld overgenomen |
| datasets die de NeedForHeat-weerbibliotheek gebruiken | RBF-interpolatie naar een punt; de bibliotheek laat rijen met een ontbrekende grootheid weg, dus met T en Q samen doen alleen stations mee die beide meten |
| WarmingUP, DACS-HW | geen weer per woning |

### Hoe ermee om te gaan

1. **Stationsset per grootheid en per uur** in de rechercheur: gedaan voor "alle stations met T"
   tegenover "alleen stations met T én Q" (methode met achtervoegsel `+Q`). Nog te doen: andere
   combinaties (wind, luchtvochtigheid) en een vaste lijst die een dataset gebruikte (IM3: 28).
2. **Stationsindeling per periode** in de populatie: `knmi_station` nu uit de huidige lijst. Een
   dataset uit een andere periode (of met 210) hoort tegen de indeling van die periode getoetst te
   worden: de Voronoi-vlakken met de stations die toen maten. Voorstel: `knmi_station` per jaar, of
   een alias (210 → 215) met een melding "historisch station".
3. **Stations die niet bij KNMI passen** (IM3: 210, 240, 340) als bevinding melden: de dataset
   bevat weer dat niet uit de openbare KNMI-reeks komt. Voor de privacy maakt het weinig uit (het
   station staat erbij), voor de precisie wel.
4. **Voor wie weer toevoegt** (stap Weerlocatie): alleen stations gebruiken die in de hele periode
   alle gevraagde grootheden meten, of per uur de beschikbare; en vastleggen welke dat waren.


## Kladbloknotitie 13: De warmtesignatuur van alle woningen openbaar, in een eigen repo (TODO)

**Naam.** Voortaan *warmtesignatuur* (Engels: *heat signature*) in plaats van
warmteprestatiesignatuur. Korter; "vingerafdruk" wekt de verkeerde indruk en "profiel" betekent in
de energiewereld een standaardverbruik door het jaar heen. De code houdt voorlopig `sig_*`.

**Idee.** De populatie met warmtesignaturen komt helemaal uit openbare bronnen (BAG, 3DBAG,
EP-online, KNMI). Een aanvaller kan hem dus zelf maken; de bescherming van een gepubliceerde
dataset moet uit die dataset komen, niet uit het geheimhouden van dit bestand (geen *security by
obscurity*). Publiceer hem daarom in een eigen repo, maandelijks automatisch bijgewerkt. Bijkomend
voordeel: de webversie (notitie 11) downloadt alleen, en de API-sleutel van EP-online blijft een
*secret* in de CI van die repo.

**Afwegingen, vóór de eerste publicatie.**

- De drempel zakt van "een paar avonden rekenen" naar "één download". Benoemen in de README.
- AVG: een signatuur per BAG-ID zegt iets over de bewoners. Energielabels per adres zijn openbaar
  bij wet; een afgeleide heeft een eigen grondslag nodig (gerechtvaardigd belang, afweging op
  papier). Laten toetsen door iemand met privacyrecht als vak.
- Licenties: BAG CC0; 3DBAG en KNMI CC BY (naamsvermelding); EP-online: nagaan of
  herverspreiding in bulk mag (mogelijk het struikelpunt).

**Bouw (GitHub Actions).**

- `schedule: cron` maandelijks; per bron een job, tussenresultaten als release-bestand (3DBAG hoeft
  niet elke maand).
- Runner voor openbare repo's: ~16 GB geheugen, ~14 GB vrije schijf, 6 uur per job. BAG is krap.
- Herkomst aantoonbaar met `actions/attest-build-provenance`; `manifest.json` met bronversies,
  commit en sha256 per bestand.
- Geplande workflows in openbare repo's stoppen na 60 dagen zonder activiteit: laat de workflow het
  manifest committen.

**Hosting voor de browser.** Een browser leest een bestand van een andere site alleen met
CORS-toestemming; downloads uit GitHub Releases hebben die (voor zover bekend) niet. Eerst testen.
Kandidaten: GitHub Pages (1 GB per site, 100 MB per bestand: opsplitsen), Hugging Face Datasets,
Zenodo (met DOI). Releases blijft de officiële bron. De webversie downloadt altijd de hele set: per
regio ophalen verraadt welke regio iemand bekijkt.

**Minimale set** (alles op `vbo_id`; huidige `population.parquet` is 1,0 GB voor 8,39 mln woningen):

| bestand | inhoud |
|---|---|
| `woningen` | vbo_id, postcode6, huisnummer, huisletter, toevoeging, gemeente, provincie, bouwjaar, oppervlakte, woningtype, energielabel, lat/lon (5 decimalen) |
| `warmtesignatuur_invoer` | pand_woningen, aaneengebouwd, opp_buitenmuur/grond/dak_plat/dak_schuin/scheidingsmuur, daktype, bouwlagen, hoogte, compactheid, label_oppervlakte, warmtebehoefte, nta8800 |
| `warmtesignatuur` | sig_H/C/tau/Asol/Ainf en de varianten per methode (mwa, best, ep, passend, passend_cbag) |
| klein | knmi_stations, gemeenten, gemeentegrenzen, knmi_uur_JJJJ, manifest.json |

Weg, want af te leiden: postcode4, h3_r4..r8, knmi_station, rd_x/rd_y; niet nodig:
nummeraanduiding_id, pand_id, status. Signaturen als float32 op 3 significante cijfers (de
modelfout is veel groter). Schatting, niet gemeten: 300 à 400 MB samen.

### EP-online: wat mag, en vier routes

**De voorwaarden** (bij de API-sleutel, dus ook voor het totaalbestand; geraadpleegd 2026-09-27):
de gegevens zijn vrij en kosteloos bruikbaar, maar "Het is niet toegestaan de gegevens direct op
individueel niveau herkenbaar in grote aantallen aan derden te leveren". Indirect mag wel
(voorbeeld: een woningsite). De sleutel is persoonsgebonden. Op data.overheid.nl: "Geen open
licentie", toegang "Beperkt". Lezing: het label zelf per BAG-ID als downloadbaar bestand voor
alle woningen is "direct in grote aantallen" en mag niet. Een signatuur per woning die (deels) uit
labelgegevens is afgeleid is een nieuwe grootheid: te verdedigen als "indirect", zoals de
voorwaarden toestaan. AnonyMate zelf (labels intern, uitkomsten naar buiten) is indirect. Aan RVO
voorleggen.

**Welke methoden zijn schoon (zonder EP-online)?** Alleen `nta8800` en `mwa`, en dan alleen als het
woningtype uit de vorm van het pand komt (`infer_dwelling_type`), niet uit het label: nu komt het
woningtype uit EP-online zodra er een label is (zie notitie 9). `best`, `ep` en `passend` rekenen met
labelgegevens (label, warmtebehoefte, compactheid, gebruiksoppervlak van het label).

1. **Alleen BAG + 3DBAG publiceren**: `woningen` zonder energielabel, `warmtesignatuur` met alleen
   `nta8800` en `mwa` (woningtype uit de vorm). Geen EP-vraag, maar de toets onderschat de
   aanvaller: die haalt het label zelf op, en het label is een sterk kenmerk.
2. **De webversie haalt EP-online zelf op met een sleutel van de gebruiker**: sleutel in de browser,
   en de API staat verzoeken vanuit een browser vermoedelijk niet toe (CORS). Afgevallen.
3. **Uitleg van RVO** (eerst via een contact bij RVO, dan fbni@rvo.nl): bevestigen dat afgeleide
   signaturen per woning "indirect" zijn. Dan kunnen `best`, `ep` en `passend` in de openbare set;
   alleen het label zelf blijft erbuiten.
4. **De gebruiker brengt zijn eigen EP-bestand mee** (voorkeur voor het label zelf; combineert met 3): de repo publiceert alleen wat uit
   BAG, 3DBAG en KNMI komt (route 1). De gebruiker vraagt zelf een sleutel aan, downloadt het
   totaalbestand op ep-online.nl en sleept het in AnonyMate; die koppelt de labels lokaal en rekent
   `best`, `ep` en `passend` ter plekke uit. Geen sleutel in de app, geen CORS, geen levering door
   ons aan derden, en de toets blijft volledig. Zonder EP-bestand werkt het ook, met de melding
   dat het risico dan een ondergrens is. Open: rekentijd van de labelmethoden in de browser.

`warmtesignatuur_invoer` is daarmee optioneel: AnonyMate heeft hem niet nodig; narekenbaarheid
komt uit de reproduceerbare, geattesteerde build.

### De sleutel voor de gebruiker zo makkelijk mogelijk

De aanvraag vraagt organisatienaam, type organisatie en e-mailadres (KvK-nummer is optioneel).
Dat is een klein hobbeltje, ook voor een aanvaller: een e-mailadres en instemming met de
voorwaarden. Geen bescherming om op te bouwen (een wegwerpadres is zo gemaakt), wel een spoor en
een afspraak.

- **Webversie (route 4)**: AnonyMate ziet de sleutel nooit. Een stappenkaartje ("1. vraag een
  sleutel aan, 2. download het totaalbestand, 3. sleep het hierheen") met de twee links; een
  sleepvlak dat ook de zip accepteert; het bestand lokaal bewaren (OPFS/IndexedDB), zodat het één
  keer per maand hoeft; de datum van het bestand tonen en na twee maanden vragen om een nieuwe.
- **Windows-versie**: een veld "EP-online-sleutel" dat de sleutel in de Windows-referentiekluis
  bewaart (`keyring`), nooit in een bestand; de knop "labels ophalen" downloadt en verwerkt. Voor
  wie de sleutel niet wil invullen: ook hier een sleepvlak voor het totaalbestand.
- **Opdrachtregel**: zoals nu `EPONLINE_API_KEY`, of `anonymate ingest ep-online --file <totaalbestand>`.
