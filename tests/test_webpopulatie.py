"""The web population: copies left out and back as aliases, cut into checked pieces."""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from anonymate.population import Population, Snapshot
from anonymate.webpopulatie import DUBBEL, LIJST, maak, schrijf


def bron(tmp_path, n=1000, labels=False):
    rng = np.random.default_rng(3)
    best = {c: rng.normal(100, 30, n) for c in set(DUBBEL.values())}
    df = pd.DataFrame({"vbo_id__str": [f"{i:016d}" for i in range(n)],
                       "bouwjaar__yr": rng.integers(1900, 2020, n), **best})
    for c, b in DUBBEL.items():
        df[c] = df[b]
    df.loc[3, "sig_best_H__W_K_1"] = np.nan          # NaN must count as equal to NaN
    df.loc[3, "sig_passend_H__W_K_1"] = np.nan
    if labels:
        df["energielabel__cat"] = "A"
    pad = tmp_path / "pop.parquet"
    df.to_parquet(pad, index=False)
    return df, pad


def test_copies_go_and_come_back_as_aliases(tmp_path):
    df, pad = bron(tmp_path)
    doel = tmp_path / "web.parquet"
    info = schrijf(pad, doel, batch_rows=300)
    assert info["rijen"] == len(df) and set(info["weggelaten"]) == set(DUBBEL)
    assert not set(DUBBEL) & set(pd.read_parquet(doel).columns)
    pop = Population.from_parquet(str(doel), Snapshot({"t": "t"}))
    assert set(DUBBEL) <= set(pop.columns)
    terug = pop.con.execute(f"SELECT * FROM {pop.relation} ORDER BY vbo_id__str").fetchdf()
    for c in DUBBEL:
        assert np.allclose(terug[c], df[c], equal_nan=True)


def test_a_differing_copy_or_labels_stop_the_build(tmp_path):
    df, pad = bron(tmp_path)
    df.loc[5, "sig_passend_tau__h"] += 1
    df.to_parquet(pad, index=False)
    with pytest.raises(ValueError, match="niet gelijk"):
        schrijf(pad, tmp_path / "web.parquet")
    _, pad = bron(tmp_path, labels=True)
    with pytest.raises(ValueError, match="energielabels"):
        schrijf(pad, tmp_path / "web.parquet")


def test_pieces_join_back_to_the_named_file(tmp_path):
    _, pad = bron(tmp_path, n=5000)
    uit = tmp_path / "uit"
    lijst = maak(pad, uit, bronnen={"bag": "2026-09"}, stuk=20_000)
    assert json.loads((uit / LIJST).read_text(encoding="utf-8")) == lijst
    assert len(lijst["stukken"]) > 1 and not (uit / lijst["bestand"]).exists()
    geheel = b"".join((uit / s["naam"]).read_bytes() for s in lijst["stukken"])
    assert len(geheel) == lijst["bytes"]
    assert hashlib.sha256(geheel).hexdigest() == lijst["sha256"]
    for s in lijst["stukken"]:
        assert hashlib.sha256((uit / s["naam"]).read_bytes()).hexdigest() == s["sha256"]
    (tmp_path / "terug.parquet").write_bytes(geheel)
    assert len(pd.read_parquet(tmp_path / "terug.parquet")) == 5000
