"""The facade for the web version (docs/werk/webversie.md): plain dicts in, plain dicts out.

The browser runs this module in Pyodide, inside a Web Worker; the page only exchanges JSON with
it. Everything here calls the same functions as the command line and the desktop window, and
none of it touches the network: a dataset arrives as bytes and results leave as bytes, which
the page offers as a download.

One session per worker: the dataset, the population and the last assessment stay in memory
between calls, so a step never has to send the data back and forth. The steps of the desktop
window (:mod:`anonymate.gui`) map onto these functions: ``open_*`` and ``set_region`` (1),
``norm`` and ``lock_norm`` (2), ``run``, ``record``, ``suggest``, ``apply`` and ``export``
(6 and 7). Texts and numbers come from the same code as the desktop
(:mod:`anonymate.stappen`), so both show the same.
"""
from __future__ import annotations

import io
import json
import math
import re
import secrets
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .detect import Role, derive_h3_columns, detect
from .explain import information_bits
from .invoer import SCENARIOS, qids_from, read_dataset
from .population import Population, Snapshot
from .qids import CATALOGUE
from .risk import P_DEFAULT, P_MAX, P_MIN, Assessment, Status, Threshold, assess
from .stappen import (NO_MATCH_TIP, STATUS_TEXT, UHI, UNKNOWN_TIP, WEATHER_H3, WEATHER_STATION,
                      bits_note, guess_gps, histogram_note, houses_for, k_histogram, k_line,
                      link_columns, merge_scope, nl, nr, numeric_columns, numeric_flags,
                      readable_error, record_card, region_scope, region_text,
                      representativeness_lines, stat_tiles, station_text, table_cell,
                      TRADEOFF_TEXTS, TRADEOFF_VIEWS, IDEAL_FROM_X, target_count_text, target_label,
                      target_note, tradeoff_points, weather_zones)

# the same texts as the desktop window (gui.py)
ROLE_LABELS = {
    Role.DIRECT: "direct identificerend: weglaten",
    Role.QID: "quasi-identifier",
    Role.IMPLICIT_LOCATION: "verborgen locatie",
    Role.DERIVED: "afgeleid (lekt hetzelfde)",
    Role.MEASUREMENT: "meetwaarde",
}
NORM_MARKS = [(0.05, "streng: openbare publicatie van gevoelige gegevens"),
              (0.09, "standaard van AnonyMate"),
              (0.10, "netbeheerders, verbruik per PC6"),
              (0.20, "medisch, gecontroleerde toegang"),
              (0.33, "ondergrens, gecontroleerde toegang")]
PROVINCES = ["Drenthe", "Flevoland", "Fryslân", "Gelderland", "Groningen", "Limburg",
             "Noord-Brabant", "Noord-Holland", "Overijssel", "Utrecht", "Zeeland", "Zuid-Holland"]
EXCEL = (".xlsx", ".xlsm", ".xls")


@dataclass
class Session:
    df: pd.DataFrame | None = None          # the dataset as opened (or as generalised)
    current: pd.DataFrame | None = None     # what the last assessment looked at
    name: str = ""
    practice: bool = False
    population: Population | None = None    # the whole population
    scoped: Population | None = None        # the population the last assessment used
    proposal: dict[str, str] = field(default_factory=dict)
    mapping: dict[str, str] = field(default_factory=dict)
    qids: list = field(default_factory=list)
    direct: list[str] = field(default_factory=list)
    threshold: Threshold = field(default_factory=Threshold)
    norm_locked: bool = False
    scenario: str = "register"
    region: dict = field(default_factory=dict)
    scope_text: str = ""
    assessment: Assessment | None = None
    shown: pd.DataFrame | None = None       # the table of the outcome, one row per record
    steps: list | None = None               # the searched generalisations (never shortened)
    export_steps: list | None = None        # the steps the report tells about
    target_share: float | None = None       # the target of that search (None: the default)
    seed: int | None = None                 # noise of the weather cell: drawn once, then reused
    tolerance: float = 0.0                  # what the attacker's search allows for (weather noise)
    uhi_frame: pd.DataFrame | None = None   # the UHI table, for the population when UHI is published
    uhi_pop: tuple | None = None            # (key, population with UHI), joined once
    loc: tuple | None = None                # (key, lat/lon/postcode6 per record)
    trace_found: object = None              # what the detective found, until it is applied
    trace_key: str = ""
    map_key: tuple | None = None
    map_data: object = None                 # kaart.ScopedMapData of the region
    layers: tuple | None = None             # (key, map_layers() answer)


S = Session()


