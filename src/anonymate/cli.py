"""Command line interface.

    anonymate ingest all                      download + ingest all public sources
    anonymate build                           build the local population
    anonymate status                          which sources, which versions
    anonymate detect data.csv                 propose (quasi-)identifiers
    anonymate assess data.csv [options]       risk per record + publishable subset
    anonymate suggest data.csv [options]      search generalisations that make records pass
    anonymate afronding --kolom ...           rounding steps for computable quantities
    anonymate signatuur tabel|adres|regenboog heat signature from public data
    anonymate signatuur publiceer data.csv    add a rounded address-based signature, assessed
    anonymate representativiteit data.csv     dataset against its target population
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
from .detect import Role, derive_h3_columns, detect, to_frame
from .generalize import (TARGET_SHARE, Bin, Edges, Group, LocationUp, Noise, Suppress, suggest,
                         tradeoff)
from .invoer import (SCENARIOS, _scope_from_args, parse_numeric_or_none, parse_scope,  # noqa: F401
                     qids_from, read_dataset)  # (re-exported)
from .namen import OUD_NAAR_NIEUW
from .population import Population, Scope
from .qids import CATALOGUE, Kind, Knowledge
from .report import write
from .risk import P_DEFAULT, P_MAX, P_MIN, QidColumn, Threshold, assess
from .signature import METHODS as SIGNATURE_METHODS



# ------------------------------------------------------------------------------------------------
# reading input
# ------------------------------------------------------------------------------------------------

def load_config(path: str | None) -> dict:
    if not path:
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


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
        elif t in ("noise", "ruis"):
            acts.append(Noise(c, a.get("max", a.get("amount")), a.get("seed", 0)))
        elif t in ("location", "locationup"):
            acts.append(LocationUp(c, a["to"]))
        else:
            raise SystemExit(f"onbekende actie {t!r}")
    return acts


def open_population(args, cfg: dict) -> Population:
    if getattr(args, "synthetic", False) or cfg.get("synthetisch"):
        from . import voorbeeld
        print("LET OP: het verzonnen Nederland van de oefenmodus, alleen om te proberen / "
              "made-up population, for trying only", file=sys.stderr)
        return Population.from_dataframe(voorbeeld.population())
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
    if which == "knmi-uur":
        from .weerspoor import download_hourly
        if not args.jaar:
            raise ValueError("geef --jaar op, bv. --jaar 2023 (of 2023,2024)")
        for year in str(args.jaar).split(","):
            download_hourly(s, int(year), progress=log)
    if which in ("bag", "all"):
        st.ingest_bag(s, args.file if which == "bag" else None, progress=log)
    if which == "pakket":
        import dataclasses

        from . import opbouw
        # the same steps as the window: package (downloaded, or --file), EP-online when a key is
        # known, population. Always a refresh, so the state is taken as "nothing there yet".
        key = None if args.file else opbouw.gevonden_sleutel(s)
        state = dataclasses.replace(opbouw.toestand(s), populatie=False, pakket_zip=False)
        if not key and not state.ep_parquet:
            log(opbouw.UITLEG_EP + f" Sleutel aanvragen: {opbouw.EP_AANVRAAG_URL} ; zet hem als "
                f"{st.EPONLINE_KEY_ENV} in de omgeving of in .env en draai dit opnieuw.")
        steps = opbouw.plan(s, state, opbouw.Bron.SLEUTEL if key else opbouw.Bron.GEEN, key=key,
                            pakket=args.file)
        shown = [None, -1]

        def report(fraction, text):
            head, tenth = text.split(" · ")[0], int(20 * (fraction or 0))
            if (head, tenth) != tuple(shown):
                shown[:] = [head, tenth]
                log(text if fraction is None else f"{text} ({100 * fraction:.0f}%)")
        opbouw.voer_uit(steps, report)
    if which == "uhi":
        if args.raster is not None:
            st.ingest_uhi_raster(s, args.raster or None, progress=log)
        else:
            st.ingest_uhi(s, args.file, progress=log)
    if which == "3dbag":
        st.ingest_3dbag(s, args.file, progress=log, max_tiles=args.max_tegels,
                        keep_tiles=not args.tegels_weggooien)
    if which in ("ep-online", "all"):
        try:
            st.ingest_eponline(s, args.file if which == "ep-online" else None, progress=log)
        except RuntimeError as e:
            if which == "all":
                print(f"EP-online overgeslagen: {e}", file=sys.stderr)
            else:
                raise
    return 0


def cmd_pakketten(args) -> int:
    from . import datapakket
    from .store import Store
    s = Store.open(args.home)
    if not s.population_path.exists():
        raise ValueError("geen populatie: draai eerst 'anonymate build'")
    # the versions of the sources in the package; EP-online is not one of them
    sources = {k: v for k, v in s.snapshot().sources.items() if k != "ep-online"}
    out = datapakket.make(s.population_path, args.uit, sources=sources,
                          progress=lambda m: print(m, flush=True))
    print(f"datapakketten in {out}")
    if args.publicatie:
        m = datapakket.publish(out, args.publicatie)
        print(f"publicatie in {args.publicatie}: {datapakket.ZIP_NAME} "
              f"({m['zip']['bytes'] / 1e6:.0f} MB, sha256 {m['zip']['sha256']})")
    return 0


def cmd_build(args) -> int:
    from . import store as st
    if args.signaturen:
        st.refresh_signatures(st.Store.open(args.home), progress=lambda m: print(m, flush=True))
        return 0
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
        pop = m["population"]
        bron = f", uit datapakket van {pop['from_package']}" if pop.get("from_package") else ""
        print(f"populatie: {pop['rows']:,} woningen, gebouwd {pop.get('built', 'onbekend')}{bron}")
    return 0


def cmd_detect(args) -> int:
    df = read_dataset(args.dataset, args.sheet)
    with pd.option_context("display.width", 200, "display.max_colwidth", 60):
        print(to_frame(detect(df)).to_string(index=False))
    return 0


def _from_config(value: str | None, config: str | None) -> str | None:
    """A relative path in a configuration file is relative to that file, not to the cwd."""
    if not value or not config or Path(value).is_absolute():
        return value
    return str(Path(config).resolve().parent / value)


def _prepare(args):
    cfg = load_config(args.config)
    args.dataset = args.dataset or _from_config(cfg.get("dataset"), args.config)
    df = read_dataset(args.dataset, args.sheet or cfg.get("blad"))
    population = open_population(args, cfg)
    koppel = args.koppel or cfg.get("koppel")
    link_cols: list[str] = []
    if koppel:
        from .link import link
        kw = _koppel(df, koppel)
        df = link(df, population, **kw)
        link_cols = list(kw.values())
        n = int(df["register_gekoppeld__bool"].sum())
        print(f"gekoppeld aan register: {n} van {len(df)} records", file=sys.stderr)
    df, mapping = derive_h3_columns(df)
    if mapping:
        print("verborgen locatie omgezet naar H3-cel: "
              + ", ".join(c for c, k in mapping.items() if k == "h3_cel"), file=sys.stderr)
    mapping.update(cfg.get("qids", {}))
    for pair in args.qid or []:
        col, _, key = pair.partition("=")
        mapping[col] = key
    auto = args.auto or cfg.get("auto", not mapping)
    qids, direct = qids_from(df, mapping, auto)
    tolerances = cfg.get("tolerantie", {})
    for col in tolerances:
        if col not in {q.column for q in qids}:
            raise SystemExit(f"tolerantie voor {col!r}, maar dat is geen quasi-identifier")
    qids = [QidColumn(q.column, q.spec, float(tolerances.get(q.column, q.tolerance)))
            for q in qids]
    qids, onderzoeken = _lezingen(df, qids, cfg)
    direct += [c for c in list(cfg.get("weglaten", [])) + link_cols + ["register_gekoppeld__bool"]
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
    return df, qids, direct, threshold, scenario, population, actions, unknown, onderzoeken


def _lezingen(df, qids, cfg):
    """How each numeric QID is read (kladbloknotitie 17): ``[afronding]`` and ``[klassegrens]``
    in the configuration, otherwise the proposal from the values. Says what it found."""
    from dataclasses import replace

    from .lezing import onderzoek, uit_config
    afronding, grens = cfg.get("afronding", {}), cfg.get("klassegrens", {})
    numeric = {q.column for q in qids if q.spec.kind == Kind.NUMERIC}
    for col in list(afronding) + list(grens):
        if col not in numeric:
            raise SystemExit(f"afronding of klassegrens voor {col!r}, maar dat is geen numerieke "
                             f"quasi-identifier")
    out, onderzoeken = [], {}
    for q in qids:
        if q.column not in numeric:
            out.append(q)
            continue
        o = onderzoeken[q.column] = onderzoek(df[q.column], q.spec, tolerance=q.tolerance)
        try:
            lezing = uit_config(afronding.get(q.column), grens.get(q.column), o.gedeeld)
        except ValueError as e:
            raise SystemExit(f"{q.column}: {e}") from None
        if lezing is None:
            lezing = o.voorstel()
            for m in o.meldingen():
                print(m, file=sys.stderr)
        out.append(replace(q, lezing=None if lezing is None or lezing.exact else lezing))
    return out, onderzoeken


def cmd_assess(args) -> int:
    df, qids, direct, threshold, scenario, population, actions, unknown, onderzoeken = (
        _prepare(args))
    if not qids:
        print("geen quasi-identifiers gekozen of gevonden / no quasi-identifiers", file=sys.stderr)
        return 2
    steps = None
    if actions:
        steps = tradeoff(df, qids, population, actions, threshold, scenario,
                         unknown_matches=unknown)
        before, df, qids = df, steps[-1].df, steps[-1].qids
        # a column rewritten into classes of AnonyMate's own has no reading left to doubt
        onderzoeken = {c: o for c, o in onderzoeken.items() if df[c].equals(before[c])}
    a = assess(df, qids, population, threshold, scenario, unknown_matches=unknown)
    _print_summary(a)
    from .lezing import gevoeligheid
    lezingen = gevoeligheid(df, qids, population, threshold, scenario, onderzoeken,
                            unknown_matches=unknown)
    for r in lezingen:
        for alt in r["alternatieven"]:
            print(f"{r['kolom']} met {alt['lezing']}: {alt['publiceerbaar']} publiceerbaar")
    if args.out:
        out = write(args.out, df, a, drop_columns=direct, steps=steps,
                    dataset_name=Path(args.dataset or "dataset").name, population=population,
                    unknown_matches=unknown, lezingen=lezingen)
        print(f"\nuitvoer / output: {out}")
        if args.kandidaten:
            _write_candidates(Path(args.out), df, a, population, direct, unknown)
    return 0


CANDIDATES_WARNING = """\
# Kandidatenlijst: NIET PUBLICEREN / candidate list: DO NOT PUBLISH

