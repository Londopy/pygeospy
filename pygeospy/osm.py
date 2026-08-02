"""
pygeospy.osm — OpenStreetMap / Overpass API queries.
Pure Python: HTTP stays in Python, geometry in shapely.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from pygeospy._utils import RateLimiter, retry
from pygeospy._cache import cached
from pygeospy._types import BoundingBox

logger = logging.getLogger("pygeospy.osm")
_limiter = RateLimiter(calls_per_second=0.5)  # Overpass fair use


# ── Overpass query builder ────────────────────────────────────────────────────

def _overpass_query(query: str, timeout: int = 25) -> dict:
    """Execute a raw Overpass QL query. Returns parsed JSON."""
    import httpx
    _limiter.wait()
    url  = "https://overpass-api.de/api/interpreter"
    resp = httpx.post(url, data={"data": query}, timeout=timeout + 5)
    resp.raise_for_status()
    return resp.json()


def _radius_query(lat: float, lon: float, radius_m: int, feature_filter: str) -> str:
    """Build an Overpass radius query string."""
    return f"""
[out:json][timeout:25];
(
  node{feature_filter}(around:{radius_m},{lat},{lon});
  way{feature_filter}(around:{radius_m},{lat},{lon});
  relation{feature_filter}(around:{radius_m},{lat},{lon});
);
out body;>;out skel qt;
"""


def _bbox_query(bbox: BoundingBox, feature_filter: str) -> str:
    return f"""
[out:json][timeout:30];
(
  node{feature_filter}({bbox.min_lat},{bbox.min_lon},{bbox.max_lat},{bbox.max_lon});
  way{feature_filter}({bbox.min_lat},{bbox.min_lon},{bbox.max_lat},{bbox.max_lon});
);
out body;>;out skel qt;
"""


# ── Feature queries ───────────────────────────────────────────────────────────

FEATURE_PRESETS = {
    "hospital":       '["amenity"="hospital"]',
    "pharmacy":       '["amenity"="pharmacy"]',
    "school":         '["amenity"="school"]',
    "university":     '["amenity"="university"]',
    "police":         '["amenity"="police"]',
    "fire_station":   '["amenity"="fire_station"]',
    "fuel":           '["amenity"="fuel"]',
    "restaurant":     '["amenity"="restaurant"]',
    "hotel":          '["tourism"="hotel"]',
    "park":           '["leisure"="park"]',
    "mosque":         '["amenity"="place_of_worship"]["religion"="muslim"]',
    "church":         '["amenity"="place_of_worship"]["religion"="christian"]',
    "synagogue":      '["amenity"="place_of_worship"]["religion"="jewish"]',
    "highway":        '["highway"]',
    "building":       '["building"]',
    "residential":    '["landuse"="residential"]',
    "industrial":     '["landuse"="industrial"]',
    "farmland":       '["landuse"="farmland"]',
    "water":          '["natural"="water"]',
    "forest":         '["natural"="wood"]',
    "beach":          '["natural"="beach"]',
    "power_tower":    '["power"="tower"]',
    "power_line":     '["power"="line"]',
    "railway":        '["railway"="rail"]',
    "airport":        '["aeroway"="aerodrome"]',
}


@cached("osm_features", ttl=86400)
@retry(times=2, delay=2.0)
def query_features(
    lat: float,
    lon: float,
    radius_m: int = 1000,
    feature_type: str = "building",
) -> list[dict]:
    """
    Query OSM features within radius.

    feature_type can be any key from FEATURE_PRESETS, or a raw Overpass
    filter string like '["amenity"="cafe"]'.
    """
    filt = FEATURE_PRESETS.get(feature_type, feature_type)
    q    = _radius_query(lat, lon, radius_m, filt)
    data = _overpass_query(q)
    return data.get("elements", [])


@cached("osm_bbox", ttl=86400)
@retry(times=2, delay=2.0)
def query_bbox(
    bbox: BoundingBox,
    feature_type: str = "building",
) -> list[dict]:
    """Query OSM features within a bounding box."""
    filt = FEATURE_PRESETS.get(feature_type, feature_type)
    q    = _bbox_query(bbox, filt)
    data = _overpass_query(q)
    return data.get("elements", [])


# ── Building footprints ───────────────────────────────────────────────────────

def building_footprints(
    lat: float,
    lon: float,
    radius_m: int = 500,
) -> list[dict]:
    """
    Extract building footprints (as GeoJSON-like polygons) around a point.
    Returns a list of GeoJSON Feature dicts.
    """
    elements = query_features(lat, lon, radius_m, "building")
    return _elements_to_geojson(elements)


def _elements_to_geojson(elements: list[dict]) -> list[dict]:
    """Convert Overpass elements to GeoJSON features."""
    node_map = {e["id"]: e for e in elements if e["type"] == "node"}
    features = []
    for el in elements:
        props = el.get("tags", {})
        props["osm_id"]   = el["id"]
        props["osm_type"] = el["type"]

        if el["type"] == "node":
            feat = {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
                "properties": props,
            }
            features.append(feat)

        elif el["type"] == "way":
            coords = []
            for nid in el.get("nodes", []):
                n = node_map.get(nid)
                if n:
                    coords.append([n["lon"], n["lat"]])
            if len(coords) >= 3:
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                feat = {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [coords]},
                    "properties": props,
                }
                features.append(feat)
    return features


# ── Road density ──────────────────────────────────────────────────────────────

def road_density(
    lat: float,
    lon: float,
    radius_m: int = 1000,
) -> dict:
    """
    Compute road network density in an area.
    Returns {"total_roads": int, "density_per_km2": float, "classification": str}.
    """
    import math
    elements = query_features(lat, lon, radius_m, "highway")
    roads    = [e for e in elements if e["type"] == "way"]
    area_km2 = math.pi * (radius_m / 1000) ** 2
    density  = len(roads) / area_km2 if area_km2 else 0

    classification = (
        "dense_urban"    if density > 50 else
        "urban"          if density > 20 else
        "suburban"       if density > 5  else
        "rural"          if density > 1  else
        "remote"
    )
    return {
        "total_ways": len(roads),
        "density_per_km2": round(density, 2),
        "classification": classification,
    }


# ── Architectural tags ────────────────────────────────────────────────────────

def architectural_tags(
    lat: float,
    lon: float,
    radius_m: int = 500,
) -> dict:
    """
    Identify unique architectural / building tags in an area.
    Returns a summary useful for visual cross-referencing.
    """
    elements = query_features(lat, lon, radius_m, "building")
    tags: dict[str, int] = {}
    for el in elements:
        for k, v in el.get("tags", {}).items():
            key = f"{k}={v}"
            tags[key] = tags.get(key, 0) + 1

    # Sort by frequency
    sorted_tags = sorted(tags.items(), key=lambda x: x[1], reverse=True)
    return {
        "building_count": len([e for e in elements if e["type"] in ("way", "relation")]),
        "top_tags": sorted_tags[:20],
        "all_tags": dict(sorted_tags),
    }


# ── Named region boundary ─────────────────────────────────────────────────────

@cached("osm_boundary", ttl=7 * 86400)
@retry(times=2, delay=2.0)
def region_boundary(name: str, admin_level: Optional[int] = None) -> Optional[dict]:
    """
    Download a named region's boundary polygon from OSM (Nominatim + Overpass).
    Returns a GeoJSON Feature or None.
    """
    import httpx
    # Step 1: Nominatim lookup for OSM relation ID
    nm_url = "https://nominatim.openstreetmap.org/search"
    params = {"q": name, "format": "json", "limit": 1}
    headers = {"User-Agent": "pygeospy-library/0.2"}
    resp = httpx.get(nm_url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None

    osm_id   = results[0].get("osm_id")
    osm_type = results[0].get("osm_type")
    if osm_type != "relation":
        return None

    # Step 2: Overpass to fetch boundary geometry
    query = f"""
