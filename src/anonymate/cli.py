"""Command line interface.

    anonymate ingest all                      download + ingest all public sources
    anonymate build                           build the local population
    anonymate status                          which sources, which versions
    anonymate detect data.csv                 propose (quasi-)identifiers
    anonymate assess data.csv [options]       risk per record + publishable subset
    anonymate suggest data.csv [options]      search generalisations that make records pass
    anonymate wizard [data.csv]               guided, question by question

Everything except ``ingest`` works offline.
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

import pandas as pd

from . import __version__
from .constraints import OneOf, Range, parse_categorical, parse_numeric
from .detect import Role, detect, to_frame
from .generalize import Bin, Edges, Group, LocationUp, Suppress, suggest, tradeoff
from .population import Population, Scope
from .qids import CATALOGUE, Kind, Knowledge
from .report import write
from .risk import P_DEFAULT, P_MAX, P_MIN, QidColumn, Threshold, assess

SCENARIOS = {"register": Knowledge.REGISTER, "zichtbaar": Knowledge.OBSERVABLE,
             "observable": Knowledge.OBSERVABLE, "insider": Knowledge.INSIDER}


# ------------------------------------------------------------------------------------------------
# reading input
# ------------------------------------------------------------------------------------------------

def read_dataset(path: str | Path, sheet: str | None = None) -> pd.DataFrame:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(p, sheet_name=sheet or 0, dtype=object)
    if suffix == ".parquet":
        return pd.read_parquet(p)
    with open(p, encoding="utf-8-sig", errors="replace") as f:
        head = f.readline()
    sep = max(";,\t|", key=head.count)
    return pd.read_csv(p, sep=sep, dtype=str, keep_default_na=False, na_values=[""],
                       encoding="utf-8-sig")


def load_config(path: str | None) -> dict:
    if not path:
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def parse_scope(items: dict | None, population: Population) -> Scope:
    """``{"gemeente": ["Zwolle"], "oppervlakte": "50-250", "eengezins": true}`` -> Scope."""
    if not items:
        return Scope()
    crit = {}
    for col, val in items.items():
        spec = CATALOGUE.get(col)
        if isinstance(val, bool):
            crit[col] = OneOf.of(str(val).lower())
        elif spec is not None and spec.kind == Kind.NUMERIC:
            crit[col] = parse_numeric(val, integer=spec.integer)
        elif isinstance(val, (int, float)):
            crit[col] = Range(float(val), float(val))
        elif isinstance(val, list):
            crit[col] = OneOf(frozenset(str(v) for v in val))
        else:
            c = parse_numeric_or_none(val)
            crit[col] = c if c is not None else parse_categorical(val)
    desc = ", ".join(f"{k}={v}" for k, v in items.items())
    return Scope(crit, desc)


def parse_numeric_or_none(v):
    try:
        c = parse_numeric(v)
        return c if c is not None and (c.lo != c.hi or c.lo is None) else None
    except ValueError:
        return None


def _scope_from_args(pairs: list[str]) -> dict:
    """``gemeente=Zwolle,Deventer`` / ``oppervlakte=50-250`` / ``eengezins=true``."""
    out: dict = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        if v.lower() in ("true", "false", "ja", "nee"):
            out[k] = v.lower() in ("true", "ja")
        elif "," in v:
            out[k] = [x.strip() for x in v.split(",")]
        else:
            out[k] = v
    return out


def qids_from(df: pd.DataFrame, mapping: dict[str, str] | None, auto: bool) -> tuple[
        list[QidColumn], list[str]]:
    """QIDs from an explicit ``column -> catalogue key`` mapping and/or detection.

    Returns the QIDs and the direct-identifier columns to drop from the publication.
    """
    found = detect(df)
    direct = [d.column for d in found if d.role == Role.DIRECT]
    qids: dict[str, QidColumn] = {}
    if auto:
        for d in found:
            if d.role in (Role.QID, Role.IMPLICIT_LOCATION) and d.qid:
                qids[d.column] = QidColumn(d.column, CATALOGUE[d.qid])
    for col, key in (mapping or {}).items():
        if key in ("", "geen", "none", "-"):
            qids.pop(col, None)
            continue
        if key == "direct":
            direct.append(col)
            qids.pop(col, None)
            continue
        if key not in CATALOGUE:
            raise SystemExit(f"onbekende QID {key!r}; kies uit: {', '.join(CATALOGUE)}")
        if col not in df.columns:
            raise SystemExit(f"kolom {col!r} staat niet in de dataset")
        qids[col] = QidColumn(col, CATALOGUE[key])
    return list(qids.values()), sorted(set(direct))


def actions_from(items: list[dict]) -> list:
    acts = []
    for a in items or []:
        t = a["type"].lower()
        c = a["column"]
        if t == "bin":
            acts.append(Bin(c, a["width"], a.get("origin", 0), a.get("below"), a.get("above")))
        elif t == "edges":
            acts.append(Edges(c, tuple(a["edges"])))
        elif t == "group":
            acts.append(Group.of(c, *a["groups"]))
        elif t == "suppress":
            acts.append(Suppress(c))
        elif t in ("location", "locationup"):
            acts.append(LocationUp(c, a["to"]))
        else:
            raise SystemExit(f"onbekende actie {t!r}")
    return acts


def open_population(args, cfg: dict) -> Population:
    if getattr(args, "synthetic", False) or cfg.get("synthetisch"):
        from . import synthetic
        print("LET OP: synthetische populatie, alleen om te proberen / synthetic population",
              file=sys.stderr)
        return Population.from_dataframe(synthetic.population(200_000))
    from .store import Store
    return Store.open(args.home).population()


# ------------------------------------------------------------------------------------------------
# commands
# ------------------------------------------------------------------------------------------------

def cmd_ingest(args) -> int:
    from . import store as st
    s = st.Store.open(args.home, args.downloads)
    log = lambda m: print(m, flush=True)  # noqa: E731
    which = args.source
    if which in ("gebieden", "all"):
        st.ingest_gebieden(s, progress=log)
    if which in ("knmi", "all"):
        st.ingest_knmi(s, progress=log)
    if which in ("bag", "all"):
        st.ingest_bag(s, args.file if which == "bag" else None, progress=log)
    if which in ("ep-online", "all"):
        try:
            st.ingest_eponline(s, args.file if which == "ep-online" else None, progress=log)
        except RuntimeError as e:
            if which == "all":
                print(f"EP-online overgeslagen: {e}", file=sys.stderr)
            else:
                raise
    return 0


def cmd_build(args) -> int:
    from . import store as st
    res = tuple(int(x) for x in args.h3.split(",")) if args.h3 else st.H3_RESOLUTIONS
    st.build(st.Store.open(args.home), h3_resolutions=res, progress=lambda m: print(m, flush=True))
    return 0


def cmd_status(args) -> int:
    from .store import Store
    s = Store.open(args.home)
    print(f"store: {s.root}")
    print(f"downloads: {s.downloads}")
    st = s.status()
    print(st.to_string(index=False) if len(st) else "nog niets ingelezen / nothing ingested yet")
    m = s.manifest()
    if "population" in m:
        print(f"populatie: {m['population']['rows']:,} woningen, gebouwd {m['population']['built']}")
    return 0


def cmd_detect(args) -> int:
    df = read_dataset(args.dataset, args.sheet)
    with pd.option_context("display.width", 200, "display.max_colwidth", 60):
        print(to_frame(detect(df)).to_string(index=False))
    return 0


def _prepare(args):
    cfg = load_config(args.config)
    df = read_dataset(args.dataset or cfg.get("dataset"), args.sheet or cfg.get("blad"))
    population = open_population(args, cfg)
    koppel = args.koppel or cfg.get("koppel")
    link_cols: list[str] = []
    if koppel:
        from .link import link
        cols = [c.strip() for c in (koppel.split(",") if isinstance(koppel, str) else koppel)]
        if len(cols) == 1:
            df = link(df, population, vbo_id=cols[0])
        else:
            names = ["postcode", "huisnummer", "huisletter", "toevoeging"]
            df = link(df, population, **dict(zip(names, cols)))
        link_cols = cols
        n = int(df["register_gekoppeld"].sum())
        print(f"gekoppeld aan register: {n} van {len(df)} records", file=sys.stderr)
    mapping = dict(cfg.get("qids", {}))
    for pair in args.qid or []:
        col, _, key = pair.partition("=")
        mapping[col] = key
    auto = args.auto or cfg.get("auto", not mapping)
    qids, direct = qids_from(df, mapping, auto)
    direct += [c for c in list(cfg.get("weglaten", [])) + link_cols + ["register_gekoppeld"]
               if c in df.columns and c not in direct]
    p = args.p if args.p is not None else cfg.get("p", P_DEFAULT)
    threshold = Threshold(p, args.delta if args.delta is not None else cfg.get("delta"))
    scenario = SCENARIOS[(args.scenario or cfg.get("scenario", "register")).lower()]
    scope_items = dict(cfg.get("afbakening", {}))
    scope_items.update(_scope_from_args(args.scope))
    scope = parse_scope(scope_items, population)
    if not scope.is_everything():
        population = population.within(scope)
    actions = actions_from(cfg.get("acties", []))
    unknown = args.unknown_matches or cfg.get("onbekend_telt_mee", False)
    return df, qids, direct, threshold, scenario, population, actions, unknown


def cmd_assess(args) -> int:
    df, qids, direct, threshold, scenario, population, actions, unknown = _prepare(args)
    if not qids:
        print("geen quasi-identifiers gekozen of gevonden / no quasi-identifiers", file=sys.stderr)
        return 2
    steps = None
    if actions:
        steps = tradeoff(df, qids, population, actions, threshold, scenario,
                         unknown_matches=unknown)
        df, qids = steps[-1].df, steps[-1].qids
    a = assess(df, qids, population, threshold, scenario, unknown_matches=unknown)
    _print_summary(a)
    if args.out:
        out = write(args.out, df, a, drop_columns=direct, steps=steps,
                    dataset_name=Path(args.dataset or "dataset").name)
        print(f"\nuitvoer / output: {out}")
    return 0


def cmd_suggest(args) -> int:
    df, qids, direct, threshold, scenario, population, _, unknown = _prepare(args)
    steps = suggest(df, qids, population, threshold, scenario, target_share=args.doel,
                    unknown_matches=unknown)
    table = pd.DataFrame([s.row() for s in steps])
    with pd.option_context("display.width", 200, "display.max_colwidth", 70):
        print(table.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    if args.out:
        last = steps[-1]
        a = assess(last.df, last.qids, population, threshold, scenario, unknown_matches=unknown)
        out = write(args.out, last.df, a, drop_columns=direct, steps=steps,
                    dataset_name=Path(args.dataset or "dataset").name)
        print(f"\nuitvoer na laatste stap / output after last step: {out}")
    return 0


def _print_summary(a) -> None:
    s = a.summary()
    n = s["records"] or 1
    print(f"records: {s['records']}   publiceerbaar: {s['ok']} ({100 * s['ok'] / n:.0f}%)   "
          f"risico: {s['risico']}   geen match: {s['geen_match']}")
    print(f"drempel: p={s['p']:g} -> k>={s['k_drempel']}, delta<={s['delta_drempel']:g}   "
          f"scenario: {s['scenario']}")
    print(f"k min/mediaan: {s['k_min']}/{s['k_mediaan']}   delta max: {s['delta_max']}")
    print(f"populatie: {s['populatie']:,} ({s['afbakening']})   bronnen: {s['snapshot']}")
    for w in a.warnings:
        print(f"let op: {w}")


def cmd_wizard(args) -> int:
    from .wizard import run
    return run(args)


# ------------------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="anonymate",
        description="Herleidbaarheidstoets voor woningdata tegen de volledige Nederlandse "
                    "woningvoorraad, lokaal en offline. / Re-identification risk of dwelling "
                    "data against the full Dutch housing stock, local and offline.")
    ap.add_argument("--version", action="version", version=f"anonymate {__version__}")
    ap.add_argument("--home", help="map van de lokale store (standaard %%LOCALAPPDATA%%\\anonymate "
                                   "of $ANONYMATE_HOME)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="publieke bronnen downloaden en inlezen (enige stap met "
                                      "netwerk)")
    p.add_argument("source", choices=["all", "bag", "gebieden", "knmi", "ep-online"])
    p.add_argument("--file", help="al gedownload bestand gebruiken (bag-light.gpkg of "
                                  "EP-online-totaalbestand)")
    p.add_argument("--downloads", help="map voor grote originele bestanden, bv. een NAS "
                                       "(of $ANONYMATE_DOWNLOADS)")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("build", help="lokale populatie opbouwen uit de ingelezen bronnen")
    p.add_argument("--h3", help="H3-resoluties, bv. 4,5,6,7,8")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("status", help="welke bronnen en versies staan er lokaal")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("detect", help="(quasi-)identificerende kolommen voorstellen")
    p.add_argument("dataset")
    p.add_argument("--sheet", help="Excel-tabblad")
    p.set_defaults(func=cmd_detect)

    for name, helptext, func in [
            ("assess", "herleidbaarheid toetsen en publiceerbare selectie maken", cmd_assess),
            ("suggest", "generalisaties zoeken die records laten slagen", cmd_suggest)]:
        p = sub.add_parser(name, help=helptext)
        p.add_argument("dataset", nargs="?", help="CSV, Excel of Parquet (of 'dataset' in config)")
        p.add_argument("--config", help="TOML-configuratie (zie docs/config-voorbeeld.toml)")
        p.add_argument("--sheet", help="Excel-tabblad")
        p.add_argument("--qid", action="append", metavar="KOLOM=QID",
                       help=f"kolom als quasi-identifier; QID uit: {', '.join(CATALOGUE)}; "
                            "'direct' = directe identificator, 'geen' = niet meenemen")
        p.add_argument("--auto", action="store_true", help="gedetecteerde QID's gebruiken")
        p.add_argument("--p", type=float, help=f"maximale heridentificatiekans, "
                                               f"{P_MIN}-{P_MAX} (standaard {P_DEFAULT})")
        p.add_argument("--delta", type=float, help="maximale δ (standaard gelijk aan p)")
        p.add_argument("--scenario", choices=sorted(SCENARIOS), help="aanvallerskennis "
                                                                     "(standaard register)")
        p.add_argument("--scope", action="append", metavar="KOLOM=WAARDE",
                       help="populatie afbakenen, bv. gemeente=Zwolle,Deventer of "
                            "oppervlakte=50-250 of eengezins=true")
        p.add_argument("--unknown-matches", action="store_true",
                       help="woningen met onbekende waarde tellen mee als match (minder streng)")
        p.add_argument("--koppel", metavar="KOLOMMEN",
                       help="lokaal koppelen aan de BAG: één kolom met verblijfsobject-ID, of "
                            "postcode,huisnummer[,huisletter,toevoeging]; voegt register_*-kolommen "
                            "toe (de koppelkolommen worden nooit gepubliceerd)")
        p.add_argument("--synthetic", action="store_true",
                       help="synthetische populatie gebruiken (om te proberen, zonder downloads)")
        p.add_argument("--out", help="uitvoermap voor publiceerbare dataset en rapporten")
        if name == "suggest":
            p.add_argument("--doel", type=float, default=0.95,
                           help="gewenst aandeel publiceerbare records (standaard 0,95)")
        p.set_defaults(func=func)

    p = sub.add_parser("wizard", help="stap voor stap, met vragen")
    p.add_argument("dataset", nargs="?")
    p.set_defaults(func=cmd_wizard)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"fout / error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
