# SPDX-License-Identifier: EUPL-1.2
"""Schrijft de TOML-configuraties van de herleidbaarheidstoets naar scenarios/.

Eén configuratie per scenario en per groep (gg = grondgebonden, pf = portiekflat, onb = typologie
onbekend). De groepen verschillen in de afbakening van de populatie: grondgebonden is een
eengezinswoning, een portiekflat een meergezinswoning.
"""
from pathlib import Path

DIR = Path(__file__).with_name("scenarios")
P = 0.09   # privacynorm: k >= 11 en delta <= 0,09; niet aanpassen aan de uitkomst

AFBAKENING = {
    "gg": ["eengezins = true"],
    "pf": ["eengezins = false"],
    "onb": [],
}
# dezelfde projecten, zonder dat het type bekend is: alleen weerstation (en wat een insider weet)
LABEL_A = '["A", "A+", "A++", "A+++", "A++++"]'

# naam: (scenario, qids, extra afbakening, omschrijving)
SCENARIOS = {
    "s0_register_zonder_station": (
        "register", {"bouwjaar": "bouwjaar", "oppervlak": "oppervlakte"}, [],
        "register: bouwjaar en oppervlak, zonder weerstation"),
    "s1_register": (
        "register", {"station": "knmi_station", "bouwjaar": "bouwjaar", "oppervlak": "oppervlakte"},
        [], "register: weerstation, bouwjaar en oppervlak (afgerond op 5)"),
    "s1b_register_ruim": (
        "register", {"station": "knmi_station", "bouwjaar_ruim": "bouwjaar",
                     "oppervlak_ruim": "oppervlakte"},
        [], "register, ruime marge: bouwjaar +-5 jaar, oppervlak +-10 m2"),
    "a1_advies_register": (
        "register", {"station": "knmi_station", "bouwjaar_advies": "bouwjaar",
                     "oppervlak_advies": "oppervlakte"},
        [], "advies: bouwjaar op 10 jaar en oppervlak op 20 m2 afgerond; register"),
    "a2_advies_insider": (
        "insider", {"station": "knmi_station", "bouwjaar_advies": "bouwjaar",
                    "oppervlak_advies": "oppervlakte", "toestel": "toestel"},
        [], "advies: idem, jaarverbruik niet gepubliceerd; insider kent het toestel"),
    "s2_register_label_a": (
        "register", {"station": "knmi_station", "bouwjaar": "bouwjaar", "oppervlak": "oppervlakte"},
        [f"energielabel = {LABEL_A}"],
        "register, aanvaller weet dat de woning na renovatie label A of beter heeft"),
    "s3_zichtbaar": (
        "zichtbaar", {"station": "knmi_station", "bouwjaar": "bouwjaar", "oppervlak": "oppervlakte",
                      "buitenunit": "buitenunit"},
        [], "zichtbaar: + bron van de warmtepomp (buitenunit)"),
    "s4_insider": (
        "insider", {"station": "knmi_station", "bouwjaar": "bouwjaar", "oppervlak": "oppervlakte",
                    "toestel": "toestel", "jaarverbruik": "jaarverbruik"},
        [], "insider: + type warmteopwekker en exacte netto jaarafname elektriciteit"),
}


def main() -> None:
    DIR.mkdir(exist_ok=True)
    for naam, (scenario, qids, extra, uitleg) in SCENARIOS.items():
        for groep, afb in AFBAKENING.items():
            if groep == "onb" and naam.startswith("s0"):
                continue
            q = dict(qids)
            if groep == "onb":      # van deze projecten zijn bouwjaar en oppervlak niet gepubliceerd
                q = {k: v for k, v in q.items() if not k.startswith(("bouwjaar", "oppervlak"))}
            regels = [f"# {uitleg} ({groep}). Gegenereerd door maak_configs.py.",
                      f'dataset = "../uitvoer/woningen_{groep}.csv"', f"p = {P}", "auto = false",
                      'weglaten = ["woningcode", "project", "groep"]',
                      f'scenario = "{scenario}"', ""]
            ab = afb + extra
            if ab:
                regels += ["[afbakening]", *ab, ""]
            regels += ["[qids]", *[f'{k} = "{v}"' for k, v in q.items()]]
            (DIR / f"{naam}_{groep}.toml").write_text("\n".join(regels) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
