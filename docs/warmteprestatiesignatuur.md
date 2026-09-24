# Warmteprestatiesignatuur publiceren zonder woningen herleidbaar te maken

Een *warmteprestatiesignatuur* vat een woning samen in een paar effectieve parameters: de
warmteoverdrachtscoëfficiënt H [W/K], de thermische massa C [Wh/K], de tijdconstante τ = C/H [h],
de zonnetoetreding A_sol [m²] en de infiltratie-opening A_inf [cm²]. Met meetdata kan een model
die per woning **leren**. Maar dezelfde parameters zijn voor elke eengezinswoning in Nederland ook
te **berekenen** uit openbare gegevens: bouwjaar en gebruiksoppervlakte (BAG), schiloppervlakken
(3D-BAG) en forfaitaire waarden (NTA 8800, RVO-voorbeeldwoningen).

## Het probleem: een rainbow table

Die berekening is deterministisch en openbaar. Een aanvaller kan hem dus voor alle ~5 miljoen
eengezinswoningen uitvoeren en een tabel maken van signatuur naar adres. Wie daarna een
signatuur publiceert, publiceert in feite een sleutel in die tabel:

* **de berekende signatuur zelf** komt exact overeen met één regel in de tabel;
* **een geleerde signatuur** wijkt af van de berekende, maar niet willekeurig: de aanvaller zoekt
  woningen waarvan de berekende waarde binnen de modelfout ligt;
* **C verraadt de gebruiksoppervlakte**: C is de specifieke massa per bouwperiode maal de
  oppervlakte, dus C en de bouwperiode samen geven de oppervlakte tot op de vierkante meter;
* **samen met andere kenmerken** (weerstation, H3-cel, woningtype) wordt de groep kleiner.

anonymate berekent daarom bij `anonymate build` de baseline-signatuur voor elke eengezinswoning
(kolommen `sig_H`, `sig_C`, `sig_tau`, `sig_Asol`; zie
[`src/anonymate/signature.py`](../src/anonymate/signature.py)) en behandelt een gepubliceerde
signatuur als quasi-identifier (`warmteverlies`, `thermische_massa`, `tijdconstante`,
`zonnetoetreding`).

## Twee baselines: NTA 8800 en Maatwerkadvies

NTA 8800 is een handhavingsinstrument; de forfaitaire waarden zijn bewust conservatief. Het
Maatwerkadvies (Van den Brom e.a., 2022, validatierapportage in opdracht van RVO) corrigeert een
deel daarvan richting werkelijk gebruik. Vier correcties raken de signatuur: Rc + 0,15 m²K/W op
gevel, vloer en dak, U van ramen en deuren × 0,9, de b-factor van de vloer boven de kruipruimte
× 0,7 en infiltratie × 0,5. anonymate rekent beide uit (`sig_*` en `sig_mwa_*`; QID's
`warmteverlies_mwa` en `tijdconstante_mwa`).

* **Voor de vergelijking** is de MWA-baseline de eerlijke tegenstander: wie een conservatieve
  NTA-baseline verslaat, bewijst weinig.
* **Voor de privacy** is de MWA-baseline de *betere* rainbow table: hoe dichter de berekende
  waarde bij de werkelijke ligt, hoe preciezer een gepubliceerde geleerde waarde terug te vinden
  is. Meet de tolerantie hieronder daarom af aan het verschil met de baseline die het dichtst bij
  de geleerde waarden ligt.

## De beste openbare schatting (`best`)

De derde variant gebruikt alles wat openbaar per adres te vinden is:

1. **Huidige staat in plaats van bouwstaat**: de U-waarden en beglazing van de passende
   RVO-voorbeeldwoning in de *huidige* staat (WoON2018), niet de oorspronkelijke. Voor woningen
   van vóór 1965 scheelt dat 25-40% in H.
2. **Kalibratie op het eigen label**: ruim 3,4 miljoen labels zijn berekend volgens NTA 8800 en
   bevatten de netto warmtebehoefte per m². Gecorrigeerd voor het verschil in compactheid met de
   voorbeeldwoning, plaatst die de woning op de schaal *bouwstaat → huidig → besparingspakket 1 →
   pakket 3*; U-waarden en beglazing worden daartussen geïnterpoleerd. Oudere labels geven alleen
   een duwtje via de labelklasse; zonder label geldt de huidige staat.
