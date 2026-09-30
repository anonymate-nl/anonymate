"""The facade for the web version (docs/werk/webversie.md): plain dicts in, plain dicts out.

The browser runs this module in Pyodide, inside a Web Worker; the page only exchanges JSON with
it. Everything here calls the same functions as the command line and the desktop window, and
none of it touches the network: a dataset arrives as bytes and results leave as bytes, which
the page offers as a download.

One session per worker: the dataset, the population and the last assessment stay in memory
between calls, so a step never has to send the data back and forth.
"""
from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .detect import Role, detect
from .invoer import SCENARIOS, parse_scope, qids_from, read_dataset
from .population import Population, Snapshot
from .qids import CATALOGUE
from .risk import P_DEFAULT, Assessment, Status, Threshold, assess

ROLE_TEXT = {Role.DIRECT: "direct", Role.QID: "qid", Role.IMPLICIT_LOCATION: "locatie",
             Role.DERIVED: "afgeleid", Role.MEASUREMENT: "meting"}


@dataclass
class Session:
    df: pd.DataFrame | None = None
    name: str = ""
    practice: bool = False
    population: Population | None = None
    mapping: dict[str, str] = field(default_factory=dict)
    qids: list = field(default_factory=list)
    direct: list[str] = field(default_factory=list)
    threshold: Threshold = field(default_factory=Threshold)
    scenario: str = "register"
    assessment: Assessment | None = None
    steps: list | None = None


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
        df = read_dataset(p)
    finally:
        p.unlink(missing_ok=True)
    S.practice = True          # until the web version has the real population (fase 3)
    practice_population()
    return _open(df, name)


def _open(df: pd.DataFrame, name: str) -> dict:
    S.df, S.name, S.mapping, S.assessment, S.steps = df, name, {}, None, None
    found = detect(df)
    return _clean({
        "name": name, "records": len(df), "columns": list(df.columns),
        "population": S.population.size() if S.population is not None else None,
        "practice": S.practice,
        "detections": [{"column": d.column, "role": ROLE_TEXT[d.role], "qid": d.qid,
                        "reason": d.reason} for d in found],
        "catalogue": {k: v.label_nl for k, v in CATALOGUE.items()},
    })


def run(mapping: dict | None = None, p: float = P_DEFAULT, scenario: str = "register",
        scope: dict | None = None) -> dict:
    """Assess the open dataset. ``mapping`` overrides detection per column: a catalogue key,
    'direct' (leave out) or 'geen' (not a QID)."""
    if S.df is None:
        raise ValueError("open eerst een dataset")
    S.mapping = dict(mapping or {})
    S.qids, S.direct = qids_from(S.df, S.mapping, auto=True)
    S.threshold, S.scenario = Threshold(float(p)), scenario
    population = S.population
    sc = parse_scope(scope or {}, population)
    if not sc.is_everything():
        population = population.within(sc)
    S.assessment = assess(S.df, S.qids, population, S.threshold, SCENARIOS[scenario])
    S.steps = None
    return _result(population)


def _result(population: Population) -> dict:
    from . import explain
    a = S.assessment
    summary = a.summary()
    needed, bits, remaining = explain.information_bits(S.df, a, population)
    shown = [q.column for q in a.qids]
    records = S.df[shown].astype(object).where(S.df[shown].notna(), None)
    records = records.join(a.records[["k", "status"]])
    return _clean({
        "summary": summary, "warnings": a.warnings, "direct": S.direct,
        "threshold": {"p": S.threshold.p, "k": S.threshold.k,
                      "bits": math.log2(S.threshold.k)},
        "bits": {"needed": needed, "per_column": [
            {"column": b.column, "median": b.median, "max": b.maximum, "estimated": b.estimated}
            for b in bits],
            "remaining_median": float(remaining.median()) if len(remaining) else None},
        "columns": shown + ["k", "status"],
        "rows": records.to_dict("records"),
    })


def suggest(target_share: float = 0.95, progress=None) -> dict:
    """Search generalisations that let more records pass; nothing is applied yet.
    ``progress(fraction, text)`` hears how far the search is."""
    from .generalize import suggest as search
    if S.assessment is None:
        raise ValueError("toets eerst")
    S.steps = search(S.df, S.qids, S.population, S.threshold, SCENARIOS[S.scenario],
                     target_share=target_share, progress=progress)
    return _clean({"steps": [s.row() for s in S.steps]})


def apply(step: int) -> dict:
    """Take the suggested steps up to and including ``step`` and assess again."""
    if not S.steps:
        raise ValueError("zoek eerst generalisaties")
    chosen = S.steps[step]
    S.df, S.qids = chosen.df, chosen.qids
    S.steps = S.steps[:step + 1]
    S.assessment = assess(S.df, S.qids, S.population, S.threshold, SCENARIOS[S.scenario])
    return _result(S.population)


def export() -> bytes:
    """A zip with publiceerbaar.csv, rapport.md, samenvatting.json and rapport_per_record.csv
    (internal), written by the same code as the command line, in memory."""
    import tempfile
    from .report import write
    if S.assessment is None:
        raise ValueError("toets eerst")
    with tempfile.TemporaryDirectory() as tmp:
        out = write(Path(tmp) / "uit", S.df, S.assessment, drop_columns=S.direct,
                    steps=S.steps, dataset_name=S.name, population=S.population)
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
