# Warmtesignatuur publiceren zonder woningen herleidbaar te maken

Een *warmtesignatuur* vat een woning samen in een paar effectieve parameters: de
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
(kolommen `sig_H__W_K_1`, `sig_C__Wh_K_1`, `sig_tau__h`, `sig_Asol__m2`, `sig_Ainf__cm2`; zie
[`src/anonymate/signature.py`](../src/anonymate/signature.py)) en behandelt een gepubliceerde
signatuur als quasi-identifier (`warmteverlies`, `thermische_massa`, `tijdconstante`,
`zonnetoetreding`, `infiltratie`).

Ook de infiltratie-apertuur A_inf is een quasi-identifier: hij volgt per woning uit het bouwjaar,
de gebruiksoppervlakte, het woningtype en het aantal bouwlagen (NTA 8800), allemaal openbaar, dus
een aanvaller rekent hem net zo na als H, τ en A_sol. Publiceer A_inf daarom grof (bijvoorbeeld
per 10 cm², stap `Ainf` in de signatuurstap) of helemaal niet; de standaardstap is 0 (niet
publiceren).

Hoeveel A_inf prijsgeeft, is gemeten op alle 2,69 miljoen eengezinswoningen met woningtype en
`best`-signatuur (alleen totalen; A_inf per woning zoals `signature.infiltration` hem berekent).
A_inf is vrijwel een functie van gebruiksoppervlakte × bouwperiode × woningtype: van de 4,5 bits
onzekerheid over bouwperiode en woningtype samen haalt A_inf (stap 25 cm²) er 0,9 af, en naast
oppervlakte (stap 10 m²) en H (stap 25 W/K) nog eens 0,9. Naast H maakt dat veel uit:

| gepubliceerd naast de postcode (PC4) | aandeel woningen met k < 11 |
|---|---|
| H per 50 W/K | 5,6% |
| H per 50 W/K + A_inf per 100 cm² | 16% |
| H per 50 W/K + A_inf per 50 cm² | 22% |
| H per 50 W/K + A_inf per 10 cm² | 47% |

Met het KNMI-station als enige locatie: 0,16% zonder A_inf, 1,3% met A_inf per 100 cm² en 4,4%
per 10 cm². Advies: A_inf niet naast H publiceren; wie infiltratie nodig heeft, gebruikt het
landelijke gemiddelde of rekent hem zelf uit bouwjaar, oppervlakte en type na. Per methode heeft
A_inf een eigen kolom (`sig_mwa_Ainf__cm2`, `sig_best_Ainf__cm2`, ...), ook
in het datapakket (`sig_nta8800_Ainf__cm2`, `sig_mwa_Ainf__cm2`). De namen volgen de
[physiquant__unit-conventie](variabelen.md).

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

## Infiltratie per woning (A_inf)

A_inf [cm²] is de effectieve windapertuur van een leermodel waarin het infiltratiedebiet gelijk
is aan windsnelheid · A_inf (warmteverlies ≈ ρ·c_p · v · A_inf · ΔT; 1 cm² · 1 m/s = 0,1 L/s).
De baseline rekent hem per woning uit, in vier stappen (`signature.py`):

1. **Forfaitaire luchtdichtheid**, NTA 8800 vgl. (11.86): `q_v;10 = f_type · f_y · q_spec`
   [dm³/(s·m²)], genormeerd op de **gebruiksoppervlakte** A_g (§11.2.5, vgl. 11.85, opmerking 2;
   NEN 2686), niet op het schiloppervlak. f_y (tabel 11.13) naar bouwjaar: vóór 1970 3,0; 1970 2,5;
   1980 2,0; 1990 1,5; 2000 1,0; 2010 en later 0,7. q_spec (tabel 11.14, eengezins): 1,0 met
   schuin dak, 0,7 met plat dak (daktype uit 3D-BAG; onbekend telt als schuin, de hoge, voorzichtige
   waarde). f_type (tabel 11.14): tussenwoning 1,0, hoekwoning 1,2, twee-onder-een-kap 1,2,
   vrijstaand 1,4. Deze waarden reproduceren de q_v;10-ladder 3,0 / 1,8 / 1,2 / 0,7 / 0,4 van het
   openbare Hestia-model van het PBL en de RVO-voorbeeldwoningen (0,7 en 0,4 in hun pakketten).
