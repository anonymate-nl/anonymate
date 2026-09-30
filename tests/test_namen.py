"""De naamconventie physiquant__unit: de tabel in code en de variabelenlijst in docs."""
import re
from pathlib import Path

import duckdb
import pandas as pd

from anonymate import namen

DOC = Path(__file__).parents[1] / "docs" / "variabelen.md"


def test_nieuwe_namen_hebben_een_eenheid():
    for oud, nieuw in namen.OUD_NAAR_NIEUW.items():
        assert nieuw.startswith(oud) and "__" in nieuw, (oud, nieuw)
        assert nieuw.count("__") == 1
    assert len(set(namen.OUD_NAAR_NIEUW.values())) == len(namen.OUD_NAAR_NIEUW)


def test_variabelenlijst_en_code_komen_overeen():
    tekst = DOC.read_text(encoding="utf-8")
    kolommen = set(re.findall(r"`([A-Za-z0-9_<>]+__[A-Za-z0-9_]+)`", tekst))
    for oud, nieuw in namen.OUD_NAAR_NIEUW.items():
        if nieuw.startswith("sig_") or re.match(r"h3_r\d__str", nieuw):
            continue
        assert nieuw in kolommen, f"{nieuw} staat niet in docs/variabelen.md"
        assert f"`{oud}`" in tekst
    for o in namen.UITVOER_EENHEID:
        assert namen.sig_kolom(o) in tekst or f"sig_{o}__" in tekst


def test_naar_nieuw_laat_nieuwe_en_vreemde_kolommen_staan():
    df = pd.DataFrame({"bouwjaar": [1], "oppervlakte__m2": [2], "eigen": [3], "lat": [4]})
    assert list(namen.naar_nieuw(df).columns) == ["bouwjaar__yr", "oppervlakte__m2", "eigen",
                                                  "lat__degN"]
    assert namen.is_oud(df.columns)
    assert not namen.is_oud(["bouwjaar__yr", "eigen"])


def test_parquet_relatie_geeft_nieuwe_namen_bij_oud_bestand(tmp_path):
    p = tmp_path / "oud.parquet"
    pd.DataFrame({"bouwjaar": [1965], "sig_H": [1.5], "eigen": [1]}).to_parquet(p)
    con = duckdb.connect()
    cols = [r[0] for r in con.execute(
        f"DESCRIBE SELECT * FROM {namen.parquet_relatie(p)}").fetchall()]
    assert cols == ["bouwjaar__yr", "sig_H__W_K_1", "eigen"]
    q = tmp_path / "nieuw.parquet"
    pd.DataFrame({"bouwjaar__yr": [1965]}).to_parquet(q)
    assert namen.parquet_relatie(q).startswith("read_parquet(")
