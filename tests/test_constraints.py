import pytest

from anonymate.constraints import OneOf, Range, parse_categorical, parse_numeric, union
from anonymate.qids import normalise_dwelling_type, normalise_label, normalise_postcode


@pytest.mark.parametrize("value,expected", [
    (1974, Range(1974, 1974)),
    ("1974", Range(1974, 1974)),
    ("115-124", Range(115, 124)),
    ("115 - 124", Range(115, 124)),
    ("1960 t/m 1979", Range(1960, 1979)),
    ("<1945", Range(None, 1944)),
    ("voor 1945", Range(None, 1944)),
    ("<=1945", Range(None, 1945)),
    (">250", Range(251, None)),
    (">=250", Range(250, None)),
    ("250+", Range(250, None)),
    ("1960s", Range(1960, 1969)),
    ("12,5", Range(12.5, 12.5)),
])
def test_parse_numeric(value, expected):
    assert parse_numeric(value) == expected


@pytest.mark.parametrize("value", [None, float("nan"), "", "onbekend", "NaN"])
def test_parse_numeric_missing(value):
    assert parse_numeric(value) is None


def test_parse_numeric_nonsense():
    with pytest.raises(ValueError):
        parse_numeric("ongeveer honderd")


def test_parse_numeric_float_strict_bound_not_shifted():
    assert parse_numeric("<1.5", integer=False) == Range(None, 1.5)


def test_parse_categorical():
    assert parse_categorical("A|B") == OneOf.of("A", "B")
    assert parse_categorical("A / B") == OneOf.of("A", "B")
    assert parse_categorical("C of D") == OneOf.of("C", "D")
    assert parse_categorical("a+", normalise=normalise_label) == OneOf.of("A+")
    assert parse_categorical("X", normalise=normalise_label) is None


def test_render_roundtrip():
    for c in [Range(1960, 1969), Range(None, 1944), Range(250, None), Range(3, 3),
              OneOf.of("A", "B")]:
        parsed = parse_numeric(c.render()) if isinstance(c, Range) else parse_categorical(c.render())
        assert parsed == c


def test_union():
    assert union([Range(1, 3), Range(5, 9)]) == Range(1, 9)
    assert union([Range(None, 3), Range(5, 9)]) == Range(None, 9)
    assert union([OneOf.of("A"), OneOf.of("B")]) == OneOf.of("A", "B")
    assert union([Range(1, 3), None]) is None


@pytest.mark.parametrize("raw,canon", [
    ("Vrijstaande woning", "vrijstaand"),
    ("2-onder-1-kap", "twee_onder_een_kap"),
    ("semi-detached", "twee_onder_een_kap"),
    ("Rijwoning hoek", "hoekwoning"),
    ("Rijwoning tussen", "tussenwoning"),
    ("Galerijflat", "appartement"),
    ("woonboot", None),
])
def test_dwelling_type(raw, canon):
    assert normalise_dwelling_type(raw) == canon


def test_postcode():
    assert normalise_postcode("1234 ab") == "1234AB"
    assert normalise_postcode("1234") == "1234"
    assert normalise_postcode("123") is None
