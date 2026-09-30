"""The local store: public registers downloaded once, in bulk, and turned into one population.

This is the **only** module that uses the network, and only to download complete public
datasets. Nothing about the dataset you assess is ever sent anywhere: the ingest functions do not
even accept it as input.

Sources (all bulk, all public):

``bag``
    PDOK ``bag-light.gpkg`` (Kadaster BAG, ~7.8 GB, monthly). Every *verblijfsobject* with a
    residential function: address, usable area, construction year of its building, point.
``gebieden``
    PDOK bestuurlijke gebieden: municipality code -> name -> province.
``knmi``
    KNMI station list with coordinates (stations that measure temperature).
``ep-online``
    RVO EP-online *totaalbestand*: registered energy labels (needs a free API key, read from the
    ``EPONLINE_API_KEY`` environment variable; never stored by this tool).
``3dbag``
    TU Delft / 3DGI 3D-BAG (CC BY 4.0), tile by tile: roof type, floors, height and whether a
    building shares walls, per BAG pand.

:func:`build` joins them into ``population.parquet``: one row per dwelling, canonical columns
(see :mod:`anonymate.qids`), plus a manifest recording the exact version of every source.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import re
import sqlite3
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .population import Population, Snapshot
from .qids import normalise_dwelling_type, normalise_label
from .rd import haversine_km, rd_to_wgs84

BAG_URL = "https://service.pdok.nl/kadaster/bag/atom/downloads/bag-light.gpkg"
GEBIEDEN_URL = ("https://api.pdok.nl/kadaster/bestuurlijkegebieden/ogc/v1/collections/"
                "gemeentegebied/items?f=json&limit=1000")
LAND_URL = ("https://api.pdok.nl/cbs/wijken-en-buurten-2024/ogc/v1/collections/gemeenten/"
            "items?f=json&limit=50")
KNMI_URL = "https://www.daggegevens.knmi.nl/klimatologie/uurgegevens"
EPONLINE_URL = "https://public.ep-online.nl/api/v5/Mutatiebestand/DownloadInfo?fileType=csv"
EPONLINE_KEY_ENV = "EPONLINE_API_KEY"

# BAG statuses of dwellings that exist (not withdrawn, not merely planned)
LIVE_STATUSES = ("Verblijfsobject in gebruik", "Verblijfsobject in gebruik (niet ingemeten)",
                 "Verbouwing verblijfsobject")
H3_RESOLUTIONS = (4, 5, 6, 7, 8)

Progress = Callable[[str], None]


def _quiet(_: str) -> None:
    pass


def default_home() -> Path:
    if env := os.environ.get("ANONYMATE_HOME"):
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME") \
        or Path.home() / ".local" / "share"
    return Path(base) / "anonymate"


# ------------------------------------------------------------------------------------------------
# network: bulk downloads only
# ------------------------------------------------------------------------------------------------

def fetch(url: str, *, data: bytes | None = None, headers: dict | None = None) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 (fixed public URLs)
        return r.read()


def download(url: str, dest: Path, *, headers: dict | None = None,
             progress: Progress = _quiet, attempts: int = 5) -> Path:
    """Download ``url`` to ``dest``, resuming a previous partial download (``dest.part``).

    A connection that drops halfway can end the response without an error; the file is only
    renamed to ``dest`` once it has the length the server announced, and otherwise the download
    resumes where it stopped (up to ``attempts`` times)."""
    import http.client
    import time
    import urllib.error
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, attempts + 1):
        try:
            done, total = _download_once(url, part, dest.name, headers, progress)
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError,
                TimeoutError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code < 500:
                raise
            done, total, why = (part.stat().st_size if part.exists() else 0), 0, str(e)
        else:
            if not total or done >= total:
                part.replace(dest)
                return dest
            why = f"verbinding na {done / 1e9:.2f} van {total / 1e9:.2f} GB gestopt"
        if attempt == attempts:
            raise RuntimeError(f"{dest.name}: download onvolledig na {attempts} pogingen ({why})")
        progress(f"{dest.name}: {why}; verder vanaf {done / 1e9:.2f} GB (poging {attempt + 1})")
        time.sleep(min(60, 5 * 2 ** attempt))
    raise AssertionError("unreachable")


def _download_once(url: str, part: Path, name: str, headers: dict | None,
                   progress: Progress) -> tuple[int, int]:
    """One request, appending to ``part``; returns (bytes on disk, announced total or 0)."""
    import urllib.request
    done = part.stat().st_size if part.exists() else 0
    h = dict(headers or {})
    if done:
        h["Range"] = f"bytes={done}-"
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310
        if done and r.status != 206:  # server ignored the range: start over
            done = 0
        total = int(r.headers.get("Content-Length", 0)) + done if r.headers.get(
            "Content-Length") else 0
        with open(part, "ab" if done else "wb") as f:
            last = -1
            while chunk := r.read(1 << 22):
                f.write(chunk)
                done += len(chunk)
                pct = int(100 * done / total) if total else -1
                if pct != last:
                    progress(f"{name}: {done / 1e9:.2f} GB ({pct}%)" if total else
                             f"{name}: {done / 1e9:.2f} GB")
                    last = pct
    return done, total


DATAPAKKET_URL = ("https://github.com/anonymate-nl/anonymate/releases/download/datapakket/"
                  "anonymate-datapakket.zip")
DATAPAKKET_MANIFEST_URL = DATAPAKKET_URL.rsplit("/", 1)[0] + "/manifest.json"


def download_datapakket(store: "Store", *, url: str = DATAPAKKET_URL,
                        manifest_url: str = DATAPAKKET_MANIFEST_URL,
                        progress: Progress = _quiet) -> Path:
    """The latest published datapakket in the downloads directory (resumable), checked against
    the published manifest.json; returns the zip's path."""
    from . import datapakket
    manifest = store.downloads / datapakket.MANIFEST_NAME
    manifest.write_bytes(fetch(manifest_url))     # small; always the current one
    zip_path = download(url, store.downloads / datapakket.ZIP_NAME, progress=progress)
    try:
        datapakket.verify(zip_path, manifest)
    except ValueError:
        zip_path.unlink(missing_ok=True)          # a wrong file must not be resumed or reused
        raise
    return zip_path


