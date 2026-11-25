"""Height of shared walls from the 3D-BAG LoD1.3 parts: two semi-detached pairs whose garages
touch are not one terrace of four."""
import gzip
import sqlite3

import numpy as np
import pandas as pd
import pytest

from anonymate import gevel
from anonymate import store as st
from tests.test_gevel import PAND_DDL, gp_polygon
from tests.test_store import VBO_DDL, gp_point

X0, Y0 = 200000.0, 500000.0


def ring(*xy):
    pts = [(X0 + x, Y0 + y) for x, y in xy]
    return pts + [pts[0]]


def box(x0, x1, y0, y1):
    return ring((x0, y0), (x1, y0), (x1, y1), (x0, y1))


# P1 | P2 + garage | garage + P3 | P4: the houses are 10 m deep, the garages 6 m and 3 m high
PANDEN = {
    "0193100000000011": box(0, 6, 0, 10),
    "0193100000000012": ring((6, 0), (15, 0), (15, 6), (12, 6), (12, 10), (6, 10)),
    "0193100000000013": ring((15, 0), (24, 0), (24, 10), (18, 10), (18, 6), (15, 6)),
    "0193100000000014": box(24, 30, 0, 10),
}
# LoD1.3 parts: (pand, footprint, 70th percentile of the roof); ground level 1.0 m
DELEN = [
    ("0193100000000011", box(0, 6, 0, 10), 9.0),
    ("0193100000000012", box(6, 12, 0, 10), 9.0),
    ("0193100000000012", box(12, 15, 0, 6), 4.0),
    ("0193100000000013", box(15, 18, 0, 6), 4.0),
    ("0193100000000013", box(18, 24, 0, 10), 9.0),
    ("0193100000000014", box(24, 30, 0, 10), 9.0),
]


def arrays(rings_by_pand):
    ids = list(rings_by_pand)
    rings = [[(np.array(r, dtype=float), False)] for r in rings_by_pand.values()]
    return ids, rings


def test_part_height_at_takes_the_nearest_part_of_the_same_pand():
    part_pand = np.array([12, 12, 13])
    rings = [[(np.array(box(6, 12, 0, 10), dtype=float), False)],
             [(np.array(box(12, 15, 0, 6), dtype=float), False)],
             []]                                          # pand 13: one part
    h = gevel.part_height_at(
        np.array([X0 + 15, X0 + 6, X0 + 15, X0 + 40, X0 + 15]),
        np.array([Y0 + 3, Y0 + 5, Y0 + 3, Y0 + 3, Y0 + 3]),
        np.array([12, 12, 13, 12, 99]), part_pand, np.array([8.0, 3.0, 5.0]), rings)
    # the garage wall, the house wall, the single part, too far away, an unknown pand
    assert h[:3].tolist() == [3.0, 8.0, 5.0] and np.isnan(h[3]) and np.isnan(h[4])


def test_a_wall_between_garages_is_low():
    ids, rings = arrays(PANDEN)
    pid, *e = gevel.edges_from_rings(rings)
    _, _, (na, nb, length), seg = gevel.exposed_per_sector(
        pid, *e, len(ids), neighbours=True, segments=True)
    assert dict(zip(zip(na.tolist(), nb.tolist()), length.round(6).tolist()))[(1, 2)] == 6.0
    part_pand = np.array([ids.index(p) for p, _, _ in DELEN])
    part_rings = [[(np.array(r, dtype=float), False)] for _, r, _ in DELEN]
    hoogte = np.array([h - 1.0 for _, _, h in DELEN])
    a, b, tot, high, known = gevel.high_wall_length(*seg, part_pand, hoogte, part_rings)
    got = {(int(i), int(j)): (round(t, 6), round(hh, 6)) for i, j, t, hh in zip(a, b, tot, high)}
    assert got[(0, 1)] == (10.0, 10.0)            # house against house: 8 m high
    assert got[(1, 2)] == (6.0, 0.0)              # garage against garage: 3 m high
    assert got[(2, 3)] == (10.0, 10.0)
    assert known.sum() == pytest.approx(tot.sum())
    # a terrace of bungalows (every part 3 m high): the walls are as high as the houses, so they
    # count
    a, b, tot, high, known = gevel.high_wall_length(*seg, part_pand, np.full(len(DELEN), 3.0),
                                                    part_rings)
    assert high.tolist() == tot.tolist()
    # an unknown height counts as high: without the parts every wall counts
    _, _, tot0, high0, known0 = gevel.high_wall_length(*seg, np.zeros(0, dtype=int),
                                                       np.zeros(0), [])
    assert high0.tolist() == tot0.tolist() and known0.sum() == 0


