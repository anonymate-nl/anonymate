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

### Twee opbrengsten tegelijk

- **Voor de signatuur als functioneel product**: een onderbouwde keuze voor de standaardmethode,
  en een foutmarge die bij `anonymate signatuur adres` vermeld kan worden.
- **Voor de herleidbaarheid**: het verschil tussen de beste berekende en de geleerde signatuur
  per woning is precies de **tolerantie** waarmee een aanvaller een gepubliceerde geleerde
  signatuur moet terugzoeken (zie [`../warmteprestatiesignatuur.md`](../warmteprestatiesignatuur.md)).
  Nu is die tolerantie een schatting; met deze toets wordt hij gemeten.

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
4. De standaardmethode en de foutmarge vastleggen in `signature.py` en de tolerantie in
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
8800 geeft forfaitaire qv10-waarden per bouwperiode; geschaald op het landelijk gemiddelde geeft
dat per woning een verschillende A_inf. De exacte NTA 8800-tabel moet dan eerst met bron
vastgelegd worden.

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

## Kladbloknotitie 6: Het Windows-programma via GitHub Releases (TODO)

De workflow staat klaar ([`../../.github/workflows/release.yml`](../../.github/workflows/release.yml)):
een versietag bouwt een zip met GUI en CLI. Wacht op de publieke repo. Daarna een keer handmatig
testen op een schone Windows-machine zonder Python.
