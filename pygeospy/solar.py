"""
pygeospy.solar — Solar analysis and shadow-based geolocation.

Core math delegated to _rustcore.solar; Python layer handles
GeoJSON export, season classification, and cross-module data contracts.
"""
from __future__ import annotations

import json
import math
from typing import Optional

from pygeospy._utils import rustcore, bearing_to_cardinal
from pygeospy._types import SolarResult, Clue, BoundingBox, LatLon

_S = rustcore("solar")


# ── Pure-Python fallbacks ─────────────────────────────────────────────────────

def _py_solar_declination(doy: float) -> float:
    # Correct formula: δ = 23.45 × sin(360/365 × (doy − 81))
    return 23.45 * math.sin(math.radians(360 / 365 * (doy - 81)))


def _py_equation_of_time(doy: float) -> float:
    b = math.radians(360 / 365 * (doy - 81))
    return 9.87 * math.sin(2*b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)


def _py_solar_elevation(lat, lon, doy, hour_utc):
    decl  = math.radians(_py_solar_declination(doy))
    latr  = math.radians(lat)
    # LSTM: Local Standard Time Meridian, based on longitude
    lstm  = 15 * round(lon / 15)
    eot   = _py_equation_of_time(doy)
    lst   = hour_utc + (4*(lon - lstm) + eot) / 60
    ha    = math.radians(15 * (lst - 12))
    sin_el = math.sin(latr)*math.sin(decl) + math.cos(latr)*math.cos(decl)*math.cos(ha)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_el))))


def _py_solar_azimuth(lat, lon, doy, hour_utc):
    decl  = math.radians(_py_solar_declination(doy))
    latr  = math.radians(lat)
    lstm  = 15 * round(lon / 15)
    eot   = _py_equation_of_time(doy)
    lst   = hour_utc + (4*(lon - lstm) + eot) / 60
    ha    = math.radians(15 * (lst - 12))
    sin_el = math.sin(latr)*math.sin(decl) + math.cos(latr)*math.cos(decl)*math.cos(ha)
    el_r   = math.asin(max(-1.0, min(1.0, sin_el)))
    denom  = math.cos(latr) * math.cos(el_r)
    if abs(denom) < 1e-9:
        return 0.0
    cos_az = (math.sin(decl) - math.sin(latr)*math.sin(el_r)) / denom
    az_raw = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))
    return (360 - az_raw) if lst > 12 else az_raw


# ── Public API ────────────────────────────────────────────────────────────────

def solar_elevation(lat: float, lon: float, day_of_year: int, hour_utc: float) -> float:
    """Sun elevation angle (degrees above horizon) at a given place and time."""
    if _S:
        return _S.solar_elevation(lat, lon, float(day_of_year), hour_utc)
    return _py_solar_elevation(lat, lon, day_of_year, hour_utc)


def solar_azimuth(lat: float, lon: float, day_of_year: int, hour_utc: float) -> float:
    """Sun azimuth (degrees, 0=N, 90=E) at a given place and time."""
    if _S:
        return _S.solar_azimuth(lat, lon, float(day_of_year), hour_utc)
    return _py_solar_azimuth(lat, lon, day_of_year, hour_utc)


def shadow_azimuth(sun_azimuth_deg: float) -> float:
    """Shadow points away from sun: shadow_az = (sun_az + 180) % 360."""
    if _S:
        return _S.shadow_azimuth(sun_azimuth_deg)
    return (sun_azimuth_deg + 180) % 360


def shadow_length_ratio(sun_elevation_deg: float) -> float:
    """Shadow-length / object-height ratio from sun elevation."""
    if sun_elevation_deg <= 0:
        return float("inf")
    if _S:
        return _S.shadow_length_ratio(sun_elevation_deg)
    return 1.0 / math.tan(math.radians(sun_elevation_deg))


def elevation_from_shadow(shadow_ratio: float) -> float:
    """
    Infer sun elevation (degrees) from measured shadow-length / object-height ratio.
    shadow_ratio = shadow_length / object_height.
    """
    if shadow_ratio <= 0:
        return 90.0
    if _S:
        return _S.elevation_from_shadow_ratio(shadow_ratio)
    return math.degrees(math.atan(1.0 / shadow_ratio))


