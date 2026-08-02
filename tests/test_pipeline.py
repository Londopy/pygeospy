"""Tests for pygeospy.pipeline — end-to-end integration."""
import pytest


# ── Input type detection ──────────────────────────────────────────────────────

def test_detect_ip():
    from pygeospy.pipeline import _detect_input_type
    assert _detect_input_type("8.8.8.8") == "ip"
    assert _detect_input_type("192.168.1.1") == "ip"


def test_detect_coords():
    from pygeospy.pipeline import _detect_input_type
    assert _detect_input_type("51.5,-0.1") == "coords"
    assert _detect_input_type("-33.87, 151.21") == "coords"


def test_detect_url():
    from pygeospy.pipeline import _detect_input_type
    assert _detect_input_type("https://example.com/photo.jpg") == "url"
    assert _detect_input_type("http://maps.google.com") == "url"


def test_detect_text():
    from pygeospy.pipeline import _detect_input_type
    assert _detect_input_type("Hello world") == "text"


# ── GeoResult structure ───────────────────────────────────────────────────────

def test_geo_result_defaults():
    from pygeospy._types import GeoResult
    r = GeoResult()
    assert r.candidate_coordinates == []
    assert r.candidate_countries   == []
    assert r.clues                 == []
    assert r.reasoning_chain       == []
    assert r.best_location is None
    assert r.top_country   is None


def test_geo_result_best_location():
    from pygeospy._types import GeoResult, CandidateLocation, LatLon
    r = GeoResult()
    r.candidate_coordinates = [
        CandidateLocation(LatLon(0, 0), 0.5, ["test"]),
        CandidateLocation(LatLon(1, 1), 0.9, ["test"]),
        CandidateLocation(LatLon(2, 2), 0.3, ["test"]),
    ]
    best = r.best_location
    assert best.confidence == 0.9
    assert best.location.lat == 1.0


def test_geo_result_top_country():
    from pygeospy._types import GeoResult
    r = GeoResult(candidate_countries=[("France", 0.3), ("Germany", 0.6), ("Spain", 0.1)])
    assert r.top_country == "Germany"


# ── Text analysis (no network) ────────────────────────────────────────────────

def test_pipeline_text_cyrillic():
    """Pipeline should detect Cyrillic script in text."""
    from pygeospy.pipeline import analyze
    result = analyze("Москва — столица России")
    cyrillic_clues = [c for c in result.clues if c.clue_type == "script" and c.value == "cyrillic"]
    assert len(cyrillic_clues) > 0


def test_pipeline_text_phone_code():
    """Pipeline should detect UK phone code."""
    from pygeospy.pipeline import analyze
    result = analyze("Call us at +44 20 7946 0958")
    phone_clues = [c for c in result.clues if c.clue_type == "phone_code"]
    assert any("+44" in c.value for c in phone_clues)


def test_pipeline_text_tld():
    """Pipeline should detect country TLD."""
    from pygeospy.pipeline import analyze
    result = analyze("Visit www.bbc.co.uk for news")
    tld_clues = [c for c in result.clues if c.clue_type == "domain_tld"]
    assert len(tld_clues) > 0


# ── Coordinate pipeline (no network mock) ─────────────────────────────────────

def test_pipeline_coords_with_mock():
    """Pipeline coordinate input should create a candidate location."""
    from pygeospy.pipeline import analyze
    from unittest.mock import patch

    mock_geo = {"display_name": "Paris, France", "country": "France",
                "country_code": "FR", "city": "Paris", "state": "", "postcode": "",
                "road": "", "suburb": "", "raw": {}}

    with patch("pygeospy.geo.reverse_geocode", return_value=mock_geo):
        result = analyze("48.8566,2.3522")

    assert result.input_type == "coords"
    assert len(result.candidate_coordinates) > 0
    best = result.candidate_coordinates[0]
    assert best.location.lat == pytest.approx(48.8566)
    assert best.location.lon == pytest.approx(2.3522)
    assert best.confidence   == 1.0


# ── Clue type ─────────────────────────────────────────────────────────────────

def test_clue_to_dict():
    from pygeospy._types import Clue
    c = Clue("solar", "sun_elevation", 45.0, 0.85, notes="test")
    d = c.to_dict()
    assert d["source"]     == "solar"
    assert d["clue_type"]  == "sun_elevation"
    assert d["confidence"] == 0.85


# ── Country aggregation ───────────────────────────────────────────────────────

def test_country_normalisation():
    from pygeospy.pipeline import _aggregate_country_probabilities
    from pygeospy._types import GeoResult
    r = GeoResult()
    r.candidate_countries = [("France", 0.3), ("France", 0.4), ("Germany", 0.5)]
    _aggregate_country_probabilities(r)
    country_dict = dict(r.candidate_countries)
    assert "France" in country_dict
    assert "Germany" in country_dict
    # Probabilities should sum to ~1
    assert sum(p for _, p in r.candidate_countries) == pytest.approx(1.0, abs=0.01)
    # France should have higher probability
    assert country_dict["France"] > country_dict["Germany"]


# ── Generate summary ──────────────────────────────────────────────────────────

def test_generate_summary_no_result():
    from pygeospy.pipeline import _generate_summary
    from pygeospy._types import GeoResult
    r = GeoResult()
    summary = _generate_summary(r)
    assert "Insufficient evidence" in summary


def test_generate_summary_with_result():
    from pygeospy.pipeline import _generate_summary
    from pygeospy._types import GeoResult, CandidateLocation, LatLon
    r = GeoResult(input_type="image")
    r.candidate_coordinates = [CandidateLocation(LatLon(48.85, 2.35), 0.9, ["exif"])]
    r.candidate_countries   = [("France", 1.0)]
    summary = _generate_summary(r)
    assert "France" in summary
    assert "48.85" in summary
