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
def test_ingest_uhi_then_build_puts_it_in_the_population(store, tmp_path):
    tif = tmp_path / "uhi.tif"
    data = _write_tif(tif)
    messages = []
    out = st.ingest_uhi(store, tif, progress=messages.append)
    table = pd.read_parquet(out)
    assert list(table.columns) == ["vbo_id", "uhi"] and table["uhi"].dtype == "float32"
    assert any("zonder" in m for m in messages)
    src = store.manifest()["sources"]["uhi"]
    assert src["version"] == st.UHI_VERSION and src["rows"] == len(table)
    st.build(store, h3_resolutions=(4,), batch_rows=7)
    pop = pd.read_parquet(store.population_path)
    assert "uhi" in pop.columns
    zwolle = pop[pop["gemeente"] == "Zwolle"]
    assert zwolle["uhi"].notna().all() and (zwolle["uhi"].round(2) == np.round(data[300, 300], 2)).all()
    assert pop.loc[pop["gemeente"] == "Deventer", "uhi"].isna().all()    # outside the raster


@needs_rasterio
def test_a_population_without_the_uhi_table_has_no_uhi_column(store):
    st.build(store, h3_resolutions=(4,), batch_rows=50)
    assert "uhi" not in pd.read_parquet(store.population_path).columns


@needs_rasterio
def test_a_table_that_covers_the_bag_is_kept_and_a_stale_one_is_recomputed(store, tmp_path):
    tif = tmp_path / "uhi.tif"
    _write_tif(tif)
    st.ingest_uhi(store, tif)
    assert st.uhi_coverage(store) == 1.0
    messages = []
    st.ingest_uhi(store, only_if_needed=True, progress=messages.append)   # no raster needed
    assert any("niets te doen" in m for m in messages)
    assert "bronnen-cache" in store.manifest()["sources"]["uhi"]["version"]
    # new dwellings in the BAG that the table does not know: recompute
    table = pd.read_parquet(store.raw / "uhi.parquet")
    table.iloc[: len(table) // 2].to_parquet(store.raw / "uhi.parquet", index=False)
    assert st.uhi_coverage(store) < st.UHI_COVERAGE_SHARE
    with pytest.raises(FileNotFoundError):
        st.ingest_uhi(store, tmp_path / "bestaat-niet.zip", only_if_needed=True)


@needs_rasterio
def test_the_rivm_zip_is_unpacked_and_a_small_zip_is_refused(store, tmp_path):
    tif = tmp_path / st.UHI_TIF
    _write_tif(tif)
    z = tmp_path / "uhi.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.write(tif, tif.name)
    with pytest.raises(RuntimeError, match="te klein"):
        st.ingest_uhi(store, z)                     # the real map is ~2 GB
    st.ingest_uhi(store, z, min_zip_bytes=1)
    assert pd.read_parquet(store.raw / "uhi.parquet")["uhi"].notna().any()
    assert z.exists()                               # the user's own file stays


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
    store.ingest_uhi(store.Store.open(sys.argv[1]), None)
except FileNotFoundError:
    raise SystemExit("verwacht de melding over rasterio, niet die over de BAG")
except RuntimeError as e:
    assert "anonymate[uhi]" in str(e), e
    print("ok")
"""
    r = subprocess.run([sys.executable, "-c", code, str(tmp_path / "leeg")],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr
