"""Guided mode: question by question, for people who do not want to learn command line options.

Every answer has a sensible default (press Enter). At the end the wizard shows the equivalent
TOML configuration, so a run can be repeated exactly, and writes the results.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .cli import SCENARIOS, open_population, parse_scope, qids_from, read_dataset
from .detect import Role, detect
from .generalize import TARGET_SHARE, suggest
from .qids import CATALOGUE
from .report import write
from .risk import P_DEFAULT, P_MAX, P_MIN, Threshold, assess


def ask(question: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    answer = input(f"{question}{hint}: ").strip()
    return answer or default


def yes(question: str, default: bool = True) -> bool:
    return ask(question + " (j/n)", "j" if default else "n").lower().startswith(("j", "y"))


def run(args) -> int:
    print("anonymate — herleidbaarheidstoets, stap voor stap. Enter = standaardkeuze.\n")
    path = args.dataset or ask("1. Welk bestand wil je toetsen (CSV, Excel, Parquet)?")
    df = read_dataset(path)
    print(f"   {len(df)} records, {len(df.columns)} kolommen.\n")

    print("2. Voorstel per kolom:")
    found = detect(df)
    mapping: dict[str, str] = {}
    for d in found:
        label = {Role.DIRECT: "DIRECTE IDENTIFICATOR (wordt weggelaten)",
                 Role.QID: f"quasi-identifier: {d.qid}",
                 Role.IMPLICIT_LOCATION: f"verborgen locatie: {d.qid}",
                 Role.DERIVED: f"afgeleid van {d.qid} (lekt hetzelfde)",
                 Role.MEASUREMENT: "meetwaarde / geen QID"}[d.role]
        print(f"   - {d.column}: {label}  ({d.reason})")
    print("   Wijzigen? Typ 'kolom=qid' (qid uit: " + ", ".join(CATALOGUE)
          + ", of 'direct'/'geen'); leeg = klaar.")
    while pair := input("   > ").strip():
        col, _, key = pair.partition("=")
        if col not in df.columns:
            print(f"     onbekende kolom {col!r}")
            continue
        mapping[col] = key
    for d in found:
        if d.role == Role.DERIVED and d.column not in mapping and d.qid:
            mapping.setdefault(d.column, "geen")
    qids, direct = qids_from(df, mapping, auto=True)
    print(f"   quasi-identifiers: {', '.join(q.column for q in qids) or '(geen)'}")
    print(f"   weglaten: {', '.join(direct) or '(niets)'}\n")

    print("3. Wie is de aanvaller?")
    print("   register  = iedereen met openbare registers (BAG, EP-online)")
    print("   zichtbaar = ook wat je van buitenaf ziet (zonnepanelen, glas)")
    print("   insider   = ook installateur/leverancier/buren (installatiedatum, verbruik)")
    scenario_key = ask("   scenario", "register")
    scenario = SCENARIOS.get(scenario_key.lower(), SCENARIOS["register"])

    p = float(ask(f"\n4. Maximale kans op heridentificatie p ({P_MIN}-{P_MAX})", str(P_DEFAULT))
              .replace(",", "."))
    threshold = Threshold(p)
    print(f"   dat betekent: minstens {threshold.k} woningen per record, δ hoogstens {p:g}\n")

    print("5. Uit welke woningen kan de dataset komen? (bekende inclusiecriteria/regio)")
    print("   Voorbeelden: gemeente=Zwolle,Deventer   bouwjaar=1900-1989   eengezins=true")
    scope_items: dict = {}
    while pair := input("   > ").strip():
        k, _, v = pair.partition("=")
        scope_items[k] = (v.lower() in ("true", "ja")) if v.lower() in ("true", "false", "ja",
                                                                         "nee") else (
            [x.strip() for x in v.split(",")] if "," in v else v)
    population = open_population(args, {})
    scope = parse_scope(scope_items, population)
    if not scope.is_everything():
        population = population.within(scope)
    print(f"   populatie: {population.size():,} woningen\n")

    a = assess(df, qids, population, threshold, scenario)
    s = a.summary()
    print(f"6. Uitkomst: {s['ok']} van {s['records']} records publiceerbaar, {s['risico']} met "
          f"risico, {s['geen_match']} zonder match.")
    for w in a.warnings:
        print(f"   let op: {w}")
    steps = None
    if s["risico"] and yes("\n7. Zal ik zoeken naar generalisaties die meer records laten slagen?"):
        steps = suggest(df, qids, population, threshold, scenario, target_share=TARGET_SHARE)
        print(pd.DataFrame([st.row() for st in steps]).to_string(
            index=False, float_format=lambda x: f"{x:.2f}"))
        if yes("   Deze stappen toepassen?"):
            df, qids = steps[-1].df, steps[-1].qids
            a = assess(df, qids, population, threshold, scenario)
        else:
            steps = None

    out = ask("\n8. Uitvoermap", str(Path(path).with_suffix("")) + "_anonymate")
    write(out, df, a, drop_columns=direct, steps=steps, dataset_name=Path(path).name,
          target_share=TARGET_SHARE if steps else None)
    print(f"   geschreven naar {out}: publiceerbaar.csv, rapport.md, rapport_per_record.csv "
          "(intern!), samenvatting.json")

    print("\nOm dit precies te herhalen (anonymate assess --config ...):\n")
    print(f'dataset = "{Path(path).as_posix()}"\np = {p:g}\nscenario = "{scenario_key}"')
    print("[qids]")
    for q in qids:
        print(f'"{q.column}" = "{q.spec.key}"')
    if scope_items:
        print("[afbakening]")
        for k, v in scope_items.items():
            val = str(v).lower() if isinstance(v, bool) else (
                "[" + ", ".join(f'"{x}"' for x in v) + "]" if isinstance(v, list) else f'"{v}"')
            print(f"{k} = {val}")
    return 0
