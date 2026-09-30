import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from anonymate import datapakket, synthetic


def _population(tmp_path, n=600):
    rng = np.random.default_rng(1)
    pop = synthetic.with_places(synthetic.population(n, seed=4))
    pop["pand_woningen"] = np.where(pop["woningtype"] == "appartement", 12, 1)
    pop["aaneengebouwd"] = pop["woningtype"] != "vrijstaand"
    for c, lo, hi in (("opp_grond", 40, 120), ("opp_dak_plat", 0, 30), ("opp_dak_schuin", 40, 140),
                      ("opp_buitenmuur", 60, 220), ("opp_scheidingsmuur", 0, 120)):
        pop[c] = rng.uniform(lo, hi, n).round(1)
    pop["daktype"], pop["bouwlagen"], pop["hoogte"] = "schuin", 2, 8.5
    # label data the population holds, which must not leave in a package
    pop["warmtebehoefte"], pop["compactheid"], pop["nta8800"] = 90.0, 2.1, True
    pop["uhi"] = np.round(rng.uniform(0, 2, n), 2).astype("float32")   # public (RIVM), goes along
    path = tmp_path / "population.parquet"
    pop.to_parquet(path, index=False)
    return path


def test_the_package_holds_nothing_from_ep_online(tmp_path):
    out = datapakket.make(_population(tmp_path), tmp_path / "pakket",
                          sources={"bag": "2026-08", "3dbag": "v20250903"}, batch_rows=250)
    woningen = pq.read_table(out / "woningen.parquet").to_pandas()
    vorm = pq.read_table(out / "warmtesignatuur.parquet").to_pandas()
    columns = set(woningen.columns) | set(vorm.columns)
    assert not columns & (datapakket.EP_COLUMNS | {"energielabel", "woningtype"})
    assert {"sig_nta8800_H", "sig_mwa_tau"} <= set(vorm.columns)
    assert "uhi" in woningen.columns and woningen["uhi"].notna().all()
    assert len(woningen) == len(vorm) == 600
    # single-family homes have a signature; the dwelling type came from the building's shape
    single = vorm[woningen["pand_woningen"] == 1]
    assert single["sig_nta8800_H"].notna().mean() > 0.9
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ep_online"].startswith("niet gebruikt")
    assert set(manifest["bestanden"]) == {"woningen.parquet", "warmtesignatuur.parquet"}
    assert all(not s.lower().startswith("ep") for s in manifest["kolommen"].values())
    assert manifest["kolommen"]["uhi"].startswith("RIVM")


def test_a_package_becomes_a_population_with_or_without_own_ep_online(tmp_path):
    from anonymate.store import Store
    pkg = datapakket.make(_population(tmp_path), tmp_path / "pakket", batch_rows=250)
    store = Store.open(tmp_path / "store")
    store.raw.mkdir(parents=True, exist_ok=True)
    datapakket.install(pkg, store, batch_rows=250)
    pop = pd.read_parquet(store.population_path)
    assert len(pop) == 600
    assert {"knmi_station", "h3_r4", "h3_r8", "postcode4", "sig_H", "woningtype"} <= set(pop.columns)
    assert "energielabel" not in pop.columns
    assert "uhi" in pop.columns and pop["uhi"].notna().all()    # the heat island comes along
    assert set(pop["woningtype_bron"].dropna()) == {"vorm"}
    assert pop.loc[pop["pand_woningen"] == 1, "sig_H"].notna().mean() > 0.9
    # the user's own EP-online (route 4): labels joined, type from the label where known
    ids = pop["vbo_id"].head(50)
    pd.DataFrame({"vbo_id": ids, "energielabel": "C", "woningtype": "hoekwoning",
                  "warmtebehoefte": 95.0}).to_parquet(store.raw / "ep_online.parquet", index=False)
    datapakket.install(pkg, store, batch_rows=250)
    pop = pd.read_parquet(store.population_path)
    first = pop[pop["vbo_id"].isin(ids)]
    assert (first["energielabel"] == "C").all() and (first["woningtype_bron"] == "ep-online").all()
    assert store.manifest()["sources"]["datapakket"]["ep_online"] == "eigen opslag"


