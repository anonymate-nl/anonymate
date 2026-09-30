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
- [Kladbloknotitie 12: Zonnepanelen vanuit de lucht: een zichtbaar kenmerk dat een aanvaller kan tellen](#kladbloknotitie-12-zonnepanelen-vanuit-de-lucht-een-zichtbaar-kenmerk-dat-een-aanvaller-kan-tellen-todo)

**C. Verspreiding**

- [Kladbloknotitie 13: Een webversie (WebAssembly): local first en verifieerbaar](#kladbloknotitie-13-een-webversie-webassembly-local-first-en-verifieerbaar-todo)
- [Kladbloknotitie 14: De warmtesignatuur van alle woningen openbaar, als datapakketten van AnonyMate](#kladbloknotitie-14-de-warmtesignatuur-van-alle-woningen-openbaar-als-datapakketten-van-anonymate-todo)
- [Kladbloknotitie 15: De webversie sneller laten opstarten](#kladbloknotitie-15-de-webversie-sneller-laten-opstarten-todo)

---

## Kladbloknotitie 1: Welke berekende signatuur is de beste? Toetsen tegen gemeten woningen (TODO)

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
rainbow table (zie notitie 1).

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

Het uitgangspunt van de signatuur `best` is: *de beste signatuur die je alleen uit een adres en
openbare gegevens kunt halen*. Het stedelijk hitte-eiland hoort daar mogelijk bij.

**Wat het is.** Geen eigenschap van het gebouw, maar van de plek: in de stad is het buiten warmer
dan op het KNMI-station waarvan het weer komt. Het Maatwerkadvies corrigeert daarom de
buitentemperatuur met een locatiespecifieke toeslag (0-2 °C, studiewaarde 1 °C; bron: de
validatierapportage MWA, RVO 2022), op basis van de RIVM-hitte-eilandkaart.

**Waarom het ertoe doet.** Een woningmodel dat het weer van een KNMI-station gebruikt, ziet een
stadswoning als "beter geïsoleerd" dan hij is: de lagere warmtevraag komt deels door de warmere
omgeving. Een geleerde signatuur neemt dat effect vanzelf mee in H; een berekende niet. Zonder
correctie is de vergelijking dus niet eerlijk, en mét correctie zou `best` dichter bij de meting
moeten komen. Dat is te toetsen in notitie 1.

**Het voorbehoud.** De RIVM-waarden zijn zomergemiddelden. Voor het stookseizoen is de correctie
niet gevalideerd, en er is geen onderbouwde winterfactor. Vandaar de varianten 0, 50 en 100% van
de kaartwaarde in notitie 1: de meting beslist, niet een aanname.

**Voor de herleidbaarheid.** Als de correctie alleen intern in de simulatie wordt gebruikt, lekt
er niets. Maar een geleerde H van een stadswoning bevat het hitte-eiland-effect al, en draagt dus
een beetje locatie-informatie mee. En de hitte-eilandwaarde zelf is, als hij gepubliceerd wordt,
een locatie-QID (`uhi` in de catalogus). Beide zijn mee te nemen in de rainbow table.

**Wat er nog moet gebeuren.**

1. De varianten 0/50/100% meenemen in de toets van notitie 1, en `uhi` als extra parameter
   ΔT_uhi [K] naast H, C, τ, A_sol, A_inf in de functionele signatuurtabel.
2. Afhankelijk van de uitkomst: `best` met of zonder hitte-eilandcorrectie als standaard.
3. **`uhi` per woning** (`anonymate ingest uhi --raster`, bemonsterd op het eigen punt van de
   woning) in de maandelijkse run: eenmalig een download van 1,95 GB zip (~3,5 GB uitgepakt) en
   ~300 vensters van 2048 x 2048 cellen, naar schatting een half uur extra bij de eerste keer (niet
   op GitHub gemeten); de tabel daarna bewaren bij `bronnen-cache`. De kaart wordt niet ververst,
   dus eenmalig volstaat. Andere routes zijn afgevallen (WCS: ruim 500 blokken; WMS per punt:
   onhaalbaar; een tabel per postcode van PDOK of RIVM bestaat niet).
4. Beslissen of `uhi` per woning het datapakket in mag: een 10 m-waarde is een fijnere
   locatie-eigenschap dan een waarde per postcode.

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

**Hoek of twee-onder-een-kap** is met het aandeel scheidingsmuur niet te scheiden (beide één
gedeelde muur). Idee: kijk naar de buurwoning. Bij een twee-onder-een-kap is de dichtstbijzijnde
aaneengebouwde woning in een ander pand zelf ook een woning met één gedeelde muur (aandeel ~0,3),
bij een hoekwoning een tussenwoning (~0,6). Te zoeken met een raster van 25 m in DuckDB op
`rd_x`/`rd_y` (geen scipy nodig). Op de eerste vijf van de twaalf provincies (eengezinswoningen
met label) is de buurregel in elke provincie slechter dan de regel zonder buur (ongeveer 79-80%
tegen 81% juiste woningtypen, bij drempels 0,40-0,52). Tenzij de Randstad (de meeste
rijwoningen) dat omdraait: niet opnemen, en de regel zonder buur houden. De overige zeven
provincies nog meten (enkele uren; de laptop mag niet in slaap vallen).

**Nog open:** `infer_dwelling_type` (drempel `MID_TERRACE_SHARE`, zie `signature.py`) wordt al
gebruikt voor de signatuur en in het datapakket (`woningtype_bron` = 'vorm' of 'ep-online'); stap 3
moet ook in `anonymate build`, zodat de kolom `woningtype` van de lokale populatie voor elke woning
gevuld is, en stap 4.

## Kladbloknotitie 10: Welke KNMI-stations, welk jaar, welke grootheden? (TODO)

Niet elk KNMI-station meet alles, en de stationslijst verandert in de tijd.
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

## Kladbloknotitie 12: Zonnepanelen vanuit de lucht: een zichtbaar kenmerk dat een aanvaller kan tellen (TODO)

**De vraag.** Zonnepanelen staan in de catalogus als zichtbaar kenmerk (`zonnepanelen`, scenario
"zichtbaar"): een aanvaller ziet ze op straat of op een luchtfoto. De populatie heeft er geen kolom
voor, dus de toets **schat** hoe vaak het kenmerk voorkomt uit de dataset zelf. Inmiddels tellen
partijen de panelen per dak op luchtfoto's, en voor een paar gemeenten staat dat open per pand. Een
aanvaller met zo'n kaart kan het kenmerk dus **tellen**, en niet alleen "ja/nee" maar ook het aantal
panelen, het benutte dakoppervlak en de oriëntatie. Een dataset die zonnepanelen, het aantal, het
vermogen (kWp) of de oriëntatie publiceert, geeft daarmee meer prijs dan de toets nu meet. Omgekeerd
kunnen dezelfde bronnen de toets beter maken.

### De bronnen

| bron | wat | niveau | toegang |
|---|---|---|---|
| **Zonnepanelenkaart** (Utrecht) | eigen AI-model op luchtfoto's, "op een detailniveau van 7 centimeter"; luchtfoto's uit september 2024 | per adres: aanwezig ja/nee, aantal panelen, benut dakoppervlak, dakdelen met hellingshoek, geschatte kWh, maximale potentie | commercieel: 20 credits per maand gratis, daarboven 24 tot 748 euro per maand; export naar Excel; geen API genoemd; licentie niet gevonden |
| **Zon op gebouw** (RVO, Kadaster, NP RES, 2022) | detectie van bestaande panelen op luchtfoto's plus theoretische potentie, op daken en boven parkeerplaatsen | per pand | alleen overheden, één exemplaar per RES-regio; openbaar publiceren is het voornemen, maar er zijn eerst nog belemmeringen weg te nemen |
| **CBS** 86044NED en opvolgers | aantal installaties en opgesteld vermogen (kWp) bij woningen, uit registraties (PIR, CertiQ, subsidies); peildatum 31 december | wijk en buurt | open (OData); de tabel over 2022 is gevonden, nieuwere jaargangen niet nagelopen |
| **Liander**, terugleverdata kleinverbruik (vanaf 2025) | Standaard Jaar Invoeding (SJI): verwachte teruglevering in kWh, afgeleid van de gemeten teruglevering van het jaar ervoor; peildatum 1 januari | pc6, clusters van minstens 10 aansluitingen | open, met bronvermelding; Enexis en Stedin hebben vergelijkbare sets, niet nagelopen |
| **Liander**, decentrale opwek zon kleinverbruik | aantal installaties en kWp | CBS-buurt | open |
| **Amsterdam** (door Readar), **Den Haag** 2022 | detectie op luchtfoto's, Amsterdam jaarlijks sinds 2015 | per pand | open (Amsterdam publiek domein, Den Haag CC-0) |
| **Readar**, **Sobolt** (Zonnedakje) | landelijke detectie op luchtfoto's (Readar: meer dan 1,4 miljoen installaties), Zonnedakje in 100+ gemeenten | per pand | commercieel, maatwerk voor gemeenten en portefeuilles |
| **PDOK-luchtfoto's** en **3DBAG** | geen detectie, wel de grondstof: jaarlijkse luchtfoto's als open data (2025 ook in hoge resolutie), en dakvlakken met oriëntatie en helling per pand | per pand | open |

Ter vergelijking, landelijk: eind 2024 lag er 11,7 GWp aan panelen bij woningen (CBS, nieuwsbericht
2025/32). CBS heeft met Deep Solaris ook zelf op luchtfoto's gedetecteerd, maar publiceert alleen
geaggregeerd; registraties zijn in Nederland niet verplicht, en dat is precies waarom detectie vanuit
de lucht iets toevoegt.

### Wat een aanvaller per woning kan zien, en hoe goed

| kenmerk in een dataset | te zien vanuit de lucht | haalbaarheid |
|---|---|---|
| zonnepanelen ja/nee | aanwezigheid | **goed**: dit is waar detectie het sterkst in is |
| aantal panelen | telling | **redelijk**: telling op 7 à 8 cm is haalbaar; bomen, schaduw en schuine opnamehoeken maken het minder zeker |
| oriëntatie en helling | panelen op de dakvlakken van 3DBAG | **redelijk tot goed**; Zonnepanelenkaart levert al hellingshoeken per dakdeel |
| oost-west gesplitst | idem | **redelijk**: volgt uit dezelfde koppeling met dakvlakken |
| vermogen (kWp) | aantal × typisch paneelvermogen | **zwak tot redelijk**: niet te zien, wel te benaderen via het aantal en het jaar waarin de panelen voor het eerst op de luchtfoto staan |
| omvormervermogen | niet | **niet**: onzichtbaar; landelijk ligt het onder het paneelvermogen (CBS: 25,6 tegen 28,6 GW over alle sectoren) |
| welk adres bij welke panelen | koppeling | **lastig bij gestapelde bouw**: een pand met meerdere adressen deelt één dak; bij rijwoningen gaat het meestal goed, omdat elk huis een eigen BAG-pand is |

Daarnaast verraadt een gepubliceerde **opwekreeks** per woning (kWh per uur of kwartier) de
oriëntatie en helling (de vorm van de dagcurve) en, net als de buitentemperatuur, de ligging (het
patroon van bewolking). Dat is hetzelfde soort spoor als het weerspoor.

### Het voorbehoud

- **Geen van de per-adresbronnen is landelijk open.** Zonnepanelenkaart is commercieel en de
  licentie voor hergebruik is onbekend; de Kadasterset is alleen voor overheden. Open per pand zijn
  alleen Amsterdam en Den Haag. Voor de aanvaller maakt dat weinig uit (een abonnement volstaat);
  voor een openbare populatie in AnonyMate wel.
- **AnonyMate bevraagt geen derde partij met adressen.** Local-first: alleen open bulkbestanden komen
  in aanmerking als bron, een dienst per adres niet.
- **De nauwkeurigheid is nergens onafhankelijk getoetst** in wat er gevonden is. "7 centimeter" gaat
  over de resolutie van de foto, niet over de juistheid van de telling. CBS rapporteerde in Deep
  Solaris grote verschillen tussen regio's.
- **De peildatum loopt achter.** Een foto van september 2024 mist alles wat daarna is gelegd, en
  in 2025 en 2026 is er door het einde van de salderingsregeling juist veel veranderd. Voor de toets
  betekent dat: een aanvaller met een recentere kaart ziet meer dan de populatie.

### Wat te doen

- **Catalogus uitbreiden**: naast `zonnepanelen` (ja/nee) ook aantal panelen, vermogen (kWp) en
  oriëntatie/helling als zichtbare kenmerken, met herkenning van de kolomnamen in `detect.py` en
  een voorstel voor grove klassen (bijvoorbeeld aantal in klassen van 5, kWp in klassen van 2).
- **Beter schatten waar tellen nog niet kan**: de frequentie van "zonnepanelen ja" per buurt uit de
  open CBS-tabellen (en de netbeheerderssets per buurt of pc6) gebruiken in plaats van de frequentie
  in de dataset zelf. Klein werk en direct bruikbaar.
- **Tellen waar het open kan**: voor Amsterdam en Den Haag een kolom `zonnepanelen` (en aantal)
  per pand in de populatie, zodat de toets daar telt in plaats van schat; en bij RVO en Kadaster
  navragen hoe het staat met het openbaar maken van Zon op gebouw (dan landelijk).
- **Uitleg**: in `docs/herleidbaarheid-uitleg.md` bij het scenario "zichtbaar" benoemen dat
  commerciële luchtfotokaarten het kenmerk landelijk en zonder straatbezoek beschikbaar maken.
- **Later: opwekreeksen** als spoor toetsen, naar het voorbeeld van het weerspoor.
- In de zusterrepo wordt dezelfde bron verkend om de PV-opstelling van een woning voor te vullen;
  wat daar over de nauwkeurigheid bekend wordt, is hier ook bruikbaar.

Bronnen: [zonnepanelenkaart.com](https://zonnepanelenkaart.com/) en
[functionaliteiten](https://zonnepanelenkaart.com/functionaliteiten/);
[Dataset Zon op gebouw (NP RES)](https://www.regionale-energiestrategie.nl/werkwijze/data+monitoring/data+overzicht/2661076.aspx);
[CBS 86044NED](https://www.cbs.nl/nl-nl/cijfers/detail/86044NED);
[CBS, Grootste deel zonnepanelen ligt bij bedrijven (2025)](https://www.cbs.nl/nl-nl/nieuws/2025/32/grootste-deel-zonnepanelen-ligt-bij-bedrijven);
[CBS, Zonnepanelen automatisch detecteren met luchtfoto's](https://www.cbs.nl/nl-nl/over-ons/onderzoek-en-innovatie/project/zonnepanelen-automatisch-detecteren-met-luchtfoto-s);
[Liander, toelichting terugleverdata kleinverbruik](https://www.liander.nl/-/media/files/open-data/terugleverdata-kleinverbruikaansluitingen/toelichting-terugleverdataset-kleinverbruik.pdf);
[Liander decentrale opwek zon](https://data.overheid.nl/dataset/liander-decentrale-opwek-zon-kleinverbruik);
[Amsterdam, zonnepanelen](https://maps.amsterdam.nl/zonnepanelen/);
[Den Haag, zonnepanelen en groene daken 2022](https://data.overheid.nl/en/dataset/zonnepanelendakenjacht);
[Readar, zonnepanelen in Nederland](https://readar.com/zonnepanelen-in-nederland/);
[Sobolt, Zonnedakje](https://sobolt.com/zonnedakje/);
[PDOK, luchtfoto 2025](https://www.pdok.nl/-/luchtfoto-2025-nu-beschikbaar-bij-pdok).

---

## Kladbloknotitie 13: Een webversie (WebAssembly): local first en verifieerbaar (TODO)

De webversie (https://anonymate.nl/app/) draait al; het technisch ontwerp, de stand en hoe je haar
controleert staan in [`webversie.md`](webversie.md). Wat er nog moet gebeuren:

1. **De echte populatie in de browser**: het datapakket in OPFS, via `WORKERFS` naar DuckDB (hangt
   aan notitie 14). Tot dan wordt een eigen dataset tegen het verzonnen Nederland getoetst.
2. **EP-online**: het totaalbestand van de gebruiker slepen en lokaal koppelen; daarmee ook de stap
   Signatuur in de browser (nu uitgeschakeld in de oefenmodus). Open: de rekentijd van de
   labelmethoden in de browser.
3. **Attestaties, controlegetallen en reproduceerbaarheid voor het Windows-programma**: in de
   release-workflow (afstemmen met het werk aan codeondertekening). Een PyInstaller-exe is
   lastiger bit voor bit reproduceerbaar te bouwen: documenteren wat afwijkt.

Uitgangspunten die dit werk sturen: downloaden mag, uploaden nooit; de rekenkern kent geen
netwerk en geen schijf; geen sleutels in de browser (een bron met sleutel komt via een vooraf
gemaakt, openbaar artefact); en ook het ophalen mag niets verraden (hele landelijke bestanden of
grove stukken, zodat het verzoek in een menigte opgaat).

## Kladbloknotitie 14: De warmtesignatuur van alle woningen openbaar, als datapakketten van AnonyMate (TODO)

**Idee.** De populatie met warmtesignaturen komt helemaal uit openbare bronnen (BAG, 3DBAG,
EP-online, KNMI). Een aanvaller kan hem dus zelf maken; de bescherming van een gepubliceerde
dataset moet uit die dataset komen, niet uit het geheimhouden van dit bestand (geen *security by
obscurity*). Het pakket wordt daarom maandelijks automatisch gebouwd en gepubliceerd vanuit de
AnonyMate-repo ([`populatie.yml`](../../.github/workflows/populatie.yml); gebruik staat in de
README). Bijkomend voordeel: de webversie (notitie 13) downloadt alleen, en de API-sleutel van
EP-online blijft een *secret* in de CI.

**Afwegingen.**

- De drempel zakt van "een paar avonden rekenen" naar "één download". Benoemen in de README.
- AVG: een signatuur per BAG-ID zegt iets over de bewoners. Energielabels per adres zijn openbaar
  bij wet; een afgeleide heeft een eigen grondslag nodig (gerechtvaardigd belang, afweging op
  papier). Laten toetsen door iemand met privacyrecht als vak.
- Licenties: BAG CC0; 3DBAG en KNMI CC BY (naamsvermelding); EP-online: nagaan of
  herverspreiding in bulk mag (mogelijk het struikelpunt).

**Nog te doen aan de bouw.**

- **De marge is klein.** Een run duurt ruim 3 uur (baseline: BAG downloaden en inlezen ~3 uur,
  omdat PDOK traag levert; EP-online 2 min; populatie bouwen 11 min). Bij een nieuwe 3D-BAG-versie
  (4 uur of meer extra) past het niet in de 6 uur van een job. Dan de 3D-BAG in een eigen job of
  workflow die alleen `bronnen-cache` vult; en overwegen de BAG ook te cachen (per maand).
- **Herkomst aantoonbaar** met `actions/attest-build-provenance`, ook voor het datapakket (voor de
  webversie is dat er al, in `pages.yml`).
- **Voor de browser** (notitie 13, stap 1) moet het pakket van dezelfde herkomst komen als de app:
  een kopie op GitHub Pages naast `/app/` (bestanden onder 100 MB, dus opsplitsen), samen met de
  landingspagina in één Pages-deploy. Releases blijven de officiële bron.
- **60-dagengrens**: of het weer aanzetten van de workflow via de API de grens echt reset; anders
  het manifest laten committen.
- **Provenance per kolom** in `manifest.json` (welke bron, welke versie, "ep_online: niet
  gebruikt"), zodat aantoonbaar is welke onderdelen EP-vrij zijn.

**Hosting voor de browser.** Een browser leest een bestand van een andere site alleen met
CORS-toestemming; downloads uit GitHub Releases hebben die (voor zover bekend) niet. Eerst testen.
Kandidaten: GitHub Pages (1 GB per site, 100 MB per bestand: opsplitsen; zachte grens 100 GB
bandbreedte per maand, bij ~400 MB ≈ 250 volledige downloads; deploy maximaal 10 minuten; geen
Git LFS, dus het pakket als Pages-artifact vanuit Actions, niet in git), GitHub Releases (< 2 GiB,
geen bandbreedtelimiet volgens GitHub; range-verzoeken en CORS eerst testen), object-opslag zonder
uitgaande-verkeerkosten (bijvoorbeeld Cloudflare R2), Hugging Face Datasets, Zenodo (met DOI).
De webversie downloadt altijd de hele set: per regio ophalen verraadt welke regio iemand bekijkt.

**Minimale set** (alles op `vbo_id`; huidige `population.parquet` is 1,0 GB voor 8,39 mln woningen;
het pakket is ~420 MB):

| bestand | inhoud |
|---|---|
| `woningen` | vbo_id, postcode6, huisnummer, huisletter, toevoeging, gemeente, provincie, bouwjaar, oppervlakte, woningtype, energielabel, lat/lon (5 decimalen) |
| `warmtesignatuur_invoer` | pand_woningen, aaneengebouwd, opp_buitenmuur/grond/dak_plat/dak_schuin/scheidingsmuur, daktype, bouwlagen, hoogte, compactheid, label_oppervlakte, warmtebehoefte, nta8800 |
| `warmtesignatuur` | sig_H/C/tau/Asol/Ainf en de varianten per methode (mwa, best, ep, passend, passend_cbag) |
| klein | knmi_stations, gemeenten, gemeentegrenzen, knmi_uur_JJJJ, manifest.json |

Weg, want af te leiden: postcode4, h3_r4..r8, knmi_station, rd_x/rd_y; niet nodig:
nummeraanduiding_id, pand_id, status. Signaturen als float32 op 3 significante cijfers (de
modelfout is veel groter). `warmtesignatuur_invoer` is optioneel: AnonyMate heeft hem niet nodig;
narekenbaarheid komt uit de reproduceerbare, geattesteerde build.

### EP-online: wat mag, en vier routes

**Standpunt.** Voorkeur voor de makkelijke route: de afgeleide signaturen (deels uit EP-online)
wél in het datapakket, het label zelf niet. Argument: wie toetst, moet toetsen tegen hetzelfde
bestand dat een aanvaller zelf maakt; een gemotiveerde aanvaller vraagt een gratis sleutel aan en
downloadt EP-online toch, dus de drempel hindert vooral de datahouder (geen *security by
obscurity*). Openlijk erbij zeggen dat een bestand dat de app ophaalt, altijd ook los te
downloaden is. De vraag ligt bij een privacyjurist en bij RVO (via de KITE-community). Tot er een
antwoord is: pakket zonder EP-online; de gebruiker koppelt zijn eigen totaalbestand lokaal
(route 4, zie README).

**De voorwaarden** (bij de API-sleutel, dus ook voor het totaalbestand): de gegevens zijn vrij en
kosteloos bruikbaar, maar "Het is niet toegestaan de gegevens direct op individueel niveau
herkenbaar in grote aantallen aan derden te leveren". Indirect mag wel (voorbeeld: een woningsite).
De sleutel is persoonsgebonden. Op data.overheid.nl: "Geen open licentie", toegang "Beperkt".
Lezing: het label zelf per BAG-ID als downloadbaar bestand voor alle woningen is "direct in grote
aantallen" en mag niet. Een signatuur per woning die (deels) uit labelgegevens is afgeleid is een
nieuwe grootheid: te verdedigen als "indirect", zoals de voorwaarden toestaan. AnonyMate zelf
(labels intern, uitkomsten naar buiten) is indirect. Gebruik binnen de webapp, waar labelgegevens
alleen functioneel worden gebruikt, is goed verdedigbaar; het zwakke punt is het **los
downloadbare bestand**: afgeleide signaturen per BAG-ID in bulk lijken meer op directe levering.
Het label zelf per BAG-ID: niet doen. Afgeleide signaturen in het openbare pakket pas na
schriftelijke bevestiging van RVO.

**Aan RVO voorleggen, letterlijk naast elkaar**: (1) afgeleide modeluitkomsten per BAG-ID,
(2) gebruik binnen de webapp, (3) hetzelfde als los downloadbaar bestand, (4) het label zelf,
(5) server-side bouwen met één persoonsgebonden sleutel. De API-sleutel is persoonsgebonden:
aanvragen op eigen naam (privé), niet via een werkgever; vragen of automatisch bouwen in GitHub
Actions met die sleutel binnen de voorwaarden valt.

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
4. **De gebruiker brengt zijn eigen EP-bestand mee** (voorkeur voor het label zelf; combineert met 3):
   de repo publiceert alleen wat uit BAG, 3DBAG en KNMI komt (route 1). De gebruiker vraagt zelf een
   sleutel aan, downloadt het totaalbestand op ep-online.nl en sleept het in AnonyMate; die koppelt
   de labels lokaal en rekent `best`, `ep` en `passend` ter plekke uit. Geen sleutel in de app, geen
   CORS, geen levering door ons aan derden, en de toets blijft volledig. Zonder EP-bestand werkt het
   ook, met de melding dat het risico dan een ondergrens is. Open: rekentijd van de labelmethoden in
   de browser.

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

### Overige overwegingen

- **AVG**: BAG-ID → adres → bewoner maakt gegevens per woning mogelijk persoonsgegevens; "de bron
  is openbaar" is geen grondslag. Gerechtvaardigd belang (doel, noodzaak, afweging) uitschrijven.
  Dataminimalisatie weegt zwaar: de referentiepopulatie is zelf deel van de informatiepositie van
  een aanvaller, dus alleen kolommen die de toets echt nodig heeft. GitHub (VS) valt onder het
  EU-US Data Privacy Framework; los daarvan verwerkt GitHub gegevens van bezoekers van de site.
- **Webapp privacy-minimaal**: geen analytics, externe fonts, scripts of kaarttegels; een CSP met
  `connect-src` alleen naar de eigen herkomst; de dataset van de gebruiker verlaat de browser nooit.

## Kladbloknotitie 15: De webversie sneller laten opstarten (TODO)

De webversie doet er nog te lang over voordat je iets kunt. Wat al is ingebouwd (geen pyarrow,
oefenpopulatie vooraf gemaakt, lui importeren, parallel laden, pagina meteen bruikbaar, service
worker) staat in [`webversie.md`](webversie.md), onder "Opstarten".

### Baseline en doel

Koud opstarten (Chromium via QtWebEngine): **17-22 s**, waarvan `python_pakketten` (Python, numpy,
pandas, DuckDB laden) 12-14 s en `import` 5-7 s; de oefenmodus daarna 1-2 s. Opnieuw laden uit de
cache is niet sneller: de tijd zit in het compileren en importeren van de wasm-bibliotheken, niet
in het downloaden.

**Doel**: koud binnen 10 s tot je een dataset kunt kiezen, de oefenmodus binnen 2 s daarna. Elke
stap meten met de tijden die de worker al in de console zet ("opstarten (s)").

### Kandidaten

1. **Geheugen-snapshot van Pyodide** (experimenteel: `makeMemorySnapshot` / `_loadSnapshot`): na
   de imports één snapshot, daarna in een paar seconden terug. Onderzoeken of dat werkt met de
   gedeelde bibliotheken van duckdb en pandas, en hoe groot hij wordt.
2. **pandas vervangen** (door DuckDB-SQL of numpy): een herschrijving van de kern, dus pas als 1
   niet genoeg is. De rest van de import- en laadtijd is het importeren van pandas en DuckDB zelf.
