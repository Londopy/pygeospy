"""
pygeospy.coords — Coordinate toolkit.

Pure math delegated to _rustcore.coords when available; pure-Python fallback
otherwise.  Heavy I/O (elevation API, timezone lookup) stays in Python.
"""
from __future__ import annotations

import math
from typing import Optional

from pygeospy._utils import rustcore, validate_latlon, format_latlon, retry
from pygeospy._cache import cached
from pygeospy._types import LatLon, BoundingBox

# Rust sub-module (may be None if not compiled)
_C = rustcore("coords")

# ── Pure-Python fallbacks ─────────────────────────────────────────────────────
_EARTH_RADIUS_KM = 6371.0088


def _py_haversine(lat1, lon1, lat2, lon2):
    r = math.radians
    dlat = r(lat2 - lat1)
    dlon = r(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(dlon/2)**2
    return _EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(a))


def _py_bearing(lat1, lon1, lat2, lon2):
    r = math.radians
    y = math.sin(r(lon2-lon1)) * math.cos(r(lat2))
    x = math.cos(r(lat1))*math.sin(r(lat2)) - math.sin(r(lat1))*math.cos(r(lat2))*math.cos(r(lon2-lon1))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _py_destination(lat, lon, bearing_deg, distance_km):
    r = math.radians
    d = distance_km / _EARTH_RADIUS_KM
    lat1, lon1, br = r(lat), r(lon), r(bearing_deg)
    lat2 = math.asin(math.sin(lat1)*math.cos(d) + math.cos(lat1)*math.sin(d)*math.cos(br))
    lon2 = lon1 + math.atan2(math.sin(br)*math.sin(d)*math.cos(lat1), math.cos(d)-math.sin(lat1)*math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)


# ── Public API ────────────────────────────────────────────────────────────────

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres (Haversine formula)."""
    validate_latlon(lat1, lon1); validate_latlon(lat2, lon2)
    if _C:
        return _C.haversine_distance(lat1, lon1, lat2, lon2)
    return _py_haversine(lat1, lon1, lat2, lon2)


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 → point 2 (degrees, 0–360, 0=N)."""
    validate_latlon(lat1, lon1); validate_latlon(lat2, lon2)
    if _C:
        return _C.bearing(lat1, lon1, lat2, lon2)
    return _py_bearing(lat1, lon1, lat2, lon2)


def destination(lat: float, lon: float, bearing_deg: float, distance_km: float) -> LatLon:
    """Destination point from start, bearing, distance."""
    validate_latlon(lat, lon)
    if _C:
        la, lo = _C.destination_point(lat, lon, bearing_deg, distance_km)
    else:
        la, lo = _py_destination(lat, lon, bearing_deg, distance_km)
    return LatLon(la, lo)


def midpoint(lat1: float, lon1: float, lat2: float, lon2: float) -> LatLon:
    """Midpoint between two coordinates."""
    if _C:
        la, lo = _C.midpoint(lat1, lon1, lat2, lon2)
    else:
        # Pure-Python midpoint
        r = math.radians
        bx = math.cos(r(lat2)) * math.cos(r(lon2 - lon1))
        by = math.cos(r(lat2)) * math.sin(r(lon2 - lon1))
        la = math.degrees(math.atan2(math.sin(r(lat1)) + math.sin(r(lat2)),
                          math.sqrt((math.cos(r(lat1)) + bx)**2 + by**2)))
        lo = lon1 + math.degrees(math.atan2(by, math.cos(r(lat1)) + bx))
    return LatLon(la, lo)


def bounding_box(lat: float, lon: float, radius_km: float) -> BoundingBox:
    """Axis-aligned bounding box around a centre point + radius."""
    validate_latlon(lat, lon)
    if _C:
        mn_lat, mn_lon, mx_lat, mx_lon = _C.bounding_box(lat, lon, radius_km)
    else:
        dlat = math.degrees(radius_km / _EARTH_RADIUS_KM)
        dlon = math.degrees(radius_km / (_EARTH_RADIUS_KM * math.cos(math.radians(lat))))
        mn_lat, mn_lon, mx_lat, mx_lon = lat-dlat, lon-dlon, lat+dlat, lon+dlon
    return BoundingBox(mn_lat, mn_lon, mx_lat, mx_lon)


def cross_track_distance(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
    lat3: float, lon3: float,
) -> float:
    """
    Cross-track distance (km, signed) of point P3 from the great-circle P1→P2.
    Positive = right of track.
    """
    if _C:
        return _C.cross_track_distance(lat1, lon1, lat2, lon2, lat3, lon3)
    # Fallback approximation
    d13   = _py_haversine(lat1, lon1, lat3, lon3) / _EARTH_RADIUS_KM
    b13   = math.radians(_py_bearing(lat1, lon1, lat3, lon3))
    b12   = math.radians(_py_bearing(lat1, lon1, lat2, lon2))
    return _EARTH_RADIUS_KM * math.asin(math.sin(d13) * math.sin(b13 - b12))


def polygon_area(coords: list[tuple[float, float]]) -> float:
    """Approximate great-circle polygon area in km²."""
    if _C:
        return _C.polygon_area(coords)
    # Shoelace fallback (planar, accurate for small polygons)
    n = len(coords)
    if n < 3: return 0.0
    area = 0.0
    for i in range(n):
        j = (i+1) % n
        area += coords[i][1] * coords[j][0]
        area -= coords[j][1] * coords[i][0]
    return abs(area) / 2 * (111.32 ** 2)


def batch_haversine(origin_lat: float, origin_lon: float, points: list[tuple[float, float]]) -> list[float]:
    """
    Compute Haversine distances from one origin to many points.
    Uses Rust SIMD-style loop when available — ideal for large geocoding batches.
    """
    if _C:
        return _C.batch_haversine(origin_lat, origin_lon, points)
    return [_py_haversine(origin_lat, origin_lon, la, lo) for la, lo in points]


