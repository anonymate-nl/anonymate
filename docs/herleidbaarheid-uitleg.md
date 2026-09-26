# Herleidbaarheid van woning- en energiedata: een uitleg

Voor wie een dataset over woningen en hun energiegebruik openbaar wil maken, en wil begrijpen
waarom "de adressen eruit halen" niet genoeg is. Dit document legt uit wat herleidbaarheid is, hoe
anonymate het meet, en wat er bijzonder is aan woningdata in Nederland: bijna alles wat je over een
woning publiceert, staat ook per adres in een openbaar register. De cijfers komen uit toetsen met
anonymate tegen de volledige woningvoorraad (BAG en EP-online van september 2026). anonymate
bouwt voort op werk aan monitoringdata van woningen bij het Lectoraat Energietransitie van
Hogeschool Windesheim (*NeedForHeat AnonyMate*).

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

**In bits: Shannon-entropie.** k zegt iets over één woning; bits maken kenmerken onderling
vergelijkbaar en optelbaar. Om één woning aan te wijzen tussen N gelijke kandidaten zijn log2(N)
ja/nee-vragen nodig, zoals bij *Wie is het?*: 23 bits voor de ruim 8 miljoen Nederlandse woningen,
22 bits voor de 5 miljoen eengezinswoningen van 50 tot 250 m². Elk gepubliceerd kenmerk
beantwoordt een deel van die vragen. Hoeveel, is de **Shannon-entropie** van de gepubliceerde
waarden over de populatie:

> H = −Σ p_g · log2(p_g), met p_g het aandeel woningen in groep g (alle woningen met dezelfde
> gepubliceerde waarden).

Wat overblijft is het gemiddelde van log2(k) over de woningen, en samen tellen ze op tot log2(N):
elke bit die je publiceert, is een bit minder te gaan. Drie dingen maken bits handig:

* **Vergelijken.** Een kenmerk dat een groep 7 keer groter maakt, voegt log2(7) = 2,8 bits
  bescherming toe, waar het ook in de dataset zit.
* **Toevoegen.** Wat een extra kenmerk kost, is het verschil in onthulde bits met en zonder dat
  kenmerk: het deel van de informatie dat de andere kenmerken nog niet gaven. Zo blijkt of twee
  kenmerken hetzelfde vertellen (weerzone en gemeente) of elkaar aanvullen.
* **De norm.** k ≥ 11 betekent ten minste log2(11) = 3,5 bits te gaan, voor élke woning. Een
  gemiddelde van 6 bits zegt dus nog niet dat de norm gehaald is: entropie is een gemiddelde, de
  norm een ondergrens. Daarom rapporteert anonymate beide: bits voor het begrip, k voor de toets.

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
  uiterste in Noord-Holland: van 2.652 naar 394.755 woningen). In bits: de ruis geeft in de
  mediaan log2(7) = 2,8 bits bescherming terug, en tot 7,2 bits. Zeldzame woningen zijn dan niet
  meer zeldzaam.

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

**Het stedelijk hitte-eiland: in de berekening wel, als kolom niet.** In de stad is het warmer
dan op het weerstation (volgens de RIVM-kaart per postcode 0,8 °C in de mediaan, bij 10% van de eengezinswoningen meer dan 1,5 °C). Een model dat de
warmteprestatie leert met stationsweer, ziet in de stad een kleiner temperatuurverschil dan er
werkelijk is en vindt een te lage warmteverliescoëfficiënt. Het is voor onderzoek dus verleidelijk
om het hitte-eiland (UHI) mee te nemen. Hoe je dat doet, maakt voor de privacy alles uit
(eengezinswoningen van 50 tot 250 m² met label; gepubliceerd: weerzone, type, label en een
signatuur afgerond op 100 W/K en 5.000 kJ/K):

| opzet | in een groep < 11 | bits onthuld |
|---|---:|---:|
| geen UHI | 2,9% | 12,2 |
| UHI verwerkt in het leren én in de adres-signatuur | 2,9% | 12,2 |
| idem, plus UHI als kolom op 1 °C | 5,7% | 13,1 |
| idem, plus UHI als kolom op 0,5 °C | 8,1% | 13,8 |
| idem, plus UHI als kolom op 0,1 °C | 20,8% | 15,8 |

* **Verwerkt in de berekening kost het niets.** Leert het model met lokaal weer (station plus UHI),
  dan vindt het de werkelijke warmteverliescoëfficiënt, en die berekent de aanvaller ook uit het
  adres. UHI zit in geen van beide als los getal.
* **Als eigen kolom is het een locatiewijzer.** Binnen een weerzone verschilt het hitte-eiland per
  postcode (spreiding 0,4 °C), en een fijne UHI-waarde wijst dus een wijk aan. Zelfs op 1 °C
  verdubbelt het aandeel te kleine groepen. Hetzelfde geldt voor een gepubliceerde **lokale
  weerreeks** (station plus UHI): het verschil met het station onthult de UHI-waarde exact.
