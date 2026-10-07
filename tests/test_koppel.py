"""--koppel: which column is which address part, found or given."""
import pandas as pd
import pytest

from anonymate.cli import VERKEN_STANDAARD, _steps
from anonymate.link import koppel_kolommen


def frame(*cols):
    return pd.DataFrame({c: ["x"] for c in cols})


def test_auto_tells_number_letter_and_addition_apart():
    df = frame("pseudoniem", "Postcode", "Huisnummer", "Huisletter", "Toevoeging", "gas_m3")
    assert koppel_kolommen(df, "auto") == {"postcode": "Postcode", "huisnummer": "Huisnummer",
                                           "huisletter": "Huisletter",
                                           "toevoeging": "Toevoeging"}


def test_auto_with_english_names_and_add_on():
    df = frame("zip_code", "home_nr", "home_nr_add_on")
    assert koppel_kolommen(df, "auto") == {"postcode": "zip_code", "huisnummer": "home_nr",
                                           "toevoeging": "home_nr_add_on"}


def test_auto_prefers_a_single_bag_id():
    df = frame("vbo_id", "postcode", "huisnummer")
    assert koppel_kolommen(df, "auto") == {"vbo_id": "vbo_id"}


def test_auto_stops_when_ambiguous_or_missing():
    with pytest.raises(ValueError, match="meerdere kolommen voor postcode"):
        koppel_kolommen(frame("postcode", "zip", "huisnummer"), "auto")
    with pytest.raises(ValueError, match="geen BAG-id"):
        koppel_kolommen(frame("postcode", "gas_m3"), "auto")


def test_named_parts_need_no_order_and_allow_a_missing_letter():
    df = frame("pc", "nr", "toev")
    assert koppel_kolommen(df, "toevoeging=toev,postcode=pc,huisnummer=nr") == {
        "toevoeging": "toev", "postcode": "pc", "huisnummer": "nr"}


def test_positional_with_an_empty_place():
    # an addition without a letter column: the empty place keeps it from being read as letter
    df = frame("pc", "nr", "toev")
    assert koppel_kolommen(df, "pc,nr,,toev") == {"postcode": "pc", "huisnummer": "nr",
                                                  "toevoeging": "toev"}
    assert koppel_kolommen(frame("bag"), "bag") == {"vbo_id": "bag"}


def test_unknown_part_or_column_is_refused():
    with pytest.raises(ValueError, match="onbekend adresdeel"):
        koppel_kolommen(frame("pc"), "straat=pc")
    with pytest.raises(ValueError, match="niet in de dataset"):
        koppel_kolommen(frame("pc"), "pc,nummer")


def test_verken_standaard_and_overrides():
    assert _steps(["standaard"]) == VERKEN_STANDAARD
    steps = _steps(["standaard", "Asol=1,2,3,5"])
    assert steps["Asol"] == [1.0, 2.0, 3.0, 5.0] and steps["H"] == VERKEN_STANDAARD["H"]
