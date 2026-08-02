"""Tests for pygeospy.coords — pure math, no network I/O."""
import pytest


# ── Haversine ─────────────────────────────────────────────────────────────────

def test_haversine_known_distance():
    """London to Paris ≈ 341 km."""
    from pygeospy.coords import haversine
    d = haversine(51.5074, -0.1278, 48.8566, 2.3522)
    assert 335 < d < 345, f"Expected ~341 km, got {d:.1f}"


def test_haversine_same_point():
    from pygeospy.coords import haversine
    assert haversine(0, 0, 0, 0) == pytest.approx(0.0, abs=1e-9)


def test_haversine_antipodal():
    """Antipodal points ≈ π × 6371 km ≈ 20015 km."""
    from pygeospy.coords import haversine
    d = haversine(0, 0, 0, 180)
    assert 20000 < d < 20030


def test_haversine_equator():
    """1 degree of longitude on equator ≈ 111.32 km."""
    from pygeospy.coords import haversine
    d = haversine(0, 0, 0, 1)
    assert 111.0 < d < 111.7


# ── Bearing ───────────────────────────────────────────────────────────────────

def test_bearing_north():
    from pygeospy.coords import bearing
    b = bearing(0, 0, 1, 0)
    assert b == pytest.approx(0.0, abs=0.1)


def test_bearing_east():
    from pygeospy.coords import bearing
    b = bearing(0, 0, 0, 1)
    assert b == pytest.approx(90.0, abs=0.2)


def test_bearing_south():
    from pygeospy.coords import bearing
    b = bearing(1, 0, 0, 0)
    assert b == pytest.approx(180.0, abs=0.1)


def test_bearing_west():
    from pygeospy.coords import bearing
    b = bearing(0, 1, 0, 0)
    assert b == pytest.approx(270.0, abs=0.1)


# ── Destination point ─────────────────────────────────────────────────────────

def test_destination_north():
    from pygeospy.coords import destination, haversine
    origin = (0.0, 0.0)
    dest   = destination(0, 0, 0, 100)
    back   = haversine(*origin, dest.lat, dest.lon)
    assert back == pytest.approx(100.0, rel=0.001)


def test_destination_roundtrip():
    """Destination 500 km bearing 45° should be ~500 km from origin."""
    from pygeospy.coords import destination, haversine
    d = destination(48.85, 2.35, 45.0, 500.0)
    dist = haversine(48.85, 2.35, d.lat, d.lon)
    assert dist == pytest.approx(500.0, rel=0.002)


# ── Midpoint ──────────────────────────────────────────────────────────────────

def test_midpoint_equator():
    from pygeospy.coords import midpoint
    mid = midpoint(0, -90, 0, 90)
    assert mid.lat == pytest.approx(0.0, abs=0.01)
    assert mid.lon == pytest.approx(0.0, abs=0.01)


def test_midpoint_distance():
    """Midpoint should be equidistant from both endpoints."""
    from pygeospy.coords import midpoint, haversine
    p1, p2 = (48.85, 2.35), (51.51, -0.13)
    mid = midpoint(*p1, *p2)
    d1  = haversine(*p1, mid.lat, mid.lon)
    d2  = haversine(*p2, mid.lat, mid.lon)
    assert d1 == pytest.approx(d2, rel=0.01)


# ── Bounding box ──────────────────────────────────────────────────────────────

def test_bounding_box_contains_centre():
    from pygeospy.coords import bounding_box
    bb = bounding_box(48.85, 2.35, 10.0)
    assert bb.contains(48.85, 2.35)


def test_bounding_box_excludes_far():
    from pygeospy.coords import bounding_box
    bb = bounding_box(48.85, 2.35, 1.0)
    assert not bb.contains(51.5, -0.1)  # London is ~341 km away


# ── DMS conversions ───────────────────────────────────────────────────────────

def test_dd_to_dms_positive():
    from pygeospy.coords import dd_to_dms
    deg, mn, sec, sign = dd_to_dms(51.5)
    assert deg == 51
    assert mn  == 30
    assert sec == pytest.approx(0.0, abs=0.01)
    assert sign == "+"


def test_dms_roundtrip():
    from pygeospy.coords import dd_to_dms, dms_to_dd
    original = -33.8688
    deg, mn, sec, sign = dd_to_dms(original)
    back = dms_to_dd(deg, mn, sec, "S")
    assert back == pytest.approx(original, abs=1e-5)


# ── UTM conversion ────────────────────────────────────────────────────────────

def test_utm_zone_london():
    from pygeospy.coords import latlon_to_utm
    result = latlon_to_utm(51.5, -0.1)
    assert result["zone"].startswith("30")
    assert 400_000 < result["easting"] < 600_000


def test_utm_zone_new_york():
    from pygeospy.coords import latlon_to_utm
    result = latlon_to_utm(40.71, -74.01)
    assert result["zone"].startswith("18")


# ── Validation ────────────────────────────────────────────────────────────────

def test_invalid_latitude():
    from pygeospy.coords import haversine
    with pytest.raises(ValueError):
        haversine(91, 0, 0, 0)


def test_invalid_longitude():
    from pygeospy.coords import haversine
    with pytest.raises(ValueError):
        haversine(0, 0, 0, 181)


# ── Batch haversine ───────────────────────────────────────────────────────────

def test_batch_haversine():
    from pygeospy.coords import batch_haversine, haversine
    origin = (51.5, -0.1)
    points = [(48.85, 2.35), (40.71, -74.01), (35.68, 139.69)]
    batch  = batch_haversine(*origin, points)
    single = [haversine(*origin, *p) for p in points]
    for b, s in zip(batch, single):
        assert b == pytest.approx(s, rel=1e-6)
