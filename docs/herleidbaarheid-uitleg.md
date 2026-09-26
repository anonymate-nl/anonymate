# Herleidbaarheid van woning- en energiedata: een uitleg

Voor wie een dataset over woningen en hun energiegebruik openbaar wil maken, en wil begrijpen
waarom "de adressen eruit halen" niet genoeg is. Dit document legt uit wat herleidbaarheid is, hoe
anonymate het meet, en wat er bijzonder is aan woningdata in Nederland: bijna alles wat je over een
woning publiceert, staat ook per adres in een openbaar register. De cijfers komen uit toetsen met
anonymate tegen de volledige woningvoorraad (BAG en EP-online van september 2026).

## 1. Waarom adressen weghalen niet genoeg is

Een dataset zonder namen en adressen lijkt anoniem. Maar elke rij beschrijft nog steeds één
woning: een vrijstaand huis uit 1932, 260 m², label C, in de omgeving van weerstation Eelde. Wie
dezelfde kenmerken voor alle woningen in Nederland kan opzoeken, telt hoeveel woningen daarop
passen. Is dat er één, dan is de rij herleid, zonder dat er ooit een adres in stond.

* **Directe identificatoren** wijzen een woning rechtstreeks aan: adres, postcode met huisnummer,
  BAG-ID, EAN-code van de meter. Die haal je altijd weg.
* **Quasi-identificatoren** wijzen niets aan, maar doen dat wel in combinatie: bouwjaar,
  oppervlakte, woningtype, energielabel, ligging. Ze zijn meestal ook precies waarom de dataset
  interessant is, dus weglaten kost bruikbaarheid.

## 2. Hoe je herleidbaarheid meet

**k: op hoeveel woningen lijkt deze rij?** Tel in de hele populatie (alle woningen in Nederland,
of het deel dat aan de publiek bekende inclusiecriteria voldoet) hoeveel woningen dezelfde
gepubliceerde kenmerken hebben. Een aanvaller die weet welke woning hij zoekt, heeft dan hoogstens
1 op k kans. Dit heet **k-map**. Het verschil met de bekendere k-anonimiteit: die telt binnen de
dataset zelf, en onderschat het risico voor kleine datasets enorm, omdat daar bijna elke rij uniek
is terwijl er in Nederland honderden gelijke woningen kunnen zijn. Andersom kan een rij die in de
dataset veel gelijken heeft, in Nederland toch zeldzaam zijn.

**δ: welk deel van de gelijke woningen zit in de dataset?** Als van de 12 woningen die op een rij
lijken er 6 in de dataset zitten, weet een aanvaller met 50% kans dat een bepaalde woning
deelneemt, ook zonder te weten welke rij de hare is. Dit heet **δ-presence**.

**De norm: kies p vooraf.** p is de hoogste kans op heridentificatie die je aanvaardbaar vindt;
de bijbehorende k is round(1/p). In de praktijk:

| p | k ≥ | waar gebruikt |
|---|---:|---|
| 0,33 | 3 | ondergrens in de medische praktijk, bij gecontroleerde toegang |
| 0,20 | 5 | idem, iets strenger |
| 0,10 | 10 | netbeheerders publiceren het standaardjaarverbruik per PC6 alleen als er minstens 10 woningen in zitten; anders voegen ze postcodes samen |
| **0,09** | **11** | standaard van anonymate |
| 0,05 | 20 | streng, bij openbare publicatie van gevoelige gegevens |

(De medische drempels komen uit El Emam & Arbuckle, *Anonymizing health data*, 2013.) Leg de norm
vast **voordat** je uitkomsten ziet, en pas hem niet aan op de uitkomst: dat is ethisch en juridisch
de juiste volgorde. Afwegen gebeurt daarna, binnen de norm.

## 3. Wie is de aanvaller?

| aanvaller | kent | voorbeeld |
|---|---|---|
| **register** | wat per adres in openbare registers staat | iedereen met de BAG, EP-online, 3D-BAG |
| **zichtbaar** | + wat je van buiten ziet | buren, Street View: zonnepanelen, dubbel glas, een buitenunit |
| **insider** | + wat een partij uit eigen administratie weet | energieleverancier, netbeheerder, installateur, thermostaatleverancier |

Een dataset kan anoniem zijn voor de eerste en volstrekt niet voor de derde. Toets voor elke
aanvaller die realistisch is.

