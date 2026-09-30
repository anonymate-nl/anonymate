"""Reading Parquet into pandas without pyarrow.

DuckDB reads Parquet itself and hands over a pandas table, so the browser version (docs/werk/
webversie.md) does not have to load pyarrow (10 MB and several seconds of start-up). Qt-free and
pyarrow-free on purpose: everything on the web path reads its Parquet through here.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def _quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def lees_parquet(path: str | Path, columns: list[str] | None = None) -> pd.DataFrame:
    """The Parquet file at ``path`` as a DataFrame, optionally only ``columns``.

    Text columns come back with the default string dtype, as ``pd.read_parquet`` gives them."""
    select = ", ".join('"' + c.replace('"', '""') + '"' for c in columns) if columns else "*"
    con = duckdb.connect()
    try:
        df = con.execute(f"SELECT {select} FROM read_parquet({_quote(str(path))})").df()
    finally:
        con.close()
    for c in df.columns:
        if df[c].dtype == object and df[c].map(lambda v: isinstance(v, str) or v is None).all():
            df[c] = df[c].astype("str")
    return df
