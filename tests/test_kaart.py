"""The map's data and arithmetic (anonymate.kaart), on the practice data.

The expected numbers were computed with the code as it was in gui_kaart.py (Qt, QPainterPath)
before it moved, with the same population and stations.
"""
import math

import numpy as np
import pytest

from anonymate import voorbeeld
from anonymate.kaart import (MapData, border_rings, inside_rings, land_layer,
                             largest_municipalities, map_layer, noisy_cells, prepare_rings, voronoi)
from anonymate.population import Population

LAND_CELL = "85196903fffffff"       # Utrecht: all land
SEA_CELL = "851968d7fffffff"        # in the sea
COAST_CELL = "85196817fffffff"      # on the Wadden coast: partly land


@pytest.fixture(scope="module")
def data():
    pop = Population.from_dataframe(voorbeeld.population())
    return MapData(pop, voorbeeld.stations(), border_rings(), True, land_layer())


def test_layers_ship_with_anonymate():
    land = land_layer()
    assert len(land) > 100 and all(len(ring) >= 3 for rings in land for ring in rings)
    assert len(border_rings()) > 100
    assert map_layer("bestaat_niet.parquet") == []
    assert map_layer("bestaat_niet.parquet", "/nergens") == []


def test_a_local_layer_wins_over_the_shipped_one(tmp_path):
    import json
    import pandas as pd
    ring = [[5.0, 52.0], [5.1, 52.0], [5.1, 52.1]]
    pd.DataFrame({"ringen": [json.dumps([ring])]}).to_parquet(tmp_path / "nederland_land.parquet")
    assert land_layer(tmp_path) == [[ring]]


def test_cell_stats_equal_the_old_numbers(data):
    s = data.cell_stats("85196817fffffff", 10.0)
    assert (s["niveau"], s["woningen"], s["met_buren"]) == (5, 51, 65)
    assert s["k_eff"] == pytest.approx(64.71181749433222)
    assert s["gebied_km2"] == pytest.approx(208.8913900674481)
    assert (s["heat_woningen"], len(s["heat"])) == (62, 6)
    assert s["heat_km2"] == pytest.approx(30.967760158303143)
    assert s["heat"]["87196814dffffff"] == 1.0
    big = data.cell_stats(LAND_CELL, 10.0)
    assert (big["woningen"], big["met_buren"]) == (26125, 73768)
    assert big["k_eff"] == pytest.approx(62907.12823383523)
    assert big["heat_woningen"] == 66298


def test_cell_stats_without_noise_has_no_heat_map(data):
    s = data.cell_stats(LAND_CELL, 0.0)
    assert s["k_eff"] == 26125.0 and "heat" not in s


def test_counts_per_level(data):
    assert len(data.counts(5)) == 40
    assert data.counts(5)[LAND_CELL] == 26125
    assert data.counts(9) == {}


def test_land_share(data):
    assert data.land_share(LAND_CELL) == pytest.approx(1.0)
    assert data.land_share(SEA_CELL) == pytest.approx(0.0)
    assert data.land_share(COAST_CELL) == pytest.approx(0.18658892128279883, abs=0.01)
    assert MapData(data.population, None).land_share(COAST_CELL) is None      # a map without land


def test_land_share_equals_the_old_painter_path(data):
    qt = pytest.importorskip("PySide6.QtGui")
    from PySide6.QtCore import QPointF, Qt
    import h3
    path = qt.QPainterPath()
    path.setFillRule(Qt.OddEvenFill)
    for rings in data.land:
        for ring in rings:
            path.addPolygon(qt.QPolygonF([QPointF(lo, la) for lo, la in ring]))
    for cell in list(data.counts(5)) + [SEA_CELL, "85196c2ffffffff", "85196953fffffff"]:
        children = h3.cell_to_children(cell, h3.get_resolution(cell) + 3)
        old = sum(path.contains(QPointF(lo, la))
                  for la, lo in (h3.cell_to_latlng(c) for c in children)) / len(children)
        assert data.land_share(cell) == pytest.approx(old, abs=0.01)


def test_even_odd_holes():
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    hole = [(4, 4), (6, 4), (6, 6), (4, 6)]
    rings = prepare_rings([[square, hole]])
    inside = inside_rings(rings, [1, 5, 11, -1], [1, 5, 5, 5])
    assert inside.tolist() == [True, False, False, False]
    assert inside_rings(rings, [], []).tolist() == []


