import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from anonymate import datapakket, synthetic


def _population(tmp_path, n=600):
    rng = np.random.default_rng(1)
    pop = synthetic.with_places(synthetic.population(n, seed=4))
    pop["pand_woningen__0"] = np.where(pop["woningtype__cat"] == "appartement", 12, 1)
    pop["aaneengebouwd__bool"] = pop["woningtype__cat"] != "vrijstaand"
    for c, lo, hi in (("opp_grond__m2", 40, 120), ("opp_dak_plat__m2", 0, 30), ("opp_dak_schuin__m2", 40, 140),
                      ("opp_buitenmuur__m2", 60, 220), ("opp_scheidingsmuur__m2", 0, 120)):
        pop[c] = rng.uniform(lo, hi, n).round(1)
    pop["daktype__cat"], pop["bouwlagen__0"], pop["hoogte__m"] = "schuin", 2, 8.5
    # label data the population holds, which must not leave in a package
    pop["warmtebehoefte__kWh_m_2_a_1"], pop["compactheid__m2_m_2"], pop["nta8800__bool"] = 90.0, 2.1, True
    pop["uhi__degC"] = np.round(rng.uniform(0, 2, n), 2).astype("float32")   # public (RIVM), goes along
    path = tmp_path / "population.parquet"
    pop.to_parquet(path, index=False)
    return path


def test_the_package_holds_nothing_from_ep_online(tmp_path):
    out = datapakket.make(_population(tmp_path), tmp_path / "pakket",
                          sources={"bag": "2026-08", "3dbag": "v20250903"}, batch_rows=250)
    woningen = pq.read_table(out / "woningen.parquet").to_pandas()
    vorm = pq.read_table(out / "warmtesignatuur.parquet").to_pandas()
    columns = set(woningen.columns) | set(vorm.columns)
    assert not columns & (datapakket.EP_COLUMNS | {"energielabel__cat", "woningtype__cat"})
    assert {"sig_nta8800_H__W_K_1", "sig_mwa_tau__h", "sig_nta8800_Ainf__cm2", "sig_mwa_Ainf__cm2"} <= set(vorm.columns)
    assert "uhi__degC" in woningen.columns and woningen["uhi__degC"].notna().all()
    assert len(woningen) == len(vorm) == 600
    # single-family homes have a signature; the dwelling type came from the building's shape
    single = vorm[woningen["pand_woningen__0"] == 1]
    assert single["sig_nta8800_H__W_K_1"].notna().mean() > 0.9
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ep_online"].startswith("niet gebruikt")
    assert set(manifest["bestanden"]) == {"woningen.parquet", "warmtesignatuur.parquet"}
    assert all(not s.lower().startswith("ep") for s in manifest["kolommen"].values())
    assert manifest["kolommen"]["uhi__degC"].startswith("RIVM")


def test_a_package_becomes_a_population_with_or_without_own_ep_online(tmp_path):
    from anonymate.store import Store
    pkg = datapakket.make(_population(tmp_path), tmp_path / "pakket", batch_rows=250)
    store = Store.open(tmp_path / "store")
    store.raw.mkdir(parents=True, exist_ok=True)
    datapakket.install(pkg, store, batch_rows=250)
    pop = pd.read_parquet(store.population_path)
    assert len(pop) == 600
    assert {"knmi_station__cat", "h3_r4__str", "h3_r8__str", "postcode4__str", "sig_H__W_K_1", "woningtype__cat"} <= set(pop.columns)
    assert "energielabel__cat" not in pop.columns
    assert "uhi__degC" in pop.columns and pop["uhi__degC"].notna().all()    # the heat island comes along
    assert set(pop["woningtype_bron__cat"].dropna()) == {"vorm"}
    assert pop.loc[pop["pand_woningen__0"] == 1, "sig_H__W_K_1"].notna().mean() > 0.9
    # the user's own EP-online (route 4): labels joined, type from the label where known
    ids = pop["vbo_id__str"].head(50)
    # raw/ep_online.parquet keeps the names of the ingest (docs/variabelen.md)
    pd.DataFrame({"vbo_id": ids, "energielabel": "C", "woningtype": "hoekwoning",
                  "warmtebehoefte": 95.0}).to_parquet(store.raw / "ep_online.parquet", index=False)
    datapakket.install(pkg, store, batch_rows=250)
    pop = pd.read_parquet(store.population_path)
    first = pop[pop["vbo_id__str"].isin(ids)]
    assert (first["energielabel__cat"] == "C").all() and (first["woningtype_bron__cat"] == "ep-online").all()
    assert store.manifest()["sources"]["datapakket"]["ep_online"] == "eigen opslag"


