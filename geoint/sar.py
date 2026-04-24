"""
geoint.sar — Search and Rescue grid generation and field operations.
Rust core handles polygon math; Python handles GPX export and
lost-person profile logic.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from geoint._utils import rustcore
from geoint._types import LatLon, BoundingBox

logger = logging.getLogger("geoint.sar")
_SAR = rustcore("sar")


# ── Grid generation ───────────────────────────────────────────────────────────

def search_grid(
    center_lat: float,
    center_lon: float,
    radius_km: float = 2.0,
    cell_km: float = 0.5,
) -> list[dict]:
    """
    Generate a NASAR-style rectangular search grid.

    Parameters
    ----------
    center_lat, center_lon : float
        Initial Planning Point (IPP).
    radius_km : float
        Half-extent of the search area.
    cell_km : float
        Size of each search segment cell.

    Returns
    -------
    list of GeoJSON Feature dicts with sector labels and polygon coordinates.
    """
    if _SAR:
        named = _SAR.named_search_grid(center_lat, center_lon, radius_km, cell_km)
    else:
        named = _py_named_grid(center_lat, center_lon, radius_km, cell_km)

    features = []
    for label, ring in named:
        coords = [[lon, lat] for lat, lon in ring]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {"sector": label, "cell_km": cell_km},
        })
    return features


def corridor_search(
    waypoints: list[tuple[float, float]],
    width_km: float = 0.1,
) -> list[dict]:
    """
    Generate a hasty-search corridor along a trail / waypoint sequence.

    Parameters
    ----------
    waypoints : list of (lat, lon)
    width_km : float
        Total corridor width (half-width each side of the centreline).

    Returns
    -------
    list of GeoJSON Polygon Features, one per segment.
    """
    if _SAR:
        segments = _SAR.corridor_search(waypoints, width_km)
    else:
        segments = _py_corridor(waypoints, width_km)

    return [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[lon, lat] for lat, lon in ring]]},
            "properties": {"segment": i, "width_km": width_km},
        }
        for i, ring in enumerate(segments)
    ]


def poa_zones(
    ipp_lat: float,
    ipp_lon: float,
    profile: str = "hiker",
    radii_km: Optional[list[float]] = None,
    n_points: int = 64,
) -> list[dict]:
    """
    Generate Probability of Area (POA) rings from IPP.

    Uses ISRID-derived radius estimates for the given subject profile.
    Returns GeoJSON Features for each ring.
    """
    if radii_km is None:
        typical, max_r = lost_person_radius(profile)
        radii_km = [typical * 0.25, typical * 0.5, typical, typical * 1.5, max_r]

    if _SAR:
        rings = _SAR.poa_rings(ipp_lat, ipp_lon, radii_km, n_points)
    else:
        rings = _py_rings(ipp_lat, ipp_lon, radii_km, n_points)

    return [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[lon, lat] for lat, lon in ring]],
            },
            "properties": {
                "radius_km": radii_km[i],
                "ring":      i + 1,
                "profile":   profile,
            },
        }
        for i, ring in enumerate(rings)
    ]


def expanding_square(
    ipp_lat: float,
    ipp_lon: float,
    leg_spacing_km: float = 0.1,
    legs: int = 12,
) -> list[tuple[float, float]]:
    """
    Generate an expanding-square search pattern waypoint sequence.
    Returns ordered (lat, lon) waypoints.
    """
    if _SAR:
        return _SAR.expanding_square(ipp_lat, ipp_lon, leg_spacing_km, legs)
    return _py_expanding_square(ipp_lat, ipp_lon, leg_spacing_km, legs)


# ── Subject profile helpers ───────────────────────────────────────────────────

def lost_person_radius(profile: str) -> tuple[float, float]:
    """
    ISRID-derived (typical_km, max_km) search radius for a subject profile.

    Profiles: hiker, hunter, child_1_3, child_4_6, child_7_9, child_10_12,
    child_13_15, despondent, alzheimer, dementia, outdoor_worker, trail_runner,
    mountain_biker, horseback, atv, snowmobiler.
    """
    if _SAR:
        return _SAR.lost_person_radius(profile)
    _RADII = {
        "hiker": (2.9, 14.5), "hunter": (3.6, 16.0),
        "child_1_3": (0.5, 1.6), "child_4_6": (0.8, 3.0),
        "despondent": (2.3, 8.8), "alzheimer": (0.8, 5.0),
        "trail_runner": (5.0, 25.0), "mountain_biker": (8.0, 35.0),
    }
    return _RADII.get(profile, (3.0, 15.0))


def urgency_score(
    age: int,
    medical_condition: bool = False,
    last_seen_hours: float = 4.0,
    night_time: bool = False,
    adverse_weather: bool = False,
    terrain_difficult: bool = False,
) -> dict:
    """
    Compute urgency score (0–10) from subject profile.
    Higher = respond faster.
    """
    if _SAR:
        score = _SAR.urgency_score(
            age, medical_condition, last_seen_hours,
            night_time, adverse_weather, terrain_difficult
        )
    else:
        score = 0.0
        score += 3.0 if (age < 12 or age > 70) else 1.0
        score += 2.5 if medical_condition else 0.0
        score += min(last_seen_hours / 4.0, 2.0)
        score += 1.0 if night_time else 0.0
        score += 1.0 if adverse_weather else 0.0
        score += 0.5 if terrain_difficult else 0.0
        score = min(score, 10.0)

    priority = (
        "IMMEDIATE (≥8)"  if score >= 8 else
        "HIGH (≥6)"       if score >= 6 else
        "MEDIUM (≥4)"     if score >= 4 else
        "LOW (<4)"
    )
    return {"score": round(score, 1), "priority": priority}


# ── GPX export ────────────────────────────────────────────────────────────────

def to_gpx(
    waypoints: list[tuple[float, float]],
    name: str = "SAR Grid",
    output_path: str = "sar.gpx",
) -> str:
    """
    Export a waypoint list as a GPX file (compatible with Garmin, Gaia GPS, etc.).
    """
    try:
        import gpxpy
        import gpxpy.gpx
        gpx = gpxpy.gpx.GPX()
        route = gpxpy.gpx.GPXRoute(name=name)
        for i, (lat, lon) in enumerate(waypoints):
            rp = gpxpy.gpx.GPXRoutePoint(lat, lon, name=f"WP{i+1:03d}")
            route.route_points.append(rp)
        gpx.routes.append(route)
        with open(output_path, "w") as f:
            f.write(gpx.to_xml())
    except ImportError:
        # Minimal hand-written GPX fallback
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">',
            f'<rte><name>{name}</name>',
        ]
        for i, (lat, lon) in enumerate(waypoints):
            lines.append(f'  <rtept lat="{lat}" lon="{lon}"><name>WP{i+1:03d}</name></rtept>')
        lines += ["</rte>", "</gpx>"]
        with open(output_path, "w") as f:
            f.write("\n".join(lines))

    logger.info(f"GPX saved → {output_path}")
    return output_path


def grid_to_gpx(
    features: list[dict],
    output_path: str = "sar_grid.gpx",
) -> str:
    """Export a search-grid (list of GeoJSON features) as GPX route waypoints."""
    wps = []
    for feat in features:
        coords = feat["geometry"]["coordinates"][0]
        # Use centroid of each cell polygon
        if coords:
            lat = sum(c[1] for c in coords) / len(coords)
            lon = sum(c[0] for c in coords) / len(coords)
            label = feat["properties"].get("sector", "")
            wps.append((lat, lon))
    return to_gpx(wps, name="SAR Search Grid", output_path=output_path)


def to_geojson(features: list[dict], output_path: str) -> str:
    """Save SAR features as a GeoJSON FeatureCollection."""
    fc = {"type": "FeatureCollection", "features": features}
    with open(output_path, "w") as f:
        json.dump(fc, f, indent=2)
    logger.info(f"GeoJSON saved → {output_path}")
    return output_path


# ── Pure-Python fallbacks ─────────────────────────────────────────────────────

def _py_named_grid(center_lat, center_lon, radius_km, cell_km):
    import math
    _EARTH = 6371.0088
    def dest(lat, lon, brg, d):
        la, lo, br = map(math.radians, (lat, lon, brg))
        dr = d / _EARTH
        la2 = math.asin(math.sin(la)*math.cos(dr) + math.cos(la)*math.sin(dr)*math.cos(br))
        lo2 = lo + math.atan2(math.sin(br)*math.sin(dr)*math.cos(la), math.cos(dr)-math.sin(la)*math.sin(la2))
        return math.degrees(la2), math.degrees(lo2)

    n = int(2 * radius_km / cell_km)
    cells = []
    alph  = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    idx   = 0
    for row in range(n):
        for col in range(n):
            s_off = (row - n/2) * cell_km
            w_off = (col - n/2) * cell_km
            sw = dest(*dest(center_lat, center_lon, 180, -s_off), 270, -w_off)
            se = dest(sw[0], sw[1], 90, cell_km)
            ne = dest(se[0], se[1], 0, cell_km)
            nw = dest(sw[0], sw[1], 0, cell_km)
            label = alph[idx % 26] if idx < 26 else alph[idx//26-1]+alph[idx%26]
            cells.append((label, [sw, se, ne, nw, sw]))
            idx += 1
    return cells


def _py_corridor(waypoints, width_km):
    import math
    _EARTH = 6371.0088
    def dest(lat, lon, brg, d):
        la, lo, br = map(math.radians, (lat, lon, brg))
        dr = d / _EARTH
        la2 = math.asin(math.sin(la)*math.cos(dr)+math.cos(la)*math.sin(dr)*math.cos(br))
        lo2 = lo + math.atan2(math.sin(br)*math.sin(dr)*math.cos(la), math.cos(dr)-math.sin(la)*math.sin(la2))
        return math.degrees(la2), math.degrees(lo2)
    def bear(lat1, lon1, lat2, lon2):
        y = math.sin(math.radians(lon2-lon1))*math.cos(math.radians(lat2))
        x = math.cos(math.radians(lat1))*math.sin(math.radians(lat2))-math.sin(math.radians(lat1))*math.cos(math.radians(lat2))*math.cos(math.radians(lon2-lon1))
        return (math.degrees(math.atan2(y,x))+360)%360
    segs = []
    for i in range(len(waypoints)-1):
        la1,lo1 = waypoints[i]; la2,lo2 = waypoints[i+1]
        b = bear(la1,lo1,la2,lo2)
        hw = width_km / 2
        sw = dest(la1,lo1,(b+270)%360,hw); se = dest(la1,lo1,(b+90)%360,hw)
        ne = dest(la2,lo2,(b+90)%360,hw); nw = dest(la2,lo2,(b+270)%360,hw)
        segs.append([sw,se,ne,nw,sw])
    return segs


def _py_rings(ipp_lat, ipp_lon, radii_km, n_points):
    import math
    _EARTH = 6371.0088
    def dest(lat, lon, brg, d):
        la, lo, br = map(math.radians, (lat, lon, brg))
        dr = d / _EARTH
        la2 = math.asin(math.sin(la)*math.cos(dr)+math.cos(la)*math.sin(dr)*math.cos(br))
        lo2 = lo + math.atan2(math.sin(br)*math.sin(dr)*math.cos(la), math.cos(dr)-math.sin(la)*math.sin(la2))
        return math.degrees(la2), math.degrees(lo2)
    return [[dest(ipp_lat, ipp_lon, i/n_points*360, r) for i in range(n_points+1)] for r in radii_km]


def _py_expanding_square(lat, lon, spacing, legs):
    import math
    _EARTH = 6371.0088
    def dest(la, lo, brg, d):
        la, lo, br = map(math.radians, (la, lo, brg))
        dr = d/_EARTH
        la2 = math.asin(math.sin(la)*math.cos(dr)+math.cos(la)*math.sin(dr)*math.cos(br))
        lo2 = lo + math.atan2(math.sin(br)*math.sin(dr)*math.cos(la), math.cos(dr)-math.sin(la)*math.sin(la2))
        return math.degrees(la2), math.degrees(lo2)
    wps = [(lat, lon)]
    cur = (lat, lon)
    brgs = [0.0, 90.0, 180.0, 270.0]
    bi = 0; step = 1; changes = 0
    for _ in range(legs):
        cur = dest(*cur, brgs[bi%4], spacing*step)
        wps.append(cur); changes += 1; bi += 1
        if changes % 2 == 0: step += 1
    return wps
