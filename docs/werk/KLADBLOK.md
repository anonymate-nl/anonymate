# KLADBLOK (TODO) — anonymate <!-- omit from toc -->

Losse verbeterpunten, nog niet ingepland. Verplaats naar een issue of PR zodra opgepakt.

**Alleen wat nog moet gebeuren.** Bevindingen en verantwoording achteraf horen hier niet: die staan
in [`../`](..) en in de commitgeschiedenis. Staat er iets in dat alleen vertelt wat er gebeurd is,
dan kan het eruit.

## Inhoudsopgave <!-- omit from toc -->

**A. Warmtesignatuur**

- [Kladbloknotitie 1: Welke berekende signatuur is de beste? Toetsen tegen gemeten woningen](#kladbloknotitie-1-welke-berekende-signatuur-is-de-beste-toetsen-tegen-gemeten-woningen-todo)
- [Kladbloknotitie 2: Zonnetoetreding naar gevelrichting](#kladbloknotitie-2-zonnetoetreding-naar-gevelrichting-todo)
- [Kladbloknotitie 3: Infiltratie per bouwjaar in plaats van één landelijk getal](#kladbloknotitie-3-infiltratie-per-bouwjaar-in-plaats-van-één-landelijk-getal-todo)
- [Kladbloknotitie 4: Appartementen hebben geen signatuur](#kladbloknotitie-4-appartementen-hebben-geen-signatuur-todo)
- [Kladbloknotitie 5: Thermische massa uit het label of uit de BAG?](#kladbloknotitie-5-thermische-massa-uit-het-label-of-uit-de-bag-todo)
- [Kladbloknotitie 6: Hoort het stedelijk hitte-eiland bij de beste openbare signatuur?](#kladbloknotitie-6-hoort-het-stedelijk-hitte-eiland-bij-de-beste-openbare-signatuur-todo)

**B. Herleidbaarheid**

- [Kladbloknotitie 7: Gevoelige kenmerken (l-diversiteit)](#kladbloknotitie-7-gevoelige-kenmerken-l-diversiteit-todo)
- [Kladbloknotitie 8: Representativiteit: welke vertekening geeft het weglaten van woningen?](#kladbloknotitie-8-representativiteit-welke-vertekening-geeft-het-weglaten-van-woningen-todo)
- [Kladbloknotitie 9: Woningtype voor alle woningen, niet alleen die met een label](#kladbloknotitie-9-woningtype-voor-alle-woningen-niet-alleen-die-met-een-label-todo)
- [Kladbloknotitie 10: Welke KNMI-stations, welk jaar, welke grootheden?](#kladbloknotitie-10-welke-knmi-stations-welk-jaar-welke-grootheden-todo)
- [Kladbloknotitie 11: Ruis die in zee valt, of een andere woning als ruis?](#kladbloknotitie-11-ruis-die-in-zee-valt-of-een-andere-woning-als-ruis-todo)

**C. Verspreiding**

- [Kladbloknotitie 13: Een webversie (WebAssembly): local first en verifieerbaar](#kladbloknotitie-13-een-webversie-webassembly-local-first-en-verifieerbaar-todo)
- [Kladbloknotitie 14: De warmtesignatuur van alle woningen openbaar, als datapakketten van AnonyMate](#kladbloknotitie-14-de-warmtesignatuur-van-alle-woningen-openbaar-als-datapakketten-van-anonymate-todo)
- [Kladbloknotitie 15: De webversie sneller laten opstarten](#kladbloknotitie-15-de-webversie-sneller-laten-opstarten-todo)

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
[notitie 6](#kladbloknotitie-6-hoort-het-stedelijk-hitte-eiland-bij-de-beste-openbare-signatuur-todo).

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

## Kladbloknotitie 5: Thermische massa uit het label of uit de BAG? (TODO)

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

## Kladbloknotitie 6: Hoort het stedelijk hitte-eiland bij de beste openbare signatuur? (TODO)

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

---

## Kladbloknotitie 7: Gevoelige kenmerken (l-diversiteit) (TODO)

k-map en δ-presence meten of een woning te vinden is, niet of alle woningen in een groep dezelfde
gevoelige waarde delen. Bij de per-record-toets zijn de groepen in de dataset meestal één record
groot, dus l-diversiteit binnen de dataset zegt weinig; eerst doordenken wat de juiste vorm is
(bijvoorbeeld: een gevoelig kenmerk dat binnen een populatieklasse vrijwel constant is).

## Kladbloknotitie 8: Representativiteit: welke vertekening geeft het weglaten van woningen? (TODO)

De verschuiving per kenmerk en op de uitkomst (totale-variatieafstand, SMD) staat in
`anonymate.representativiteit`. Nog open:

1. **Ten opzichte van de doelpopulatie.** Een dataset is zelden representatief voor de hele
   woningvoorraad; dat hoeft ook niet. Vergelijk daarom de afstand dataset → woningvoorraad vóór en
   na weglaten (de populatie ligt toch al lokaal klaar): wordt de dataset door het weglaten
   minder of juist méér representatief? Het wegen van de verdelingen, zoals in surveyonderzoek,
   geeft ook een correctie die gebruikers kunnen toepassen.
2. **Op het analyseresultaat.** Het strengste: draai een referentieanalyse (bijvoorbeeld een
   regressie van verbruik op bouwjaar en oppervlakte) op de hele dataset en op het gepubliceerde
   deel, en rapporteer het verschil in uitkomst. Dat vraagt een analyse per dataset en is daarom
   eerder iets voor de bronhouder dan voor de tool.

3. In `suggest` en `signatuur publiceer --verken` de verschuiving naast precisieverlies en aantal
  publiceerbare records, zodat grover publiceren en weglaten op dezelfde manier te vergelijken zijn.
4. Weglaten en grover maken vergelijken voor dezelfde records: een staartklasse samenvoegen houdt
  de woning in de dataset (grover, maar zonder vertekening), weglaten niet.

Bij kleine datasets (honderden records) is de verschuiving door een handvol weglatingen
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

**Meting (2026-09-28, eengezinswoningen met label).** Aandeel scheidingsmuur in alle muur, 10e /
50e / 90e percentiel: twee-onder-een-kap 0,24 / 0,31 / 0,38; hoekwoning 0,24 / 0,31 / 0,37;
tussenwoning 0,50 / 0,62 / 0,70. Vrijstaand: 83% niet aaneengebouwd. De grens tussenwoning/rest
staat nu op 0,44 (`MID_TERRACE_SHARE`; was 0,35, waardoor een deel van de hoek- en
twee-onder-een-kapwoningen als tussenwoning telde).

**Hoek of twee-onder-een-kap** is met het aandeel niet te scheiden (beide één gedeelde muur). Idee:
kijk naar de buurwoning. Bij een twee-onder-een-kap is de dichtstbijzijnde aaneengebouwde woning in
een ander pand zelf ook een woning met één gedeelde muur (aandeel ~0,3), bij een hoekwoning een
tussenwoning (~0,6). Te zoeken met een raster van 25 m in DuckDB op `rd_x`/`rd_y` (geen scipy
nodig). Tussenstand na 5 van de 12 provincies (Drenthe,
Flevoland, Friesland, Gelderland, Groningen; 558.059 rij- en twee-onder-een-kapwoningen met label;
de run stopte daarna): woningtype juist met de regel **zonder buur** 81,3%, met de buurregel bij
drempel 0,40 / 0,44 / 0,48 / 0,52: 78,9 / 79,7 / 79,9 / 80,0%. De buurregel is in elke provincie
tot nu toe slechter. Tenzij de Randstad (de meeste rijwoningen) dat omdraait: niet opnemen, en de
regel zonder buur houden. De overige zeven provincies draaien als er geen andere zware programma's
open staan (enkele uren; de laptop mag niet in slaap vallen).

**Stand.** `infer_dwelling_type` bestaat en wordt gebruikt voor de signatuur en in het datapakket
(`woningtype_bron` = 'vorm' of 'ep-online'). Nog open: stap 3 ook in `anonymate build`, zodat de
kolom `woningtype` van de lokale populatie voor elke woning gevuld is, en stap 4.

## Kladbloknotitie 10: Welke KNMI-stations, welk jaar, welke grootheden? (TODO)

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

1. **Stationsset per grootheid en per uur** in de rechercheur: naast "alle stations" en "+Q"
   (alleen stations die ook straling meten) ook andere combinaties (wind, luchtvochtigheid) en een
   vaste lijst die een dataset gebruikte (IM3: 28).
2. **Stationsindeling per periode** in de populatie: `knmi_station` nu uit de huidige lijst. Een
   dataset uit een andere periode hoort tegen de indeling van die periode getoetst te worden: de
   Voronoi-vlakken met de stations die toen maten (`knmi_station` per jaar). De alias voor gestopte
   stations (210 → 215, met melding) bestaat al (`qids.HISTORICAL_STATIONS`); nog na te gaan
   welke andere stations sinds 2010 gestopt of verplaatst zijn.
3. **Stations die niet bij KNMI passen** (IM3: 210, 240, 340) als bevinding melden: de dataset
   bevat weer dat niet uit de openbare KNMI-reeks komt. Voor de privacy maakt het weinig uit (het
   station staat erbij), voor de precisie wel.
4. **Voor wie weer toevoegt** (stap Weerlocatie): alleen stations gebruiken die in de hele periode
   alle gevraagde grootheden meten, of per uur de beschikbare; en vastleggen welke dat waren.

## Kladbloknotitie 11: Ruis die in zee valt, of een andere woning als ruis? (TODO)

Opgekomen 28-09-2026, bij het bekijken van de kaart in de oefenmodus.

**Wat er gebeurt.** De weerzone is de H3-cel waarin de woninglocatie valt *nadat* er ruis op is
gezet (σ ≈ 10 km). Aan de kust valt dat punt geregeld in zee, en dan wordt een cel gepubliceerd die
(bijna) helemaal zee is. Dat ziet er vreemd uit, en een aanvaller weet dan zeker dat de cel niet de
plek van de woning is.

**Wordt de aanvaller er wijzer van?** Nauwelijks, als hij de methode kent:

- Hij wist al dat de cel niet de plek van de woning is, maar een punt na ruis; dat geldt voor
  elke gepubliceerde cel, op land of in zee.
- Wat hij wel leert: een zeecel komt alleen voor bij woningen vlak bij de kust (binnen een paar σ).
  Maar precies die afweging maakt de ruisbewuste weging al: elke woning telt mee naar de kans dat
  haar ruis in déze cel uitkomt (het oranje gebied op de kaart). Voor een zeecel zijn dat alleen
  kustwoningen, en de toets rekent met dat kleinere aantal. Er lekt dus niets extra's, zolang de
  toets per cel met die weging rekent en niet met "woningen in de cel".
- Wat wel een punt is: de **bruikbaarheid**. Het weer van het midden van een zeecel is zeeklimaat
  (milder, winderiger), dus minder representatief voor de woning. Dat is een kwaliteitsprobleem,
  geen privacyprobleem.

**Eenvoudige verbetering: opnieuw trekken.** Valt de cel buiten land (of zonder woningen), trek de
ruis opnieuw. De toets moet dan wel met die regel rekenen: de kans op een cel wordt de kans op
die cel gedeeld door de kans op een landcel, per woning. Anders overschat hij de bescherming aan
de kust iets.

**Andere benadering: een andere woning uit de BAG als ruis.** In plaats van een willekeurige
verschuiving kies je een willekeurige woning uit de N dichtstbijzijnde (of binnen een straal), en
publiceer je de cel (of het weer) van die woning (vgl. *adaptive* en *donut geomasking* in de
literatuur van de uitleg).

Voordelen:

- Altijd op land en op een plek waar woningen staan: het weer is representatief.
- **De bescherming past zich aan de dichtheid aan.** Met "één van de N dichtstbijzijnde" zit een
  woning altijd verborgen tussen minstens N kandidaten: in de stad is de verschuiving klein (goed
  weer), op het platteland en op de Wadden groot. Dat is precies waar de huidige vaste σ tekortschiet
  (dunbevolkte kustcellen) of overdreven is (steden).
- De toets wordt eenvoudiger te begrijpen: k volgt direct uit N.

Nadelen en valkuilen:

- De publicerende partij heeft de BAG nodig (anonymate heeft hem, de populatie ligt lokaal).
- Een gekozen *andere* woning is een echt adres. Publiceer daarom nooit het punt zelf, alleen de
  (grove) cel of het weer daarvan; anders wijst de dataset een onschuldige buur aan.
- De aanvaller kent de regel ook: de kans dat een woning de gepubliceerde cel oplevert, hangt nu
  af van de dichtheid rond die woning. Die kans is exact uit te rekenen (de toets moet dat doen),
  maar hij is niet meer overal gelijk: aan de rand van een dorp kan de verdeling scheef zijn.
- Herhaalbaarheid: bij een nieuwe versie van de dataset dezelfde keuze bewaren (vaste startwaarde
  per woning), anders middelt een aanvaller over versies naar de echte plek toe. Dat geldt ook
  voor de huidige ruis.

**Te doen.** (1) In de toets en op de kaart de regel "opnieuw trekken buiten land" ondersteunen.
(2) "Eén van de N dichtstbijzijnde woningen" als tweede methode in de stap Weerlocatie, met
N ≥ de k van de norm, en vergelijken met σ = 10 km: bescherming (k per woning) en afstand tussen
woning en weerpunt, landelijk en aan de kust.

---

## Kladbloknotitie 13: Een webversie (WebAssembly): local first en verifieerbaar (TODO)

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

### Stand en volgende stappen

Het technisch ontwerp staat in [`webversie.md`](webversie.md). **Stand 30-09-2026:** de webversie
staat op https://anonymate.nl/app/ en de landingspagina linkt ernaar als eerste knop. Alle zeven
stappen van de Windows-app zitten erin, met dezelfde uitkomsten en teksten: norm vastleggen,
kolommen, signatuur (uit in de oefenmodus, zoals in de Windows-app), weerlocatie met kaart,
hitte-eiland en weerspoor, aanvaller, uitkomst met tegels, bitsbalk, k-histogram, afweging (twee
weergaven, waaronder die van El Emam & Arbuckle) en toelichting. Het rekenwerk dat eerst in de
GUI zat, staat in de Qt-vrije kern (`kaart.py`, `stappen.py`, `voortgang.py`); de Windows-app
gebruikt dezelfde functies. Een eigen dataset wordt in de browser nog tegen het verzonnen
Nederland getoetst. Nog te doen, in volgorde:

1. Pyodide en de wheel zelf hosten onder `/app/`, met een service worker voor offline gebruik; de
   CSP zonder CDN (fase 2; in aanbouw op de branch `web-fase2`).
2. Verifieerbaar (fase 6): reproduceerbare build, `manifest.json` met controlegetallen,
   attestatie in de Pages-workflow, een pagina "Zo controleer je dit zelf"; bij voorkeur vóór de
   KITE-presentatie van 29-10-2026.
3. De echte populatie: datapakket in OPFS, via `WORKERFS` naar DuckDB (hangt aan notitie 14).
4. EP-online: het totaalbestand van de gebruiker slepen en lokaal koppelen; daarmee ook de stap
   Signatuur in de browser.
5. Attestaties en controlegetallen ook in de release-workflow van het Windows-programma (afstemmen
   met het werk aan codeondertekening).

## Kladbloknotitie 14: De warmtesignatuur van alle woningen openbaar, als datapakketten van AnonyMate (TODO)

**Idee.** De populatie met warmtesignaturen komt helemaal uit openbare bronnen (BAG, 3DBAG,
EP-online, KNMI). Een aanvaller kan hem dus zelf maken; de bescherming van een gepubliceerde
dataset moet uit die dataset komen, niet uit het geheimhouden van dit bestand (geen *security by
obscurity*). Publiceer hem daarom als datapakketten vanuit de AnonyMate-repo (GitHub Pages),
maandelijks automatisch bijgewerkt. Bijkomend voordeel: de webversie (notitie 13) downloadt
alleen, en de API-sleutel van EP-online blijft een *secret* in de CI.

**Afwegingen, vóór de eerste publicatie.**

- De drempel zakt van "een paar avonden rekenen" naar "één download". Benoemen in de README.
- AVG: een signatuur per BAG-ID zegt iets over de bewoners. Energielabels per adres zijn openbaar
  bij wet; een afgeleide heeft een eigen grondslag nodig (gerechtvaardigd belang, afweging op
  papier). Laten toetsen door iemand met privacyrecht als vak.
- Licenties: BAG CC0; 3DBAG en KNMI CC BY (naamsvermelding); EP-online: nagaan of
  herverspreiding in bulk mag (mogelijk het struikelpunt).

**Bouw (GitHub Actions).** De maandelijkse run staat er
([`populatie.yml`](../../.github/workflows/populatie.yml), op de 10e om 03:17 UTC; het ritme staat
bovenin de workflow uitgelegd) en maakt met `anonymate pakketten` een EP-vrij pakket als artefact.
Nog te doen:

- **Eerste geslaagde run: 30-09-2026** (run 36656432586, 3 u 28 min): populatie van 8.388.265
  woningen, datapakket **421 MB** als artefact (90 dagen bewaard). Tijden: BAG downloaden en inlezen
  191 min (PDOK levert traag), EP-online 2 min, 3D-BAG uit `bronnen-cache` 0 min, populatie bouwen
  11 min. Onderweg gerepareerd: een afgebroken download hervat nu (`store.download`), en het pakket
  houdt één schema over alle blokken (`datapakket.make`).
- De marge is klein: bij een nieuwe 3D-BAG-versie (4 uur of meer extra) past het niet in 6 uur.
  Dan de 3D-BAG in een eigen job of workflow die alleen `bronnen-cache` vult; en overwegen de BAG
  ook te cachen (per maand).
- Herkomst aantoonbaar met `actions/attest-build-provenance`.
- De pakketten naar GitHub Pages (Pages-artefact uit de run, niet in git). De organisatie
  (`anonymate-nl`) en het adres (anonymate.nl) liggen vast; de landingspagina staat er al
  (`website/`, `pages.yml`). Pakketten en landingspagina moeten dan samen in één Pages-deploy.
- Of het weer aanzetten van de workflow via de API de 60-dagengrens echt reset; anders het manifest
  laten committen.

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

### Tweede lezing (andere AI, 2026-09-27) en wat eruit volgt

- **Voorwaarden**: de webapp die labelgegevens alleen functioneel gebruikt is goed verdedigbaar als
  "indirect" (vergelijkbaar met de woningsite). Het zwakke punt is het **los downloadbare bestand**:
  afgeleide signaturen per BAG-ID in bulk lijken meer op directe levering. Label zelf per BAG-ID:
  niet doen. Afgeleide signaturen in het openbare pakket pas na schriftelijke bevestiging van RVO.
- **API-sleutel**: persoonsgebonden. Aanvragen op eigen naam (privé), niet via een werkgever;
  vragen of automatisch bouwen in GitHub Actions met die sleutel binnen de voorwaarden valt.
- **Aan RVO voorleggen, letterlijk naast elkaar**: (1) afgeleide modeluitkomsten per BAG-ID,
  (2) gebruik binnen de webapp, (3) hetzelfde als los downloadbaar bestand, (4) het label zelf,
  (5) server-side bouwen met één persoonsgebonden sleutel.
- **Architectuur**: alles in de AnonyMate-repo; webapp en datapakketten op GitHub Pages (zelfde
  herkomst, dus geen CORS). Datapakketten niet in git (historie groeit, geen Git LFS op Pages),
  maar als Pages-artifact vanuit Actions. Limieten Pages: 1 GB per site, zachte grens 100 GB
  bandbreedte per maand (bij ~400 MB ≈ 250 volledige downloads), deploy maximaal 10 minuten.
  Alternatieven bij groei: GitHub Releases (bestanden < 2 GiB, geen bandbreedtelimiet volgens
  GitHub; range-verzoeken en CORS vanuit de browser eerst testen), object-opslag zonder
  uitgaande-verkeerkosten (bijvoorbeeld Cloudflare R2), Zenodo als archief met DOI.
- **Provenance per kolom** in `manifest.json` (welke bron, welke versie, "ep_online: niet gebruikt"),
  zodat aantoonbaar is welke onderdelen EP-vrij zijn.
- **AVG**: BAG-ID → adres → bewoner maakt gegevens per woning mogelijk persoonsgegevens; "de bron
  is openbaar" is geen grondslag. Gerechtvaardigd belang (doel, noodzaak, afweging) uitschrijven.
  Dataminimalisatie weegt zwaar: de referentiepopulatie is zelf deel van de informatiepositie van
  een aanvaller, dus alleen kolommen die de toets echt nodig heeft. GitHub (VS) valt onder het
  EU-US Data Privacy Framework; los daarvan verwerkt GitHub gegevens van bezoekers van de site.
- **Webapp privacy-minimaal**: geen analytics, externe fonts, scripts of kaarttegels; een CSP met
  `connect-src` alleen naar de eigen herkomst; de dataset van de gebruiker verlaat de browser nooit.

## Kladbloknotitie 15: De webversie sneller laten opstarten (TODO)

Opgekomen 30-09-2026. Het prototype op anonymate.nl/app/ doet er 20 à 40 seconden over voordat je
iets kunt, en de oefenmodus daarna nog 7 à 12 seconden.

### Gemeten (Chromium via QtWebEngine, deze laptop, 29/30-09-2026)

Download over de lijn **33 MB**: pyarrow 9,9 · duckdb 8,6 · pandas 4,1 · wasm-runtime 3,5 ·
numpy 2,9 · Python-stdlib 2,5 · h3 0,4 · pytz, dateutil, micropip samen < 1.

| fase (s) | koud | warm (HTTP-cache) |
|---|---:|---:|
| Python-runtime | 4,6 | 4,2 |
| pakketten laden (numpy, pandas, duckdb, pyarrow, h3) | 19,1 | 23,3 |
| wheel installeren (micropip) | 0,9 | 0,9 |
| `import anonymate.web` | 11,4 | 14,6 |
| oefenpopulatie maken | 12,3 | 12,7 |

Een rustigere meting eerder die avond: opstarten 22-26 s, oefenmodus 7-10 s. **Warm is niet
sneller dan koud**: de tijd zit niet in downloaden maar in rekenen: de wasm-bibliotheken laden en
koppelen, en Python-modules importeren. Minder bytes helpt dus vooral doordat er minder te laden
en te importeren is.

De oefenpopulatie kost native 5 s: 200.000 woningen verzinnen (1,1 s), een miljoen
`h3.latlng_to_cell`-aanroepen voor vijf H3-niveaus (1,5 van 2,2 s in `with_places`) en het
kopiëren naar DuckDB (1,8 s).

### Strategie, van meeste winst per moeite naar minste

1. **pyarrow niet laden.** In het browserpad leest alleen `pd.read_parquet` (voorbeeldweer,
   stations, kaart, weerspoor) nog Parquet. DuckDB leest Parquet zelf en geeft een pandas-tabel
   zonder pyarrow. Eén hulpfunctie voor het lezen, in de kern; pandas 3 valt zonder pyarrow terug
   op Python-strings (nagaan: tests groen zonder pyarrow). Scheelt 10 MB en het laden ervan.
2. **De oefenpopulatie vooraf maken.** `web/maak.py` schrijft haar als Parquet (zstd) naast de app;
   de worker haalt het bestand op en `Population.from_parquet` laat DuckDB er direct in lezen, zonder
   pandas en zonder h3. Dezelfde bytes elke build (vaste seed). Scheelt ~12 s bij de oefenmodus, en
   h3 is bij het opstarten niet meer nodig.
3. **Lui importeren.** `anonymate.web` importeert nu via `cli` bijna alles (signatuur,
   generalisatie, rapport). Bij het opstarten alleen `detect`, `risk`, `population`; de rest pas
   bij de stap die hem nodig heeft. `h3` pas bij Weerlocatie.
4. **Parallel.** Runtime en pakketten tegelijk (`loadPyodide({packages})`); de wheel en de
   oefenpopulatie ophalen terwijl Python start; micropip overslaan en de wheel zelf uitpakken
   (`pyodide.unpackArchive`).
5. **De pagina meteen bruikbaar.** Stap 1 tonen terwijl Python laadt; het bestand kiezen mag al,
   de knop "toetsen" wacht. Zo voelt 15 s als 5.
6. **Zelf hosten met een service worker** (fase 2 van `webversie.md`): na de eerste keer offline
   en zonder netwerkvertraging. Lost het rekenwerk niet op.
7. **Geheugen-snapshot van Pyodide** (experimenteel: `makeMemorySnapshot` / `_loadSnapshot`): na
   de imports één snapshot, daarna in een paar seconden terug. Onderzoeken of dat werkt met de
   gedeelde bibliotheken van duckdb en pandas, en hoe groot hij wordt.
8. **pandas vervangen** (door DuckDB-SQL of numpy): een herschrijving van de kern, dus pas als 1-7
   niet genoeg zijn.

**Doel**: koud binnen 10 s tot je een dataset kunt kiezen, de oefenmodus binnen 2 s daarna. Elke
stap meten met de tijden die de worker al in de console zet ("opstarten (s)").

### Stand van zaken (30-09-2026, stap 1-5 gedaan en in de browser gemeten)

**Gemeten in Chromium op deze laptop**, zelfde moment, oude tegen nieuwe versie: opstarten 47 s →
**17-22 s**; oefenmodus 11 s → **1-2 s**. Wat overblijft is vooral `python_pakketten` (12-14 s) en
`import` (5-7 s): Python, numpy, pandas en DuckDB laden en importeren. Daarna laden h3 en de
modules voor de latere stappen op de achtergrond (samen ~2 s); "Alles is geladen" verschijnt pas
als dat klaar is. De opstartbalk telt stappen en schat vanaf de eerste seconde de resterende tijd
(met de tijden van het vorige bezoek). Het weerspoor gebruikt alleen Europe/Amsterdam, die de
wheel zelf meelevert (1,1 kB) in plaats van het pakket tzdata (349 kB).

Volgende kandidaten: stap 6 (zelf hosten met een service worker, fase 2) en stap 7
(geheugen-snapshot); stap 8 (pandas vervangen) pas als dat niet genoeg is.

- **1 pyarrow niet laden: gedaan.** `anonymate/tabel.py` (`lees_parquet`, via DuckDB, zelfde dtypes
  als `pd.read_parquet`) wordt gebruikt door `voorbeeld.py`, `weerspoor.py` (uurgegevens,
  stations, reeksen) en `read_dataset`. `gui.py` en de code die het depot schrijft
  (`store`, `datapakket`, `rounding`, `signature`) blijven pyarrow gebruiken. De worker laadt
  pyarrow niet meer. Test in `tests/test_web.py`: een subproces waarin `pyarrow` en `h3` niet te
  importeren zijn, draait `open_practice`, `run` en `export` met dezelfde uitkomst (0 van 62
  publiceerbaar, 17,61 bits nodig).
- **2 oefenpopulatie vooraf maken: gedaan.** `voorbeeld.write_population` schrijft
  `web/dist/oefenpopulatie.parquet` (zstd, één thread, dezelfde bytes per build; **4,1 MB**);
  `web.open_practice(population_path)` leest hem met `Population.from_parquet`. Een test vergelijkt
  de uitkomst met de populatie uit het geheugen: gelijk. h3 wordt bij het opstarten niet geladen;
  de worker laadt hem pas als een aanroep om `h3` vraagt.
- **3 lui importeren: gedaan.** De hulpfuncties van de facade (`read_dataset`, `qids_from`,
  `parse_scope`, `SCENARIOS`) staan nu in `anonymate/invoer.py`; `cli` importeert ze daar vandaan.
  `import anonymate.web` haalt `cli`, `generalize`, `report` en `signature` niet meer binnen (10
  naar 8 eigen modules). Gemeten in CPython op deze (drukke) laptop, met pandas en DuckDB al
  geladen: de eigen modules kosten 0,5-0,7 s voor, 0,2-0,4 s na. De rest van de 11-15 s in de
  browser is het importeren van pandas en DuckDB zelf; dat lost stap 1 (geen pyarrow) en ten slotte
  stap 7 of 8 op, niet dit.
- **4 parallel: gebouwd.** `loadPyodide({packages})`; wheel en oefenpopulatie worden opgehaald terwijl
  Python start; zonder micropip: `unpackArchive(wheel, "wheel", {extractDir: site-packages})`. De
  tijden staan in "opstarten (s)": `python_pakketten`, `wheel`, `import`, `oefenpopulatie`, plus
  `wheel_ophalen` en `populatie_ophalen` (de duur van de parallelle downloads zelf).
- **5 pagina meteen bruikbaar: gebouwd.** Stap 1 staat er meteen, de voortgang is een smalle regel
  bovenaan; klikken op de oefenknop of een bestand kiezen vóór de rekenkern klaar is, zet de
  aanroep in de rij ("wacht op de rekenkern…") en voert hem uit zodra Python klaar is.

`unpackArchive` en DuckDB's `read_parquet` op het Emscripten-bestandssysteem werken in de browser
zoals in CPython (gecontroleerd).