def sun_azimuth_from_shadow(shadow_azimuth_deg: float) -> float:
    """Convert a measured shadow azimuth back to sun azimuth."""
    return (shadow_azimuth_deg + 180) % 360


def shadow_cardinal_direction(shadow_azimuth_deg: float) -> str:
    """Return the cardinal direction the shadow is pointing."""
    return bearing_to_cardinal(shadow_azimuth_deg)


def sunrise_sunset(lat: float, lon: float, day_of_year: int) -> tuple[float, float]:
    """
    Approximate sunrise and sunset in UTC decimal hours.
    Returns (NaN, NaN) for polar night / midnight sun.
    """
    if _S:
        return _S.sunrise_sunset(lat, lon, float(day_of_year))
    # Pure-Python fallback
    decl  = math.radians(_py_solar_declination(day_of_year))
    latr  = math.radians(lat)
    cos_ha = -(math.tan(latr) * math.tan(decl))
    if cos_ha < -1 or cos_ha > 1:
        return float("nan"), float("nan")
    ha_deg  = math.degrees(math.acos(cos_ha))
    eot     = _py_equation_of_time(day_of_year)
    lstm    = 15 * round(lon / 15)
    noon    = 12 - (4*(lon - lstm) + eot) / 60
    half    = ha_deg / 15
    return noon - half, noon + half


def solar_noon_utc(lon: float, day_of_year: int) -> float:
    """Approximate solar noon in UTC hours for a given longitude and day."""
    if _S:
        return _S.solar_noon_utc(lon, float(day_of_year))
    eot  = _py_equation_of_time(day_of_year)
    lstm = 15 * round(lon / 15)
    return 12 - (4*(lon - lstm) + eot) / 60


def season_from_shadow(shadow_ratio: float, hemisphere: str = "northern") -> str:
    """
    Estimate season from shadow ratio alone.
    hemisphere: "northern" | "southern".
    Returns "winter" | "spring/autumn" | "summer".
    """
    north = hemisphere.lower().startswith("n")
    if _S:
        return _S.season_from_shadow_ratio(shadow_ratio, north)
    el = elevation_from_shadow(shadow_ratio)
    if el < 30:
        raw = "winter"
    elif el < 60:
        raw = "spring/autumn"
    else:
        raw = "summer"
    if not north:
        raw = {"winter": "summer", "summer": "winter"}.get(raw, raw)
    return raw


# ── Core GEOINT function ──────────────────────────────────────────────────────

def latitude_band_from_shadow(
    shadow_ratio: float,
    shadow_azimuth_deg: float,
    day_of_year: Optional[int] = None,
    hour_utc_hint: float = 12.0,
    tolerance_deg: float = 3.0,
) -> SolarResult:
    """
    Geolocate from shadow ratio and shadow azimuth.

    Parameters
    ----------
    shadow_ratio : float
        Measured shadow_length / object_height.
    shadow_azimuth_deg : float
        Direction the shadow is pointing (degrees, 0=N).
    day_of_year : int, optional
        Day-of-year hint. Defaults to equinox (172).
    hour_utc_hint : float
        Approximate UTC hour of the photo.
    tolerance_deg : float
        Matching tolerance for the latitude sweep.

    Returns
    -------
    SolarResult
    """
    doy = day_of_year or 172  # equinox
    el  = elevation_from_shadow(shadow_ratio)
    sun_az = sun_azimuth_from_shadow(shadow_azimuth_deg)

    # Use Rust sweep if available
    if _S:
        bands = _S.latitude_band_from_solar(el, sun_az, float(doy), hour_utc_hint, tolerance_deg)
    else:
        bands = _sweep_latitudes(el, sun_az, doy, hour_utc_hint, tolerance_deg)

    # Hemisphere hint from sun azimuth at local noon
    # In northern hemisphere, sun is to the south at noon (az ~180)
    # In southern hemisphere, sun is to the north at noon (az ~0/360)
    hemisphere = None
    if 90 < sun_az < 270:
        hemisphere = "northern"
    elif sun_az < 90 or sun_az > 270:
        hemisphere = "southern"

    season = season_from_shadow(shadow_ratio, hemisphere or "northern")

    clues = [
        Clue("solar", "sun_elevation", el, 0.85,
             f"Inferred from shadow ratio {shadow_ratio:.2f}"),
        Clue("solar", "sun_azimuth", sun_az, 0.9,
             f"Inferred from shadow azimuth {shadow_azimuth_deg:.1f}°"),
        Clue("solar", "season", season, 0.7),
    ]
    if hemisphere:
        clues.append(Clue("solar", "hemisphere", hemisphere, 0.75))

    return SolarResult(
        sun_elevation=el,
        sun_azimuth=sun_az,
        shadow_azimuth=shadow_azimuth_deg,
        shadow_length_ratio=shadow_ratio,
        estimated_season=season,
        candidate_lat_bands=bands,
        hemisphere_hint=hemisphere,
        day_of_year_hint=doy,
        clues=clues,
    )