2. **Lekdebiet naar effectief lekoppervlak**: `q10 = q_v;10 · A_g` [L/s] bij 10 Pa; stroomwet
   `q ∝ Δp^n` met n = 0,67 terug naar 4 Pa; `ELA = q4 / √(2·Δp/ρ)` met Δp = 4 Pa, ρ = 1,2 kg/m³
   en uitstroomcoëfficiënt 1.
3. **LBL-model** (Sherman & Grimsrud; ASHRAE Handbook of Fundamentals, hoofdstuk infiltratie,
   afschermingsklasse 3, voorstedelijk): `debiet [L/s] = ELA [cm²] · √(C_s·ΔT + C_w·v²)` met C_s
   0,000145 / 0,000290 / 0,000435 en C_w 0,000319 / 0,000420 / 0,000494 voor 1 / 2 / 3 bouwlagen
   (bouwlagen uit 3D-BAG, begrensd op 1..3, onbekend telt als 2).
4. **Linearisatie** tot de A_inf van het leermodel, zó dat het warmteverlies over een stookseizoen
   gelijk is: `A_inf = 10 · Σ debiet_LBL·ΔT / Σ v·ΔT = ELA · k`. De constanten k (1 / 2 / 3
   bouwlagen: 0,2300 / 0,2877 / 0,3310) komen uit KNMI-uurgegevens van De Bilt (260), stookseizoen
   oktober 2025 t/m april 2026, T_binnen 20 °C, uren met ΔT > 0. De invoer staat in
   [`data/knmi_260_uur_2025-26.csv`](data/knmi_260_uur_2025-26.csv), het script in
   [`tools/infiltratie_k.py`](../tools/infiltratie_k.py), en een test rekent k opnieuw na.

Maatwerkadvies (`mwa`, `best`, `ep`, `ep_3dbag`, `ep_cbag`): q_v;10 × 0,5 (Van den Brom e.a., 2022,
p. 26-27), dus ook A_inf × 0,5. Ontbreken jaar, oppervlakte of type, dan valt de berekening terug op
het landelijk gemiddelde (108 cm², met MWA 54); `detail=True` zegt dat in `Ainf_bron__str` en toont
verder `qv10__dm3_s_1_m_2`, `ELA__cm2` en `bouwlagenklasse__cat`. Op een steekproef van 125.000 eengezinswoningen uit de
lokale populatie is de mediaan 204 cm² (P10 89, P90 417) voor `nta8800` en 102 cm² (P10 44, P90 209)
voor `mwa`/`best`, tegen 108 en 54 eerder.

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

