"""
pygeospy.network — Network & digital OSINT: IP, BGP, Wi-Fi, email headers.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from pygeospy._types import Clue, LatLon
from pygeospy._cache import cached
from pygeospy._utils import retry

logger = logging.getLogger("pygeospy.network")


# ── IP / ASN analysis ─────────────────────────────────────────────────────────

@cached("ip_asn", ttl=86400)
@retry(times=3, delay=1.0)
def ip_to_asn(ip: str) -> dict:
    """
    Resolve IP → ASN (Autonomous System Number) + org name via Team Cymru / BGPView.
    Returns {"asn": int, "org": str, "country": str, "prefix": str}.
    """
    import httpx
    resp = httpx.get(f"https://api.bgpview.io/ip/{ip}", timeout=10)
    resp.raise_for_status()
    data = resp.json().get("data", {})
    prefixes = data.get("prefixes", [{}])
    asn_info = prefixes[0].get("asn", {}) if prefixes else {}
    return {
        "asn":     asn_info.get("asn"),
        "org":     asn_info.get("description", ""),
        "country": asn_info.get("country_code", ""),
        "prefix":  prefixes[0].get("prefix", "") if prefixes else "",
        "type":    _classify_asn_type(asn_info.get("description", "")),
    }


def _classify_asn_type(org_name: str) -> str:
    """Classify ASN as datacenter / hosting / residential / mobile / CDN."""
    org = org_name.lower()
    if any(k in org for k in ("amazon", "aws", "google", "azure", "digital ocean",
                               "linode", "vultr", "ovh", "hetzner", "cloudflare")):
        return "hosting/cloud"
    if any(k in org for k in ("comcast", "at&t", "verizon", "vodafone", "telstra",
                               "bt ", "virgin", "tmobile", "sprint", "telefonica")):
        return "residential/isp"
    if any(k in org for k in ("mobile", "cellular", "gsm", "lte", "4g", "5g")):
        return "mobile"
    return "unknown"


def is_vpn_or_proxy(ip: str) -> dict:
    """
    Check if an IP is a known VPN/proxy/Tor exit node.
    Uses ip-api.com fields.
    """
    from pygeospy.geo import ip_to_location
    try:
        info = ip_to_location(ip)
        return {
            "is_proxy":   info.get("proxy", False),
            "is_hosting": info.get("hosting", False),
            "is_mobile":  info.get("mobile", False),
        }
    except Exception:
        return {"is_proxy": None, "is_hosting": None, "is_mobile": None}


# ── Wi-Fi geolocation ─────────────────────────────────────────────────────────

@cached("wigle", ttl=7 * 86400)
@retry(times=2, delay=2.0)
def bssid_to_location(bssid: str, api_key: Optional[str] = None) -> Optional[LatLon]:
    """
    Geolocate a Wi-Fi access point by BSSID/MAC using WiGLE API.
    Requires a WiGLE API key (set WIGLE_API_KEY env var or pass api_key).
    """
    import httpx
    import os
    key = api_key or os.environ.get("WIGLE_API_KEY", "")
    if not key:
        logger.warning("WIGLE_API_KEY not set; BSSID lookup unavailable")
        return None

    # WiGLE expects "nameToken:key" base64 encoded as Basic auth
    headers = {"Authorization": f"Basic {key}"}
    url  = "https://api.wigle.net/api/v2/network/search"
    params = {"netid": bssid.upper().replace("-", ":"), "resultsPerPage": 1}
    resp = httpx.get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        return None
    r = results[0]
    return LatLon(r.get("trilat", 0), r.get("trilong", 0))


# ── MAC address OUI ───────────────────────────────────────────────────────────

@cached("oui", ttl=30 * 86400)
def mac_to_manufacturer(mac: str) -> dict:
    """
    Resolve MAC address OUI to manufacturer via macvendors.com.
    Returns {"manufacturer": str, "country_hint": str}.
    """
    import httpx
    oui = mac.replace(":", "").replace("-", "").upper()[:6]
    try:
        resp = httpx.get(f"https://api.macvendors.com/{oui}", timeout=10)
        if resp.status_code == 404:
            return {"manufacturer": "unknown", "country_hint": None}
        manufacturer = resp.text.strip()
        # Very rough country hinting from manufacturer
        mfr_lower = manufacturer.lower()
        country = None
        if any(k in mfr_lower for k in ("apple", "cisco", "intel", "qualcomm")):
            country = "United States"
        elif any(k in mfr_lower for k in ("samsung", "lg ", "sk hynix")):
            country = "South Korea"
        elif any(k in mfr_lower for k in ("huawei", "xiaomi", "zte", "oppo", "vivo")):
            country = "China"
        elif any(k in mfr_lower for k in ("sony", "toshiba", "fujitsu", "nec")):
            country = "Japan"
        return {"manufacturer": manufacturer, "country_hint": country}
    except Exception as e:
        logger.debug(f"MAC lookup error: {e}")
        return {"manufacturer": "unknown", "country_hint": None}


# ── Email header analysis ─────────────────────────────────────────────────────

def extract_ips_from_email_headers(headers_text: str) -> list[str]:
    """
    Extract originating IP addresses from raw email headers.
    Returns list of IPs ordered from innermost (sender) to outermost.
    """
    # Match "Received: from ... [IP]" patterns
    received_ips = re.findall(
        r'Received:.*?\[(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\]',
        headers_text, re.IGNORECASE | re.DOTALL
    )
    # Also match bare IPs in Received lines
    bare_ips = re.findall(
        r'(?<!\d)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?!\d)',
        headers_text
    )
    # Deduplicate, filter private ranges
    all_ips = list(dict.fromkeys(received_ips + bare_ips))
    return [ip for ip in all_ips if not _is_private_ip(ip)]


def _is_private_ip(ip: str) -> bool:
    """Check if an IP is in a private/reserved range."""
    try:
        parts = list(map(int, ip.split(".")))
        if parts[0] == 10: return True
        if parts[0] == 127: return True
        if parts[0] == 172 and 16 <= parts[1] <= 31: return True
        if parts[0] == 192 and parts[1] == 168: return True
    except (ValueError, IndexError):
        pass
    return False


def analyze_email_headers(headers_text: str) -> list[dict]:
    """
    Full email header analysis: extract IPs and geolocate each.
    Returns list of {"ip": str, "country": str, "city": str, "type": str}.
    """
    from pygeospy.geo import ip_to_location
    ips = extract_ips_from_email_headers(headers_text)
    results = []
    for ip in ips[:5]:  # limit API calls
        try:
            info = ip_to_location(ip)
            asn  = ip_to_asn(ip)
            results.append({
                "ip":      ip,
                "country": info.get("country", ""),
                "city":    info.get("city", ""),
                "isp":     info.get("isp", ""),
                "asn":     asn.get("asn"),
                "type":    asn.get("type", "unknown"),
                "lat":     info.get("lat"),
                "lon":     info.get("lon"),
            })
        except Exception as e:
            results.append({"ip": ip, "error": str(e)})
    return results


# ── Certificate transparency ──────────────────────────────────────────────────

@cached("crt_sh", ttl=7 * 86400)
def domain_cert_info(domain: str) -> list[dict]:
    """
    Query crt.sh for certificate transparency logs for a domain.
    Returns list of {"common_name": str, "issuer": str, "not_before": str}.
    """
    import httpx
    url  = f"https://crt.sh/?q={domain}&output=json"
    try:
        resp = httpx.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        seen = set()
        results = []
        for entry in data[:20]:
            name = entry.get("common_name", "")
            if name not in seen:
                seen.add(name)
                results.append({
                    "common_name": name,
                    "issuer":      entry.get("issuer_name", ""),
                    "not_before":  entry.get("not_before", ""),
                })
        return results
    except Exception as e:
        logger.warning(f"crt.sh query failed for {domain}: {e}")
        return []


# ── Full network analysis ─────────────────────────────────────────────────────

def analyze(target: str) -> dict:
    """
    Unified network OSINT analysis for an IP, domain, or email.

    Parameters
    ----------
    target : str
        IP address, domain name, or raw email headers.

    Returns
    -------
    dict with: type, location, asn, proxy_check, clues
    """
    clues: list[Clue] = []

    # Detect input type
    ip_pattern = r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$'
    if re.match(ip_pattern, target.strip()):
        # IP address analysis
        from pygeospy.geo import ip_to_location
        try:
            loc  = ip_to_location(target)
            asn  = ip_to_asn(target)
            prox = is_vpn_or_proxy(target)

            clues.append(Clue("network", "ip_location",
                              f"{loc['city']}, {loc['country']}",
                              confidence=0.8 if not prox.get("is_proxy") else 0.3,
                              narrows_to=loc.get("country"),
                              notes=f"ISP: {loc.get('isp', '')}"))
            if prox.get("is_proxy"):
                clues.append(Clue("network", "vpn_proxy", True, 0.9,
                                  notes="IP flagged as proxy/VPN by ip-api"))

            return {"type": "ip", "location": loc, "asn": asn, "proxy": prox, "clues": clues}
        except Exception as e:
            return {"type": "ip", "error": str(e), "clues": clues}

    elif "Received:" in target or "From:" in target:
        # Email headers
        results = analyze_email_headers(target)
        for r in results:
            if r.get("country"):
                clues.append(Clue("network", "email_relay_ip",
                                  r["ip"], 0.7, narrows_to=r["country"],
                                  notes=f"Mail relay: {r.get('isp', '')}"))
        return {"type": "email_headers", "relays": results, "clues": clues}

    else:
        # Domain
        certs = domain_cert_info(target)
        return {"type": "domain", "certificates": certs, "clues": clues}
