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
import math
import re
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
from .stappen import (STATUS_TEXT, guess_gps, houses_for, k_histogram, link_columns, merge_scope,
                      nl, numeric_columns, readable_error, record_card, region_scope,
                      region_text, representativeness_lines)

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


def _g(x) -> str:
    return "–" if x is None else f"{x:.3g}"


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


def open_practice(population_path: str | None = None) -> dict:
    """Open the example dataset against the made-up Netherlands, read from
    ``population_path`` when given, else made up in memory."""
    from . import voorbeeld
    S.practice = True
    practice_population(population_path)
    return _open(read_dataset(voorbeeld.WONINGEN), voorbeeld.WONINGEN.name)


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
    return {"practice": False}


def _open(df: pd.DataFrame, name: str) -> dict:
    """Start a session on ``df``: the H3 columns derived, and every column preselected exactly
    as the desktop window does (``MainWindow.load``)."""
    df, derived = derive_h3_columns(df)
    S.df, S.current, S.name = df, df, name
    S.assessment = S.shown = S.steps = S.export_steps = S.scoped = None
    S.norm_locked = False           # a new dataset: fix the norm again before assessing
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
    sc = merge_scope(S.region, S.scope_text, S.population)
    S.scoped = S.population if sc.is_everything() else S.population.within(sc)
    return S.qids, S.direct, S.scoped


def _bits(df, a, population):
    """(bits needed, per attribute, remaining bits per record), or None when it fails."""
    try:
        return information_bits(df, a, population)
    except Exception:  # noqa: BLE001 (the picture is optional; the assessment stands)
        return None


def _cell(v, j: int, status_col: int, k_col: int) -> str:
    """One table cell as the desktop window writes it."""
    text = "" if v is None or v is pd.NA or (isinstance(v, float) and pd.isna(v)) else (
        f"{v:.3g}" if isinstance(v, float) else str(v))
    if j == status_col:
        return STATUS_TEXT.get(v, text)
    if j == k_col and text:
        return f"{int(v):,}".replace(",", ".")
    return text


def _show(df: pd.DataFrame, a: Assessment, title_suffix: str = "") -> dict:
    """Keep ``a`` as the outcome and describe it: what the desktop's ``_show_assessment``
    shows (the cards, the bits, the histogram, the table and the Toelichting)."""
    S.current, S.assessment = df, a
    s = a.summary()
    n = s["records"] or 1
    n_out = s["records"] - s["ok"]
    text = [f"{s['ok']} van {s['records']} records publiceerbaar ({100 * s['ok'] / n:.0f}%), "
            f"{s['risico']} met risico, {s['geen_match']} zonder match in de populatie.",
            f"k minimaal {_g(s['k_min'])}, mediaan {_g(s['k_mediaan'])}; "
            f"δ maximaal {_g(s['delta_max'])}.",
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
    stats = {"ok": f"{s['ok']} · {100 * s['ok'] / n:.0f}%", "risk": str(n_out),
             "k": _g(s["k_mediaan"]), "bits": "–"}
    bits_out = None
    if bits is not None:
        needed, parts, remaining = bits
        median = float(remaining.median()) if len(remaining) else 0.0
        stats["bits"] = f"{nl(median)} bits"
        population = f"{s['populatie']:,}".replace(",", ".")
        bits_out = {"needed": needed, "remaining_median": median, "norm_bits": math.log2(norm_k),
                    "parts": [{"column": b.column, "median": b.median, "estimated": b.estimated}
                              for b in parts],
                    "note": f"{nl(needed)} bits wijzen één woning aan uit {population} woningen; "
                            "per kenmerk de mediaan over de woningen, en wat er daarna nog te "
                            "raden valt."}

    shown = df[[q.column for q in a.qids]].join(a.records[["k", "delta", "status", "redenen"]])
    S.shown = shown
    cols = list(shown.columns)
    status_col, k_col = cols.index("status"), cols.index("k")
    rows = [[_cell(v, j, status_col, k_col) for j, v in enumerate(row)]
            for row in shown.itertuples(index=False)]
    statuses = list(shown["status"])
    risky = [i for i, st in enumerate(statuses) if st != Status.OK]
    return _clean({
        "title": f"{s['ok']} van de {s['records']} woningen publiceerbaar{title_suffix}",
        "summary": s, "warnings": a.warnings, "direct": S.direct, "mapping": S.mapping,
        "threshold": {"p": S.threshold.p, "k": S.threshold.k, "bits": math.log2(norm_k)},
        "stats": stats, "bits": bits_out,
        "histogram": [{"lo": lo, "hi": hi, "n": c}
                      for lo, hi, c in k_histogram(list(a.records["k"]), norm_k)],
        "table": {"columns": cols, "rows": rows, "status": statuses,
                  "selected": (risky[0] if risky else 0) if rows else None},
        "toelichting": text,
    })


def run(mapping: dict | None = None, scenario: str | None = None, scope: str | None = None
        ) -> dict:
    """Assess the open dataset, like the desktop's "Toetsen". ``mapping`` is complete (a
    catalogue key, 'direct' or 'geen' per column; None: the preselected one), ``scenario`` the
    attacker, ``scope`` the free-text population scope (combined with the region of step 1).
    The norm must have been locked."""
    _inputs(mapping, scenario, scope)
    S.steps = S.export_steps = None
    a = assess(S.df, S.qids, S.scoped, S.threshold, SCENARIOS[S.scenario])
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


def suggest(mapping: dict | None = None, scenario: str | None = None, scope: str | None = None,
            target_share: float = 0.95, progress=None) -> dict:
    """Search generalisations that let more records pass, and assess the last step, like the
    desktop's "Generalisaties zoeken". Nothing is applied to the dataset yet.
    ``progress(fraction, text)`` hears how far the search is."""
    from .generalize import suggest as search
    _inputs(mapping, scenario, scope)
    steps = search(S.df, S.qids, S.scoped, S.threshold, SCENARIOS[S.scenario],
                   target_share=target_share, progress=progress)
    last = steps[-1]
    a = assess(last.df, last.qids, S.scoped, S.threshold, SCENARIOS[S.scenario])
    S.steps = S.export_steps = steps
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
                    steps=S.export_steps, dataset_name=S.name, population=S.scoped)
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