## 4. Woningregisters: wat iedereen per adres kan opzoeken

In Nederland is over elke woning veel openbaar, per adres en voor iedereen:

* **BAG** (Kadaster): bouwjaar, gebruiksoppervlakte, ligging (coördinaten), het pand en het aantal
  woningen erin.
* **EP-online** (RVO): het energielabel, het woningtype, en bij labels volgens NTA 8800 ook de
  warmtebehoefte, de compactheid en de gebruiksoppervlakte van de thermische zone.
* **3D-BAG** (TU Delft): de schil van het pand: gevel-, dak- en grondoppervlak, hoogte, dakvorm.

Alles wat een dataset over deze kenmerken publiceert, is dus te koppelen. Klassen helpen: bouwjaar
in klassen van 20 jaar en oppervlakte per 50 m² maken de meeste woningen al ruim anoniem, zolang er
geen locatie bij staat. De **staarten** blijven lastig: grote, oude, vrijstaande woningen zijn
zeldzaam, dus voeg de uiterste klassen samen (bijvoorbeeld "250 m² en meer", "vóór 1940").

## 5. Verborgen locatie

Een dataset zonder adres heeft vaak toch een locatie, verstopt in iets anders: de weergegevens.

**Het dichtstbijzijnde weerstation** wijst het gebied rond één van de ruim dertig KNMI-stations
aan. Dat verkleint de populatie van miljoenen woningen tot tienduizenden, en rond een eilandstation
tot een paar duizend. Precies daar worden de staarten herkenbaar.

**Een H3-cel met ruis.** Beter is het weer te interpoleren op het middelpunt van een zeshoek van
een vast raster (H3), en die zeshoek te kiezen **nadat** er een paar kilometer willekeurige ruis op
de woninglocatie is gezet. Het effect hangt helemaal van die ruis af:

* **Zonder ruis** is een zeshoek van niveau 4 (~1.800 km²) ongeveer even precies als het gebied van
  een weerstation. Winst is er dan niet.
* **Met ruis** kan de woning ook in een van de zes buurzeshoeken liggen. Een aanvaller moet dan in
  zeven zeshoeken tegelijk zoeken. Daar staan in de mediaan **7 keer** zoveel woningen (P10-P90:
  4 tot 21 keer); langs de kust, het IJsselmeer of een stadsrand soms **meer dan 100 keer** (het
  uiterste in Noord-Holland: van 2.652 naar 394.755 woningen). Zeldzame woningen zijn dan
  niet meer zeldzaam.

Wat het kost voor het weer (steekproef van eengezinswoningen; verschil in uurwaarden tussen
KNMI-stations als functie van de afstand, stookseizoen 2023/2024):

| weerpunt | afstand tot de woning (mediaan) | fout in temperatuur (mediaan) |
|---|---:|---:|
| dichtstbijzijnd station | 14 km | 0,7 °C |
| middelpunt H3-cel niveau 4, met 5-10 km ruis | 17-19 km | 0,8 °C |
| middelpunt H3-cel niveau 5, met 5-10 km ruis | 8-13 km | 0,4-0,6 °C |

**Kleiner (niveau 5, ~250 km²) alleen met ruis.** Zonder ruis kost niveau 5 veel privacy: met
weerzone, type, label en een afgeronde signatuur valt landelijk 10% van de eengezinswoningen in een
te kleine groep, tegen 3% op niveau 4. Met ruis is dat verschil grotendeels weg, en ligt het
weerpunt dichter bij de woning dan nu.

## 6. Berekende grootheden: de rainbow table

Veel datasets publiceren niet alleen metingen, maar ook iets wat uit openbare gegevens berekend is,
bijvoorbeeld een warmteprestatiesignatuur uit het adres (zie
[`warmteprestatiesignatuur.md`](warmteprestatiesignatuur.md)). Als het algoritme openbaar is, kan
een aanvaller die waarde voor **elke** woning in Nederland uitrekenen: een rainbow table. De
gepubliceerde waarde is dan geen schatting maar een exacte sleutel; de echte woning zit altijd in
het vakje met de gepubliceerde, afgeronde waarde. Afronden is dan de enige bescherming, en de toets
telt precies die vakjes.

