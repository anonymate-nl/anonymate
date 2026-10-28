# Herleidbaarheid van de woningdata

Hoe makkelijk is een woning uit de DACS-HW-dataset terug te vinden met gegevens die online voor
iedereen beschikbaar zijn? Dit document toetst de woningdata zoals ze nu openbaar zijn en geeft een
advies aan de **bronhouder** (Projectgroep DACS-HW, aanspreekpunt Inversable) en aan **KITE**
(Kennis- en Dataplatform Individuele Technieken, RVO). Beslissen over de publicatie is aan hen.

**Strekking.** De analyse gaat over één soort aanvaller: iemand die de dataset naast openbare online
bronnen legt (de BAG, de 3D-BAG, EP-online, de KNMI-stationslijst en de bestuurlijke gebieden van
PDOK) en naast wat openbaar over het project is geschreven. **Niet** in de analyse:

- *insiders*: wie de woningen al uit eigen administratie of werk kent, zoals een corporatie,
  aannemer, installatiebedrijf, leverancier van het verwarmingssysteem, energieleverancier of
  netbeheerder;
- *waarneming ter plekke*: wie door een wijk rijdt of fietst en kijkt (buitenunits, zonnepanelen).

Voor insiders staan in [Buiten deze analyse: insiders](#buiten-deze-analyse-insiders) een paar
algemene maatregelen die de bruikbaarheid van de dataset nauwelijks raken.

Getoetst met [AnonyMate](https://github.com/anonymate-nl/anonymate), versie `6ec1c19` (git-commit),
tegen de volledige Nederlandse woningvoorraad. AnonyMate is open source (EUPL-1.2).

| | |
|---|---|
| dataset | 93 woningen: het maandbestand per woning (`household_monthly`, pseudoniem `custom_id`). De andere vijf bestanden zijn aggregaten of gaan over één transformator, zie [Wat niet is getoetst](#wat-niet-is-getoetst) |
| populatie | 8.388.265 woningen: BAG-verblijfsobjecten met woonfunctie, in gebruik; afgebakend op Dalen, bouwjaar 1959-1994: 1.099 woningen |
| bronnen | BAG 31-08-2026 (PDOK `bag-light.gpkg`); EP-online totaalbestand, publicatie 01-09-2026; 3D-BAG v20250903; PDOK bestuurlijke gebieden 27-09-2026 |
| norm | k ≥ 11: elke woning lijkt op minstens 11 woningen in de afgebakende populatie, dus hoogstens ongeveer 1 op 11 kans op heridentificatie |
| uitgevoerd | 04-10-2026; scripts en configuraties in [`analyse/herleidbaarheid/`](../analyse/herleidbaarheid/) |

## Begrippen

- **QID** (quasi-identifier): een kenmerk dat een woning niet alleen aanwijst, maar in combinatie
  met andere wel (bouwjaar, oppervlak, ligging).
- **k**: op hoeveel woningen in de populatie lijkt deze rij? De kans op een juiste heridentificatie
  is 1/k.
- **Populatie**: de woningen waaruit de dataset kan komen. Wat publiek bekend is over werving en
  inclusie (achtergrondkennis) hoort in de afbakening.
- **Deelnameonthulling** (δ, *delta-presence*): welk deel van de gelijke woningen in de dataset
  zit. Dat is de kans dat een woning meedoet, ook als niet bekend is welke rij de hare is. k
  beschermt tegen *terugvinden*, δ tegen *aantonen dat iemand meedoet*. Zie
  [Deelnameonthulling](#deelnameonthulling-δ).
- **BAG**: Basisregistratie Adressen en Gebouwen (Kadaster). **EP-online**: het register van
  energielabels (RVO). **KITE**: Kennis- en Dataplatform Individuele Technieken (RVO).
  **DACS-HW**: Digitale Aggregatie en Collectieve Sturing van Hybride Warmtepompen.

## Werkwijze: eerst de norm, dan toetsen, dan afwegen

1. **De norm ligt vooraf vast**: k ≥ 11, de standaard van AnonyMate en dezelfde norm als bij de
   toetsen van andere openbare woningdatasets. Hij is niet aangepast aan de uitkomst. Bij de
   norm hoort ook de vraag of meedoen zelf gevoelig is; zo niet, dan wordt δ gemeld en vanaf 50%
   gemarkeerd, en beslist k (zie [Deelnameonthulling](#deelnameonthulling-δ)).
2. **Toetsen tegen de populatie, niet tegen de dataset.** Per woning telt AnonyMate hoeveel
   woningen in de afgebakende populatie dezelfde gepubliceerde kenmerken hebben (k).
3. **Afwegen** tussen grover publiceren en de bruikbaarheid: zie [Advies](#advies).

## Wat de dataset per woning prijsgeeft

De woningdata publiceren **geen woningkenmerken**: geen bouwjaar, oppervlakte, woningtype,
energielabel, adres of postcode, en ook geen weer per woning. Per woning staat er alleen een
pseudoniem en per maand het verbruik van stroom en gas. De pseudoniemen zijn niet te koppelen aan
de kwartier- en uurbestanden (`README_dataset.md` van de bron).

| kenmerk | kolom (in `household_monthly`) | wie kent het | detail |
|---|---|---|---|
| locatie en bouwperiode | geen kolom; staat in het eindrapport | iedereen | dorp Dalen, circa 1959-1994 |
| zonnepanelen | `e_teruglevering_tot__kWh` (meer dan 0 in minstens een maand) | waarneming ter plekke | buiten deze analyse |
| hybride warmtepomp | geen kolom; geldt voor elke woning | waarneming ter plekke (buitenunit) | buiten deze analyse |
| verbruik per maand | `e_geleverd_tot__kWh`, `g_geleverd_tot__m3` | energieleverancier, netbeheerder | buiten deze analyse |
| verbruik van het warmtepompsysteem | `e_warmtepomp_tot__kWh`, `g_warmtepomp_tot__m3` | installateur, leverancier van het systeem | buiten deze analyse |

**Achtergrondkennis over werving en inclusie.** Het openbare eindrapport (p. 8 en 10) noemt het
dorp Dalen (gemeente Coevorden), woningen van circa 1959 tot 1994, en tussenwoningen,
twee-onder-een-kapwoningen en vrijstaande woningen. Wie dat leest, kent de populatie waaruit de 93
woningen komen. Dat is de afbakening van de toets.

## Hoe de kenmerken de toets ingaan

- **Locatie en bouwperiode** gaan als afbakening van de populatie de toets in, niet als kenmerk:
  ze gelden voor alle woningen in de dataset tegelijk.
- Er is **geen registerkenmerk per woning**. k is daarom voor elke woning gelijk aan de grootte van
  de afgebakende populatie.

## Scenario's

| naam | wat de aanvaller gebruikt | populatie |
|---|---|---:|
| s1a | de hele gemeente Coevorden, bouwjaar 1959-1994 | 9.074 |
| **s1b** | het dorp Dalen, bouwjaar 1959-1994: de dataset zoals hij nu is, met het eindrapport | 1.099 |
| s1c | idem, alleen eengezinswoningen (een pand met één woning) | 969 |
| g1 | het dorp Dalen, bouwjaar 1955-1999 (ruimer dan "circa 1959-1994") | 1.275 |
| g2 | de hele gemeente Coevorden, alle bouwjaren | 16.077 |

## Uitkomst voor de dataset zoals hij nu openbaar is

Aantallen woningen (van 93); een woning haalt de norm als k ≥ 11.

| scenario | haalt de norm | te herleidbaar (k < 11) | k |
|---|---:|---:|---:|
| s1a, gemeente | 93 (100%) | 0 | 9.074 |
| **s1b, dorp Dalen** | **93 (100%)** | **0** | 1.099 |
| s1c, dorp Dalen, eengezins | 93 (100%) | 0 | 969 |
| g1, ruimere bouwperiode | 93 (100%) | 0 | 1.275 |
| g2, gemeente, alle bouwjaren | 93 (100%) | 0 | 16.077 |

### Bevindingen

1. **Eén woning is niet terug te vinden: k is overal ten minste 969.** Er is geen enkel
   registerkenmerk om een woning mee aan te wijzen; de kleinste groep is die van de
   eengezinswoningen in Dalen uit de genoemde bouwperiode.
2. **De uitkomst hangt niet af van de norm.** Ook bij de strengste norm die AnonyMate kent
   (k ≥ 20) halen alle woningen hem, in elk scenario.
3. **Wat de groep klein zou maken, staat niet in de dataset.** k is hier precies de grootte van de
   afbakening. Een postcode, straat, buurt of transformatornummer bij de woningdata zou de groep
   per woning direct verkleinen, tot onder de norm als het om een straat of een klein blok gaat.

### Deelnameonthulling (δ)

Hoe erg het is als bekend wordt *dát* een woning meedoet, hangt af van wat meedoen verraadt. Dat
kan alleen de bronhouder beoordelen. AnonyMate laat daarom bij de norm kiezen:

- **meedoen is niet gevoelig, of al bekend** (standaard): δ wordt gemeld en gemarkeerd vanaf 50%,
  waar meedoen minstens zo waarschijnlijk is als niet meedoen; een woning wordt alleen op k
  beoordeeld;
- **meedoen is zelf gevoelig:** dan moet ook δ ≤ 9% gelden (δ ≤ p, dezelfde grens als voor k).

Omdat er geen kenmerk per woning is, is δ hier voor elke woning gelijk: 93 gedeeld door de grootte
van de afbakening.

| scenario | δ | gemarkeerd (δ ≥ 50%) | haalt δ ≤ 9% |
|---|---:|---:|---:|
| s1a, gemeente | 1,0% | 0 | 93 |
| **s1b, dorp Dalen** | **8,5%** | **0** | **93** |
| s1c, dorp Dalen, eengezins | 9,6% | 0 | 0 |
| g1, ruimere bouwperiode | 7,3% | 0 | 93 |
| g2, gemeente, alle bouwjaren | 0,6% | 0 | 93 |

Onder de standaardkeuze is er niets gemarkeerd: wie een woning in Dalen uit die periode kent, weet
met ongeveer 1 op 10 kans dat ze meedoet. Onder de strenge keuze ligt δ precies rond de grens: net
eronder voor alle woningen in Dalen, net erboven als een aanvaller weet dat het om eengezinswoningen
gaat. Grover publiceren helpt daar niet, want er is niets per woning om grover te maken: δ is het
aandeel van het project in het dorp. Of meedoen gevoelig is, is aan de bronhouder; daarbij telt dat
het eindrapport het dorp al noemt en dat een hybride warmtepomp van buiten te zien is.

## Advies

Voor de bestaande kolommen is geen wijziging nodig. Twee punten:

1. **Publiceer geen extra locatie.** Geen postcode, buurt, straat of transformatornummer bij de
   woningdata, en houd de pseudoniemen onkoppelbaar aan de kwartier- en uurbestanden, zoals nu.
   Een locatiekenmerk per woning maakt k kleiner dan de afbakening (bevinding 3) en vraagt een
   nieuwe toets.
2. **Publiceer één versie.** Laat de huidige versie niet naast een nieuwe staan: wie beide heeft,
   legt ze over elkaar en weet meer dan uit elk van beide. Toets een nieuwe versie voordat hij
   verschijnt.

**Ruimte voor meer.** De ruime marge (k ≥ 969 bij een norm van 11) laat waarschijnlijk ruimte
voor een **bouwjaarklasse per 10 jaar**. Volgens tellingen in de populatie (969 eengezinswoningen
in Dalen, 1959-1994) heeft elke klasse van 10 jaar minstens 148 woningen. Voor onderzoek naar
warmtevraag is het bouwjaar een waardevol kenmerk. Het woningtype (rijwoning, twee-onder-een-kap,
vrijstaand) ligt minder voor de hand: één type komt in Dalen maar 4 keer voor, en type en bouwjaar
samen geven groepen van 1. Een versie die alleen een kolom toevoegt aan dezelfde woningen, leert
wie ook de huidige versie heeft niets extra's. Een bouwjaarklasse maakt wel δ per klasse groter:
zitten veel deelnemers in één klasse van 148 woningen, dan kan δ daar boven 50% komen, en dan is
van zo'n woning af te leiden dat ze waarschijnlijk meedoet. De bronhouder kan dit met AnonyMate op
de eigen gegevens (met adressen) toetsen voordat de kolom verschijnt; dan telt het werkelijke
bouwjaar van de deelnemers, niet de afbakening uit het eindrapport, en ziet de bronhouder ook δ per
klasse.

## Buiten deze analyse: insiders

Wie een woning al uit eigen administratie of werk kent, zit niet in de analyse hierboven. Voor
sommige insiders kan een kenmerk dat alleen zij kennen (het verbruik voor de energieleverancier of
netbeheerder, het toestel voor de installateur) toch een sleutel zijn. Een paar maatregelen kosten
vrijwel geen bruikbaarheid:

- **Verschillen per interval in plaats van meterstanden**, zo dat de verschillen optellen tot de
  juiste totalen over langere perioden, ook over gaten in de reeks heen. Een meterstand is een getal
  dat de netbeheerder of leverancier zelf ook heeft; een verschil per interval bevat dezelfde
  informatie voor analyse.
- **Geen nummers uit andere systemen:** geen EAN-codes, meternummers of serienummers.
- **Geen codes die ook elders voorkomen:** woningcodes die niet terugkomen in een andere dataset of
  een eerdere versie.

Voor andere kenmerken die alleen insiders kennen, zoals het exacte verbruik per maand of het
verbruik van het warmtepompsysteem, is afronden of weglaten niet vanzelf beter: voor onderzoekers
zijn juist die gegevens vaak waardevol. Dat is een afweging voor de bronhouder tussen het nut voor
onderzoek en het risico bij insiders. Deze analyse doet daar geen uitspraak over.

## Wat niet is getoetst

- **De kwartier- en uurbestanden** (`heatpump_15m`, `heatpump_steering_15m`,
  `smartmeters_gas_hourly`) zijn aggregaten over minstens 20 woningen per interval (gas) of 26
  systemen (warmtepomp; de aansturing heeft minimaal 2 gestuurde toestellen en geen
  toestel-identifiers). Het zijn geen woningrijen en AnonyMate toetst ze dus niet.
- **De wijktransformatordata** (`wijktrafo_15min`) gaan over één transformator. Ze wijzen geen
  woning aan.
- **Weer.** De dataset bevat geen weer per woning, dus geen weerstation of -cel als verborgen
  locatie.

## Kanttekeningen

- **Deelnameonthulling (δ)** is geteld uit de toets van 10-10-2026, volgens de keuze die AnonyMate
  sinds 18-10-2026 bij de norm biedt (melden en markeren vanaf 50%, of δ ≤ p). Of meedoen in dit
  project gevoelig is, is aan de bronhouder; zie [Deelnameonthulling](#deelnameonthulling-δ).
- **Inclusiecriteria uit één rapport.** De afbakening (Dalen, 1959-1994) komt uit het eindrapport
  (p. 10) en is daar "circa". De werkelijke deelnemers kunnen een ander bouwjaar hebben; de toets
  neemt aan dat alle 93 binnen de afbakening vallen. g1 toetst een ruimere bouwperiode.
- **93, 92 of 97 woningen.** Het rapport noemt drie aantallen en legt het verschil niet uit. Voor k
  maakt dat niets uit.
- **Eengezins volgens de BAG.** "Eengezins" betekent hier: een pand met één woning. Het woningtype
  uit EP-online is voor een deel van de woningen in Dalen niet bekend.
- **Registerversie.** De populatie is de BAG van 31-08-2026 (woningen in gebruik); de proef liep in
  2024-2025. Woningen die sindsdien zijn gesloopt of gebouwd, tellen mee of niet.
- **Geen adressenlijst.** Bij andere datasets gaat een lijst met kandidaat-adressen naar de
  bronhouder, zodat die kan controleren of de deelnemende woning tussen de kandidaten staat. Hier
  is de kandidatenlijst voor elke woning dezelfde: alle woningen in de afbakening. Die zegt niets
  wat het eindrapport niet al zegt, en is daarom niet gemaakt.

## Hertoets met een nieuwere AnonyMate (10-10-2026)

Alle scenario's zijn op 10-10-2026 herhaald met AnonyMate `4e55ae0` (onder meer met de controle
op klassegrenzen en afgeronde waarden). De uitkomsten zijn gelijk aan die hierboven, voor elk
scenario. Nieuw zijn alleen meldingen over "gaten" tussen verbruiksklassen in de
insider-scenario's (bijvoorbeeld `50-99` naast `100-149` m³): die klassen maakt het analysescript
zelf, ze staan niet in de publicatie, en ze veranderen de uitkomst niet.

## Reproduceren

```bash
pip install -e ".[dev]" && python -m dacs_hw_preprocessing     # de verwerkte woningdata
pip install "anonymate @ git+https://github.com/anonymate-nl/anonymate"
anonymate ingest pakket                                       # BAG, 3D-BAG, KNMI, gebieden
anonymate ingest ep-online                                    # optioneel, nodig voor het label
anonymate build
ANONYMATE=anonymate bash analyse/herleidbaarheid/draai.sh
```

`ingest` en `build` halen de registers één keer op (enkele GB); daarna is de toets offline en
duurt hij enkele seconden per scenario. `draai.sh` draait ook scenario's met kenmerken die alleen
ter plekke of door insiders te kennen zijn; die horen niet bij deze analyse. De uitvoer staat in
`analyse/herleidbaarheid/uitvoer/` (niet in git).

## Melding

De gebruiksvoorwaarden van de woningdata vragen gebruik en uitkomsten te melden bij
data@inversable.com (zie [`GEBRUIKSVOORWAARDEN.md`](https://github.com/duurzaamleven/dacs-hw-dataset-preprocessing/blob/main/GEBRUIKSVOORWAARDEN.md)). Deze toets valt
daaronder.