3. **Maatwerkadvies-correcties** erbovenop, omdat de schatting werkelijk gedrag moet beschrijven.

## Het label als bron van de schil (`ep`, `ep_3dbag`)

3D-BAG meet het hele pand: ook een onverwarmde zolder, een aangebouwde berging, de gevel tot de
nok. Het energielabel meet de **thermische schil**: EP-online publiceert per label de compactheid
(verliesoppervlak / gebruiksoppervlak) en het gebruiksoppervlak, en daarmee het verliesoppervlak.
Over 1,4 miljoen eengezinswoningen met een NTA 8800-label is de schil uit 3D-BAG in de mediaan
**1,26 keer** het verliesoppervlak uit het label (tussenwoning 1,21, hoekwoning 1,27, vrijstaand
1,36; populatie van september 2026). `best` rekent dus met een te grote schil.

* **`ep`**: `best` zonder 3D-BAG. Het verliesoppervlak uit het label, verdeeld over gevel, raam,
  deur, dak en vloer zoals bij de voorbeeldwoning; de warmtecapaciteit uit het gebruiksoppervlak
  van het label. Alleen voor woningen met een label met compactheid.
* **`ep_3dbag`**: de verhoudingen van dit pand uit 3D-BAG, de omvang uit het label: de
  3D-BAG-schil geschaald naar het verliesoppervlak van het label.

Het isolatieniveau (U-waarden, beglazing) komt bij alle drie uit dezelfde kalibratie op de
warmtebehoefte, dus `best` − `ep` meet precies wat 3D-BAG aan het label toevoegt.

Geprobeerd en verworpen: H rechtstreeks uit de warmtebehoefte terugrekenen met een
regressiemodel, gekalibreerd op de RVO-voorbeeldwoningen. Buiten de kalibratie was dat niet beter
dan de voorbeeldwoning zelf (mediane fout 14%), en alleen dankzij een zonterm met het verkeerde
teken: de besparingspakketten veranderen ook de ventilatie, en die staat niet in de dataset. Een
echte inversie vraagt de maandmethode van NTA 8800 met gecontroleerde constanten.

## Dezelfde grootheid als een geleerde signatuur

Een leermodel dat H schat uit gasverbruik en één gemeten binnentemperatuur, zonder gemeten
ventilatiedebiet, vindt één H voor alle verliezen die met binnen- minus buitentemperatuur
schalen, ten opzichte van de kamer waar gemeten wordt. De berekende H is transmissie door de schil,
ten opzichte van de gemiddelde binnentemperatuur. `signature.as_learned` zet een berekende
signatuur om:

* **+ ventilatie**: NTA 8800-debiet voor systeem C1 (tabel 11.8, vgl. 11.22, 11.56, 7.19), maal
  de Maatwerkadvies-correctie 0,5 (systeem C; het rapport geeft 0,25 voor A tot 0,75 voor D);
* **× (gemiddelde binnen − buiten) / (thermostaatkamer − buiten)**: 18,33 en 6,44 °C (stookseizoen,
  afgeleid uit het NTA 8800-referentieklimaat, zoals in `needforheat-diagnosis-software`) en een
  aangenomen 20 °C in de thermostaatkamer.

A_sol is aan beide kanten al gelijk gedefinieerd (winst = globale horizontale instraling ×
A_sol). De berekende A_sol volgt NTA 8800 (glasaandeel 0,70, F_w 0,9, F_sh 0,9) en rekent een
verticaal vlak om met de verhouding verticale / horizontale instraling: **0,731**, naar energie
gewogen over het stookseizoen (oktober-april) van het NTA 8800-referentieklimaat, ramen gelijk
verdeeld over de windrichtingen. Een eerder gebruikte waarde (1,1543, uit een openbaar
rekenwerkblad) was de omgekeerde verhouding (horizontaal / verticaal), per maand gemiddeld in
plaats van naar energie gewogen, en zette A_sol ongeveer 1,6 keer te hoog; met de ontbrekende
reducties voor het glas samen ongeveer 2,5 keer. C niet: een geleerde C is de massa die in de dagelijkse dynamiek meedoet, de berekende de
effectieve interne warmtecapaciteit uit de NTA 8800-tabel per bouwwijze (tabel 7.10). Een leermodel
schat bovendien τ, niet C; vergelijk dus op (H, τ, A_sol). Voor oudere woningen maakt de tabel τ
veel te kort: gemeten uit thermostaatdata van 1319 woningen (Vosmer, 2018, via TNO 2019 P10600,
tabel 13) is τ gemiddeld 40, 50, 57 en 71 h voor bouwjaar vóór 1976, 1976-1988, 1989-2000 en
vanaf 2001, tegen 14, 28, 49 en 80 h berekend (Van den Ham & Van der Vliet, 2013).
`as_learned(..., tau="gemeten", construction_year=...)` zet τ op die gemeten klassewaarde en C op
τ · H. Dat verbetert het niveau voor oude woningen, niet de volgorde binnen een klasse. Infiltratie blijft aan beide kanten
buiten H (een leermodel zet die meestal vast op een landelijk gemiddelde).

