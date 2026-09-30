"""Exposed façade per orientation from BAG footprints: sectors, party walls, side façades, the
GeoPackage reader, and ingest -> build."""
import sqlite3
import struct

import numpy as np
import pandas as pd
import pytest

from anonymate import gevel
from anonymate import store as st
from anonymate.signature import GEVEL_COLUMNS, GEVEL_ZIJ_COLUMNS
from tests.test_store import VBO_DDL, gp_point

N, NO, O, ZO, Z, ZW, W, NW = range(8)


def rect(x0, y0, w, h, *, cw=False, angle=0.0):
    pts = np.array([[0, 0], [w, 0], [w, h], [0, h], [0, 0]], dtype=float)
    a = np.radians(angle)
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    pts = pts @ rot.T + [x0, y0]
    return [(pts[::-1] if cw else pts, False)]


def run(panden, own=None):
    pid, *e = gevel.edges_from_rings(panden)
    return gevel.exposed_per_sector(pid, *e, len(panden), own)


def test_square_detached_has_four_sectors():
    total, side = run([rect(0, 0, 10, 10)])
    assert total[0] == pytest.approx([10, 0, 10, 0, 10, 0, 10, 0])


def test_rectangle_lengths_and_ring_direction_does_not_matter():
    for cw in (False, True):
        total, _ = run([rect(0, 0, 12, 8, cw=cw)])
        # 12 m long north and south walls, 8 m east and west walls
        assert total[0] == pytest.approx([12, 0, 8, 0, 12, 0, 8, 0])


def test_rotated_square_faces_the_diagonals():
    total, _ = run([rect(0, 0, 10, 10, angle=45)])
    assert total[0] == pytest.approx([0, 10, 0, 10, 0, 10, 0, 10])
    total, _ = run([rect(0, 0, 10, 10, angle=30)])
    # turned 30 degrees: the walls face 330, 60, 150 and 240 degrees: NW, NE, SE, SW
    assert total[0][[NW, NO, ZO, ZW]] == pytest.approx([10, 10, 10, 10])


def test_party_wall_between_two_adjacent_squares_is_excluded():
    total, _ = run([rect(0, 0, 5, 10), rect(5, 0, 5, 10)])
    assert total[0] == pytest.approx([5, 0, 0, 0, 5, 0, 10, 0])        # east wall shared
    assert total[1] == pytest.approx([5, 0, 10, 0, 5, 0, 0, 0])        # west wall shared


def test_party_wall_with_a_gap_and_with_unequal_edges():
    # 0.3 m between the footprints: still the same wall; a neighbour twice as long shares 10 m
    total, _ = run([rect(0, 0, 5, 10), rect(5.3, -5, 5, 20)])
    assert total[0][O] == pytest.approx(0.0, abs=1e-6)
    # half of the long wall of the big building is shared with the small one
    assert total[1][W] == pytest.approx(10.0, abs=1e-6)
    # a 1 m gap is not a shared wall
    total, _ = run([rect(0, 0, 5, 10), rect(6, 0, 5, 10)])
    assert total[0][O] == pytest.approx(10.0)


def test_a_neighbour_covers_only_the_part_it_touches():
    # a second building stands on the north wall of the first, over 2 m; its side walls run at
    # right angles to that wall and do not count
    total, _ = run([rect(0, 0, 10, 4), rect(4, 4, 2, 6)])
    assert total[0][N] == pytest.approx(10 - 2)     # only the 2 m under the neighbour is covered
    assert total[0][O] == pytest.approx(4)


def test_only_own_buildings_get_a_result():
    total, _ = run([rect(0, 0, 5, 10), rect(5, 0, 5, 10)], own=[True, False])
    assert total[1].sum() == 0 and total[0][O] == 0 and total[0][W] == pytest.approx(10)


def test_side_facades_of_a_terrace_follow_the_main_axis():
    row = [rect(0, 0, 5, 10), rect(5, 0, 5, 10), rect(10, 0, 5, 10)]
    total, side = run(row)
    # the long axis runs south-north (10 m): front and back (5 m, N and S) are no side façades;
    # the exposed 10 m end walls of the two end houses are
    assert side[0] == pytest.approx([0, 0, 0, 0, 0, 0, 10, 0])
    assert side[2] == pytest.approx([0, 0, 10, 0, 0, 0, 0, 0])
    assert side[1].sum() == 0 and total[1].sum() == pytest.approx(10)    # terraced: front + back