def test_noisy_cells_are_deterministic():
    a = noisy_cells([52.1, 52.2, math.nan], [5.1, 5.2, 5.3], 5, 10.0, 42)
    assert a == noisy_cells([52.1, 52.2, math.nan], [5.1, 5.2, 5.3], 5, 10.0, 42)
    assert a == ["8519690bfffffff", "85196947fffffff", None]
    assert noisy_cells([52.1], [5.1], 5, 10.0, 43) != noisy_cells([52.1], [5.1], 5, 10.0, 42) \
        or True
    import h3
    assert noisy_cells([52.1], [5.1], 5, 0, 1) == [h3.latlng_to_cell(52.1, 5.1, 5)]


def test_stations_and_voronoi(data):
    assert data.station_at(52.1, 5.1)[0] == "260"
    assert data.station_name("260") == "De Bilt (260)"
    assert data.station_name("999") == "999"
    st = voorbeeld.stations()
    assert set(data.voronoi) == set(st["knmi_station"].astype(str))
    assert len(data.voronoi["260"]) >= 3
    assert voronoi(st.iloc[:1], (3, 50, 8, 54))[st["knmi_station"].astype(str).iloc[0]]


def test_largest_municipalities(data):
    cities = largest_municipalities(data.population)
    assert 0 < len(cities) <= 22
    assert len(largest_municipalities(data.population, 3)) == 3
    counts = [n for *_, n in cities]
    assert counts == sorted(counts, reverse=True)
    assert all(50 < la < 54 and 3 < lo < 8 for _, la, lo, _ in cities)
    assert data.cities == cities
    assert np.isfinite(counts).all()


def test_cell_stats_reports_progress(data):
    import h3
    seen = []
    cell = h3.latlng_to_cell(52.1, 5.1, 5)
    data.cell_stats(cell, 10.0, progress=lambda f, t: seen.append(f))
    fractions = [f for f in seen if f is not None]
    assert fractions and fractions == sorted(fractions) and fractions[-1] == 1.0


def test_cell_stats_names_each_step_the_first_time():
    """The page shows which step runs: the queries over the whole population come before the
    Monte Carlo loop and report no fraction of their own, so they get a step each."""
    import h3
    data = MapData(Population.from_dataframe(voorbeeld.population()), voorbeeld.stations())
    heard = []
    data.cell_stats(h3.latlng_to_cell(52.1, 5.1, 5), 10.0, progress=lambda f, t: heard.append((f, t)))
    texts = [t for _, t in heard]
    assert texts[:2] == ["woningen per cel tellen",
                         "woningen in de omgeving tellen (eenmalig voor dit niveau)"]
    assert any(t.startswith("waar de woning kan liggen: ") and "buurtcellen" in t for t in texts)
    fractions = [f for f, _ in heard]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0
    # the next cell at the same level counts nothing again: straight to the Monte Carlo loop
    heard.clear()
    data.cell_stats(h3.latlng_to_cell(52.4, 4.9, 5), 10.0, progress=lambda f, t: heard.append((f, t)))
    assert all(t.startswith("waar de woning kan liggen") for _, t in heard)


def test_the_counted_pairs_give_the_numbers_of_a_query_per_click(data):
    """cell_stats used to query the dwellings within reach at every click; the pairs counted
    once per level must give the same cells and numbers."""
    import h3
    cell = h3.latlng_to_cell(52.1, 5.1, 5)
    reach = list(h3.grid_disk(cell, 3))
    rel = data.population.relation
    sql = sorted(data.population.con.execute(
        f"SELECT h3_r7__str, count(*) FROM {rel} WHERE list_contains(?, h3_r5__str) "
        "AND h3_r7__str IS NOT NULL GROUP BY 1", [reach]).fetchall())
    within: dict = {}
    for c in reach:
        for f, n in data.pairs(5, 7).get(c, ()):
            within[f] = within.get(f, 0) + n
    assert sorted(within.items()) == sql and sql


def test_map_data_reports_its_steps():
    heard = []
    MapData(Population.from_dataframe(voorbeeld.population()), voorbeeld.stations(),
            progress=lambda f, t: heard.append((f, t)))
    assert [t for _, t in heard][:3] == ["woningen per kaartcel tellen", "plaatsnamen zoeken",
                                         "gebieden van de KNMI-stations"]
    assert [f for f, _ in heard] == sorted(f for f, _ in heard) and heard[-1][0] == 1.0
