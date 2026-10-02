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

The columns follow the physiquant__unit naming convention (``docs/variabelen.md``; the manifest
says so in ``"namen"``). Packages made before it (up to and including the one of 2026-09-30) have
plain names (``bouwjaar``, ``sig_nta8800_H``); :func:`install` still takes them, through the one
table in :mod:`anonymate.namen`.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .namen import NAMEN_VERSIE, h3_kolom, naar_nieuw, uitvoer_kolom

# column -> source; only these go into the package
WONINGEN = {
    "vbo_id__str": "BAG", "postcode6__str": "BAG", "huisnummer__str": "BAG",
    "huisletter__str": "BAG", "toevoeging__str": "BAG", "woonplaats__cat": "BAG",
    "gemeente__cat": "CBS (gebiedsindelingen)", "provincie__cat": "CBS (gebiedsindelingen)",
    "bouwjaar__yr": "BAG", "oppervlakte__m2": "BAG", "pand_woningen__0": "BAG",
    "lat__degN": "BAG (rd_x, rd_y, afgerond op 5 decimalen)",
    "lon__degE": "BAG (rd_x, rd_y, afgerond op 5 decimalen)",
    "uhi__degC": ("RIVM stedelijk hitte-eiland effect (10 m raster, 01-06-2022; CC Publiek Domein 1.0), "
            "woninggewogen gemiddelde per postcode over de BAG-adrespunten (BAG, CC0)"),
}
VORM = {
    "daktype__cat": "3D-BAG", "bouwlagen__0": "3D-BAG", "hoogte__m": "3D-BAG",
    "aaneengebouwd__bool": "3D-BAG", "opp_grond__m2": "3D-BAG", "opp_dak_plat__m2": "3D-BAG",
    "opp_dak_schuin__m2": "3D-BAG", "opp_buitenmuur__m2": "3D-BAG",
    "opp_scheidingsmuur__m2": "3D-BAG",
}
# signatures computed without any label data (see anonymate.signature)
METHODS = ("nta8800", "mwa")
OUTPUTS = ("H", "C", "tau", "Asol", "Ainf")
EP_COLUMNS = {"energielabel__cat", "energie_index__0", "compactheid__m2_m_2",
              "label_oppervlakte__m2", "warmtebehoefte__kWh_m_2_a_1", "nta8800__bool"}


def sig_kolom(methode: str, uitvoer: str) -> str:
    """The package's signature column: ``sig_nta8800_H__W_K_1`` (the method is always in the
    name here, also for nta8800, unlike in the population)."""
    return f"sig_{methode}_{uitvoer_kolom(uitvoer)}"


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
    inputs["woningtype__cat"] = np.where(pd.to_numeric(inputs.get("pand_woningen__0"),
                                                       errors="coerce") > 1, "appartement", None)
    for c in EP_COLUMNS:
        inputs[c] = None
    out = pd.DataFrame(index=df.index)
    for method in METHODS:
        sig = compute(inputs, method)
        for o in OUTPUTS:
            out[sig_kolom(method, o)] = _three_digits(
                sig[uitvoer_kolom(o)].to_numpy()).astype("float32")
    return out