def _clean(x):
    """JSON-safe: numpy scalars to Python, NaN and infinity to None."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):
        x = x.item()
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def readable(message: str) -> str:
    """An error as the page got it (a Python traceback, or 'Type: text') as text for people."""
    lines = str(message).strip().splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if re.match(r"^\w+(?:Error|Exception):", lines[i]):
            return readable_error("\n".join(lines[i:]))
    return readable_error(lines[-1] if lines else "")


# --- step 1: the dataset and the region ----------------------------------------------------------
def practice_population(population_path: str | None = None) -> Population:
    """The made-up Netherlands of the practice mode, built once per worker. With
    ``population_path`` (web/maak.py writes it as oefenpopulatie.parquet) DuckDB reads that file
    and nothing has to be made up, so neither pandas work nor h3 is needed at start-up."""
    if S.population is None or not S.practice:
        snapshot = Snapshot({"oefenpopulatie": "verzonnen"})     # the same on both routes
        if population_path:
            S.population = Population.from_parquet(str(population_path), snapshot)
        else:
            from . import voorbeeld
            S.population = Population.from_dataframe(voorbeeld.population(), snapshot)
    return S.population


def open_practice(population_path: str | None = None, progress=None) -> dict:
    """Open the example dataset against the made-up Netherlands, read from
    ``population_path`` when given, else made up in memory. ``progress(fraction, text)`` hears
    the phases."""
    from . import voorbeeld
    from .voortgang import Voortgang
    vg = Voortgang(None, progress)
    S.practice = True
    vg.set(0.0, "de verzonnen populatie " + ("lezen" if population_path else "maken"))
    practice_population(population_path)
    vg.set(0.8, "de voorbeelddataset lezen")
    out = _open(read_dataset(voorbeeld.WONINGEN), voorbeeld.WONINGEN.name)
    vg.set(1.0)
    return out


def open_bytes(name: str, data: bytes) -> dict:
    """Open a dataset the user chose, given as bytes."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(name).name
        path.write_bytes(bytes(data))
        return open_file(str(path), name)


def open_file(path: str, name: str) -> dict:
    """Open a dataset the page wrote into the worker's in-memory file system, and remove it
    from there once read: the table stays in memory, the file does not linger."""
    p = Path(path)
    try:
        try:
            df = read_dataset(p)
        except ImportError as e:
            if p.suffix.lower() in EXCEL and "openpyxl" in str(e):
                raise ValueError("Excel-bestanden (.xlsx) volgen in een latere versie van de "
                                 "webversie. Sla het werkblad nu op als CSV (in Excel: Opslaan "
                                 "als, CSV) en open die.") from e
            raise
    finally:
        p.unlink(missing_ok=True)
    S.practice = True          # until the web version has the real population (fase 3)
    practice_population()
    return _open(df, name)


def stop_practice() -> dict:
    """Leave the practice mode as the desktop does: the open dataset goes, and step 1 asks for
    another one. (The real population comes with fase 3: a dataset of your own is still
    assessed against the made-up Netherlands until then.)"""
    S.practice = False
    S.df = S.current = S.assessment = S.shown = S.steps = S.export_steps = S.scoped = None
    S.mapping, S.proposal, S.norm_locked = {}, {}, False
    _reset_weather()
    return {"practice": False}


def _open(df: pd.DataFrame, name: str) -> dict:
    """Start a session on ``df``: the H3 columns derived, and every column preselected exactly
    as the desktop window does (``MainWindow.load``)."""
    df, derived = derive_h3_columns(df)
    S.df, S.current, S.name = df, df, name
    S.assessment = S.shown = S.steps = S.export_steps = S.scoped = None
    S.norm_locked = False           # a new dataset: fix the norm again before assessing
    _reset_weather()
    S.direct = []
    found = detect(df)
    S.proposal = {}
    for d in found:
        if d.column in derived:
            S.proposal[d.column] = derived[d.column]
        elif d.role == Role.DIRECT:
            S.proposal[d.column] = "direct"
        elif d.role in (Role.QID, Role.IMPLICIT_LOCATION) and d.qid:
            S.proposal[d.column] = d.qid
        else:
            S.proposal[d.column] = "geen"
    S.mapping = dict(S.proposal)
    numeric = numeric_columns(df)
    return _clean({
        "name": name, "records": len(df), "columns": list(df.columns),
        "population": S.population.size() if S.population is not None else None,
        "practice": S.practice,
        "detections": [{"column": d.column, "role": d.role, "qid": d.qid,
                        "reason": d.reason,
                        "proposal": ROLE_LABELS[d.role] + (f": {d.qid}" if d.qid else ""),
                        "default": S.proposal[d.column],
                        "derived": d.column in derived} for d in found],
        "catalogue": {k: v.label_nl for k, v in CATALOGUE.items()},
        "link_columns": link_columns(found),
        "numeric_columns": numeric,
        "gps": list(guess_gps(numeric)),
        "region": region_text(S.region),
        "norm": {"p_min": P_MIN, "p_max": P_MAX, "p": S.threshold.p, "default": P_DEFAULT,
                 "marks": [{"p": p, "k": Threshold(p).k, "text": t} for p, t in NORM_MARKS]},
        "provinces": PROVINCES,
    })


def set_region(heel_nederland: bool = True, provincies=(), gemeenten="") -> dict:
    """The region of step 1. It stays in the session: assess, suggest, apply and export all use
    it, on top of the free-text scope of step 6."""
    S.region = region_scope(bool(heel_nederland), list(provincies or ()), gemeenten or "")
    return {"text": region_text(S.region)}


# --- step 2: the norm ---------------------------------------------------------------------------
def norm(p: float) -> dict:
    """What a norm p means: k, the big label, the houses and the explanation of the desktop
    window. When the norm is locked, that one is shown whatever ``p`` is."""
    t = S.threshold if S.norm_locked else Threshold(round(float(p), 2))
    filled = min(t.k, 20)
    return {"p": t.p, "k": t.k, "big": f"k ≥ {t.k}", "houses": [filled, filled, 0],
            "text": f"Elke woning in de dataset moet lijken op minstens {t.k} woningen in de "
                    f"populatie: wie er één zoekt, heeft hooguit 1 op {t.k} kans. Van zo'n "
                    f"groep mag hooguit {t.p:.0%} in de dataset zitten.",
            "locked": S.norm_locked}