Per record dat de toets niet haalt: de woningen in de populatie die bij alle gepubliceerde
registerkenmerken passen, met adres. Bedoeld voor de bronhouder, om de bevinding te controleren
(zit de deelnemende woning er echt tussen?). Wie deze lijst heeft, hoeft maar een handvol adressen
af te gaan: bewaar hem alleen waar ook de adressen van de deelnemers mogen staan, en nooit in
versiebeheer.

For every record that fails the test: the population dwellings matching all its published register
attributes, with their address. For the data holder only.
"""


def _write_candidates(out: Path, df, a, population, direct, unknown) -> None:
    from .candidates import candidates
    c = candidates(df, a, population, unknown_matches=unknown)
    ids = [col for col in direct if col in df.columns]
    if ids and not c.empty:
        c = df[ids].rename(columns=lambda x: f"dataset_{x}").join(c.set_index("record"),
                                                                    how="inner")
        c = c.rename_axis("record").reset_index()
    target = out / "kandidaten_NIET_PUBLICEREN"
    target.mkdir(parents=True, exist_ok=True)
    c.to_csv(target / "kandidaten.csv", index=False)
    c.to_parquet(target / "kandidaten.parquet", index=False)
    (target / "LEESMIJ.md").write_text(CANDIDATES_WARNING, encoding="utf-8")
    print(f"kandidatenlijst (niet publiceren / do not publish): {target}")


def cmd_suggest(args) -> int:
    df, qids, direct, threshold, scenario, population, _, unknown, _ = _prepare(args)
    steps = suggest(df, qids, population, threshold, scenario, target_share=args.doel,
                    unknown_matches=unknown)
    table = pd.DataFrame([s.row() for s in steps])
    with pd.option_context("display.width", 200, "display.max_colwidth", 70):
        print(table.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    if args.out:
        last = steps[-1]
        a = assess(last.df, last.qids, population, threshold, scenario, unknown_matches=unknown)
        out = write(args.out, last.df, a, drop_columns=direct, steps=steps,
                    dataset_name=Path(args.dataset or "dataset").name, population=population,
                    unknown_matches=unknown, target_share=args.doel)
        print(f"\nuitvoer na laatste stap / output after last step: {out}")
    return 0


def _print_summary(a) -> None:
    s = a.summary()
    n = s["records"] or 1
    print(f"records: {s['records']}   publiceerbaar: {s['ok']} ({100 * s['ok'] / n:.0f}%)   "
          f"risico: {s['risico']}   geen match: {s['geen_match']}")
    print(f"drempel: p={s['p']:g} -> k>={s['k_drempel']}, delta<={s['delta_drempel']:g}   "
          f"scenario: {s['scenario']}")
    from .stappen import k_line
    print(k_line(s))
    print(f"populatie: {s['populatie']:,} ({s['afbakening']})   bronnen: {s['snapshot']}")
    for w in a.warnings:
        print(f"let op: {w}")


def _population_column(name: str, *, table: bool = False) -> str:
    """Catalogue key or column name -> column; ``table=True`` for a functional signature table
    (``anonymate signatuur tabel``), where ``sig_best_H__W_K_1`` is called ``best_H__W_K_1``."""
    spec = CATALOGUE.get(name)
    # a catalogue key, or a plain (``h3_r4``) or full (``h3_r4__str``) column name
    col = (spec.population_column if spec is not None and spec.population_column
           else OUD_NAAR_NIEUW.get(name, name))
    if table and col.startswith("sig_"):
        rest = col[4:]
        for m in ("mwa", "best", "passend_cbag", "ep_cbag", "ep", "passend"):
            if rest.startswith(m + "_"):
                return rest
        return "nta8800_" + rest
    return col


def _source(args) -> Population:
    """The population, or a functional signature table given with ``--bron``."""
    if getattr(args, "bron", None):
        from .population import Snapshot
        return Population.from_parquet(args.bron, Snapshot({"signatuurtabel": Path(args.bron).name}))
    return open_population(args, {})


def cmd_afronding(args) -> int:
    from .rounding import grid
    candidates = {}
    for item in args.kolom:
        name, _, steps = item.partition("=")
        candidates[_population_column(name, table=bool(args.bron))] = [
            float(x.replace(",", ".")) for x in steps.split(";" if ";" in steps else ",")]
    exact = [_population_column(c, table=bool(args.bron)) for c in (args.ook or [])]
    population = _source(args)
    scope = parse_scope(_scope_from_args(args.scope), population)
    if not scope.is_everything():
        population = population.within(scope)
    k = Threshold(args.p if args.p is not None else P_DEFAULT).k
    table = grid(population, candidates, exact, k)
    table["aandeel_te_klein"] = (100 * table["aandeel_te_klein"]).round(2)
    table = table.rename(columns={"aandeel_te_klein": f"% in groep < {k}"})
    with pd.option_context("display.width", 200):
        print(table.to_string(index=False))
    if args.out:
        table.to_csv(args.out, index=False)
        print(f"\nuitvoer / output: {args.out}")
    return 0


def cmd_signatuur(args) -> int:
    from . import signature as sg
    from .store import Store
    store = Store.open(args.home)
    methods = tuple(args.methode) if args.methode else sg.METHODS
    if args.actie == "tabel":
        out = args.out or "signaturen.parquet"
        sg.table(store.population_path, out, methods=methods, detail=args.detail,
                 progress=lambda m: print(m, flush=True))
        print(f"uitvoer / output: {out}")
    elif args.actie == "adres":
        if not args.adres or len(args.adres) < 2:
            raise SystemExit("geef postcode en huisnummer, bv. 'signatuur adres 1234AB 12'")
        df = sg.lookup(store.population_path, args.adres[0], int(args.adres[1]),
                       args.letter or "", args.toevoeging or "", methods=methods)
        if df.empty:
            print("geen eengezinswoning met dit adres in de populatie")
            return 1
        with pd.option_context("display.width", 200, "display.max_rows", 200):
            print(df.T.to_string(header=False))
    elif args.actie == "publiceer":
        return _signatuur_publiceer(args, store)
    else:  # regenboog
        from .rounding import rainbow
        steps = {}
        table = bool(args.bron)
        for item in args.stap or []:
            name, _, step = item.partition("=")
            steps[_population_column(name, table=table)] = float(step.replace(",", "."))
        if not steps:
            raise SystemExit("geef minstens één --stap, bv. --stap warmteverlies_best=10")
        exact = [_population_column(c, table=table) for c in (args.ook or [])]
        population = _source(args) if table else store.population()
        scope = parse_scope(_scope_from_args(args.scope), population)
        if not scope.is_everything():
            population = population.within(scope)
        freq = rainbow(population, steps, exact, out=args.out,
                       description=scope.description if not scope.is_everything() else "")
        k = Threshold(args.p if args.p is not None else P_DEFAULT).k
        small = freq.loc[freq["n"] < k, "n"].sum()
        print(f"{len(freq):,} verschillende afgeronde signaturen voor {freq['n'].sum():,} "
              f"woningen; {small:,} woningen ({100 * small / max(freq['n'].sum(), 1):.1f}%) "
              f"in een groep < {k}")
        if args.out:
            print(f"frequentietabel (zonder adressen): {args.out}")
    return 0


NORM_EERST = (
    "geef eerst je privacynorm op met --p (0,05-0,33): de maximale kans op heridentificatie die "
    "je aanvaardbaar vindt. Die norm hoort vast te staan vóór je naar de uitkomst kijkt; daarna "
    "pas afwegen hoe grof je afrondt en welke woningen je niet publiceert.")


# --verken standaard: a first look at every output that is usually published; 36 combinations
VERKEN_STANDAARD = {"H": [10.0, 25.0], "C": [1000.0, 2500.0], "Asol": [1.0, 2.0, 5.0],
                    "Ainf": [25.0, 50.0, 100.0]}


def _steps(items: list[str] | None) -> dict:
    out = {}
    for item in items or []:
        if item == "standaard":          # later --verken items override single outputs
            out.update({k: list(v) for k, v in VERKEN_STANDAARD.items()})
            continue
        name, _, val = item.partition("=")
        if name not in ("H", "C", "tau", "Asol", "Ainf"):
            raise SystemExit(f"onbekende uitkomst {name!r}; kies uit H, C, tau, Asol, Ainf")
        vals = [float(v.replace(",", ".")) for v in val.split(";" if ";" in val else ",")]
        out[name] = vals
    return out


def _koppel(df, spec) -> dict[str, str]:
    """--koppel to keywords for link(), with the chosen columns printed (names only)."""
    from .link import beschrijf_koppeling, koppel_kolommen
    try:
        kw = koppel_kolommen(df, spec)
    except ValueError as e:
        raise SystemExit(str(e))
    print(beschrijf_koppeling(kw), file=sys.stderr)
    return kw


def _meld_afbakening(scope) -> None:
    """Without --scope the comparison is against every dwelling in the Netherlands: say so."""
    if scope.is_everything():
        print("let op: geen --scope, dus vergeleken met alle woningen in Nederland; geef de "
              "afbakening van de dataset (bv. --scope eengezins=true) / no --scope: compared "
              "with all dwellings", file=sys.stderr)


def _meld_h3_niveau(df, qids) -> None:
    """Name the H3 level of each H3 column used as QID, so a wrong column or level shows."""
    import h3
    for q in qids:
        if q.spec.key != "h3_cel" or q.column not in df.columns:
            continue
        cells = df[q.column].dropna().astype(str)
        levels = sorted({h3.get_resolution(c) for c in cells if h3.is_valid_cell(c)})
        if levels:
            print(f"{q.column}: H3-niveau {', '.join(map(str, levels))}", file=sys.stderr)


def _signatuur_publiceer(args, store) -> int:
    from .publicatie import Plan, add_baseline, explore
    if args.p is None:
        raise SystemExit(NORM_EERST)
    if not args.adres:
        raise SystemExit("geef het databestand: anonymate signatuur publiceer data.csv --koppel ...")
    if not args.koppel:
        raise SystemExit("--koppel is nodig: de kolom met BAG-verblijfsobject-ID, of "
                         "postcode,huisnummer[,huisletter,toevoeging]")
    threshold = Threshold(args.p)
    df = read_dataset(args.adres[0])
    link_kw = _koppel(df, args.koppel)
    mapping = {c: "direct" for c in link_kw.values()}
    for pair in args.qid or []:
        col, _, key = pair.partition("=")
        mapping[col] = key
    qids, direct = qids_from(df, mapping, auto=args.auto)
    _meld_h3_niveau(df, qids)
    scenario = SCENARIOS[(args.scenario or "register").lower()]
    population = store.population()
    scope = parse_scope(_scope_from_args(args.scope), population)
    _meld_afbakening(scope)
    if not scope.is_everything():
        population = population.within(scope)
    method = (args.methode or ["passend"])[0]
    candidates = _steps(args.verken or args.stap)
    if not candidates:
        candidates = {"H": [50.0], "C": [5000.0]}
    if args.verken:
        table = explore(df, population, method, candidates, threshold, qids, scenario,
                        **link_kw)
        print(f"norm: p = {args.p:g} (k ≥ {threshold.k}); methode: {method}; "
              f"{len(df)} woningen")
        with pd.option_context("display.width", 200):
            print(table.to_string(index=False))
        if args.out:
            table.to_csv(args.out, index=False)
        return 0
    plan = Plan(method, {o: v[0] for o, v in candidates.items()})
    extended, sig_qids, never = add_baseline(df, population, plan, **link_kw)
    a = assess(extended, qids + sig_qids, population, threshold, scenario)
    _print_summary(a)
    n_out = int((~a.ok).sum())
    print(f"{plan.describe()}; niet te publiceren woningen: {n_out} van {len(df)}")
    if args.out:
        out = write(args.out, extended, a, drop_columns=sorted(set(direct + never)),
                    dataset_name=Path(args.adres[0]).name, population=population)
        print(f"uitvoer / output: {out}")
    return 0


def cmd_weerspoor(args) -> int:
    """Trace each dwelling's weather series back to a KNMI station or H3 cell."""
    from .store import Store
    from .weerspoor import (as_columns, grid_from, investigate, load_hourly,
                            read_series_source, utc_hours)
    series = read_series_source(args.reeksen, id_from=args.id_uit, id_col=args.woning,
                                time_col=args.tijd, value_col=args.waarde, pattern=args.patroon,
                                id_regex=args.id_regex, max_homes=args.steekproef)
    print(f"gelezen: {series['woning'].nunique()} woningen, {len(series):,} waarden")
    years = (str(args.jaar).split(",") if args.jaar else
             sorted({str(y) for y in utc_hours(series["tijd"]).dt.year.dropna().astype(int)}))
    store = Store.open(args.home)
    grid = grid_from(store, store.population())
    found = investigate(series, load_hourly(store, years), grid, id_col="woning",
                        time_col="tijd", value_col="waarde", variable=args.variabele)
    traced = found.per_home
    print("Getoetste hypotheses (één methode voor de hele dataset):")
    print(found.hypotheses.to_string(index=False))
    print(f"\nConclusie: {found.verdict}\nAdvies: {found.advice}")
    for note in found.findings or []:
        print(f"Bevinding: {note}")
    print()
    show = [c for c in ("woning", "uren", "regime", "locatie", "exact", "rms", "zekerheid",
                        "verschuiving_uur") if c in traced.columns]
    print("exact: de dataset gebruikte dit station of deze cel; anders de meest waarschijnlijke "
          "omgeving (typisch 5-25 km naast de echte plek), getoetst met die onzekerheid")
    print(traced[show].to_string(index=False))
    if args.uit:
        traced.to_csv(args.uit, index=False)
        print(f"-> {args.uit}")
    if args.dataset:
        df = read_dataset(Path(args.dataset))
        key = args.dataset_woning or args.woning or "woning"
        from .weerspoor import check_assignment
        cols = as_columns(traced).rename(columns={"woning": key})
        df[key] = df[key].astype(str)
        cols[key] = cols[key].astype(str)
        out = df.merge(cols, on=key, how="left")
        stations, notes = check_assignment(out, key, traced, store.population(), grid.stations)
        out["weer_knmi_station"] = stations.where(stations.notna(), out["weer_knmi_station"])
        for note in notes:
            print(f"Bevinding: {note}")
        target = args.dataset_uit or str(Path(args.dataset).with_suffix("")) + "_weerspoor.csv"
        out.to_csv(target, index=False)
        print(f"dataset met afgeleide weerlocatie (toets die als verborgen locatie) -> {target}")
    return 0