Welke methode de eerlijke baseline is, is een inhoudelijke vraag die je beantwoordt door te
vergelijken met gemeten woningen (kladbloknotitie 1), in de definitie van `as_learned`.

## De signatuur los gebruiken

De berekening staat op zichzelf ([`signature.py`](../src/anonymate/signature.py)) en werkt
offline op de lokale populatie:

```bash
anonymate signatuur adres 1234AB 12                  # één adres, alle methodes, met details
anonymate signatuur tabel --out signaturen.parquet   # alle eengezinswoningen, per methode
anonymate signatuur tabel --detail --methode best    # ook oppervlakken, U-waarden, bron
```

De tabel heeft per woning de BAG-sleutel en het adres, en per methode elke uitkomst in een
eigen kolom (`nta8800_H`, `mwa_tau`, `best_Asol`, ...). In Python: `signature.compute(df,
"best", detail=True)` op een eigen tabel met registergegevens.

## De rainbow table zelf: alleen een frequentietabel

Voor de herleidbaarheid zijn geen adressen nodig, alleen hoeveel woningen dezelfde afgeronde
signatuur delen:

```bash
anonymate signatuur regenboog --scope eengezins=true \
    --stap warmteverlies_best=10 --stap thermische_massa=1000 --ook knmi_station \
    --out regenboog.parquet
```

Dat levert per afrondschema een tabel `hash → aantal woningen` (md5 van de afgeronde waarden).
Een gepubliceerd record zoek je op met `rounding.rainbow_key` en hetzelfde schema. Zo'n tabel
zegt *hoeveel* woningen een record kunnen zijn, niet *welke*: hij is zelf geen aanvalsinstrument.

## Publiceren: een adresgebaseerde signatuur als baseline per woning

Het doel van publiceren is vaak een eerlijke vergelijking: *levert een datagedreven signatuur
echt een beter resultaat dan een die je alleen uit het adres had kunnen afleiden?* Daarvoor
publiceer je per woning, naast de meetdata en de geleerde signatuur, ook de adresgebaseerde
signatuur, en het algoritme dat hem berekent. Het adres zelf publiceer je natuurlijk niet.

**Kies een goed algoritme.** Het zou flauw zijn om een slechte baseline te nemen. Toets de
kandidaten (`nta8800`, `mwa`, `best`, en varianten zoals met of zonder correctie voor het
stedelijk hitte-eiland) tegen gemeten woningen en kies de beste; zie
[kladbloknotitie 1](werk/KLADBLOK.md).

**Weet wat je daarmee weggeeft.** Omdat het algoritme openbaar is, is de gepubliceerde baseline
voor een aanvaller geen schatting maar een *exacte sleutel*: hij rekent de signatuur voor elke
woning uit, rondt op dezelfde manier af en kijkt wie in hetzelfde vakje valt. Precies dat telt
de rainbow-frequentietabel. De geleerde signatuur komt daar als extra, minder precies kenmerk
bij (met een tolerantie ter grootte van de modelfout).

## Werkwijze: eerst de norm, dan toetsen, dan afwegen

De volgorde doet ertoe, ethisch en juridisch:

**1. Stel eerst de privacynorm vast.** De maximale kans op heridentificatie die je aanvaardbaar
vindt (p, en daarmee k ≥ round(1/p)), vóór je naar uitkomsten kijkt. De norm pas je niet aan op
de uitkomst. `anonymate signatuur publiceer` weigert te werken zonder expliciete `--p`; in het
desktopvenster moet je de norm eerst vastleggen, en daarna zit hij op slot voor die dataset.