def lock_norm(p: float | None = None) -> dict:
    """Fix the norm (``p``, or the last one shown). It stays fixed until a new dataset is
    opened, so it cannot be tuned to the outcome; assessing is only possible after this."""
    if S.df is None:
        raise ValueError("open eerst een dataset")
    t = Threshold(round(float(S.threshold.p if p is None else p), 2))
    S.threshold, S.norm_locked = t, True
    out = norm(t.p)
    out["label"] = f"Vastgelegd: p = {t.p:g} (k ≥ {t.k}); blijft vast voor deze dataset."
    return out


# --- steps 6 and 7: assess, search, adopt, save ---------------------------------------------
def _inputs(mapping, scenario, scope):
    """The QIDs, the direct identifiers and the (scoped) population of an assessment, from what
    the page sends (None: what the session has), like the desktop's ``_inputs`` (``auto=False``:
    the mapping is complete)."""
    if S.df is None:
        raise ValueError("open eerst een dataset")
    if not S.norm_locked:
        raise ValueError("Leg eerst de privacynorm vast (stap 2).")
    if mapping is not None:
        S.mapping = {str(k): str(v) for k, v in dict(mapping).items()}
    if scenario is not None:
        S.scenario = str(scenario)
    if scope is not None:
        S.scope_text = str(scope)
    if S.scenario not in SCENARIOS:
        raise ValueError(f"onbekende aanvaller: {S.scenario}")
    try:
        S.qids, S.direct = qids_from(S.df, S.mapping, auto=False)
    except SystemExit as e:
        raise ValueError(str(e)) from None
    if S.tolerance:                 # the weather cell after noise: the search allows for sigma
        from .risk import QidColumn
        S.qids = [QidColumn(q.column, q.spec, S.tolerance) if q.column == WEATHER_H3 else q
                  for q in S.qids]
    population = _with_uhi(S.population)
    sc = merge_scope(S.region, S.scope_text, population)
    S.scoped = population if sc.is_everything() else population.within(sc)
    return S.qids, S.direct, S.scoped


def _bits(df, a, population):
    """(bits needed, per attribute, remaining bits per record), or None when it fails."""
    try:
        return information_bits(df, a, population)
    except Exception:  # noqa: BLE001 (the picture is optional; the assessment stands)
        return None


def _show(df: pd.DataFrame, a: Assessment, title_suffix: str = "") -> dict:
    """Keep ``a`` as the outcome and describe it: what the desktop's ``_show_assessment``
    shows (the cards, the bits, the histogram, the table and the Toelichting)."""
    S.current, S.assessment = df, a
    s = a.summary()
    n = s["records"] or 1
    n_out = s["records"] - s["ok"]
    text = [f"{s['ok']} van {s['records']} records publiceerbaar ({100 * s['ok'] / n:.0f}%), "
            f"{s['risico']} met risico, {s['geen_match']} zonder match in de populatie.",
            k_line(s),
            f"populatie: {s['populatie']:,} woningen ({s['afbakening']}); "
            f"bronnen: {s['snapshot']}"]
    if n_out:
        text.append(f"{n_out} woningen blijven te herleidbaar: die worden NIET opgenomen in "
                    "publiceerbaar.csv. Grover afronden of meer kenmerken grover maken kan "
                    "dat aantal verkleinen; de norm blijft staan.")
        if s["ok"]:
            drop = set(S.direct or [])
            text += representativeness_lines(df, a.ok, [c for c in df.columns if c not in drop])
    text += [f"let op: {w}" for w in a.warnings]

    norm_k = s["k_drempel"]
    bits = _bits(df, a, S.scoped)
    median = None      # the remaining bits: unknown (not 0) without bits or without a match
    if bits is not None and bits[2].notna().any():
        median = float(bits[2].median())
    tiles = stat_tiles(s, median)
    stats = {key: text for key, (text, _tip) in tiles.items()}
    stats_tips = {key: tip for key, (_text, tip) in tiles.items() if tip}
    bits_out = None
    if bits is not None:
        needed, parts, _remaining = bits
        bits_out = {"needed": needed, "remaining_median": median, "norm_bits": math.log2(norm_k),
                    "parts": [{"column": b.column, "median": b.median, "estimated": b.estimated}
                              for b in parts],
                    "note": bits_note(needed, s["populatie"], median)}

    shown = df[[q.column for q in a.qids]].join(a.records[["k", "delta", "status", "redenen"]])
    S.shown = shown
    cols = list(shown.columns)
    statuses = list(shown["status"])
    rows = [[table_cell(v, cols[j], st)[0] for j, v in enumerate(row)]
            for st, row in zip(statuses, shown.itertuples(index=False))]
    risky = [i for i, st in enumerate(statuses) if st != Status.OK]
    return _clean({
        "title": f"{s['ok']} van de {s['records']} woningen publiceerbaar{title_suffix}",
        "summary": s, "warnings": a.warnings, "direct": S.direct, "mapping": S.mapping,
        "threshold": {"p": S.threshold.p, "k": S.threshold.k, "bits": math.log2(norm_k)},
        "stats": stats, "stats_tips": stats_tips, "bits": bits_out,
        "histogram_note": histogram_note(s["geen_match"]),
        "histogram": [{"lo": lo, "hi": hi, "n": c}
                      for lo, hi, c in k_histogram(list(a.records["k"]), norm_k)],
        "table": {"columns": cols, "rows": rows, "status": statuses,
                  "tips": {"dash": UNKNOWN_TIP, "no_match": NO_MATCH_TIP},
                  "numeric": numeric_flags(rows, len(cols)),
                  "selected": (risky[0] if risky else 0) if rows else None},
        "toelichting": text,
    })


