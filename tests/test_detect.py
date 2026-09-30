import pandas as pd
import pytest

from anonymate.detect import Role, detect, detect_column


@pytest.mark.parametrize("name,values,role,qid", [
    ("bouwjaar", [1970, 1985], Role.QID, "bouwjaar"),
    ("construction_year", ["1960-1979"], Role.QID, "bouwjaar"),
    ("bouwjaar_klasse__cat", ["1960-1979"], Role.QID, "bouwjaar"),
    ("vloeroppervlak_bin__cat", ["115-124"], Role.QID, "oppervlakte"),
    ("surface", ["100-149"], Role.QID, "oppervlakte"),
    ("energylabel", ["A", "C"], Role.QID, "energielabel"),
    ("woningtype__cat", ["Tussenwoning"], Role.QID, "woningtype"),
    ("house_type", ["detached"], Role.QID, "woningtype"),
    ("pc6", ["1234AB"], Role.QID, "postcode6"),
    ("installatiedatum_wp", ["2021-03-01"], Role.QID, "installatiedatum"),
    ("isde_vermogen__kW", [5, 7], Role.QID, "vermogen"),
    ("gas_voor_1__m3", [1200.0], Role.QID, "jaarverbruik"),
    ("heeft_muurisolatie__bool", [True], Role.QID, "isolatie"),
    ("ketel_merk_type", ["X 28c"], Role.QID, "toestel"),
    ("knmi_station", [260], Role.IMPLICIT_LOCATION, "knmi_station"),
    ("weather_lat__degN", [52.1], Role.IMPLICIT_LOCATION, "h3_cel"),
    ("h3_cell", ["841f9a9ffffffff"], Role.IMPLICIT_LOCATION, "h3_cel"),
    ("gps_lat__degN", [52.123456], Role.DIRECT, None),
    ("rd_x", [155000], Role.DIRECT, None),
    ("huisnummer", [12], Role.DIRECT, None),
    ("street", ["Dorpsstraat"], Role.DIRECT, None),
    ("email", ["a@b.nl"], Role.DIRECT, None),
    ("e_net__W", [350.0, 420.5], Role.MEASUREMENT, None),
    ("e_consumed_high", [8789.167], Role.DIRECT, None),
    ("v_gas_consumed", [5059.199], Role.DIRECT, None),
    ("meterstand_gas__m3", [5059.199], Role.DIRECT, None),
    ("ainf", [120.0, 140.5], Role.QID, "infiltratie"),
    ("a_inf", [120.0], Role.QID, "infiltratie"),
    ("infiltratie", [120.0], Role.QID, "infiltratie"),
    ("infiltration_aperture", [120.0], Role.QID, "infiltratie"),
    ("adres_Ainf__cm2", [120.0], Role.QID, "infiltratie"),
    ("adres_H__W_K_1", [180.0], Role.QID, "warmteverlies"),
    ("adres_C__Wh_K_1", [9000.0], Role.QID, "thermische_massa"),
    ("adres_tau__h", [50.0], Role.QID, "tijdconstante"),
    ("adres_Asol__m2", [4.5], Role.QID, "zonnetoetreding"),
    ("adres", ["Dorpsstraat 1"], Role.DIRECT, None),
    ("adres_straat", ["Dorpsstraat"], Role.DIRECT, None),
    ("tijdstip_start", ["2024-01-01 00:00"], Role.MEASUREMENT, None),
])
def test_by_name(name, values, role, qid):
    d = detect_column(name, pd.Series(values))
    assert (d.role, d.qid) == (role, qid)


@pytest.mark.parametrize("values,role,qid", [
    (["1234 AB", "5678CD", "9999ZZ"], Role.QID, "postcode6"),
    (["841f9a9ffffffff", "841f91dffffffff"], Role.IMPLICIT_LOCATION, "h3_cel"),
    (["x@y.nl", "p@q.com"], Role.DIRECT, None),
    (["C", "A+", "G"], Role.QID, "energielabel"),
    (["0363010000000001", "0363010000000002"], Role.DIRECT, None),
])
def test_by_values_with_opaque_name(values, role, qid):
    d = detect_column("kolom_7", pd.Series(values))
    assert (d.role, d.qid) == (role, qid)


def test_name_and_values_agree_raises_confidence():
    assert detect_column("postcode", pd.Series(["1234AB"])).confidence > \
        detect_column("postcode", pd.Series(["onzin"])).confidence


def test_derived_column_leaks_its_source():
    models = ["A", "A", "B", "B", "C", "C", "A"]
    df = pd.DataFrame({
        "toestel": models,
        "pmax__kW": [24, 24, 28, 28, 35, 35, 24],
        "e_net__W": [100.0, 220.0, 130.0, 90.0, 400.0, 50.0, 70.0],
    })
    found = {d.column: d for d in detect(df)}
    assert found["pmax__kW"].role == Role.DERIVED
    assert found["pmax__kW"].qid == "toestel"
    assert found["e_net__W"].role == Role.MEASUREMENT


def test_unique_key_does_not_make_everything_derived():
    df = pd.DataFrame({"pc6": ["1234AB", "1234AC", "1234AD", "1234AE", "1234AF"],
                       "x": [1, 2, 3, 4, 5]})
    assert {d.column: d.role for d in detect(df)}["x"] == Role.MEASUREMENT


def test_weather_cell_centres_become_h3_column():
    import h3
    from anonymate.detect import derive_h3_columns, h3_center_resolution
    cells = [h3.latlng_to_cell(52.1 + i * 0.3, 5.1 + i * 0.2, 4) for i in range(4)]
    centres = [h3.cell_to_latlng(c) for c in cells]
    df = pd.DataFrame({"weather_lat__degN": [c[0] for c in centres],
                       "weather_lon__degE": [c[1] for c in centres],
                       "e_net__W": [1.0, 2.0, 3.0, 4.0]})
    assert h3_center_resolution(df["weather_lat__degN"], df["weather_lon__degE"]) == 4
    out, mapping = derive_h3_columns(df)
    assert list(out["weather_h3_cel"]) == cells
    assert mapping == {"weather_h3_cel": "h3_cel", "weather_lat__degN": "geen",
                       "weather_lon__degE": "geen"}


def test_raw_coordinates_are_not_cell_centres():
    from anonymate.detect import h3_center_resolution
    lat = pd.Series([52.123456, 52.654321])
    lon = pd.Series([5.111111, 6.222222])
    assert h3_center_resolution(lat, lon) is None


def test_every_published_signature_column_is_a_qid():
    from anonymate.publicatie import COLUMN
    for output, name in COLUMN.items():
        d = detect_column(name, pd.Series([1.0, 2.0]))
        assert d.role == Role.QID and d.qid is not None, name
