"""
geoint.visual — Visual clue extraction from images.
Supports pluggable vision backends: Claude, GPT-4V, LLaVA (offline), or rule-based.
Returns structured Clue objects for the pipeline.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Optional, Any

from geoint._types import Clue, GeoResult

logger = logging.getLogger("geoint.visual")

# ── Vision backend registry ───────────────────────────────────────────────────

_BACKEND = "none"  # default: rule-based only

AVAILABLE_BACKENDS = ("claude", "gpt4v", "llava", "none")

def set_backend(backend: str, **kwargs) -> None:
    """
    Configure the vision model backend.

    Parameters
    ----------
    backend : str
        "claude" | "gpt4v" | "llava" | "none"
    **kwargs :
        backend-specific options (api_key, model, base_url, etc.)
    """
    global _BACKEND, _BACKEND_KWARGS
    if backend not in AVAILABLE_BACKENDS:
        raise ValueError(f"Unknown backend {backend!r}. Choose from {AVAILABLE_BACKENDS}")
    _BACKEND = backend
    _BACKEND_KWARGS = kwargs
    logger.info(f"Vision backend set to: {backend}")

_BACKEND_KWARGS: dict = {}


# ── System prompt for geographic clue extraction ──────────────────────────────

_SYSTEM_PROMPT = """You are a geographic intelligence analyst specializing in visual geolocation.
Your task is to analyze the image and extract every geographic signal you can find.

For each signal, output a JSON object with:
- "type": the type of clue (e.g. "power_pole", "road_marking", "sign_script", "vegetation", "architecture", "vehicle", "road_sign")
- "value": what you observed (be specific)
- "region_hint": which region/country this suggests (can be multiple, separated by commas)
- "confidence": 0.0–1.0
- "notes": brief reasoning

Return a JSON array of clue objects. Output ONLY valid JSON, no prose.
Focus on: infrastructure, road markings, signs, vegetation, architecture, vehicles, writing systems."""


def _encode_image(image_path: str) -> str:
    """Base64-encode an image for API submission."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _image_media_type(image_path: str) -> str:
    ext = Path(image_path).suffix.lower()
    return {"jpg": "image/jpeg", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "image/jpeg")


# ── Backend implementations ───────────────────────────────────────────────────

def _call_claude(image_path: str, prompt: str) -> str:
    try:
        import anthropic
    except ImportError:
        raise ImportError("anthropic SDK required: pip install anthropic")

    api_key = _BACKEND_KWARGS.get("api_key") or __import__("os").environ.get("ANTHROPIC_API_KEY")
    model   = _BACKEND_KWARGS.get("model", "claude-opus-4-6")
    client  = anthropic.Anthropic(api_key=api_key)

    b64 = _encode_image(image_path)
    media = _image_media_type(image_path)

    msg = client.messages.create(
        model=model,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return msg.content[0].text


def _call_gpt4v(image_path: str, prompt: str) -> str:
    try:
        import openai
    except ImportError:
        raise ImportError("openai SDK required: pip install openai")

    api_key = _BACKEND_KWARGS.get("api_key") or __import__("os").environ.get("OPENAI_API_KEY")
    model   = _BACKEND_KWARGS.get("model", "gpt-4o")
    client  = openai.OpenAI(api_key=api_key)

    b64 = _encode_image(image_path)
    media = _image_media_type(image_path)

    resp = client.chat.completions.create(
        model=model,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text",       "text": _SYSTEM_PROMPT + "\n\n" + prompt},
                {"type": "image_url",  "image_url": {"url": f"data:{media};base64,{b64}"}},
            ],
        }],
    )
    return resp.choices[0].message.content


