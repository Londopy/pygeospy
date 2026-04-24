"""
pygeospy.language — Linguistic analysis: OCR, script detection, sign text geocoding.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from pygeospy._types import Clue
from pygeospy._cache import cached

logger = logging.getLogger("pygeospy.language")


# ── Script detection ──────────────────────────────────────────────────────────

SCRIPT_REGIONS = {
    "cyrillic":    (r"[\u0400-\u04FF]",  ["Russia", "Ukraine", "Belarus", "Bulgaria", "Serbia", "Kazakhstan"]),
    "arabic":      (r"[\u0600-\u06FF]",  ["Saudi Arabia", "UAE", "Egypt", "Iraq", "Iran", "Morocco", "Algeria"]),
    "devanagari":  (r"[\u0900-\u097F]",  ["India", "Nepal"]),
    "hangul":      (r"[\uAC00-\uD7AF\u1100-\u11FF]", ["South Korea"]),
    "hiragana":    (r"[\u3040-\u309F]",  ["Japan"]),
    "katakana":    (r"[\u30A0-\u30FF]",  ["Japan"]),
    "thai":        (r"[\u0E00-\u0E7F]",  ["Thailand"]),
    "georgian":    (r"[\u10A0-\u10FF]",  ["Georgia"]),
    "hebrew":      (r"[\u05D0-\u05EA]",  ["Israel"]),
    "greek":       (r"[\u0370-\u03FF]",  ["Greece", "Cyprus"]),
    "chinese":     (r"[\u4E00-\u9FFF]",  ["China", "Taiwan", "Singapore", "Hong Kong"]),
    "khmer":       (r"[\u1780-\u17FF]",  ["Cambodia"]),
    "myanmar":     (r"[\u1000-\u109F]",  ["Myanmar"]),
    "ethiopic":    (r"[\u1200-\u137F]",  ["Ethiopia", "Eritrea"]),
    "armenian":    (r"[\u0530-\u058F]",  ["Armenia"]),
    "sinhala":     (r"[\u0D80-\u0DFF]",  ["Sri Lanka"]),
    "tamil":       (r"[\u0B80-\u0BFF]",  ["India (Tamil Nadu)", "Sri Lanka"]),
    "telugu":      (r"[\u0C00-\u0C7F]",  ["India (Andhra Pradesh)"]),
    "bengali":     (r"[\u0980-\u09FF]",  ["Bangladesh", "India (West Bengal)"]),
}

# Latin diacritic patterns → likely regions
LATIN_DIACRITICS = {
    r"[ąćęłńóśźż]":  ["Poland"],
    r"[čšžđ]":       ["Croatia", "Serbia", "Slovenia", "Bosnia"],
    r"[ăîâșț]":      ["Romania"],
    r"[áéíóúñü¿¡]":  ["Spain", "Mexico", "Latin America"],
    r"[àâæçèêëîïôùûœ]": ["France", "Belgium", "Switzerland"],
    r"[äöüß]":       ["Germany", "Austria", "Switzerland"],
    r"[àèìòùé]":     ["Italy"],
    r"[ãõ]":         ["Portugal", "Brazil"],
    r"[æøå]":        ["Denmark", "Norway"],
    r"[ÅÄÖ]":        ["Sweden", "Finland"],
    r"[ğışçö]":      ["Turkey"],
}


def detect_script(text: str) -> list[dict]:
    """
    Detect writing scripts present in text and return region hints.
    Returns list of {"script": str, "regions": list[str], "confidence": float}.
    """
    results = []
    for script, (pattern, regions) in SCRIPT_REGIONS.items():
        if re.search(pattern, text):
            results.append({
                "script": script,
                "regions": regions,
                "confidence": 0.9,
            })

    # Latin: check diacritics if no other script found
    if not results or any(r["script"] == "latin" for r in results):
        for pattern, regions in LATIN_DIACRITICS.items():
            if re.search(pattern, text, re.IGNORECASE):
                results.append({
                    "script": "latin",
                    "regions": regions,
                    "confidence": 0.7,
                })

    return results


# ── OCR ────────────────────────────────────────────────────────────────────────

def ocr_image(image_path: str, engines: tuple = ("tesseract", "easyocr")) -> str:
    """
    Extract text from an image using available OCR engines.
    Tries tesseract first, falls back to EasyOCR.
    Returns extracted text as a string.
    """
    for engine in engines:
        try:
            if engine == "tesseract":
                import pytesseract
                from PIL import Image
                img = Image.open(image_path)
                return pytesseract.image_to_string(img)

            elif engine == "easyocr":
                import easyocr
                reader = easyocr.Reader(["en", "ru", "ar", "zh-cn", "ja", "ko", "th"])
                results = reader.readtext(image_path)
                return " ".join(r[1] for r in results)

        except ImportError:
            continue
        except Exception as e:
            logger.warning(f"OCR engine {engine} failed: {e}")
            continue

    logger.warning("No OCR engine available. Install pytesseract or easyocr.")
    return ""


# ── Text analysis ─────────────────────────────────────────────────────────────

# Phone number country codes
_PHONE_CODES = {
    "+1": ["United States", "Canada"],
    "+7": ["Russia", "Kazakhstan"],
    "+44": ["United Kingdom"],
    "+49": ["Germany"],
    "+33": ["France"],
    "+34": ["Spain"],
    "+39": ["Italy"],
    "+61": ["Australia"],
    "+62": ["Indonesia"],
    "+63": ["Philippines"],
    "+64": ["New Zealand"],
    "+65": ["Singapore"],
    "+66": ["Thailand"],
    "+81": ["Japan"],
    "+82": ["South Korea"],
    "+86": ["China"],
    "+90": ["Turkey"],
    "+91": ["India"],
    "+92": ["Pakistan"],
    "+966": ["Saudi Arabia"],
    "+971": ["UAE"],
    "+972": ["Israel"],
    "+55": ["Brazil"],
    "+52": ["Mexico"],
    "+27": ["South Africa"],
    "+234": ["Nigeria"],
    "+254": ["Kenya"],
    "+20": ["Egypt"],
    "+212": ["Morocco"],
}

# Postal code patterns by country
_POSTAL_PATTERNS = {
    r"^\d{5}$":           ["United States", "Germany", "France", "Spain"],
    r"^\d{5}-\d{4}$":     ["United States (ZIP+4)"],
    r"^[A-Z]{1,2}\d{1,2}[A-Z]?\s?\d[A-Z]{2}$": ["United Kingdom"],
    r"^\d{4}$":           ["Australia", "New Zealand", "Austria", "Denmark"],
    r"^\d{6}$":           ["Russia", "India", "China"],
    r"^\d{3}-\d{4}$":     ["Japan"],
    r"^[A-Z]\d[A-Z]\s?\d[A-Z]\d$": ["Canada"],
}

# Domain TLD → country
_TLD_COUNTRIES = {
    ".ru": "Russia", ".de": "Germany", ".fr": "France", ".uk": "United Kingdom",
    ".au": "Australia", ".ca": "Canada", ".jp": "Japan", ".kr": "South Korea",
    ".cn": "China", ".br": "Brazil", ".mx": "Mexico", ".in": "India",
    ".za": "South Africa", ".ng": "Nigeria", ".eg": "Egypt", ".ar": "Argentina",
    ".cl": "Chile", ".co": "Colombia", ".ve": "Venezuela", ".pe": "Peru",
    ".pl": "Poland", ".nl": "Netherlands", ".be": "Belgium", ".ch": "Switzerland",
    ".at": "Austria", ".se": "Sweden", ".no": "Norway", ".dk": "Denmark",
    ".fi": "Finland", ".es": "Spain", ".pt": "Portugal", ".it": "Italy",
    ".gr": "Greece", ".tr": "Turkey", ".il": "Israel", ".ir": "Iran",
    ".sa": "Saudi Arabia", ".ae": "UAE", ".id": "Indonesia", ".th": "Thailand",
    ".vn": "Vietnam", ".ph": "Philippines", ".my": "Malaysia", ".sg": "Singapore",
    ".nz": "New Zealand", ".com.au": "Australia", ".co.uk": "United Kingdom",
}


def analyze_text(text: str) -> dict:
    """
    Extract geographic signals from text (e.g. OCR output from signs).

    Returns
    -------
    dict with: scripts, phone_codes, postal_matches, tld_matches, regions
    """
    results: dict = {"scripts": [], "phone_codes": [], "postal_matches": [],
                     "tld_matches": [], "clues": []}

    # Script detection
    scripts = detect_script(text)
    results["scripts"] = scripts
    for s in scripts:
        results["clues"].append(Clue(
            source="language",
            clue_type="script",
            value=s["script"],
            confidence=s["confidence"],
            narrows_to=", ".join(s["regions"]),
        ))

    # Phone numbers
    for code, countries in _PHONE_CODES.items():
        if code in text:
            results["phone_codes"].append({"code": code, "countries": countries})
            results["clues"].append(Clue(
                source="language", clue_type="phone_code", value=code,
                confidence=0.85, narrows_to=", ".join(countries),
            ))

    # Postal codes
    for pattern, countries in _POSTAL_PATTERNS.items():
        m = re.search(pattern, text)
        if m:
            results["postal_matches"].append({"match": m.group(), "countries": countries})
            results["clues"].append(Clue(
                source="language", clue_type="postal_code", value=m.group(),
                confidence=0.6, narrows_to=", ".join(countries),
            ))

    # Domain TLDs
    for tld, country in _TLD_COUNTRIES.items():
        if tld in text.lower():
            results["tld_matches"].append({"tld": tld, "country": country})
            results["clues"].append(Clue(
                source="language", clue_type="domain_tld", value=tld,
                confidence=0.75, narrows_to=country,
            ))

    # Currency symbols
    currencies = {
        "$": ["United States", "Canada", "Australia", "New Zealand"],
        "€": ["Eurozone"],
        "£": ["United Kingdom"],
        "¥": ["Japan", "China"],
        "₩": ["South Korea"],
        "₹": ["India"],
        "₽": ["Russia"],
        "₺": ["Turkey"],
        "﷼": ["Saudi Arabia", "Iran"],
    }
    for symbol, countries in currencies.items():
        if symbol in text:
            results["clues"].append(Clue(
                source="language", clue_type="currency", value=symbol,
                confidence=0.65, narrows_to=", ".join(countries),
            ))

    return results


# ── Sign text → place geocoding ───────────────────────────────────────────────

def extract_place_names(text: str) -> list[str]:
    """
    Extract potential place names from sign text using simple heuristics.
    (Proper NLP would use spacy/transformers; this is a lightweight fallback.)
    """
    # Capitalised words not at sentence start, not common English words
    common = {"the", "and", "or", "in", "at", "on", "to", "for", "of", "a", "an",
              "is", "are", "was", "were", "km", "m", "street", "road", "ave"}
    tokens = re.findall(r'\b[A-Z][a-z]+\b', text)
    return [t for t in tokens if t.lower() not in common]


def ocr_and_geocode(image_path: str) -> list[dict]:
    """
    OCR an image, extract place names, and geocode them.
    Returns a list of {"text": str, "lat": float, "lon": float} dicts.
    """
    from pygeospy.geo import geocode

    text   = ocr_image(image_path)
    places = extract_place_names(text)
    results = []
    for place in places:
        loc = geocode(place)
        if loc:
            results.append({"text": place, "lat": loc.lat, "lon": loc.lon})
    return results


# ── Full analysis ──────────────────────────────────────────────────────────────

def analyze(image_path: str) -> dict:
    """
    Full linguistic analysis of an image:
    1. OCR to extract text
    2. Script and regional signal analysis
    3. Place name geocoding

    Returns
    -------
    dict with: text, clues, geocoded_places
    """
    text    = ocr_image(image_path)
    signals = analyze_text(text)
    places  = []

    if text.strip():
        place_names = extract_place_names(text)
        from pygeospy.geo import geocode
        for name in place_names[:5]:  # limit geocode calls
            loc = geocode(name)
            if loc:
                places.append({"name": name, "lat": loc.lat, "lon": loc.lon})

    return {
        "text":           text,
        "clues":          signals.get("clues", []),
        "scripts":        signals.get("scripts", []),
        "geocoded_places": places,
    }