def run(mapping: dict | None = None, scenario: str | None = None, scope: str | None = None,
        progress=None) -> dict:
    """Assess the open dataset, like the desktop's "Toetsen". ``mapping`` is complete (a
    catalogue key, 'direct' or 'geen' per column; None: the preselected one), ``scenario`` the
    attacker, ``scope`` the free-text population scope (combined with the region of step 1).
    The norm must have been locked."""
    from .voortgang import Voortgang
    vg = Voortgang(None, progress)
    vg.set(0.0, "populatie voorbereiden")
    _inputs(mapping, scenario, scope)
    S.steps = S.export_steps = None
    vg.set(0.3, "woningen toetsen")
    a = assess(S.df, S.qids, S.scoped, S.threshold, SCENARIOS[S.scenario])
    vg.set(0.9, "uitkomst opstellen")
    return _show(S.df, a)


def record(index: int) -> dict:
    """The card of one dwelling of the outcome: title, text and the houses."""
    if S.shown is None or S.assessment is None:
        raise ValueError("toets eerst")
    i = int(index)
    rec = S.shown.iloc[i]
    norm_k = S.assessment.summary()["k_drempel"]
    k = rec["k"]
    k_int = 0 if pd.isna(k) else int(k)
    title, body = record_card(rec, k, norm_k, rec["delta"], rec["status"], index=i)
    return _clean({"index": i, "title": title, "text": body, "status": rec["status"],
                   "houses": list(houses_for(k_int, norm_k))})


def target_text(share: float | None = None) -> str:
    """The count under the target field: "95% van 62 woningen: minstens 59 publiceerbaar"."""
    from .generalize import TARGET_SHARE
    share = TARGET_SHARE if share is None else float(share)
    return target_count_text(0 if S.df is None else len(S.df), share)


def suggest(mapping: dict | None = None, scenario: str | None = None, scope: str | None = None,
            target_share: float | None = None, progress=None) -> dict:
    """Search generalisations that let more records pass, and assess the last step, like the
    desktop's "Generalisaties zoeken". Nothing is applied to the dataset yet.
    ``progress(fraction, text)`` hears how far the search is."""
    from .generalize import LOSS_NOTE, TARGET_SHARE, suggest as search
    target_share = TARGET_SHARE if target_share is None else float(target_share)
    _inputs(mapping, scenario, scope)
    steps = search(S.df, S.qids, S.scoped, S.threshold, SCENARIOS[S.scenario],
                   target_share=target_share, progress=progress)
    last = steps[-1]
    a = assess(last.df, last.qids, S.scoped, S.threshold, SCENARIOS[S.scenario])
    S.steps = S.export_steps = steps
    S.target_share = target_share
    out = _show(last.df, a, ", na generalisatie")
    lines, rows = ["", "Generalisatiestappen:"], []
    for i, st in enumerate(steps):
        r = st.row()
        label = str(r["stap"]).split(" / ")[0]
        lines.append(f"  {r['stap']}: {r['publiceerbaar_%']:.0f}% publiceerbaar, "
                     f"informatieverlies {r['informatieverlies']:.2f}")
        rows.append({"label": label, "pct": float(r["publiceerbaar_%"]),
                     "loss": float(r["informatieverlies"]),
                     "text": f"{i}. {label} · {r['publiceerbaar_%']:.0f}%"})
    out["toelichting"] = out["toelichting"] + lines
    out["steps"] = _clean(rows)
    out["target"] = {"pct": round(100 * target_share, 1), "label": target_label(target_share),
                     "note": target_note(target_share), "loss_note": LOSS_NOTE,
                     "count": target_text(target_share)}
    # both views of the chart, worked out by the core (stappen.tradeoff_points)
    out["tradeoff"] = {"ideal_from": IDEAL_FROM_X, "views": {
        v: {**TRADEOFF_TEXTS[v], "points": _clean(tradeoff_points(rows, v))}
        for v in TRADEOFF_VIEWS}}
    out["selected_step"] = len(rows) - 1
    out["can_adopt"] = len(rows) > 1
    return out


def apply(step: int) -> dict:
    """Take over generalisation ``step`` (into the dataset) and assess again, like the
    desktop's "Overnemen". The list of steps stays as it was."""
    if not S.steps:
        raise ValueError("zoek eerst generalisaties")
    i = int(step)
    if not 0 < i < len(S.steps):
        raise ValueError("Kies in de lijst een stap na de uitgangssituatie.")
    chosen = S.steps[i]
    S.df = chosen.df
    keys = {q.column: q.spec.key for q in chosen.qids}
    changed = [c for c in S.mapping if c in keys]
    for c in changed:
        S.mapping[c] = keys[c]
    _inputs(None, None, None)
    S.export_steps = None                   # as on the desktop: the report tells no steps now
    a = assess(S.df, S.qids, S.scoped, S.threshold, SCENARIOS[S.scenario])
    out = _show(S.df, a)
    out["adopted"] = {"step": i, "description": chosen.description, "columns": changed,
                      "reason": f"gegeneraliseerd tot en met stap {i}"}
    return _clean(out)


