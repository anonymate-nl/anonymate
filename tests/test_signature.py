"""Baseline heat performance signature: made-up dwellings with hand-checkable numbers."""
import numpy as np
import pandas as pd
import pytest

from anonymate import CATALOGUE, Population, QidColumn, Threshold, assess
from anonymate.signature import baseline, compute, infer_dwelling_type


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
    # infiltration per dwelling: qv10 = 1.4 (detached) * 1.0 (2000) * 1.0 (pitched, unknown roof),
    # q10 = 168 L/s, q4 = 168 * 0.4^0.67, ELA = q4 / sqrt(2*4/1.2), 2 storeys (unknown) k = 0.2877
    ela = 168 * 0.4 ** 0.67 / 1000 / (8 / 1.2) ** 0.5 * 1e4
    assert s.sig_Ainf == pytest.approx(ela * 0.2877, abs=0.05)


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
    # a party-wall share of 0.40 is typical of one shared wall, not of a mid-terrace home
    t = infer_dwelling_type(pd.Series([True]), pd.Series([80.0]), pd.Series([120.0]))
    assert list(t) == ["twee_onder_een_kap"]


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
    assert np.allclose(mwa.sig_Ainf, nta.sig_Ainf * 0.5, atol=0.06)
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
    assert d.Ainf == pytest.approx(101.3 / 2, abs=0.06)      # qv10 halved (Maatwerkadvies)


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


def test_table_schema_stable_when_a_column_is_empty_in_one_batch(tmp_path):
    rows = [{**home(opp_buitenmuur=200.0 + i, aaneengebouwd=None if i == 5 else False),
             "vbo_id": f"{i:016d}", "postcode6": "8011AB",
             "huisnummer": i + 1, "huisletter": "A" if i >= 4 else None, "toevoeging": None,
             "eengezins": True, "gemeente": "Zwolle", "bouwlagen": None if i == 6 else 2,
             "bouwjaar": None if i == 7 else 2000} for i in range(8)]
    src = tmp_path / "population.parquet"
    df = pd.DataFrame(rows)
    df["bouwlagen"] = df["bouwlagen"].astype("Int64")
    df["bouwjaar"] = df["bouwjaar"].astype("Int64")
    df["aaneengebouwd"] = df["aaneengebouwd"].astype("boolean")
    df.to_parquet(src)
    out = table(src, tmp_path / "s.parquet", batch_rows=2, detail=True)  # first batches: no letter
    t = pd.read_parquet(out)
    assert len(t) == 8 and list(t["huisletter"].iloc[4:]) == ["A"] * 4
    assert t["best_bron"].iloc[0] == "referentie"


def _home_matching_reference(ref, **kw):
    """A home whose 3D-BAG envelope is exactly the reference dwelling's."""
    p = ref["bouwdelen"]
    a = {k: p[k]["oppervlak__m2"] for k in p}
    return home(oppervlakte=ref["gebruiksoppervlak__m2"], label_oppervlakte=ref["gebruiksoppervlak__m2"],
                compactheid=sum(a.values()) / ref["gebruiksoppervlak__m2"],
                opp_buitenmuur=a["gevel"] + a["raam"] + a.get("deur", 0), opp_grond=a["vloer"],
                opp_dak_plat=0.0, opp_dak_schuin=a["dak"], **kw)


def test_ep_equals_best_when_label_and_3dbag_envelope_agree():
    ref = _ref_detached_2000()
    row = _home_matching_reference(ref, warmtebehoefte=ref["warmtebehoefte_qhnd__kWh_m_2"]["huidig"],
                                   nta8800=True)
    b = compute(pd.DataFrame([row]), "best").iloc[0]
    e = compute(pd.DataFrame([row]), "ep").iloc[0]
    for k in ("H", "C", "Asol"):
        assert e[k] == pytest.approx(b[k], rel=1e-3), k