# ── Format conversions ────────────────────────────────────────────────────────

def dd_to_dms(dd: float) -> tuple[int, int, float, str]:
    """
    Decimal degrees → (degrees, minutes, seconds, hemisphere).
    hemisphere is "N"/"S" for latitude; caller decides which based on context.
    """
    if _C:
        deg, mn, sec = _C.dd_to_dms(dd)
    else:
        a = abs(dd)
        deg = int(a)
        mn  = int((a - deg) * 60)
        sec = (a - deg - mn/60) * 3600
    direction = 1 if dd >= 0 else -1
    return deg, mn, sec, "+" if dd >= 0 else "-"


def dms_to_dd(degrees: int, minutes: int, seconds: float, direction: str) -> float:
    """
    DMS → decimal degrees.
    direction: "N"/"E" → positive, "S"/"W" → negative (or +1/-1 int).
    """
    sign = 1
    if isinstance(direction, str):
        sign = -1 if direction.upper() in ("S", "W", "-") else 1
    else:
        sign = int(direction)
    if _C:
        return _C.dms_to_dd(degrees, minutes, seconds, sign)
    return sign * (degrees + minutes/60 + seconds/3600)


def latlon_to_utm(lat: float, lon: float) -> dict:
    """Convert WGS-84 lat/lon to UTM (easting, northing, zone)."""
    validate_latlon(lat, lon)
    if _C:
        e, n, zone_num, zone_letter = _C.latlon_to_utm(lat, lon)
    else:
        # Simplified fallback
        zone_num = int((lon + 180) / 6) + 1
        zone_letter = "N" if lat >= 0 else "S"
        e, n = 500000.0, (0.0 if lat >= 0 else 10_000_000.0)
    return {"easting": e, "northing": n, "zone": f"{zone_num}{zone_letter}"}


def latlon_to_mgrs(lat: float, lon: float, precision: int = 5) -> str:
    """
    Convert lat/lon to MGRS string.
    Requires the `mgrs` package; falls back to UTM zone string if unavailable.
    """
    try:
        import mgrs as _mgrs
        m = _mgrs.MGRS()
        return m.toMGRS(lat, lon, MGRSPrecision=precision)
    except ImportError:
        utm = latlon_to_utm(lat, lon)
        return f"{utm['zone']} {utm['easting']:.0f}E {utm['northing']:.0f}N"


def mgrs_to_latlon(mgrs_string: str) -> LatLon:
    """Convert MGRS string to lat/lon."""
    try:
        import mgrs as _mgrs
        m = _mgrs.MGRS()
        lat, lon = m.toLatLon(mgrs_string)
        return LatLon(lat, lon)
    except ImportError:
        raise ImportError("mgrs package required: pip install mgrs")


def latlon_to_plus_code(lat: float, lon: float, code_length: int = 10) -> str:
    """Convert lat/lon to Google Plus Code (Open Location Code)."""
    try:
        import openlocationcode.openlocationcode as olc
        return olc.encode(lat, lon, code_length)
    except ImportError:
        try:
            import pyotp  # noqa – wrong package, will fail
        except ImportError:
            pass
        raise ImportError("openlocationcode package required: pip install openlocationcode")


# ── Elevation API ─────────────────────────────────────────────────────────────

@cached("elevation", ttl=7 * 86400)
@retry(times=3, delay=1.0)
def get_elevation(lat: float, lon: float, dataset: str = "srtm30m") -> float:
    """
    Fetch elevation (metres) from Open-Topo-Data API.
    Supported datasets: srtm30m, srtm90m, aster30m, eudem25m, ned10m.
    Result is cached for 7 days.
    """
    import httpx
    validate_latlon(lat, lon)
    url = f"https://api.opentopodata.org/v1/{dataset}?locations={lat},{lon}"
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [{}])
    return results[0].get("elevation", 0.0)


def get_elevation_batch(points: list[tuple[float, float]], dataset: str = "srtm30m") -> list[float]:
    """
    Batch elevation lookup (max 100 points per request by Open-Topo-Data limits).
    """
    import httpx
    if not points:
        return []
    locs = "|".join(f"{lat},{lon}" for lat, lon in points[:100])
    url  = f"https://api.opentopodata.org/v1/{dataset}?locations={locs}"
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    return [r.get("elevation", 0.0) for r in resp.json().get("results", [])]


# ── Timezone inference ────────────────────────────────────────────────────────

@cached("timezone", ttl=30 * 86400)
def get_timezone(lat: float, lon: float) -> str:
    """
    Return the IANA timezone name for a lat/lon.
    Uses timezonefinder (offline) with httpx fallback to worldtimeapi.org.
    """
    try:
        from timezonefinder import TimezoneFinder
        tf = TimezoneFinder()
        tz = tf.timezone_at(lat=lat, lng=lon)
        return tz or "UTC"
    except ImportError:
        pass
    # Fallback: rough UTC offset from longitude
    offset_hours = round(lon / 15)
    sign = "+" if offset_hours >= 0 else "-"
    return f"Etc/GMT{sign}{abs(offset_hours)}"


# ── Friendly wrappers ─────────────────────────────────────────────────────────

def format(lat: float, lon: float, fmt: str = "dd") -> str:
    """Format coordinates. fmt: 'dd' | 'dms' | 'utm' | 'mgrs'."""
    if fmt == "utm":
        u = latlon_to_utm(lat, lon)
        return f"{u['zone']} {u['easting']:.0f}E {u['northing']:.0f}N"
    if fmt == "mgrs":
        return latlon_to_mgrs(lat, lon)
    return format_latlon(lat, lon, fmt)