def export() -> bytes:
    """A zip with publiceerbaar.csv, rapport.md, samenvatting.json and rapport_per_record.csv
    (internal), written by the same code as the command line, in memory."""
    import tempfile
    from .report import write
    if S.assessment is None:
        raise ValueError("toets eerst")
    with tempfile.TemporaryDirectory() as tmp:
        out = write(Path(tmp) / "uit", S.current, S.assessment, drop_columns=S.direct,
                    steps=S.export_steps, dataset_name=S.name, population=S.scoped,
                    target_share=S.target_share)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(out.iterdir()):
                z.write(f, f.name)
    return buf.getvalue()


def status_counts() -> dict:
    if S.assessment is None:
        return {}
    st = S.assessment.records["status"]
    return {s: int((st == s).sum()) for s in (Status.OK, Status.AT_RISK, Status.NO_MATCH)}


# --- step 5: weather location, map, UHI, the weather trace --------------------------------------
# What the desktop's _page_weather does (gui.py) and the map of gui_kaart.py, as functions. H3 and
# the map/weather modules are imported inside them: the start of the page needs none of it.
NO_POPULATION = ("Geen populatie: de echte populatie volgt in een latere versie van de "
                 "webversie. Oefen met het voorbeeld.")


def _reset_weather() -> None:
    """A new dataset: no weather noise drawn, no UHI, no trace, as ``MainWindow.load``."""
    S.seed, S.tolerance, S.uhi_frame, S.uhi_pop, S.loc = None, 0.0, None, None, None
    S.trace_found, S.trace_key = None, ""


def _population() -> Population:
    if S.population is None:
        raise ValueError(NO_POPULATION)
    return S.population


def _with_uhi(population: Population) -> Population:
    """The population with the UHI of the chosen file, when UHI is published (``_with_uhi`` of
    the desktop window). Joined once per file."""
    if (S.df is None or UHI not in S.df.columns or S.uhi_frame is None
            or "uhi" in population.columns or "postcode6" not in population.columns):
        return population
    if S.uhi_pop is None or S.uhi_pop[0] is not population or S.uhi_pop[1] is not S.uhi_frame:
        from .stappen import population_with_uhi
        S.uhi_pop = (population, S.uhi_frame, population_with_uhi(population, S.uhi_frame))
    return S.uhi_pop[2]


def _round_ring(points) -> list:
    """A ring of (lon, lat) with 4 decimals (about 10 m), without repeated points."""
    out: list = []
    for x, y in points:
        q = [round(float(x), 4), round(float(y), 4)]
        if not out or out[-1] != q:
            out.append(q)
    return out


def _cell_ring(cell: str) -> list:
    """The boundary of an H3 cell as a ring of [lon, lat]."""
    import h3
    return _round_ring((lo, la) for la, lo in h3.cell_to_boundary(cell))


def _need_df() -> pd.DataFrame:
    if S.df is None:
        raise ValueError("open eerst een dataset")
    return S.df


def _map_data():
    """The map's data of the region chosen in step 1 (``_ensure_map`` of the desktop window),
    made once per region."""
    from . import voorbeeld
    from .kaart import ScopedMapData, available, border_rings, land_layer
    population = _population()
    if not available(population):
        raise ValueError("Geen kaart: de populatie heeft geen coördinaten")
    key = (population, json.dumps(S.region, sort_keys=True), S.scope_text)   # holds the object
    if S.map_key != key or S.map_data is None:
        scope = merge_scope(S.region, S.scope_text, population)
        if not scope.is_everything():
            population = population.within(scope)
        S.map_data = ScopedMapData(population, voorbeeld.stations(), border_rings(), land_layer())
        S.map_key = key
    return S.map_data


_STATIC: dict = {}


def map_layers() -> dict:
    """Everything the map draws that does not change while you click, as [lon, lat] rings with
    4 decimals: the Dutch ``land`` (polygons of rings), the municipal ``borders``, the city
    ``cities`` [name, lon, lat], the ``stations`` (id, name, lon, lat), the Voronoi ``voronoi``
    areas [{id, ring}] in the order of the stations, the level-6 ``base`` cells that hold dwellings, and the ``bbox``
    (lon0, lat0, lon1, lat1) the desktop map starts from. Made once per region."""
    from .kaart import LAND, STATION_COLOURS, WATER
    md = _map_data()
    if S.layers is not None and S.layers[0] == S.map_key:
        return S.layers[1]
    if not _STATIC:
        _STATIC["land"] = [[_round_ring(r) for r in rings] for rings in md.land]
        _STATIC["borders"] = [_round_ring(r) for r in md.borders]
    st = md.stations
    stations = [] if st is None else [
        {"id": str(r.knmi_station), "name": str(getattr(r, "naam", "") or ""),
         "lon": round(float(r.lon), 4), "lat": round(float(r.lat), 4)}
        for r in st.itertuples(index=False)]
    out = {"land": _STATIC["land"], "borders": _STATIC["borders"],
           "cities": [[str(n), round(float(lo), 4), round(float(la), 4)]
                      for n, la, lo, _c in md.cities],
           "stations": stations,
           "voronoi": [{"id": str(k), "ring": _round_ring((lo, la) for la, lo in v)}
                       for k, v in md.voronoi.items()],
           "colours": {"water": WATER, "land": LAND, "stations": list(STATION_COLOURS)},
           "base": [_cell_ring(c) for c, _n, _s, _b in md.base],
           "bbox": [round(float(x), 4) for x in md.bbox]}
    S.layers = (S.map_key, _clean(out))
    return S.layers[1]


def _dataset_cells(level: int) -> dict:
    """The weather cells of the dataset at ``level``, with the number of records."""
    from .stappen import weather_zones
    return weather_zones(S.df, level)[0] or {}


