"""
pygeospy.exif — EXIF metadata extraction, GPS parsing, and forensics.
Pure Python (Pillow + exifread); no Rust needed — already fast enough.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pygeospy._types import Clue, ExifResult, LatLon
from pygeospy._utils import format_latlon

logger = logging.getLogger("pygeospy.exif")


# ── GPS conversion helpers ────────────────────────────────────────────────────

def _rational_to_float(value) -> float:
    """Convert IFDRational or (num, den) tuple to float."""
    try:
        return float(value)
    except TypeError:
        try:
            return value.numerator / value.denominator
        except AttributeError:
            if hasattr(value, 'values'):
                v = value.values
                if len(v) >= 1:
                    num, den = (v[0].num, v[0].den) if hasattr(v[0], 'num') else (v[0], 1)
                    return num / den if den else 0.0
    return 0.0


def _parse_gps_coord(dms_values, ref: str) -> float:
    """Convert exifread GPS DMS tag to decimal degrees."""
    try:
        deg = _rational_to_float(dms_values[0])
        mn  = _rational_to_float(dms_values[1])
        sec = _rational_to_float(dms_values[2])
        dd  = deg + mn / 60 + sec / 3600
        if ref.upper() in ("S", "W"):
            dd = -dd
        return dd
    except (IndexError, TypeError, ZeroDivisionError):
        return 0.0


def _parse_pillow_gps(gps_info: dict) -> Optional[LatLon]:
    """Parse GPS data from Pillow's _getexif() GPSInfo dict."""
    try:
        # Tag IDs: 1=LatRef, 2=Lat, 3=LonRef, 4=Lon, 5=AltRef, 6=Alt
        lat_ref = gps_info.get(1, "N")
        lat_dms = gps_info.get(2)
        lon_ref = gps_info.get(3, "E")
        lon_dms = gps_info.get(4)

        if not lat_dms or not lon_dms:
            return None

        def dms_to_dd(dms, ref):
            d = float(dms[0])
            m = float(dms[1])
            s = float(dms[2])
            v = d + m/60 + s/3600
            return -v if ref in ("S", "W") else v

        lat = dms_to_dd(lat_dms, lat_ref)
        lon = dms_to_dd(lon_dms, lon_ref)

        alt = None
        alt_ref = gps_info.get(5, 0)
        alt_val = gps_info.get(6)
        if alt_val is not None:
            alt = float(alt_val)
            if alt_ref == 1:
                alt = -alt

        result = LatLon(lat, lon)
        return result
    except Exception as e:
        logger.debug(f"Pillow GPS parse error: {e}")
        return None


# ── Core extraction ───────────────────────────────────────────────────────────

