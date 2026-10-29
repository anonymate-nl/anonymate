# Herleidbaarheid van de woningkenmerken

Hoe makkelijk is een woning uit de WarmingUP-dataset *How Low Can You Go* terug te vinden met
gegevens die online voor iedereen beschikbaar zijn? Dit document toetst de woningkenmerken zoals ze
nu openbaar zijn en geeft een advies aan de **bronhouder** (Deltares, data-eigenaar) en **KITE**
(het Kennis- en Dataplatform Individuele Technieken van RVO, waar de dataset wordt aangeboden).
Beslissen over de publicatie is aan hen.

**Strekking.** De analyse gaat over één soort aanvaller: iemand die de dataset naast openbare online
bronnen legt (de BAG, de 3D-BAG, EP-online, de KNMI-stationslijst en de bestuurlijke gebieden van
PDOK) en naast wat openbaar over het project is geschreven. **Niet** in de analyse:

- *insiders*: wie de woningen al uit eigen administratie of werk kent, zoals een corporatie,
  aannemer, installatiebedrijf, leverancier van het verwarmingssysteem, energieleverancier of
  netbeheerder;
- *waarneming ter plekke*: wie door een wijk rijdt of fietst en kijkt.

Voor insiders staan in [Buiten deze analyse: insiders](#buiten-deze-analyse-insiders) een paar
algemene maatregelen die de bruikbaarheid van de dataset nauwelijks raken.

Getoetst met [AnonyMate](https://github.com/anonymate-nl/anonymate), versie `59ebc8a` (git-commit),
tegen de volledige Nederlandse woningvoorraad. AnonyMate is open source (EUPL-1.2). De eerste
versie van dit rapport (20-10-2026) gebruikte `a132113`; wat er sindsdien veranderd is, staat onder
[Gewijzigd op 24-10-2026](#gewijzigd-op-24-10-2026). Op 29-10-2026 is de toets herhaald op de
versie van de dataset van 27-10-2026; zie [Gewijzigd op 29-10-2026](#gewijzigd-op-29-10-2026).

| | |
|---|---|
| dataset | 212 woningen: de woningkenmerken uit `resultaten.parquet` (uitvoercontractversie `2026-10-28-vierde-opzet`, zie [`datacatalogus.md`](https://github.com/duurzaamleven/warmingup-dataset-preprocessing/blob/main/docs/datacatalogus.md) §5.5). 198 woningen hebben ten minste één kenmerk ingevuld, 14 hebben alles leeg |
| populatie | 8.388.265 woningen: BAG-verblijfsobjecten met woonfunctie, in gebruik (heel Nederland) |
| bronnen | BAG 31-08-2026 (PDOK `bag-light.gpkg`, ook de pandcontouren); EP-online totaalbestand, publicatie 01-09-2026; 3D-BAG v20250903; PDOK bestuurlijke gebieden 27-09-2026; KNMI-stations met temperatuurmeting |
| norm | k ≥ 11: elke woning lijkt op minstens 11 woningen in Nederland, dus hoogstens ongeveer 1 op 11 kans op heridentificatie |
| uitgevoerd | 04-10-2026, herhaald op 10-10-2026 met de nieuwere AnonyMate (zelfde uitkomsten), opnieuw op 24-10-2026 met het herstelde woningtype, en op 29-10-2026 op de versie van de dataset van 27-10-2026 (zelfde uitkomsten); scripts en configuraties in [`../analyse/herleidbaarheid/`](../analyse/herleidbaarheid/) |

**Waarom een toets, als de dataset "onherleidbaar" heet?** De KITE-pagina zegt dat de dataset
openbaar is gesteld, "beperkt zodat individuele personen/adressen onherleidbaar zijn"
([`GEBRUIKSVOORWAARDEN.md`](https://github.com/duurzaamleven/warmingup-dataset-preprocessing/blob/main/GEBRUIKSVOORWAARDEN.md)). Dat is een belofte aan de deelnemers. Deze
toets meet of de beperking houdt voor wie de dataset heeft en de openbare woningregisters ernaast
legt.

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
- **2R2C**: een grijze-dozenmodel van een woning met twee thermische weerstanden (R) en twee
  warmtecapaciteiten (C). **H**: de warmteoverdrachtscoëfficiënt van een woning, in W/K.
- **BAG**: Basisregistratie Adressen en Gebouwen (Kadaster). **EP-online**: het register van
  energielabels (RVO). **3D-BAG**: het 3D-gebouwmodel van TU Delft. **KNMI**: het weerinstituut.

## Werkwijze: eerst de norm, dan toetsen, dan afwegen

1. **De norm ligt vooraf vast**: k ≥ 11, de standaard van AnonyMate en dezelfde norm als bij de
   toetsen van andere openbare woningdatasets. Hij is niet aangepast aan de uitkomst. Hoe gevoelig
   de uitkomst is voor een andere norm, staat onder
   [Gevoeligheid](#gevoeligheid-voor-de-norm-en-de-aannames). Bij de norm hoort ook de vraag of
   meedoen zelf gevoelig is; zo niet, dan wordt δ gemeld en vanaf 50% gemarkeerd, en beslist k
   (zie [Deelnameonthulling](#deelnameonthulling-δ)).
2. **Toetsen tegen de populatie, niet tegen de dataset.** Per woning telt AnonyMate hoeveel
   woningen in heel Nederland dezelfde gepubliceerde kenmerken hebben (k).
3. **Afwegen** tussen grover publiceren (minder detail voor iedereen) en woningen niet publiceren
   (minder woningen, mogelijk een vertekening). Zie [Advies](#advies).

## Wat de dataset per woning prijsgeeft

Alleen `resultaten.parquet` bevat woningkenmerken. `boiler_temp`, `thermostat_temp` en `etmaal` zijn
tijdreeksen per pseudoniem (`WU0` tot `WU242`); die staan onder
[Wat niet is getoetst](#wat-niet-is-getoetst).

| kenmerk | kolom | wie kent het | detail |
|---|---|---|---|
| woningtype | `woningtype__cat` | iedereen (EP-online; anders afgeleid uit de BAG) | 5 typen; bij 14 woningen leeg |
| bouwjaar | `bouwjaar_klasse__cat` en `bouwjaar_klasse_eindrapport__cat` | iedereen (BAG) | twee indelingen naast elkaar, klassen van meestal 9 tot 11 jaar (de oudste 30), en een grove van drie klassen (`Voor 1974`, `1974-1991`, `Na 1991`). Samen te lezen als de smalste van de twee; 198 woningen ingevuld |
| gebruiksoppervlak | `oppervlak_klasse__cat` | iedereen (BAG) | klassen van 10 m² tot 150 m², daarboven 25 en 50 m², tot `350-399`; 192 ingevuld |
| model 2R2C | `r_*`, `c_*`, `a_raam_effectief__m2` | iedereen, bij benadering: een aanvaller kan H uit het adres berekenen en vergelijken | per woning een exacte waarde, 198 ingevuld |
| jaarverbruik gas | `g_jaarverbruik_indicatief__m3` | energieleverancier, netbeheerder | buiten deze analyse |
| geïnstalleerd radiatorvermogen | `p_afgifte_geinstalleerd__W` | installateur | buiten deze analyse |
| ontwerpvermogen en overdimensionering | `p_ontwerp__W`, `overdimensionering__frac` | volgen uit de metingen | buiten deze analyse; zie [insiders](#buiten-deze-analyse-insiders) |

**Er is geen locatie.** Geen postcode, gemeente, weerstation of H3-cel (een zeshoekig raster voor locaties) in de dataset: het weer is
geen onderdeel van het archief. Dat is het grootste verschil met andere woningdatasets, waar het
weerstation de staarten herkenbaar maakte. Ook het energielabel staat er niet in.

### Achtergrondkennis over werving en inclusie

Wat publiek bekend is, hoort bij de populatie-afbakening (het eindrapport van Pothof, Vreeken & Van
Meerkerk, Deltares, 13-09-2022; zie [`datacatalogus.md`](https://github.com/duurzaamleven/warmingup-dataset-preprocessing/blob/main/docs/datacatalogus.md) §2):

- **Gasketel, thermostaat en radiatoren**; geen extra warmtebron, geen vloerverwarming zonder
  hydraulische balans, een stopcontact bij de ketel nodig. Dat is geen filter dat AnonyMate op de
  woningvoorraad kan toepassen (de registers kennen de verwarmingsinstallatie niet), dus de populatie
  blijft heel Nederland. Dat is de **milde kant**: de werkelijke populatie van gasketelwoningen is
  kleiner, en de kans dat een kenmerkencombinatie zeldzaam is dus groter.
- **Streefverdeling**: minstens 200 woningen over vier woningtypen (vrijstaand, hoek, tussen,
  appartement) en drie bouwperioden (vóór 1974, 1974 tot 1991, na 1991). Dat is een steekproef over
  heel Nederland, geen beperkt aantal wijken.
- **Werving** via installatiebedrijf Feenstra, dat destijds circa 20.000 Intergas-ketels monitorde,
  met de warmtebedrijven Vattenfall, HVC, SVP, Eneco en ENnatuurlijk als partners. Over de regio's
  is niets vastgesteld. Het weerstation Deelen ligt
  volgens het rapport "geographically closest to most studied buildings"; daarom is als
  gevoeligheid een populatie rond Deelen getoetst (536 duizend woningen), zie
  [Gevoeligheid](#gevoeligheid-voor-de-norm-en-de-aannames).

## Hoe de kenmerken de toets ingaan

- **Woningtype, bouwjaar en oppervlak** als klasse, zoals gepubliceerd; de twee bouwjaarindelingen
  samen als de smalste klasse.
- **H uit het model** (1 gedeeld door de som van de twee weerstanden) kan een aanvaller alleen
  vergelijken met een uit het adres berekende waarde. Die wijkt per woning tientallen W/K af; de
  toets rekent met een tolerantie van 81 W/K, geleend van een andere woningdataset (s3a).
- **C uit het model** is op dezelfde manier geprobeerd (s3b), maar is niet te duiden: zie
  bevinding 3.

## Scenario's

| naam | wat de aanvaller gebruikt |
|---|---|
| **s1** | woningtype, bouwjaar, oppervlakte: de registerkenmerken zoals gepubliceerd |
| s3a | s1 + de warmteoverdracht H uit het model, vergeleken met een uit het adres berekende H (indicatief) |
| s3b | s1 + de thermische massa C uit het model, op dezelfde manier (niet te duiden) |

## Uitkomst voor de dataset zoals hij nu openbaar is

Aantallen woningen (van 212); een woning haalt de norm als k ≥ 11.

| scenario | haalt de norm | te herleidbaar (k < 11) | k mediaan |
|---|---:|---:|---:|
| **s1, registerkenmerken** | **212 (100%)** | **0** | 24.571 |
| s3a, + H uit het model (indicatief) | 208 (98%) | 3, plus 1 zonder match | 2.038 |

### Bevindingen

1. **Met de registerkenmerken is één woning niet terug te vinden.** Elke woning lijkt op minstens
   1.494 woningen in Nederland, mediaan 25 duizend; alle 212 hebben k boven 1.000. De klassen
   (bouwjaar, oppervlakte per 10 m²) zijn dus fijn genoeg om informatief te zijn en grof genoeg om
   te beschermen, zolang er geen locatie bij staat. Ook de grootste woningen (200 tot 399 m²) halen
   de norm met k van 3.300 of meer.
2. **Het 2R2C-model is een zwakke sleutel.** Met H uit het model erbij haalt 98% de norm. De drie
   woningen onder de norm zijn uitschieters (H onder 80 of boven 340 W/K), vermoedelijk modelfits
   die niet goed gelukt zijn. De uitkomst is indicatief: de tolerantie is niet voor deze dataset
   gekalibreerd.
3. **Voor de thermische massa C is dezelfde vergelijking niet te duiden**: voor 115 van de 212
   woningen past geen enkele woning, omdat het model een andere grootheid meet dan de
   adres-signatuur. "Geen match" is geen veiligheid; het zegt hier alleen dat de vergelijking mank
   gaat.

### Bits per kenmerk

Om één woning aan te wijzen tussen 8,4 miljoen zijn 23,0 bits nodig (log₂ van het aantal woningen:
23 ja/nee-vragen, zoals bij *Wie is het?*). Gemiddeld geven de registerkenmerken samen ongeveer 9 bits
prijs (oppervlakte 3,7, bouwjaar 3,1, woningtype 2,7), dus er resteren mediaan 13,7 bits: duizenden
gelijke woningen. De norm k ≥ 11 vraagt minstens 3,5 bits te gaan voor élke woning, dus een
gemiddelde zegt niet genoeg; de toets telt per woning. (Cijfers van 20-10-2026. Met het
woningtype van 24-10-2026 geeft het woningtype 1,9 bits prijs in plaats van 2,7, en resteren
mediaan 14,6 bits.)

## Advies

Voor de registerkenmerken hoeft er niets te veranderen. Wel twee punten:

1. **Kijk naar de uitschieters in het model.** De drie woningen die met H onder de norm komen, zijn
   vermoedelijk mislukte modelfits. Zijn hun modelparameters voor onderzoek niet bruikbaar, dan
   kunnen ze weg; dat is dan ook beter voor de herleidbaarheid. Dat is een afweging voor de
   bronhouder.
2. **Publiceer één versie.** Laat de huidige versie niet naast een nieuwe staan: wie beide heeft,
   legt de klassen over elkaar en krijgt smallere klassen dan elk van beide. Toets een nieuwe
   versie voordat hij verschijnt.

### Gevoeligheid voor de norm en de aannames

| variant | haalt de norm |
|---|---:|
| s1 met k ≥ 20 (de strengste norm in AnonyMate) | 212 (100%), k minimaal 1.494 |
| s1, woningen zonder woningtype tellen mee als mogelijke match | 212 (100%), k mediaan 24.571 |
| s1, populatie alleen het weerstationsgebied Deelen (536 duizend woningen) | 212 (100%), k minimaal 83, mediaan 1.579 |

De conclusie voor de registerkenmerken is stabiel, ook als de steekproef in werkelijkheid in één
regio geconcentreerd is.

### Deelnameonthulling (δ)

Hoe erg het is als bekend wordt *dát* een woning meedoet, hangt af van wat meedoen verraadt. Dat
kan alleen de bronhouder beoordelen. AnonyMate laat daarom bij de norm kiezen:

- **meedoen is niet gevoelig, of al bekend** (standaard): δ wordt gemeld en gemarkeerd vanaf 50%,
  waar meedoen minstens zo waarschijnlijk is als niet meedoen; een woning wordt alleen op k
  beoordeeld;
- **meedoen is zelf gevoelig:** dan moet ook δ ≤ 9% gelden (δ ≤ p, dezelfde grens als voor k).

| scenario | δ ≥ 50% (gemarkeerd) | δ > 9% | daarvan met k ≥ 11 | δ maximaal |
|---|---:|---:|---:|---:|
| **s1, registerkenmerken** | **0** | **0** | **0** | 0,1% |
| s1, populatie rond Deelen | 0 | 0 | 0 | 2% |
| s3a, + H uit het model (indicatief) | 1 | 4 | 1 | 100% |

Met de registerkenmerken is δ verwaarloosbaar: de 212 woningen zijn een steekproef uit heel
Nederland, en ook rond Deelen blijft δ ver onder 9%. Met H uit het model is één woning gemarkeerd;
die haalt ook k niet. Als meedoen gevoelig is, valt in s3a één woning extra af (207 in plaats van
208 halen de norm). Voor het advies maakt de keuze niets uit.

## Buiten deze analyse: insiders

Wie een woning al uit eigen administratie of werk kent, zit niet in de analyse hierboven. Voor
sommige insiders kan een kenmerk dat alleen zij kennen (het radiatorvermogen voor de installateur,
het jaarverbruik voor de energieleverancier of netbeheerder) toch een sleutel zijn. Een paar
maatregelen kosten vrijwel geen bruikbaarheid:

- **Verschillen per interval in plaats van meterstanden**, zo dat de verschillen optellen tot de
  juiste totalen over langere perioden, ook over gaten in de reeks heen. Een meterstand is een getal
  dat de netbeheerder of leverancier zelf ook heeft; een verschil per interval bevat dezelfde
  informatie voor analyse.
- **Geen nummers uit andere systemen:** geen EAN-codes, meternummers of serienummers.
- **Geen codes die ook elders voorkomen:** woningcodes die niet terugkomen in een andere dataset of
  een eerdere versie.

**Het gasverbruik per dag** (`etmaal`: tapwater en ruimteverwarming per kalenderdag, met datum) is
voor de netbeheerder en de energieleverancier waarschijnlijk een sterkere sleutel dan het
jaarverbruik: zij hebben vaak de dagstanden van de slimme meter, en een reeks van honderden dagen
is zelden bij twee woningen gelijk. Dit rapport geeft daar geen oordeel over en heeft het niet
getoetst; het noemt het hier omdat die tabel de kern van de dataset is.

Voor andere kenmerken die alleen insiders kennen, zoals het radiatorvermogen en het jaarverbruik, is
afronden of weglaten niet vanzelf beter: voor onderzoekers zijn juist die gegevens vaak waardevol,
en het radiatorvermogen is wat deze dataset bijzonder maakt. Dat is een afweging voor de bronhouder
tussen het nut voor onderzoek en het risico bij insiders. Deze analyse doet daar geen uitspraak
over. Wie die afweging maakt: `p_afgifte_geinstalleerd__W` is gelijk aan `p_ontwerp__W` gedeeld
door `overdimensionering__frac`, dus de drie kolommen horen bij elkaar.

## Wat niet is getoetst

- **Tijdreeksen.** Het gasverbruik per dag (`etmaal`), het debiet en de temperaturen per minuut.
  Zonder locatie in de dataset zijn ze voor de openbare aanvaller lastig te koppelen; voor insiders
  zie [Buiten deze analyse: insiders](#buiten-deze-analyse-insiders).
- **De twee indelingen van bouwjaar naast elkaar** zijn getoetst als één smalste klasse; in deze
  dataset zijn ze niet tegenstrijdig (0 gevallen). AnonyMate meldt daardoor overlappende bouwjaarklassen (bijvoorbeeld
  `<=1899` naast `<=1973`): dat is zo bedoeld, want per woning staat de smalste klasse die bekend
  is. De melding over een gat tussen oppervlakteklassen betekent alleen dat er geen woningen van 250
  tot 299 m² in de dataset zitten.

## Kanttekeningen

- **Deelnameonthulling (δ)** is geteld volgens de keuze die AnonyMate sinds 18-10-2026 bij de
  norm biedt (melden en markeren vanaf 50%, of δ ≤ p). Of meedoen in dit project gevoelig is, is
  aan de bronhouder; zie [Deelnameonthulling](#deelnameonthulling-δ).
- **Eigen opgave tegenover register.** Een deel van de kenmerken komt uit een huisbezoek of
  enquête, en kan afwijken van de registers. De toets telt tegen de registers.
- **Het woningtype in de registers.** Heeft een woning een energielabel, dan geldt het woningtype
  uit EP-online. Zo niet, dan leidt AnonyMate het af uit de pandcontouren van de BAG, zoals een
  aanvaller dat ook kan: de panden met een woning waarmee ze een muur deelt, en de grootte van het
  blok (geen buren: vrijstaand; een blok van twee: twee-onder-een-kap; het eind van een rij:
  hoekwoning; daartussen: tussenwoning). In twee proefgebieden klopt dat in 90 à 91% met EP-online,
  het minst bij twee-onder-een-kap (ongeveer 60%). De toets rekent alsof het type klopt; dat is
  voorzichtig, want een aanvaller die zich vergist, zoekt in de verkeerde groep.
- **Modelparameters.** De berekening van H uit het model (zie
  [`../analyse/herleidbaarheid/maak_invoer.py`](../analyse/herleidbaarheid/maak_invoer.py)) is een
  aanname van deze toets; de tolerantie is niet voor deze dataset gekalibreerd, omdat er geen adressen
  bij de pseudoniemen bekend zijn. De eenheid van `C_i` en `C_e` is J/K volgens de brontabel en
  Wh/K volgens het eindrapport; de grootte-orde wijst op J/K.
- **Woningen zonder kenmerken.** 14 van de 212 woningen hebben geen enkel woningkenmerk. Ze tellen
  als publiceerbaar (k is dan de hele populatie) maar zeggen niets.
- **Alleen de gepubliceerde tabel.** De toets bekijkt wat nu openbaar is. Een andere uitvoer van de
  preprocessing, met meer of minder kolommen, vraagt een nieuwe toets.

## Gewijzigd op 24-10-2026

De eerste versie van dit rapport (20-10-2026) rekende met een populatie waarin twee fouten in het
woningtype zaten, allebei in AnonyMate. Het gecombineerde EP-online-type "Twee-onder-een-kap /
rijwoning hoek" telde altijd als twee-onder-een-kap, ook als het subtype "Rijwoning" zei (ruim
300.000 labels van hoekwoningen), en "Twee-onder-één-kap" met accenten (241.000 labels) werd niet
herkend. En woningen zonder label hadden geen woningtype, en telden standaard niet mee als
mogelijke match. Beide zijn hersteld in AnonyMate `59ebc8a`; het woningtype zonder label komt nu
uit de vorm (zie [Kanttekeningen](#kanttekeningen)). Alle scenario's zijn opnieuw gedraaid, met
dezelfde BAG en EP-online als eerst; de uitvoer staat in
`analyse/herleidbaarheid/uitvoer_59ebc8a_hertoets/`.

| | 20-10-2026 | 24-10-2026 |
|---|---:|---:|
| s1: k minimaal / mediaan | 607 / 13.342 | 1.494 / 24.571 |
| s3a: haalt de norm | 204 (96%) | 208 (98%) |
| s3a: te herleidbaar | 7, plus 1 zonder match | 3, plus 1 zonder match |
| s3a: haalt de norm als meedoen gevoelig is | 203 | 207 |

Eerdere versies van dit rapport noemden voor s3a ook 203 en 8; dat waren de aantallen met δ ≤ p.
Geen woning die eerst de norm haalde, haalt hem nu niet. Het advies blijft hetzelfde.

## Gewijzigd op 29-10-2026

Op 27-10-2026 verscheen een nieuwe versie van de dataset. De kenmerken die de toets gebruikt
(woningtype, bouwjaar, oppervlak en het model) zijn daarin ongewijzigd, voor dezelfde 212 woningen.
Alle scenario's zijn opnieuw gedraaid op de uitvoer van de preprocessing van die versie
(uitvoercontractversie `2026-10-28-vierde-opzet`), met dezelfde registers als op 24-10-2026. De
uitkomsten zijn gelijk; de uitvoer staat in `analyse/herleidbaarheid/uitvoer/`.

## Adressenlijst voor de bronhouder: niet gemaakt

Met de registerkenmerken (s1) haalt elke woning de norm. Voor s3a zou een lijst met
kandidaat-adressen steunen op een vergelijking met een niet-gekalibreerde tolerantie; zo'n lijst is
niet betrouwbaar genoeg om aan iemand te geven. Is er behoefte aan, dan maakt
`anonymate assess --kandidaten` hem; hij moet `bijlage_NIET_PUBLICEREN` heten, in
`analyse/herleidbaarheid/uitvoer/` staan (gitignored) en alleen naar de bronhouder en KITE gaan.

## Reproduceren

```bash
git clone https://github.com/anonymate-nl/anonymate && git -C anonymate checkout 59ebc8a
pip install -e ./anonymate
anonymate ingest all               # BAG met pandcontouren, gemeenten, KNMI (zie hieronder)
anonymate ingest ep-online         # energielabels, met eigen EP-online-sleutel
anonymate build
bash analyse/herleidbaarheid/draai.sh <uitvoermap van de preprocessing>
```

`ingest` en `build` halen de registers één keer op en bouwen de populatie (enkele uren). Het
datapakket (`anonymate ingest pakket`, een half uur) is sneller, maar een pakket van vóór
24-10-2026 heeft de buren uit de pandcontouren nog niet; daarmee wijken de getallen iets af; daarna is de toets offline en duurt hij enkele minuten. De uitvoermap
van de preprocessing is de map met `resultaten.parquet` (zie
[`../VOORTGANG.md`](https://github.com/duurzaamleven/warmingup-dataset-preprocessing/blob/main/VOORTGANG.md)). Configuraties en uitleg per scenario: zie
[`../analyse/herleidbaarheid/README.md`](../analyse/herleidbaarheid/README.md). `draai.sh` draait
ook scenario's met kenmerken die alleen insiders kennen; die horen niet bij deze analyse.

## Melding

De voorwaarden van de dataset vragen gebruik te melden op <kite@rvo.nl> en analyseresultaten te
delen met de KITE-community. Deze toets valt daaronder; de uitkomsten zijn bedoeld voor Deltares en
KITE.