def map_cells(level: int) -> dict:
    """The cells of ``level`` that hold dwellings of the dataset (as weather zone), with their
    number, as rings; and, for level 4 to 5, the population cells of that level as outlines
    (level 6 is the ``base`` of :func:`map_layers`). Call it again after adding the weather."""
    level = int(level)
    md = _map_data()
    return _clean({
        "level": level,
        "dataset": [{"cell": c, "n": n, "ring": _cell_ring(c)}
                    for c, n in _dataset_cells(level).items()],
        "population": [_cell_ring(c) for c in md.counts(level)] if level < 6 else []})


def map_hit(lat: float, lon: float, level: int) -> dict:
    """The H3 cell of ``level`` at a click on the map, with its ring and its ring-1 neighbours."""
    import h3
    cell = h3.latlng_to_cell(float(lat), float(lon), int(level))
    return {"cell": cell, "ring": _cell_ring(cell),
            "neighbours": [_cell_ring(c) for c in h3.grid_disk(cell, 1) if c != cell]}


def map_cell(cell: str, sigma: float = 10.0, p: float | None = None, progress=None) -> dict:
    """A clicked cell like the desktop's ``_cell_clicked``/``_show_cell``: the statistics of
    :meth:`kaart.MapData.cell_stats` (``stats``), the ring-1 ``neighbours``, the orange ``heat``
    cells with their weight, where to look (``focus``), and the side card (``card``, from
    :func:`stappen.cell_text`; values use ``**bold**`` and ``!!orange!!``). ``p`` is the norm
    when it is not locked yet. ``progress(fraction, text)`` hears how far the calculation is."""
    import h3

    from .stappen import cell_text
    md = _map_data()
    cell = str(cell)
    if not h3.is_valid_cell(cell):
        raise ValueError(f"geen H3-cel: {cell}")
    sig = float(sigma)
    stats = md.cell_stats(cell, sig, progress)
    level = stats["niveau"]
    zones, other = weather_zones(S.df, level)
    in_dataset = None if zones is None else zones.get(cell, 0)
    threshold = S.threshold if S.norm_locked or p is None else Threshold(round(float(p), 2))
    shown = int(sig) if sig.is_integer() else sig
    card = cell_text(stats, level, shown, threshold.k, land_share=md.land_share(cell),
                     in_dataset=in_dataset, other_levels=other)
    la, lo = h3.cell_to_latlng(cell)
    edge = h3.average_hexagon_edge_length(level, unit="km")
    heat = stats.get("heat", {})
    return _clean({
        "cell": cell, "level": level, "ring": _cell_ring(cell),
        "stats": {k: v for k, v in stats.items() if k != "heat"},
        "neighbours": [_cell_ring(c) for c in h3.grid_disk(cell, 1) if c != cell],
        "heat": [{"cell": c, "weight": w, "ring": _cell_ring(c)} for c, w in heat.items()],
        "focus": {"lat": la, "lon": lo, "km": max(8 * edge, 6 * sig)},
        "card": card})


def map_station(lat: float, lon: float) -> dict:
    """A click on the map in the station mode: the nearest KNMI station, for how many dwellings
    it is that, and how many of the dataset's (the desktop's text)."""
    md = _map_data()
    station, count = md.station_at(float(lat), float(lon))
    if station is None:
        return {"station": None}
    name = md.station_name(station)
    in_data = int((S.df[WEATHER_STATION] == station).sum()) \
        if S.df is not None and WEATHER_STATION in S.df.columns else None   # None: not added yet
    return _clean({"station": station, "name": name, "count": count, "in_dataset": in_data,
                   "title": f"KNMI-station {name}", "text": station_text(count, in_data)})


def _locations(source: str, link_cols, gps, progress=None):
    from .stappen import locations
    df = _need_df()
    gps = tuple(gps or ("", ""))
    link = link_cols if isinstance(link_cols, str) else ",".join(link_cols or [])
    key = (source, link, gps, S.name, len(df))
    if S.loc is None or S.loc[0] != key:
        S.loc = (key, locations(df, _population() if source != "gps" else None, source=source,
                                link_cols=link, gps=gps, progress=progress))
    return S.loc[1]


def _weather_sub(level=None, sigma=None) -> str:
    """The sub-line of step 5 in the rail (``_weather_sub`` of the desktop window)."""
    if S.df is None:
        return ""
    parts = []
    if WEATHER_H3 in S.df.columns:
        parts.append(f"H3 niveau {level if level is not None else 5}, "
                     f"σ {sigma if sigma is not None else 10} km")
    elif WEATHER_STATION in S.df.columns:
        parts.append("KNMI-station")
    if UHI in S.df.columns:
        parts.append("UHI")
    return " + ".join(parts) if parts else "niet toegevoegd"


def _added_now() -> dict:
    qid = {WEATHER_H3: "h3_cel", WEATHER_STATION: "knmi_station", UHI: "uhi"}
    return {c: q for c, q in qid.items() if S.df is not None and c in S.df.columns}


def _column_rows(added: dict, source_cols) -> dict:
    """The rows step 3 gets (``_add_column_rows``): old weather rows go, the new ones come
    (reason 'toegevoegd in stap 5'), and the GPS source columns are marked 'direct'."""
    for c in (WEATHER_H3, WEATHER_STATION, UHI):
        S.proposal.pop(c, None)
        S.mapping.pop(c, None)
    direct = [c for c in source_cols if c and c in S.mapping]
    for c in direct:
        S.mapping[c] = "direct"
    for c, q in added.items():
        S.proposal[c] = q
        S.mapping[c] = q
    return {"remove": [WEATHER_H3, WEATHER_STATION, UHI], "direct": direct,
            "rows": [{"column": c, "proposal": f"weerlocatie: {q}", "default": q,
                      "reason": "toegevoegd in stap 5"} for c, q in added.items()]}


