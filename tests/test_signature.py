"""Baseline heat performance signature: made-up dwellings with hand-checkable numbers."""
import pandas as pd
import pytest

from anonymate import CATALOGUE, Population, QidColumn, Threshold, assess
from anonymate.signature import baseline, infer_dwelling_type


def home(**kw):
    row = dict(bouwjaar=2000, oppervlakte=120, woningtype="vrijstaand", pand_woningen=1,
               aaneengebouwd=False, opp_buitenmuur=200.0, opp_grond=80.0, opp_dak_plat=0.0,
               opp_dak_schuin=100.0, opp_scheidingsmuur=0.0)
    row.update(kw)
    return row


def test_hand_calculation_detached_2000():
    s = baseline(pd.DataFrame([home()])).iloc[0]
    # period 92-05, detached reference dwelling: windows 21.41% of 200 m², door 10.09 m², Uw 2.9
    windows, door = 200 * 0.2141, 10.09
    walls = 200 - windows - door
    u = 1 / (2.5 + 0.13 + 0.04)          # Rc 2.5 wall
    u_floor = 1 / (2.5 + 0.17)
    u_roof = 1 / (2.5 + 0.10 + 0.04)
    H = walls * u + windows * 2.9 + door * 1.4925 + 80 * 0.7 * u_floor + 100 * u_roof
    assert s.sig_H == pytest.approx(H, abs=0.01)
    assert s.sig_C == pytest.approx(450 * 1000 / 3600 * 120)   # 15000 Wh/K
    assert s.sig_tau == pytest.approx(15000 / H, abs=0.01)
    assert s.sig_Ainf == 108


def test_signature_follows_envelope_and_period():
    df = pd.DataFrame([home(), home(opp_buitenmuur=260.0), home(bouwjaar=1970),
                       home(oppervlakte=150)])
    s = baseline(df)
    assert s.sig_H[1] > s.sig_H[0]            # more wall, more loss
    assert s.sig_H[2] > 2 * s.sig_H[0]        # poorly insulated period
    assert s.sig_C[3] == pytest.approx(s.sig_C[0] * 150 / 120)
    assert s.sig_Asol[1] > s.sig_Asol[0]


def test_only_single_family_homes():
    s = baseline(pd.DataFrame([home(pand_woningen=12), home(opp_buitenmuur=None)]))
    assert s.isna().all().all()


def test_infer_dwelling_type():
    t = infer_dwelling_type(pd.Series([False, True, True, None]),
                            pd.Series([0.0, 30.0, 150.0, 60.0]),
                            pd.Series([200.0, 180.0, 100.0, 120.0]))
    assert list(t) == ["vrijstaand", "twee_onder_een_kap", "tussenwoning", "twee_onder_een_kap"]


def test_published_signature_is_a_quasi_identifier():
    # the rainbow table: a rounded H published for a home is counted against the computed H
    # of every home; tolerance = half the rounding step
    pop = pd.DataFrame([home(opp_buitenmuur=200.0 + i) for i in range(40)])
    pop = pd.concat([pop, baseline(pop)], axis=1)
    population = Population.from_dataframe(pop)
    h = pop.sig_H.iloc[20]
    rounded_10 = round(h / 10) * 10
    ds = pd.DataFrame({"H": [rounded_10]})
    exact = assess(ds, [QidColumn("H", CATALOGUE["warmteverlies"])], population,
                   Threshold(0.33))
    rounded = assess(ds, [QidColumn("H", CATALOGUE["warmteverlies"], tolerance=5)], population,
                     Threshold(0.33))
    assert exact.records["k_populatie"].iloc[0] <= 1
    assert rounded.records["k_populatie"].iloc[0] > 5


def test_mwa_variant():
    df = pd.DataFrame([home(), home(bouwjaar=1970)])
    nta = baseline(df)
    mwa = baseline(df, method="mwa")
    assert (mwa.sig_H < nta.sig_H).all()                  # less conservative: lower loss
    assert list(mwa.sig_C) == list(nta.sig_C)             # thermal mass unchanged
    assert (mwa.sig_Ainf == 54).all()
    # the Rc surcharge matters most for poorly insulated homes
    assert (nta.sig_H[1] - mwa.sig_H[1]) / nta.sig_H[1] > (nta.sig_H[0] - mwa.sig_H[0]) / nta.sig_H[0]
    # hand check of the wall U for 2000: Rc 2.5 + 0.15
    windows, door = 200 * 0.2141, 10.09
    walls = 200 - windows - door
    H = (walls / (2.65 + 0.17) + windows * 2.9 * 0.9 + door * 1.4925 * 0.9
         + 80 * 0.7 * 0.7 / (2.65 + 0.17) + 100 / (2.65 + 0.14))
    assert mwa.sig_H[0] == pytest.approx(H, abs=0.01)
    with pytest.raises(ValueError):
        baseline(df, method="onbekend")


# --- method "best": current state, calibrated with the registered label ------------------------

from anonymate.signature import compute, lookup, reference_dwellings, table  # noqa: E402


def _ref_detached_2000():
    return reference_dwellings()[("vrijstaand", "1992–2005")]


