"""Ingest -> build -> assess on a tiny synthetic GeoPackage with the real PDOK schema. No network."""
import json
import socket
import sqlite3
import struct

import pandas as pd
import pytest

from anonymate import CATALOGUE, QidColumn, Scope, Threshold, assess
from anonymate import store as st
from anonymate.rd import rd_to_wgs84

VBO_DDL = """CREATE TABLE "verblijfsobject" (
  "feature_id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "geom" GEOMETRY,
  "rdf_seealso" TEXT, "identificatie" TEXT, "oppervlakte" INT, "status" TEXT,
  "gebruiksdoel" TEXT, "openbare_ruimte_naam" TEXT, "openbare_ruimte_naam_kort" TEXT,
  "huisnummer" INT, "huisletter" TEXT, "toevoeging" TEXT, "postcode" TEXT,
  "woonplaats_naam" TEXT, "bouwjaar" INT, "pand_identificatie" TEXT, "pandstatus" TEXT,
  "nummeraanduiding_hoofdadres_identificatie" TEXT, "openbare_ruimte_identificatie" TEXT,
  "woonplaats_identificatie" TEXT, "bronhouder_identificatie" TEXT)"""


def gp_point(x, y, envelope=False):
    flags = 0b1 | (0b10 if envelope else 0)
    head = b"GP" + bytes([0, flags]) + struct.pack("<i", 28992)
    env = struct.pack("<dddd", x, x, y, y) if envelope else b""
    return head + env + struct.pack("<BIdd", 1, 1, x, y)


def make_gpkg(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE gpkg_contents (table_name TEXT, last_change TEXT)")
    con.execute("INSERT INTO gpkg_contents VALUES ('verblijfsobject', '2026-09-01T00:00:00Z')")
    con.execute(VBO_DDL)
    rows = []
    n = 0

    def add(k, bouwjaar, opp, pc, pand, gebruik="woonfunctie", status="Verblijfsobject in gebruik",
            gem="0193", x=203000.0, y=503000.0):
        nonlocal n
        for _ in range(k):
            n += 1
            rows.append((gp_point(x, y, envelope=n % 2 == 0), f"0193010000{n:06d}", opp, status,
                         gebruik, n, None, None, pc, "Zwolle", bouwjaar, pand,
                         f"0193200000{n:06d}", gem))

    add(12, 1970, 100, "8011AB", None)       # 12 single-family homes, each own building
    add(1, 1850, 300, "8011AC", None)        # one unique old house
    add(6, 1995, 70, "8012CD", "P-flat")     # six flats in one building
    add(3, 1970, 100, "8011AB", None, gebruik="kantoorfunctie")   # not residential
    add(2, 1970, 100, "8011AB", None, status="Verblijfsobject ingetrokken")  # withdrawn
    add(4, 1970, 100, "7411AA", None, gem="0150", x=207000.0, y=474000.0)  # Deventer
    fixed = []
    for i, r in enumerate(rows):
        pand = r[11] or f"P-{i}"
        fixed.append(r[:11] + (pand,) + r[12:])
    con.executemany(
        'INSERT INTO verblijfsobject (geom, identificatie, oppervlakte, status, gebruiksdoel, '
        'huisnummer, huisletter, toevoeging, postcode, woonplaats_naam, bouwjaar, '
        'pand_identificatie, nummeraanduiding_hoofdadres_identificatie, '
        'bronhouder_identificatie) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', fixed)
    con.commit()
    con.close()


GEBIEDEN = {"features": [
    {"properties": {"code": "0193", "naam": "Zwolle", "ligt_in_provincie_naam": "Overijssel"}},
    {"properties": {"code": "0150", "naam": "Deventer", "ligt_in_provincie_naam": "Overijssel"}},
], "links": []}

KNMI = """# STN         LON(east)   LAT(north)  ALT(m)      NAME
# 260         5.180       52.100      1.90        De Bilt
# 278         6.259       52.435      3.60        Heino
# 285         6.399       53.575      0.00        Huibertgat
# STN,YYYYMMDD,HH,    T
  260,20240101,   12,   72
  278,20240101,   12,   65
  285,20240101,   12,
"""

EP_CSV = ("PublicatieDatum;01-09-2026\nLaatstVerwerkteMutatievolgnummer;123\n"
          "Pand_opnamedatum;Pand_registratiedatum;Pand_postcode;Pand_huisnummer;"
          "Pand_bagverblijfsobjectid;Pand_energieklasse;Pand_gebouwklasse;Pand_gebouwtype;"
          "Pand_gebouwsubtype;Pand_energieindex\n")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("store")
    gpkg = root / "bag-light.gpkg"
    make_gpkg(gpkg)
    csv = root / "ep.csv"
    lines = [EP_CSV]
    for i in range(1, 13):  # homes 1..12 labelled C, 1..3 had an older D label
        lines.append(f"20240101;20240201;8011AB;{i};0193010000{i:06d};C;W;"
                     f"Rijwoning;tussen;1,4\n")
    for i in range(1, 4):
        lines.append(f"20190101;20190201;8011AB;{i};0193010000{i:06d};D;W;Rijwoning;"
                     f"tussen;1,9\n")
    lines.append("2024-01-01;2024-02-01;9999ZZ;1;0000010000000001;A;U;Kantoor;;0,8\n")
    csv.write_text("".join(lines), encoding="utf-8")

    s = st.Store.open(root / "home")
    st.ingest_bag(s, gpkg)
    st.ingest_gebieden(s, fetcher=lambda url, **kw: json.dumps(GEBIEDEN).encode())
    st.ingest_knmi(s, fetcher=lambda url, **kw: KNMI.encode())
    st.ingest_eponline(s, csv)
    st.build(s, h3_resolutions=(4, 7), batch_rows=7)  # several batches
    return s


def test_gpkg_point_with_and_without_envelope():
    assert st.gpkg_point(gp_point(1.5, 2.5)) == (1.5, 2.5)
    assert st.gpkg_point(gp_point(1.5, 2.5, envelope=True)) == (1.5, 2.5)
    assert all(pd.isna(v) for v in st.gpkg_point(None))


def test_rd_to_wgs84_reference_points():
    lat, lon = rd_to_wgs84(155000, 463000)  # Amersfoort, origin of the RD grid
    assert (lat, lon) == pytest.approx((52.15517, 5.38721), abs=1e-5)
    # reference values from pyproj (EPSG:28992 -> EPSG:4326); 1e-5 degrees is about a metre
    for (x, y), ref in {(121687, 487484): (52.374218, 4.898010),
                        (233000, 582000): (53.218925, 6.554963),
                        (176000, 317000): (50.842460, 5.685334),
                        (30000, 385000): (51.440228, 3.589234)}.items():
        assert rd_to_wgs84(x, y) == pytest.approx(ref, abs=1e-5)


def test_population_contents(built):
    pop = pd.read_parquet(built.population_path)
    assert len(pop) == 23  # 12 + 1 + 6 + 4 live residential; office and withdrawn excluded
    assert set(pop["gemeente"]) == {"Zwolle", "Deventer"}
    assert set(pop["provincie"]) == {"Overijssel"}
    zw = pop[pop["postcode6"] == "8011AB"].sort_values("huisnummer")
    assert list(zw["energielabel"].head(3)) == ["C", "C", "C"]  # latest label wins
    assert zw["woningtype"].iloc[0] == "tussenwoning"
    flats = pop[pop["pand_id"] == "P-flat"]
    assert (flats["pand_woningen"] == 6).all() and (~flats["eengezins"]).all()
    assert (flats["woningtype"] == "appartement").all()
    assert set(pop["knmi_station"]) <= {"260", "278"}  # 285 measures no temperature
    assert pop["h3_r4"].notna().all() and pop["h3_r7"].notna().all()
    assert pop["lat"].between(52, 53).all()


def test_manifest_records_versions(built):
    m = built.manifest()
    assert m["sources"]["bag"]["version"] == "2026-09-01T00:00:00Z"
    assert m["sources"]["bag"]["rows"] == 25  # residential incl. withdrawn, before filtering
    assert m["population"]["rows"] == 23
    assert "bag 2026-09-01" in built.snapshot().describe()
    assert m["sources"]["ep-online"]["version"].startswith("publicatie 01-09-2026")
    assert m["sources"]["ep-online"]["LaatstVerwerkteMutatievolgnummer"] == "123"


def test_assess_against_built_store_without_network(built, monkeypatch):
    def no_network(*a, **kw):
        raise AssertionError("assessment must not use the network")
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)

    population = built.population()
    ds = pd.DataFrame({"bouwjaar": [1970, 1850], "oppervlakte": [100, 300],
                       "energielabel": ["C", None], "gemeente": ["Zwolle", "Zwolle"]})
    qids = [QidColumn(c, CATALOGUE[c]) for c in ds.columns]
    a = assess(ds, qids, population, Threshold(0.2))
    assert list(a.records["k_populatie"]) == [12, 1]
    assert "bag" in a.summary()["snapshot"]