def test_ep_uses_the_label_envelope_not_3dbag():
    ref = _ref_detached_2000()
    row = _home_matching_reference(ref, warmtebehoefte=100.0, nta8800=True)
    bigger_3dbag = dict(row, opp_buitenmuur=row["opp_buitenmuur"] * 2)
    e1, e2 = (compute(pd.DataFrame([r]), "ep").iloc[0] for r in (row, bigger_3dbag))
    assert e1.H == pytest.approx(e2.H)
    larger_label = dict(row, compactheid=row["compactheid"] * 1.2)
    assert compute(pd.DataFrame([larger_label]), "ep").iloc[0].H > e1.H


def test_ep_needs_a_label_with_compactness():
    assert pd.isna(compute(pd.DataFrame([home()]), "ep").iloc[0].H)


def test_label_methods_use_the_heated_zone_and_fall_back_on_the_bag_area():
    ref = _ref_detached_2000()
    row = _home_matching_reference(ref, warmtebehoefte=100.0, nta8800=True)
    # the BAG and the label disagree on the floor area: the label's A_g wins
    row = dict(row, oppervlakte=row["label_oppervlakte"] + 30)
    e = compute(pd.DataFrame([row]), "ep", detail=True).iloc[0]
    assert e.oppervlakte_bron.startswith("label") and e.oppervlakte_gebruikt == row["label_oppervlakte"]
    # a label without A_g: the BAG area, and it says so
    no_ag = dict(row, label_oppervlakte=None)
    f = compute(pd.DataFrame([no_ag]), "ep", detail=True).iloc[0]
    assert f.oppervlakte_bron == "BAG" and f.oppervlakte_gebruikt == row["oppervlakte"]
    assert pd.notna(f.H) and f.C > e.C
    # the BAG methods always use the BAG area
    b = compute(pd.DataFrame([row]), "nta8800", detail=True).iloc[0]
    assert b.oppervlakte_bron == "BAG"


def test_as_learned_adds_ventilation_and_room_temperature():
    from anonymate.signature import as_learned, ventilation_H
    # NTA 8800 C1, Ag 120: f_tau 0.8, 60 dm3/s, x1.10/0.95 -> 200.1 m3/h -> 67.3 W/K; MWA x0.5
    assert float(ventilation_H(120.0)) == pytest.approx(33.65, abs=0.05)
    sig = pd.DataFrame({"H": [200.0], "C": [20000.0], "tau": [100.0], "Asol": [5.0]})
    plain = as_learned(sig, [120.0], ventilation=None, room_temperature=False)
    assert plain.H[0] == 200.0
    vent = as_learned(sig, [120.0], room_temperature=False)
    assert vent.H[0] == pytest.approx(233.65, abs=0.05)
    both = as_learned(sig, [120.0])
    assert both.H[0] == pytest.approx(233.65 * (18.33 - 6.44) / (20 - 6.44), abs=0.05)
    assert both.tau[0] == pytest.approx(20000.0 / both.H[0]) and both.Asol[0] == 5.0


def test_ep_3dbag_takes_shape_from_3dbag_and_size_from_label():
    ref = _ref_detached_2000()
    row = _home_matching_reference(ref, warmtebehoefte=100.0, nta8800=True)
    same = compute(pd.DataFrame([row]), "ep_3dbag", detail=True).iloc[0]
    ep = compute(pd.DataFrame([row]), "ep").iloc[0]
    assert same.H == pytest.approx(ep.H, rel=0.02)       # same envelope: same result
    # a 3D-BAG envelope twice as large (whole building) is scaled back to the label's size
    big = {k: (v * 2 if k.startswith("opp_") else v) for k, v in row.items()}
    scaled = compute(pd.DataFrame([big]), "ep_3dbag", detail=True).iloc[0]
    # only the (absolute) door area shifts the shape a little
    assert scaled.H == pytest.approx(same.H, rel=0.06)
    assert compute(pd.DataFrame([big]), "best").iloc[0].H > 1.5 * same.H
    assert pd.isna(compute(pd.DataFrame([home()]), "ep_3dbag").iloc[0].H)