def dotenv(name: str, files: Iterable[Path]) -> str | None:
    """Value of ``name`` from the first ``.env`` file that defines it (``NAME=value`` lines)."""
    for f in files:
        if not f.is_file():
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and k.strip() == name and not k.lstrip().startswith("#"):
                return v.strip().strip('"').strip("'") or None
    return None


# ------------------------------------------------------------------------------------------------
# the store
# ------------------------------------------------------------------------------------------------

@dataclass
class Store:
    """``root`` holds the compact, derived tables the analysis reads (keep it on a fast local
    disk); ``downloads`` holds the large original files (may be a network share, e.g. a NAS),
    which are only read during ingest."""

    root: Path
    downloads_dir: Path | None = None

    @classmethod
    def open(cls, root: str | Path | None = None,
             downloads: str | Path | None = None) -> "Store":
        downloads = (downloads or os.environ.get("ANONYMATE_DOWNLOADS")
                     or dotenv("ANONYMATE_DOWNLOADS", [Path.cwd() / ".env"]))
        s = cls(Path(root) if root else default_home(), Path(downloads) if downloads else None)
        s.raw.mkdir(parents=True, exist_ok=True)
        s.downloads.mkdir(parents=True, exist_ok=True)
        return s

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def downloads(self) -> Path:
        return self.downloads_dir or self.root / "downloads"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def population_path(self) -> Path:
        return self.root / "population.parquet"

    def manifest(self) -> dict:
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        return {"sources": {}}

    def record(self, source: str, **info) -> None:
        m = self.manifest()
        m["sources"][source] = {**info, "ingested": dt.datetime.now().isoformat(timespec="seconds")}
        self.manifest_path.write_text(json.dumps(m, indent=2, ensure_ascii=False),
                                      encoding="utf-8")

    def snapshot(self) -> Snapshot:
        m = self.manifest()
        return Snapshot({k: str(v.get("version", "?")) for k, v in m["sources"].items()})

    def population(self) -> Population:
        if not self.population_path.exists():
            raise FileNotFoundError(
                f"geen populatie in {self.root}; draai eerst 'anonymate ingest' en "
                f"'anonymate build' / no population yet, run ingest and build first")
        return Population.from_parquet(str(self.population_path), self.snapshot())

    def status(self) -> pd.DataFrame:
        rows = [{"bron": k, **v} for k, v in self.manifest()["sources"].items()]
        return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------------
# BAG
# ------------------------------------------------------------------------------------------------

def gpkg_point(blob: bytes | None) -> tuple[float, float]:
    """(x, y) of a GeoPackage point geometry blob; NaN for empty/missing/non-point."""
    if not blob or blob[:2] != b"GP":
        return (np.nan, np.nan)
    flags = blob[3]
    if flags & 0b10000:  # empty geometry
        return (np.nan, np.nan)
    env = (flags >> 1) & 0b111
    off = 8 + (0, 32, 48, 48, 64)[env] if env <= 4 else 8
    wkb = blob[off:]
    fmt = "<" if wkb[0] == 1 else ">"
    gtype = struct.unpack(fmt + "I", wkb[1:5])[0] % 1000
    if gtype != 1:
        return (np.nan, np.nan)
    return struct.unpack(fmt + "dd", wkb[5:21])


_BAG_COLUMNS = ["identificatie", "oppervlakte", "status", "gebruiksdoel", "huisnummer",
                "huisletter", "toevoeging", "postcode", "woonplaats_naam", "bouwjaar",
                "pand_identificatie", "nummeraanduiding_hoofdadres_identificatie",
                "bronhouder_identificatie"]


def ingest_bag(store: Store, gpkg: str | Path | None = None, *, progress: Progress = _quiet,
               chunk: int = 200_000) -> Path:
    """Read every residential *verblijfsobject* from ``bag-light.gpkg`` into Parquet.

    Without ``gpkg`` the file is downloaded from PDOK (resumable) into the store first.
    """
    path = Path(gpkg) if gpkg else store.downloads / "bag-light.gpkg"
    if not path.exists():
        progress("BAG downloaden van PDOK (~7,8 GB) / downloading BAG from PDOK")
        download(BAG_URL, path, progress=progress)
    out = store.raw / "bag_vbo.parquet"
    part = out.with_suffix(".parquet.part")  # a crash never leaves a half file behind
    con = sqlite3.connect(sqlite_readonly_uri(path), uri=True)
    try:
        version = _gpkg_last_change(con, "verblijfsobject")
        cur = con.execute(f"SELECT {', '.join(_BAG_COLUMNS)}, geom FROM verblijfsobject "
                          "WHERE gebruiksdoel LIKE '%woonfunctie%'")
        writer, n = None, 0
        while rows := cur.fetchmany(chunk):
            df = pd.DataFrame([r[:-1] for r in rows], columns=_BAG_COLUMNS)
            xy = np.array([gpkg_point(r[-1]) for r in rows], dtype=float).reshape(-1, 2)
            df["rd_x"], df["rd_y"] = xy[:, 0], xy[:, 1]
            table = pa.Table.from_pandas(df, preserve_index=False,
                                         schema=_bag_schema())
            if writer is None:
                writer = pq.ParquetWriter(part, table.schema, compression="zstd")
            writer.write_table(table)
            n += len(df)
            progress(f"BAG: {n:,} verblijfsobjecten met woonfunctie")
        if writer is None:
            pq.write_table(pa.Table.from_pylist([], schema=_bag_schema()), part)
        else:
            writer.close()
    finally:
        con.close()
    part.replace(out)
    store.record("bag", version=version, file=str(path), rows=n, url=BAG_URL)
    return out


