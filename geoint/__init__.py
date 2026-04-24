"""
geoint — Python GEOINT/OSINT library with Rust-accelerated core.

Quick start
-----------
>>> import geoint
>>> # Coordinate math (Rust-backed)
>>> dist = geoint.coords.haversine(51.5, -0.1, 48.85, 2.35)  # London → Paris
>>> # EXIF extraction
>>> result = geoint.exif.extract("photo.jpg")
>>> # Solar analysis
>>> band = geoint.solar.latitude_band_from_shadow(ratio=2.5, azimuth=195)
>>> # Full pipeline
>>> report = geoint.pipeline.analyze("mystery_photo.jpg")

Modules
-------
  geoint.coords    — Coordinate math and projections   (Rust core)
  geoint.solar     — Solar/shadow geolocation          (Rust core)
  geoint.exif      — EXIF metadata forensics           (Python)
  geoint.terrain   — DEM terrain analysis              (Rust core)
  geoint.osm       — OpenStreetMap / Overpass          (Python)
  geoint.geo       — Geocoding and IP lookup           (Python)
  geoint.sar       — Search and rescue grid ops        (Rust core)
  geoint.export    — Maps, reports, GeoJSON/GPX/KML    (Python)
  geoint.visual    — Visual clue extraction (v0.2)     (Python + vision model)
  geoint.chronos   — Temporal analysis      (v0.2)     (Python)
  geoint.language  — Linguistic/OCR analysis (v0.2)    (Python)
  geoint.network   — Network OSINT          (v0.2)     (Python)
  geoint.satellite — Sentinel / aerial imagery (v0.2)  (Rust+Python)
  geoint.acoustic  — Audio geolocation      (v0.2)     (Python)
  geoint.pipeline  — Unified analysis engine (v0.2)    (Python)
"""

__version__ = "0.2.0"
__author__  = "geoint contributors"
__license__ = "MIT"

# ── Lazy module imports ───────────────────────────────────────────────────────
# Imported on first access so optional heavy deps (rasterio, easyocr, …)
# don't block users who only need a subset of the library.

from geoint import coords   # noqa: F401 — always available, Rust-backed
from geoint import solar    # noqa: F401 — always available, Rust-backed

# The rest are imported lazily via __getattr__ to avoid hard import failures
# when optional dependencies (rasterio, overpy, …) are not installed.

_LAZY_MODULES = [
    "exif", "terrain", "osm", "geo", "sar", "export",
    "visual", "chronos", "language", "network", "satellite", "acoustic",
    "pipeline",
]

import importlib as _importlib
import sys as _sys


def __getattr__(name: str):
    if name in _LAZY_MODULES:
        mod = _importlib.import_module(f"geoint.{name}")
        _sys.modules[f"geoint.{name}"] = mod
        globals()[name] = mod
        return mod
    raise AttributeError(f"module 'geoint' has no attribute {name!r}")


def __dir__():
    return sorted(list(globals().keys()) + _LAZY_MODULES)


# ── Rust availability flag ────────────────────────────────────────────────────

from geoint._utils import RUST_AVAILABLE  # noqa: F401

if not RUST_AVAILABLE:
    import warnings
    warnings.warn(
        "geoint: Rust core (_rustcore) not found. "
        "Performance-critical operations will use pure-Python fallbacks. "
        "Run `maturin develop --release` inside the _rustcore/ directory to build.",
        RuntimeWarning,
        stacklevel=2,
    )