def test_detached_house_total_equals_perimeter():
    total, side = run([rect(0, 0, 9, 7)])
    assert total.sum() == pytest.approx(32) and side.sum() == pytest.approx(18)   # the two 9 m walls


def test_hole_edges_face_the_courtyard():
    outer = rect(0, 0, 20, 20)[0][0]
    hole = np.array([[8, 8], [12, 8], [12, 12], [8, 12], [8, 8]], dtype=float)
    total, _ = run([[(outer, False), (hole, True)]])
    # the courtyard's north wall (y = 12) faces south, and so on
    assert total[0] == pytest.approx([24, 0, 24, 0, 24, 0, 24, 0])


# ------------------------------------------------------------------------------------------------
# GeoPackage geometry
# ------------------------------------------------------------------------------------------------

def gp_polygon(rings, *, envelope=False, multi=False, z=False):
    flags = 0b1 | (0b10 if envelope else 0)
    head = b"GP" + bytes([0, flags]) + struct.pack("<i", 28992)
    if envelope:
        allp = np.vstack(rings)
        head += struct.pack("<dddd", allp[:, 0].min(), allp[:, 0].max(), allp[:, 1].min(),
                            allp[:, 1].max())
    code = 1003 if z else 3

    def poly():
        body = struct.pack("<BII", 1, code, len(rings))
        for r in rings:
            body += struct.pack("<I", len(r))
            for x, y in r:
                body += struct.pack("<dd", x, y) + (struct.pack("<d", 5.0) if z else b"")
        return body
    if multi:
        return head + struct.pack("<BII", 1, 6, 1) + poly()
    return head + poly()


@pytest.mark.parametrize("kw", [{}, {"envelope": True}, {"multi": True}, {"z": True}])
def test_gpkg_rings(kw):
    sq = [(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0), (0.0, 0.0)]
    hole = [(1.0, 1.0), (1.0, 2.0), (2.0, 2.0), (1.0, 1.0)]
    rings = gevel.gpkg_rings(gp_polygon([sq, hole], **kw))
    assert [h for _, h in rings] == [False, True]
    assert rings[0][0].shape == (5, 2) and rings[0][0][2].tolist() == [4.0, 3.0]
    assert gevel.gpkg_rings(None) == [] and gevel.gpkg_rings(gp_point(1, 2)) == []


# ------------------------------------------------------------------------------------------------
# ingest -> build
# ------------------------------------------------------------------------------------------------

PAND_DDL = """CREATE TABLE pand (feature_id INTEGER PRIMARY KEY AUTOINCREMENT, geom GEOMETRY,
  identificatie TEXT, status TEXT, bouwjaar INT)"""