def make(population_parquet: str | Path, out_dir: str | Path, *, sources: dict | None = None,
         batch_rows: int = 250_000, progress=lambda m: None) -> Path:
    """Write ``woningen.parquet``, ``warmtesignatuur.parquet`` and ``manifest.json``."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    reader = pq.ParquetFile(population_parquet)
    source = reader.schema_arrow
    # a population from before the naming convention is read under the new names
    bron_naam = {naar_nieuw_naam(n): n for n in source.names}
    have = set(bron_naam)
    need = [c for c in list(WONINGEN) + list(VORM) + ["woningtype__cat"] if c in have]
    writers: dict[str, pq.ParquetWriter] = {}
    n = 0
    try:
        for batch in reader.iter_batches(batch_size=batch_rows,
                                         columns=[bron_naam[c] for c in need]):
            df = naar_nieuw(batch.to_pandas())
            for c in ("lat__degN", "lon__degE"):
                if c in df:
                    df[c] = df[c].round(5)
            if "huisnummer__str" in df:
                df["huisnummer__str"] = _as_text(df["huisnummer__str"])
            woningen = df[[c for c in WONINGEN if c in df]]
            sig = signatures_without_labels(df)
            vorm = pd.concat([df[["vbo_id__str"]], df[[c for c in VORM if c in df]], sig], axis=1)
            for name, part in (("woningen", woningen), ("warmtesignatuur", vorm)):
                table = pa.Table.from_pandas(part, preserve_index=False)
                # one schema for every batch: a whole-number column with gaps in one batch comes
                # back from pandas as float there, and as int in a batch without gaps
                table = table.cast(pa.schema(
                    [pa.field(c, pa.string()) if c == "huisnummer__str"
                     else source.field(bron_naam[c]).with_name(c) if c in have
                     else table.schema.field(c) for c in table.column_names]))
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
               **{sig_kolom(m, o): f"berekend uit BAG en 3D-BAG ({m}; woningtype uit de vorm van "
                                   "het pand, geen EP-online)" for m in METHODS for o in OUTPUTS}}
    manifest = {
        "gemaakt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "woningen": n,
        "namen": NAMEN_VERSIE,
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


ZIP_NAME = "anonymate-datapakket.zip"
MANIFEST_NAME = "manifest.json"


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()


def zip_package(package: str | Path, zip_path: str | Path) -> Path:
    """Zip a package directory deterministically (sorted names, fixed timestamps, stored
    parquet: it is compressed already), so the same package gives the same zip."""
    import zipfile
    src = Path(package)
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        for f in sorted(src.iterdir()):
            if f.is_file():
                info = zipfile.ZipInfo(f.name, date_time=(2020, 1, 1, 0, 0, 0))
                info.external_attr = 0o644 << 16
                with open(f, "rb") as fh, z.open(info, "w", force_zip64=True) as out:
                    while chunk := fh.read(1 << 22):
                        out.write(chunk)
    return zip_path


def publish(package: str | Path, out_dir: str | Path) -> dict:
    """The two release assets: ``anonymate-datapakket.zip`` and ``manifest.json`` (the package
    manifest plus a ``zip`` entry with the zip's size and sha256, which is what a download is
    checked against). Returns the published manifest."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    z = zip_package(package, out / ZIP_NAME)
    manifest = json.loads((Path(package) / MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["zip"] = {"naam": ZIP_NAME, "bytes": z.stat().st_size, "sha256": sha256_file(z)}
    (out / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
    return manifest


def verify(zip_path: str | Path, manifest_path: str | Path) -> dict:
    """Check a downloaded zip against the published manifest: the zip's sha256, and the sha256
    of every file inside against the manifest's list. Raises ValueError on any difference."""
    import zipfile
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    want = (manifest.get("zip") or {}).get("sha256")
    if not want:
        raise ValueError("het manifest bevat geen sha256 van de zip")
    got = sha256_file(zip_path)
    if got != want:
        raise ValueError(f"{Path(zip_path).name}: sha256 klopt niet (manifest {want[:12]}..., "
                         f"bestand {got[:12]}...); download opnieuw")
    with zipfile.ZipFile(zip_path) as z:
        for name, info in (manifest.get("bestanden") or {}).items():
            h = hashlib.sha256()
            with z.open(name) as f:
                while chunk := f.read(1 << 22):
                    h.update(chunk)
            if h.hexdigest() != info["sha256"]:
                raise ValueError(f"{name} in de zip komt niet overeen met het manifest")
    return manifest


# the label columns of ``raw/ep_online.parquet`` (the raw names) and what they are called in the
# population
LABEL_COLUMNS = ["energielabel", "woningtype", "energie_index", "compactheid",
                 "label_oppervlakte", "warmtebehoefte", "nta8800"]


def naar_nieuw_naam(kolom: str) -> str:
    from .namen import OUD_NAAR_NIEUW
    return OUD_NAAR_NIEUW.get(kolom, kolom)


def _as_text(values: pd.Series) -> pd.Series:
    """House numbers as text (the old package had them as whole numbers)."""
    if pd.api.types.is_numeric_dtype(values):
        return pd.to_numeric(values, errors="coerce").astype("Int64").astype("string")
    return values.astype("string")


def install(package: str | Path, store, *, batch_rows: int = 250_000,
            progress=lambda m: None, fraction=None) -> Path:
    """Make the local population from a data package, as ``anonymate build`` would from the
    sources: coordinates, KNMI station, H3 cells and all signatures.

    What the package leaves out is derived here: the dwelling type from the building's shape
    (``woningtype_bron`` = 'vorm'). When the user has ingested EP-online with their own key
    (``raw/ep_online.parquet``), the label and label data are joined on the BAG id and win over
    the shape (``woningtype_bron`` = 'ep-online'), and the label-based signatures are computed
    too; that data never came from the package. ``fraction(x)`` is called after every batch with the
    share of the package's dwellings done.
    """
    import tempfile
    import zipfile

    import pyarrow as pa
    import pyarrow.parquet as pq

    from .signature import infer_dwelling_type
    from .store import H3_RESOLUTIONS, _h3_cells, _nearest_station, _with_signatures

    src = Path(package)
    tmp = None
    if src.suffix.lower() == ".zip":
        tmp = tempfile.TemporaryDirectory()
        with zipfile.ZipFile(src) as z:
            z.extractall(tmp.name)
        found = next(Path(tmp.name).rglob("manifest.json"))
        src = found.parent
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    st = store.raw / "knmi_stations.parquet"
    if st.exists():
        stations = pd.read_parquet(st)
    else:
        from . import voorbeeld
        stations = voorbeeld.stations()
    ep = store.raw / "ep_online.parquet"
    labels = None
    if ep.exists():
        cols = [c for c in ["vbo_id"] + LABEL_COLUMNS if c in pq.read_schema(ep).names]
        labels = pd.read_parquet(ep, columns=cols).drop_duplicates("vbo_id", keep="last") \
            .set_index("vbo_id")
        progress(f"EP-online koppelen: {len(labels):,} labels uit de eigen opslag")
    # kept, so they can be closed before the temporary directory goes (Windows cannot delete
    # a file that is still open)
    homes_file = pq.ParquetFile(src / "woningen.parquet")
    shape_file = pq.ParquetFile(src / "warmtesignatuur.parquet")
    homes = homes_file.iter_batches(batch_size=batch_rows)
    shape = shape_file.iter_batches(batch_size=batch_rows)
    out = store.population_path
    part = out.with_suffix(".parquet.part")
    writer, n = None, 0
    try:
        for hb, sb in zip(homes, shape):
            # a package from before the naming convention has the old names: map them
            df = naar_nieuw(hb.to_pandas())
            vorm = naar_nieuw(sb.to_pandas())
            df["huisnummer__str"] = _as_text(df["huisnummer__str"])
            if not (df["vbo_id__str"].to_numpy() == vorm["vbo_id__str"].to_numpy()).all():
                raise ValueError("datapakket: woningen en warmtesignatuur lopen niet gelijk")
            df = pd.concat([df, vorm.drop(columns=["vbo_id__str"])
                            .drop(columns=[c for c in vorm if c.startswith("sig_")])], axis=1)
            df["postcode4__str"] = df["postcode6__str"].astype("string").str[:4]
            df["eengezins__bool"] = pd.to_numeric(df["pand_woningen__0"], errors="coerce") == 1
            flat = pd.to_numeric(df["pand_woningen__0"], errors="coerce") > 1
            guess = infer_dwelling_type(df["aaneengebouwd__bool"], df["opp_scheidingsmuur__m2"],
                                        df["opp_buitenmuur__m2"])
            df["woningtype__cat"] = np.where(flat, "appartement", guess)
            df["woningtype_bron__cat"] = np.where(df["woningtype__cat"].notna(), "vorm", None)
            if labels is not None:
                lab = labels.reindex(df["vbo_id__str"].astype(str))
                for c in LABEL_COLUMNS:
                    if c == "woningtype":
                        known = lab[c].notna().to_numpy()
                        df.loc[known, "woningtype__cat"] = lab[c].to_numpy()[known]
                        df.loc[known, "woningtype_bron__cat"] = "ep-online"
                    elif c in lab:
                        df[naar_nieuw_naam(c)] = lab[c].to_numpy()
            lat = df["lat__degN"].to_numpy(dtype=float)
            lon = df["lon__degE"].to_numpy(dtype=float)
            df["knmi_station__cat"] = _nearest_station(lat, lon, stations)
            for res in H3_RESOLUTIONS:
                df[h3_kolom(res)] = _h3_cells(lat, lon, res)
            # fixed types, so a column that is empty in one batch still fits the file
            for c in df.columns:
                if c in ("nta8800__bool", "aaneengebouwd__bool", "eengezins__bool"):
                    df[c] = df[c].astype("boolean")
                elif df[c].dtype == object:
                    df[c] = df[c].astype("string")
            table = _with_signatures(pa.Table.from_pandas(df, preserve_index=False))
            if writer is not None:
                table = table.cast(writer.schema)
            if writer is None:
                writer = pq.ParquetWriter(part, table.schema, compression="zstd")
            writer.write_table(table)
            n += table.num_rows
            progress(f"populatie uit datapakket: {n:,} woningen")
            if fraction is not None and manifest.get("woningen"):
                fraction(min(n / manifest["woningen"], 1.0))
    finally:
        if writer is not None:
            writer.close()
        homes_file.close()
        shape_file.close()
        if tmp is not None:
            tmp.cleanup()
    if writer is None:
        raise ValueError("datapakket is leeg")
    part.replace(out)
    for name, version in (manifest.get("bronnen") or {}).items():
        store.record(name, version=f"{version} (uit datapakket)")
    store.record("datapakket", version=manifest.get("gemaakt"), rows=n,
                 ep_online="eigen opslag" if labels is not None else "niet gebruikt")
    m = store.manifest()
    m["population"] = {"rows": n, "built": datetime.now().isoformat(timespec="seconds"),
                       "from_package": manifest.get("gemaakt"),
                       "h3_resolutions": list(H3_RESOLUTIONS)}
    store.manifest_path.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    return out