[out:json][timeout:30];
relation({osm_id});
out body;>;out skel qt;
"""
    try:
        data  = _overpass_query(query, timeout=30)
        feats = _elements_to_geojson(data.get("elements", []))
        if feats:
            return {"type": "FeatureCollection", "features": feats, "name": name}
    except Exception as e:
        logger.warning(f"region_boundary overpass query failed: {e}")
    return None


# ── GeoJSON / KML export ──────────────────────────────────────────────────────

def to_geojson(elements: list[dict]) -> dict:
    """Convert Overpass elements to a GeoJSON FeatureCollection."""
    features = _elements_to_geojson(elements)
    return {"type": "FeatureCollection", "features": features}


def save_geojson(elements: list[dict], path: str) -> str:
    gj = to_geojson(elements)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(gj, f, indent=2)
    logger.info(f"GeoJSON saved → {path}")
    return path


def save_kml(elements: list[dict], path: str) -> str:
    """Export OSM elements as a minimal KML file."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "<Document>",
    ]
    for el in elements:
        if el["type"] == "node":
            name = el.get("tags", {}).get("name", f"node {el['id']}")
            lat, lon = el["lat"], el["lon"]
            lines += [
                "<Placemark>",
                f"  <name>{name}</name>",
                "  <Point>",
                f"    <coordinates>{lon},{lat},0</coordinates>",
                "  </Point>",
                "</Placemark>",
            ]
    lines += ["</Document>", "</kml>"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"KML saved → {path}")
    return path
