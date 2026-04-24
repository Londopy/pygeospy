"""
geoint.satellite — Sentinel-2 open imagery download, NDVI, change detection.
Raster math delegated to _rustcore.raster for large arrays.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from geoint._utils import rustcore, retry
from geoint._cache import cached
from geoint._types import BoundingBox

logger = logging.getLogger("geoint.satellite")
_R = rustcore("raster")


# ── Sentinel-2 download (Copernicus/SentinelHub) ─────────────────────────────

@cached("sentinel_products", ttl=86400)
@retry(times=2, delay=3.0)
def search_sentinel2(
    bbox: BoundingBox,
    start_date: str,
    end_date: str,
    max_cloud_pct: float = 20.0,
    limit: int = 5,
) -> list[dict]:
    """
    Search Copernicus OData API for Sentinel-2 products.
    Returns list of product metadata dicts.

    Parameters
    ----------
    bbox : BoundingBox
    start_date : str  "YYYY-MM-DD"
    end_date   : str  "YYYY-MM-DD"
    max_cloud_pct : float  0–100
    """
    import httpx
    # Copernicus Data Space Ecosystem (CDSE) OData API — free, no key required
    base = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
    aoi  = (f"POLYGON(({bbox.min_lon} {bbox.min_lat},{bbox.max_lon} {bbox.min_lat},"
            f"{bbox.max_lon} {bbox.max_lat},{bbox.min_lon} {bbox.max_lat},"
            f"{bbox.min_lon} {bbox.min_lat}))")
    filter_str = (
        f"Collection/Name eq 'SENTINEL-2' "
        f"and OData.CSC.Intersects(area=geography'SRID=4326;{aoi}') "
        f"and ContentDate/Start gt {start_date}T00:00:00.000Z "
        f"and ContentDate/Start lt {end_date}T23:59:59.000Z "
        f"and Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq "
        f"'cloudCover' and att/OData.CSC.DoubleAttribute/Value le {max_cloud_pct})"
    )
    params = {"$filter": filter_str, "$top": limit, "$orderby": "ContentDate/Start desc"}
    resp = httpx.get(base, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json().get("value", [])


def download_sentinel2_preview(product_id: str, output_dir: str = ".") -> Optional[str]:
    """
    Download the quicklook preview thumbnail for a Sentinel-2 product.
    Returns path to saved image or None.
    """
    import httpx
    url  = f"https://catalogue.dataspace.copernicus.eu/odata/v1/Products({product_id})/Nodes"
    try:
        resp = httpx.get(url, timeout=15)
        resp.raise_for_status()
        # Find preview node
        for node in resp.json().get("value", []):
            if "preview" in node.get("Name", "").lower() or node.get("Name", "").endswith(".png"):
                dl_url = node.get("DownloadLink", "")
                if dl_url:
                    img_resp = httpx.get(dl_url, timeout=30)
                    img_resp.raise_for_status()
                    fname = Path(output_dir) / f"preview_{product_id[:8]}.png"
                    with open(fname, "wb") as f:
                        f.write(img_resp.content)
                    return str(fname)
    except Exception as e:
        logger.warning(f"Preview download failed: {e}")
    return None


# ── Band loading ──────────────────────────────────────────────────────────────

def load_band_as_array(tiff_path: str, band: int = 1) -> list[float]:
    """
    Load a GeoTIFF band as a flat float list.
    Requires rasterio + numpy.
    """
    try:
        import rasterio
        import numpy as np
        with rasterio.open(tiff_path) as src:
            data = src.read(band).astype(float).flatten()
            # Normalise DN to 0–1 (Sentinel-2 is 0–10000)
            data = data / 10000.0
            return data.tolist()
    except ImportError:
        raise ImportError("rasterio and numpy required: pip install rasterio numpy")


# ── Spectral indices ──────────────────────────────────────────────────────────

def compute_ndvi(red_band: list[float], nir_band: list[float]) -> list[float]:
    """
    Compute NDVI from red and NIR band arrays.
    Uses Rust raster module for speed on large arrays.
    """
    if _R:
        return _R.ndvi(red_band, nir_band)
    return [(n - r) / (n + r) if (n + r) > 1e-9 else 0.0
            for r, n in zip(red_band, nir_band)]


def compute_evi(red: list[float], nir: list[float], blue: list[float]) -> list[float]:
    """Compute Enhanced Vegetation Index (EVI)."""
    if _R:
        return _R.evi(red, nir, blue)
    return [2.5*(n-r)/(n+6*r-7.5*b+1) if abs(n+6*r-7.5*b+1) > 1e-9 else 0.0
            for r, n, b in zip(red, nir, blue)]


def compute_mndwi(green: list[float], swir: list[float]) -> list[float]:
    """Modified Normalized Difference Water Index — highlights water bodies."""
    if _R:
        return _R.mndwi(green, swir)
    return [(g-s)/(g+s) if (g+s) > 1e-9 else 0.0 for g, s in zip(green, swir)]


def compute_urban_heat_index(swir: list[float], nir: list[float]) -> list[float]:
    """Built-up index: high values = urban / industrial areas."""
    if _R:
        return _R.urban_heat_index(swir, nir)
    return [(s-n)/(s+n) if (s+n) > 1e-9 else 0.0 for s, n in zip(swir, nir)]


# ── Statistics ────────────────────────────────────────────────────────────────

def band_statistics(values: list[float]) -> dict:
    """Compute min, max, mean, std, median for a band."""
    if _R:
        mn, mx, mean, std, med = _R.pixel_statistics(values)
        return {"min": mn, "max": mx, "mean": mean, "std": std, "median": med}
    import statistics
    return {
        "min": min(values), "max": max(values),
        "mean": statistics.mean(values),
        "std": statistics.stdev(values) if len(values) > 1 else 0.0,
        "median": statistics.median(values),
    }


# ── Change detection ──────────────────────────────────────────────────────────

def detect_change(
    ndvi_before: list[float],
    ndvi_after: list[float],
    threshold: float = 0.2,
) -> dict:
    """
    Simple NDVI differencing change detection.
    Returns statistics on changed pixels.
    """
    if len(ndvi_before) != len(ndvi_after):
        raise ValueError("Arrays must have same length")

    diffs     = [a - b for a, b in zip(ndvi_after, ndvi_before)]
    decreased = [d for d in diffs if d < -threshold]  # vegetation loss
    increased = [d for d in diffs if d > threshold]   # vegetation gain
    n         = len(diffs)

    return {
        "total_pixels":   n,
        "loss_pixels":    len(decreased),
        "gain_pixels":    len(increased),
        "loss_pct":       100 * len(decreased) / n if n else 0,
        "gain_pct":       100 * len(increased) / n if n else 0,
        "mean_change":    sum(diffs) / n if n else 0,
        "max_loss":       min(diffs) if diffs else 0,
        "max_gain":       max(diffs) if diffs else 0,
        "interpretation": _interpret_change(len(decreased)/n if n else 0, len(increased)/n if n else 0),
    }


def _interpret_change(loss_frac: float, gain_frac: float) -> str:
    if loss_frac > 0.3:
        return "Significant vegetation loss — possible deforestation, fire, drought, or urban expansion."
    if gain_frac > 0.3:
        return "Significant vegetation gain — possible reforestation, crop growth, or flooding recession."
    if loss_frac > 0.1:
        return "Moderate vegetation loss."
    return "Minor or no significant change detected."


# ── OpenAerialMap ─────────────────────────────────────────────────────────────

@cached("oam_search", ttl=86400)
def search_open_aerial(bbox: BoundingBox, limit: int = 5) -> list[dict]:
    """
    Search OpenAerialMap for high-resolution aerial imagery covering a bbox.
    Returns list of image metadata dicts.
    """
    import httpx
    url = "https://api.openaerialmap.org/meta"
    params = {
        "bbox": f"{bbox.min_lon},{bbox.min_lat},{bbox.max_lon},{bbox.max_lat}",
        "limit": limit,
    }
    try:
        resp = httpx.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("results", [])
    except Exception as e:
        logger.warning(f"OpenAerialMap search failed: {e}")
        return []


# ── Full pipeline ─────────────────────────────────────────────────────────────

def analyze_area(
    bbox: BoundingBox,
    start_date: str,
    end_date: str,
    output_dir: str = ".",
) -> dict:
    """
    Run a full satellite analysis for a bounding box:
    1. Search Sentinel-2 products
    2. Download preview thumbnails
    3. Return metadata + aerial map links

    Returns
    -------
    dict with: products, aerial_images, ndvi_stats (if bands available)
    """
    products = search_sentinel2(bbox, start_date, end_date)
    aerial   = search_open_aerial(bbox)

    return {
        "bbox":          bbox.to_dict(),
        "sentinel_products": [
            {"id": p.get("Id"), "name": p.get("Name"), "date": p.get("ContentDate", {}).get("Start"), "cloud_pct": None}
            for p in products
        ],
        "aerial_images": [
            {"title": a.get("title", ""), "url": a.get("uuid", ""), "gsd_m": a.get("gsd")}
            for a in aerial
        ],
        "product_count": len(products),
        "aerial_count":  len(aerial),
    }