def test_solar_aperture_hand_calculation():
    """NTA 8800 glazing gains, as a horizontal equivalent over the heating season."""
    d = compute(pd.DataFrame([home()]), "nta8800", detail=True).iloc[0]
    ratio = 0.731                        # vertical / horizontal, Oct-Apr, NTA reference climate
    glass = d.A_raam * 0.70 * 0.75 * 0.9 * 0.9 * ratio      # 92-05: g 0.75
    opaque = 0.6 * 0.04 * (d.A_gevel * d.U_gevel * ratio + d.A_deur * d.U_deur * ratio
                           + d.A_dak * d.U_dak)
    assert d.Asol == pytest.approx(glass + opaque, abs=0.01)
    assert d.Asol < 0.4 * d.A_raam       # a horizontal equivalent is far below the window area


def test_vertical_irradiance_ratio_from_the_nta_climate():
    """Energy-weighted vertical/horizontal ratio, October-April, N/E/S/W equally (NTA 8800
    reference climate, De Bilt, monthly mean irradiance in W/m²)."""
    ghi = [28.0, 49.3, 96.6, 160.5, 197.0, 209.3, 191.0, 177.2, 123.9, 73.2, 34.3, 21.0]
    vert = {"N": [11.1, 19.5, 34.8, 49.4, 61.9, 73.0, 66.7, 55.9, 41.4, 26.4, 13.6, 8.9],
            "E": [20.2, 36.5, 70.7, 112.2, 114.6, 114.8, 104.9, 89.0, 73.7, 49.8, 23.9, 15.9],
            "S": [60.1, 66.7, 101.8, 135.1, 124.9, 112.7, 109.7, 128.5, 122.3, 96.2, 59.5, 46.2],
            "W": [23.4, 32.8, 57.3, 96.2, 107.3, 125.7, 112.7, 120.0, 83.9, 46.7, 22.7, 15.2]}
    days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    season = [9, 10, 11, 0, 1, 2, 3]
    num = sum(sum(v[m] for v in vert.values()) / 4 * days[m] for m in season)
    den = sum(ghi[m] * days[m] for m in season)
    from anonymate.signature import VERTICAL_IRRADIANCE_RATIO
    assert VERTICAL_IRRADIANCE_RATIO == pytest.approx(num / den, abs=5e-4)


def test_as_learned_with_measured_time_constant():
    from anonymate.signature import as_learned
    sig = pd.DataFrame({"H": [300.0, 150.0], "C": [6000.0, 12000.0], "tau": [20.0, 80.0],
                        "Asol": [5.0, 5.0]})
    out = as_learned(sig, [120.0, 120.0], ventilation=None, room_temperature=False,
                     construction_year=[1930, 2005], tau="gemeten")
    assert list(out.tau) == [40.0, 71.0]             # Vosmer (2018) via TNO 2019 table 13
    assert list(out.C) == [40.0 * 300.0, 71.0 * 150.0]
    with pytest.raises(ValueError):
        as_learned(sig, [120.0, 120.0], tau="gemeten")


def test_mean_indoor_temperature_by_label():
    from anonymate.signature import as_learned, mean_indoor_temperature
    t = mean_indoor_temperature(["A", "A++", "D", "G", None], "majcen")
    assert list(t[:4]) == pytest.approx([20.7, 20.7, 16.55, 12.4])
    assert t[4] == pytest.approx(18.33)                    # no label: the NTA mean
    mid = mean_indoor_temperature(["G"], "midden")
    assert mid[0] == pytest.approx((12.4 + 18.33) / 2)
    sig = pd.DataFrame({"H": [300.0], "C": [9000.0], "tau": [30.0], "Asol": [4.0]})
    g = as_learned(sig, [120.0], ventilation=None, mean_indoor=t[3:4])
    assert g.H[0] == pytest.approx(300.0 * (12.4 - 6.44) / (20 - 6.44))
    with pytest.raises(ValueError):
        mean_indoor_temperature(["A"], "anders")


def test_passend_uses_ep_where_the_label_allows_and_best_otherwise():
    ref = _ref_detached_2000()
    with_label = _home_matching_reference(ref, warmtebehoefte=100.0, nta8800=True)
    rows = pd.DataFrame([with_label, home()])
    p = compute(rows, "passend", detail=True)
    e, b = compute(rows, "ep"), compute(rows, "best")
    assert p.H[0] == pytest.approx(e.H[0]) and p.H[1] == pytest.approx(b.H[1])
    assert list(p.methode_gebruikt) == ["ep", "best"]


