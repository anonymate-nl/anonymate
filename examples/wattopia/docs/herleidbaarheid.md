# Herleidbaarheid van de woningkenmerken

Hoe makkelijk is een woning of een project uit deze dataset terug te vinden met gegevens die online
voor iedereen beschikbaar zijn? Dit document toetst de kenmerken zoals ze in het pakket staan en
geeft een advies aan de **bronhouder** (Wattopia, met RVO en het KITE-portaal, waarlangs de dataset
wordt verspreid). Beslissen over een volgende publicatie is aan hen.

**Strekking.** De analyse gaat over één soort aanvaller: iemand die de dataset naast openbare online
bronnen legt (de BAG, de 3D-BAG, EP-online, de KNMI-stationslijst en de bestuurlijke gebieden van
PDOK). **Niet** in de analyse:

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
| dataset | 898 woningen in 24 projecten: de projectkenmerken uit `projecten`, via het project van elke woning in `woningen_jaar` |
| populatie | 8.388.265 woningen: BAG-verblijfsobjecten met woonfunctie, in gebruik; 5.306.817 eengezins- en 3.081.448 meergezinswoningen |
| bronnen | BAG 31-08-2026 (PDOK `bag-light.gpkg`); EP-online totaalbestand, publicatie 01-09-2026; 3D-BAG v20250903; PDOK bestuurlijke gebieden 27-09-2026; KNMI-stations met temperatuurmeting |
| norm | k ≥ 11: elke woning lijkt op minstens 11 woningen in Nederland, dus hoogstens ongeveer 1 op 11 kans op heridentificatie |
| uitgevoerd | 04-10-2026; scripts en configuraties in [`analyse/herleidbaarheid/`](../analyse/herleidbaarheid/) |

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
- **BAG**: Basisregistratie Adressen en Gebouwen (Kadaster). **EP-online**: het register van
  energielabels (RVO). **KNMI**: het weerinstituut. **PC4**: postcode met vier cijfers.

## Werkwijze: eerst de norm, dan toetsen, dan afwegen

