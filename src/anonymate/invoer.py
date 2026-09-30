"""What both the command line and the web facade need to start an assessment: reading a
dataset, the scenarios, the scope and the QIDs of a run. Kept apart from ``cli`` so the browser
version (docs/werk/webversie.md) does not import the whole command line (signature, report,
generalisation) just to open a file; ``cli`` re-exports the names.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import namen
from .constraints import OneOf, Range, parse_categorical, parse_numeric
from .detect import Role, detect
from .population import Population, Scope
from .qids import CATALOGUE, Kind, Knowledge
from .risk import QidColumn
from .tabel import lees_parquet

SCENARIOS = {"register": Knowledge.REGISTER, "zichtbaar": Knowledge.OBSERVABLE,
             "observable": Knowledge.OBSERVABLE, "insider": Knowledge.INSIDER}


def read_dataset(path: str | Path, sheet: str | None = None) -> pd.DataFrame:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(p, sheet_name=sheet or 0, dtype=object)
    if suffix == ".parquet":
        return lees_parquet(p)
    with open(p, encoding="utf-8-sig", errors="replace") as f:
        head = f.readline()
    sep = max(";,\t|", key=head.count)
    return pd.read_csv(p, sep=sep, dtype=str, keep_default_na=False, na_values=[""],
                       encoding="utf-8-sig")


def scope_column(name: str, population: Population | None) -> str:
    """The population column a scope key means: the column itself (``bouwjaar__yr``), the
    catalogue key (``bouwjaar``) or the plain name of a column (``eengezins``, ``hoogte``)."""
    if population is not None and name in population.columns:
        return name
    spec = CATALOGUE.get(name)
    if spec is not None and spec.population_column:
        return spec.population_column
    return namen.OUD_NAAR_NIEUW.get(name, name)


def parse_scope(items: dict | None, population: Population) -> Scope:
    """``{"gemeente": ["Zwolle"], "bouwjaar": "1900-1989", "eengezins": true}`` -> Scope; a key
    is a catalogue key, a plain column name or a population column (``bouwjaar__yr``).

    A key ending in ``!`` (from ``kolom!=waarde``) is an exclusion: ``{"woningtype!":
    "appartement"}`` keeps every dwelling that is *not* an apartment."""
    if not items:
        return Scope()
    crit = {}
    excl = {}
    for col, val in items.items():
        target = crit
        if col.endswith("!"):
            col, target = col[:-1], excl
        spec = CATALOGUE.get(col) or CATALOGUE.get(namen.zonder_eenheid(col))
        col = scope_column(col, population)
        spec = spec or next((x for x in CATALOGUE.values() if x.population_column == col), None)
        if isinstance(val, bool):
            target[col] = OneOf.of(str(val).lower())
        elif spec is not None and spec.kind == Kind.NUMERIC:
            target[col] = parse_numeric(val, integer=spec.integer)
        elif isinstance(val, (int, float)):
            target[col] = Range(float(val), float(val))
        elif isinstance(val, list):
            target[col] = OneOf(frozenset(str(v) for v in val))
        else:
            c = parse_numeric_or_none(val)
            target[col] = c if c is not None else parse_categorical(val)
    desc = ", ".join(f"{k[:-1]}≠{v}" if k.endswith("!") else f"{k}={v}"
                     for k, v in items.items())
    return Scope(crit, desc, excl)


def parse_numeric_or_none(v):
    try:
        c = parse_numeric(v)
        return c if c is not None and (c.lo != c.hi or c.lo is None) else None
    except ValueError:
        return None


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


def _scope_from_args(pairs: list[str]) -> dict:
    """``gemeente=Zwolle,Deventer`` / ``bouwjaar=1900-1989`` / ``eengezins=true``."""
    out: dict = {}
    for p in pairs or []:
        k, _, v = p.partition("=")  # "kolom!=waarde" gives key "kolom!": an exclusion
        if v.lower() in ("true", "false", "ja", "nee"):
            out[k] = v.lower() in ("true", "ja")
        elif "," in v:
            out[k] = [x.strip() for x in v.split(",")]
        else:
            out[k] = v
    return out