def extract(image_path: str | Path) -> ExifResult:
    """
    Extract all EXIF metadata from an image file.

    Returns an ExifResult with GPS coordinates (if present), camera info,
    timestamp, and a forensic flag for scrubbed EXIF.

    Supports JPEG, TIFF, HEIC (via Pillow).
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    result = ExifResult()

    # ── Try exifread first (more detailed GPS) ────────────────────────────────
    try:
        import exifread
        with open(image_path, "rb") as f:
            tags = exifread.process_file(f, details=True)

        result.raw_exif = {str(k): str(v) for k, v in tags.items()}

        # GPS extraction
        gps_lat  = tags.get("GPS GPSLatitude")
        gps_lat_ref  = tags.get("GPS GPSLatitudeRef")
        gps_lon  = tags.get("GPS GPSLongitude")
        gps_lon_ref  = tags.get("GPS GPSLongitudeRef")
        gps_alt  = tags.get("GPS GPSAltitude")

        if gps_lat and gps_lon:
            lat = _parse_gps_coord(gps_lat.values, str(gps_lat_ref or "N"))
            lon = _parse_gps_coord(gps_lon.values, str(gps_lon_ref or "E"))
            if lat != 0 or lon != 0:
                result.coordinates = LatLon(lat, lon)
                result.has_gps = True
                if gps_alt:
                    try:
                        result.altitude_m = _rational_to_float(gps_alt.values[0])
                    except Exception:
                        pass

        # Camera info
        result.camera_make  = str(tags.get("Image Make", "")).strip() or None
        result.camera_model = str(tags.get("Image Model", "")).strip() or None
        result.lens = str(tags.get("EXIF LensModel", tags.get("EXIF LensMake", ""))).strip() or None
        result.software = str(tags.get("Image Software", "")).strip() or None

        # Timestamp
        dt_str = str(tags.get("EXIF DateTimeOriginal", tags.get("Image DateTime", ""))).strip()
        if dt_str and dt_str != "0000:00:00 00:00:00":
            result.timestamp = dt_str

        # Forensic: check if EXIF is minimal / scrubbed
        non_trivial = {k for k in tags if not k.startswith("JPEGThumbnail")}
        result.exif_scrubbed = len(non_trivial) < 5

    except ImportError:
        logger.debug("exifread not installed; falling back to Pillow")
        _extract_with_pillow(image_path, result)
    except Exception as e:
        logger.warning(f"exifread error on {image_path}: {e}; falling back to Pillow")
        _extract_with_pillow(image_path, result)

    return result


def _extract_with_pillow(image_path: Path, result: ExifResult) -> None:
    """Fallback EXIF extraction using Pillow."""
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS

        img  = Image.open(image_path)
        raw  = img._getexif()
        if raw is None:
            result.exif_scrubbed = True
            return

        decoded = {TAGS.get(tag, str(tag)): val for tag, val in raw.items()}
        result.raw_exif = {k: str(v) for k, v in decoded.items()}

        gps_raw = decoded.get("GPSInfo")
        if gps_raw:
            coords = _parse_pillow_gps(gps_raw)
            if coords:
                result.coordinates = coords
                result.has_gps = True

        result.camera_make  = decoded.get("Make", "")  or None
        result.camera_model = decoded.get("Model", "") or None
        result.software     = decoded.get("Software", "") or None

        for key in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
            ts = decoded.get(key)
            if ts:
                result.timestamp = ts
                break

        result.exif_scrubbed = len(decoded) < 5

    except ImportError:
        raise ImportError("Pillow is required: pip install Pillow")
    except Exception as e:
        logger.warning(f"Pillow EXIF error: {e}")


# ── Batch processing ──────────────────────────────────────────────────────────

def batch_extract(directory: str | Path, extensions=(".jpg", ".jpeg", ".tiff", ".heic")) -> list[dict]:
    """
    Process all images in a directory and return a list of result dicts.
    Each dict includes the file path plus the ExifResult data.
    """
    directory = Path(directory)
    results = []
    for path in sorted(directory.rglob("*")):
        if path.suffix.lower() in extensions:
            try:
                r = extract(path)
                row = {
                    "file": str(path),
                    "has_gps": r.has_gps,
                    "lat": r.coordinates.lat if r.coordinates else None,
                    "lon": r.coordinates.lon if r.coordinates else None,
                    "altitude_m": r.altitude_m,
                    "timestamp": r.timestamp,
                    "camera": f"{r.camera_make or ''} {r.camera_model or ''}".strip() or None,
                    "lens": r.lens,
                    "exif_scrubbed": r.exif_scrubbed,
                }
                results.append(row)
            except Exception as e:
                results.append({"file": str(path), "error": str(e)})
    return results


# ── Forensic analysis ─────────────────────────────────────────────────────────

def forensic_flags(result: ExifResult) -> list[str]:
    """
    Return a list of forensic warning strings for an ExifResult.
    Useful for detecting edited/scrubbed/manipulated images.
    """
    flags = []
    if result.exif_scrubbed:
        flags.append("EXIF appears minimal or scrubbed — may have been cleaned.")
    if result.software:
        soft = result.software.lower()
        if any(k in soft for k in ("photoshop", "gimp", "lightroom", "snapseed", "facetune")):
            flags.append(f"Image editing software detected: {result.software}")
    if not result.timestamp:
        flags.append("No creation timestamp found in EXIF.")
    if not result.camera_make and not result.camera_model:
        flags.append("No camera make/model in EXIF — possible screenshot or re-upload.")
    return flags


def extract_clues(result: ExifResult) -> list[Clue]:
    """Convert ExifResult into Clue objects for the pipeline."""
    clues = []
    if result.has_gps and result.coordinates:
        clues.append(Clue(
            source="exif",
            clue_type="gps_coordinates",
            value=result.coordinates,
            confidence=0.98,
            narrows_to=result.coordinates,
            notes="GPS embedded in EXIF",
        ))
    if result.camera_make:
        clues.append(Clue(
            source="exif",
            clue_type="camera_make",
            value=result.camera_make,
            confidence=0.9,
            notes="May indicate country of purchase / target demographic",
        ))
    if result.timestamp:
        clues.append(Clue(
            source="exif",
            clue_type="timestamp",
            value=result.timestamp,
            confidence=0.95,
            notes="Camera clock; may be uncorrected for timezone",
        ))
    if result.exif_scrubbed:
        clues.append(Clue(
            source="exif",
            clue_type="exif_scrubbed",
            value=True,
            confidence=0.8,
            notes="Minimal EXIF — data may have been stripped",
        ))
    return clues


# ── Map output ────────────────────────────────────────────────────────────────

def map_gps_points(results: list[ExifResult] | list[dict], output_path: str = "exif_map.html") -> str:
    """
    Generate a Folium HTML map pinning all GPS-tagged images.
    Works with both ExifResult objects and batch_extract() dicts.
    """
    try:
        import folium
    except ImportError:
        raise ImportError("folium is required: pip install folium")

    points = []
    for r in results:
        if isinstance(r, ExifResult):
            if r.has_gps and r.coordinates:
                points.append((r.coordinates.lat, r.coordinates.lon, r.camera_model or "", r.timestamp or ""))
        elif isinstance(r, dict) and r.get("has_gps") and r.get("lat"):
            points.append((r["lat"], r["lon"], r.get("camera", ""), r.get("timestamp", "")))

    if not points:
        logger.warning("No GPS-tagged images to map.")
        return ""

    center_lat = sum(p[0] for p in points) / len(points)
    center_lon = sum(p[1] for p in points) / len(points)
    m = folium.Map(location=[center_lat, center_lon], zoom_start=10)

    for lat, lon, cam, ts in points:
        folium.Marker(
            [lat, lon],
            popup=folium.Popup(f"<b>{cam}</b><br>{ts}<br>{format_latlon(lat, lon)}", max_width=250),
            icon=folium.Icon(color="blue", icon="camera", prefix="fa"),
        ).add_to(m)

    m.save(output_path)
    logger.info(f"Map saved → {output_path}")
    return output_path
