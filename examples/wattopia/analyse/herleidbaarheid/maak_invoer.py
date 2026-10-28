# SPDX-License-Identifier: EUPL-1.2
"""Invoer voor de herleidbaarheidstoets: één rij per woning, met de kenmerken die de dataset
openbaar maakt, in de vorm waarin een aanvaller ze tegen de registers legt.

De projectkenmerken (bouwjaar, oppervlak, typologie, weerstation, installaties) gelden voor alle
woningen van een project; de woning erft ze. Bouwjaar en oppervlak zijn in de bron afgerond op 5,
en gaan hier als bereik (klasse) de toets in, zodat de toets de afronding meetelt.

Schrijft naar uitvoer/ (gitignored): de rijen blijven buiten git.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
UIT = Path(__file__).with_name("uitvoer")

# KNMI-stationsnaam in de dataset -> stationsnummer in de populatie van anonymate.
# "Rotterdam Geulhaven" is het huidige station 344 (Rotterdam); die koppeling is een aanname.
STATION = {
    "Hoogeveen": "279", "Ell": "377", "Amsterdam/Schiphol AP": "240", "Cabauw Tower": "348",
    "Herwijnen": "356", "Woensdrecht": "340", "Nieuw Beerta": "286", "Groningen AP": "280",
    "De Bilt": "260", "Deelen": "275", "Volkel": "375", "Rotterdam Geulhaven": "344",
    "Voorschoten": "215",
}


def bereik(x, marge):
    return "" if pd.isna(x) else f"{int(x) - marge}-{int(x) + marge}"


def afronden(x, stap):
    """Naar het dichtstbijzijnde veelvoud van stap (halve stap omhoog)."""
    return None if pd.isna(x) else int((x / stap + 0.5) // 1) * stap


def main() -> None:
    p = pd.read_parquet(ROOT / "data/processed/projecten.parquet")
    w = pd.read_parquet(ROOT / "data/processed/woningen_jaar.parquet")
    onbekend = set(p.knmi_station__str.dropna()) - set(STATION)
    assert not onbekend, f"station zonder nummer: {onbekend}"
    d = w.merge(p, on="projectcode__str", how="left", validate="m:1")
    typ = d.woningtypologie__cat.astype("string")
    d["groep"] = typ.str.startswith("Grondgebonden").map({True: "gg", False: "pf"}).where(
        typ.notna(), "onb")
    out = pd.DataFrame({
        "woningcode": d.woningcode__str,
        "project": d.projectcode__str,
        "groep": d.groep,
        "station": d.knmi_station__str.map(STATION),
        # advies: bouwjaar afgerond op 10 jaar, oppervlak op 20 m2; de klasse is de afrondstap
        "bouwjaar_advies": [bereik(afronden(x, 10), 5) for x in d.bouwjaar_afgerond__0],
        "oppervlak_advies": [bereik(afronden(x, 20), 10) for x in d.gebruiksoppervlak_afgerond__m2],
        # afgerond op 5: het echte bouwjaar ligt hoogstens 2 jaar ernaast
        "bouwjaar": [bereik(x, 2) for x in d.bouwjaar_afgerond__0],
        "oppervlak": [bereik(x, 2) for x in d.gebruiksoppervlak_afgerond__m2],
        # ruimere marge: oppervlak is het gemiddelde van het project, de woning wijkt daar vanaf
        "bouwjaar_ruim": [bereik(x, 5) for x in d.bouwjaar_afgerond__0],
        "oppervlak_ruim": [bereik(x, 10) for x in d.gebruiksoppervlak_afgerond__m2],
        # zichtbaar van buiten: een lucht-waterwarmtepomp heeft een buitenunit
        "buitenunit": d.bron_warmteopwekker__cat.astype("string").str.lower(),
        # insider (installateur, corporatie, monitoringleverancier)
        "toestel": d.warmteopwekker__cat.astype("string").str.lower(),
        # insider (energieleverancier, netbeheerder): exacte jaarwaarde
        "jaarverbruik": d.e_netto_afname__kWh_a_1,
    })
    UIT.mkdir(exist_ok=True)
    for g, df in out.groupby("groep"):
        df.to_csv(UIT / f"woningen_{g}.csv", index=False)
        print(g, len(df), "woningen")


if __name__ == "__main__":
    main()
