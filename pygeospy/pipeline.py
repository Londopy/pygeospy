"""
pygeospy.pipeline — Unified analysis engine.
Single entry point: pygeospy.pipeline.analyze(input) → GeoResult

Chains all modules together, runs in parallel where possible,
and returns a ranked GeoResult with confidence-weighted candidates.
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from pygeospy._types import GeoResult, CandidateLocation, Clue, LatLon

logger = logging.getLogger("pygeospy.pipeline")

# ── Input type detection ──────────────────────────────────────────────────────

def _detect_input_type(inp: str) -> str:
    """Return "image" | "url" | "ip" | "coords" | "audio" | "text"."""
    import re
    inp = inp.strip()
    # IP address
    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', inp):
        return "ip"
    # URL
    if inp.startswith("http://") or inp.startswith("https://"):
        return "url"
    # Coordinate pair "lat,lon"
    if re.match(r'^-?\d+\.?\d*\s*,\s*-?\d+\.?\d*$', inp):
        return "coords"
    # File path
    if os.path.exists(inp):
        ext = Path(inp).suffix.lower()
        if ext in (".jpg", ".jpeg", ".png", ".tiff", ".heic", ".webp", ".bmp"):
            return "image"
        if ext in (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".opus"):
            return "audio"
        if ext in (".txt", ".md"):
            return "text"
    # Raw text
    return "text"


# ── Module runners ────────────────────────────────────────────────────────────

def _run_exif(image_path: str, result: GeoResult) -> list[Clue]:
    try:
        from pygeospy.exif import extract, extract_clues
        exif   = extract(image_path)
        clues  = extract_clues(exif)
        if exif.has_gps and exif.coordinates:
            result.candidate_coordinates.append(CandidateLocation(
                location=exif.coordinates,
                confidence=0.98,
                source_modules=["exif"],
                supporting_clues=clues,
                notes="GPS coordinates from EXIF",
            ))
            result.add_reasoning(f"EXIF GPS found: {exif.coordinates.lat:.5f}, {exif.coordinates.lon:.5f}")
        return clues
    except Exception as e:
        logger.warning(f"EXIF module error: {e}")
        return []


def _run_solar(image_path: str, result: GeoResult, shadow_ratio: Optional[float],
               shadow_azimuth: Optional[float]) -> list[Clue]:
    if shadow_ratio is None or shadow_azimuth is None:
        return []
    try:
        from pygeospy.solar import analyze_shadow
        solar = analyze_shadow(shadow_ratio, shadow_azimuth)
        result.add_reasoning(
            f"Solar analysis: elevation={solar.sun_elevation:.1f}°, "
            f"azimuth={solar.sun_azimuth:.1f}°, season={solar.estimated_season}"
        )
        if solar.hemisphere_hint:
            result.add_reasoning(f"Hemisphere hint from sun azimuth: {solar.hemisphere_hint}")
        return solar.clues
    except Exception as e:
        logger.warning(f"Solar module error: {e}")
        return []


def _run_visual(image_path: str, result: GeoResult, vision_backend: str) -> list[Clue]:
    try:
        from pygeospy import visual
        visual.set_backend(vision_backend)
        analysis = visual.analyze(image_path)
        clues    = analysis.get("clues", [])
        countries = analysis.get("candidate_countries", [])
        # Merge country probabilities
        for country, prob in countries:
            # Check if already in candidate_countries
            existing = dict(result.candidate_countries)
            existing[country] = existing.get(country, 0) + prob
            result.candidate_countries = list(existing.items())
        if clues:
            result.add_reasoning(f"Visual analysis extracted {len(clues)} clues via {vision_backend}")
        return clues
    except Exception as e:
        logger.warning(f"Visual module error: {e}")
        return []


def _run_language(image_path: str, result: GeoResult) -> list[Clue]:
    try:
        from pygeospy.language import analyze
        lang_result = analyze(image_path)
        clues = lang_result.get("clues", [])
        for place in lang_result.get("geocoded_places", []):
            result.candidate_coordinates.append(CandidateLocation(
                location=LatLon(place["lat"], place["lon"]),
                confidence=0.5,
                source_modules=["language"],
                notes=f"Place name from sign text: {place['name']}",
            ))
            result.add_reasoning(f"Sign text geocoded: '{place['name']}' → {place['lat']:.4f}, {place['lon']:.4f}")
        return clues
    except Exception as e:
        logger.warning(f"Language module error: {e}")
        return []


def _run_chronos(image_path: str, result: GeoResult) -> list[Clue]:
    try:
        from pygeospy.chronos import analyze
        chrono = analyze(image_path=image_path)
        return chrono.get("clues", [])
    except Exception as e:
        logger.warning(f"Chronos module error: {e}")
        return []


def _run_audio(audio_path: str, result: GeoResult) -> list[Clue]:
    try:
        from pygeospy.acoustic import analyze
        acoustic = analyze(audio_path)
        clues    = acoustic.get("clues", [])
        if clues:
            result.add_reasoning(f"Acoustic analysis: {len(clues)} geographic signals from audio")
        return clues
    except Exception as e:
        logger.warning(f"Acoustic module error: {e}")
        return []


def _run_ip(ip: str, result: GeoResult) -> list[Clue]:
    try:
        from pygeospy.geo import ip_to_location, ip_to_latlon
        info = ip_to_location(ip)
        loc  = ip_to_latlon(ip)
        if loc:
            result.candidate_coordinates.append(CandidateLocation(
                location=loc,
                confidence=0.75,
                source_modules=["geo_ip"],
                notes=f"IP: {ip} → {info.get('city')}, {info.get('country')}",
            ))
        country = info.get("country", "")
        if country:
            existing = dict(result.candidate_countries)
            existing[country] = existing.get(country, 0) + 0.75
            result.candidate_countries = list(existing.items())
        result.add_reasoning(f"IP geolocation: {ip} → {info.get('city')}, {info.get('country')}")
        return [Clue("geo", "ip_location", ip, 0.75, narrows_to=country)]
    except Exception as e:
        logger.warning(f"IP module error: {e}")
        return []


# ── Candidate aggregation ─────────────────────────────────────────────────────

def _aggregate_country_probabilities(result: GeoResult) -> None:
    """Normalise and sort country probabilities."""
    if not result.candidate_countries:
        return
    counts: dict[str, float] = {}
    for country, prob in result.candidate_countries:
        counts[country] = counts.get(country, 0) + prob
    total = sum(counts.values()) or 1.0
    result.candidate_countries = sorted(
        [(c, round(p / total, 3)) for c, p in counts.items()],
        key=lambda x: -x[1],
    )


def _generate_summary(result: GeoResult) -> str:
    best = result.best_location
    top_country = result.top_country
    n_clues = len(result.clues)

    lines = [f"pygeospy analysis: {n_clues} clues from {result.input_type} input."]
    if best:
        lines.append(f"Best candidate: {best.location.lat:.4f}, {best.location.lon:.4f} "
                     f"({best.confidence:.0%} confidence) via {', '.join(best.source_modules)}.")
    if top_country:
        top_prob = result.candidate_countries[0][1] if result.candidate_countries else 0
        lines.append(f"Most likely country: {top_country} ({top_prob:.0%}).")
    if not best and not top_country:
        lines.append("Insufficient evidence to determine location.")
    return " ".join(lines)


# ── Main entry point ──────────────────────────────────────────────────────────

def analyze(
    input_path: str,
    shadow_ratio: Optional[float] = None,
    shadow_azimuth: Optional[float] = None,
    vision_backend: str = "none",
    modules: Optional[list[str]] = None,
    parallel: bool = True,
    output_dir: Optional[str] = None,
    export: bool = False,
) -> GeoResult:
    """
    Full geolocation analysis from a single input.

    Parameters
    ----------
    input_path : str
        Image path, IP address, "lat,lon" string, audio path, or text.
    shadow_ratio : float, optional
        shadow_length / object_height for solar analysis.
    shadow_azimuth : float, optional
        Shadow pointing direction (degrees, 0=N) for solar analysis.
    vision_backend : str
        Vision model to use for visual clue extraction.
        "none" | "claude" | "gpt4v" | "llava"
    modules : list[str], optional
        Whitelist of modules to run. Default: all applicable.
    parallel : bool
        Run independent modules in parallel threads.
    output_dir : str, optional
        Directory for exported files (only if export=True).
    export : bool
        Auto-export all formats after analysis.

    Returns
    -------
    GeoResult
    """
    start = time.monotonic()

    result = GeoResult(input_path=input_path)
    result.input_type = _detect_input_type(input_path)

    logger.info(f"Pipeline starting: input_type={result.input_type}")
    result.add_reasoning(f"Input detected as: {result.input_type}")

    all_clues: list[Clue] = []

    # ── IP shortcut ───────────────────────────────────────────────────────────
    if result.input_type == "ip":
        all_clues.extend(_run_ip(input_path, result))

    # ── Coordinate shortcut ───────────────────────────────────────────────────
    elif result.input_type == "coords":
        try:
            lat, lon = map(float, input_path.split(","))
            from pygeospy.geo import reverse_geocode
            info = reverse_geocode(lat, lon)
            result.candidate_coordinates.append(CandidateLocation(
                location=LatLon(lat, lon), confidence=1.0,
                source_modules=["direct"],
                notes=info.get("display_name", ""),
            ))
            result.add_reasoning(f"Direct coordinates: {lat}, {lon} → {info.get('country', '')}")
            all_clues.append(Clue("direct", "coordinates", f"{lat},{lon}", 1.0,
                                  narrows_to=info.get("country")))
            if info.get("country"):
                result.candidate_countries = [(info["country"], 1.0)]
        except Exception as e:
            logger.warning(f"Coordinate parse error: {e}")

    # ── Image pipeline ────────────────────────────────────────────────────────
    elif result.input_type == "image":
        enabled = set(modules or ["exif", "solar", "visual", "language", "chronos"])

        if parallel:
            tasks = {}
            with ThreadPoolExecutor(max_workers=4) as pool:
                if "exif" in enabled:
                    tasks["exif"]     = pool.submit(_run_exif, input_path, result)
                if "solar" in enabled:
                    tasks["solar"]    = pool.submit(_run_solar, input_path, result, shadow_ratio, shadow_azimuth)
                if "visual" in enabled:
                    tasks["visual"]   = pool.submit(_run_visual, input_path, result, vision_backend)
                if "language" in enabled:
                    tasks["language"] = pool.submit(_run_language, input_path, result)
                if "chronos" in enabled:
                    tasks["chronos"]  = pool.submit(_run_chronos, input_path, result)

                for name, future in tasks.items():
                    try:
                        all_clues.extend(future.result(timeout=60))
                    except Exception as e:
                        logger.warning(f"Module {name} thread error: {e}")
        else:
            if "exif"     in enabled: all_clues.extend(_run_exif(input_path, result))
            if "solar"    in enabled: all_clues.extend(_run_solar(input_path, result, shadow_ratio, shadow_azimuth))
            if "visual"   in enabled: all_clues.extend(_run_visual(input_path, result, vision_backend))
            if "language" in enabled: all_clues.extend(_run_language(input_path, result))
            if "chronos"  in enabled: all_clues.extend(_run_chronos(input_path, result))

    # ── Audio pipeline ────────────────────────────────────────────────────────
    elif result.input_type == "audio":
        all_clues.extend(_run_audio(input_path, result))

    # ── Text pipeline ─────────────────────────────────────────────────────────
    elif result.input_type == "text":
        text = Path(input_path).read_text(encoding="utf-8") if os.path.exists(input_path) else input_path
        from pygeospy.language import analyze_text
        signals = analyze_text(text)
        all_clues.extend(signals.get("clues", []))
        result.add_reasoning("Analyzed as plain text — language and regional signals extracted.")

    # ── Collate ───────────────────────────────────────────────────────────────
    result.clues = all_clues
    _aggregate_country_probabilities(result)

    # Sort candidates by confidence
    result.candidate_coordinates.sort(key=lambda c: c.confidence, reverse=True)

    # Summary
    elapsed = time.monotonic() - start
    result.summary = _generate_summary(result)
    result.add_reasoning(f"Analysis complete in {elapsed:.1f}s. {len(all_clues)} clues found.")

    # Auto-export
    if export:
        out_dir = output_dir or "pygeospy_output"
        from pygeospy.export import export_all
        paths = export_all(result, output_dir=out_dir)
        logger.info(f"Exported to {out_dir}: {list(paths.keys())}")

    logger.info(result.summary)
    return result


# ── CLI-friendly wrapper ──────────────────────────────────────────────────────

def quick_locate(image_path: str, vision_backend: str = "none") -> Optional[LatLon]:
    """
    One-liner: analyze an image and return the best candidate LatLon.
    Returns None if no location could be determined.
    """
    result = analyze(image_path, vision_backend=vision_backend)
    best = result.best_location
    return best.location if best else None
