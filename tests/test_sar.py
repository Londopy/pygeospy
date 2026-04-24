"""Tests for geoint.sar — grid generation and SAR utilities."""
import pytest


def test_search_grid_returns_features():
    from pygeospy.sar import search_grid
    features = search_grid(47.6, -122.3, radius_km=1.0, cell_km=0.5)
    assert len(features) > 0
    for f in features:
        assert f["type"] == "Feature"
        assert f["geometry"]["type"] == "Polygon"
        assert "sector" in f["properties"]


def test_search_grid_cell_count():
    """2km radius, 0.5km cell → 4×4 = 16 cells."""
    from pygeospy.sar import search_grid
    features = search_grid(0, 0, radius_km=1.0, cell_km=0.5)
    assert len(features) == 16


def test_corridor_search_segments():
    from pygeospy.sar import corridor_search
    waypoints = [(47.6, -122.3), (47.61, -122.3), (47.62, -122.3)]
    segs = corridor_search(waypoints, width_km=0.1)
    assert len(segs) == 2  # 3 points → 2 segments
    for seg in segs:
        assert seg["geometry"]["type"] == "Polygon"


def test_poa_zones_ring_count():
    from pygeospy.sar import poa_zones
    zones = poa_zones(47.6, -122.3, profile="hiker")
    assert len(zones) == 5  # default 5 rings
    for z in zones:
        assert "radius_km" in z["properties"]
        assert z["geometry"]["type"] == "Polygon"


def test_lost_person_radius_hiker():
    from pygeospy.sar import lost_person_radius
    typical, max_r = lost_person_radius("hiker")
    assert typical > 0
    assert max_r > typical


def test_lost_person_radius_child():
    from pygeospy.sar import lost_person_radius
    typical_child, _ = lost_person_radius("child_1_3")
    typical_adult, _ = lost_person_radius("hiker")
    assert typical_child < typical_adult


def test_urgency_score_range():
    from pygeospy.sar import urgency_score
    low  = urgency_score(30, False, 2.0, False, False, False)
    high = urgency_score(80, True,  12.0, True,  True,  True)
    assert 0 <= low["score"]  <= 10
    assert 0 <= high["score"] <= 10
    assert high["score"] > low["score"]


def test_urgency_score_never_exceeds_10():
    from pygeospy.sar import urgency_score
    s = urgency_score(5, True, 24.0, True, True, True)
    assert s["score"] <= 10.0


def test_expanding_square_waypoint_count():
    from pygeospy.sar import expanding_square
    wps = expanding_square(47.6, -122.3, leg_spacing_km=0.1, legs=8)
    # Start + 8 legs = 9 waypoints
    assert len(wps) == 9


def test_expanding_square_starts_at_ipp():
    from pygeospy.sar import expanding_square
    ipp_lat, ipp_lon = 47.6, -122.3
    wps = expanding_square(ipp_lat, ipp_lon, 0.1, 4)
    assert wps[0][0] == pytest.approx(ipp_lat, abs=1e-9)
    assert wps[0][1] == pytest.approx(ipp_lon, abs=1e-9)


def test_poa_zones_custom_radii():
    from pygeospy.sar import poa_zones
    zones = poa_zones(0, 0, radii_km=[1.0, 5.0, 10.0])
    assert len(zones) == 3
    assert zones[0]["properties"]["radius_km"] == 1.0
    assert zones[2]["properties"]["radius_km"] == 10.0