def make_gpkg_with_panden(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE gpkg_contents (table_name TEXT, last_change TEXT)")
    con.executemany("INSERT INTO gpkg_contents VALUES (?, ?)",
                    [("verblijfsobject", "2026-09-01T00:00:00Z"), ("pand", "2026-09-01T00:00:00Z")])
    con.execute("CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT)")
    con.execute("INSERT INTO gpkg_geometry_columns VALUES ('pand', 'geom')")
    con.execute("CREATE VIRTUAL TABLE rtree_pand_geom USING rtree(id, minx, maxx, miny, maxy)")
    con.execute(VBO_DDL)
    con.execute(PAND_DDL)

    def ring(x0, y0, w, h):
        return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h), (x0, y0)]
    # a terrace of three houses (east-west row), a flat building, and a shed against house 3
    panden = {"0193100000000001": ring(200000, 500000, 5, 10),
              "0193100000000002": ring(200005, 500000, 5, 10),
              "0193100000000003": ring(200010, 500000, 5, 10),
              "0193100000000004": ring(200030, 500000, 20, 10),
              "0193100000000005": ring(200015, 500002, 3, 3)}          # shed, no dwelling
    for i, (pid, r) in enumerate(panden.items(), 1):
        con.execute("INSERT INTO pand (geom, identificatie, status, bouwjaar) VALUES (?,?,?,?)",
                    (gp_polygon([r]), pid, "Pand in gebruik", 1990))
        xs, ys = [p[0] for p in r], [p[1] for p in r]
        con.execute("INSERT INTO rtree_pand_geom VALUES (?,?,?,?,?)",
                    (i, min(xs), max(xs), min(ys), max(ys)))
    n = 0
    for pid, k in (("0193100000000001", 1), ("0193100000000002", 1), ("0193100000000003", 1),
                   ("0193100000000004", 6)):
        for _ in range(k):
            n += 1
            con.execute(
                "INSERT INTO verblijfsobject (geom, identificatie, oppervlakte, status, "
                "gebruiksdoel, huisnummer, postcode, woonplaats_naam, bouwjaar, "
                "pand_identificatie, nummeraanduiding_hoofdadres_identificatie, "
                "bronhouder_identificatie) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (gp_point(200002.0, 500005.0), f"0193010000{n:06d}", 100,
                 "Verblijfsobject in gebruik", "woonfunctie", n, "8011AB", "Zwolle", 1990, pid,
                 f"0193200000{n:06d}", "0193"))
    con.commit()
    con.close()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("gevel")
    gpkg = root / "bag-light.gpkg"
    make_gpkg_with_panden(gpkg)
    s = st.Store.open(root / "home")
    st.ingest_bag(s, gpkg)
    st.build(s, h3_resolutions=(4,))
    return s


def test_ingest_keeps_a_compact_table_per_single_dwelling_pand(built):
    g = pd.read_parquet(built.raw / "bag_pand_gevel.parquet").set_index("pand_id")
    # the three houses only: the flat building (6 dwellings) and the shed (no dwelling) are
    # neighbours at most
    assert sorted(g.index) == ["0193100000000001", "0193100000000002", "0193100000000003"]
    mid = g.loc["0193100000000002"]
    assert mid["gevel_n__m"] == 5 and mid["gevel_z__m"] == 5
    assert mid["gevel_o__m"] == 0 and mid["gevel_w__m"] == 0
    west = g.loc["0193100000000001"]
    assert west["gevel_w__m"] == 10 and west["gevelzij_w__m"] == 10 and west["gevel_o__m"] == 0
    # the shed shares 3 m of the north... of the east wall of house 3 (y 500002-500005, x 200015)
    east = g.loc["0193100000000003"]
    assert east["gevel_o__m"] == pytest.approx(7)
    assert built.manifest()["sources"]["bag_pand_gevel"]["rows"] == 3


def test_build_joins_area_with_height_fallback(built):
    pop = pd.read_parquet(built.population_path)
    assert set(GEVEL_COLUMNS + GEVEL_ZIJ_COLUMNS) <= set(pop.columns)
    one = pop[pop["pand_id"] == "0193100000000002"].iloc[0]
    # no 3D-BAG: two storeys of 2.8 m
    assert one["gevel_n__m2"] == pytest.approx(5 * 5.6, rel=1e-5)
    assert one["gevel_o__m2"] == 0
    flats = pop[pop["pand_id"] == "0193100000000004"]
    assert flats[GEVEL_COLUMNS].isna().all().all()      # multi-dwelling: no signature, no façade
    assert pop["pand_woningen"].eq(1).sum() == 3


def test_population_without_pand_layer_has_empty_columns(tmp_path):
    from tests.test_store import make_gpkg
    gpkg = tmp_path / "bag-light.gpkg"
    make_gpkg(gpkg)
    s = st.Store.open(tmp_path / "home")
    st.ingest_bag(s, gpkg)
    assert not (s.raw / "bag_pand_gevel.parquet").exists()
    st.build(s, h3_resolutions=(4,))
    pop = pd.read_parquet(s.population_path)
    assert pop[GEVEL_COLUMNS].isna().all().all()


def test_layer_extent_from_the_rtree_root(tmp_path):
    make_gpkg_with_panden(tmp_path / "x.gpkg")
    con = sqlite3.connect(tmp_path / "x.gpkg")
    x0, x1, y0, y1 = st._layer_extent(con, "pand")
    con.close()
    assert (x0, x1, y0, y1) == (200000.0, 200050.0, 500000.0, 500010.0)
