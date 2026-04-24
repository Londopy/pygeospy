"""
geoint.acoustic — Audio-based geographic signals (experimental).
Bird species → range map, language/accent ID, siren classification.
"""
from __future__ import annotations

import logging
from typing import Optional

from geoint._types import Clue

logger = logging.getLogger("geoint.acoustic")


# ── Bird species identification ───────────────────────────────────────────────

def identify_birds(audio_path: str, api_key: Optional[str] = None) -> list[dict]:
    """
    Submit audio to the BirdNET Analyzer API for species identification.
    Returns list of {"species": str, "common_name": str, "confidence": float}.

    Optionally uses the BirdNET-Analyzer local model if no API key given.
    """
    # Try local BirdNET-Analyzer first (no key needed)
    try:
        from birdnetlib import Recording
        from birdnetlib.analyzer import Analyzer

        analyzer  = Analyzer()
        recording = Recording(analyzer, audio_path, min_conf=0.25)
        recording.analyze()

        results = []
        for det in recording.detections:
            results.append({
                "species":     det.get("scientific_name", ""),
                "common_name": det.get("common_name", ""),
                "confidence":  det.get("confidence", 0),
                "start_time":  det.get("start_time", 0),
                "end_time":    det.get("end_time", 0),
            })
        return results

    except ImportError:
        logger.debug("birdnetlib not installed; trying API")
    except Exception as e:
        logger.warning(f"BirdNET local error: {e}")

    # Fallback: BirdNET API
    api_key = api_key or __import__("os").environ.get("BIRDNET_API_KEY", "")
    if not api_key:
        logger.warning("BirdNET: no local model and no API key. Install birdnetlib for offline analysis.")
        return []

    try:
        import httpx
        with open(audio_path, "rb") as f:
            audio_data = f.read()
        resp = httpx.post(
            "https://birdnet.cornell.edu/api/analyze",
            files={"audio": audio_data},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("detections", [])
    except Exception as e:
        logger.warning(f"BirdNET API error: {e}")
        return []


# ── Bird range → region ───────────────────────────────────────────────────────

# Simplified range database for common indicator species
_BIRD_RANGES = {
    "Kookaburra":            ["Australia"],
    "Laughing Kookaburra":   ["Australia"],
    "Tui":                   ["New Zealand"],
    "Bellbird":              ["New Zealand"],
    "Red-billed Quelea":     ["Sub-Saharan Africa"],
    "Secretary Bird":        ["Sub-Saharan Africa"],
    "African Grey Parrot":   ["Central Africa"],
    "Japanese Bush Warbler": ["Japan"],
    "Japanese White-eye":    ["Japan", "South Korea"],
    "Common Cuckoo":         ["Europe", "Asia"],
    "Red Kite":              ["UK", "Western Europe"],
    "Robin":                 ["Europe", "UK"],
    "Bald Eagle":            ["United States", "Canada"],
    "Cardinal":              ["United States", "Canada"],
    "Wild Turkey":           ["United States"],
    "Roadrunner":            ["United States (Southwest)", "Mexico"],
    "Quetzal":               ["Central America"],
    "Scarlet Macaw":         ["Central America", "South America"],
    "Toucan":                ["Central America", "South America"],
    "Indian Peafowl":        ["India", "Sri Lanka"],
    "Indian Roller":         ["India", "South Asia"],
    "Siberian Crane":        ["Russia", "India (winter)"],
}


def birds_to_regions(detections: list[dict]) -> list[Clue]:
    """Convert bird detections to geographic Clue objects."""
    clues = []
    for det in detections:
        common = det.get("common_name", "")
        conf   = det.get("confidence", 0.5)
        regions = _BIRD_RANGES.get(common)
        if regions:
            clues.append(Clue(
                source="acoustic",
                clue_type="bird_species",
                value=common,
                confidence=min(conf, 0.85),
                narrows_to=", ".join(regions),
                notes=f"Species range: {', '.join(regions)}",
            ))
    return clues


# ── Siren classification ──────────────────────────────────────────────────────

# Emergency siren patterns by country (simplified frequency characteristics)
_SIREN_PATTERNS = {
    "uk_two_tone":   {"freq_hz": [500, 1000], "pattern": "alternating", "regions": ["United Kingdom"]},
    "usa_wail":      {"freq_hz": [700, 1200], "pattern": "sweep",       "regions": ["United States"]},
    "eu_nee_naw":    {"freq_hz": [800, 1000], "pattern": "rapid_alt",   "regions": ["France", "Germany", "Italy"]},
    "japan_warble":  {"freq_hz": [960, 770],  "pattern": "double",      "regions": ["Japan"]},
    "russia_signal": {"freq_hz": [400, 1000], "pattern": "single_sweep", "regions": ["Russia", "Eastern Europe"]},
}


def classify_siren(audio_path: str) -> Optional[dict]:
    """
    Attempt to classify emergency siren type from audio.
    Returns {"type": str, "regions": list, "confidence": float} or None.

    Note: This is a stub — real implementation requires audio DSP.
    Install librosa and scipy for spectral analysis.
    """
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(audio_path, duration=5.0)
        # Dominant frequency via spectral centroid
        spec_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)
        mean_freq = float(np.mean(spec_centroid))

        # Very rough classification by centroid frequency
        if 400 < mean_freq < 700:
            return {"type": "uk_two_tone", "regions": ["United Kingdom"], "confidence": 0.4}
        elif 700 < mean_freq < 1000:
            return {"type": "usa_wail", "regions": ["United States"], "confidence": 0.4}
        elif 1000 < mean_freq < 1200:
            return {"type": "eu_nee_naw", "regions": ["France", "Germany", "Italy"], "confidence": 0.35}
        return None

    except ImportError:
        logger.debug("librosa not installed; siren classification unavailable")
        return None
    except Exception as e:
        logger.warning(f"Siren classification error: {e}")
        return None