def test_gaps_in_a_later_batch_keep_one_schema(tmp_path):
    """A whole-number column (oppervlakte) without gaps in the first batch and with gaps in a
    later one: pandas makes it int there and float here; the package must still be one file
    (the first run on GitHub stopped at 500,000 dwellings on exactly this)."""
    import pyarrow as pa
    path = _population(tmp_path)
    table = pq.read_table(path)
    area = table.column("oppervlakte").to_pylist()
    area[400:410] = [None] * 10
    i = table.schema.get_field_index("oppervlakte")
    table = table.set_column(i, pa.field("oppervlakte", pa.int64()), pa.array(area, pa.int64()))
    pq.write_table(table, path)
    out = datapakket.make(path, tmp_path / "pakket", batch_rows=250)
    woningen = pq.read_table(out / "woningen.parquet")
    assert woningen.num_rows == 600
    assert woningen.schema.field("oppervlakte").type == pa.int64()
    assert woningen.column("oppervlakte").null_count == 10


def test_three_significant_digits():
    x = datapakket._three_digits(np.array([123.456, 0.012345, 98765.0, 0.0, np.nan]))
    assert list(x[:4]) == [123.0, 0.0123, 98800.0, 0.0] and np.isnan(x[4])


def _published(tmp_path):
    pkg = datapakket.make(_population(tmp_path), tmp_path / "pakket", batch_rows=250)
    pub = tmp_path / "publicatie"
    manifest = datapakket.publish(pkg, pub)
    return pub, manifest


def test_the_published_zip_is_deterministic_and_installs(tmp_path):
    from anonymate.store import Store
    pub, manifest = _published(tmp_path)
    assert {p.name for p in pub.iterdir()} == {"anonymate-datapakket.zip", "manifest.json"}
    assert manifest["zip"]["sha256"] == datapakket.sha256_file(pub / "anonymate-datapakket.zip")
    again = datapakket.zip_package(tmp_path / "pakket", tmp_path / "nog-eens.zip")
    assert datapakket.sha256_file(again) == manifest["zip"]["sha256"]
    datapakket.verify(pub / "anonymate-datapakket.zip", pub / "manifest.json")
    store = Store.open(tmp_path / "store")
    datapakket.install(pub / "anonymate-datapakket.zip", store, batch_rows=250)
    assert len(pd.read_parquet(store.population_path)) == 600


def test_a_damaged_zip_or_manifest_is_refused(tmp_path):
    import pytest
    pub, _ = _published(tmp_path)
    z = pub / "anonymate-datapakket.zip"
    bad = tmp_path / "kapot.zip"
    bad.write_bytes(z.read_bytes()[:-1] + b"x")
    with pytest.raises(ValueError, match="sha256"):
        datapakket.verify(bad, pub / "manifest.json")
    plain = tmp_path / "zonder.json"
    plain.write_text(json.dumps({"bestanden": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="geen sha256"):
        datapakket.verify(z, plain)


def test_ingest_pakket_without_file_downloads_and_installs(tmp_path, monkeypatch):
    import argparse
    from anonymate import cli, store as st
    pub, _ = _published(tmp_path)
    seen = []

    def fake_fetch(url, **kw):
        seen.append(url)
        return (pub / "manifest.json").read_bytes()

    def fake_download(url, dest, **kw):
        seen.append(url)
        dest.write_bytes((pub / "anonymate-datapakket.zip").read_bytes())
        return dest

    monkeypatch.setattr(st, "fetch", fake_fetch)
    monkeypatch.setattr(st, "download", fake_download)
    monkeypatch.setenv("ANONYMATE_HOME", str(tmp_path / "home"))
    args = argparse.Namespace(source="pakket", file=None, home=None, downloads=None,
                              jaar=None, max_tegels=None, tegels_weggooien=False)
    cli.cmd_ingest(args)
    assert seen == [st.DATAPAKKET_MANIFEST_URL, st.DATAPAKKET_URL]
    assert (tmp_path / "home" / "population.parquet").exists()


def test_a_download_that_does_not_match_the_manifest_is_removed(tmp_path, monkeypatch):
    import pytest
    from anonymate import store as st
    pub, _ = _published(tmp_path)
    monkeypatch.setattr(st, "fetch", lambda url, **kw: (pub / "manifest.json").read_bytes())
    monkeypatch.setattr(st, "download", lambda url, dest, **kw: (dest.write_bytes(b"nee"), dest)[1])
    with pytest.raises(ValueError):
        st.download_datapakket(st.Store.open(tmp_path / "s"))
    assert not (tmp_path / "s" / "downloads" / "anonymate-datapakket.zip").exists()