def test_best_uses_current_state_without_label():
    d = compute(pd.DataFrame([home()]), "best", detail=True).iloc[0]
    assert d.bron == "referentie" and d.isolatieniveau == 1.0
    ref = _ref_detached_2000()
    u_huidig = ref["bouwdelen"]["gevel"]["u__W_m_2_K_1"]["huidig"]
    assert d.U_gevel == pytest.approx(1 / (1 / u_huidig + 0.15), abs=1e-3)  # + MWA Rc surcharge
    assert d.Ainf == 54


def test_best_calibrates_on_nta_heat_demand():
    ref = _ref_detached_2000()
    q = ref["warmtebehoefte_qhnd__kWh_m_2"]
    comp_ref = sum(p["oppervlak__m2"] for p in ref["bouwdelen"].values()) \
        / ref["gebruiksoppervlak__m2"]
    rows = [home(warmtebehoefte=w, nta8800=True, compactheid=comp_ref)
            for w in (q["oorspronkelijk"] + 50, q["besparingspakket_1"], 1.0)]
    d = compute(pd.DataFrame(rows), "best", detail=True)
    assert list(d.bron) == ["warmtebehoefte"] * 3
    assert list(d.isolatieniveau) == [0.0, 2.0, 3.0]
    assert d.H[0] > d.H[1] >= d.H[2]


def test_best_label_class_only_nudges():
    d = compute(pd.DataFrame([home(energielabel="A++"), home(energielabel="B"),
                              home(energielabel="E")]), "best", detail=True)
    assert list(d.isolatieniveau) == [2.0, 1.5, 1.0]
    assert list(d.bron) == ["labelklasse"] * 3


def test_best_compactness_correction():
    # the same heat demand means better insulation for a less compact (larger envelope) home
    ref = _ref_detached_2000()
    w = ref["warmtebehoefte_qhnd__kWh_m_2"]["huidig"]
    comp_ref = sum(p["oppervlak__m2"] for p in ref["bouwdelen"].values()) \
        / ref["gebruiksoppervlak__m2"]
    d = compute(pd.DataFrame([home(warmtebehoefte=w, nta8800=True, compactheid=comp_ref),
                              home(warmtebehoefte=w, nta8800=True, compactheid=comp_ref * 1.5)]),
                "best", detail=True)
    assert d.isolatieniveau[1] > d.isolatieniveau[0]


def test_all_outputs_separate_and_detail():
    d = compute(pd.DataFrame([home()]), "nta8800", detail=True)
    assert {"H", "C", "tau", "Asol", "Ainf", "A_gevel", "U_raam", "g_raam", "bron"} <= set(d)


def test_table_and_lookup(tmp_path):
    pop = pd.DataFrame([{**home(opp_buitenmuur=200.0 + i), "vbo_id": f"{i:016d}",
                         "postcode6": "8011AB", "huisnummer": i + 1, "huisletter": None,
                         "toevoeging": None, "eengezins": True} for i in range(5)]
                       + [{**home(pand_woningen=6), "vbo_id": "9" * 16, "postcode6": "8011AC",
                           "huisnummer": 1, "huisletter": None, "toevoeging": None,
                           "eengezins": False}])
    src = tmp_path / "population.parquet"
    pop.to_parquet(src)
    out = table(src, tmp_path / "signaturen.parquet", batch_rows=2)
    t = pd.read_parquet(out)
    assert len(t) == 5  # single-family only
    assert {"vbo_id", "postcode6", "nta8800_H", "mwa_H", "best_H", "best_tau", "best_Ainf"} \
        <= set(t)
    one = lookup(src, "8011 ab", 3)
    assert len(one) == 1 and one["vbo_id"].iloc[0] == f"{2:016d}"
    assert one["best_bron"].iloc[0] == "referentie"


def test_rainbow_from_functional_table_for_a_subset(tmp_path, monkeypatch, capsys):
    """Functional table -> sharper rainbow table for a region, via the CLI."""
    from anonymate import cli
    from anonymate.rounding import rainbow_metadata
    rows = []
    for i in range(60):
        rows.append({**home(opp_buitenmuur=150.0 + i), "vbo_id": f"{i:016d}",
                     "postcode6": "8011AB", "huisnummer": i + 1, "huisletter": None,
                     "toevoeging": None, "eengezins": True,
                     "gemeente": "Zwolle" if i < 20 else "Deventer", "provincie": "Overijssel",
                     "woningtype": "vrijstaand" if i % 3 else "tussenwoning"})
    src = tmp_path / "population.parquet"
    pd.DataFrame(rows).to_parquet(src)
    tabel = table(src, tmp_path / "signaturen.parquet")
    t = pd.read_parquet(tabel)
    assert {"gemeente", "provincie", "woningtype", "best_H"} <= set(t)   # context kept

    out = tmp_path / "zwolle.parquet"
    rc = cli.main(["signatuur", "regenboog", "--bron", str(tabel), "--scope", "gemeente=Zwolle",
                   "--scope", "woningtype!=tussenwoning", "--stap", "warmteverlies_best=20",
                   "--out", str(out)])
    assert rc == 0
    freq = pd.read_parquet(out)
    assert freq["n"].sum() == 13        # 20 in Zwolle, minus the 7 terraced ones
    meta = rainbow_metadata(str(out))
    assert meta["stappen"] == {"best_H": 20.0}
    assert "gemeente=Zwolle" in meta["afbakening"] and "woningtype≠tussenwoning" in meta["afbakening"]
    assert "signatuurtabel" in meta["bronnen"]
