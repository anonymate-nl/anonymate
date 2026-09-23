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

## Werkwijze

**1. Kies afrondstappen vóór publicatie.** Hoe groot worden de groepen woningen met dezelfde
afgeronde waarden, in de populatie waaruit je dataset komt?

```bash
anonymate afronding --scope eengezins=true \
    --kolom warmteverlies=5,10,20,50 \
    --kolom thermische_massa=500,1000,2000,5000
```

Voeg met `--ook` toe wat je daarnaast exact publiceert (bijvoorbeeld `--ook knmi_station` of
`--ook h3_cel`), en met `--scope` de bekende inclusiecriteria (bijvoorbeeld
`--scope oppervlakte=50-250`). Kies de fijnste stappen waarbij (vrijwel) geen woning in een te
kleine groep valt.

**2. Toets de dataset zelf.** Afgerond publiceren op stap *s* betekent voor de aanvaller: de
waarde ligt binnen ±*s*/2. Voor een **geleerde** signatuur komt de modelfout daar nog bij: de
aanvaller zoekt berekende waarden binnen ±(*s*/2 + fout). Leg dat vast als tolerantie:

```toml
[qids]
H_geleerd__W_K_1 = "warmteverlies"
C_geleerd__Wh_K_1 = "thermische_massa"

[tolerantie]
H_geleerd__W_K_1 = 25       # halve afrondstap (5) + typische afwijking geleerd vs. berekend (20)
C_geleerd__Wh_K_1 = 3000
```

De typische afwijking tussen geleerd en berekend volgt uit je eigen data. Neem een ruime
schatting (bijvoorbeeld de 25e percentiel van de absolute verschillen): een kleinere tolerantie
geeft kleinere groepen, dus een strengere toets.

## Laten zien dat leren beter is, zonder de sleutel te publiceren

Wie wil aantonen dat een geleerde signatuur beter simuleert dan de berekende, hoeft de
berekende signatuur niet per woning te publiceren. Wie het adres kent, kan hem toch uitrekenen,
en voor iedereen anders is hij juist de sleutel. Opties, van veilig naar informatief:

1. **Alleen geaggregeerd**: de verdeling van de simulatiefout van beide varianten over alle
   woningen, zonder waarden per woning.
2. **Per woning de simulatiefout**, zonder signatuurwaarden: laat zien *dat* leren beter werkt,
   verraadt weinig over de woning.
3. **De geleerde signatuur afgerond**, met stappen gekozen via `anonymate afronding` en getoetst
   met tolerantie. Niet de verhouding geleerd/berekend erbij publiceren: samen met de geleerde
   waarde onthult die de berekende, en daarmee de sleutel.

A_inf wordt in de baseline als landelijk gemiddelde gezet en geeft dus geen informatie; een
geleerde A_inf is een insider-kenmerk zonder register en telt alleen via de schatting mee.
