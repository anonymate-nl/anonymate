"""Step 4 in the web facade: assessing with the address-based signature, and exploring its
rounding steps (anonymate.web.run with sig, anonymate.web.explore)."""
import json

import pytest

from anonymate import web
from tests.test_publicatie import dataset, make_population


@pytest.fixture(scope="module")
def pop():
    return make_population()


@pytest.fixture()
def session(pop, monkeypatch):
    df, population = pop
    monkeypatch.setattr(web, "S", web.Session())
    web.S.population = population
    web._open(dataset(df, list(range(0, 400, 50))), "proef.csv")
    web.lock_norm(0.09)
    return df, population


def sig(**kw):
    return {"on": True, "method": "best", "steps": {"H": 25, "C": 5000}, "link_cols": "pc,nr",
            **kw}


def test_run_adds_the_rounded_signature_and_keeps_the_address_out(session):
    r = web.run(sig=sig())
    json.dumps(r)
    assert "adres_H__W_K_1" in r["table"]["columns"]
    assert {"pc", "nr"} <= set(r["direct"])
    # the page sends its own mapping every time; with the signature off, pc is a QID again
    off = web.run(mapping={"pc": "postcode6", "nr": "geen", "gas__m3": "geen"},
                  sig=sig(on=False))
    assert "adres_H__W_K_1" not in off["table"]["columns"]


def test_explore_gives_steps_and_loss_per_output(session):
    r = web.explore(sig=sig(), standaard=False)
    json.dumps(r)
    t = r["table"]
    assert "stap H [W/K]" in t["columns"] and "precisieverlies H [%]" in t["columns"]
    assert len(t["rows"]) == 16              # 4 steps for H times 4 for C
    std = web.explore(sig=sig(), standaard=True)
    assert len(std["table"]["rows"]) == 36
    assert "stap A_inf [cm²]" in std["table"]["columns"]


def test_explore_needs_the_signature_on_and_a_population_with_it(session, monkeypatch):
    with pytest.raises(ValueError, match="zet stap 4 aan"):
        web.explore(sig=sig(on=False))
    with pytest.raises(ValueError, match="koppelkolommen zijn leeg"):
        web.explore(sig=sig(link_cols=""))
    df, population = session
    bare = population.__class__.from_dataframe(df[[c for c in df.columns
                                                   if not c.startswith("sig_")]])
    web.S.population = bare
    with pytest.raises(ValueError, match="geen berekende signaturen"):
        web.run(sig=sig())


def test_representativiteit_compares_register_values_and_goes_in_the_zip(session):
    import io
    import zipfile
    r = web.representativiteit(sig=sig(on=False))
    json.dumps(r)
    assert r["title"].startswith("Representativiteit: 8 van 8 records")
    kolommen = {row["kenmerk"] for row in r["uitkomst"]["kenmerken"]}
    assert {"bouwjaar__yr", "woningtype__cat", "oppervlakte__m2"} <= kolommen
    web.run(mapping={"pc": "postcode6", "nr": "geen", "gas__m3": "geen"}, sig=sig(on=False))
    names = zipfile.ZipFile(io.BytesIO(web.export())).namelist()
    assert {"representativiteit.json", "representativiteit.md"} <= set(names)


def test_representativiteit_needs_link_columns(session):
    with pytest.raises(ValueError, match="koppelkolommen zijn leeg"):
        web.representativiteit(sig=sig(link_cols=""))