def make_bag(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE gpkg_contents (table_name TEXT, last_change TEXT)")
    con.executemany("INSERT INTO gpkg_contents VALUES (?, ?)",
                    [("verblijfsobject", "2026-09-01T00:00:00Z"),
                     ("pand", "2026-09-01T00:00:00Z")])
    con.execute("CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT)")
    con.execute("INSERT INTO gpkg_geometry_columns VALUES ('pand', 'geom')")
    con.execute("CREATE VIRTUAL TABLE rtree_pand_geom USING rtree(id, minx, maxx, miny, maxy)")
    con.execute(VBO_DDL)
    con.execute(PAND_DDL)
    for i, (pid, r) in enumerate(PANDEN.items(), 1):
        con.execute("INSERT INTO pand (geom, identificatie, status, bouwjaar) VALUES (?,?,?,?)",
                    (gp_polygon([r]), pid, "Pand in gebruik", 1975))
        xs, ys = [p[0] for p in r], [p[1] for p in r]
        con.execute("INSERT INTO rtree_pand_geom VALUES (?,?,?,?,?)",
                    (i, min(xs), max(xs), min(ys), max(ys)))
        con.execute(
            "INSERT INTO verblijfsobject (geom, identificatie, oppervlakte, status, gebruiksdoel, "
            "huisnummer, postcode, woonplaats_naam, bouwjaar, pand_identificatie, "
            "nummeraanduiding_hoofdadres_identificatie, bronhouder_identificatie) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (gp_point(min(xs) + 1, Y0 + 5), f"0193010000{i:06d}", 120,
             "Verblijfsobject in gebruik", "woonfunctie", i, "8011AB", "Zwolle", 1975, pid,
             f"0193200000{i:06d}", "0193"))
    con.commit()
    con.close()


def make_3dbag_tile(path, delen=DELEN):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE pand (fid INTEGER PRIMARY KEY, identificatie TEXT, "
                "b3_h_maaiveld REAL)")
    con.execute("CREATE TABLE lod13_2d (fid INTEGER PRIMARY KEY, geom BLOB, identificatie TEXT, "
                "b3_h_70p REAL)")
    for pid in dict.fromkeys(p for p, _, _ in delen):
        con.execute("INSERT INTO pand VALUES (NULL, ?, 1.0)", (f"NL.IMBAG.Pand.{pid}",))
    for pid, r, h in delen:
        con.execute("INSERT INTO lod13_2d VALUES (NULL, ?, ?, ?)",
                    (gp_polygon([r]), f"NL.IMBAG.Pand.{pid}", h))
    con.commit()
    con.close()


def types(s):
    st.build(s, h3_resolutions=(4,))
    pop = pd.read_parquet(s.population_path).set_index("pand_id__str")
    return pop["woningtype__cat"].to_dict()


@pytest.fixture(scope="module")
def bag_only(tmp_path_factory):
    root = tmp_path_factory.mktemp("muur")
    make_bag(root / "bag-light.gpkg")
    s = st.Store.open(root / "home", root / "nas")
    st.ingest_bag(s, root / "bag-light.gpkg")
    return s, root


def test_without_the_3dbag_the_garages_make_a_terrace(bag_only):
    s, _ = bag_only
    walls = pd.read_parquet(s.raw / "bag_pand_muren.parquet")
    assert {"pand_a", "pand_b", "x1", "y1", "x2", "y2", "lengte", "cel"} <= set(walls.columns)
    assert walls.cel.nunique() == 1
    assert types(s) == {"0193100000000011": "hoekwoning", "0193100000000012": "tussenwoning",
                        "0193100000000013": "tussenwoning", "0193100000000014": "hoekwoning"}
    assert s.manifest()["sources"]["bag_pand_buren"]["muurhoogte"].startswith("geen")


def test_with_the_3dbag_parts_they_are_two_semi_detached_pairs(bag_only):
    s, root = bag_only
    tiles = root / "tegels"
    tiles.mkdir()
    make_3dbag_tile(root / "t.gpkg")
    (tiles / "t.gpkg.gz").write_bytes(gzip.compress((root / "t.gpkg").read_bytes()))
    st.ingest_3dbag_delen(s, tiles)
    delen = pd.read_parquet(s.raw / "3dbag_delen.parquet")
    # a pand with one part keeps no footprint, only its height above the ground
    single = delen[delen.pand_id == 193100000000011].iloc[0]
    assert single.geom is None and single.hoogte == pytest.approx(8.0)
    assert (delen.pand_id == 193100000000012).sum() == 2
    assert types(s) == {p: "twee_onder_een_kap" for p in PANDEN}
    buren = s.manifest()["sources"]["bag_pand_buren"]
    assert buren["muurhoogte"].startswith("minstens 4 m") and buren["muur_met_hoogte"] == 1.0
    # the BAG once more (a new month): the parts are used again straight away
    st.ingest_bag(s, root / "bag-light.gpkg")
    assert types(s) == {p: "twee_onder_een_kap" for p in PANDEN}
    # and 'anonymate ingest buren' with a lower threshold joins them again
    st.neighbours_from_walls(s, threshold=2.5)
    assert types(s)["0193100000000012"] == "tussenwoning"
