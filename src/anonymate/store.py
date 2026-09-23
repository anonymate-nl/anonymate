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
             progress: Progress = _quiet) -> Path:
    """Download ``url`` to ``dest``, resuming a previous partial download (``dest.part``)."""
    import urllib.request
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    done = part.stat().st_size if part.exists() else 0
    h = dict(headers or {})
    if done:
        h["Range"] = f"bytes={done}-"
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310
        if done and r.status != 206:  # server ignored the range: start over
            done = 0
        total = int(r.headers.get("Content-Length", 0)) + done
        with open(part, "ab" if done else "wb") as f:
            last = -1
            while chunk := r.read(1 << 22):
                f.write(chunk)
                done += len(chunk)
                pct = int(100 * done / total) if total else -1
                if pct != last:
                    progress(f"{dest.name}: {done / 1e9:.2f} GB ({pct}%)" if total else
                             f"{dest.name}: {done / 1e9:.2f} GB")
                    last = pct
    part.replace(dest)
    return dest


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
               chunk: int = 500_000) -> Path:
    """Read every residential *verblijfsobject* from ``bag-light.gpkg`` into Parquet.

    Without ``gpkg`` the file is downloaded from PDOK (resumable) into the store first.
    """
    path = Path(gpkg) if gpkg else store.downloads / "bag-light.gpkg"
    if not path.exists():
        progress("BAG downloaden van PDOK (~7,8 GB) / downloading BAG from PDOK")
        download(BAG_URL, path, progress=progress)
    out = store.raw / "bag_vbo.parquet"
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
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
                writer = pq.ParquetWriter(out, table.schema, compression="zstd")
            writer.write_table(table)
            n += len(df)
            progress(f"BAG: {n:,} verblijfsobjecten met woonfunctie")
        if writer is None:
            pq.write_table(pa.Table.from_pylist([], schema=_bag_schema()), out)
        else:
            writer.close()
    finally:
        con.close()
    store.record("bag", version=version, file=str(path), rows=n, url=BAG_URL)
    return out


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

def ingest_gebieden(store: Store, *, fetcher=fetch, progress: Progress = _quiet) -> Path:
    url, rows = GEBIEDEN_URL, []
    while url:
        doc = json.loads(fetcher(url))
        rows += [f["properties"] for f in doc.get("features", [])]
        url = next((link["href"] for link in doc.get("links", []) if link.get("rel") == "next"),
                   None)
    df = pd.DataFrame(rows)[["code", "naam", "ligt_in_provincie_naam"]].rename(
        columns={"code": "gemeente_code", "naam": "gemeente",
                 "ligt_in_provincie_naam": "provincie"})
    out = store.raw / "gemeenten.parquet"
    df.to_parquet(out, index=False)
    progress(f"gemeenten: {len(df)}")
    store.record("gebieden", version=dt.date.today().isoformat(), rows=len(df), url=GEBIEDEN_URL)
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
}


def read_eponline_csv(stream: io.TextIOBase) -> pd.DataFrame:
    """Read an EP-online totaalbestand CSV, tolerant to column naming and delimiter."""
    head = stream.readline()
    delim = max(";,\t|", key=head.count)
    headers = next(csv.reader([head], delimiter=delim))
    norm = [_norm_header(h) for h in headers]
    pick = {}
    for field, candidates in _EP_FIELDS.items():
        for c in candidates:
            if c in norm:
                pick[field] = norm.index(c)
                break
    if "energieklasse" not in pick or ("vbo_id" not in pick and "postcode" not in pick):
        raise ValueError(f"onbekend EP-online-formaat; kolommen: {headers[:30]}")
    rows = []
    for rec in csv.reader(stream, delimiter=delim):
        if not rec:
            continue
        rows.append({f: (rec[i].strip() if i < len(rec) else "") for f, i in pick.items()})
    df = pd.DataFrame(rows, columns=list(pick))
    return df.replace("", None)


def ingest_eponline(store: Store, file: str | Path | None = None, *, api_key: str | None = None,
                    fetcher=fetch, progress: Progress = _quiet) -> Path:
    """Ingest the EP-online totaalbestand (downloaded with an API key, or a local file)."""
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
            download(info["downloadUrl"], Path(file), progress=progress)
    file = Path(file)
    progress(f"EP-online lezen: {file.name}")
    if file.suffix.lower() == ".zip":
        with zipfile.ZipFile(file) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            with z.open(name) as raw:
                df = read_eponline_csv(io.TextIOWrapper(raw, encoding="utf-8-sig",
                                                        errors="replace"))
    else:
        with open(file, encoding="utf-8-sig", errors="replace") as f:
            df = read_eponline_csv(f)
    if "gebouwklasse" in df:
        df = df[df["gebouwklasse"].isna() | df["gebouwklasse"].str.upper().str.startswith("W")]
    df["energielabel"] = df["energieklasse"].map(lambda v: normalise_label(v) if v else None)
    if "gebouwtype" in df:
        sub = df.get("gebouwsubtype")
        both = df["gebouwtype"].fillna("") + " " + (sub.fillna("") if sub is not None else "")
        df["woningtype"] = both.map(lambda v: normalise_dwelling_type(v) if v.strip() else None)
    for c in ("energie_index", "compactheid", "label_oppervlakte"):
        if c in df:
            df[c] = pd.to_numeric(df[c].str.replace(",", "."), errors="coerce")
    if "registratiedatum" in df:
        df["registratiedatum"] = pd.to_datetime(df["registratiedatum"], errors="coerce",
                                                dayfirst=False)
    out = store.raw / "ep_online.parquet"
    df.to_parquet(out, index=False)
    progress(f"EP-online: {len(df):,} woninglabels")
    store.record("ep-online", version=version, file=file.name, rows=len(df))
    return out


