"""Tests for geoint.terrain — slope, TRI, viewshed (pure-Python fallback)."""
import math
import pytest


# ── Test DEM fixtures ─────────────────────────────────────────────────────────

def flat_dem(n=10, value=100.0):
    return [[value] * n for _ in range(n)]


def sloped_dem(n=10):
    """DEM that increases linearly west to east."""
    return [[float(j * 10) for j in range(n)] for _ in range(n)]


def bowl_dem(n=9):
    """Circular bowl — minimum at centre."""
    centre = n // 2
    dem = []
    for r in range(n):
        row = []
        for c in range(n):
            d = math.sqrt((r - centre)**2 + (c - centre)**2)
            row.append(d * 10.0)
        dem.append(row)
    return dem


# ── Slope and aspect ──────────────────────────────────────────────────────────

def test_slope_flat_dem():
    from pygeospy.terrain import slope_aspect
    dem = flat_dem()
    result = slope_aspect(dem, cell_size_m=30.0)
    # Interior cells should have ~0° slope
    slopes = result["slope"]
    for r in range(1, 9):
        for c in range(1, 9):
            assert slopes[r][c] == pytest.approx(0.0, abs=0.01)


def test_slope_nonzero_on_gradient():
    from pygeospy.terrain import slope_aspect
    dem    = sloped_dem()
    result = slope_aspect(dem, cell_size_m=30.0)
    slopes = result["slope"]
    interior_slopes = [slopes[r][c] for r in range(1, 9) for c in range(1, 9)]
    assert any(s > 0 for s in interior_slopes)


def test_aspect_east_facing_slope():
    from pygeospy.terrain import slope_aspect
    dem    = sloped_dem()  # increases E
    result = slope_aspect(dem, cell_size_m=30.0)
    aspects = result["aspect"]
    # Most interior cells should point east (≈90°)
    for r in range(1, 9):
        for c in range(1, 9):
            asp = aspects[r][c]
            if not math.isnan(asp):
                assert 60 < asp < 120, f"Expected east-facing, got {asp:.1f}°"


# ── TRI ───────────────────────────────────────────────────────────────────────

def test_tri_flat_is_zero():
    from pygeospy.terrain import terrain_ruggedness_index
    dem = flat_dem()
    tri = terrain_ruggedness_index(dem)
    for r in range(1, 9):
        for c in range(1, 9):
            assert tri[r][c] == pytest.approx(0.0, abs=1e-9)


def test_tri_increases_with_relief():
    from pygeospy.terrain import terrain_ruggedness_index
    flat_tri   = terrain_ruggedness_index(flat_dem())
    sloped_tri = terrain_ruggedness_index(sloped_dem())
    flat_mean   = sum(flat_tri[r][c] for r in range(1,9) for c in range(1,9)) / 64
    sloped_mean = sum(sloped_tri[r][c] for r in range(1,9) for c in range(1,9)) / 64
    assert sloped_mean > flat_mean


# ── Viewshed ──────────────────────────────────────────────────────────────────

def test_viewshed_observer_always_visible():
    from pygeospy.terrain import viewshed
    dem = flat_dem()
    vs  = viewshed(dem, 5, 5, 1.8, 30.0)
    assert vs[5][5] is True


def test_viewshed_flat_all_visible():
    from pygeospy.terrain import viewshed
    dem = flat_dem(n=9)
    vs  = viewshed(dem, 4, 4, 1.8, 30.0)
    visible = sum(1 for r in vs for c in r if c)
    assert visible == 81  # all cells visible on flat DEM


def test_viewshed_blocked_by_ridge():
    from pygeospy.terrain import viewshed
    # Build a DEM with a wall between observer (row 0) and target (row 8)
    dem = [[10.0]*10 for _ in range(10)]
    dem[4] = [100.0] * 10  # row 4 is a ridge at elevation 100
    vs  = viewshed(dem, 0, 5, 1.8, 30.0)
    # Cells beyond the ridge (rows 5-9) should be blocked
    assert vs[8][5] is False


# ── Elevation profile ─────────────────────────────────────────────────────────

def test_elevation_profile_length():
    from pygeospy.terrain import elevation_profile
    dem = sloped_dem()
    profile = elevation_profile(dem, [(r, r) for r in range(5)])
    assert len(profile) == 5


def test_elevation_profile_values():
    from pygeospy.terrain import elevation_profile
    dem = sloped_dem(n=10)
    # Along diagonal — col increases → elevation increases
    profile = elevation_profile(dem, [(0, c) for c in range(5)])
    assert profile == sorted(profile), "Profile along gradient should be monotonically increasing"


# ── Focal mean ────────────────────────────────────────────────────────────────

def test_focal_mean_preserves_flat():
    from pygeospy.terrain import focal_mean
    dem = flat_dem(value=50.0)
    out = focal_mean(dem, radius=2)
    for row in out:
        for v in row:
            assert v == pytest.approx(50.0, abs=0.01)
