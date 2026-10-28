# Herleidbaarheid van de woningkenmerken

Hoe makkelijk is een woning uit deze dataset terug te vinden met gegevens die online voor iedereen
beschikbaar zijn? Dit document toetst de woningkenmerken zoals ze nu openbaar zijn en geeft een
advies aan de **bronhouder** (de Smart Energy Foundation) en **KITE**. Beslissen over de publicatie
is aan hen.

**Strekking.** De analyse gaat over één soort aanvaller: iemand die de dataset naast openbare online
bronnen legt (de BAG, de 3D-BAG, EP-online, de KNMI-stationslijst en de bestuurlijke gebieden van
PDOK). **Niet** in de analyse:

- *insiders*: wie de woningen al uit eigen administratie of werk kent, zoals een corporatie,
  aannemer, installatiebedrijf, leverancier van het verwarmingssysteem, energieleverancier of
  netbeheerder;
- *waarneming ter plekke*: wie door een wijk rijdt of fietst en kijkt (buitenunits, zonnepanelen,
  glas).

Voor insiders staan in [Buiten deze analyse: insiders](#buiten-deze-analyse-insiders) een paar
algemene maatregelen die de bruikbaarheid van de dataset nauwelijks raken.

Getoetst met [AnonyMate](https://github.com/anonymate-nl/anonymate), versie `59ebc8a` (git-commit),
tegen de volledige Nederlandse woningvoorraad. AnonyMate is open source (EUPL-1.2). De eerste
versie van dit rapport (20-10-2026) gebruikte `9c59a48`; wat er sindsdien veranderd is, staat onder
[Gewijzigd op 24-10-2026](#gewijzigd-op-24-10-2026).

| | |
|---|---|
| dataset | 174 woningen: de kenmerken uit `household.csv` (via `homes.parquet`) plus het weerstation per woning uit `knmi.csv` |
| populatie | 8.388.265 woningen: BAG-verblijfsobjecten met woonfunctie, in gebruik |
| bronnen | BAG 31-08-2026 (PDOK `bag-light.gpkg`, ook de pandcontouren); EP-online totaalbestand, publicatie 01-09-2026; 3D-BAG v20250903; PDOK bestuurlijke gebieden 27-09-2026; KNMI-stations met temperatuurmeting |
| norm | k ≥ 11: elke woning lijkt op minstens 11 woningen in Nederland, dus hoogstens ongeveer 1 op 11 kans op heridentificatie |
| uitgevoerd | 24-09-2026, opnieuw op 24-10-2026; scripts en configuraties in [`herleidbaarheid/`](herleidbaarheid/) |

## Begrippen

- **QID** (quasi-identifier): een kenmerk dat een woning niet alleen aanwijst, maar in combinatie
  met andere wel (bouwjaar, oppervlak, ligging).
- **k**: op hoeveel woningen in Nederland lijkt deze rij? De kans op een juiste heridentificatie is 1/k.
- **Populatie**: de woningen waaruit de dataset kan komen. Wat publiek bekend is over werving en
  inclusie (achtergrondkennis) hoort in de afbakening.
- **Deelnameonthulling** (δ, *delta-presence*): welk deel van de gelijke woningen in de dataset
  zit. Dat is de kans dat een woning meedoet, ook als niet bekend is welke rij de hare is. k
  beschermt tegen *terugvinden*, δ tegen *aantonen dat iemand meedoet*. Zie
  [Deelnameonthulling](#deelnameonthulling-δ).
- **Staart**: de uiterste klasse van een kenmerk (zeer groot, zeer oud), waar weinig woningen in
  zitten.
- **BAG**: Basisregistratie Adressen en Gebouwen (Kadaster). **EP-online**: het register van
  energielabels (RVO). **KNMI**: het weerinstituut. **KITE**: Kennis- en Dataplatform Individuele
  Technieken (RVO).

## Werkwijze: eerst de norm, dan toetsen, dan afwegen

1. **De norm ligt vooraf vast**: k ≥ 11, de standaard van AnonyMate en dezelfde norm als bij de
   toetsen van andere openbare woningdatasets. Hij is niet aangepast aan de uitkomst. Bij de
   norm hoort ook de vraag of meedoen zelf gevoelig is; zo niet, dan wordt δ gemeld en vanaf 50%
   gemarkeerd, en beslist k (zie [Deelnameonthulling](#deelnameonthulling-δ)). Hoe gevoelig
   de uitkomst is voor een andere norm, staat onder [Gevoeligheid](#gevoeligheid-voor-de-norm).
2. **Toetsen tegen de populatie, niet tegen de dataset.** Per woning telt AnonyMate hoeveel
   woningen in heel Nederland dezelfde gepubliceerde kenmerken hebben (k).
3. **Afwegen** tussen grover publiceren (minder detail voor iedereen) en enkele woningen niet
   publiceren (minder woningen, mogelijk een vertekening). Zie [Advies](#advies).

## Wat de dataset per woning prijsgeeft

| kenmerk | kolom | wie kent het | detail |
|---|---|---|---|
| woningtype | `woningtype__cat` | iedereen (EP-online; anders afgeleid uit de BAG, zie [Kanttekeningen](#kanttekeningen)) | 5 typen |
| bouwjaar | `bouwjaar_klasse__cat` | iedereen (BAG) | klassen van 20 jaar, open staarten `<1900`, `2000=>` |
| oppervlakte | `oppervlak_klasse__cat` | iedereen (BAG) | klassen van 50 m², tot `500=>` |
| energielabel | `energielabel__cat` | iedereen (EP-online) | 101 van 174 ingevuld |
| **weerstation** | `station_code` in `knmi.csv` | iedereen (KNMI-stationslijst en BAG-ligging) | het dichtstbijzijnde van 25 stations: een **verborgen locatie** |
| glas | `heeft_dubbelglas__bool` | waarneming ter plekke | buiten deze analyse |
| isolatie (dak, muur, vloer) | `heeft_*isolatie__bool` | installateur, aannemer | buiten deze analyse |
| gas- en stroomjaarverbruik vóór installatie | `gas_voor_*`, `elektra_voor_*` | energieleverancier, netbeheerder | buiten deze analyse |
| meterstanden | `e_consumed_*`, `v_gas_consumed` in `dsmr.csv` | energieleverancier, netbeheerder | buiten deze analyse; zie [insiders](#buiten-deze-analyse-insiders) |

## Scenario's

| naam | wat de aanvaller gebruikt |
|---|---|
| s1 | woningtype, bouwjaar, oppervlakte, label, **zonder** weerstation (om de bijdrage van het station te zien) |
| **s2** | idem **met weerstation**: de dataset zoals hij nu is |
| s2c | idem, maar het energielabel weggelaten (de aanvaller laat het minst betrouwbare kenmerk weg) |
| s2b | het **advies**: de staarten samengevoegd (oppervlakte ≥ 250 m², bouwjaar < 1940) |

## Uitkomst voor de dataset zoals hij nu openbaar is

Aantallen woningen (van 174); een woning haalt de norm als k ≥ 11.

| scenario | haalt de norm | te herleidbaar (k < 11) | k mediaan |
|---|---:|---:|---:|
| s1, zonder weerstation | 174 (100%) | 0 | 20.259 |
| **s2, de dataset zoals hij nu is** | **167 (96%)** | **6, plus 1 zonder match** | 776 |
| s2c, zonder label | 173 (99%) | 1, met k = 5 | 2.499 |

### Bevindingen

1. **Zonder locatie zijn de woningkenmerken ruim anoniem.** Klassen van 20 jaar en 50 m² zijn grof
   genoeg: elke woning lijkt op minstens 76 andere in Nederland, mediaan 20 duizend.
2. **Het weerstation verkleint de groep gelijke woningen het sterkst.** Het verkleint de populatie
   van 8,4 miljoen tot het gebied van één station: van ruim 2 duizend woningen op de kleinste
   eilandstations tot 875 duizend rond Rotterdam. Te herleidbaar zijn de **staarten**: grote
   (≥ 250 m²) en oude (< 1940) vrijstaande en twee-onder-een-kapwoningen. Zelfs in grote
   stationsgebieden zijn die zeldzaam: er blijven er 2 tot 10 over.
3. **"Geen match" is geen veiligheid.** Eén woning ligt in een klein stationsgebied en past daar
   niet bij het energielabel in het register. De toets telt letterlijk, vindt met alle vier de
   kenmerken niets, en meldt "geen match". Een aanvaller laat het minst betrouwbare kenmerk weg, en
   een label verandert vaker dan een bouwjaar: zonder label (s2c) passen er 5 woningen bij (k = 5).
   Grover maken helpt hier niet, omdat het stationsgebied te klein is; vandaar advies 2. Of het
   de deelnemer is, kan alleen de bronhouder controleren (zie de
   [bijlage](#bijlage-voor-de-bronhouder)).

## Advies

Twee wijzigingen aan de publicatie, en een algemene regel. Het weerstation blijft staan: dat is
voor warmtevraaganalyse het waardevolste kenmerk.

1. **Voeg alleen de staarten samen**: oppervlakte ≥ 250 m² als één klasse, bouwjaar < 1940 als één
   klasse. De rest van de klassen blijft zoals hij is.
2. **Publiceer de woning onder bevinding 3 niet**, of geef haar het dichtstbijzijnde weerstation op
   het vasteland.
3. **Publiceer één versie.** Laat de huidige versie niet naast een nieuwe staan: wie beide heeft,
   legt de klassen over elkaar en krijgt smallere klassen dan elk van beide. Toets een nieuwe
   versie voordat hij verschijnt.

Getoetst met dezelfde norm:

| scenario | haalt de norm | niet te publiceren |
|---|---:|---:|
| s2b, advies | 173 (99%) | 1 (bevinding 3) |

### Representativiteit: vertekent het weglaten de dataset?

Weglaten is niet willekeurig: de toets haalt juist grote, oude, afgelegen woningen weg, vaak met
een hoog verbruik. Per kenmerk de afstand tussen de hele dataset en het gepubliceerde deel: de
totale-variatieafstand (TVD, het aandeel woningen dat van klasse zou moeten wisselen om de
verdelingen gelijk te maken) en, voor het verbruik, het gestandaardiseerde verschil in gemiddelde
(SMD). Ter vergelijking de TVD die je in 95% van de gevallen onderschrijdt als je **willekeurig**
evenveel woningen weglaat.

| | huidige publicatie, s2 | advies, s2b |
|---|---:|---:|
| weggelaten | 7 | 1 |
| TVD woningtype (toeval 95%) | 0,008 (0,018) | 0,004 (0,006) |
| TVD bouwjaar (toeval 95%) | **0,026** (0,022) | 0,004 (0,006) |
| TVD oppervlakte (toeval 95%) | **0,024** (0,022) | 0,004 (0,006) |
| TVD energielabel (toeval 95%) | **0,026** (0,020) | 0,004 (0,006) |
| TVD weerstation (toeval 95%) | 0,033 (0,032) | 0,006 (0,006) |
| SMD gasverbruik jaar 1 | −0,068 | 0,003 |
| SMD stroomverbruik jaar 1 | −0,017 | 0,002 |

Lezen:

- **Alleen weglaten, zonder grover te publiceren** (de huidige klassen, 7 woningen weg), vertekent
  bouwjaar, oppervlakte en label meer dan toeval, en verlaagt het gemiddelde gasverbruik merkbaar
  (SMD −0,07): precies de grote, oude woningen verdwijnen.
- **Met de staarten samengevoegd** (s2b) is de vertekening verwaarloosbaar: de woningen blijven in
  de dataset, alleen minder gedetailleerd.

Met 174 woningen is de onzekerheid groot; de maat laat vooral zien dat grover publiceren hier
minder vertekent dan weglaten.

### Gevoeligheid voor de norm

| variant | haalt de norm |
|---|---:|
| s2b met k ≥ 20 (de strengste norm in AnonyMate) | 172 (99%) |
| s2 met k ≥ 5 | 171 (98%) |
| s2, woningen zonder geregistreerd label tellen mee als mogelijke match | 173 (99%) |

### Deelnameonthulling (δ)

Hoe erg het is als bekend wordt *dát* een woning meedoet, hangt af van wat meedoen verraadt: een
meetkastje in een project dat al in de krant stond weinig, een subsidie of een regeling voor lage
inkomens meer. Dat kan alleen de bronhouder beoordelen. AnonyMate laat daarom bij de norm kiezen:

- **meedoen is niet gevoelig, of al bekend** (standaard): δ wordt gemeld en gemarkeerd vanaf 50%,
  waar meedoen minstens zo waarschijnlijk is als niet meedoen; een woning wordt alleen op k
  beoordeeld;
- **meedoen is zelf gevoelig:** dan moet ook δ ≤ 9% gelden (δ ≤ p, dezelfde grens als voor k).

Voor de huidige versie scheelt die keuze één woning; met het advies maakt ze niets uit:

| scenario | δ ≥ 50% (gemarkeerd) | δ > 9% | daarvan met k ≥ 11 | δ maximaal |
|---|---:|---:|---:|---:|
| s1, zonder weerstation | 0 | 0 | 0 | 1% |
| s2, de dataset zoals hij nu is | 1 | 7 | 1 | 50% |
| s2c, zonder label | 0 | 1 | 0 | 20% |
| s2b, advies | 0 | 0 | 0 | 8% |

Op één na heeft elke woning met een hoge δ ook een te kleine k, en staat dus al bij de woningen die
de norm niet halen. Die ene haalt k wel, maar meer dan 9% van de gelijke woningen doet mee. Is
meedoen gevoelig, dan halen in de huidige versie 166 woningen de norm in plaats van 167. Met het
advies (s2b) blijft δ overal onder 9%, ook onder de strenge keuze. De vraag of meedoen in dit
project gevoelig is, hoeft voor het advies dus niet beantwoord te worden; voor een volgende versie
of een uitbreiding van de dataset wel.

### Aanvulling: het weer via een H3-cel met ruis in plaats van via het weerstation

Het weerstation verkleint de groep het sterkst. Als de weerkoppeling om een andere reden toch
herzien wordt (de weerreeksen zelf kloppen, op de uurlabeling na, maar of elke woning aan het goede
station hangt is zonder de adressen niet te controleren), is er een alternatief dat veel minder
prijsgeeft: het weer geospatiaal interpoleren op het middelpunt van een **H3-cel van niveau 4**
(een zeshoek van ~1.800 km²), en die cel bepalen **na een paar kilometer willekeurige ruis** op de
woninglocatie.

Verwacht aantal woningen dat de norm niet haalt (k < 11), van 174 (script:
[`herleidbaarheid/weerlocatie_alternatieven.py`](herleidbaarheid/weerlocatie_alternatieven.py)):

| weerlocatie in de publicatie | verwacht | ter controle: werkelijk |
|---|---:|---:|
| dichtstbijzijnd weerstation (zoals nu) | 5,0 | 3, plus 1 zonder match |
| H3-cel niveau 4, zonder ruis | 5,5 | |
| H3-cel niveau 4, met 5-10 km ruis | **0,2** | |

Omdat de adressen niet bekend zijn, is dit een verwachting: een woning ligt met een kans evenredig
aan het aantal passende woningen in een gebied, en telt als risico waar er minder dan 11 passen. De
controle op de weerstations, waarvan de uitkomst wel bekend is, laat zien dat de schatting eerder
iets te streng is.

**Waarom de ruis het verschil maakt.** Zonder ruis is een H3-cel van niveau 4 ongeveer even precies
als het gebied van een weerstation, dus winst is er dan niet. Met ruis wijst de gepubliceerde cel
de woning niet meer aan: ze kan ook in een van de zes buurcellen liggen. Een aanvaller moet dan in
zeven cellen zoeken in plaats van één, en daar staan in de mediaan zeven keer zoveel woningen; bij
de kust, het IJsselmeer of een stadsrand soms meer dan honderd keer zoveel. De zeldzame woningen
(groot, oud, vrijstaand) zijn dan niet meer zeldzaam. (De telling met alle buurcellen is een
bovengrens voor het effect van 5-10 km ruis.)

**Wat het kost voor het weer.** Het weer wordt geïnterpoleerd op het middelpunt van de cel die na
de ruis gekozen is, niet op de woning. Voor een steekproef van 100.000 eengezinswoningen:

| weerpunt | afstand tot de woning: mediaan | P90 | maximum |
|---|---:|---:|---:|
| dichtstbijzijnd KNMI-station (zoals nu) | 14 km | 23 km | 37 km |
| middelpunt eigen H3-cel, zonder ruis | 16 km | 21 km | 25 km |
| middelpunt H3-cel na ruis, σ = 5 km | 17 km | 25 km | 42 km |
| middelpunt H3-cel na ruis, σ = 10 km | 19 km | 31 km | 62 km |

Met σ = 5 km belandt 20% van de woningen in een buurcel, met σ = 10 km 37%. Het weerpunt komt dus
iets verder van de woning te liggen dan nu, maar het is dan een interpolatie tussen stations in
plaats van één station.

**Maar: wat al openbaar is, blijft openbaar.** De stationscodes staan al in de gepubliceerde
dataset en kunnen gekopieerd zijn. Een nieuwe versie met H3-cel en ruis beschermt alleen als ze de
oude vervangt, en niet tegen wie de oude al heeft. Twee versies naast elkaar zijn slechter dan elk
apart: wie beide heeft, snijdt het stationsgebied met de cel en haar buren, en houdt een kleiner
gebied over.

## Buiten deze analyse: insiders

Wie een woning al uit eigen administratie of werk kent, zit niet in de analyse hierboven. Voor
sommige insiders kan een kenmerk dat alleen zij kennen (het jaarverbruik voor de energieleverancier,
de isolatie voor de aannemer) toch een sleutel zijn. Een paar maatregelen kosten vrijwel geen
bruikbaarheid:

- **Verschillen per interval in plaats van meterstanden**, zo dat de verschillen optellen tot de
  juiste totalen over langere perioden, ook over gaten in de reeks heen. Een meterstand is een getal
  dat de netbeheerder of leverancier zelf ook heeft; een verschil per interval bevat dezelfde
  informatie voor analyse. De meterstanden in `dsmr.csv` zijn nu cumulatief.
- **Geen nummers uit andere systemen:** geen EAN-codes, meternummers of serienummers.
- **Geen codes die ook elders voorkomen:** woningcodes die niet terugkomen in een andere dataset of
  een eerdere versie.

Voor andere kenmerken die alleen insiders kennen, zoals het jaarverbruik vóór installatie of de
isolatie, is afronden of weglaten niet vanzelf beter: voor onderzoekers zijn juist die gegevens
vaak waardevol. Dat is een afweging voor de bronhouder tussen het nut voor onderzoek en het risico
bij insiders. Deze analyse doet daar geen uitspraak over.

## Bijlage voor de bronhouder

Voor elke woning die de norm niet haalt in de dataset zoals hij nu openbaar is (s2 en s2c): de
woningen in de BAG die bij alle gepubliceerde registerkenmerken passen, met adres en BAG-ID. Dat
zijn 7 woningen met samen 43 kandidaat-adressen.

**Deze bijlage staat niet in deze repo en wordt niet gepubliceerd**: wie haar heeft, hoeft maar een
handvol adressen af te gaan. Ze wordt alleen aan de bronhouder en KITE gegeven. Zij kennen de
adressen van de deelnemers en kunnen controleren:

- **Zit de deelnemende woning er echt tussen?** Zo niet, dan wijkt de eigen opgave van de
  deelnemer af van het register, en is het risico voor die woning kleiner dan hier berekend.
- **Hoeveel kandidaten zijn er echt?** Een kandidaat die geen woning meer is, of in werkelijkheid
  een ander type, telt niet mee.

Daarna is het aan hen om te beslissen of gegevens aangepast of verwijderd moeten worden.

Opnieuw maken: [`herleidbaarheid/draai.sh`](herleidbaarheid/draai.sh) schrijft de bijlage naar
`data/analyse/herleidbaarheid/v<versie>/bijlage_NIET_PUBLICEREN/`, als CSV en Parquet.

## Kanttekeningen

- **Deelnameonthulling (δ)** is geteld volgens de keuze die AnonyMate sinds 18-10-2026 bij de
  norm biedt (melden en markeren vanaf 50%, of δ ≤ p). Of meedoen in dit project gevoelig is, is
  aan de bronhouder; voor het advies maakt het niets uit.
- **Het woningtype in de registers.** Heeft een woning een energielabel, dan geldt het woningtype
  uit EP-online. Zo niet, dan leidt AnonyMate het af uit de pandcontouren van de BAG, zoals een
  aanvaller dat ook kan: de panden met een woning waarmee ze een muur deelt, en de grootte van het
  blok (geen buren: vrijstaand; een blok van twee: twee-onder-een-kap; het eind van een rij:
  hoekwoning; daartussen: tussenwoning). In twee proefgebieden klopt dat in 90 à 91% met EP-online,
  het minst bij twee-onder-een-kap (ongeveer 60%). De toets rekent alsof het type klopt; dat is
  voorzichtig, want een aanvaller die zich vergist, zoekt in de verkeerde groep.
- **Eigen opgave tegenover register.** De kenmerken zijn door de deelnemers opgegeven en kunnen
  afwijken van BAG en EP-online. De toets telt tegen de registers.
- **Woningen zonder label.** 37% van de woningvoorraad heeft geen geldig label. Standaard tellen
  die niet mee als mogelijke match (de strengste lezing); laat je ze wel meetellen, dan haalt alles
  de norm. De werkelijke aanvaller zit daartussen.
- **Stationsindeling.** De toets wijst elke woning toe aan het dichtstbijzijnde KNMI-station dat
  temperatuur meet. De indeling in de dataset kan daarvan afwijken; alle 25 stations uit de dataset
  komen wel in de toewijzing voor.
- **De tijdreeksen zelf zijn niet getoetst.**

## Gewijzigd op 24-10-2026

De eerste versie van dit rapport (20-10-2026) rekende met een populatie waarin twee fouten in het
woningtype zaten, allebei in AnonyMate. Het gecombineerde EP-online-type "Twee-onder-een-kap /
rijwoning hoek" telde altijd als twee-onder-een-kap, ook als het subtype "Rijwoning" zei (ruim
300.000 labels van hoekwoningen), en "Twee-onder-één-kap" met accenten (241.000 labels) werd niet
herkend. En woningen zonder label hadden geen woningtype, en telden standaard niet mee als
mogelijke match. Beide zijn hersteld in AnonyMate `59ebc8a`; het woningtype zonder label komt nu
uit de vorm (zie [Kanttekeningen](#kanttekeningen)). Alle scenario's zijn opnieuw gedraaid, met
dezelfde BAG en EP-online als eerst, en ook de representativiteit en de weerlocatie-alternatieven.

| | 20-10-2026 | 24-10-2026 |
|---|---:|---:|
| s2: haalt de norm | 166 | 167 |
| s2: te herleidbaar | 7, plus 1 zonder match | 6, plus 1 zonder match |
| s2: extra af als meedoen gevoelig is | 0 | 1 |
| s2c (zonder label): k van de woning onder bevinding 3 | 1 | 5 |
| s2b (advies): haalt de norm | 173 | 173 |

Geen woning die eerst de norm haalde, haalt hem nu niet. Het advies blijft hetzelfde.

## Hertoets met een nieuwere AnonyMate (10-10-2026)

Alle scenario's zijn op 10-10-2026 herhaald met AnonyMate `4e55ae0` (onder meer met de controle
op klassegrenzen en afgeronde waarden). Het aantal woningen dat de norm haalt, was voor elk
scenario gelijk aan dat van de eerste versie; de nieuwere versie noemt nu ook k minimaal en mediaan (voor s2
3 en 585, voor het advies s2b 12 en 712). Nieuw is alleen de melding dat er tussen de
oppervlakteklassen `400-449` en `>=500` een klasse ontbreekt: er zitten geen woningen van 450 tot
499 m² in de dataset. Dat verandert niets.

## Reproduceren

```bash
git clone https://github.com/anonymate-nl/anonymate && git -C anonymate checkout 59ebc8a
pip install -e ./anonymate
anonymate ingest all               # BAG, EP-online (API-sleutel nodig), gebieden, KNMI
anonymate ingest 3dbag             # optioneel voor deze toets; ~20 GB
anonymate build
bash docs/herleidbaarheid/draai.sh 59ebc8a
```

`ingest` en `build` halen de registers één keer op en bouwen de populatie (enkele uren, een paar
GB); daarna is de toets offline en duurt hij enkele minuten. `draai.sh` draait ook scenario's met
kenmerken die alleen ter plekke of door insiders te kennen zijn; die horen niet bij deze analyse.

## Melding

De licentie van de dataset vraagt gebruik, rekenmethoden en conclusies te melden via het KITE-portaal
of via data@demoprojecthybride.nl. Deze toets valt daaronder.
