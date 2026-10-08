"""The population for the web version, served from anonymate.nl (fase 3 of docs/werk/webversie.md).

The web version needs one Parquet file with every dwelling of the Netherlands, without
EP-online: BAG, 3D-BAG, CBS and KNMI, and the signatures derived from those alone (the
population that :func:`anonymate.datapakket.install` makes from a data package when there is no
``raw/ep_online.parquet``). EP-online never comes from the site: the user adds their own
totaalbestand in the browser (:func:`anonymate.web.add_eponline`).

To keep the download small, columns that are exact copies of another column in a population
without labels are left out (:data:`DUBBEL`: without a label, ``passend`` *is* ``best``) and named
in the file's metadata; :meth:`anonymate.population.Population.from_parquet` puts them back as
aliases, so every query and the EP-online supplement see the same columns as before. The copies
are checked while writing: a difference stops the build.

The file is cut into pieces below the 100 MB per file of GitHub Pages, and ``populatie.json``
names each piece with its size and SHA-256, and the whole file's. The page downloads every piece
(always the whole country: fetching per region would tell the server which region someone looks
at), checks it, and keeps the file in the browser's own storage (OPFS).

    python -m anonymate.webpopulatie <population.parquet> <map> [--bronnen manifest.json]
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# column left out -> the column it equals in a population without labels
DUBBEL = {
    "sig_passend_H__W_K_1": "sig_best_H__W_K_1",
    "sig_passend_tau__h": "sig_best_tau__h",
    "sig_passend_Asol__m2": "sig_best_Asol__m2",
    "sig_passend_Ainf__cm2": "sig_best_Ainf__cm2",
    "sig_passend_cbag_tau__h": "sig_best_tau__h",
    "sig_passend_cbag_Ainf__cm2": "sig_best_Ainf__cm2",
}
# key in the Parquet metadata: {"left out": "equal to"}, read by Population.from_parquet
ALIASSEN_SLEUTEL = "anonymate.aliassen"
BESTAND = "populatie.parquet"
LIJST = "populatie.json"
STUK = 95 * 1000 * 1000          # bytes per piece: below the 100 MB of GitHub Pages
ZSTD_NIVEAU = 9                  # once a month, downloaded by everyone: worth the time


def _gelijk(a, b) -> bool:
    """Whether two Arrow columns hold the same values, nulls and NaN included."""
    x = a.to_numpy(zero_copy_only=False)
    y = b.to_numpy(zero_copy_only=False)
    if x.dtype.kind == "f" or y.dtype.kind == "f":
        x, y = x.astype(float), y.astype(float)
        return bool(np.array_equal(x, y, equal_nan=True))
    return bool((x == y).all())


def schrijf(bron: str | Path, doel: str | Path, *, batch_rows: int = 250_000,
            niveau: int = ZSTD_NIVEAU, voortgang=lambda m: None) -> dict:
    """Write the web population from the label-free population ``bron`` to ``doel``: without the
    columns of :data:`DUBBEL` (checked equal first), with their names in the metadata. Returns
    {"rijen", "weggelaten"}. Raises ValueError when the population has labels or a copy differs."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    src = pq.ParquetFile(bron)
    namen = src.schema_arrow.names
    if "energielabel__cat" in namen:
        raise ValueError("deze populatie heeft energielabels; de webversie krijgt alleen een "
                         "populatie zonder EP-online (datapakket.install zonder ep_online)")
    weg = {c: b for c, b in DUBBEL.items() if c in namen and b in namen}
    houden = [c for c in namen if c not in weg]
    schema = pa.schema([src.schema_arrow.field(c) for c in houden],
                       metadata={ALIASSEN_SLEUTEL: json.dumps(weg)})
    doel = Path(doel)
    deel = doel.with_suffix(".parquet.part")
    n = 0
    with pq.ParquetWriter(deel, schema, compression="zstd", compression_level=niveau) as w:
        for batch in src.iter_batches(batch_size=batch_rows):
            for c, b in weg.items():
                if not _gelijk(batch.column(c), batch.column(b)):
                    raise ValueError(f"{c} is niet gelijk aan {b}: kan niet als alias weg")
            w.write_table(pa.Table.from_batches([batch]).select(houden))
            n += batch.num_rows
            voortgang(f"webpopulatie: {n:,} woningen")
    src.close()
    deel.replace(doel)
    return {"rijen": n, "weggelaten": weg}


def _sha256(pad: Path) -> str:
    h = hashlib.sha256()
    with open(pad, "rb") as f:
        for blok in iter(lambda: f.read(1 << 20), b""):
            h.update(blok)
    return h.hexdigest()


def knip(bestand: str | Path, map_: str | Path, stuk: int = STUK) -> list[dict]:
    """Cut ``bestand`` into ``<naam>.000``, ``.001``, … in ``map_``; returns name, size and
    SHA-256 per piece."""
    bestand, map_ = Path(bestand), Path(map_)
    stukken = []
    with open(bestand, "rb") as f:
        i = 0
        while True:
            data = f.read(stuk)
            if not data:
                break
            naam = f"{bestand.name}.{i:03d}"
            (map_ / naam).write_bytes(data)
            stukken.append({"naam": naam, "bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest()})
            i += 1
    return stukken


def maak(bron: str | Path, map_: str | Path, *, bronnen: dict | None = None,
         stuk: int = STUK, niveau: int = ZSTD_NIVEAU, voortgang=lambda m: None) -> dict:
    """The web population from ``bron`` in pieces in ``map_``, with ``populatie.json``; the
    whole file is not kept. ``bronnen``: source -> version (from the data package's manifest),
    shown in the report as the snapshot."""
    map_ = Path(map_)
    map_.mkdir(parents=True, exist_ok=True)
    geheel = map_ / BESTAND
    info = schrijf(bron, geheel, niveau=niveau, voortgang=voortgang)
    lijst = {
        "bestand": BESTAND,
        "bytes": geheel.stat().st_size,
        "sha256": _sha256(geheel),
        "rijen": info["rijen"],
        "weggelaten": info["weggelaten"],
        "bronnen": dict(bronnen or {}),
        "gemaakt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stukken": knip(geheel, map_, stuk),
    }
    geheel.unlink()
    (map_ / LIJST).write_text(json.dumps(lijst, indent=1, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    return lijst


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m anonymate.webpopulatie", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("populatie", help="populatie zonder EP-online (Parquet)")
    p.add_argument("map", help="uitvoermap voor de stukken en populatie.json")
    p.add_argument("--bronnen", help="manifest.json van het datapakket (voor de bronversies)")
    p.add_argument("--niveau", type=int, default=ZSTD_NIVEAU, help="zstd-niveau")
    args = p.parse_args(argv)
    bronnen = None
    if args.bronnen:
        m = json.loads(Path(args.bronnen).read_text(encoding="utf-8"))
        bronnen = {**(m.get("bronnen") or {}), "datapakket": m.get("gemaakt", "")}
    lijst = maak(args.populatie, args.map, bronnen=bronnen, niveau=args.niveau,
                 voortgang=lambda m: print(m, flush=True))
    print(f"{len(lijst['stukken'])} stukken, {lijst['bytes'] / 1e6:.0f} MB, "
          f"{lijst['rijen']:,} woningen; sha256 {lijst['sha256'][:16]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