def analyze_shadow(
    shadow_ratio: float,
    shadow_azimuth_deg: float,
    timestamp_utc: Optional[str] = None,
) -> SolarResult:
    """
    Full shadow analysis combining ratio, azimuth, and optional timestamp.

    Parameters
    ----------
    shadow_ratio : float
        shadow_length / object_height from image measurement.
    shadow_azimuth_deg : float
        Direction the shadow is pointing (0=N, clockwise).
    timestamp_utc : str, optional
        ISO-8601 timestamp hint ("2024-06-15T14:30:00Z").

    Returns
    -------
    SolarResult with candidate latitude bands.
    """
    doy, hour_utc = 172, 12.0

    if timestamp_utc:
        from datetime import datetime, timezone
        try:
            dt = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
            doy = dt.timetuple().tm_yday
            hour_utc = dt.hour + dt.minute / 60 + dt.second / 3600
        except ValueError:
            pass

    return latitude_band_from_shadow(shadow_ratio, shadow_azimuth_deg, doy, hour_utc)


def _sweep_latitudes(el, sun_az, doy, hour_utc, tol):
    """Pure-Python latitude sweep (fallback when Rust unavailable)."""
    candidates = []
    lat = -89.5
    while lat <= 89.5:
        lon_est = (12.0 - hour_utc) * 15.0
        calc_el = _py_solar_elevation(lat, lon_est, doy, hour_utc)
        calc_az = _py_solar_azimuth(lat, lon_est, doy, hour_utc)
        if abs(calc_el - el) < tol and abs(calc_az - sun_az) < tol * 2:
            candidates.append(lat)
        lat += 0.5

    if not candidates:
        return []
    bands = []
    start = prev = candidates[0]
    for c in candidates[1:]:
        if c - prev > 1.0:
            bands.append((start, prev))
            start = c
        prev = c
    bands.append((start, prev))
    return bands


# ── GeoJSON export ────────────────────────────────────────────────────────────

def lat_band_to_geojson(
    lat_bands: list[tuple[float, float]],
    lon_min: float = -180.0,
    lon_max: float = 180.0,
) -> dict:
    """
    Export candidate latitude bands as a GeoJSON FeatureCollection of rectangles.
    """
    features = []
    for min_lat, max_lat in lat_bands:
        coords = [
            [lon_min, min_lat],
            [lon_max, min_lat],
            [lon_max, max_lat],
            [lon_min, max_lat],
            [lon_min, min_lat],
        ]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {"min_lat": min_lat, "max_lat": max_lat},
        })
    return {"type": "FeatureCollection", "features": features}


def save_lat_bands(result: SolarResult, path: str) -> None:
    """Save candidate lat bands to a GeoJSON file."""
    gj = lat_band_to_geojson(result.candidate_lat_bands)
    with open(path, "w") as f:
        json.dump(gj, f, indent=2)
    print(f"Saved {len(result.candidate_lat_bands)} lat bands → {path}")