def sqlite_readonly_uri(path: Path) -> str:
    """Read-only SQLite URI for a local path or a network share (``\\\\server\\share``)."""
    from urllib.parse import quote
    from pathlib import PurePath
    p = path if isinstance(path, PurePath) else Path(path)
    posix = p.as_posix()  # C:/x/y.gpkg or //server/share/y.gpkg
    prefix = "//" if posix.startswith("//") else ("///" if posix[1:2] == ":" else "")
    return f"file:{prefix}{quote(posix, safe='/:')}?mode=ro"


def _bag_schema() -> pa.Schema:
    s = pa.string()
    i = pa.int64()
    return pa.schema([("identificatie", s), ("oppervlakte", i), ("status", s),
                      ("gebruiksdoel", s), ("huisnummer", i), ("huisletter", s),
                      ("toevoeging", s), ("postcode", s), ("woonplaats_naam", s),
                      ("bouwjaar", i), ("pand_identificatie", s),
                      ("nummeraanduiding_hoofdadres_identificatie", s),
                      ("bronhouder_identificatie", s), ("rd_x", pa.float64()),
                      ("rd_y", pa.float64())])


def _gpkg_last_change(con: sqlite3.Connection, table: str) -> str:
    try:
        row = con.execute("SELECT last_change FROM gpkg_contents WHERE table_name = ?",
                          (table,)).fetchone()
        return str(row[0]) if row else "onbekend"
    except sqlite3.Error:
        return "onbekend"


# ------------------------------------------------------------------------------------------------
# municipalities and KNMI stations
# ------------------------------------------------------------------------------------------------