def test_population_columns_cover_every_published_qid():
    from anonymate.qids import CATALOGUE
    from anonymate.signature import population_columns
    cols = population_columns(pd.DataFrame([home()]))
    wanted = {s.population_column for s in CATALOGUE.values()
              if (s.population_column or "").startswith("sig_")}
    assert wanted <= set(cols.columns)


def test_population_has_ainf_per_method_and_qids_for_it():
    from anonymate.qids import CATALOGUE
    from anonymate.signature import population_columns
    cols = population_columns(pd.DataFrame([home()]))
    for m in ("mwa", "best", "ep", "passend", "passend_cbag"):
        assert f"sig_{m}_Ainf" in cols.columns
    assert "sig_Ainf" in cols.columns
    for key, col in (("infiltratie", "sig_Ainf"), ("infiltratie_mwa", "sig_mwa_Ainf"),
                     ("infiltratie_best", "sig_best_Ainf"), ("infiltratie_ep", "sig_ep_Ainf"),
                     ("infiltratie_passend", "sig_passend_Ainf"),
                     ("infiltratie_passend_cbag", "sig_passend_cbag_Ainf")):
        assert CATALOGUE[key].population_column == col
        assert CATALOGUE[key].domain == (0, 2000) and not CATALOGUE[key].integer


def test_c_from_bag_area_in_the_cbag_variants():
    ref = _ref_detached_2000()
    row = _home_matching_reference(ref, warmtebehoefte=100.0, nta8800=True)
    row = dict(row, label_oppervlakte=row["oppervlakte"] * 1.4)   # label area differs from BAG
    rows = pd.DataFrame([row, home()])
    ep, epc = compute(rows, "ep"), compute(rows, "ep_cbag")
    assert epc.C[0] == pytest.approx(compute(rows, "best").C[0])   # C from the BAG area
    assert ep.C[0] == pytest.approx(epc.C[0] * 1.4)
    assert epc.H[0] == pytest.approx(ep.H[0]) and epc.Asol[0] == pytest.approx(ep.Asol[0])
    p, pc = compute(rows, "passend"), compute(rows, "passend_cbag")
    assert pc.H.tolist() == pytest.approx(p.H.tolist())
    assert pc.C[1] == pytest.approx(p.C[1])                        # best: unchanged


def test_publication_qids_for_passend_cbag():
    from anonymate.publicatie import _qid_key
    assert _qid_key("passend_cbag", "H") == "warmteverlies_passend"
    assert _qid_key("passend_cbag", "C") == "thermische_massa_passend_cbag"
    assert _qid_key("passend_cbag", "tau") == "tijdconstante_passend_cbag"


# --- infiltration per dwelling ---------------------------------------------------------------

from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

from anonymate import signature as sg  # noqa: E402


def test_qv10_lookups():
    f = sg.qv10_forfaitary
    assert f([1960], ["tussenwoning"], ["schuin"])[0] == 3.0
    assert f([1970], ["tussenwoning"], ["schuin"])[0] == 2.5
    assert f([1979], ["tussenwoning"], ["schuin"])[0] == 2.5
    assert f([1980], ["tussenwoning"], ["schuin"])[0] == 2.0
    assert f([1995], ["tussenwoning"], ["schuin"])[0] == 1.5
    assert f([2005], ["tussenwoning"], ["schuin"])[0] == 1.0
    assert f([2019], ["tussenwoning"], ["schuin"])[0] == 0.7
    assert f([1960], ["hoekwoning"], ["schuin"])[0] == pytest.approx(3.6)
    assert f([1960], ["twee_onder_een_kap"], [None])[0] == pytest.approx(3.6)   # unknown: pitched
    assert f([1960], ["vrijstaand"], ["plat"])[0] == pytest.approx(3.0 * 1.4 * 0.7)
    assert f([1960], ["vrijstaand"], ["plat_meerdere"])[0] == pytest.approx(3.0 * 1.4 * 0.7)
    assert np.isnan(f([np.nan], ["vrijstaand"], ["plat"])[0])
    assert np.isnan(f([2000], [None], ["plat"])[0])