**2. Toets.** Voeg per woning de afgeronde adres-signatuur toe en toets die samen met alle
andere gepubliceerde kenmerken (weerzone, bouwjaarklasse, ...). Een waarde afgerond op stap *s*
telt als "ligt binnen ±*s*/2"; dat is dezelfde afronding als in de rainbow table.

```bash
anonymate signatuur publiceer data.csv --koppel postcode,huisnummer --p 0.09 \
    --methode best --stap H=50 --stap C=5000 --qid weerzone=h3_cel --out uitvoer
```

**3. Weeg af, binnen de norm.** Twee knoppen, die je tegen elkaar afweegt:

* **Afronden** (privacy tegen bruikbaarheid): grover afronden maakt groepen groter en kost
  precisie in de vergelijking.
* **Woningen niet publiceren**: woningen die ook na redelijk afronden te herleidbaar blijven,
  laat je weg. `publiceerbaar.csv` bevat alleen de woningen die de toets halen; het rapport
  vermeldt hoeveel er afvallen.

```bash
anonymate signatuur publiceer data.csv --koppel postcode,huisnummer --p 0.09 \
    --methode best --verken H=10,25,50,100 --verken C=1000,2500,5000
```

geeft per combinatie van stappen het aantal publiceerbare woningen en het precisieverlies
(gemiddelde relatieve afrondfout). Kies daaruit; de norm blijft staan.

Vooraf, zonder dataset, laat `anonymate afronding` (of `signatuur regenboog`) zien hoe groot de
groepen in de hele populatie of in een afgebakend deel ervan worden; met `--bron` en `--scope`
vanuit de functionele tabel, voor de publiek bekende inclusie- en exclusiecriteria van de dataset:

```bash
anonymate afronding --bron signaturen_nl.parquet --scope oppervlakte=50-250 \
    --scope woningtype!=appartement --kolom warmteverlies_best=25,50,100 \
    --kolom thermische_massa=2500,5000 --ook h3_r4
```

## Een geleerde signatuur naast de baseline

Wordt de baseline per woning gepubliceerd, dan bepaalt **die** de herleidbaarheid voor een
aanvaller met alleen registers: hij rekent haar voor elke woning uit, en de echte woning zit altijd
in het vakje met de gepubliceerde waarde. De geleerde signatuur kan hij voor de andere kandidaten
niet uitrekenen, dus binnen dat vakje helpt ze hem nauwelijks verder. Ze telt wel voor wie zelf
metingen van de woning heeft (energieleverancier, netbeheerder, thermostaatleverancier): toets
daarvoor het insiderscenario. Publiceer niet de verhouding geleerd/berekend naast de geleerde
waarde: samen onthullen ze de berekende, en daarmee de sleutel.

## Een geleerde signatuur zonder baseline publiceren

Wie de baseline niet per woning publiceert, toetst de geleerde signatuur als quasi-identifier met
een tolerantie: een aanvaller rekent de baseline voor alle woningen uit en zoekt binnen die marge
rond de gepubliceerde geleerde waarde.

```toml
[qids]
H_geleerd__W_K_1 = "warmteverlies_best"
C_geleerd__Wh_K_1 = "thermische_massa"

[tolerantie]
H_geleerd__W_K_1 = 150      # halve afrondstap + P90 van |geleerd - berekend|
C_geleerd__Wh_K_1 = 15000
```

**Kies de tolerantie ruim**: groot genoeg dat de echte woning er vrijwel altijd binnen valt,
bijvoorbeeld een halve afrondstap plus de 90e percentiel van |geleerd − berekend|, gemeten tegen de
baseline die er het dichtst bij ligt, en na correctie voor een systematische afwijking (een
aanvaller die die kent, corrigeert ervoor). Een smallere tolerantie lijkt strenger, maar is
ongeldig: de groep die geteld wordt bevat de echte woning dan vaak niet, en de toets meldt risico's
die er niet zijn en mist de echte.

A_inf wordt in de baselines als landelijk gemiddelde gezet en geeft dus geen informatie; een
geleerde A_inf is een kenmerk zonder register en telt alleen via de schatting mee.