# ── Traffic / driving side inference ─────────────────────────────────────────

def infer_driving_side_from_audio(audio_path: str) -> Optional[str]:
    """
    Infer driving side (left/right) from traffic audio patterns.
    This is highly experimental — genuine implementation needs labelled training data.
    Returns "left", "right", or None.
    """
    # Placeholder: real implementation would analyse traffic flow using
    # binaural audio or doppler shift patterns.
    logger.debug("Driving side audio inference not yet implemented.")
    return None


# ── Language identification from speech ──────────────────────────────────────

def identify_language(audio_path: str) -> Optional[dict]:
    """
    Identify spoken language from audio.
    Uses Whisper (local, offline) if available.
    Returns {"language": str, "confidence": float} or None.
    """
    try:
        import whisper
        model = whisper.load_model("base")
        result = model.transcribe(audio_path)
        lang  = result.get("language", "unknown")
        # Whisper doesn't expose confidence directly; use segment avg logprob
        segs  = result.get("segments", [])
        avg_logprob = (sum(s.get("avg_logprob", -1) for s in segs) / len(segs)) if segs else -1
        confidence  = max(0.0, min(1.0, (avg_logprob + 1.0)))  # rough normalisation
        return {"language": lang, "confidence": round(confidence, 2)}
    except ImportError:
        logger.debug("openai-whisper not installed; language ID unavailable")
        return None
    except Exception as e:
        logger.warning(f"Whisper language ID error: {e}")
        return None


# ── Call to prayer detection ──────────────────────────────────────────────────

def detect_call_to_prayer(audio_path: str) -> dict:
    """
    Detect Islamic call to prayer (adhan) in audio.
    Returns {"detected": bool, "confidence": float, "region_hint": str}.
    Stub — real implementation requires an audio classifier.
    """
    logger.debug("Call-to-prayer detection requires a trained audio classifier.")
    return {"detected": False, "confidence": 0.0,
            "region_hint": "Islamic world if detected"}


# ── Full acoustic analysis ────────────────────────────────────────────────────

def analyze(audio_path: str) -> dict:
    """
    Full acoustic geographic analysis:
    1. Bird species identification → range clues
    2. Siren classification → country hints
    3. Language identification from speech

    Returns
    -------
    dict with: birds, siren, language, clues
    """
    clues: list[Clue] = []

    # Birds
    birds = identify_birds(audio_path)
    bird_clues = birds_to_regions(birds)
    clues.extend(bird_clues)

    # Siren
    siren = classify_siren(audio_path)
    if siren:
        clues.append(Clue("acoustic", "siren_type",
                          siren["type"], siren["confidence"],
                          narrows_to=", ".join(siren["regions"]),
                          notes="Emergency siren tone classification"))

    # Language
    lang = identify_language(audio_path)
    if lang and lang.get("language") != "unknown":
        clues.append(Clue("acoustic", "spoken_language",
                          lang["language"], lang.get("confidence", 0.5),
                          notes="Whisper language detection"))

    return {
        "birds":    birds,
        "siren":    siren,
        "language": lang,
        "clues":    clues,
    }