def test_effective_leakage_area_hand_example():
    # qv10 1.0 dm3/(s m2) on 100 m2: 100 L/s at 10 Pa; at 4 Pa 100 * 0.4^0.67 = 54.1 L/s;
    # v = sqrt(2*4/1.2) = 2.582 m/s; ELA = 0.0541 / 2.582 m2 = 209.5 cm2
    ela = sg.effective_leakage_area(1.0, 100.0)
    assert ela == pytest.approx(0.1 * 0.4 ** 0.67 / (8 / 1.2) ** 0.5 * 1e4, rel=1e-9)
    assert ela == pytest.approx(209.6, abs=0.2)


def test_lbl_flow_hand_example():
    # 2 storeys: sqrt(0.000290 * 10 + 0.000420 * 16) = sqrt(0.0016) ... 0.0029 + 0.00672
    assert sg.lbl_flow(200.0, 10.0, 4.0, 2) == pytest.approx(200 * (0.0029 + 0.00672) ** 0.5)
    assert sg.lbl_flow(200.0, 0.0, 0.0, 3) == 0
    # more storeys: more stack effect
    assert sg.lbl_flow(200.0, 10.0, 0.0, 3) > sg.lbl_flow(200.0, 10.0, 0.0, 1)
    # clamped to 1..3
    assert sg.lbl_flow(200.0, 10.0, 4.0, 7) == sg.lbl_flow(200.0, 10.0, 4.0, 3)


def test_lbl_k_constants_follow_from_committed_data():
    data = pd.read_csv(Path(__file__).parents[1] / "docs" / "data" / "knmi_260_uur_2025-26.csv")
    assert len(data) == 5088                                  # October - April
    for n, k in sg.LBL_K.items():
        assert sg.lbl_linearisation(data["T__C"], data["FH__m_s"], n) == pytest.approx(k, abs=6e-5)


def test_ainf_varies_with_year_and_type():
    df = pd.DataFrame([home(bouwjaar=1960), home(bouwjaar=2015), home(woningtype="tussenwoning"),
                       home()])
    a = sg.compute(df, "nta8800", detail=True)
    assert a.Ainf[0] > a.Ainf[3] > a.Ainf[1]                 # older -> larger
    assert a.Ainf[3] > a.Ainf[2]                             # detached > mid-terrace
    assert a.Ainf[0] / a.Ainf[1] == pytest.approx(3.0 / 0.7, rel=0.01)
    assert a.qv10[3] == pytest.approx(1.4)
    assert a.bouwlagenklasse[3] == 2
    m = sg.compute(df, "mwa")
    assert np.allclose(m.Ainf, a.Ainf * 0.5, atol=0.06)


def test_ainf_storeys_roof_and_fallback():
    df = pd.DataFrame([home(bouwlagen=1, daktype="schuin"), home(bouwlagen=3, daktype="schuin"),
                       home(bouwlagen=2, daktype="plat"), home(bouwlagen=2, daktype="schuin"),
                       ])
    d = sg.compute(df, "nta8800", detail=True)
    assert d.bouwlagenklasse[:2].tolist() == [1, 3]
    assert d.Ainf[1] / d.Ainf[0] == pytest.approx(0.3310 / 0.2300, rel=1e-3)
    assert d.Ainf[2] == pytest.approx(0.7 * d.Ainf[3], rel=1e-3)
    assert d.Ainf_bron[0].startswith("woning")
    # missing inputs give NaN here; compute() then falls back on the national average
    assert np.isnan(sg.infiltration([np.nan], [100.0], ["vrijstaand"], [None], [2],
                                    maatwerk=False)["Ainf"][0])



# ------------------------------------------------------------------------------------------------
# A_sol per façade orientation (docs/warmtesignatuur.md, "A_sol per gevelrichting")
# ------------------------------------------------------------------------------------------------

def _facades(side_m2=None, **m2):
    """Façade columns from area per sector (keyword: n, no, o, ...); ``side_m2`` the part of a
    sector that is a side façade."""
    from anonymate.signature import GEVEL_COLUMNS, GEVEL_ZIJ_COLUMNS
    out = {c: 0.0 for c in GEVEL_COLUMNS + GEVEL_ZIJ_COLUMNS}
    for r, a in m2.items():
        out[f"gevel_{r}__m2"] = a
    for r, a in (side_m2 or {}).items():
        out[f"gevelzij_{r}__m2"] = a
    return out