def _call_llava(image_path: str, prompt: str) -> str:
    """Call LLaVA via Ollama local API."""
    import httpx
    base_url = _BACKEND_KWARGS.get("base_url", "http://localhost:11434")
    model    = _BACKEND_KWARGS.get("model", "llava:13b")
    b64      = _encode_image(image_path)

    payload = {
        "model": model,
        "prompt": _SYSTEM_PROMPT + "\n\n" + prompt,
        "images": [b64],
        "stream": False,
    }
    resp = httpx.post(f"{base_url}/api/generate", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json().get("response", "")


# ── Clue parsing ──────────────────────────────────────────────────────────────

def _parse_clues(raw: str) -> list[Clue]:
    """Parse JSON array of clue dicts from model output."""
    # Strip markdown code blocks if present
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON array from mixed text
        import re
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        if m:
            try:
                items = json.loads(m.group(0))
            except json.JSONDecodeError:
                logger.warning("Could not parse vision model JSON output")
                return []
        else:
            return []

    clues = []
    for item in items:
        clues.append(Clue(
            source="visual",
            clue_type=item.get("type", "unknown"),
            value=item.get("value", ""),
            confidence=float(item.get("confidence", 0.5)),
            narrows_to=item.get("region_hint"),
            notes=item.get("notes", ""),
        ))
    return clues


# ── Rule-based fallback classifier ────────────────────────────────────────────

# Geographic signals extracted from known visual databases
_RULE_SIGNALS = {
    "yellow_centerline": ("road_marking", "North America, Japan, South Korea, parts of Asia", 0.7),
    "blue_circle_sign":  ("road_sign",    "European Union mandatory sign", 0.75),
    "red_triangle_sign": ("road_sign",    "European Union warning sign", 0.7),
    "diamond_yellow":    ("road_sign",    "USA, Canada, Australia warning", 0.7),
    "orange_clay_roof":  ("architecture", "Mediterranean, Balkans, South America", 0.65),
    "onion_dome":        ("architecture", "Russia, Eastern Europe", 0.85),
    "minaret":           ("architecture", "Islamic world", 0.85),
    "pagoda":            ("architecture", "East / Southeast Asia", 0.85),
    "baobab":            ("vegetation",   "sub-Saharan Africa, Madagascar", 0.9),
    "date_palm":         ("vegetation",   "Middle East, North Africa", 0.8),
    "eucalyptus":        ("vegetation",   "Australia, Portugal, Spain, Africa (planted)", 0.65),
    "cyrillic_text":     ("language",     "Russia, Eastern Europe, Central Asia", 0.9),
    "arabic_text":       ("language",     "Middle East, North Africa", 0.9),
    "devanagari_text":   ("language",     "India, Nepal", 0.9),
    "hangul_text":       ("language",     "South Korea", 0.95),
    "thai_text":         ("language",     "Thailand", 0.95),
    "yellow_rear_plate": ("vehicle",      "UK, Netherlands", 0.8),
    "left_hand_traffic": ("infrastructure", "UK, Japan, Australia, India, South Africa", 0.9),
    "red_asphalt":       ("road_surface", "Netherlands, Portugal, Nordic countries", 0.7),
    "concrete_panel_buildings": ("architecture", "Former Soviet states", 0.75),
}

def rule_based_clues(description: str) -> list[Clue]:
    """
    Extract clues from a text description using keyword matching.
    Used as fallback when no vision model is available.
    """
    desc_lower = description.lower()
    clues = []
    for keyword, (clue_type, region, conf) in _RULE_SIGNALS.items():
        signal_kw = keyword.replace("_", " ")
        if signal_kw in desc_lower or keyword.replace("_", " ") in desc_lower:
            clues.append(Clue(
                source="visual_rule",
                clue_type=clue_type,
                value=keyword,
                confidence=conf,
                narrows_to=region,
                notes=f"Keyword match: '{signal_kw}'",
            ))
    return clues


# ── Country probability from clues ────────────────────────────────────────────

# Simplified mapping: region hint string → country probability dict
_REGION_TO_COUNTRIES = {
    "north america":   {"United States": 0.7, "Canada": 0.2, "Mexico": 0.1},
    "europe":          {"Germany": 0.15, "France": 0.12, "UK": 0.1, "Italy": 0.1, "Spain": 0.08},
    "eastern europe":  {"Russia": 0.3, "Ukraine": 0.15, "Poland": 0.1, "Romania": 0.1},
    "middle east":     {"Saudi Arabia": 0.2, "UAE": 0.15, "Turkey": 0.15, "Iran": 0.1, "Iraq": 0.1},
    "east africa":     {"Kenya": 0.3, "Tanzania": 0.25, "Ethiopia": 0.2},
    "south asia":      {"India": 0.6, "Pakistan": 0.2, "Bangladesh": 0.1, "Nepal": 0.05},
    "southeast asia":  {"Thailand": 0.2, "Vietnam": 0.2, "Indonesia": 0.2, "Philippines": 0.15},
    "east asia":       {"China": 0.5, "Japan": 0.25, "South Korea": 0.15, "Taiwan": 0.05},
    "oceania":         {"Australia": 0.75, "New Zealand": 0.2},
    "russia":          {"Russia": 0.95},
    "japan":           {"Japan": 0.98},
    "south korea":     {"South Korea": 0.98},
    "thailand":        {"Thailand": 0.98},
    "australia":       {"Australia": 0.9, "New Zealand": 0.08},
}


def infer_countries(clues: list[Clue]) -> list[tuple[str, float]]:
    """
    Aggregate country probabilities from a set of visual clues.
    Returns a sorted list of (country, probability) pairs.
    """
    scores: dict[str, float] = {}
    for clue in clues:
        if not clue.narrows_to:
            continue
        region_hint = str(clue.narrows_to).lower()
        for region_key, country_map in _REGION_TO_COUNTRIES.items():
            if region_key in region_hint:
                for country, base_prob in country_map.items():
                    w = base_prob * clue.confidence
                    scores[country] = scores.get(country, 0) + w

    if not scores:
        return []

    # Normalize
    total = sum(scores.values())
    return sorted(
        [(c, round(v/total, 3)) for c, v in scores.items()],
        key=lambda x: -x[1],
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_clues(
    image_path: str,
    prompt: str = "What geographic signals can you identify in this image?",
    backend: Optional[str] = None,
) -> list[Clue]:
    """
    Extract geographic clues from an image.

    Uses the configured vision backend (or overrides with `backend` param).
    Falls back to rule-based analysis if no model is available.

    Parameters
    ----------
    image_path : str
        Path to the image file.
    prompt : str
        Additional instruction for the vision model.
    backend : str, optional
        Override the global backend for this call.

    Returns
    -------
    list[Clue]
    """
    active_backend = backend or _BACKEND

    if active_backend == "none":
        logger.info("No vision backend configured — using rule-based analysis only.")
        return []

    try:
        if active_backend == "claude":
            raw = _call_claude(image_path, prompt)
        elif active_backend == "gpt4v":
            raw = _call_gpt4v(image_path, prompt)
        elif active_backend == "llava":
            raw = _call_llava(image_path, prompt)
        else:
            raise ValueError(f"Unknown backend: {active_backend!r}")

        clues = _parse_clues(raw)
        logger.info(f"Extracted {len(clues)} visual clues via {active_backend}")
        return clues

    except Exception as e:
        logger.error(f"Vision extraction failed ({active_backend}): {e}")
        return []


def analyze(
    image_path: str,
    backend: Optional[str] = None,
) -> dict:
    """
    Full visual analysis: extract clues and infer candidate countries.

    Returns
    -------
    dict with keys: "clues", "candidate_countries"
    """
    clues    = extract_clues(image_path, backend=backend)
    countries = infer_countries(clues)
    return {
        "clues":             clues,
        "candidate_countries": countries,
    }
