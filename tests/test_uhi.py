"""The urban heat island (RIVM raster) per dwelling: sampling, ingest, build, and the optional
dependency. A tiny GeoTIFF in EPSG:28992 is written in the test; no network."""
import json
import subprocess
import sys
import zipfile

import numpy as np
import pandas as pd
import pytest

from anonymate import store as st
from tests.test_store import GEBIEDEN, KNMI, make_gpkg

try:
    import rasterio
except ImportError:      # the optional extra anonymate[uhi]
    rasterio = None
needs_rasterio = pytest.mark.skipif(rasterio is None, reason="rasterio (anonymate[uhi]) ontbreekt")

X0, Y0 = 200000.0, 506000.0        # top left corner; 10 m cells; covers Zwolle, not Deventer
W, H = 500, 600                    # x 200000..205000, y 500000..506000


def _write_tif(path, crs="EPSG:28992"):
    from rasterio.transform import from_origin
    col, row = np.meshgrid(np.arange(W), np.arange(H))
    data = (col * 0.002 + row * 0.001).astype("float32")      # 0 to ~1.6, unique per cell
    data[300, 301] = -9999                                    # nodata under one point
    with rasterio.open(path, "w", driver="GTiff", width=W, height=H, count=1, dtype="float32",
                       crs=crs, transform=from_origin(X0, Y0, 10, 10), nodata=-9999,
                       tiled=True, blockxsize=256, blockysize=256) as dst:
        dst.write(data, 1)
    return data


@needs_rasterio
def test_sampling_at_points_in_windows(tmp_path):
    tif = tmp_path / "uhi.tif"
    data = _write_tif(tif)
    # cell centres and cell edges; a point on the nodata cell; two outside the raster; a NaN
    x = np.array([203005.0, 200000.0, 204999.9, 203015.0, 199990.0, 203005.0, np.nan])
    y = np.array([503005.0, 505999.9, 500000.1, 502995.0, 503005.0, 506000.1, 503005.0])
    got = st.sample_raster(tif, x, y, block=64)
    want = lambda r, c: np.round(data[r, c], 2)  # noqa: E731
    assert got[0] == want(299, 300) and got[1] == want(0, 0) and got[2] == want(599, 499)
    assert np.isnan(got[3])                        # nodata
    assert np.isnan(got[4]) and np.isnan(got[5]) and np.isnan(got[6])
    # the window size does not matter
    assert np.array_equal(got, st.sample_raster(tif, x, y, block=2048), equal_nan=True)


@needs_rasterio
def test_a_raster_that_is_not_rd_is_refused(tmp_path):
    tif = tmp_path / "wgs.tif"
    _write_tif(tif, crs="EPSG:4326")
    with pytest.raises(ValueError, match="28992"):
        st.sample_raster(tif, [5.0], [52.0])


@pytest.fixture()
def store(tmp_path):
    gpkg = tmp_path / "bag-light.gpkg"
    make_gpkg(gpkg)
    s = st.Store.open(tmp_path / "home")
    st.ingest_bag(s, gpkg)
    st.ingest_gebieden(s, fetcher=lambda url, **kw: json.dumps(GEBIEDEN).encode())
    st.ingest_knmi(s, fetcher=lambda url, **kw: KNMI.encode())
    return s


@needs_rasterio
def test_raster_ingest_then_build_puts_it_in_the_population_per_dwelling(store, tmp_path):
    tif = tmp_path / "uhi.tif"
    data = _write_tif(tif)
    messages = []
    out = st.ingest_uhi_raster(store, tif, progress=messages.append)
    assert out.name == "uhi_woning.parquet"
    table = pd.read_parquet(out)
    assert list(table.columns) == ["vbo_id", "uhi"] and table["uhi"].dtype == "float32"
    assert any("zonder" in m for m in messages)
    src = store.manifest()["sources"]["uhi"]
    assert src["version"].endswith("per woning") and src["rows"] == len(table)
    st.build(store, h3_resolutions=(4,), batch_rows=7)
    pop = pd.read_parquet(store.population_path)
    zwolle = pop[pop["gemeente"] == "Zwolle"]
    assert zwolle["uhi"].notna().all() and (zwolle["uhi"].round(2) == np.round(data[300, 300], 2)).all()
    assert pop.loc[pop["gemeente"] == "Deventer", "uhi"].isna().all()    # outside the raster


