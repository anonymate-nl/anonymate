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
