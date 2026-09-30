# Variabelenlijst: kolomnamen van de populatie en het datapakket

Dit is het *variable dictionary* van anonymate: per kolom van de populatie (`population.parquet`)
en van het datapakket (`woningen.parquet`, `warmtesignatuur.parquet`) onze naam, de bron, het
veld in de bron, de eenheid, het type en een korte omschrijving. De tabel sluit aan op
`src/anonymate/namen.py` (`OUD_NAAR_NIEUW`); een test bewaakt dat de twee gelijk blijven.

## De naamconventie

De namen volgen de [physiquant__unit](https://github.com/energietransitie/physiquant__unit)-conventie
(variant met `__0`, `__cat`, `__str`, `__bool`):

- de eenheid staat als postfix achter een dubbele underscore: `oppervlakte__m2`, `hoogte__m`;
- samengestelde eenheden worden met een enkele underscore gescheiden, een negatieve exponent
  krijgt een underscore ervoor: `sig_H__W_K_1` (W/K), `warmtebehoefte__kWh_m_2_a_1`
  (kWh/(m²·a)), `compactheid__m2_m_2` (m² verliesoppervlak per m² gebruiksoppervlak);
- een fractie of telling is `__0`; een verhouding van gelijke grootheden liefst expliciet
  (`__W0`, `__m2_m_2`);
- `__cat` voor een categorische variabele met een vaste verzameling waarden, `__str` voor vrije
  tekst en identificatoren, `__bool` voor een boolean (in Parquet/pandas met ontbrekende waarden:
  "onbekend" is niet `false`).

De conventie geldt voor namen die *wij* bepalen. Gegevens uit een externe bron houden hun eigen
veldnamen tot het punt waarop wij ze vertalen; die vertaling staat in de tabellen hieronder
(kolom "bronveld"). Het datapakket en de populatie gebruiken de nieuwe namen. De tussenopslag van
de bronnen (`raw/*.parquet` in de lokale opslag: BAG, 3D-BAG, EP-online, gemeenten, stations) is
een cache van de ingest en houdt haar eigen korte namen; de vertaling naar de nieuwe namen gebeurt
in `anonymate build`. De kolommen in het *eigen* dataset van een gebruiker worden nooit hernoemd;
detectie (`detect.py`) herkent overigens ook kolommen die de conventie volgen.

### Keuzes

- **`bouwjaar__yr`.** Het bouwjaar is een kalenderjaar (een moment, "1965"), geen duur. De
  eenheid `a` (annum) is voor duren gereserveerd (`kWh_m_2_a_1`, "per jaar"); met `yr` blijft het
  jaartal daarvan te onderscheiden, zoals de conventie ook een stand (`_cum`) van een gemiddelde
  over een interval onderscheidt. Het type is een geheel getal.
- **Identificatoren zijn `__str`**, ook als ze uit cijfers bestaan: `vbo_id__str`,
  `pand_id__str`, `postcode6__str`, `postcode4__str`, `huisnummer__str`. Een huisnummer is een
  identificerend deel van het adres, geen grootheid waarmee gerekend wordt; het wordt daarom als
  tekst opgeslagen (in het oude formaat was het een geheel getal).
- **`postcode6__str`/`postcode4__str`** (geen `__cat`): de verzameling is te groot en te
  veranderlijk om een vaste verzameling te heten. **`gemeente__cat`, `provincie__cat`,
  `woonplaats__cat`** hebben wel een vaste verzameling (bestuurlijke indeling van het jaar; BAG-
  woonplaatsen). `knmi_station__cat`: de vaste lijst van KNMI-stations. `h3_r<n>__str`:
  H3-celidentificatoren.
- **`uhi__degC`**: RIVM geeft het effect in °C, als temperatuurverschil; wij houden de eenheid
  van de bron aan.
- **`bouwlagenklasse__cat`**: de klasse 1, 2 of 3 (een vaste verzameling, getalwaarden).
- **Sleutels blijven.** De korte uitvoersleutels van een signatuur (`H`, `C`, `tau`, `Asol`,
  `Ainf`) in `publicatie.Plan(steps={"H": ...})`, in de interface en in de QID-catalogus
  (`warmteverlies`, `bouwjaar`, ...) zijn identificatoren van een keuze, geen waarden; ze blijven.
  De *kolommen* waarin ze landen hebben wel een eenheid (`H__W_K_1`, `sig_H__W_K_1`). De
  catalogussleutel `bouwjaar` blijft dus `bouwjaar`; zijn populatiekolom is `bouwjaar__yr`.
- **Tekstdetails** van een signatuurberekening die een zin zijn (`asol_bron__str`,
  `oppervlakte_bron__str`, `Ainf_bron__str`) zijn `__str`; codes uit een vaste verzameling
  (`bron__cat`, `methode_gebruikt__cat`, `woningtype_gebruikt__cat`) zijn `__cat`.

## Populatie en datapakket

Kolommen van `woningen.parquet` (W), `warmtesignatuur.parquet` (S) en/of de lokale populatie (P).
De oude naam is de kolomnaam tot en met het datapakket van 2026-09-30.

### Adres en identificatie

| nieuwe naam | oude naam | waar | bron | bronveld | eenheid | type | omschrijving |
|---|---|---|---|---|---|---|---|
| `vbo_id__str` | `vbo_id` | W S P | BAG | `verblijfsobject.identificatie` | - | str | BAG-id van het verblijfsobject (16 cijfers) |
| `nummeraanduiding_id__str` | `nummeraanduiding_id` | P | BAG | `nummeraanduiding_hoofdadres_identificatie` | - | str | BAG-id van het hoofdadres |
| `pand_id__str` | `pand_id` | P | BAG | `pand_identificatie` | - | str | BAG-id van het pand |
| `postcode6__str` | `postcode6` | W P | BAG | `postcode` | - | str | postcode zonder spatie, hoofdletters (`1234AB`) |
| `postcode4__str` | `postcode4` | P | BAG | `postcode` (eerste 4) | - | str | postcode, 4 cijfers |
| `huisnummer__str` | `huisnummer` | W P | BAG | `huisnummer` | - | str | huisnummer (oud: geheel getal) |
| `huisletter__str` | `huisletter` | W P | BAG | `huisletter` | - | str | huisletter |
| `toevoeging__str` | `toevoeging` | W P | BAG | `toevoeging` | - | str | huisnummertoevoeging |
| `woonplaats__cat` | `woonplaats` | W P | BAG | `woonplaats_naam` | - | cat | woonplaats |
| `gemeente_code__str` | `gemeente_code` | P | BAG | `bronhouder_identificatie` | - | str | gemeentecode (bronhouder) |
| `gemeente__cat` | `gemeente` | W P | CBS (gebiedsindelingen, PDOK) | `gemeenten.naam` | - | cat | gemeentenaam |
| `provincie__cat` | `provincie` | W P | CBS (gebiedsindelingen, PDOK) | `ligt_in_provincie_naam` | - | cat | provincienaam |
| `status__cat` | `status` | P | BAG | `status` | - | cat | status van het verblijfsobject |

### Woning

| nieuwe naam | oude naam | waar | bron | bronveld | eenheid | type | omschrijving |
|---|---|---|---|---|---|---|---|
| `bouwjaar__yr` | `bouwjaar` | W P | BAG | `bouwjaar` (1000-2100) | kalenderjaar | int | oorspronkelijk bouwjaar van het pand |
| `oppervlakte__m2` | `oppervlakte` | W P | BAG | `oppervlakte` (1-99999) | m² | int | gebruiksoppervlakte verblijfsobject |
| `pand_woningen__0` | `pand_woningen` | W P | afgeleid (BAG) | aantal verblijfsobjecten per `pand_identificatie` | - (telling) | int | woningen in het pand |
| `eengezins__bool` | `eengezins` | P | afgeleid (BAG) | `pand_woningen == 1` | - | bool | enige woning in het pand |
| `rd_x__m` | `rd_x` | P | BAG | geometrie verblijfsobject (RD New) | m | float | RD-x |
| `rd_y__m` | `rd_y` | P | BAG | geometrie verblijfsobject (RD New) | m | float | RD-y |
| `lat__degN` | `lat` | W P | afgeleid (BAG) | `rd_x`, `rd_y` naar WGS84 (5 decimalen in het pakket) | ° noorderbreedte | float | breedtegraad |
| `lon__degE` | `lon` | W P | afgeleid (BAG) | `rd_x`, `rd_y` naar WGS84 | ° oosterlengte | float | lengtegraad |
| `uhi__degC` | `uhi` | W P | RIVM | stedelijk hitte-eiland effect, 10 m raster, 01-06-2022 | °C | float | woninggewogen gemiddelde per postcode (pakket) of per woning (raster) |
| `knmi_station__cat` | `knmi_station` | P | KNMI + BAG | stationslijst + coördinaat | - | cat | dichtstbijzijnde KNMI-station (nummer) |
| `h3_r4__str` ... `h3_r8__str` | `h3_r4` ... `h3_r8` | P | afgeleid (BAG) | `lat`, `lon` | - | str | H3-cel op resolutie 4 tot en met 8 |

### Energielabel (EP-online; niet in het datapakket)

| nieuwe naam | oude naam | waar | bron | bronveld | eenheid | type | omschrijving |
|---|---|---|---|---|---|---|---|
| `energielabel__cat` | `energielabel` | P | EP-online | `energieklasse` | - | cat | labelklasse (A++++ ... G) |
| `woningtype__cat` | `woningtype` | P | EP-online of afgeleid (3D-BAG) | `gebouwtype`, `gebouwsubtype`; anders uit de vorm van het pand | - | cat | vrijstaand, twee_onder_een_kap, hoekwoning, tussenwoning, appartement |
| `woningtype_bron__cat` | `woningtype_bron` | P | afgeleid | - | - | cat | `ep-online` of `vorm` (alleen bij installatie uit een datapakket) |
| `energie_index__0` | `energie_index` | P | EP-online | `energieindex` | - (dimensieloos) | float | energie-index |
| `compactheid__m2_m_2` | `compactheid` | P | EP-online | `compactheid` (A_ls / A_g) | m² verliesoppervlak per m² gebruiksoppervlak | float | compactheid |
| `label_oppervlakte__m2` | `label_oppervlakte` | P | EP-online | `gebruiksoppervlaktethermischezone` | m² | float | gebruiksoppervlakte A_g van de thermische zone |
| `warmtebehoefte__kWh_m_2_a_1` | `warmtebehoefte` | P | EP-online | `warmtebehoefte` (NTA 8800, netto, per m² per jaar) | kWh/(m²·a) | float | netto warmtebehoefte van de berekening |
| `nta8800__bool` | `nta8800` | P | EP-online | `berekeningstype` (NTA 8800 of eerder) | - | bool (nullable) | label berekend met NTA 8800 |

### Gebouwvorm (3D-BAG)

| nieuwe naam | oude naam | waar | bron | bronveld | eenheid | type | omschrijving |
|---|---|---|---|---|---|---|---|
| `daktype__cat` | `daktype` | S P | 3D-BAG | `b3_dak_type` | - | cat | schuin, plat, plat_meerdere |
| `bouwlagen__0` | `bouwlagen` | S P | 3D-BAG | `b3_bouwlagen` | - (telling) | int | geschat aantal bouwlagen |
| `hoogte__m` | `hoogte` | S P | 3D-BAG | `b3_h_70p` minus `b3_h_maaiveld` | m | float | hoogte van het gebouw |
| `aaneengebouwd__bool` | `aaneengebouwd` | S P | 3D-BAG | `b3_opp_scheidingsmuur > 0` | - | bool (nullable) | deelt een muur met een ander pand |
| `pand_volume__m3` | `pand_volume` | P | 3D-BAG | `b3_volume_lod22` | m³ | float | volume van het pand |
| `opp_grond__m2` | `opp_grond` | S P | 3D-BAG | `b3_opp_grond` | m² | float | grondvlak van het pand |
| `opp_dak_plat__m2` | `opp_dak_plat` | S P | 3D-BAG | `b3_opp_dak_plat` | m² | float | plat dakoppervlak |
| `opp_dak_schuin__m2` | `opp_dak_schuin` | S P | 3D-BAG | `b3_opp_dak_schuin` | m² | float | schuin dakoppervlak |
| `opp_buitenmuur__m2` | `opp_buitenmuur` | S P | 3D-BAG | `b3_opp_buitenmuur` | m² | float | buitenmuuroppervlak |
| `opp_scheidingsmuur__m2` | `opp_scheidingsmuur` | S P | 3D-BAG | `b3_opp_scheidingsmuur` | m² | float | scheidingsmuuroppervlak |
| `gevel_<r>__m2` | (ongewijzigd) | P | BAG + 3D-BAG | voetafdruk pand x hoogte | m² | float | blootgestelde gevel per windrichting `n no o zo z zw w nw` |
| `gevelzij_<r>__m2` | (ongewijzigd) | P | BAG + 3D-BAG | idem | m² | float | het deel daarvan dat zijgevel is |

### Warmtesignatuur (berekend)

Per methode (`mwa`, `best`, `ep`, `passend`, `passend_cbag`; `nta8800` zonder methode in de naam).
Het pakket bevat alleen `nta8800` en `mwa`, zonder EP-online, op drie significante cijfers; daar
heet de nta8800-signatuur `sig_nta8800_H__W_K_1` (de methode staat er altijd in; oud:
`sig_nta8800_H`). De populatie rekent ze opnieuw uit en kent `sig_H__W_K_1`.

| nieuwe naam | oude naam | eenheid | type | omschrijving |
|---|---|---|---|---|
| `sig_H__W_K_1`, `sig_<methode>_H__W_K_1` | `sig_H`, `sig_<methode>_H` | W/K | float | warmteoverdrachtscoëfficiënt |
| `sig_C__Wh_K_1`, `sig_<methode>_C__Wh_K_1` | `sig_C`, `sig_<methode>_C` | Wh/K | float | thermische massa |
| `sig_tau__h`, `sig_<methode>_tau__h` | `sig_tau`, `sig_<methode>_tau` | h | float | thermische tijdconstante C/H |
| `sig_Asol__m2`, `sig_<methode>_Asol__m2` | `sig_Asol`, `sig_<methode>_Asol` | m² | float | effectieve zonnetoetreding |
| `sig_Ainf__cm2`, `sig_<methode>_Ainf__cm2` | `sig_Ainf`, `sig_<methode>_Ainf` | cm² | float | infiltratie-apertuur |

## Uitvoer van `signature.compute`

De kolommen van het resultaat: `H__W_K_1`, `C__Wh_K_1`, `tau__h`, `Asol__m2`, `Ainf__cm2`; met
`detail=True` ook `A_gevel__m2`, `A_raam__m2`, `A_deur__m2`, `A_grond__m2`, `A_dak__m2`,
`U_<deel>__W_m_2_K_1`, `g_raam__0`, `isolatieniveau__0`, `oppervlakte_gebruikt__m2`,
`qv10__dm3_s_1_m_2`, `ELA__cm2`, `bouwlagenklasse__cat`, `woningtype_gebruikt__cat`,
`referentiewoning__str`, `bron__cat`, `methode_gebruikt__cat`, `oppervlakte_bron__str`,
`Ainf_bron__str`, `asol_bron__str`. In de tabel van `anonymate signatuur` staat de methode als
voorvoegsel: `nta8800_H__W_K_1`, `best_tau__h`.

## Gepubliceerde kolommen

De kolommen die `anonymate publiceer` maakt (`adres_H__W_K_1`, `adres_C__Wh_K_1`, `adres_tau__h`,
`adres_Asol__m2`, `adres_Ainf__cm2`) volgden de conventie al.

## Overgang

Het datapakket van 2026-09-30 en eerder heeft de oude namen; `anonymate ingest pakket` accepteert
beide formaten (het manifest van een nieuw pakket bevat `"namen": "physiquant__unit"`). Een lokale
populatie met oude namen wordt bij het lezen omgezet (`anonymate build` maakt er een met nieuwe
namen).
