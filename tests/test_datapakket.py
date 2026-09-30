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
    path = tmp_path / "population.parquet"
    pop.to_parquet(path, index=False)
    return path


def test_the_package_holds_nothing_from_ep_online(tmp_path):
    out = datapakket.make(_population(tmp_path), tmp_path / "pakket",
                          sources={"bag": "2026-08", "3dbag": "v20250903"}, batch_rows=250)
    woningen = pq.read_table(out / "woningen.parquet").to_pandas()
    vorm = pq.read_table(out / "warmtesignatuur.parquet").to_pandas()
    columns = set(woningen.columns) | set(vorm.columns)
    assert not columns & (datapakket.EP_COLUMNS | {"energielabel", "woningtype", "uhi"})
    assert {"sig_nta8800_H", "sig_mwa_tau"} <= set(vorm.columns)
    assert len(woningen) == len(vorm) == 600
    # single-family homes have a signature; the dwelling type came from the building's shape
    single = vorm[woningen["pand_woningen"] == 1]
    assert single["sig_nta8800_H"].notna().mean() > 0.9
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ep_online"].startswith("niet gebruikt")
    assert set(manifest["bestanden"]) == {"woningen.parquet", "warmtesignatuur.parquet"}
    assert all(not s.lower().startswith("ep") for s in manifest["kolommen"].values())


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
