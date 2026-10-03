"""Reading the EP-online totaalbestand: the registered energy labels of residential buildings,
one compact row per label, keyed by BAG verblijfsobject id.

Kept apart from :mod:`anonymate.store` and free of pyarrow, so the web version (Pyodide, which
has no pyarrow) reads a totaalbestand the user dragged in with exactly the same code as the
desktop does when it ingests one.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from .qids import normalise_dwelling_type, normalise_label

# the columns of every frame (and of ``raw/ep_online.parquet``)
EP_COLUMNS = ["vbo_id", "energielabel", "woningtype", "energie_index", "compactheid",
              "label_oppervlakte", "label_bouwjaar", "registratiedatum", "warmtebehoefte",
              "nta8800"]


def _norm_header(h: str) -> str:
    t = re.sub(r"[^a-z0-9]", "", h.lower())
    return t.removeprefix("pand")


_EP_FIELDS = {
    "vbo_id": ["bagverblijfsobjectid"],
    "postcode": ["postcode"],
    "huisnummer": ["huisnummer"],
    "huisletter": ["huisletter"],
    "toevoeging": ["huisnummertoevoeging"],
    "energieklasse": ["energieklasse"],
    "gebouwklasse": ["gebouwklasse"],
    "gebouwtype": ["gebouwtype"],
    "gebouwsubtype": ["gebouwsubtype"],
    "registratiedatum": ["registratiedatum"],
    "opnamedatum": ["opnamedatum"],
    "energie_index": ["energieindex"],
    "compactheid": ["compactheid"],
    "label_oppervlakte": ["gebruiksoppervlaktethermischezone"],
    "label_bouwjaar": ["bouwjaar"],
    "warmtebehoefte": ["warmtebehoefte"],
    "berekeningstype": ["berekeningstype"],
}


def iter_eponline_csv(stream: io.TextIOBase, chunk: int = 200_000,
                      meta_out: dict | None = None):
    """Yield compact DataFrames (columns :data:`EP_COLUMNS`) from an EP-online totaalbestand CSV.

    Tolerant to column naming (``Pand_energieklasse`` / ``Energieklasse``) and delimiter; reads
    in chunks so memory stays small however large the file is. Only residential labels
    (gebouwklasse W) with a BAG verblijfsobject id are kept: that id is the lookup key.
    """
    # the totaalbestand starts with "key;value" preamble lines (PublicatieDatum, ...) before the
    # column header; collect those as metadata
    meta = {}
    head = stream.readline()
    for _ in range(20):
        if "energieklasse" in re.sub(r"[^a-z]", "", head.lower()):
            break
        k, _, v = head.strip().partition(";")
        if k:
            meta[k] = v
        head = stream.readline()
    delim = max(";,\t|", key=head.count)
    headers = next(csv.reader([head], delimiter=delim))
    norm = [_norm_header(h) for h in headers]
    if meta_out is not None:
        meta_out.update(meta)
    pick = {}
    for field, candidates in _EP_FIELDS.items():
        for c in candidates:
            if c in norm:
                pick[field] = norm.index(c)
                break
    if "energieklasse" not in pick or "vbo_id" not in pick:
        raise ValueError(f"onbekend EP-online-formaat; kolommen: {headers[:30]}")
    labels: dict = {}
    types: dict = {}

    def label(v):
        if v not in labels:
            labels[v] = normalise_label(v) if v else None
        return labels[v]

    def dtype(v):
        if v not in types:
            types[v] = normalise_dwelling_type(v) if v.strip() else None
        return types[v]

    def frame(rows):
        df = pd.DataFrame(rows, columns=list(pick)).replace("", None)
        if "gebouwklasse" in df:
            df = df[df["gebouwklasse"].isna() | df["gebouwklasse"].str.upper().str.startswith("W")]
        df = df[df["vbo_id"].notna()]
        out = pd.DataFrame({"vbo_id": df["vbo_id"].str.strip().str.zfill(16)})
        out["energielabel"] = df["energieklasse"].map(label)
        if "gebouwtype" in df:
            sub = df["gebouwsubtype"].fillna("") if "gebouwsubtype" in df else ""
            out["woningtype"] = (df["gebouwtype"].fillna("") + " " + sub).map(dtype)
        for c in ("energie_index", "compactheid", "label_oppervlakte", "warmtebehoefte"):
            out[c] = pd.to_numeric(df[c].str.replace(",", "."), errors="coerce") \
                if c in df else np.nan
        out["label_bouwjaar"] = pd.to_numeric(df["label_bouwjaar"], errors="coerce") \
            .astype("Int64") if "label_bouwjaar" in df else pd.NA
        out["registratiedatum"] = _dates(df["registratiedatum"]) \
            if "registratiedatum" in df else pd.NaT
        out["nta8800"] = df["berekeningstype"].str.contains("NTA 8800", na=False) \
            if "berekeningstype" in df else False
        return out.reindex(columns=EP_COLUMNS)

    rows = []
    for rec in csv.reader(stream, delimiter=delim):
        if not rec:
            continue
        rows.append([rec[i].strip() if i < len(rec) else "" for i in pick.values()])
        if len(rows) >= chunk:
            yield frame(rows)
            rows = []
    if rows:
        yield frame(rows)


def _dates(s: pd.Series) -> pd.Series:
    """EP-online dates are ``YYYYMMDD`` in the totaalbestand, ISO elsewhere."""
    compact = pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    return compact.fillna(pd.to_datetime(s.where(compact.isna()), errors="coerce"))


def read_eponline_csv(stream: io.TextIOBase) -> pd.DataFrame:
    """The whole file as one compact DataFrame (small files and tests)."""
    parts = list(iter_eponline_csv(stream))
    return pd.concat(parts, ignore_index=True) if parts else \
        pd.DataFrame(columns=EP_COLUMNS)


class _Telwrapper(io.RawIOBase):
    """A binary stream that counts the bytes read from it, for the fraction of a long read."""

    def __init__(self, raw, on_read):
        self._raw, self._on_read, self._n = raw, on_read, 0

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        n = self._raw.readinto(b)
        self._n += n or 0
        self._on_read(self._n)
        return n

    def close(self) -> None:
        self._raw.close()
        super().close()


def iter_eponline_file(file: str | Path, *, chunk: int = 200_000,
                       fraction: Callable[[float], None] | None = None,
                       meta_out: dict | None = None):
    """:func:`iter_eponline_csv` over a totaalbestand as EP-online delivers it (a zip with one
    CSV) or the CSV itself. ``fraction(x)`` hears the share of the uncompressed bytes read."""
    file = Path(file)
    if re.match(r"d\d{8}", file.name, re.IGNORECASE):
        raise ValueError(f"{file.name} is een mutatiebestand van EP-online, met alleen de "
                         "wijzigingen van één dag. Kies het totaalbestand: v…_csv.zip.")

    def frames(raw, size):
        seen = [0]
        counted = io.BufferedReader(_Telwrapper(raw, lambda b: seen.__setitem__(0, b)))
        stream = io.TextIOWrapper(counted, encoding="utf-8-sig", errors="replace")
        for df in iter_eponline_csv(stream, chunk=chunk, meta_out=meta_out):
            yield df
            if fraction is not None and size:
                fraction(min(seen[0] / size, 1.0))

    if file.suffix.lower() == ".zip":
        with zipfile.ZipFile(file) as z:
            csvs = [x for x in z.infolist() if x.filename.lower().endswith(".csv")]
            if not csvs:
                raise ValueError(f"{file.name}: geen CSV-bestand in de zip. Kies het "
                                 "totaalbestand in CSV (v…_csv.zip), niet de xml- of "
                                 "xlsx-versie.")
            with z.open(csvs[0]) as raw:
                yield from frames(raw, csvs[0].file_size)
    else:
        with open(file, "rb") as raw:
            yield from frames(raw, file.stat().st_size)
