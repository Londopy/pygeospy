"""
geoint.chronos — Temporal analysis: when was this taken?
Combines shadow analysis, vegetation state, weather archive, and metadata hints.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from geoint._types import Clue
from geoint.solar import elevation_from_shadow, solar_elevation, sunrise_sunset

logger = logging.getLogger("geoint.chronos")


# ── Time-of-day from shadow ───────────────────────────────────────────────────

def time_from_shadow(
    shadow_ratio: float,
    shadow_azimuth_deg: float,
    lat: float,
    lon: float,
    day_of_year: int = 172,
    tolerance_hours: float = 0.5,
) -> list[float]:
    """
    Estimate UTC time of day from shadow geometry at a known location.
    Returns a list of candidate UTC hours (typically 1–2 values, AM and PM).

    Parameters
    ----------
    shadow_ratio : float
        shadow_length / object_height
    shadow_azimuth_deg : float
        Direction shadow points (0=N)
    lat, lon : float
        Known or estimated location
    day_of_year : int
    tolerance_hours : float
        Search resolution
    """
    target_el  = elevation_from_shadow(shadow_ratio)
    target_az  = (shadow_azimuth_deg + 180) % 360  # sun azimuth

    candidates = []
    hour = 5.0
    while hour <= 20.0:
        calc_el = solar_elevation(lat, lon, day_of_year, hour)
        if abs(calc_el - target_el) < 3.0:  # ±3 degrees elevation tolerance
            candidates.append(round(hour, 2))
        hour += 0.1

    return candidates


# ── Season from image signals ─────────────────────────────────────────────────

def season_from_signals(
    snow_present: bool = False,
    dry_grass: bool = False,
    green_leaves: bool = False,
    bare_trees: bool = False,
    lat_hint: Optional[float] = None,
) -> dict:
    """
    Estimate season from visual environmental signals.
    Returns {"season": str, "hemisphere_hint": str, "doy_range": (int, int)}.
    """
    # Northern hemisphere seasons: winter=DEC-FEB, spring=MAR-MAY, summer=JUN-AUG, autumn=SEP-NOV
    nh_seasons = {"winter": (335, 60), "spring": (60, 152), "summer": (152, 244), "autumn": (244, 335)}

    season = "unknown"
    doy_range = (1, 365)

    if snow_present:
        season = "winter"
        doy_range = (335, 60)  # wraps
    elif bare_trees and not green_leaves:
        season = "late_autumn_or_early_spring"
        doy_range = (60, 120)
    elif green_leaves and not dry_grass:
        season = "spring_or_summer"
        doy_range = (91, 244)
    elif dry_grass and not green_leaves:
        season = "late_summer_or_autumn"
        doy_range = (182, 335)

    # Hemisphere inference: if lat hint given, flip for southern
    hemisphere = "northern"
    if lat_hint is not None and lat_hint < 0:
        hemisphere = "southern"
        # Southern hemisphere seasons are reversed
        southern_map = {"winter": "summer", "summer": "winter",
                        "spring_or_summer": "autumn_or_winter",
                        "late_summer_or_autumn": "late_winter_or_spring"}
        season = southern_map.get(season, season)

    return {"season": season, "hemisphere_hint": hemisphere, "doy_range": doy_range}


# ── Vehicle model year estimation ─────────────────────────────────────────────

def estimate_photo_era_from_vehicles(vehicle_descriptions: list[str]) -> dict:
    """
    Rough photo era estimation from vehicle models described in the image.
    Returns {"min_year": int, "max_year": int, "notes": str}.
    """
    # Very rough heuristics; real implementation would use a model-year database
    year_hints = []
    for desc in vehicle_descriptions:
        d = desc.lower()
        if any(k in d for k in ("horse", "cart", "wagon")):
            year_hints.append((1800, 1940))
        elif any(k in d for k in ("model t", "model a", "ford t")):
            year_hints.append((1908, 1931))
        elif any(k in d for k in ("beetle", "vw bug")):
            year_hints.append((1938, 2003))
        elif "digital" in d or "smartphone" in d:
            year_hints.append((2007, 2030))
        elif any(k in d for k in ("tesla", "electric", "ev", "bev")):
            year_hints.append((2010, 2030))

    if not year_hints:
        return {"min_year": 1950, "max_year": 2030, "notes": "No specific vehicle era detected"}

    min_year = min(y[0] for y in year_hints)
    max_year = max(y[1] for y in year_hints)
    return {"min_year": min_year, "max_year": max_year, "notes": f"Based on {len(year_hints)} vehicles"}


# ── Weather archive lookup ────────────────────────────────────────────────────

def weather_on_date(lat: float, lon: float, date_str: str) -> dict:
    """
    Fetch historical weather for a location and date via Meteostat API.
    date_str: "YYYY-MM-DD"
    Returns dict with temperature, precipitation, cloud cover.
    """
    try:
        from datetime import date as _date
        import httpx

        dt = _date.fromisoformat(date_str)
        start = dt.strftime("%Y-%m-%d")

        # Nearest station via Meteostat
        stations_url = "https://meteostat.p.rapidapi.com/stations/nearby"
        params = {"lat": lat, "lon": lon, "limit": 1}
        # Note: Meteostat requires RapidAPI key; graceful fallback if unavailable
        headers = {"X-RapidAPI-Host": "meteostat.p.rapidapi.com",
                   "X-RapidAPI-Key": __import__("os").environ.get("RAPIDAPI_KEY", "")}
        resp = httpx.get(stations_url, params=params, headers=headers, timeout=10)
        if resp.status_code == 401 or resp.status_code == 403:
            return {"error": "Meteostat API key required (set RAPIDAPI_KEY env var)"}
        resp.raise_for_status()
        stations = resp.json().get("data", [])
        if not stations:
            return {"error": "No nearby station found"}

        station_id = stations[0]["id"]
        daily_url  = "https://meteostat.p.rapidapi.com/stations/daily"
        params = {"station": station_id, "start": start, "end": start}
        resp = httpx.get(daily_url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", [{}])[0]
        return {
            "date":        date_str,
            "tavg_c":      data.get("tavg"),
            "tmin_c":      data.get("tmin"),
            "tmax_c":      data.get("tmax"),
            "precip_mm":   data.get("prcp"),
            "snow_depth_mm": data.get("snow"),
            "cloud_cover": data.get("tsun"),
        }

    except ImportError:
        return {"error": "httpx required"}
    except Exception as e:
        return {"error": str(e)}


# ── Street View capture year estimation ──────────────────────────────────────

def estimate_street_view_year(image_path: str) -> Optional[int]:
    """
    Estimate Google Street View capture year from camera metadata / visual cues.
    Currently uses EXIF software tag and image quality heuristics.
    Returns approximate year or None.
    """
    try:
        from geoint.exif import extract
        exif = extract(image_path)
        if exif.timestamp:
            ts = exif.timestamp
            # EXIF timestamp: "YYYY:MM:DD HH:MM:SS"
            year = int(ts[:4])
            if 2007 <= year <= 2030:
                return year
    except Exception:
        pass
    return None


# ── Full temporal analysis ────────────────────────────────────────────────────

def analyze(
    image_path: Optional[str] = None,
    shadow_ratio: Optional[float] = None,
    shadow_azimuth: Optional[float] = None,
    lat_hint: Optional[float] = None,
    lon_hint: Optional[float] = None,
    snow_present: bool = False,
    dry_grass: bool = False,
    green_leaves: bool = False,
    bare_trees: bool = False,
    vehicle_descriptions: Optional[list[str]] = None,
) -> dict:
    """
    Full temporal analysis combining all available signals.

    Returns
    -------
    dict with keys: "clues", "doy_range", "time_of_day_utc", "year_range", "season"
    """
    clues: list[Clue] = []
    doy_range = (1, 365)
    time_candidates: list[float] = []
    year_range = (1950, 2030)

    # EXIF timestamp
    if image_path:
        try:
            from geoint.exif import extract
            exif = extract(image_path)
            if exif.timestamp:
                clues.append(Clue("chronos", "exif_timestamp", exif.timestamp, 0.9,
                                  notes="From EXIF DateTimeOriginal"))
                year = int(exif.timestamp[:4])
                year_range = (year, year)
        except Exception:
            pass

    # Shadow-based time-of-day
    if shadow_ratio and shadow_azimuth and lat_hint and lon_hint:
        times = time_from_shadow(shadow_ratio, shadow_azimuth, lat_hint, lon_hint)
        time_candidates = times
        if times:
            clues.append(Clue("chronos", "time_of_day_utc",
                              [round(t, 1) for t in times[:3]], 0.75,
                              notes="Inferred from shadow geometry"))

    # Season from visual signals
    season_info = season_from_signals(snow_present, dry_grass, green_leaves, bare_trees, lat_hint)
    if season_info["season"] != "unknown":
        clues.append(Clue("chronos", "season", season_info["season"], 0.7,
                          notes="From vegetation / snow signals"))
        doy_range = season_info["doy_range"]

    # Vehicle era
    if vehicle_descriptions:
        era = estimate_photo_era_from_vehicles(vehicle_descriptions)
        if "min_year" in era:
            year_range = (era["min_year"], era["max_year"])
            clues.append(Clue("chronos", "photo_era", era, 0.5, notes=era.get("notes", "")))

    return {
        "clues":          clues,
        "doy_range":      doy_range,
        "time_of_day_utc": time_candidates,
        "year_range":     year_range,
        "season":         season_info["season"],
    }