**Twee oppervlakken, niet hetzelfde.** De *gebruiksoppervlakte* in de BAG is die van het
verblijfsobject volgens de NEN 2580-meetregels, zoals de gemeente hem registreert. De
*gebruiksoppervlakte A_g* van het energielabel (NTA 8800) is die van de verwarmde (thermische)
zone waarvoor het label is berekend: een onverwarmde zolder of berging telt daar niet mee, een
verwarmde uitbouw die (nog) niet in de BAG staat wel. Ze verschillen soms tientallen m², in beide
richtingen. `nta8800` en `mwa` rekenen met de BAG-oppervlakte; `ep` en `ep_3dbag` met A_g, en vallen
terug op de BAG-oppervlakte als het label geen A_g heeft. Met `detail=True` staat per woning welke
gebruikt is (`oppervlakte_gebruikt__m2`, `oppervlakte_bron__str`). Wie de signatuur naast een gepubliceerde
oppervlakteklasse zet, moet weten welke van de twee dat is: zie
[kladbloknotitie 4](werk/KLADBLOK.md#kladbloknotitie-4-thermische-massa-uit-het-label-of-uit-de-bag-todo).

## A_sol per gevelrichting

De signatuur rekent A_sol als *effectieve horizontale zonnetoetreding*: een leermodel schat de
zonwinst als A_sol × globale horizontale instraling (GHI, KNMI). Een raam op een verticaal vlak
vangt daar een richtingsafhankelijk deel van: zuid veel, noord weinig. Wat de methoden doen:

* **`nta8800` en `mwa`: gemiddeld over de richtingen**, met één verhouding verticaal / horizontaal
  van **0,731** (ramen gelijk over noord, oost, zuid en west, zoals in de RVO-voorbeeldwoningen).
  Dat is bewust: zo blijven deze twee standaardconform en vergelijkbaar met de voorbeeldwoningen.
* **`best`, `ep`, `ep_3dbag`, `passend` en de `_cbag`-varianten: per gevelrichting** van de
  woning zelf, als de contour van het pand bekend is. Anders geldt de gemiddelde verhouding van
  0,731; `detail=True` zegt dat in `asol_bron__str`.

**1. Instraling per richting, R_o.** Voor een verticaal vlak gericht op richting o (N, NO, O, ZO,
Z, ZW, W, NW): `R_o = Σ instraling op het vlak / Σ GHI`, over de uren van het stookseizoen
(oktober-april), naar energie gewogen, net als de 0,731. Uurgegevens van globale straling Q van
KNMI De Bilt (260), hetzelfde seizoen als bij A_inf (oktober 2025 t/m april 2026; J/cm² per uur
naar W/m²). Per uur: zonspositie volgens het NOAA-algoritme; GHI gesplitst in direct en diffuus
met de correlatie van Erbs e.a. (1982); transpositie naar het verticale vlak met Hay & Davies
(1980) (direct, circumsolair en isotroop diffuus) plus grondreflectie met albedo 0,2. Alles staat
in [`instraling.py`](../src/anonymate/instraling.py); pvlib is alleen in een test een referentie
(afwijking minder dan 2%).

| richting | N | NO | O | ZO | Z | ZW | W | NW |
|---|---|---|---|---|---|---|---|---|
| berekend uit KNMI | 0,298 | 0,384 | 0,655 | 1,009 | 1,188 | 1,017 | 0,660 | 0,382 |
| gebruikt (geschaald) | 0,311 | 0,401 | 0,684 | 1,053 | 1,241 | 1,061 | 0,689 | 0,399 |

Het gewone gemiddelde van N/O/Z/W van de berekende waarden is 0,700, tegen 0,731 van NTA 8800: een
ander klimaatjaar en een ander hemelmodel. De gebruikte waarden zijn daarom geschaald tot dat
gemiddelde 0,731 is: het patroon over de richtingen komt uit KNMI, het niveau uit NTA 8800. Zo komt
een verschil tussen nta8800 en best alleen door de gevelrichting, niet door het klimaatjaar. De
invoer staat in
[`data/knmi_260_straling_2025-26.csv`](data/knmi_260_straling_2025-26.csv), het script in
[`tools/instraling_r.py`](../tools/instraling_r.py), en een test rekent de acht waarden opnieuw na.
Eén winter is een bescheiden basis; de onzekerheid van de verhouding per richting door het
weerjaar is enkele procenten.

**2. Blootgestelde gevel per richting.** Uit de contour van het pand in de BAG (laag `pand` van
`bag-light.gpkg`, door `anonymate ingest bag` ingelezen in `raw/bag_pand_gevel.parquet`): per rand
de lengte en het kompasazimut van de buitennormaal, in acht sectoren van 45°. Randen die het pand
met een buurpand deelt tellen niet mee: een rand van een ander pand binnen 0,5 m en bijna
evenwijdig (minder dan 15°) maakt dat stuk van de rand tot scheidingsmuur; een deel van een rand
kan gedeeld zijn. Vermenigvuldigd met de wandhoogte (3D-BAG-hoogte, anders bouwlagen × 2,8 m,
anders twee bouwlagen) geeft dat `gevel_<richting>__m2` per woning in de populatie (alleen voor
panden met één woning). Het RD-raster staat hooguit ongeveer 2° scheef ten opzichte van het ware
noorden; daar wordt niet voor gecorrigeerd. [`gevel.py`](../src/anonymate/gevel.py).

**3. Ramen over de richtingen.** Het totale raamoppervlak blijft zoals het was (aandeel van de
voorbeeldwoning, of geschaald naar het label). Het wordt verdeeld over de richtingen naar het
blootgestelde gevelvlak, waarbij een **zijgevel telt met gewicht 0,5** (voor een vrijstaande
woning is alles gewicht 1). De hoofdas van het pand is de richting van de langste rand; een zijgevel
is een blootgestelde gevel met de normaal loodrecht op die as (hoek met de loodlijn hoogstens
45°), dus de lange zijmuur van een hoekwoning of twee-onder-een-kap, niet de voor- en achtergevel.
Dan geldt

`A_sol = Σ_o A_raam,o · (1 − 0,30) · g · F_w · F_sh · R_o + Σ_o A_wand,o · α · R_se · U · R_o + dak`

met de dichte wand en de deur op dezelfde manier per richting, en het dak ongewijzigd (horizontale
instraling). Bron: NTA 8800 (glasaandeel, F_w, F_sh, α, R_se).

**Wat het wel en niet doet.** Op 457.000 eengezinswoningen rond Utrecht (RD-vak 120-165 km x
445-485 km) gaf `best` met de ongeschaalde R_o een mediaan A_sol van 11,0 tegen 11,5 m² (P5-P95 van
de verhouding nieuw / oud 0,81-1,10; rangcorrelatie 0,97); die daling kwam vooral door het lagere
niveau van de ongeschaalde R_o, en valt met de schaling grotendeels weg. Woningen zonder
gevelrichting houden 0,731. Een rij van oost naar west (voor en achter op noord en zuid) krijgt
een ruim 10% hogere A_sol dan een rij van noord naar zuid (voor en achter op oost en west). Een
rijwoning met de achtergevel op het zuiden krijgt echter dezelfde A_sol als met de achtergevel op
het noorden: voor- en achtergevel hebben evenveel gevel, en de ramen volgen de gevel. Dat de
achterzijde vaak meer glas heeft, is niet openbaar. Beschaduwing door buren en de dakvlakken zijn
nog open ([kladbloknotitie 2](werk/KLADBLOK.md#kladbloknotitie-2-zonnetoetreding-beschaduwing-dakvlakken-en-referentieklimaat-todo)).
Een scherpere A_sol is ook een scherpere rainbow table.

**Bronnen:** Erbs, Klein & Duffie (1982), *Estimation of the diffuse radiation fraction for hourly,
daily and monthly-average global radiation*, Solar Energy 28(4); Hay & Davies (1980), *Calculation
of the solar radiation incident on an inclined surface*, Proc. First Canadian Solar Radiation Data
Workshop; NOAA Global Monitoring Laboratory, Solar Calculator; NEN-EN-ISO 52016-1 en NTA 8800.

## Per woning het meest passende algoritme (`passend`)

Niet elke woning heeft een label met compactheid. `passend` kiest daarom per woning, met een vaste
en openbare regel: **`ep` waar het label het toelaat, anders `best`**. Dat is de standaard bij
`anonymate signatuur publiceer`. Omdat de regel vastligt en openbaar is, rekent een aanvaller met
dezelfde registerversie precies dezelfde waarden uit; de rainbow table klopt dus, en de toets telt
ertegen. Leg bij publicatie de registerversie vast (EP-online-publicatiedatum, BAG-datum): een
later geregistreerd label verandert de keuze voor die woning.

De populatie draagt kolommen per methode (`sig_passend_H__W_K_1`, `sig_ep_C__Wh_K_1`, ...). Na een wijziging in
de berekening zet `anonymate build --signaturen` alleen die kolommen opnieuw, zonder de hele
populatie te herbouwen; `anonymate signatuur tabel` maakt de functionele tabel met alle methodes.

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
* **stedelijk hitte-eiland** (`uhi`, `uhi_share`): een leermodel dat de buitentemperatuur van een
  KNMI-station gebruikt, ziet een stadswoning minder warmte verliezen dan het station doet
  vermoeden, en schat dus een kleinere H. In de factor hierboven stijgt de buitentemperatuur met
  `uhi_share · uhi` (RIVM-kaart, een zomergemiddelde; welk deel ervan in het stookseizoen geldt,
  is niet bekend, vandaar de varianten 0, 0,5 en 1, kladbloknotitie 5). Over alle
  eengezinswoningen is de RIVM-waarde per postcode gemiddeld 0,85 K (mediaan 0,82; 38% boven 1 K,
  11% boven 1,5 K). Bij 100% wordt H daardoor in de mediaan 7% kleiner, bij het negentigste
  percentiel 13%.

A_sol is aan beide kanten al gelijk gedefinieerd (winst = globale horizontale instraling ×
A_sol). De berekende A_sol volgt NTA 8800 (glasaandeel 0,70, F_w 0,9, F_sh 0,9) en rekent een
verticaal vlak om met de verhouding verticale / horizontale instraling: **0,731**, naar energie
gewogen over het stookseizoen (oktober-april) van het NTA 8800-referentieklimaat, ramen gelijk
verdeeld over de windrichtingen (`nta8800`, `mwa`; de andere methoden rekenen per gevelrichting,
zie boven). Een eerder gebruikte waarde (1,1543, uit een openbaar
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
eigen kolom (`nta8800_H__W_K_1`, `mwa_tau__h`, `best_Asol__m2`, ...). In Python: `signature.compute(df,
"best", detail=True)` op een eigen tabel met registergegevens (kolommen met de namen van
[docs/variabelen.md](variabelen.md), bijvoorbeeld `bouwjaar__yr`); het resultaat heeft `H__W_K_1`,
`C__Wh_K_1`, `tau__h`, `Asol__m2` en `Ainf__cm2`.

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

Of in één keer, met de kolommen en een rooster die AnonyMate zelf kiest:

```bash
anonymate signatuur publiceer data.csv --koppel auto --auto --p 0.09 \
    --scope eengezins=true --verken standaard
```

* `--koppel auto` zoekt de kolommen voor BAG-id, of postcode, huisnummer, huisletter en
  toevoeging, en meldt welke het neemt (alleen kolomnamen). Twijfelt het, dan stopt het; geef ze
  dan bij naam: `--koppel postcode=pc,huisnummer=nr,toevoeging=toev`.
* `--auto` neemt de herkende kenmerken mee als QID, ook een weerzone (H3-cel); AnonyMate meldt
  op welk H3-niveau die ligt.
* `--verken standaard` probeert H 10/25, C 1.000/2.500, A<sub>sol</sub> 1/2/5 en
  A<sub>inf</sub> 25/50/100 (36 combinaties). Een losse `--verken` erachter vervangt één
  uitkomst, bv. `--verken standaard --verken Asol=1,2,3,5`.
* Zonder `--scope` vergelijkt AnonyMate met alle woningen in Nederland en zegt dat erbij. Geef de
  afbakening van de dataset (zoals eengezinswoningen), anders valt de toets te gunstig uit.

geeft per combinatie van stappen het aantal publiceerbare woningen en het precisieverlies
(gemiddelde relatieve afrondfout), per uitkomst (`precisieverlies_H_%`, `precisieverlies_Asol_%`,
…) en gemiddeld (`precisieverlies_%`). Het verlies is gerekend ten opzichte van de onafgeronde
waarde: een kleine uitkomst met een grove stap (A<sub>sol</sub> van 2 m² per 5 m²) verliest
veel, ook als de afgeronde waarde er netjes uitziet. Kies daaruit; de norm blijft staan.

Vooraf, zonder dataset, laat `anonymate afronding` (of `signatuur regenboog`) zien hoe groot de
groepen in de hele populatie of in een afgebakend deel ervan worden; met `--bron` en `--scope`
vanuit de functionele tabel, voor de publiek bekende inclusie- en exclusiecriteria van de dataset:

```bash
anonymate afronding --bron signaturen_nl.parquet --scope bouwjaar=1900-1989 \
    --scope woningtype!=appartement --kolom warmteverlies_best=25,50,100 \
    --kolom thermische_massa=2500,5000 --ook h3_r4__str
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

A_inf volgt in de baselines uit bouwjaar, woningtype, daktype, oppervlakte en bouwlagen (zie
"Infiltratie per woning") en draagt dus mee aan wat een aanvaller kan berekenen; een geleerde A_inf
is een kenmerk zonder register en telt alleen via de schatting mee.