@needs_rasterio
def test_the_rivm_zip_is_unpacked_and_a_small_zip_is_refused(store, tmp_path):
    tif = tmp_path / st.UHI_TIF
    _write_tif(tif)
    z = tmp_path / "uhi.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.write(tif, tif.name)
    with pytest.raises(RuntimeError, match="te klein"):
        st.ingest_uhi_raster(store, z)              # the real map is ~2 GB
    st.ingest_uhi_raster(store, z, min_zip_bytes=1)
    assert pd.read_parquet(store.raw / "uhi_woning.parquet")["uhi"].notna().any()
    assert z.exists()                               # the user's own file stays


PC6 = pd.DataFrame({"pc6": ["8011AB", "8011 ac", "8012CD"], "uhi__degC": [0.9, 1.4, 0.2],
                    "n_adressen": [15, 1, 6]})    # 7411AA (Deventer) is not in the table


def _pc6_file(tmp_path):
    path = tmp_path / "uhi-pc6.parquet"
    PC6.astype({"uhi__degC": "float32"}).to_parquet(path, index=False)
    return path


def test_a_population_without_any_uhi_table_has_no_uhi_column(store):
    st.build(store, h3_resolutions=(4,), batch_rows=50)
    assert "uhi" not in pd.read_parquet(store.population_path).columns


def test_ingest_uhi_from_a_local_copy_joins_on_the_postcode(store, tmp_path):
    messages = []
    out = st.ingest_uhi(store, _pc6_file(tmp_path))
    assert out == store.raw / "uhi.parquet"
    src = store.manifest()["sources"]["uhi"]
    assert src["version"] == "RIVM 01-06-2022 v2, per postcode" and src["rows"] == 3
    assert len(src["sha256"]) == 64
    st.build(store, h3_resolutions=(4,), batch_rows=7, progress=messages.append)
    pop = pd.read_parquet(store.population_path)
    assert pop["uhi"].dtype == "float32"
    by = pop.groupby("postcode6")["uhi"].first()
    assert by["8011AB"] == pytest.approx(0.9) and by["8011AC"] == pytest.approx(1.4)  # 'ac ' normalised
    assert by["8012CD"] == pytest.approx(0.2) and pd.isna(by["7411AA"])
    assert any("hitte-eiland: 19 woningen met een waarde, 4 zonder" in m for m in messages)


def test_ingest_uhi_downloads_the_published_table(store, tmp_path, monkeypatch):
    src = _pc6_file(tmp_path)
    seen = []
    monkeypatch.setattr(st, "fetch", lambda url, **kw: seen.append(url) or b'{"artefact": "x"}')

    def fake_download(url, dest, **kw):
        seen.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        return dest

    monkeypatch.setattr(st, "download", fake_download)
    st.ingest_uhi(store)
    assert seen == [st.UHI_PC6_HERKOMST_URL, st.UHI_PC6_URL]
    assert st.UHI_PC6_URL.endswith("/releases/download/bronnen-cache/uhi-pc6-rivm-20220601-v2.parquet")
    assert (store.raw / "uhi.herkomst.json").exists()


def test_a_download_that_does_not_match_the_provenance_is_refused(store, tmp_path, monkeypatch):
    src = _pc6_file(tmp_path)
    monkeypatch.setattr(st, "fetch", lambda url, **kw: b'{"sha256": "' + b"0" * 64 + b'"}')
    monkeypatch.setattr(st, "download", lambda url, dest, **kw: (
        dest.parent.mkdir(parents=True, exist_ok=True), dest.write_bytes(src.read_bytes()), dest)[2])
    with pytest.raises(ValueError, match="sha256"):
        st.ingest_uhi(store)
    assert not (store.raw / "uhi.parquet").exists()


def test_a_table_without_a_uhi_column_is_refused(store, tmp_path):
    bad = tmp_path / "bad.parquet"
    pd.DataFrame({"pc6": ["8011AB"], "waarde": [1.0]}).to_parquet(bad, index=False)
    with pytest.raises(ValueError, match="uhi__degC"):
        st.ingest_uhi(store, bad)


def test_the_core_and_the_web_version_do_not_need_rasterio(tmp_path):
    code = r"""
import importlib.abc, sys

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "rasterio":
            raise ImportError("rasterio is niet beschikbaar (test)")

sys.meta_path.insert(0, Blocker())
import anonymate, anonymate.cli, anonymate.datapakket, anonymate.stappen, anonymate.web
from anonymate import store
assert "rasterio" not in sys.modules
try:
    store.ingest_uhi_raster(store.Store.open(sys.argv[1]), None)
except FileNotFoundError:
    raise SystemExit("verwacht de melding over rasterio, niet die over de BAG")
except RuntimeError as e:
    assert "anonymate[uhi]" in str(e), e
    print("ok")
"""
    r = subprocess.run([sys.executable, "-c", code, str(tmp_path / "leeg")],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr
