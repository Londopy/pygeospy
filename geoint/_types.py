"""
geoint._types — Shared data-types and result containers.
All modules return instances of these classes so the pipeline can reason
about confidence and evidence uniformly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ── Coordinate containers ─────────────────────────────────────────────────────

@dataclass
class LatLon:
    """A WGS-84 coordinate pair."""
    lat: float
    lon: float
    accuracy_km: Optional[float] = None   # uncertainty radius

    def __iter__(self):
        return iter((self.lat, self.lon))

    def __repr__(self):
        return f"LatLon({self.lat:.6f}, {self.lon:.6f})"

    def to_dict(self) -> dict:
        return {"lat": self.lat, "lon": self.lon, "accuracy_km": self.accuracy_km}

    def to_geojson_point(self) -> dict:
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [self.lon, self.lat]},
            "properties": {"accuracy_km": self.accuracy_km},
        }


@dataclass
class BoundingBox:
    """Axis-aligned bounding box in WGS-84."""
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    @property
    def center(self) -> LatLon:
        return LatLon(
            (self.min_lat + self.max_lat) / 2,
            (self.min_lon + self.max_lon) / 2,
        )

    def contains(self, lat: float, lon: float) -> bool:
        return (self.min_lat <= lat <= self.max_lat and
                self.min_lon <= lon <= self.max_lon)

    def to_dict(self) -> dict:
        return {
            "min_lat": self.min_lat, "min_lon": self.min_lon,
            "max_lat": self.max_lat, "max_lon": self.max_lon,
        }

    def to_geojson_polygon(self) -> dict:
        coords = [
            [self.min_lon, self.min_lat],
            [self.max_lon, self.min_lat],
            [self.max_lon, self.max_lat],
            [self.min_lon, self.max_lat],
            [self.min_lon, self.min_lat],
        ]
        return {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {},
        }


# ── Evidence / Clue containers ────────────────────────────────────────────────

@dataclass
class Clue:
    """A single geographic clue detected by any module."""
    source: str                  # e.g. "solar", "exif", "visual"
    clue_type: str               # e.g. "sun_azimuth", "gps_coords", "pole_type"
    value: Any                   # raw value
    confidence: float = 1.0      # 0–1
    narrows_to: Optional[Any] = None   # BoundingBox / country list / hemisphere / etc.
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "clue_type": self.clue_type,
            "value": str(self.value),
            "confidence": self.confidence,
            "narrows_to": str(self.narrows_to) if self.narrows_to else None,
            "notes": self.notes,
        }


# ── Candidate location ────────────────────────────────────────────────────────

@dataclass
class CandidateLocation:
    """A candidate geographic location with associated confidence."""
    location: LatLon
    confidence: float             # 0–1
    source_modules: list[str] = field(default_factory=list)
    supporting_clues: list[Clue] = field(default_factory=list)
    country_hint: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "lat": self.location.lat,
            "lon": self.location.lon,
            "confidence": self.confidence,
            "source_modules": self.source_modules,
            "country_hint": self.country_hint,
            "notes": self.notes,
        }


# ── Top-level result ──────────────────────────────────────────────────────────

@dataclass
class GeoResult:
    """
    Unified result returned by geoint.pipeline.analyze().
    Contains all evidence, ranked candidates, and export handles.
    """
    # Input
    input_path: Optional[str] = None
    input_type: str = "unknown"  # "image" | "url" | "coords" | "ip" | "audio" | "text"

    # Evidence
    clues: list[Clue] = field(default_factory=list)

    # Ranked outputs
    candidate_coordinates: list[CandidateLocation] = field(default_factory=list)
    candidate_countries: list[tuple[str, float]] = field(default_factory=list)  # (country, prob)

    # Narrative
    reasoning_chain: list[str] = field(default_factory=list)
    summary: str = ""

    # Export paths (populated by export module)
    map_html_path: Optional[str] = None
    report_path: Optional[str]   = None
    geojson_path: Optional[str]  = None

    @property
    def best_location(self) -> Optional[CandidateLocation]:
        """Highest-confidence candidate, or None."""
        if not self.candidate_coordinates:
            return None
        return max(self.candidate_coordinates, key=lambda c: c.confidence)

    @property
    def top_country(self) -> Optional[str]:
        """Most likely country, or None."""
        if not self.candidate_countries:
            return None
        return max(self.candidate_countries, key=lambda x: x[1])[0]

    def add_clue(self, clue: Clue) -> None:
        self.clues.append(clue)

    def add_reasoning(self, step: str) -> None:
        self.reasoning_chain.append(step)

    def to_dict(self) -> dict:
        return {
            "input_path": self.input_path,
            "input_type": self.input_type,
            "clues": [c.to_dict() for c in self.clues],
            "candidates": [c.to_dict() for c in self.candidate_coordinates],
            "candidate_countries": self.candidate_countries,
            "reasoning_chain": self.reasoning_chain,
            "summary": self.summary,
            "map_html_path": self.map_html_path,
        }


# ── Solar result ──────────────────────────────────────────────────────────────

@dataclass
class SolarResult:
    sun_elevation: Optional[float] = None
    sun_azimuth: Optional[float] = None
    shadow_azimuth: Optional[float] = None
    shadow_length_ratio: Optional[float] = None
    estimated_season: Optional[str] = None
    candidate_lat_bands: list[tuple[float, float]] = field(default_factory=list)
    hemisphere_hint: Optional[str] = None   # "northern" | "southern" | None
    day_of_year_hint: Optional[int] = None
    clues: list[Clue] = field(default_factory=list)


# ── EXIF result ───────────────────────────────────────────────────────────────

@dataclass
class ExifResult:
    has_gps: bool = False
    coordinates: Optional[LatLon] = None
    altitude_m: Optional[float] = None
    timestamp: Optional[str] = None
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    lens: Optional[str] = None
    software: Optional[str] = None
    exif_scrubbed: bool = False
    raw_exif: dict = field(default_factory=dict)


# ── Terrain result ────────────────────────────────────────────────────────────

@dataclass
class TerrainResult:
    slope_grid: Optional[list] = None
    aspect_grid: Optional[list] = None
    tri_grid: Optional[list] = None
    viewshed_grid: Optional[list] = None
    elevation_profile: Optional[list[float]] = None
    dem_source: str = "unknown"
    cell_size_m: float = 30.0