def _radiation():
    from pathlib import Path
    return pd.read_csv(Path(__file__).parents[1] / "docs" / "data" / "knmi_260_straling_2025-26.csv",
                       parse_dates=["tijd_utc"])


def test_solar_ratios_recomputed_from_the_committed_knmi_radiation():
    from anonymate.instraling import RICHTINGEN, r_verticaal_per_richting
    from anonymate.signature import R_VERTICAAL_PER_RICHTING__W0
    data = _radiation()
    assert len(data) == 5088 and data["GHI__W_m_2"].between(0, 1000).all()
    r = r_verticaal_per_richting(data["tijd_utc"], data["GHI__W_m_2"])
    assert len(RICHTINGEN) == len(R_VERTICAAL_PER_RICHTING__W0) == 8
    assert r == pytest.approx(R_VERTICAAL_PER_RICHTING__W0, abs=5e-5)
    # south catches most, north least; the plain mean of N/E/S/W is close to the NTA 8800 value
    assert np.argmax(r) == 4 and np.argmin(r) == 0
    assert r[[0, 2, 4, 6]].mean() == pytest.approx(0.731, rel=0.06)


def test_solar_ratios_against_pvlib():
    """pvlib (not a dependency) as an offline reference: same Erbs + Hay-Davies chain."""
    pvlib = pytest.importorskip("pvlib")
    from anonymate.instraling import AZIMUTH__deg, SEASON_MONTHS, r_verticaal_per_richting
    data = _radiation()
    t, ghi = pd.DatetimeIndex(data["tijd_utc"]), data["GHI__W_m_2"].to_numpy()
    mid = (t + pd.Timedelta(minutes=30)).tz_localize("UTC")
    sp = pvlib.solarposition.get_solarposition(mid, 52.10, 5.18)
    extra = pvlib.irradiance.get_extra_radiation(mid)
    dec = pvlib.irradiance.erbs(ghi, sp["zenith"], mid)
    season = np.isin(t.month, SEASON_MONTHS)
    ref = [pvlib.irradiance.get_total_irradiance(
        90, a, sp["zenith"], sp["azimuth"], dec["dni"], ghi, dec["dhi"], dni_extra=extra,
        albedo=0.2, model="haydavies")["poa_global"].fillna(0).to_numpy()[season].sum()
        / ghi[season].sum() for a in AZIMUTH__deg]
    assert r_verticaal_per_richting(t, ghi) == pytest.approx(ref, rel=0.03)


def test_solar_position_and_erbs():
    from anonymate.instraling import erbs_diffuse_fraction, zonspositie
    cos_z, az, i0 = zonspositie(pd.DatetimeIndex(["2025-06-21 11:40", "2025-12-21 11:40",
                                                  "2025-03-20 06:00"]))
    assert np.degrees(np.arccos(cos_z[0])) == pytest.approx(90 - 61.4, abs=0.6)   # solstice noon
    assert np.degrees(np.arccos(cos_z[1])) == pytest.approx(90 - 14.4, abs=0.6)
    assert az[0] == pytest.approx(180, abs=6) and az[2] == pytest.approx(90, abs=3)  # equinox dawn
    assert 1310 < i0[0] < 1325 and 1400 < i0[1] < 1415
    assert list(np.round(erbs_diffuse_fraction([0.1, 0.22, 0.9]), 3)) == [0.991, 0.98, 0.165]


def _terrace_home(**extra):
    return {**home(woningtype="tussenwoning", aaneengebouwd=True, opp_scheidingsmuur=100.0,
                   opp_buitenmuur=100.0), **extra}