def test_status_after_installing_a_package(tmp_path, capsys):
    """`anonymate status` read a 'built' date that only `anonymate build` wrote (KeyError)."""
    from anonymate import cli
    from anonymate.store import Store
    pkg = datapakket.make(_population(tmp_path), tmp_path / "pakket", batch_rows=250)
    store = Store.open(tmp_path / "store")
    store.raw.mkdir(parents=True, exist_ok=True)
    datapakket.install(pkg, store, batch_rows=250)
    assert store.manifest()["population"]["built"]
    assert cli.main(["--home", str(tmp_path / "store"), "status"]) == 0
    assert "populatie: 600 woningen" in capsys.readouterr().out


def test_gaps_in_a_later_batch_keep_one_schema(tmp_path):
    """A whole-number column (oppervlakte__m2) without gaps in the first batch and with gaps in a
    later one: pandas makes it int there and float here; the package must still be one file
    (the first run on GitHub stopped at 500,000 dwellings on exactly this)."""
    import pyarrow as pa
    path = _population(tmp_path)
    table = pq.read_table(path)
    area = table.column("oppervlakte__m2").to_pylist()
    area[400:410] = [None] * 10
    i = table.schema.get_field_index("oppervlakte__m2")
    table = table.set_column(i, pa.field("oppervlakte__m2", pa.int64()), pa.array(area, pa.int64()))
    pq.write_table(table, path)
    out = datapakket.make(path, tmp_path / "pakket", batch_rows=250)
    woningen = pq.read_table(out / "woningen.parquet")
    assert woningen.num_rows == 600
    assert woningen.schema.field("oppervlakte__m2").type == pa.int64()
    assert woningen.column("oppervlakte__m2").null_count == 10


def test_three_significant_digits():
    x = datapakket._three_digits(np.array([123.456, 0.012345, 98765.0, 0.0, np.nan]))
    assert list(x[:4]) == [123.0, 0.0123, 98800.0, 0.0] and np.isnan(x[4])


def _published(tmp_path):
    pkg = datapakket.make(_population(tmp_path), tmp_path / "pakket", batch_rows=250)
    pub = tmp_path / "publicatie"
    manifest = datapakket.publish(pkg, pub)
    return pub, manifest


def test_the_published_zip_is_deterministic_and_installs(tmp_path):
    from anonymate.store import Store
    pub, manifest = _published(tmp_path)
    assert {p.name for p in pub.iterdir()} == {"anonymate-datapakket.zip", "manifest.json"}
    assert manifest["zip"]["sha256"] == datapakket.sha256_file(pub / "anonymate-datapakket.zip")
    again = datapakket.zip_package(tmp_path / "pakket", tmp_path / "nog-eens.zip")
    assert datapakket.sha256_file(again) == manifest["zip"]["sha256"]
    datapakket.verify(pub / "anonymate-datapakket.zip", pub / "manifest.json")
    store = Store.open(tmp_path / "store")
    datapakket.install(pub / "anonymate-datapakket.zip", store, batch_rows=250)
    assert len(pd.read_parquet(store.population_path)) == 600


