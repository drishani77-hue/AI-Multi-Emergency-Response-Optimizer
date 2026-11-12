import pytest

from backend.road_engine import RoadEngine


@pytest.fixture(scope="module")
def engine():
    road_engine = RoadEngine()
    yield road_engine
    road_engine.close()


def test_engine_loads_complete_road_graph(engine):
    assert engine.node_count == 118628
    assert engine.edge_count == 241998


def test_dijkstra_returns_valid_route(engine):
    result = engine.route(
        source_osm_id=10013517538,
        destination_osm_id=2365388391,
    )

    assert result["node_count"] == 739
    assert result["nodes"][0] == 10013517538
    assert result["nodes"][-1] == 2365388391
    assert result["distance_metres"] == pytest.approx(
        30840.91, abs=0.01
    )
    assert result["distance_km"] == pytest.approx(
        30.84091, abs=0.00001
    )


def test_dijkstra_returns_valid_reverse_route(engine):
    result = engine.route(
        source_osm_id=2365388391,
        destination_osm_id=10013517538,
    )

    assert result["node_count"] == 762
    assert result["nodes"][0] == 2365388391
    assert result["nodes"][-1] == 10013517538
    assert result["distance_metres"] == pytest.approx(
        31190.00, abs=0.01
    )


def test_dijkstra_same_source_and_destination(engine):
    result = engine.route(
        source_osm_id=2365388391,
        destination_osm_id=2365388391,
    )

    assert result["nodes"] == [2365388391]
    assert result["node_count"] == 1
    assert result["distance_metres"] == 0.0


def test_dijkstra_rejects_unknown_osm_node(engine):
    with pytest.raises(ValueError, match="OSM node"):
        engine.route(
            source_osm_id=99999999999999,
            destination_osm_id=2365388391,
        )


def test_resource_ranking_orders_by_road_distance(engine):
    candidates = [
        {
            "resource_id": "res_west",
            "base_osm_id": 10013517538,
        },
        {
            "resource_id": "res_east",
            "base_osm_id": 2365388391,
        },
        {
            "resource_id": "res_unknown",
            "base_osm_id": 99999999999999,
        },
    ]

    results = engine.rank_resources(
        emergency_osm_id=2365388391,
        candidates=candidates,
    )

    assert [item["resource_id"] for item in results] == [
        "res_east",
        "res_west",
    ]

    assert results[0]["distance_metres"] == 0.0
    assert results[1]["distance_metres"] == pytest.approx(
        30840.91, abs=0.01
    )


def test_resource_ranking_uses_resource_id_for_ties(engine):
    candidates = [
        {
            "resource_id": "res_zeta",
            "base_osm_id": 2365388391,
        },
        {
            "resource_id": "res_alpha",
            "base_osm_id": 2365388391,
        },
    ]

    results = engine.rank_resources(
        emergency_osm_id=2365388391,
        candidates=candidates,
    )

    assert [item["resource_id"] for item in results] == [
        "res_alpha",
        "res_zeta",
    ]


def test_resource_ranking_handles_empty_candidates(engine):
    results = engine.rank_resources(
        emergency_osm_id=2365388391,
        candidates=[],
    )

    assert results == []


def test_engine_supports_repeated_route_calls(engine):
    first = engine.route(
        source_osm_id=10013517538,
        destination_osm_id=2365388391,
    )

    second = engine.route(
        source_osm_id=10013517538,
        destination_osm_id=2365388391,
    )

    assert first == second
