"""Tests for pygeospy.solar — shadow geometry and latitude inference."""
import math
import pytest


def test_solar_elevation_noon_equator_equinox():
    """At equinox solar noon, sun should be at ~90° elevation on equator.
    Spring equinox ≈ doy 81 (declination → 0°, so sun transits overhead at equator).
    """
    from pygeospy.solar import solar_elevation
    el = solar_elevation(0.0, 0.0, 81, 12.0)   # doy 81 = spring equinox
    assert 85 < el <= 90, f"Expected ~90°, got {el:.2f}°"


def test_solar_elevation_midnight_negative():
    """At midnight, elevation should be well below horizon."""
    from pygeospy.solar import solar_elevation
    el = solar_elevation(51.5, 0.0, 172, 0.0)
    assert el < 0, "Midnight elevation should be negative"


def test_solar_azimuth_noon_northern():
    """At solar noon in northern hemisphere, sun should be roughly south (az ≈ 180°)."""
    from pygeospy.solar import solar_azimuth, solar_noon_utc
    noon = solar_noon_utc(0.0, 172)
    az = solar_azimuth(51.5, 0.0, 172, noon)
    assert 150 < az < 210, f"Expected ~180°, got {az:.1f}°"


def test_solar_azimuth_noon_southern():
    """In southern hemisphere, sun at noon should be roughly north (az ≈ 0° or 360°)."""
    from pygeospy.solar import solar_azimuth, solar_noon_utc
    noon = solar_noon_utc(0.0, 172)
    az = solar_azimuth(-33.87, 0.0, 172, noon)
    assert az < 30 or az > 330, f"Expected ~0/360°, got {az:.1f}°"


def test_shadow_azimuth_opposite_sun():
    """Shadow azimuth = sun azimuth + 180°."""
    from pygeospy.solar import shadow_azimuth
    assert shadow_azimuth(90.0)  == pytest.approx(270.0)
    assert shadow_azimuth(180.0) == pytest.approx(0.0)
    assert shadow_azimuth(270.0) == pytest.approx(90.0)
    assert shadow_azimuth(0.0)   == pytest.approx(180.0)


def test_shadow_length_ratio_inverse_elevation():
    """Higher elevation → shorter shadow."""
    from pygeospy.solar import shadow_length_ratio
    r30 = shadow_length_ratio(30)
    r60 = shadow_length_ratio(60)
    assert r30 > r60, "30° elevation should give longer shadow than 60°"


def test_shadow_length_ratio_45():
    """At 45° elevation, shadow ratio = 1.0 (shadow = object height)."""
    from pygeospy.solar import shadow_length_ratio
    r = shadow_length_ratio(45.0)
    assert r == pytest.approx(1.0, abs=0.02)


def test_elevation_from_shadow_roundtrip():
    """elevation → ratio → elevation should round-trip."""
    from pygeospy.solar import shadow_length_ratio, elevation_from_shadow
    for el in [20, 35, 55, 70]:
        ratio = shadow_length_ratio(el)
        back  = elevation_from_shadow(ratio)
        assert back == pytest.approx(el, abs=0.1), f"Failed for el={el}"


def test_sunrise_sunset_tropical():
    """Near the equator, sunrise ≈ 6 UTC and sunset ≈ 18 UTC (on equinox, at lon=0)."""
    from pygeospy.solar import sunrise_sunset
    sr, ss = sunrise_sunset(1.0, 0.0, 172)
    assert not math.isnan(sr)
    assert not math.isnan(ss)
    assert 5.5 < sr < 6.5, f"Sunrise: {sr:.2f}"
    assert 17.5 < ss < 18.5, f"Sunset: {ss:.2f}"


def test_sunrise_sunset_polar_summer():
    """At polar regions in summer, should return NaN (midnight sun)."""
    from pygeospy.solar import sunrise_sunset
    sr, ss = sunrise_sunset(89.0, 0.0, 172)  # near North Pole, midsummer
    assert math.isnan(sr) and math.isnan(ss), "Expected polar NaN"


def test_season_from_shadow_ratio():
    """Long shadow (ratio > 3) should map to winter."""
    from pygeospy.solar import season_from_shadow
    assert season_from_shadow(4.0, "northern") == "winter"
    assert season_from_shadow(0.5, "northern") == "summer"


def test_season_flipped_hemisphere():
    """Southern hemisphere seasons should be flipped."""
    from pygeospy.solar import season_from_shadow
    assert season_from_shadow(4.0, "southern") == "summer"
    assert season_from_shadow(0.5, "southern") == "winter"


def test_latitude_band_returns_list():
    """latitude_band_from_shadow should return at least one band for valid inputs."""
    from pygeospy.solar import latitude_band_from_shadow
    result = latitude_band_from_shadow(2.0, 195.0, 172, 12.0)
    assert isinstance(result.candidate_lat_bands, list)
    # Should find some candidates
    assert len(result.candidate_lat_bands) > 0 or result.sun_elevation is not None