def simplify(points: list, tolerance: float) -> list:
    """Douglas-Peucker on a ring of (lon, lat): drop points closer than ``tolerance`` (degrees)
    to the line between the points kept around them. Keeps the first and last point."""
    import numpy as np
    pts = np.asarray(points, float)
    if len(pts) < 5:
        return pts.tolist()
    keep = np.zeros(len(pts), bool)
    keep[0] = keep[-1] = True
    # a closed ring starts and ends in the same point: split it at the point farthest away
    far = int(np.argmax(np.hypot(*(pts - pts[0]).T)))
    keep[far] = True
    stack = [(0, far), (far, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        seg = pts[b] - pts[a]
        rel = pts[a + 1:b] - pts[a]
        norm = float(np.hypot(*seg)) or 1e-12
        dist = np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / norm
        i = int(np.argmax(dist))
        if dist[i] > tolerance:
            k = a + 1 + i
            keep[k] = True
            stack += [(a, k), (k, b)]
    return pts[keep].round(5).tolist()


def ingest_gebieden(store: Store, *, fetcher=fetch, progress: Progress = _quiet) -> Path:
    url, rows, borders = GEBIEDEN_URL, [], []
    while url:
        doc = json.loads(fetcher(url))
        for f in doc.get("features", []):
            rows.append(f["properties"])
            geom = f.get("geometry") or {}
            polys = ([geom["coordinates"]] if geom.get("type") == "Polygon"
                     else geom.get("coordinates", []) if geom.get("type") == "MultiPolygon" else [])
            # outer rings only, simplified to ~100 m: enough for a map in the window, offline
            rings = [simplify(poly[0], 0.001) for poly in polys if poly]
            borders.append({"gemeente": f["properties"].get("naam"),
                            "ringen": json.dumps(rings)})
        url = next((link["href"] for link in doc.get("links", []) if link.get("rel") == "next"),
                   None)
    df = pd.DataFrame(rows)[["code", "naam", "ligt_in_provincie_naam"]].rename(
        columns={"code": "gemeente_code", "naam": "gemeente",
                 "ligt_in_provincie_naam": "provincie"})
    out = store.raw / "gemeenten.parquet"
    df.to_parquet(out, index=False)
    if any(json.loads(b["ringen"]) for b in borders):
        pd.DataFrame(borders).to_parquet(store.raw / "gemeentegrenzen.parquet", index=False)
    progress(f"gemeenten: {len(df)}")
    store.record("gebieden", version=dt.date.today().isoformat(), rows=len(df), url=GEBIEDEN_URL)
    try:
        ingest_land(store, fetcher=fetcher, progress=progress)
    except Exception as e:  # noqa: BLE001 (the land is a nicety on the map)
        progress(f"let op: geen land-watergrens ({e})")
    return out


def land_polygons(features) -> list:
    """The Dutch land, without water, as polygons of rings (lon, lat), simplified to ~100 m: the
    land parts (``water == 'NEE'``) of the CBS municipalities. Outer ring first, then holes."""
    out = []
    for f in features:
        if (f.get("properties") or {}).get("water") != "NEE":
            continue
        geom = f.get("geometry") or {}
        polys = ([geom["coordinates"]] if geom.get("type") == "Polygon"
                 else geom.get("coordinates", []) if geom.get("type") == "MultiPolygon" else [])
        for poly in polys:
            rings = [simplify(r, 0.001) for r in poly]
            rings = [r for r in rings if len(r) >= 4]
            if rings:
                out.append(rings)
    return out


def ingest_land(store: Store, *, fetcher=fetch, progress: Progress = _quiet) -> Path:
    """``raw/nederland_land.parquet``: the land-water boundary for the map (CBS Wijk- en
    Buurtkaart, from the Bestand Bodemgebruik), so the IJsselmeer, the Wadden and the Zeeland
    waters show as water instead of as part of a municipality."""
    url, polygons = LAND_URL, []
    while url:
        doc = json.loads(fetcher(url))
        polygons += land_polygons(doc.get("features", []))
        url = next((link["href"] for link in doc.get("links", []) if link.get("rel") == "next"),
                   None)
        progress(f"land-watergrens: {len(polygons)} vlakken")
    out = store.raw / "nederland_land.parquet"
    pd.DataFrame({"ringen": [json.dumps(p) for p in polygons]}).to_parquet(out, index=False)
    store.record("land", version="CBS Wijk- en Buurtkaart 2024", rows=len(polygons), url=LAND_URL)
    return out


_STATION_RE = re.compile(r"^#\s+(\d{3})\s+([\d.]+)\s+([\d.]+)\s+(-?[\d.]+)\s+(.+?)\s*$")


def parse_knmi_stations(text: str) -> pd.DataFrame:
    """Stations listed in a KNMI hourly-data response that reported a temperature."""
    stations = {}
    for line in text.splitlines():
        if m := _STATION_RE.match(line):
            stations[m[1]] = (float(m[3]), float(m[2]), m[5])  # lat, lon, name
    measured = set()
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4 and parts[0] in stations and parts[3] != "":
            measured.add(parts[0])
    rows = [{"knmi_station": k, "lat": v[0], "lon": v[1], "naam": v[2]}
            for k, v in sorted(stations.items()) if k in measured]
    return pd.DataFrame(rows)


def ingest_knmi(store: Store, *, fetcher=fetch, reference_hour: str = "2024010112",
                progress: Progress = _quiet) -> Path:
    body = f"start={reference_hour}&end={reference_hour}&vars=T".encode()
    text = fetcher(KNMI_URL, data=body).decode("utf-8", "replace")
    df = parse_knmi_stations(text)
    out = store.raw / "knmi_stations.parquet"
    df.to_parquet(out, index=False)
    progress(f"KNMI-stations met temperatuurmeting: {len(df)}")
    store.record("knmi", version=f"stations met T op {reference_hour}", rows=len(df),
                 url=KNMI_URL)
    return out


# ------------------------------------------------------------------------------------------------
# EP-online
# ------------------------------------------------------------------------------------------------

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


_EP_SCHEMA = pa.schema([
    ("vbo_id", pa.string()), ("energielabel", pa.string()), ("woningtype", pa.string()),
    ("energie_index", pa.float64()), ("compactheid", pa.float64()),
    ("label_oppervlakte", pa.float64()), ("label_bouwjaar", pa.int64()),
    ("registratiedatum", pa.timestamp("us")),
    # net heat demand per m² from an NTA 8800 calculation (labels since 2021), and the method
    ("warmtebehoefte", pa.float64()), ("nta8800", pa.bool_()),
])


def iter_eponline_csv(stream: io.TextIOBase, chunk: int = 200_000,
                      meta_out: dict | None = None):
    """Yield compact DataFrames (schema ``_EP_SCHEMA``) from an EP-online totaalbestand CSV.

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
        return out.reindex(columns=_EP_SCHEMA.names)

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
        _EP_SCHEMA.empty_table().to_pandas()


def ingest_eponline(store: Store, file: str | Path | None = None, *, api_key: str | None = None,
                    fetcher=fetch, progress: Progress = _quiet) -> Path:
    """Ingest the EP-online totaalbestand (downloaded with an API key, or a local file).

    The zip is stored in ``store.downloads`` (may be a NAS); the result is a compact lookup
    table ``raw/ep_online.parquet``: one row per registered residential label, keyed by BAG
    verblijfsobject id.
    """
    version = "lokaal bestand"
    if file is None:
        key = (api_key or os.environ.get(EPONLINE_KEY_ENV)
               or dotenv(EPONLINE_KEY_ENV, [Path.cwd() / ".env", store.root / ".env"]))
        if not key:
            raise RuntimeError(
                f"geen EP-online API-sleutel: zet {EPONLINE_KEY_ENV} als omgevingsvariabele of "
                "in een .env-bestand (gratis aan te vragen via ep-online.nl), of geef een "
                "gedownload totaalbestand op")
        info = json.loads(fetcher(EPONLINE_URL, headers={"Authorization": key}))
        version = f"{info.get('bestandsnaam')} (geldig t/m {info.get('geldigTotEnMet')})"
        file = store.downloads / (info.get("bestandsnaam") or "ep-online-totaal.zip")
        if not Path(file).exists():
            progress(f"EP-online downloaden naar {Path(file).parent}")
            download(info["downloadUrl"], Path(file), progress=progress)
    file = Path(file)
    if version == "lokaal bestand":
        version = f"{file.name} (lokaal bestand)"
    progress(f"EP-online lezen: {file.name}")
    out = store.raw / "ep_online.parquet"
    part = out.with_suffix(".parquet.part")
    n = 0
    meta: dict = {}
    with pq.ParquetWriter(part, _EP_SCHEMA, compression="zstd") as writer:
        def consume(stream):
            nonlocal n
            for df in iter_eponline_csv(stream, meta_out=meta):
                writer.write_table(pa.Table.from_pandas(df, schema=_EP_SCHEMA,
                                                        preserve_index=False))
                n += len(df)
                progress(f"EP-online: {n:,} woninglabels")
        if file.suffix.lower() == ".zip":
            with zipfile.ZipFile(file) as z:
                name = next(x for x in z.namelist() if x.lower().endswith(".csv"))
                with z.open(name) as raw:
                    consume(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace"))
        else:
            with open(file, encoding="utf-8-sig", errors="replace") as f:
                consume(f)
    part.replace(out)
    if meta.get("PublicatieDatum"):
        version = f"publicatie {meta['PublicatieDatum']}, {version}"
    store.record("ep-online", version=version, file=str(file), rows=n,
                 **{k: v for k, v in meta.items() if k != "PublicatieDatum"})
    return out


# ------------------------------------------------------------------------------------------------
# 3D-BAG
# ------------------------------------------------------------------------------------------------

THREEDBAG_INDEX = "https://data.3dbag.nl/v20250903/tile_index.fgb"
THREEDBAG_VERSION = "v20250903"
_DAKTYPE = {"slanted": "schuin", "horizontal": "plat", "multiple horizontal": "plat_meerdere"}
_3DBAG_SCHEMA = pa.schema([
    ("pand_id", pa.string()), ("daktype", pa.string()), ("bouwlagen", pa.int64()),
    ("hoogte", pa.float64()), ("aaneengebouwd", pa.bool_()), ("volume", pa.float64()),
    # the building envelope, per building (all dwellings in it together), in m²
    ("opp_grond", pa.float64()), ("opp_dak_plat", pa.float64()), ("opp_dak_schuin", pa.float64()),
    ("opp_buitenmuur", pa.float64()), ("opp_scheidingsmuur", pa.float64()),
])


def read_3dbag_gpkg(path: str | Path) -> pd.DataFrame:
    """Per building (pand) from a 3D-BAG GeoPackage: roof type, floors, height, attached or not.

    ``hoogte`` is the highest 70th-percentile roof height over the building's parts minus the
    ground level (``b3_h_maaiveld``): a robust "how tall is it" in metres. ``aaneengebouwd`` is
    true when the building shares a wall with another (``b3_opp_scheidingsmuur`` > 0).
    """
    con = sqlite3.connect(sqlite_readonly_uri(Path(path)), uri=True)
    try:
        pand = pd.read_sql_query(
            "SELECT identificatie, b3_dak_type, b3_bouwlagen, b3_h_maaiveld, "
            "b3_opp_scheidingsmuur, b3_volume_lod22, b3_opp_grond, b3_opp_dak_plat, "
            "b3_opp_dak_schuin, b3_opp_buitenmuur FROM pand", con)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        h = pd.read_sql_query("SELECT identificatie, max(b3_h_70p) AS h70 FROM lod22_2d "
                              "GROUP BY identificatie", con) if "lod22_2d" in tables else \
            pd.DataFrame({"identificatie": [], "h70": []})
    finally:
        con.close()
    df = pand.merge(h, on="identificatie", how="left")
    out = pd.DataFrame({
        "pand_id": df["identificatie"].astype(str).str.extract(r"(\d{16})$")[0],
        "daktype": df["b3_dak_type"].map(_DAKTYPE),
        "bouwlagen": pd.to_numeric(df["b3_bouwlagen"], errors="coerce").round().astype("Int64"),
        "hoogte": (pd.to_numeric(df["h70"], errors="coerce")
                   - pd.to_numeric(df["b3_h_maaiveld"], errors="coerce")).round(1),
        "aaneengebouwd": (pd.to_numeric(df["b3_opp_scheidingsmuur"], errors="coerce") > 0)
        .astype("boolean").mask(pd.to_numeric(df["b3_opp_scheidingsmuur"],
                                              errors="coerce").isna()),
        "volume": pd.to_numeric(df["b3_volume_lod22"], errors="coerce").round(0),
        **{c.removeprefix("b3_"): pd.to_numeric(df[c], errors="coerce").round(1)
           for c in ("b3_opp_grond", "b3_opp_dak_plat", "b3_opp_dak_schuin",
                     "b3_opp_buitenmuur", "b3_opp_scheidingsmuur")},
    })
    out.loc[(out["hoogte"] < 0) | (out["hoogte"] > 400), "hoogte"] = np.nan
    return out[out["pand_id"].notna()].reindex(columns=_3DBAG_SCHEMA.names)


def threedbag_tiles(index_url: str = THREEDBAG_INDEX) -> pd.DataFrame:
    """The 3D-BAG tile index (tile id, GeoPackage URL, sha256). Needs DuckDB's spatial
    extension, which DuckDB downloads once; only used during ingest."""
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    return con.execute(f"SELECT tile_id, gpkg_download, gpkg_sha256 FROM ST_Read('{index_url}') "
                       "ORDER BY tile_id").fetchdf()


def ingest_3dbag(store: Store, source: str | Path | None = None, *, tiles: pd.DataFrame | None = None,
                 fetcher=fetch, progress: Progress = _quiet, max_tiles: int | None = None,
                 part_tiles: int = 250, keep_tiles: bool = True) -> Path:
    """Ingest 3D-BAG building attributes into ``raw/3dbag.parquet`` (one row per pand).

    ``source``: a GeoPackage (a tile or the full dump) or a folder of ``*.gpkg``/``*.gpkg.gz``.
    Without ``source`` the tiles are fetched one by one from the tile index into
    ``store.downloads/3dbag/<version>/`` (which may be a NAS; ~20 GB in total), each checked
    against its sha256 and kept for later use (e.g. the full envelope geometry). Tiles already
    there are not fetched again. Locally only the compact per-building table is kept, and
    memory stays small. Progress is kept per block of ``part_tiles`` tiles, so a stopped ingest
    resumes where it left off. ``keep_tiles=False`` drops each tile once read (for a machine
    without room for ~20 GB, such as a GitHub runner).
    """
    import gzip
    import hashlib
    import tempfile

    parts = store.raw / "3dbag_parts"
    parts.mkdir(exist_ok=True)
    out = store.raw / "3dbag.parquet"
    if source is not None:
        src = Path(source)
        files = sorted(src.glob("*.gpkg")) + sorted(src.glob("*.gpkg.gz")) if src.is_dir() \
            else [src]
        frames = []
        for f in files:
            if f.suffix == ".gz":
                with tempfile.TemporaryDirectory() as tmp:
                    g = Path(tmp) / "tile.gpkg"
                    with gzip.open(f) as zin, open(g, "wb") as zout:
                        zout.write(zin.read())
                    frames.append(read_3dbag_gpkg(g))
            else:
                frames.append(read_3dbag_gpkg(f))
            progress(f"3D-BAG: {f.name}")
        df = pd.concat(frames, ignore_index=True).drop_duplicates("pand_id")
        pq.write_table(pa.Table.from_pandas(df, schema=_3DBAG_SCHEMA, preserve_index=False), out,
                       compression="zstd")
        store.record("3dbag", version=f"{THREEDBAG_VERSION} (lokaal: {src.name})", rows=len(df))
        return out

    tiles = tiles if tiles is not None else threedbag_tiles()
    if max_tiles is not None:
        tiles = tiles.head(max_tiles)
    done_file = parts / "klaar.txt"
    done = set(done_file.read_text(encoding="utf-8").split()) if done_file.exists() else set()
    todo = tiles[~tiles["tile_id"].isin(done)]
    progress(f"3D-BAG: {len(todo):,} van {len(tiles):,} tegels te doen")
    block, block_ids = [], []

    def flush():
        if not block_ids:
            return
        name = parts / f"part-{len(list(parts.glob('part-*.parquet'))):05d}.parquet"
        df = pd.concat(block, ignore_index=True) if block else \
            _3DBAG_SCHEMA.empty_table().to_pandas()
        pq.write_table(pa.Table.from_pandas(df, schema=_3DBAG_SCHEMA, preserve_index=False), name,
                       compression="zstd")
        with open(done_file, "a", encoding="utf-8") as f:
            f.write("\n".join(block_ids) + "\n")
        block.clear()
        block_ids.clear()

    tile_dir = store.downloads / "3dbag" / THREEDBAG_VERSION
    tile_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        g = Path(tmp) / "tile.gpkg"
        for i, t in enumerate(todo.itertuples(index=False), 1):
            kept = tile_dir / (str(t.tile_id).replace("/", "-") + ".gpkg.gz")
            data = kept.read_bytes() if kept.exists() else b""
            if not data or (t.gpkg_sha256 and hashlib.sha256(data).hexdigest() != t.gpkg_sha256):
                data = fetcher(t.gpkg_download)
                if t.gpkg_sha256 and hashlib.sha256(data).hexdigest() != t.gpkg_sha256:
                    raise RuntimeError(f"3D-BAG-tegel {t.tile_id}: sha256 klopt niet")
                if keep_tiles:
                    part = kept.with_suffix(".gz.part")
                    part.write_bytes(data)
                    part.replace(kept)
            g.write_bytes(gzip.decompress(data))
            block.append(read_3dbag_gpkg(g))
            block_ids.append(t.tile_id)
            if len(block_ids) >= part_tiles:
                flush()
            if i % 50 == 0 or i == len(todo):
                progress(f"3D-BAG: {len(done) + i:,} / {len(tiles):,} tegels")
        flush()
    con = duckdb.connect()
    q = (parts / "part-*.parquet").as_posix()
    n = con.execute(f"""
        COPY (SELECT * FROM read_parquet('{q}') QUALIFY row_number() OVER (PARTITION BY pand_id) = 1)
        TO '{out.as_posix()}' (FORMAT parquet, COMPRESSION zstd)""").fetchone()[0]
    complete = len(done) + len(todo) == len(tiles) and max_tiles is None
    store.record("3dbag", version=THREEDBAG_VERSION + ("" if complete else " (deels)"),
                 rows=int(n), tiles=int(len(done) + len(todo)), url=THREEDBAG_INDEX)
    return out


# ------------------------------------------------------------------------------------------------
# build the population
# ------------------------------------------------------------------------------------------------

def _with_signatures(table):
    """``table`` with every ``sig_*`` column (re)computed from its register columns."""
    from .signature import INPUT, population_columns
    keep = [c for c in table.column_names if not c.startswith("sig_")]
    table = table.select(keep)
    inputs = table.select([c for c in INPUT if c in table.column_names]).to_pandas()
    sig = population_columns(inputs)
    for c in sig.columns:
        table = table.append_column(c, _nullable(sig[c].to_numpy()))
    return table


def refresh_signatures(store: Store, *, progress: Progress = _quiet,
                       batch_rows: int = 250_000) -> Path:
    """Recompute every ``sig_*`` column of an existing population (after a change in
    :mod:`anonymate.signature`), without rebuilding it from the raw sources."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    src = store.population_path
    part = src.with_suffix(".parquet.part")
    reader = pq.ParquetFile(src)
    total, n, writer = reader.metadata.num_rows, 0, None
    try:
        for batch in reader.iter_batches(batch_size=batch_rows):
            table = _with_signatures(pa.Table.from_batches([batch]))
            if writer is None:
                writer = pq.ParquetWriter(part, table.schema, compression="zstd")
            writer.write_table(table)
            n += table.num_rows
            progress(f"signaturen: {n:,} / {total:,} woningen")
    finally:
        reader.close()   # Windows cannot replace a file that is still open
        if writer is not None:
            writer.close()
    part.replace(src)
    return src


def build(store: Store, *, h3_resolutions: Iterable[int] = H3_RESOLUTIONS,
          progress: Progress = _quiet, batch_rows: int = 250_000,
          memory_limit: str = "1GB") -> Path:
    """Join the ingested sources into ``population.parquet`` (one row per live dwelling).

    Built to fit on an ordinary laptop: DuckDB works in a temporary on-disk database with a
    memory limit (spilling to disk when needed), and the result is streamed in batches of
    ``batch_rows`` dwellings, each enriched (coordinates, KNMI station, H3 cells) and written
    before the next is read.
    """
    bag = store.raw / "bag_vbo.parquet"
    if not bag.exists():
        raise FileNotFoundError("BAG ontbreekt: draai eerst 'anonymate ingest bag'")
    h3_resolutions = tuple(h3_resolutions)
    q = lambda p: "'" + p.as_posix().replace("'", "''") + "'"  # noqa: E731
    work = store.root / "build.duckdb"
    work.unlink(missing_ok=True)
    tmp = store.root / "build.tmp"
    con = duckdb.connect(str(work))
    con.execute(f"SET memory_limit = '{memory_limit}'")
    con.execute(f"SET temp_directory = {q(tmp)}")
    con.execute("SET preserve_insertion_order = false")

    statuses = ", ".join("'" + s + "'" for s in LIVE_STATUSES)
    con.execute(f"""
        CREATE VIEW vbo AS
        SELECT identificatie AS vbo_id,
               nummeraanduiding_hoofdadres_identificatie AS nummeraanduiding_id,
               pand_identificatie AS pand_id,
               upper(replace(postcode, ' ', '')) AS postcode6,
               left(upper(replace(postcode, ' ', '')), 4) AS postcode4,
               huisnummer, huisletter, toevoeging, woonplaats_naam AS woonplaats,
               bronhouder_identificatie AS gemeente_code,
               CASE WHEN bouwjaar BETWEEN 1000 AND 2100 THEN bouwjaar END AS bouwjaar,
               CASE WHEN oppervlakte BETWEEN 1 AND 99999 THEN oppervlakte END AS oppervlakte,
               status, rd_x, rd_y
        FROM read_parquet({q(bag)})
        WHERE status IN ({statuses})
    """)
    # dwellings per building: one small table instead of a window over everything
    con.execute("CREATE TABLE panden AS SELECT pand_id, count(*) AS pand_woningen "
                "FROM vbo GROUP BY pand_id")

    gem = store.raw / "gemeenten.parquet"
    if gem.exists():
        gem_join = f"LEFT JOIN read_parquet({q(gem)}) g USING (gemeente_code)"
        gem_cols = "g.gemeente, g.provincie"
    else:
        progress("let op: geen gemeentenamen (draai 'anonymate ingest gebieden')")
        gem_join, gem_cols = "", "v.gemeente_code AS gemeente, NULL::VARCHAR AS provincie"

    ep = store.raw / "ep_online.parquet"
    label_cols = ["energielabel", "woningtype", "energie_index", "compactheid",
                  "label_oppervlakte", "warmtebehoefte", "nta8800"]
    if ep.exists():
        cols = set(pq.read_schema(ep).names)
        order = "registratiedatum DESC NULLS LAST" if "registratiedatum" in cols else "1"
        typed = {"energielabel": "VARCHAR", "woningtype": "VARCHAR", "energie_index": "DOUBLE",
                 "compactheid": "DOUBLE", "label_oppervlakte": "DOUBLE",
                 "warmtebehoefte": "DOUBLE", "nta8800": "BOOLEAN"}
        sel = ", ".join(c if c in cols else f"NULL::{typed[c]} AS {c}" for c in label_cols)
        con.execute(f"""
            CREATE TABLE labels AS
            SELECT vbo_id, {sel} FROM read_parquet({q(ep)})
            WHERE vbo_id IS NOT NULL
            QUALIFY row_number() OVER (PARTITION BY vbo_id ORDER BY {order}) = 1
        """)
        label_join = "LEFT JOIN labels l USING (vbo_id)"
        label_sel = ("l.energielabel, "
                     "CASE WHEN l.woningtype IS NULL AND p.pand_woningen > 1 "
                     "THEN 'appartement' ELSE l.woningtype END AS woningtype, "
                     "l.energie_index, l.compactheid, l.label_oppervlakte, l.warmtebehoefte, "
                     "l.nta8800")
    else:
        progress("let op: geen energielabels (draai 'anonymate ingest ep-online')")
        label_join = ""
        label_sel = ("NULL::VARCHAR AS energielabel, "
                     "CASE WHEN p.pand_woningen > 1 THEN 'appartement' END AS woningtype, "
                     "NULL::DOUBLE AS energie_index, NULL::DOUBLE AS compactheid, "
                     "NULL::DOUBLE AS label_oppervlakte, NULL::DOUBLE AS warmtebehoefte, "
                     "NULL::BOOLEAN AS nta8800")

    b3 = store.raw / "3dbag.parquet"
    if b3.exists():
        b3_join = f"LEFT JOIN read_parquet({q(b3)}) d USING (pand_id)"
        b3_cols = ("d.daktype, d.bouwlagen, d.hoogte, d.aaneengebouwd, d.volume AS pand_volume, "
                   "d.opp_grond, d.opp_dak_plat, d.opp_dak_schuin, d.opp_buitenmuur, "
                   "d.opp_scheidingsmuur")
    else:
        progress("let op: geen 3D-BAG (draai 'anonymate ingest 3dbag')")
        b3_join = ""
        b3_cols = ("NULL::VARCHAR AS daktype, NULL::BIGINT AS bouwlagen, NULL::DOUBLE AS hoogte, "
                   "NULL::BOOLEAN AS aaneengebouwd, NULL::DOUBLE AS pand_volume, "
                   "NULL::DOUBLE AS opp_grond, NULL::DOUBLE AS opp_dak_plat, "
                   "NULL::DOUBLE AS opp_dak_schuin, NULL::DOUBLE AS opp_buitenmuur, "
                   "NULL::DOUBLE AS opp_scheidingsmuur")

    total = con.execute("SELECT count(*) FROM vbo").fetchone()[0]
    progress(f"populatie: {total:,} woningen")
    reader = con.execute(f"""
        SELECT v.*, p.pand_woningen, p.pand_woningen = 1 AS eengezins, {gem_cols}, {label_sel},
               {b3_cols}
        FROM vbo v
        JOIN panden p USING (pand_id)
        {gem_join}
        {label_join}
        {b3_join}
    """).fetch_record_batch(batch_rows)

    st = store.raw / "knmi_stations.parquet"
    stations = pd.read_parquet(st) if st.exists() else None
    if stations is None:
        progress("let op: geen KNMI-stations (draai 'anonymate ingest knmi')")

    out = store.population_path
    part = out.with_suffix(".parquet.part")
    writer, n = None, 0
    try:
        for batch in reader:
            table = pa.Table.from_batches([batch])
            lat, lon = rd_to_wgs84(table["rd_x"].to_numpy(zero_copy_only=False),
                                   table["rd_y"].to_numpy(zero_copy_only=False))
            # NaN -> NULL: in SQL, NaN is a value (it sorts above everything), NULL is "unknown"
            table = table.append_column("lat", _nullable(lat)).append_column("lon", _nullable(lon))
            if stations is not None:
                table = table.append_column("knmi_station", pa.array(
                    _nearest_station(lat, lon, stations), type=pa.string()))
            for res in h3_resolutions:
                table = table.append_column(f"h3_r{res}", pa.array(_h3_cells(lat, lon, res),
                                                                   type=pa.string()))
            # the baseline heat performance signature: what anyone can compute from these
            # public registers for every single-family home (see anonymate.signature)
            table = _with_signatures(table)
            if writer is None:
                writer = pq.ParquetWriter(part, table.schema, compression="zstd")
            writer.write_table(table)
            n += table.num_rows
            progress(f"populatie: {n:,} / {total:,} woningen verrijkt")
    finally:
        if writer is not None:
            writer.close()
        con.close()
        work.unlink(missing_ok=True)
        wal = work.with_suffix(".duckdb.wal")
        wal.unlink(missing_ok=True)
    if writer is None:
        raise RuntimeError("geen woningen in de BAG-extractie / no dwellings in the BAG extract")
    part.replace(out)
    m = store.manifest()
    m["population"] = {"rows": n, "built": dt.datetime.now().isoformat(timespec="seconds"),
                       "h3_resolutions": list(h3_resolutions)}
    store.manifest_path.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    progress(f"klaar: {out}")
    return out


def _nullable(values) -> pa.Array:
    """Float array with NaN written as NULL."""
    return pa.array(np.asarray(values, dtype=float), type=pa.float64(), from_pandas=True)


def _nearest_station(lat: np.ndarray, lon: np.ndarray, stations: pd.DataFrame,
                     chunk: int = 1_000_000) -> list[str | None]:
    codes = stations["knmi_station"].astype(str).to_numpy()
    slat, slon = stations["lat"].to_numpy(), stations["lon"].to_numpy()
    out = np.empty(len(lat), dtype=object)
    for a in range(0, len(lat), chunk):
        la, lo = lat[a:a + chunk, None], lon[a:a + chunk, None]
        d = haversine_km(la, lo, slat[None, :], slon[None, :])
        out[a:a + chunk] = codes[np.argmin(d, axis=1)]
    out[np.isnan(lat)] = None
    return out.tolist()


def _h3_cells(lat: np.ndarray, lon: np.ndarray, res: int) -> list[str | None]:
    import h3
    # many dwellings share a point (apartments); compute each distinct point once
    key = np.round(lat, 6) + 1j * np.round(lon, 6)
    uniq, inv = np.unique(key, return_inverse=True)
    cells = [None if np.isnan(k.real) else h3.latlng_to_cell(k.real, k.imag, res) for k in uniq]
    return [cells[i] for i in inv]