**Twee bronnen voor hetzelfde kenmerk zijn een extra sleutel.** Het gebruiksoppervlak staat twee
keer in openbare registers: in de BAG (het verblijfsobject) en in EP-online (de thermische zone
van het label). Die verschillen vaak:

| eengezinswoningen met een NTA 8800-label (1,47 miljoen) | |
|---|---:|
| labeloppervlak precies gelijk aan BAG (± 0,5 m²) | 8,5% |
| meer dan 15% verschil | 17,5% |
| meer dan 30% verschil | 4,2% |
| vrijstaande woningen: label meer dan 15% kleiner | 31% |

Het label is meestal kleiner, met een piek bij 5 tot 15 m² minder. Dat past bij een aangebouwde
garage of berging, die de BAG meetelt en het label niet (buiten de thermische schil). Andere
oorzaken: verbouwingen die in het ene register wel en in het andere nog niet staan, labels van een
referentiegebouw, en fouten ergens in de keten.

Voor een aanvaller is dat verschil een extra kenmerk, want hij kan het voor elke woning
uitrekenen. Met weerzone, woningtype, bouwjaar (20 jaar) en oppervlakte (50 m²) valt landelijk 1%
van deze woningen in een te kleine groep; met de verhouding label/BAG erbij (in klassen van 10%)
**6%**; met ook het label **18%**. Publiceer daarom geen grootheid die van het labeloppervlak afhangt
naast een oppervlakteklasse uit de BAG, of toets het expliciet.

## 7. Energiedata

* **Jaarverbruik** van vóór een ingreep is voor de energieleverancier en de netbeheerder vrijwel
  uniek per woning, ook afgerond. Publiceer het niet, of alleen als verhouding (na/voor).
* **Absolute meterstanden** zijn voor wie de meter uitleest een rechtstreekse sleutel naar het
  adres, los van alle woningkenmerken. Publiceer verbruik per interval, niet de stand: dat bevat
  dezelfde informatie voor analyse, maar geen sleutel.
* **Tijdreeksen** (stroom, gas, binnentemperatuur per kwartier) zijn voor een insider een
  vingerafdruk: de netbeheerder heeft dezelfde reeks. Daar helpt geen generalisatie van
  woningkenmerken tegen; het is een afweging die buiten deze tool valt.

## 8. Eigen opgave tegenover register

Kenmerken in onderzoeksdatasets komen vaak uit een enquête of intake, niet uit het register. Ze
kunnen afwijken: een ander woningtype, een ouder label. De toets telt dan "geen match": met alle
gepubliceerde kenmerken past er geen enkele woning. Dat is **geen veiligheid**. Een aanvaller die
niets vindt, laat het minst betrouwbare kenmerk weg; blijven er dan één of twee woningen over, dan is
de rij toch herleid. Toets daarom ook met de kenmerken zoals ze in het register staan, en behandel
een afwijkende opgave als een kenmerk dat een aanvaller mag negeren.

## 9. Afwegen: grover maken of weglaten

Binnen de norm zijn er twee knoppen:

* **Grover maken** (klassen, afronden, een grotere zeshoek, ruis) kost detail voor iedereen, maar
  houdt alle woningen in de dataset.
* **Woningen niet publiceren** kost geen detail, maar is niet willekeurig: de toets haalt juist de
  staarten weg (groot, oud, afgelegen), vaak ook de woningen met het hoogste verbruik. De dataset
  kan daardoor vertekenen. Grover maken van alleen de staarten vertekent meestal minder dan
  weglaten.

anonymate zoekt met `suggest` welke generalisaties de meeste woningen publiceerbaar maken tegen het
kleinste informatieverlies, en het rapport vermeldt hoeveel en welke woningen niet te publiceren
zijn.

## 10. Wat anonymate niet doet

* Het toetst **tabellen met kenmerken**, niet tijdreeksen.
* Kenmerken zonder volledig register (dubbel glas, jaarverbruik) worden **geschat** uit de dataset
  zelf, onder de aanname dat ze onafhankelijk zijn; dat is meestal te streng.
* Het woningtype staat in de populatie alleen voor woningen met een label; zie het
  [kladblok](werk/KLADBLOK.md) voor dit en andere open punten.
* Het is een **hulpmiddel bij een afweging**, geen juridisch oordeel. De norm en de keuzes blijven
  bij wie publiceert.
