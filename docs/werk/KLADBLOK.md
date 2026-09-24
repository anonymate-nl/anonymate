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
- [Kladbloknotitie 7: Hoort het stedelijk hitte-eiland bij de beste openbare signatuur?](#kladbloknotitie-7-hoort-het-stedelijk-hitte-eiland-bij-de-beste-openbare-signatuur-todo)

**B. Herleidbaarheid**

- [Kladbloknotitie 5: Gevoelige kenmerken (l-diversiteit)](#kladbloknotitie-5-gevoelige-kenmerken-l-diversiteit-todo)
- [Kladbloknotitie 9: Woningtype voor alle woningen, niet alleen die met een label](#kladbloknotitie-9-woningtype-voor-alle-woningen-niet-alleen-die-met-een-label-todo)
- [Kladbloknotitie 8: Representativiteit: welke vertekening geeft het weglaten van woningen?](#kladbloknotitie-8-representativiteit-welke-vertekening-geeft-het-weglaten-van-woningen-todo)

**C. Verspreiding**

- [Kladbloknotitie 6: Het Windows-programma via GitHub Releases](#kladbloknotitie-6-het-windows-programma-via-github-releases-todo)

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
  [`../warmteprestatiesignatuur.md`](../warmteprestatiesignatuur.md)).

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
   `warmteprestatiesignatuur.md`.

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
   (ASHRAE, stack- en windcoëfficiënt per aantal boulagen) naar een debiet. Een leermodel met een
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