# ------------------------------------------------------------------------------------------------
# build the population
# ------------------------------------------------------------------------------------------------

def build(store: Store, *, h3_resolutions: Iterable[int] = H3_RESOLUTIONS,
          progress: Progress = _quiet) -> Path:
    """Join the ingested sources into ``population.parquet`` (one row per live dwelling)."""
    bag = store.raw / "bag_vbo.parquet"
    if not bag.exists():
        raise FileNotFoundError("BAG ontbreekt: draai eerst 'anonymate ingest bag'")
    con = duckdb.connect()
    q = lambda p: "'" + p.as_posix().replace("'", "''") + "'"  # noqa: E731
    con.execute(f"""
        CREATE TABLE vbo AS
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
        WHERE status IN ({', '.join("'" + s + "'" for s in LIVE_STATUSES)})
    """)
    con.execute("""
        CREATE TABLE pop AS
        SELECT *, count(*) OVER (PARTITION BY pand_id) AS pand_woningen
        FROM vbo
    """)
    con.execute("ALTER TABLE pop ADD COLUMN eengezins BOOLEAN")
    con.execute("UPDATE pop SET eengezins = pand_woningen = 1")

    gem = store.raw / "gemeenten.parquet"
    if gem.exists():
        con.execute(f"""
            CREATE TABLE pop2 AS SELECT p.*, g.gemeente, g.provincie
            FROM pop p LEFT JOIN read_parquet({q(gem)}) g USING (gemeente_code)
        """)
    else:
        progress("let op: geen gemeentenamen (draai 'anonymate ingest gebieden')")
        con.execute("CREATE TABLE pop2 AS SELECT *, gemeente_code AS gemeente, "
                    "NULL::VARCHAR AS provincie FROM pop")

    ep = store.raw / "ep_online.parquet"
    if ep.exists():
        cols = set(pq.read_schema(ep).names)
        extra = [c for c in ("woningtype", "energie_index", "compactheid") if c in cols]
        order = "registratiedatum DESC NULLS LAST" if "registratiedatum" in cols else "1"
        sel = ", ".join(["energielabel"] + extra)
        con.execute(f"""
            CREATE TABLE labels AS
            SELECT vbo_id, {sel} FROM (
                SELECT *, row_number() OVER (PARTITION BY vbo_id ORDER BY {order}) AS rn
                FROM read_parquet({q(ep)}) WHERE vbo_id IS NOT NULL
            ) WHERE rn = 1
        """)
        con.execute("CREATE TABLE pop3 AS SELECT p.*, "
                    + ", ".join(f"l.{c}" for c in ["energielabel"] + extra)
                    + " FROM pop2 p LEFT JOIN labels l USING (vbo_id)")
        missing = {"woningtype", "energie_index", "compactheid"} - set(extra)
        for c in missing:
            con.execute(f"ALTER TABLE pop3 ADD COLUMN {c} "
                        f"{'VARCHAR' if c == 'woningtype' else 'DOUBLE'}")
    else:
        progress("let op: geen energielabels (draai 'anonymate ingest ep-online')")
        con.execute("CREATE TABLE pop3 AS SELECT *, NULL::VARCHAR AS energielabel, "
                    "NULL::VARCHAR AS woningtype, NULL::DOUBLE AS energie_index, "
                    "NULL::DOUBLE AS compactheid FROM pop2")
    # dwellings in a multi-dwelling building without a label type are apartments for sure
    con.execute("UPDATE pop3 SET woningtype = 'appartement' "
                "WHERE woningtype IS NULL AND pand_woningen > 1")

    table = con.execute("SELECT * FROM pop3").fetch_arrow_table()
    progress(f"populatie: {table.num_rows:,} woningen; coördinaten afleiden")
    lat, lon = rd_to_wgs84(table["rd_x"].to_numpy(zero_copy_only=False),
                           table["rd_y"].to_numpy(zero_copy_only=False))
    table = table.append_column("lat", pa.array(lat)).append_column("lon", pa.array(lon))

    st = store.raw / "knmi_stations.parquet"
    if st.exists():
        stations = pd.read_parquet(st)
        table = table.append_column("knmi_station", pa.array(
            _nearest_station(lat, lon, stations), type=pa.string()))
    else:
        progress("let op: geen KNMI-stations (draai 'anonymate ingest knmi')")

    for res in h3_resolutions:
        progress(f"H3-cellen op niveau {res}")
        table = table.append_column(f"h3_r{res}", pa.array(_h3_cells(lat, lon, res),
                                                           type=pa.string()))

    out = store.population_path
    pq.write_table(table, out, compression="zstd")
    m = store.manifest()
    m["population"] = {"rows": table.num_rows, "built": dt.datetime.now().isoformat(timespec="seconds"),
                       "h3_resolutions": list(h3_resolutions)}
    store.manifest_path.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    progress(f"klaar: {out}")
    return out


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