def _dataset_changed() -> None:
    """The dataset got other columns: the last outcome no longer describes it."""
    S.current = S.df
    S.assessment = S.shown = S.steps = S.export_steps = S.scoped = None


def _weather_answer(loc, source, gps, level, sigma) -> dict:
    _dataset_changed()
    added = _added_now()
    rows = _column_rows(added, list(gps or ()) if source == "gps" else [])
    n = int(loc["lat"].notna().sum())
    return _clean({**rows, "added": added, "columns": list(S.df.columns),
                   "found": n, "records": len(S.df), "level": level, "sigma": sigma,
                   "status": f"Toegevoegd: {', '.join(added) or 'niets'} (locatie gevonden voor "
                             f"{n} van {len(S.df)} records). De bronkolommen worden weggelaten.",
                   "sub": _weather_sub(level, sigma)})


def _number(x):
    x = float(x)
    return int(x) if x.is_integer() else x


def weather(source: str = "koppel", link_cols=None, gps=None, method: str | None = None,
            level: int = 5, sigma: float = 10.0, count_noise: bool = True, progress=None) -> dict:
    """Add the weather location as published column, like the desktop's "Weerlocatie
    toevoegen". ``source`` is "koppel" (``link_cols``: the link columns of step 4, a list or a
    text with commas) or "gps" (``gps``: [latitude column, longitude column]); ``method`` is
    "h3" (H3 cell of ``level`` after noise of ``sigma`` km), "knmi" (nearest station) or None
    (only clears older weather columns). The noise is drawn once per session and reused. Also
    stores the tolerance the assessment allows for. ``progress(fraction, text)`` hears how far
    it is."""
    from .stappen import add_weather
    df = _need_df()
    method = method if method in ("h3", "knmi") else None
    level, sigma = int(level), _number(sigma)
    link = link_cols if isinstance(link_cols, str) else ",".join(link_cols or [])
    from .voortgang import monotoon
    progress = monotoon(progress)
    if progress:
        progress(0.0, "weerlocatie bepalen")
    loc = _locations(source, link, gps, progress)
    if method == "h3" and S.seed is None:
        S.seed = secrets.randbits(32)
    out, _added, tolerance = add_weather(
        df, _population() if method == "knmi" else None, method=method, level=level,
        sigma=float(sigma), seed=S.seed or 0, count_noise=bool(count_noise), locations=loc,
        source=source, link_cols=link, progress=progress)
    if tolerance is not None:
        S.tolerance = tolerance
    S.df = out
    return _weather_answer(loc, source, gps, level, sigma)


def _read_uhi_file(path: str) -> pd.DataFrame:
    """The UHI file the page wrote into the worker's file system, read and removed."""
    from .stappen import read_uhi_frame
    try:
        return read_uhi_frame(path)
    finally:
        Path(path).unlink(missing_ok=True)


def uhi_bron() -> str:
    """Where the UHI comes from when no file is chosen (for the Hitte-eiland tab)."""
    from .stappen import UHI_FROM_POPULATION
    pop = _population()
    if "uhi" in pop.columns and "postcode6" in pop.columns:
        return "Bron: " + UHI_FROM_POPULATION + ". Een eigen bestand is optioneel."
    return "De populatie heeft geen UHI: kies een eigen bestand (per postcode: pc6 en uhi)."


def uhi(name: str | None, path: str | None, class_width: float = 0.5, source: str = "koppel", link_cols=None,
        gps=None, level: int = 5, sigma: float = 10.0, progress=None) -> dict:
    """Add the urban heat island as column ``uhi`` (classes of ``class_width`` °C) from a csv or
    parquet with ``pc6`` and ``uhi``, per record through its postcode. Call it after
    :func:`weather`: that one removes older weather and UHI columns. From then on the population
    of ``run``, ``suggest`` and ``export`` has the UHI too."""
    from .stappen import add_uhi, uhi_from_population, uhi_table
    df = _need_df()
    from .voortgang import Voortgang
    vg = Voortgang(None, progress)
    own = bool(path)
    if own:
        vg.set(0.0, "UHI-bestand lezen")
        frame = _read_uhi_file(path)
    else:
        vg.set(0.0, "UHI uit de populatie")
        frame = uhi_from_population(_population())
        if frame is None:
            raise ValueError("de populatie heeft geen UHI: kies een UHI-bestand "
                             "(per postcode: pc6 en uhi)")
    table = uhi_table(frame)
    link = link_cols if isinstance(link_cols, str) else ",".join(link_cols or [])
    loc = _locations(source, link, gps, vg.stage(0.2, 0.9).callback() if progress else None)
    vg.set(0.9, "UHI per woning bepalen")
    S.df = add_uhi(df, loc, table, float(class_width))
    vg.set(1.0)
    # a UHI from the population needs no join later: the population has the column itself
    S.uhi_frame, S.uhi_pop = (frame if own else None), None
    return _weather_answer(loc, source, gps, int(level), _number(sigma))


def weather_sub(level: int = 5, sigma: float = 10.0) -> str:
    return _weather_sub(int(level), _number(sigma))


# "Weer al in de data?": the weather trace
def _auto(value):
    return None if value in (None, "", "(automatisch)") else str(value)