* **Wat afronden aan precisie kost**, is klein: op 0,25 °C blijft 98% van de variatie over (fout in
  de signatuur 0,5%), op 0,5 °C 92% (1,1%), op 1 °C 77% (2,1%). Een gemiddelde per weerzone houdt
  maar 23% over. Maar ook de grove varianten kosten privacy; de veilige weg is de correctie door de
  dataverstrekker laten doen, vóór publicatie.

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
**6%**; met ook het label **18%**. In bits: de verhouding onthult 1,8 bits extra (van 9,9 naar
11,7), ongeveer evenveel als het label zelf (2,2 bits), en samen 3,9 bits. Publiceer daarom geen grootheid die van het labeloppervlak afhangt
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

## 10. Transparantie en privacy

Wie onderzoek doet, wil dat anderen de resultaten kunnen narekenen. Wie publiceert, moet de
deelnemers beschermen. Dat lijkt te botsen: moet je niet elke waarde per woning publiceren, tot
en met de hitte-eilandwaarde waarmee het weer is gecorrigeerd, om reproduceerbaar te zijn? Nee;
de spanning is echt, maar kleiner dan hij lijkt, omdat reproduceerbaar niet hetzelfde is als
elke waarde per woning voor iedereen inzichtelijk.

**Wees transparant over het mechanisme, niet over elke waarde.** Publiceer de code, de bronnen
en elke bewerking: welke UHI-kaart, welke aggregatie, hoe die in het weer is verwerkt, welke
afrondstap, welke ruis. Een openbare kaart hoef je niet per woning te herhalen: wie het adres
heeft, rekent de waarde exact na; wie het niet heeft, kan er niets mee. Let wel op dat twee
gepubliceerde varianten samen niet onthullen wat elk apart verbergt: een warmteverliescoëfficiënt
geleerd met stationsweer én een met lokaal weer geven samen de UHI-waarde exact.

**Afronden is een resolutie, geen verzwijgen,** mits je de stap en de reden vermeldt. Afronden
op stap s geeft een fout van s/√12 (RMS). Voor een signatuur op 100 W/K is dat 29 W/K, 13% van de
mediaan (226 W/K voor eengezinswoningen); voor de warmtecapaciteit op 5.000 kJ/K 1.400 kJ/K, 12%
van de mediaan. Zet dat naast de onzekerheid van de waarde zelf: ligt die in dezelfde orde of
hoger, dan verlies je met afronden weinig wetenschappelijke informatie; is hij veel kleiner, zoek
dan een andere route. Dataminimalisatie is bovendien geen keuze maar een plicht: de AVG staat
onderzoek toe met passende waarborgen (artikel 89), en aan de deelnemers is meestal anonimiteit
beloofd. Transparantie geldt ook tegenover hen.

**Publiceer in lagen: zo open als mogelijk, zo gesloten als nodig (FAIR).**

| laag | wat | voor wie |
|---|---|---|
| open | afgeronde waarden per woning; code; volledige beschrijving van bronnen, afronding en ruis | iedereen |
| open, geaggregeerd | resultaten op volle precisie: verdelingen, correlaties, regressiecoëfficiënten, effecten per klasse (met ten minste k woningen per cel) | iedereen |
| gecontroleerd | exacte waarden per woning | onderzoekers onder voorwaarden |

De wetenschappelijke claims zijn na te rekenen met de eerste twee lagen; wie elke woning wil
narekenen, gaat via de derde. Twee technieken kunnen de open laag rijker maken: **ruis met
gepubliceerde parameters** in plaats van afronden (het idee achter differential privacy:
schattingen blijven gemiddeld zuiver, alleen minder precies), en een **synthetische dataset** met
dezelfde statistiek, waarop iedereen de code kan draaien.

**Gecontroleerde toegang hoef je niet zelf te bouwen.** Niet elke organisatie kan een eigen
toegangsomgeving opzetten en jarenlang onderhouden, en dat hoeft ook niet:

* **DANS Data Station** (KNAW/NWO): bestanden met *restricted access* zijn pas te downloaden als
  de eigenaar een verzoek goedkeurt. DANS bewaart de data duurzaam, met een DOI, en regelt
  opslag, beveiliging en de aanvraagprocedure. Deponeren is gratis tot 50 GB per account,
  downloaden altijd; daarboven maakt DANS een offerte (stand september 2026). Wat bij de eigenaar
  blijft: elk verzoek beoordelen aan de hand van een *Data Access Protocol* (DANS heeft een
  sjabloon) en zo nodig een gebruiksovereenkomst tekenen. Beleg dat bij een rol (de datasteward,
  het lectoraat), niet bij één persoon, zodat het een personeelswissel overleeft.
* **Code naar de data:** de eigenaar, of een partij die hij aanwijst, draait het script van de
  onderzoeker op de exacte data en geeft alleen de uitkomsten terug, na een controle op
  herleidbaarheid (bijvoorbeeld met anonymate).
* **CBS Remote Access,** tegen betaling, als de analyse ook om koppeling met CBS-microdata vraagt.

## 11. Wat anonymate niet doet

* Het toetst **tabellen met kenmerken**, niet tijdreeksen.
* Kenmerken zonder volledig register (dubbel glas, jaarverbruik) worden **geschat** uit de dataset
  zelf, onder de aanname dat ze onafhankelijk zijn; dat is meestal te streng.
* Het woningtype staat in de populatie alleen voor woningen met een label; zie het
  [kladblok](werk/KLADBLOK.md) voor dit en andere open punten.
* Het is een **hulpmiddel bij een afweging**, geen juridisch oordeel. De norm en de keuzes blijven
  bij wie publiceert.