1. **De norm ligt vooraf vast**: k ≥ 11, de standaard van AnonyMate en dezelfde norm als bij de
   toetsen van andere openbare woningdatasets. Hij is niet aangepast aan de uitkomst. Bij de
   norm hoort ook de vraag of meedoen zelf gevoelig is; zo niet, dan wordt δ gemeld en vanaf 50%
   gemarkeerd, en beslist k (zie [Deelnameonthulling](#deelnameonthulling-δ)).
2. **Toetsen tegen de populatie, niet tegen de dataset.** Per woning telt AnonyMate hoeveel
   woningen in heel Nederland dezelfde gepubliceerde kenmerken hebben (k).
3. **Afwegen** tussen grover publiceren en de bruikbaarheid: zie [Advies](#advies).

## Wat de dataset per woning prijsgeeft

De dataset heeft geen adressen, postcodes of coördinaten. Alle kenmerken die naar een woning
wijzen, zijn **projectkenmerken**: alle woningen van een project delen ze.

| kenmerk | kolom | wie kent het | detail |
|---|---|---|---|
| bouwjaar | `bouwjaar_afgerond__0` | iedereen (BAG) | afgerond op 5 jaar |
| gebruiksoppervlak | `gebruiksoppervlak_afgerond__m2` | iedereen (BAG) | gemiddelde van het project, afgerond op 5 m² |
| woningtypologie | `woningtypologie__cat` | iedereen (BAG, EP-online) | grondgebonden (eengezins) of portiekflat (meergezins), met bouwperiode |
| **weerstation** | `knmi_station__str` | iedereen (KNMI-stationslijst en BAG-ligging) | het dichtstbijzijnde van 13 stations: een **verborgen locatie** |
| zonnepanelen | `elektrische_opwekking__cat` | waarneming ter plekke | buiten deze analyse |
| bron van de warmtepomp | `bron_warmteopwekker__cat` | waarneming ter plekke (buitenunit) | buiten deze analyse |
| warmteopwekker | `warmteopwekker__cat` | installateur, corporatie | buiten deze analyse |
| renovatiejaar | `renovatiejaar_afgerond__0` | corporatie, aannemer | niet in een register; buiten deze analyse |
| jaarverbruik | `e_netto_afname__kWh_a_1`, `gas_voor_renovatie__m3_a_1`, `e_voor_renovatie__kWh_a_1` | energieleverancier, netbeheerder | buiten deze analyse |
| ligging | `ligging__cat` | waarneming ter plekke | hoek of tussen; buiten deze analyse |

Niet in de dataset: adres, postcode, gemeente, energielabel, weerreeksen. Vier projecten (50
woningen) hebben geen bouwjaar, oppervlak en typologie; van hen is alleen het weerstation bekend.

**Achtergrondkennis over werving en inclusie** (codeboek, KITE-pagina): woningen die in 2019 tot 2022
zijn gerenoveerd naar of richting aardgasvrij, met monitoringdata die woningcorporaties,
bouwbedrijven en monitoringleveranciers hebben gedeeld; alle projecten halen een netto warmtevraag
onder 50 kWh/m²/jaar. Het codeboek beschrijft de eigen anonimisering: willekeurige codes, het
aantal woningen per project verhuld (projecten gesplitst of woningen weggelaten), willekeurige
volgorde, bouwjaar, renovatiejaar en oppervlak afgerond op 5. Wat daarvan in een register staat,
hoort in de afbakening van de populatie: het woningtype (eengezins of meergezins). Dat de woningen
gerenoveerd zijn en van corporaties of bouwers komen, staat in **geen enkel register** en kon dus
niet in de populatie; zie [Kanttekeningen](#kanttekeningen).

## Hoe de kenmerken de toets ingaan

- **Weerstation:** het nummer van het KNMI-station als verborgen locatie.
- **Bouwjaar en oppervlak:** een afgerond 1965 betekent een echt bouwjaar van 1963 tot 1967; het
  wordt dus als bereik getoetst (`1963-1967`), en oppervlak 95 m² als `93-97`. Zo telt de toets de
  afronding eerlijk mee. Het oppervlak is het gemiddelde van het project en kan per woning
  afwijken: daarvoor is een ruimere marge getoetst (s1b).
- **Woningtype:** een afbakening van de populatie (grondgebonden: eengezinswoningen; portiekflat:
  meergezinswoningen), niet een kenmerk, omdat het woningtype in de registers niet de typologie
  van de dataset kent.
- Een project zonder bouwjaar en oppervlak wordt alleen op weerstation getoetst.

## Scenario's

| naam | wat de aanvaller gebruikt |
|---|---|
| s0 | bouwjaar en oppervlak, **zonder** weerstation (om de bijdrage van het station te zien) |
| **s1** | weerstation, bouwjaar, oppervlak, type: de dataset zoals hij nu is |
| s1b | idem, bouwjaar ±5 jaar en oppervlak ±10 m² (de aanvaller leest de afronding ruimer) |
| s2 | idem, en de aanname dat de woning na renovatie label A of beter heeft |
| a1 | het **advies**: bouwjaar op 10 jaar en oppervlak op 20 m² afgerond |

## Uitkomst voor de dataset zoals hij nu is

Aantallen woningen (van 898); een woning haalt de norm als k ≥ 11.

| scenario | haalt de norm | te herleidbaar (k < 11) | k mediaan |
|---|---:|---:|---:|
| s0, zonder weerstation (848 woningen*) | 848 (100%) | 0 | 12.003 |
| **s1, de dataset zoals hij nu is** | **898 (100%)** | **0** | 724 |
| s1b, ruime marge | 898 (100%) | 0 | 6.017 |
| s2, label A als aanname | 878 (98%) | 20 | 231 |

\* Zonder weerstation hebben de 50 woningen zonder bouwjaar en oppervlak geen kenmerk meer en doen ze niet mee.

Woningen per k-klasse, het aantal gelijke woningen in Nederland:

| scenario | k < 11 | k 11 tot 100 | k 100 tot 1.000 | k 1.000 of meer |
|---|---:|---:|---:|---:|
| s0 | 0 | 0 | 0 | 848 |
| s1 | 0 | 20 | 621 | 257 |
| s1b | 0 | 0 | 20 | 878 |

### Bevindingen

1. **Eén woning is niet terug te vinden: k is overal ten minste 47.** Elke woning lijkt op minstens
   47 andere in Nederland (mediaan 724). Voor het herkennen van één woning is afronden op 5 jaar
   en 5 m² genoeg.
2. **Het weerstation verkleint de groep gelijke woningen het sterkst.** Zonder weerstation is k ten
   minste 4.103; met weerstation blijven er enkele tientallen tot enkele duizenden over. Voor de
   norm is dat ruim genoeg. Het weer bij de woning is voor warmtevraaganalyse het waardevolste
   kenmerk; weglaten is niet nodig.
3. **Een blok woningen is makkelijker te vinden dan één woning.** Een renovatieproject ligt bij
   elkaar, en alle woningen van een project delen bouwjaar, oppervlak, type en weerstation. Wie
   weet dat een project minstens 64 woningen telt, zoekt postcodegebieden (PC4) met zoveel
   passende woningen: voor 9 van de 19 projecten met een oppervlak blijven er **hoogstens 3**
   gebieden over, voor de projecten boven 40 woningen in de mediaan 2 (zie
   [Blok in plaats van woning](#blok-in-plaats-van-woning)). Indicatief: een project kan over meer
   postcodegebieden verspreid liggen.
4. **De aanname "label A na renovatie" past niet bij deze data.** Met die aanname komen 20 woningen
   onder k = 11, maar er staan in de populatie dan minder woningen met dat label dan er in de
   dataset zitten: veel woningen hebben na renovatie geen nieuw label laten registreren. s2 laat
   alleen zien dat extra kennis het risico kan laten oplopen.

## Advies

Het weerstation blijft staan. Twee punten:

1. **Overweeg bouwjaar af te ronden op 10 jaar en oppervlak op 20 m²** (nu 5 jaar en 5 m²). Voor
   één woning is dat niet nodig (bevinding 1), maar het maakt het blok moeilijker te vinden: nog 1
   project (nu 9) met hoogstens 3 passende postcodegebieden. Ook dan halen alle 898 woningen de
   norm, met k ten minste 1.232. Of dat de bruikbaarheid waard is, is een afweging voor de
   bronhouder. Doe het zo dat de nieuwe versie niets toevoegt aan de huidige: rond de
   **gepubliceerde** waarden (al afgerond op 5 jaar en 5 m²) verder af, niet de oorspronkelijke.
   Wie dan beide versies heeft, weet niets meer dan uit de huidige. Rond je de oorspronkelijke
   waarden af, dan kan de nieuwe versie een gepubliceerde 1955 splitsen in "1953-1954" en
   "1955-1957": smaller dan in elk van beide versies. Schrijf de klassen in het codeboek zo dat ze
   elkaar uitsluiten (bijvoorbeeld 1945-1954, 1955-1964). Het advies verlaagt ook de
   deelnameonthulling: zie [Deelnameonthulling](#deelnameonthulling-δ).
2. **Publiceer één versie.** Laat de huidige versie niet naast een nieuwe staan: wie beide heeft,
   legt de klassen over elkaar en krijgt smallere klassen dan elk van beide. Toets een nieuwe
   versie voordat hij verschijnt.

| scenario | haalt de norm | te herleidbaar |
|---|---:|---:|
| a1, advies | 898 (100%) | 0 |

### Deelnameonthulling (δ)

Hoe erg het is als bekend wordt *dát* een woning meedoet, hangt af van wat meedoen verraadt. Dat
kan alleen de bronhouder beoordelen. AnonyMate laat daarom bij de norm kiezen:

- **meedoen is niet gevoelig, of al bekend** (standaard): δ wordt gemeld en gemarkeerd vanaf 50%,
  waar meedoen minstens zo waarschijnlijk is als niet meedoen; een woning wordt alleen op k
  beoordeeld;
- **meedoen is zelf gevoelig:** dan moet ook δ ≤ 9% gelden (δ ≤ p, dezelfde grens als voor k).

| scenario | δ ≥ 50% (gemarkeerd) | δ > 9% | haalt de norm als meedoen gevoelig is | δ maximaal |
|---|---:|---:|---:|---:|
| s0, zonder weerstation | 0 | 0 | 848 (100%) | 2% |
| **s1, de dataset zoals hij nu is** | **0** | **666** | **232 (26%)** | **48%** |
| s1b, ruime marge | 0 | 0 | 898 (100%) | 4% |
| a1, advies | 0 | 0 | 898 (100%) | 5% |

Lezen:

- **Dit is de keerzijde van bevinding 3.** Een project ligt bij elkaar en deelt alle kenmerken, dus
  de gelijke woningen in een stationsgebied zijn voor een groot deel de woningen van het project
  zelf. In de huidige versie is dat voor sommige woningen bijna de helft: wie zo'n woning kent,
  weet met bijna 50% kans dat ze meedoet. Gemarkeerd (vanaf 50%) is nog geen enkele woning, maar
  het scheelt weinig.
- **Als meedoen gevoelig is,** haalt in de huidige versie maar een kwart van de woningen de norm.
- **Het advies lost dat op:** met bouwjaar op 10 jaar en oppervlak op 20 m² blijft δ overal onder
  9%, ook onder de strenge keuze. Ruis op de locatie zou niet helpen, want het hele project blijft
  bij elkaar.

Of meedoen gevoelig is, is aan de bronhouder. Dat de woningen zijn gerenoveerd naar of richting
aardgasvrij, zegt weinig; dat ze van een corporatie komen en welk verbruik ze hebben, zegt meer.
s2 (label A als aanname) staat niet in de tabel: daar zijn er in de populatie minder passende
woningen dan in de dataset (bevinding 4), zodat δ boven 100% uitkomt en niets betekent.

## Buiten deze analyse: insiders

Wie een woning al uit eigen administratie of werk kent, zit niet in de analyse hierboven. Voor
sommige insiders kan een kenmerk dat alleen zij kennen (het jaarverbruik voor de energieleverancier,
het toestel voor de installateur) toch een sleutel zijn. Een paar maatregelen kosten vrijwel geen
bruikbaarheid:

- **Verschillen per interval in plaats van meterstanden**, zo dat de verschillen optellen tot de
  juiste totalen over langere perioden, ook over gaten in de reeks heen. Een meterstand is een getal
  dat de netbeheerder of leverancier zelf ook heeft; een verschil per interval bevat dezelfde
  informatie voor analyse.
- **Geen nummers uit andere systemen:** geen EAN-codes, meternummers of serienummers.
- **Geen codes die ook elders voorkomen:** woning- en projectcodes die niet terugkomen in een andere
  dataset of een eerdere versie.

Voor andere kenmerken die alleen insiders kennen, zoals het exacte jaarverbruik, het afgiftesysteem
of het vermogen, is afronden of weglaten niet vanzelf beter: voor onderzoekers zijn juist die
gegevens vaak waardevol. Dat is een afweging voor de bronhouder tussen het nut voor onderzoek en het
risico bij insiders. Deze analyse doet daar geen uitspraak over.

## Kanttekeningen

- **Deelnameonthulling (δ)** is geteld uit de toets van 10-10-2026, volgens de keuze die AnonyMate
  sinds 18-10-2026 bij de norm biedt (melden en markeren vanaf 50%, of δ ≤ p). Of meedoen in dit
  project gevoelig is, is aan de bronhouder; zie [Deelnameonthulling](#deelnameonthulling-δ).
  Omdat de echte populatie kleiner is dan hier getoetst (zie hieronder), is ook δ een ondergrens.
- **De echte populatie is kleiner dan hier getoetst.** De woningen komen uit renovatieprojecten van
  corporaties en bouwers. Dat staat in geen register, dus de populatie is hier de hele woningvoorraad
  van dat type. Een aanvaller met die kennis heeft een kleinere populatie en dus een lagere k. De
  cijfers zijn daarom een ondergrens van het risico. s2 probeert dit te benaderen met het label,
  maar dat past niet bij de data (bevinding 4).
- **Het weerstation per project** komt uit de dataset; de koppeling van stationsnaam aan
  stationsnummer is gedaan met de KNMI-lijst. "Rotterdam Geulhaven" is gelezen als het huidige
  station 344 (Rotterdam); dat is een aanname.
- **Typologie en afbakening.** Grondgebonden is gelezen als eengezins, portiekflat als meergezins.
  De BAG is van 2026, de woningen zijn gerenoveerd in 2015 tot 2020: bouwjaar verandert niet, maar
  sloop en nieuwbouw wel.
- **Het oppervlak is een gemiddelde per project**, geen waarde per woning; s1b toetst daarom ook met
  ±10 m². Eén woning heeft geen oppervlak en telt in de analyse van postcodegebieden niet mee.
- **De tijdreeksen zijn niet getoetst.**
- **Blok in plaats van woning** (bevinding 3) is een eigen berekening naast AnonyMate, met de
  populatie van AnonyMate; het neemt aan dat een project in één postcodegebied ligt.
- **Eigen opgave tegenover register.** De projectkenmerken komen van de dataleveranciers en kunnen
  afwijken van de registers. Een aanvaller die niets vindt, laat het minst betrouwbare kenmerk weg.

## Blok in plaats van woning

Voor elk project het aantal PC4-gebieden binnen het stationsgebied waar minstens zoveel woningen
met dezelfde kenmerken staan als het project woningen heeft (het aantal woningen met monitoring,
een ondergrens voor de echte grootte). Minimum, mediaan en maximum per grootteklasse:

| projectgrootte | projecten | gebieden, huidige publicatie | gebieden, advies |
|---|---:|---|---|
| tot 10 woningen | 7 | 13, 20, 43 | 33, 73, 103 |
| 11 tot 40 | 3 | 0, 3, 17 | 24, 46, 64 |
| boven 40 | 9 | 0, 2, 14 | 3, 18, 53 |

Bij "0 gebieden" past het project in geen enkel PC4-gebied met zoveel woningen: het ligt dan over
meer gebieden verspreid, of de woningen zijn minder gelijk dan de afronding doet vermoeden.

## Bijlage voor de bronhouder

Een lijst met kandidaat-adressen per project is **niet gemaakt**: de adressen per project zijn
precies wat de dataleveranciers hebben verhuld. De lijst kan met `anonymate assess --kandidaten`
worden gemaakt en alleen aan de bronhouder worden gegeven, buiten git, onder de naam
`bijlage_NIET_PUBLICEREN`.

## Hertoets met een nieuwere AnonyMate (10-10-2026)

Alle scenario's zijn op 10-10-2026 herhaald met AnonyMate `4e55ae0` (onder meer met de controle
op klassegrenzen en afgeronde waarden). De uitkomsten zijn voor elk scenario gelijk aan die
hierboven. De nieuwe controle meldt wel iets over het advies: de klassen na afronden op 10 jaar en
20 m² delen hun grenzen (`1945-1955` naast `1955-1965`), zodat een woning van precies 1955 in
beide valt. Zie de aanvulling bij het advies. De overige meldingen (gaten en overlap tussen
klassen) komen van de marges die de toets zelf rond de afgeronde waarden legt.

## Reproduceren

Voorwaarde: de ruwe data en de verwerkte tabellen in `data/` (zie [`README.md`](https://github.com/duurzaamleven/wattopia-dataset-preprocessing/blob/main/README.md)) en
een lokale AnonyMate met populatie (`anonymate ingest all` en `anonymate build`, enkele uren; BAG,
EP-online met API-sleutel, gebieden, KNMI).

```bash
bash analyse/herleidbaarheid/draai.sh /pad/naar/anonymate.exe
```

`draai.sh` maakt de invoer, schrijft de configuraties, toetst elk scenario en schrijft de tellingen
naar `analyse/herleidbaarheid/uitvoer/samenvatting.md`. De analyse van postcodegebieden draait met
de Python van AnonyMate: `python analyse/herleidbaarheid/kandidaatgebieden.py` en met het argument
`_advies`. Alles met regels per woning staat in `uitvoer/`, dat in `.gitignore` staat.

## Melding

De gebruiksvoorwaarden vragen het doel en het gebruik van de dataset te melden aan Wattopia
(zie [`GEBRUIKSVOORWAARDEN.md`](https://github.com/duurzaamleven/wattopia-dataset-preprocessing/blob/main/GEBRUIKSVOORWAARDEN.md)). Een herleidbaarheidstoets valt daaronder.