def _series_path(path):
    from . import voorbeeld
    return str(voorbeeld.WEER) if not path else str(path)


def trace_open(path: str | None = None, name: str | None = None, pattern: str = "*") -> dict:
    """The file (or zip) with weather series, looked at like the desktop's ``_series_chosen``:
    how many files, where the dwelling ID comes from, the columns and the guessed ID, time and
    value column, and the column of the dataset that carries the same ID. Without ``path``
    (the practice mode) the example's series."""
    from . import voorbeeld
    from .weerspoor import ID_HINT, TIME_HINT, VALUE_HINT, _header, guess_column, members
    df = _need_df()
    example = not path
    src = _series_path(path)
    files = members(src, pattern or "*")
    cols: list = []
    if files:
        fname, opener = files[0]
        with opener() as h:
            cols = _header(h, fname)
    guess = {k: guess_column(cols, hint) or "" for k, hint in
             (("id_col", ID_HINT), ("time_col", TIME_HINT), ("value_col", VALUE_HINT))}
    key = voorbeeld.KEY if example and voorbeeld.KEY in df.columns else next(
        (c for c in df.columns if guess["id_col"] and c == guess["id_col"]), "")
    return _clean({"name": name or Path(src).name, "example": example, "files": len(files),
                   "id_from": "bestand" if len(files) > 1 else "kolom", "columns": cols,
                   **guess, "key": key, "key_columns": list(df.columns),
                   "pattern": pattern or "*", "max_homes": 300})


ZONEINFO = Path(__file__).with_name("data") / "zoneinfo"


def alleen_amsterdam() -> None:
    """Let zoneinfo find Europe/Amsterdam in the copy that ships with anonymate.

    The weather trace converts KNMI hours to Dutch local time. Pyodide has no system time zone
    database, and the package tzdata would add every zone of the world; this is the only one
    anonymate needs. Other zones then raise ZoneInfoNotFoundError, unless tzdata is installed
    (as it is on the desktop, where this is not called)."""
    import zoneinfo
    if str(ZONEINFO) not in zoneinfo.TZPATH:
        zoneinfo.reset_tzpath([str(ZONEINFO), *zoneinfo.TZPATH])


def trace(name: str | None = None, path: str | None = None, options: dict | None = None,
          progress=None) -> dict:
    """Trace the weather series back to a station or cell, like the desktop's ``run_trace``:
    ``options`` are id_from (kolom, bestand, map), id_col, time_col, value_col, pattern,
    max_homes and key (the dataset column with the dwelling ID). Practice mode uses the KNMI
    hours and cells of the example. Returns the conclusion, the advice, the findings (at most 8
    shown) and a count per regime; :func:`trace_apply` puts it into the dataset."""
    from . import voorbeeld
    from .weerspoor import investigate, read_series_source
    alleen_amsterdam()
    df = _need_df()
    o = dict(options or {})
    key = o.get("key") or ""
    if key not in df.columns:
        raise ValueError("kies de kolom van de dataset met de woning-ID die ook in de "
                         "weerreeksen staat")
    if not S.practice:
        raise ValueError("Het weerspoor werkt in de webversie alleen in de oefenmodus: de "
                         "KNMI-uurgegevens en de echte populatie volgen in een latere versie.")
    if progress:
        progress(0.0, "weerreeksen lezen")
    series = read_series_source(
        _series_path(path), id_from=o.get("id_from") or "kolom", id_col=_auto(o.get("id_col")),
        time_col=_auto(o.get("time_col")), value_col=_auto(o.get("value_col")),
        pattern=o.get("pattern") or "*", max_homes=int(o.get("max_homes") or 300))
    if progress:
        progress(0.2, "het weer van de KNMI-stations en cellen naast de reeksen leggen")
    from .voortgang import Voortgang
    found = investigate(series, voorbeeld.hourly(), voorbeeld.grid(), id_col="woning",
                        time_col="tijd", value_col="waarde",
                        progress=Voortgang(None, progress, lo=0.2).callback() if progress
                        else None)
    S.trace_found, S.trace_key = found, key
    notes = list(found.findings or [])
    counts = found.per_home["regime"].value_counts().to_dict()
    return _clean({"verdict": found.verdict, "advice": found.advice, "findings": notes[:8],
                   "more": max(len(notes) - 8, 0), "homes": len(found.per_home),
                   "regimes": counts, "key": key})


def trace_apply(level: int = 5, sigma: float = 10.0) -> dict:
    """Put the traced weather back into the dataset (``_show_trace``): ``weer_knmi_station``
    and/or ``weerzone_h3`` per dwelling through the key column, the tolerance from
    ``onzekerheid_km``, and what the side card says ('Wat het weer verraadt')."""
    from .stappen import apply_trace
    df = _need_df()
    if S.trace_found is None:
        raise ValueError("zoek eerst het weerspoor")
    out, tolerance, summary = apply_trace(df, S.trace_key, S.trace_found, lambda: _population())
    S.df, S.tolerance, S.loc = out, tolerance, None
    _dataset_changed()
    added = _added_now()
    rows = _column_rows(added, [])
    notes = summary.get("notes", [])
    return _clean({**rows, "added": added, "columns": list(out.columns),
                   "status": summary["status"], "tolerance": tolerance,
                   "verdict": summary.get("verdict"), "advice": summary.get("advice"),
                   "findings": notes[:8], "more": max(len(notes) - 8, 0),
                   "sub": _weather_sub(int(level), _number(sigma))})