def test_h3_resolution_resolved_from_values(built):
    population = built.population()
    cell = pd.read_parquet(built.population_path)["h3_r7"].iloc[0]
    ds = pd.DataFrame({"weer_cel": [cell]})
    a = assess(ds, [QidColumn("weer_cel", CATALOGUE["h3_cel"])], population, Threshold(0.33))
    assert a.records["k_populatie"].iloc[0] >= 1


def test_scope_eengezins(built):
    population = built.population().within(Scope({"eengezins": None}))
    assert population.size() == 23
    single = built.population().within(Scope.region("postcode4", "8011"))
    assert single.size() == 13


def test_eponline_requires_key(tmp_path, monkeypatch):
    monkeypatch.delenv(st.EPONLINE_KEY_ENV, raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    with pytest.raises(RuntimeError, match=st.EPONLINE_KEY_ENV):
        st.ingest_eponline(st.Store.open(tmp_path), fetcher=lambda *a, **k: b"{}")


def test_knmi_parser_skips_stations_without_temperature():
    df = st.parse_knmi_stations(KNMI)
    assert list(df["knmi_station"]) == ["260", "278"]


def test_sqlite_uri_local_and_unc(tmp_path):
    from pathlib import PureWindowsPath
    assert st.sqlite_readonly_uri(PureWindowsPath(r"\\nas\share\bag light.gpkg")) == \
        "file:////nas/share/bag%20light.gpkg?mode=ro"
    assert st.sqlite_readonly_uri(PureWindowsPath(r"C:\data\bag.gpkg")) == \
        "file:///C:/data/bag.gpkg?mode=ro"
    db = tmp_path / "x.gpkg"
    sqlite3.connect(db).execute("CREATE TABLE t (a)").connection.commit()
    con = sqlite3.connect(st.sqlite_readonly_uri(db), uri=True)
    assert con.execute("SELECT count(*) FROM t").fetchone() == (0,)