def test_orientation_of_a_terrace_matters_but_swapping_front_and_back_does_not():
    ns = _terrace_home(**_facades(n=50.0, z=50.0))
    ew = _terrace_home(**_facades(o=50.0, w=50.0))
    df = pd.DataFrame([ns, ew, _terrace_home()])
    s = compute(df, "best", detail=True)
    assert s.Asol[0] > 1.08 * s.Asol[1]                   # (N+S)/2 0.743 against (E+W)/2 0.657
    assert s.asol_bron__str[0].startswith("gevelrichting")
    assert s.asol_bron__str[2].startswith("gemiddelde verhouding (gevelrichting onbekend)")
    # the same exposed areas north and south: a south-facing rear or a north-facing rear is one
    # and the same A_sol (windows follow the exposed wall area)
    # nta8800 and mwa are orientation-averaged on purpose, whatever the façades
    for method in ("nta8800", "mwa"):
        s = compute(df, method, detail=True)
        assert s.Asol[0] == s.Asol[1] == s.Asol[2]
        assert (s.asol_bron__str == "gemiddelde verhouding (methode is richtingsgemiddeld)").all()


def test_orientation_asol_hand_calculation():
    from anonymate.signature import R_VERTICAAL_PER_RICHTING__W0 as R
    row = _terrace_home(**_facades(n=30.0, z=70.0))
    d = compute(pd.DataFrame([row]), "best", detail=True).iloc[0]
    f = 0.3 * R[0] + 0.7 * R[4]                  # windows and walls follow the exposed wall area
    glass = d.A_raam * 0.70 * d.g_raam * 0.9 * 0.9 * f
    opaque = 0.6 * 0.04 * (d.A_gevel * d.U_gevel * f + d.A_deur * d.U_deur * f
                           + d.A_dak * d.U_dak)
    assert d.Asol == pytest.approx(glass + opaque, abs=0.01)
    south = pd.DataFrame([_terrace_home(**_facades(z=100.0)), _terrace_home()])
    s = compute(south, "best").Asol
    assert s[0] > 1.3 * s[1]                     # all facing south against the average


def test_side_facades_count_half_except_for_a_detached_house():
    from anonymate.signature import R_VERTICAAL_PER_RICHTING__W0 as R, _irradiance_ratios
    facades = _facades(side_m2={"w": 60.0}, z=40.0, n=40.0, w=60.0)
    df = pd.DataFrame([facades, facades])
    r_win, r_wall, known = _irradiance_ratios(
        df, np.array(["hoekwoning", "vrijstaand"], dtype=object),
        np.full(2, 30.0), np.full(2, 120.0), np.full(2, 2.0))
    assert known.all()
    rs = [R[4], R[0], R[6]]
    w = np.array([40.0, 40.0, 30.0])             # S, N, W side (weight 0.5)
    assert r_win[0] == pytest.approx((w * rs).sum() / w.sum())
    w = np.array([40.0, 40.0, 60.0])             # detached: weight 1
    assert r_win[1] == pytest.approx((w * rs).sum() / w.sum())
    # the opaque wall follows the exposed area, not the window weight (windows take their share)
    gross = np.array([40.0, 40.0, 60.0]) / 140.0
    assert r_wall[0] == pytest.approx((gross * rs).sum(), abs=0.03)


def test_fallback_when_orientation_is_missing():
    partial = _terrace_home(**{**_facades(z=50.0), "gevel_n__m2": None})
    empty = _terrace_home(**_facades())                    # all zero: no exposed wall known
    df = pd.DataFrame([_terrace_home(), partial, empty])
    s = compute(df, "best", detail=True)
    assert s.Asol[0] == s.Asol[1] == s.Asol[2]
    assert (s.asol_bron__str == "gemiddelde verhouding (gevelrichting onbekend)").all()
    d = s.iloc[0]                                          # the averaged ratio, as before
    avg = 0.731
    assert d.Asol == pytest.approx(
        d.A_raam * 0.70 * d.g_raam * 0.9 * 0.9 * avg
        + 0.6 * 0.04 * ((d.A_gevel * d.U_gevel + d.A_deur * d.U_deur) * avg + d.A_dak * d.U_dak),
        abs=0.01)
    # passend takes the source of the method it used
    p = compute(pd.DataFrame([_terrace_home(**_facades(z=50.0, n=50.0))]), "passend", detail=True)
    assert p.asol_bron__str[0].startswith("gevelrichting")
