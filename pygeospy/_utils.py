"""
pygeospy._utils — Shared utilities used across all modules.
"""
from __future__ import annotations

import math
import time
import functools
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("pygeospy")


# ── Graceful Rust import ──────────────────────────────────────────────────────

def _import_rustcore():
    """
    Try to import the compiled Rust extension.
    Returns the module on success, None on failure (pure-Python fallback mode).
    """
    try:
        import _rustcore
        return _rustcore
    except ImportError:
        logger.warning(
            "_rustcore not found — running in pure-Python fallback mode. "
            "Run `maturin develop` or `pip install -e .` to build Rust extensions."
        )
        return None


_RC = _import_rustcore()
RUST_AVAILABLE = _RC is not None


def rustcore(submodule: str):
    """Return a rustcore sub-module or None if unavailable."""
    if _RC is None:
        return None
    return getattr(_RC, submodule, None)


# ── Rate limiter ──────────────────────────────────────────────────────────────

class RateLimiter:
    """Simple token-bucket rate limiter for API calls."""

    def __init__(self, calls_per_second: float = 1.0):
        self.min_interval = 1.0 / calls_per_second
        self._last_call = 0.0

    def wait(self):
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()


# ── Retry decorator ───────────────────────────────────────────────────────────

def retry(times: int = 3, delay: float = 1.0, exceptions=(Exception,)):
    """Retry decorator with exponential back-off."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(times):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    wait = delay * (2 ** attempt)
                    logger.debug(f"Retry {attempt+1}/{times} for {fn.__name__}: {e}. Waiting {wait:.1f}s")
                    time.sleep(wait)
            raise last_exc
        return wrapper
    return decorator


# ── Bearing / direction helpers ───────────────────────────────────────────────

CARDINAL_DIRECTIONS = [
    (0,   "N"),  (22.5,  "NNE"), (45,  "NE"),  (67.5,  "ENE"),
    (90,  "E"),  (112.5, "ESE"), (135, "SE"),  (157.5, "SSE"),
    (180, "S"),  (202.5, "SSW"), (225, "SW"),  (247.5, "WSW"),
    (270, "W"),  (292.5, "WNW"), (315, "NW"),  (337.5, "NNW"),
    (360, "N"),
]


def bearing_to_cardinal(bearing_deg: float) -> str:
    """Convert bearing (0–360) to 16-point cardinal label."""
    bearing_deg = bearing_deg % 360
    for i in range(len(CARDINAL_DIRECTIONS) - 1):
        lo, label = CARDINAL_DIRECTIONS[i]
        hi = CARDINAL_DIRECTIONS[i + 1][0]
        mid = (lo + hi) / 2
        if bearing_deg < mid:
            return label
    return "N"


def cardinal_to_bearing(cardinal: str) -> float:
    """Convert cardinal label to bearing degrees."""
    cardinal = cardinal.upper()
    for deg, label in CARDINAL_DIRECTIONS[:-1]:
        if label == cardinal:
            return float(deg)
    raise ValueError(f"Unknown cardinal direction: {cardinal!r}")


# ── Coordinate validation ─────────────────────────────────────────────────────

def validate_latlon(lat: float, lon: float) -> None:
    if not (-90 <= lat <= 90):
        raise ValueError(f"Latitude {lat} out of range [-90, 90]")
    if not (-180 <= lon <= 180):
        raise ValueError(f"Longitude {lon} out of range [-180, 180]")


def is_valid_latlon(lat: float, lon: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lon <= 180


# ── Degree-of-year helpers ────────────────────────────────────────────────────

def date_to_doy(year: int, month: int, day: int) -> int:
    """Day-of-year (1–365/366) from a calendar date."""
    import datetime
    return datetime.date(year, month, day).timetuple().tm_yday


def doy_to_date(doy: int, year: int = 2024) -> tuple[int, int, int]:
    """Convert day-of-year back to (month, day, year)."""
    import datetime
    d = datetime.date(year, 1, 1) + datetime.timedelta(days=doy - 1)
    return d.month, d.day, d.year


# ── GeoJSON helpers ───────────────────────────────────────────────────────────

def make_geojson_feature(geometry: dict, properties: dict | None = None) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties or {}}


def make_geojson_collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def polygon_from_ring(latlon_ring: list[tuple[float, float]], properties: dict | None = None) -> dict:
    """Build a GeoJSON Feature polygon from a list of (lat, lon) tuples."""
    coords = [[lon, lat] for lat, lon in latlon_ring]
    return make_geojson_feature(
        {"type": "Polygon", "coordinates": [coords]},
        properties,
    )


# ── Unit conversions ──────────────────────────────────────────────────────────

def km_to_miles(km: float) -> float: return km * 0.621371
def miles_to_km(mi: float) -> float: return mi / 0.621371
def metres_to_feet(m: float) -> float: return m * 3.28084
def feet_to_metres(ft: float) -> float: return ft / 3.28084


# ── Confidence helpers ────────────────────────────────────────────────────────

def combine_confidences(*confidences: float, method: str = "product") -> float:
    """
    Combine multiple confidence scores into one.
    method: "product" | "min" | "mean"
    """
    vals = [max(0.0, min(1.0, c)) for c in confidences if c is not None]
    if not vals:
        return 0.0
    if method == "product":
        result = 1.0
        for v in vals:
            result *= v
        return result
    elif method == "min":
        return min(vals)
    elif method == "mean":
        return sum(vals) / len(vals)
    return sum(vals) / len(vals)


# ── Pretty printing ───────────────────────────────────────────────────────────

def format_latlon(lat: float, lon: float, fmt: str = "dd") -> str:
    """Format a coordinate pair as a string."""
    if fmt == "dd":
        ns = "N" if lat >= 0 else "S"
        ew = "E" if lon >= 0 else "W"
        return f"{abs(lat):.6f}°{ns}, {abs(lon):.6f}°{ew}"
    elif fmt == "dms":
        def _dms(val):
            d = int(abs(val))
            m = int((abs(val) - d) * 60)
            s = (abs(val) - d - m / 60) * 3600
            return d, m, s
        ld, lm, ls = _dms(lat)
        od, om, os_ = _dms(lon)
        ns = "N" if lat >= 0 else "S"
        ew = "E" if lon >= 0 else "W"
        return f"{ld}°{lm}'{ls:.2f}\"{ns}, {od}°{om}'{os_:.2f}\"{ew}"
    return f"{lat}, {lon}"