def cmd_representativiteit(args) -> int:
    """Compare the dataset with its target population; publish the outcome, not the features."""
    import json

    from . import representativiteit as rp
    df = read_dataset(args.dataset, args.sheet)
    population = open_population(args, {})
    scope = parse_scope(_scope_from_args(args.scope), population)
    _meld_afbakening(scope)
    if not scope.is_everything():
        population = population.within(scope)
    wanted = []  # (dataset column given with "kolom:", name given, population column, edges)
    for item in args.kenmerk:
        name, _, edges = item.partition("=")
        source, _, given = name.rpartition(":")
        grenzen = tuple(float(e.replace(",", ".")) for e in edges.split(";" if ";" in edges
                                                                        else ",") if e)
        wanted.append((source, given, _population_column(given), grenzen))
    if args.koppel:
        from .link import link
        linked = link(df, population, **_koppel(df, args.koppel))
        found = linked["register_gekoppeld__bool"]
        print(f"gekoppeld / linked: {int(found.sum())} van {len(df)} records "
              "(alleen die worden vergeleken)")
        df = linked[found].copy()
        ids = df["register_vbo_id__str"].astype(str)
        for source, _, column, _ in wanted:
            if not source and "register_" + column not in df.columns:
                df["register_" + column] = ids.map(
                    population.lookup(column, "vbo_id__str", ids.tolist()))
    specs = []
    for source, given, column, grenzen in wanted:
        if not source:
            # register values on both sides, so a difference is not a difference in definition;
            # without --koppel "--kenmerk bouwjaar" takes the dataset's own column bouwjaar
            source = ("register_" + column if args.koppel else
                      given if given in df.columns else column)
        specs.append(rp.Kenmerk(column, source, grenzen))
    k = Threshold(args.p if args.p is not None else P_DEFAULT).k
    v = rp.vergelijk(df, population, specs, k=k, draws=args.trekkingen, seed=args.seed)
    print(v.markdown())
    if args.uit:
        Path(args.uit).write_text(json.dumps(v.to_dict(), ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"uitvoer / output: {args.uit}")
    if args.rapport:
        Path(args.rapport).write_text(v.markdown(), encoding="utf-8")
        print(f"rapport / report: {args.rapport}")
    return 0


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
    p.add_argument("source", choices=["all", "bag", "gebieden", "knmi", "knmi-uur", "ep-online",
                                      "3dbag", "pakket", "uhi"],
                   help="'all' laat 3dbag weg: dat is ~9.000 tegels / ~20 GB downloaden; "
                        "'uhi' haalt het hitte-eiland per postcode op (RIVM; --file: eigen "
                        "kopie van de tabel, of --raster voor per woning); "
                        "'pakket' maakt de populatie uit een datapakket (--file map of zip; zonder "
                        "--file wordt het laatste openbare pakket gedownload), "
                        "met EP-online erbij als je die zelf hebt ingelezen")
    p.add_argument("--max-tegels", type=int, help="3dbag: alleen de eerste N tegels (proberen)")
    p.add_argument("--jaar", help="knmi-uur: jaar of jaren, bv. 2023,2024")
    p.add_argument("--file", help="al gedownload bestand gebruiken (bag-light.gpkg, "
                                  "EP-online-totaalbestand, of 3D-BAG-GeoPackage/-map)")
    p.add_argument("--raster", nargs="?", const="", metavar="TIF_OF_ZIP",
                   help="uhi: per woning uit de RIVM-kaart bemonsteren (GeoTIFF of zip; zonder "
                        "waarde wordt de zip van ~2 GB gedownload); vraagt 'pip install "
                        "anonymate[uhi]'")
    p.add_argument("--downloads", help="map voor grote originele bestanden, bv. een NAS "
                                       "(of $ANONYMATE_DOWNLOADS)")
    p.add_argument("--tegels-weggooien", action="store_true",
                   help="3dbag: elke tegel na het inlezen weggooien (scheelt ~20 GB)")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("pakketten", help="datapakketten van de populatie maken, zonder "
                                         "EP-online-gegevens / data packages without EP-online")
    p.add_argument("--uit", required=True, help="map voor de pakketten")
    p.add_argument("--publicatie", help="map voor de twee publicatiebestanden: "
                                        "anonymate-datapakket.zip en manifest.json (met sha256)")
    p.set_defaults(func=cmd_pakketten)

    p = sub.add_parser("build", help="lokale populatie opbouwen uit de ingelezen bronnen")
    p.add_argument("--h3", help="H3-resoluties, bv. 4,5,6,7,8")
    p.add_argument("--signaturen", action="store_true",
                   help="alleen de signatuurkolommen van de bestaande populatie opnieuw berekenen")
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
                            "bouwjaar=1900-1989 of eengezins=true")
        p.add_argument("--unknown-matches", action="store_true",
                       help="woningen met onbekende waarde tellen mee als match (minder streng)")
        p.add_argument("--koppel", metavar="KOLOMMEN",
                       help="lokaal koppelen aan de BAG: 'auto', één kolom met verblijfsobject-"
                            "ID, postcode,huisnummer[,huisletter,toevoeging] (lege plek voor een "
                            "ontbrekend deel), of met namen: postcode=..,huisnummer=..,"
                            "toevoeging=..; voegt register_*-kolommen toe (de koppelkolommen "
                            "worden nooit gepubliceerd)")
        p.add_argument("--kandidaten", action="store_true",
                       help="per record met risico de passende woningen met adres, voor de "
                            "bronhouder (NIET publiceren)")
        p.add_argument("--synthetic", action="store_true",
                       help="synthetische populatie gebruiken (om te proberen, zonder downloads)")
        p.add_argument("--out", help="uitvoermap voor publiceerbare dataset en rapporten")
        if name == "suggest":
            p.add_argument("--doel", type=float, default=TARGET_SHARE,
                           help="gewenst aandeel publiceerbare records (standaard 0,95)")
        p.set_defaults(func=func)

    p = sub.add_parser("afronding", help="hoe grof moet een berekenbare grootheid (bv. de "
                                         "warmtesignatuur) gepubliceerd worden?")
    p.add_argument("--kolom", action="append", required=True, metavar="KENMERK=STAPPEN",
                   help="bv. warmteverlies=5,10,20 of thermische_massa=500,1000,2000 "
                        "(QID uit de catalogus of populatiekolom)")
    p.add_argument("--ook", action="append", metavar="KENMERK",
                   help="ook exact gepubliceerd, bv. knmi_station of woningtype")
    p.add_argument("--scope", action="append", metavar="KOLOM=WAARDE",
                   help="populatie afbakenen, bv. eengezins=true")
    p.add_argument("--p", type=float, help=f"drempel p (standaard {P_DEFAULT})")
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--bron", help="functionele signatuurtabel (anonymate signatuur tabel) "
                                  "i.p.v. de populatie")
    p.add_argument("--out", help="tabel als CSV")
    p.set_defaults(func=cmd_afronding)

    p = sub.add_parser("signatuur", help="warmtesignatuur uit openbare gegevens: "
                                         "tabel voor alle woningen, per adres, of rainbow-"
                                         "frequentietabel")
    p.add_argument("actie", choices=["tabel", "adres", "regenboog", "publiceer"])
    p.add_argument("adres", nargs="*", help="bij 'adres': postcode en huisnummer; bij "
                                           "'publiceer': het databestand")
    p.add_argument("--letter", help="huisletter")
    p.add_argument("--toevoeging", help="huisnummertoevoeging")
    p.add_argument("--methode", action="append", choices=list(SIGNATURE_METHODS),
                   help="standaard alle")
    p.add_argument("--detail", action="store_true",
                   help="bij 'tabel': ook oppervlakken, U-waarden en gebruikte bron")
    p.add_argument("--stap", action="append", metavar="KENMERK=STAP",
                   help="afrondstap; bij 'regenboog' bv. warmteverlies_best=10, bij "
                        "'publiceer' per uitkomst: H=50, C=5000, tau=20, Asol=10")
    p.add_argument("--verken", action="append", metavar="UITKOMST=STAPPEN",
                   help="bij 'publiceer': meerdere stappen naast elkaar, bv. H=10,25,50; "
                        "'standaard' = H, C, Asol en Ainf in een vast rooster")
    p.add_argument("--koppel", help="bij 'publiceer': 'auto', BAG-ID-kolom, postcode,huisnummer"
                                    "[,...] of postcode=..,huisnummer=.. (wordt nooit "
                                    "gepubliceerd)")
    p.add_argument("--qid", action="append", metavar="KOLOM=QID",
                   help="bij 'publiceer': overige gepubliceerde kenmerken als QID")
    p.add_argument("--auto", action="store_true", help="bij 'publiceer': gedetecteerde QID's")
    p.add_argument("--scenario", choices=sorted(SCENARIOS))
    p.add_argument("--ook", action="append", metavar="KENMERK",
                   help="bij 'regenboog': ook exact gepubliceerd, bv. knmi_station")
    p.add_argument("--scope", action="append", metavar="KOLOM=WAARDE",
                   help="afbakening, ook uitsluiten: kolom!=waarde")
    p.add_argument("--bron", help="bij 'regenboog': een functionele signatuurtabel als bron, "
                                  "bv. om met --scope een scherpere tabel voor een deelgebied "
                                  "te maken")
    p.add_argument("--p", type=float)
    p.add_argument("--out", help="uitvoerbestand (Parquet)")
    p.set_defaults(func=cmd_signatuur)

    p = sub.add_parser("weerspoor", help="weerreeksen per woning terugleiden naar het meest "
                                         "waarschijnlijke KNMI-station of H3-cel")
    p.add_argument("reeksen", help="bestand, map of zip met weerreeksen per woning")
    p.add_argument("--id-uit", choices=["kolom", "bestand", "map"], default="kolom",
                   help="waar de woning-ID staat: een kolom, de bestandsnaam "
                        "(IM_customer_<id>.csv, home_id=<id>.parquet) of de mapnaam")
    p.add_argument("--patroon", default="*", help="bestandsnamen in een map of zip, bv. "
                                                  "'IM_customer_*.csv' of 'knmi.csv'")
    p.add_argument("--id-regex", help="reguliere expressie met één groep voor de ID in de naam")
    p.add_argument("--steekproef", type=int, default=300,
                   help="aantal woningen om de methode te bepalen (standaard 300)")
    p.add_argument("--woning", help="kolom met de woning-ID (standaard: geraden)")
    p.add_argument("--tijd", help="kolom met het tijdstip (standaard: geraden)")
    p.add_argument("--waarde", help="kolom met de buitentemperatuur (standaard: geraden)")
    p.add_argument("--variabele", choices=["T", "Q"], default="T",
                   help="T: temperatuur [°C]; Q: globale straling [W/m²]")
    p.add_argument("--jaar", help="jaren met KNMI-uurgegevens (standaard: uit de reeksen)")
    p.add_argument("--uit", help="uitvoer per woning (csv)")
    p.add_argument("--dataset", help="dataset met één rij per woning: kolommen toevoegen")
    p.add_argument("--dataset-woning", help="kolom met de woning-ID in --dataset")
    p.add_argument("--dataset-uit", help="uitvoer van --dataset (csv)")
    p.set_defaults(func=cmd_weerspoor)

    p = sub.add_parser("representativiteit",
                       help="lijkt de dataset op de doelpopulatie? publiceer de uitkomst, niet de "
                            "kenmerken per record")
    p.add_argument("dataset", help="CSV, Excel of Parquet")
    p.add_argument("--sheet", help="Excel-tabblad")
    p.add_argument("--kenmerk", action="append", required=True,
                   metavar="[DATASETKOLOM:]KOLOM[=GRENZEN]",
                   help="kenmerk van de populatie, bv. woningtype of bouwjaar=1945,1965,1975,"
                        "1992,2006 (klassen); DATASETKOLOM: als de dataset het anders noemt")
    p.add_argument("--koppel", metavar="KOLOMMEN",
                   help="eerst koppelen aan de BAG ('auto', verblijfsobject-ID, postcode,"
                        "huisnummer[,huisletter,toevoeging] of postcode=..,huisnummer=..) en "
                        "de registerwaarden vergelijken")
    p.add_argument("--scope", action="append", metavar="KOLOM=WAARDE",
                   help="doelpopulatie, dezelfde afbakening als bij de toets")
    p.add_argument("--p", type=float, help=f"drempel p (standaard {P_DEFAULT}); aandelen "
                                           "alleen voor klassen met minstens k records")
    p.add_argument("--trekkingen", type=int, default=1000,
                   help="aselecte steekproeven voor 'toeval' (standaard 1000)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--uit", help="uitkomst als JSON, met alle parameters")
    p.add_argument("--rapport", help="uitkomst als Markdown")
    p.set_defaults(func=cmd_representativiteit)

    p = sub.add_parser("wizard", help="stap voor stap, met vragen")
    p.add_argument("dataset", nargs="?")
    p.set_defaults(func=cmd_wizard)
    return ap


def _utf8_console() -> None:
    """Help texts and reports use δ and ≥; a Windows console (cp1252) cannot print those."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"fout / error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