def test_a_damaged_zip_or_manifest_is_refused(tmp_path):
    import pytest
    pub, _ = _published(tmp_path)
    z = pub / "anonymate-datapakket.zip"
    bad = tmp_path / "kapot.zip"
    bad.write_bytes(z.read_bytes()[:-1] + b"x")
    with pytest.raises(ValueError, match="sha256"):
        datapakket.verify(bad, pub / "manifest.json")
    plain = tmp_path / "zonder.json"
    plain.write_text(json.dumps({"bestanden": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="geen sha256"):
        datapakket.verify(z, plain)


def test_ingest_pakket_without_file_downloads_and_installs(tmp_path, monkeypatch):
    import argparse
    from anonymate import cli, store as st
    pub, _ = _published(tmp_path)
    seen = []

    def fake_fetch(url, **kw):
        seen.append(url)
        return (pub / "manifest.json").read_bytes()

    def fake_download(url, dest, **kw):
        seen.append(url)
        dest.write_bytes((pub / "anonymate-datapakket.zip").read_bytes())
        return dest

    monkeypatch.setattr(st, "fetch", fake_fetch)
    monkeypatch.setattr(st, "download", fake_download)
    monkeypatch.setenv("ANONYMATE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("EPONLINE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)                      # not the developer's own .env, with a key
    args = argparse.Namespace(source="pakket", file=None, home=None, downloads=None,
                              jaar=None, max_tegels=None, tegels_weggooien=False)
    cli.cmd_ingest(args)
    assert seen == [st.DATAPAKKET_MANIFEST_URL, st.DATAPAKKET_URL]
    assert (tmp_path / "home" / "population.parquet").exists()


def test_a_download_that_does_not_match_the_manifest_is_removed(tmp_path, monkeypatch):
    import pytest
    from anonymate import store as st
    pub, _ = _published(tmp_path)
    monkeypatch.setattr(st, "fetch", lambda url, **kw: (pub / "manifest.json").read_bytes())
    monkeypatch.setattr(st, "download", lambda url, dest, **kw: (dest.write_bytes(b"nee"), dest)[1])
    with pytest.raises(ValueError):
        st.download_datapakket(st.Store.open(tmp_path / "s"))
    assert not (tmp_path / "s" / "downloads" / "anonymate-datapakket.zip").exists()


def test_the_manifest_states_the_naming_version(tmp_path):
    out = datapakket.make(_population(tmp_path), tmp_path / "pakket", batch_rows=250)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["namen"] == "physiquant__unit"
    woningen = pq.read_table(out / "woningen.parquet")
    assert woningen.schema.field("huisnummer__str").type == "string"


def _old_format(pkg, dest):
    """The package as published up to 2026-09-30: plain column names, no 'namen' in the manifest,
    house numbers as whole numbers."""
    import pyarrow as pa
    from anonymate import namen
    dest.mkdir()
    for name in ("woningen", "warmtesignatuur"):
        t = pq.read_table(pkg / f"{name}.parquet")
        t = t.rename_columns([namen.NIEUW_NAAR_OUD.get(c, c) for c in t.column_names])
        if "huisnummer" in t.column_names:
            i = t.schema.get_field_index("huisnummer")
            t = t.set_column(i, "huisnummer", pa.array(
                [int(v) for v in t.column("huisnummer").to_pylist()], pa.int64()))
        pq.write_table(t, dest / f"{name}.parquet")
    manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    manifest.pop("namen")
    (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return dest


def test_a_package_in_the_old_format_still_installs(tmp_path):
    from anonymate.store import Store
    pkg = datapakket.make(_population(tmp_path), tmp_path / "pakket", batch_rows=250)
    old = _old_format(pkg, tmp_path / "oud")
    assert {"bouwjaar", "sig_nta8800_H", "huisnummer"} <= set(
        pq.read_table(old / "woningen.parquet").column_names
        + pq.read_table(old / "warmtesignatuur.parquet").column_names)
    new_store, old_store = Store.open(tmp_path / "s-new"), Store.open(tmp_path / "s-old")
    datapakket.install(pkg, new_store, batch_rows=250)
    datapakket.install(old, old_store, batch_rows=250)
    a = pd.read_parquet(new_store.population_path)
    b = pd.read_parquet(old_store.population_path)
    assert list(a.columns) == list(b.columns) and "bouwjaar__yr" in b.columns
    pd.testing.assert_frame_equal(a, b)


def test_a_population_with_old_names_makes_a_package_with_new_names(tmp_path):
    from anonymate import namen
    path = _population(tmp_path)
    t = pq.read_table(path)
    old = tmp_path / "oude-populatie.parquet"
    pq.write_table(t.rename_columns([namen.NIEUW_NAAR_OUD.get(c, c) for c in t.column_names]), old)
    a = datapakket.make(path, tmp_path / "a", batch_rows=250)
    b = datapakket.make(old, tmp_path / "b", batch_rows=250)
    for name in ("woningen", "warmtesignatuur"):
        pd.testing.assert_frame_equal(pq.read_table(a / f"{name}.parquet").to_pandas(),
                                      pq.read_table(b / f"{name}.parquet").to_pandas())


def _totaalbestand(path, ids):
    """An EP-online totaalbestand as EP-online delivers it: a zip with one CSV, preamble first;
    a mix of classes, types and NTA 8800 labels, and for some dwellings an older label first."""
    import zipfile
    head = ("PublicatieDatum;01-09-2026\nLaatstVerwerkteMutatievolgnummer;123\n"
            "Pand_bagverblijfsobjectid;Pand_energieklasse;Pand_gebouwklasse;Pand_gebouwtype;"
            "Pand_gebouwsubtype;Pand_energieindex;Pand_compactheid;"
            "Pand_gebruiksoppervlakte_thermische_zone;Pand_warmtebehoefte;Pand_berekeningstype\n")
    kinds = [("Rijwoning", "tussen"), ("Rijwoning", "hoek"), ("Vrijstaande woning", ""),
             ("2-onder-1-kap", ""), ("Appartement", "")]
    rows = []
    for i, vbo in enumerate(ids):
        if i % 7 == 0:                          # an older label that the newer one replaces
            rows.append(f"{vbo};G;W;Rijwoning;tussen;3,1;;;;\n")
        t, sub = kinds[i % len(kinds)]
        nta = i % 2 == 0
        rows.append(f"{vbo};{'ABCDEFG'[i % 7]}{'++' if i % 11 == 0 else ''};W;{t};{sub};"
                    f"{1 + i % 20 / 10:.2f}".replace(".", ",")
                    + (f";{1.5 + i % 9 / 10:.1f};{80 + i % 60};{60 + i % 90};NTA 8800\n".replace(".", ",")
                       if nta else ";;;;Nader Voorschrift\n"))
    rows.append("9999999999999999;A;U;Kantoor;;0,8;;;;\n")       # not a dwelling: left out
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("v20260901_v4_csv.csv", head + "".join(rows))
    return path


def test_the_browser_joins_ep_online_as_the_desktop_does(tmp_path, monkeypatch):
    """Route 4 in the browser (web.add_eponline on the population from the package) gives the
    same population as the desktop (install with its own raw/ep_online.parquet): label data,
    dwelling types and every signature, over several parts."""
    from anonymate import web
    from anonymate.store import Store, ingest_eponline
    pkg = datapakket.make(_population(tmp_path, n=4_500), tmp_path / "pakket", batch_rows=1_000)
    ids = pq.read_table(pkg / "woningen.parquet", columns=["vbo_id__str"]).column(0).to_pylist()
    ep = _totaalbestand(tmp_path / "v20260901_v4_csv.zip", ids[::2])

    desk = Store.open(tmp_path / "desktop")
    ingest_eponline(desk, ep)
    datapakket.install(pkg, desk, batch_rows=1_000)
    want = pd.read_parquet(desk.population_path)

    los = Store.open(tmp_path / "browser")
    datapakket.install(pkg, los, batch_rows=1_000)          # the package without labels
    monkeypatch.setattr(web, "S", web.Session())
    assert web.open_population(str(los.population_path), {"datapakket": "2026-10"})["labels"] is False
    heard = []
    out = web.add_eponline(str(ep), progress=lambda f, t: heard.append(f), batch_rows=2_048)
    got = web.S.real.con.execute(f"SELECT * FROM {web.S.real.relation}").df()

    assert out["population"] == 4_500 and out["labels"] == len(ids[::2])
    assert "publicatie 01-09-2026" in web.S.real.snapshot.sources["ep-online"]
    assert heard[-1] == 1.0 and heard == sorted(heard)
    assert len(list(Path(web.S.ep_dir).glob("*.parquet"))) >= 2     # in parts
    assert set(got.columns) == set(want.columns)
    got = got.set_index("vbo_id__str").loc[want["vbo_id__str"]]
    want = want.set_index("vbo_id__str")
    for c in want.columns:
        a, b = want[c].astype(object).to_numpy(), got[c].astype(object).to_numpy()
        same = np.array([(pd.isna(x) and pd.isna(y)) or (not pd.isna(x) and not pd.isna(y) and x == y)
                         for x, y in zip(a, b)])
        assert same.all(), f"{c}: {(~same).sum()} verschillen, bv. {a[~same][:3]} tegen {b[~same][:3]}"
    assert (want["woningtype_bron__cat"] == "ep-online").sum() > 1_000
    with pytest.raises(ValueError, match="al"):
        web.add_eponline(str(ep))


def test_the_browser_reuses_a_kept_ep_online_aanvulling(tmp_path, monkeypatch):
    """The page keeps what add_eponline wrote in the browser's storage; use_eponline joins that
    copy to the reopened population and gives the same table, and refuses a copy that has another
    number of rows (it is joined by position)."""
    import shutil
    from anonymate import web
    from anonymate.store import Store
    pkg = datapakket.make(_population(tmp_path, n=3_000), tmp_path / "pakket", batch_rows=1_000)
    ids = pq.read_table(pkg / "woningen.parquet", columns=["vbo_id__str"]).column(0).to_pylist()
    ep = _totaalbestand(tmp_path / "v20260901_v4_csv.zip", ids[::3])
    los = Store.open(tmp_path / "browser")
    datapakket.install(pkg, los, batch_rows=1_000)
    monkeypatch.setattr(web, "S", web.Session())
    web.open_population(str(los.population_path))
    out = web.add_eponline(str(ep), batch_rows=1_024)
    assert out["month"] == "2026-09" and out["dir"] == web.S.ep_dir
    want = web.S.real.con.execute(f"SELECT * FROM {web.S.real.relation}").df()
    kept = shutil.copytree(out["dir"], tmp_path / "bewaard")
    spare = shutil.copytree(kept, tmp_path / "reserve")     # reopening removes the joined copy

    web.open_population(str(los.population_path))            # a new visit: no labels yet
    back = web.use_eponline(str(kept), out["version"])
    got = web.S.real.con.execute(f"SELECT * FROM {web.S.real.relation}").df()
    assert back == {"population": 3_000, "labels": out["labels"], "version": out["version"]}
    pd.testing.assert_frame_equal(got, want)
    assert web.S.real.snapshot.sources["ep-online"] == out["version"]
    with pytest.raises(ValueError, match="al"):
        web.use_eponline(str(kept), out["version"])

    andere = Store.open(tmp_path / "ander")
    (tmp_path / "x").mkdir()
    datapakket.install(datapakket.make(_population(tmp_path / "x", n=2_000), tmp_path / "p2",
                                       batch_rows=1_000), andere, batch_rows=1_000)
    web.open_population(str(andere.population_path))
    with pytest.raises(ValueError, match="andere populatie"):
        web.use_eponline(str(spare), out["version"])


@pytest.mark.parametrize("date, name, month", [
    ("01-09-2026", None, "2026-09"), ("2026-10-01", None, "2026-10"),
    (None, "v20261001_v4_csv.zip", "2026-10"), ("", "totaal.zip", None)])
def test_publication_month(date, name, month):
    from anonymate.web import publication_month
    assert publication_month(date, name) == month


def test_a_wrong_ep_online_file_gets_a_clear_message(tmp_path):
    """The PublicData page also offers xml and xlsx versions and daily mutation files."""
    import zipfile
    from anonymate.eponline import iter_eponline_file
    xml = tmp_path / "v20261001_v4_xml.zip"
    with zipfile.ZipFile(xml, "w") as z:
        z.writestr("v20261001_v4.xml", "<x/>")
    with pytest.raises(ValueError, match="xml- of xlsx"):
        list(iter_eponline_file(xml))
    with pytest.raises(ValueError, match="mutatiebestand"):
        list(iter_eponline_file(_totaalbestand(tmp_path / "d20261002_v4.zip", ["0000010000000001"])))
