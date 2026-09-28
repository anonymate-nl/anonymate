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
