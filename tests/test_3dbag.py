"""3D-BAG ingest on synthetic tiles with the real layer schema. No network."""
import gzip
import hashlib
import sqlite3

import pandas as pd
import pytest

from anonymate import store as st


def make_tile(path, panden):
    """panden: list of (pand_id, dak_type, bouwlagen, maaiveld, scheidingsmuur, h70_parts)."""
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE pand (fid INTEGER PRIMARY KEY, geom BLOB, identificatie TEXT, "
                "b3_dak_type TEXT, b3_bouwlagen REAL, b3_h_maaiveld REAL, "
                "b3_opp_scheidingsmuur REAL, b3_volume_lod22 REAL, b3_opp_grond REAL, "
                "b3_opp_dak_plat REAL, b3_opp_dak_schuin REAL, b3_opp_buitenmuur REAL)")
    con.execute("CREATE TABLE lod22_2d (fid INTEGER PRIMARY KEY, geom BLOB, identificatie TEXT, "
                "b3_h_70p REAL)")
    for pid, dak, lagen, maaiveld, scheiding, parts in panden:
        ident = f"NL.IMBAG.Pand.{pid}"
        con.execute("INSERT INTO pand VALUES (NULL, NULL, ?, ?, ?, ?, ?, 400, 60, 0, 70, 180)",
                    (ident, dak, lagen, maaiveld, scheiding))
        for h in parts:
            con.execute("INSERT INTO lod22_2d VALUES (NULL, NULL, ?, ?)", (ident, h))
    con.commit()
    con.close()


TILE_A = [("0193100000000001", "slanted", 2.0, 1.0, 40.0, [8.0, 9.5]),
          ("0193100000000002", "horizontal", None, 1.0, 0.0, [4.0])]
TILE_B = [("0193100000000003", "multiple horizontal", 5.0, -2.0, None, [16.0]),
          ("0193100000000002", "horizontal", None, 1.0, 0.0, [4.0])]  # also on tile A


def test_read_tile(tmp_path):
    make_tile(tmp_path / "a.gpkg", TILE_A)
    df = st.read_3dbag_gpkg(tmp_path / "a.gpkg").set_index("pand_id")
    one = df.loc["0193100000000001"]
    assert (one.daktype, one.bouwlagen, one.hoogte, bool(one.aaneengebouwd)) == \
        ("schuin", 2, 8.5, True)  # highest part 9.5 minus ground level 1.0
    assert (one.opp_grond, one.opp_buitenmuur, one.opp_scheidingsmuur) == (60, 180, 40)
    two = df.loc["0193100000000002"]
    assert two.daktype == "plat" and pd.isna(two.bouwlagen) and not two.aaneengebouwd


def test_ingest_from_folder_dedupes(tmp_path):
    folder = tmp_path / "tiles"
    folder.mkdir()
    make_tile(folder / "a.gpkg", TILE_A)
    make_tile(tmp_path / "b.gpkg", TILE_B)
    (folder / "b.gpkg.gz").write_bytes(gzip.compress((tmp_path / "b.gpkg").read_bytes()))
    s = st.Store.open(tmp_path / "home", tmp_path / "nas")
    out = st.ingest_3dbag(s, folder)
    df = pd.read_parquet(out)
    assert sorted(df.pand_id) == ["0193100000000001", "0193100000000002", "0193100000000003"]
    three = df.set_index("pand_id").loc["0193100000000003"]
    assert three.daktype == "plat_meerdere" and three.hoogte == 18.0 \
        and pd.isna(three.aaneengebouwd)


def _tiles(tmp_path):
    blobs = {}
    for name, panden in (("8/1/1", TILE_A), ("8/1/2", TILE_B)):
        g = tmp_path / (name.replace("/", "-") + ".gpkg")
        make_tile(g, panden)
        blobs[f"https://example.org/{name}.gpkg.gz"] = gzip.compress(g.read_bytes())
    index = pd.DataFrame({"tile_id": ["8/1/1", "8/1/2"], "gpkg_download": list(blobs),
                          "gpkg_sha256": [hashlib.sha256(b).hexdigest() for b in blobs.values()]})
    return index, blobs


def test_ingest_tiles_keeps_originals_in_downloads_and_resumes(tmp_path):
    index, blobs = _tiles(tmp_path)
    fetched = []

    def fetcher(url, **kw):
        fetched.append(url)
        return blobs[url]

    s = st.Store.open(tmp_path / "home", tmp_path / "nas")
    st.ingest_3dbag(s, tiles=index, fetcher=fetcher, part_tiles=1, max_tiles=1)
    assert s.manifest()["sources"]["3dbag"]["version"].endswith("(deels)")
    st.ingest_3dbag(s, tiles=index, fetcher=fetcher, part_tiles=1)
    assert len(fetched) == 2  # the first tile was not fetched again
    kept = sorted(p.name for p in (tmp_path / "nas" / "3dbag" / st.THREEDBAG_VERSION).iterdir())
    assert kept == ["8-1-1.gpkg.gz", "8-1-2.gpkg.gz"]
    assert pd.read_parquet(s.raw / "3dbag.parquet").pand_id.nunique() == 3
    assert s.manifest()["sources"]["3dbag"]["version"] == st.THREEDBAG_VERSION


def test_bad_checksum_is_refused(tmp_path):
    index, blobs = _tiles(tmp_path)
    index.loc[0, "gpkg_sha256"] = "0" * 64
    s = st.Store.open(tmp_path / "home", tmp_path / "nas")
    with pytest.raises(RuntimeError, match="sha256"):
        st.ingest_3dbag(s, tiles=index, fetcher=lambda url, **kw: blobs[url])
