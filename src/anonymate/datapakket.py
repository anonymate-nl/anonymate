"""Data packages of the population for publication (kladbloknotitie 13).

A package holds, per dwelling (key: BAG ``vbo_id``), only what comes from BAG, 3D-BAG, CBS and
KNMI, and the heat signature computed from those alone. Nothing from EP-online goes in: not the
label, not the label data, and no signature that uses them. The population itself may be built
with EP-online (the monthly run does); this module leaves those columns out, and computes the
published signatures again with the dwelling type taken from the shape of the building, not from
the label.

Why: the EP-online terms of use do not allow passing the data on "directly at an individual
level in large numbers"; whether signatures derived from them count as "indirect" is a question
for RVO. Until RVO has answered, only the EP-free package is made.

Every column in ``manifest.json`` names its source, so it can be shown which parts are EP-free.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# column -> source; only these go into the package
WONINGEN = {
    "vbo_id": "BAG", "postcode6": "BAG", "huisnummer": "BAG", "huisletter": "BAG",
    "toevoeging": "BAG", "woonplaats": "BAG", "gemeente": "CBS (gebiedsindelingen)",
    "provincie": "CBS (gebiedsindelingen)", "bouwjaar": "BAG", "oppervlakte": "BAG",
    "pand_woningen": "BAG", "lat": "BAG (rd_x, rd_y, afgerond op 5 decimalen)",
    "lon": "BAG (rd_x, rd_y, afgerond op 5 decimalen)",
}
VORM = {
    "daktype": "3D-BAG", "bouwlagen": "3D-BAG", "hoogte": "3D-BAG", "aaneengebouwd": "3D-BAG",
    "opp_grond": "3D-BAG", "opp_dak_plat": "3D-BAG", "opp_dak_schuin": "3D-BAG",
    "opp_buitenmuur": "3D-BAG", "opp_scheidingsmuur": "3D-BAG",
}
# signatures computed without any label data (see anonymate.signature)
METHODS = ("nta8800", "mwa")
OUTPUTS = ("H", "C", "tau", "Asol")
EP_COLUMNS = {"energielabel", "energie_index", "compactheid", "label_oppervlakte",
              "warmtebehoefte", "nta8800"}


def _three_digits(x: np.ndarray) -> np.ndarray:
    """Round to 3 significant digits: the model error is far larger, and it compresses well."""
    x = np.asarray(x, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        mag = np.where(np.isfinite(x) & (x != 0), np.floor(np.log10(np.abs(x))), 0)
    factor = 10.0 ** (2 - mag)
    return np.round(x * factor) / factor


def signatures_without_labels(df: pd.DataFrame) -> pd.DataFrame:
    """nta8800 and mwa signatures, with the dwelling type from the building's shape only."""
    from .signature import compute
    inputs = df.copy()
    # the label's dwelling type stays out; flats (more dwellings in the building) come from BAG
    inputs["woningtype"] = np.where(pd.to_numeric(inputs.get("pand_woningen"),
                                                  errors="coerce") > 1, "appartement", None)
    for c in EP_COLUMNS | {"energielabel"}:
        inputs[c] = None
    out = pd.DataFrame(index=df.index)
    for method in METHODS:
        sig = compute(inputs, method)
        for o in OUTPUTS:
            out[f"sig_{method}_{o}"] = _three_digits(sig[o].to_numpy()).astype("float32")
    return out


def make(population_parquet: str | Path, out_dir: str | Path, *, sources: dict | None = None,
         batch_rows: int = 250_000, progress=lambda m: None) -> Path:
    """Write ``woningen.parquet``, ``warmtesignatuur.parquet`` and ``manifest.json``."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    reader = pq.ParquetFile(population_parquet)
    have = set(reader.schema_arrow.names)
    need = [c for c in list(WONINGEN) + list(VORM) if c in have] \
        + [c for c in ("woningtype",) if c in have]
    writers: dict[str, pq.ParquetWriter] = {}
    n = 0
    try:
        for batch in reader.iter_batches(batch_size=batch_rows, columns=need):
            df = batch.to_pandas()
            for c in ("lat", "lon"):
                if c in df:
                    df[c] = df[c].round(5)
            woningen = df[[c for c in WONINGEN if c in df]]
            sig = signatures_without_labels(df)
            vorm = pd.concat([df[["vbo_id"]], df[[c for c in VORM if c in df]], sig], axis=1)
            for name, part in (("woningen", woningen), ("warmtesignatuur", vorm)):
                table = pa.Table.from_pandas(part, preserve_index=False)
                if name not in writers:
                    writers[name] = pq.ParquetWriter(out / f"{name}.parquet", table.schema,
                                                     compression="zstd")
                writers[name].write_table(table)
            n += len(df)
            progress(f"datapakket: {n:,} woningen")
    finally:
        for w in writers.values():
            w.close()
    columns = {**WONINGEN, **VORM,
               **{f"sig_{m}_{o}": f"berekend uit BAG en 3D-BAG ({m}; woningtype uit de vorm van "
                                   "het pand, geen EP-online)" for m in METHODS for o in OUTPUTS}}
    manifest = {
        "gemaakt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "woningen": n,
        "ep_online": "niet gebruikt in dit pakket",
        "bronnen": sources or {},
        "kolommen": {c: s for c, s in columns.items()
                     if c in have or c.startswith("sig_")},
        "bestanden": {f.name: {"bytes": f.stat().st_size,
                               "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}
                      for f in sorted(out.glob("*.parquet"))},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
    return out
