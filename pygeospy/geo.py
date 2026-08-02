"""
pygeospy.geo — Geocoding, reverse geocoding, and IP geolocation.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from pygeospy._cache import cached
from pygeospy._types import LatLon
from pygeospy._utils import RateLimiter, retry

logger = logging.getLogger("pygeospy.geo")
_nominatim_limiter = RateLimiter(calls_per_second=0.9)  # Nominatim: max 1 req/s


# ── Geocoding ─────────────────────────────────────────────────────────────────

@cached("geocode", ttl=7 * 86400)
@retry(times=3, delay=1.0)
def geocode(address: str) -> Optional[LatLon]:
    """
    Address → lat/lon via Nominatim (OpenStreetMap).
    Returns None if the address is not found.
    """
    import httpx
    _nominatim_limiter.wait()
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1, "addressdetails": 1}
    headers = {"User-Agent": "pygeospy-library/0.2"}
    resp = httpx.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None
    r = results[0]
    return LatLon(float(r["lat"]), float(r["lon"]))


@cached("reverse_geo", ttl=7 * 86400)
@retry(times=3, delay=1.0)
def reverse_geocode(lat: float, lon: float) -> dict:
    """
    Lat/lon → nearest named place + administrative boundary details.
    Returns a dict with: display_name, city, state, country, country_code.
    """
    import httpx
    _nominatim_limiter.wait()
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {"lat": lat, "lon": lon, "format": "json", "addressdetails": 1}
    headers = {"User-Agent": "pygeospy-library/0.2"}
    resp = httpx.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    addr = data.get("address", {})
    return {
        "display_name":  data.get("display_name", ""),
        "city":          addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet") or "",
        "state":         addr.get("state") or addr.get("region") or "",
        "country":       addr.get("country", ""),
        "country_code":  addr.get("country_code", "").upper(),
        "postcode":      addr.get("postcode", ""),
        "road":          addr.get("road", ""),
        "suburb":        addr.get("suburb") or addr.get("neighbourhood") or "",
        "raw":           addr,
    }


def country_from_coords(lat: float, lon: float) -> tuple[str, str]:
    """
    Return (country_name, ISO-2 code) for coordinates.
    Fast offline lookup via pycountry + shapely; falls back to Nominatim.
    """
    try:
        # Try fast offline library first
        import reverse_geocoder as rg  # type: ignore
        results = rg.search((lat, lon))
        if results:
            r = results[0]
            return r.get("cc", ""), r.get("cc", "")
    except ImportError:
        pass
    # Nominatim fallback
    info = reverse_geocode(lat, lon)
    return info.get("country", ""), info.get("country_code", "")


# ── IP geolocation ────────────────────────────────────────────────────────────

@cached("ip_geo", ttl=86400)
@retry(times=3, delay=1.0)
def ip_to_location(ip: str) -> dict:
    """
    IP address → city/country/ISP/coordinates via ip-api.com.
    Returns a dict with: ip, country, country_code, region, city, lat, lon, isp, org, timezone.
    Free tier supports 45 requests/minute.
    """
    import httpx
    url  = f"http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,lat,lon,isp,org,timezone,mobile,proxy,hosting"
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "success":
        raise ValueError(f"ip-api failed: {data.get('message', 'unknown error')}")

    return {
        "ip":           ip,
        "country":      data.get("country", ""),
        "country_code": data.get("countryCode", ""),
        "region":       data.get("regionName", ""),
        "city":         data.get("city", ""),
        "lat":          data.get("lat"),
        "lon":          data.get("lon"),
        "isp":          data.get("isp", ""),
        "org":          data.get("org", ""),
        "timezone":     data.get("timezone", ""),
        "mobile":       data.get("mobile", False),
        "proxy":        data.get("proxy", False),
        "hosting":      data.get("hosting", False),
    }


def ip_to_latlon(ip: str) -> Optional[LatLon]:
    """Convenience wrapper: IP → LatLon or None."""
    try:
        info = ip_to_location(ip)
        if info.get("lat") and info.get("lon"):
            return LatLon(info["lat"], info["lon"])
    except Exception as e:
        logger.warning(f"IP lookup failed for {ip}: {e}")
    return None


# ── Bulk geocoding ────────────────────────────────────────────────────────────

def bulk_geocode(
    addresses: list[str],
    rate_limit: float = 1.0,
    max_errors: int = 5,
) -> list[dict]:
    """
    Geocode a list of addresses with rate-limit handling.

    Parameters
    ----------
    addresses : list[str]
    rate_limit : float
        Maximum requests per second.
    max_errors : int
        Abort after this many consecutive errors.

    Returns
    -------
    list of {"address": str, "lat": float|None, "lon": float|None, "error": str|None}
    """
    limiter = RateLimiter(calls_per_second=rate_limit)
    results = []
    consecutive_errors = 0

    for addr in addresses:
        limiter.wait()
        try:
            loc = geocode(addr)
            if loc:
                results.append({"address": addr, "lat": loc.lat, "lon": loc.lon, "error": None})
                consecutive_errors = 0
            else:
                results.append({"address": addr, "lat": None, "lon": None, "error": "not_found"})
        except Exception as e:
            results.append({"address": addr, "lat": None, "lon": None, "error": str(e)})
            consecutive_errors += 1
            logger.warning(f"Geocode error [{addr}]: {e}")
            if consecutive_errors >= max_errors:
                logger.error(f"Aborting bulk geocode after {max_errors} consecutive errors.")
                break

    return results


# ── What3Words compatibility ──────────────────────────────────────────────────

def w3w_to_latlon(words: str, api_key: Optional[str] = None) -> Optional[LatLon]:
    """
    Convert a What3Words address (e.g. "filled.count.soap") to lat/lon.
    Requires a W3W API key or uses their free API tier.
    """
    api_key = api_key or os.environ.get("W3W_API_KEY", "")
    if not api_key:
        logger.warning("W3W_API_KEY not set; what3words lookup may fail.")

    import httpx
    url = f"https://api.what3words.com/v3/convert-to-coordinates?words={words}&key={api_key}"
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    coords = data.get("coordinates", {})
    if coords.get("lat") and coords.get("lng"):
        return LatLon(coords["lat"], coords["lng"])
    return None


def latlon_to_w3w(lat: float, lon: float, api_key: Optional[str] = None) -> Optional[str]:
    """Convert lat/lon to a What3Words address."""
    api_key = api_key or os.environ.get("W3W_API_KEY", "")
    import httpx
    url = f"https://api.what3words.com/v3/convert-to-3wa?coordinates={lat},{lon}&key={api_key}"
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json().get("words")


# ── Place lookup ──────────────────────────────────────────────────────────────

@cached("place_search", ttl=86400)
def search_places(
    query: str,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius_km: float = 50,
    limit: int = 5,
) -> list[dict]:
    """
    Search for places by name, optionally biased toward a location.
    Uses Nominatim.
    """
    import httpx
    _nominatim_limiter.wait()
    url = "https://nominatim.openstreetmap.org/search"
    params: dict = {"q": query, "format": "json", "limit": limit, "addressdetails": 1}
    if lat and lon:
        params["viewbox"] = f"{lon-radius_km/111},{lat-radius_km/111},{lon+radius_km/111},{lat+radius_km/111}"
        params["bounded"] = 1
    headers = {"User-Agent": "pygeospy-library/0.2"}
    resp = httpx.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()

    results = []
    for r in resp.json():
        results.append({
            "name":         r.get("display_name", ""),
            "lat":          float(r["lat"]),
            "lon":          float(r["lon"]),
            "type":         r.get("type", ""),
            "importance":   r.get("importance", 0),
        })
    return results


# ── Timezone ──────────────────────────────────────────────────────────────────

def timezone_from_coords(lat: float, lon: float) -> str:
    """Return IANA timezone name for coordinates."""
    from pygeospy.coords import get_timezone
    return get_timezone(lat, lon)
