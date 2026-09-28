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


def test_three_significant_digits():
    x = datapakket._three_digits(np.array([123.456, 0.012345, 98765.0, 0.0, np.nan]))
    assert list(x[:4]) == [123.0, 0.0123, 98800.0, 0.0] and np.isnan(x[4])
