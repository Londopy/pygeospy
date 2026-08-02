"""
pygeospy — Python GEOINT/OSINT library with Rust-accelerated core.

Quick start
-----------
>>> import pygeospy
>>> # Coordinate math (Rust-backed)
>>> dist = pygeospy.coords.haversine(51.5, -0.1, 48.85, 2.35)  # London → Paris
>>> # EXIF extraction
>>> result = pygeospy.exif.extract("photo.jpg")
>>> # Solar analysis
>>> band = pygeospy.solar.latitude_band_from_shadow(ratio=2.5, azimuth=195)
>>> # Full pipeline
>>> report = pygeospy.pipeline.analyze("mystery_photo.jpg")

Modules
-------
  pygeospy.coords    — Coordinate math and projections   (Rust core)
  pygeospy.solar     — Solar/shadow geolocation          (Rust core)
  pygeospy.exif      — EXIF metadata forensics           (Python)
  pygeospy.terrain   — DEM terrain analysis              (Rust core)
  pygeospy.osm       — OpenStreetMap / Overpass          (Python)
  pygeospy.geo       — Geocoding and IP lookup           (Python)
  pygeospy.sar       — Search and rescue grid ops        (Rust core)
  pygeospy.export    — Maps, reports, GeoJSON/GPX/KML    (Python)
  pygeospy.visual    — Visual clue extraction (v0.2)     (Python + vision model)
  pygeospy.chronos   — Temporal analysis      (v0.2)     (Python)
  pygeospy.language  — Linguistic/OCR analysis (v0.2)    (Python)
  pygeospy.network   — Network OSINT          (v0.2)     (Python)
  pygeospy.satellite — Sentinel / aerial imagery (v0.2)  (Rust+Python)
  pygeospy.acoustic  — Audio geolocation      (v0.2)     (Python)
  pygeospy.pipeline  — Unified analysis engine (v0.2)    (Python)
"""

__version__ = "0.2.1"
__author__  = "pygeospy contributors"
__license__ = "MIT"

# ── Lazy module imports ───────────────────────────────────────────────────────
# Imported on first access so optional heavy deps (rasterio, easyocr, …)
# don't block users who only need a subset of the library.

from pygeospy import (
    coords,  # noqa: F401 — always available, Rust-backed
    solar,  # noqa: F401 — always available, Rust-backed
)

# The rest are imported lazily via __getattr__ to avoid hard import failures
# when optional dependencies (rasterio, overpy, …) are not installed.

_LAZY_MODULES = [
    "exif", "terrain", "osm", "geo", "sar", "export",
    "visual", "chronos", "language", "network", "satellite", "acoustic",
    "pipeline",
]

import importlib as _importlib  # noqa: E402
import sys as _sys  # noqa: E402


def __getattr__(name: str):
    if name in _LAZY_MODULES:
        mod = _importlib.import_module(f"pygeospy.{name}")
        _sys.modules[f"pygeospy.{name}"] = mod
        globals()[name] = mod
        return mod
    raise AttributeError(f"module 'pygeospy' has no attribute {name!r}")


def __dir__():
    return sorted(list(globals().keys()) + _LAZY_MODULES)


# ── Rust availability flag ────────────────────────────────────────────────────

from pygeospy._utils import RUST_AVAILABLE  # noqa: F401,E402

if not RUST_AVAILABLE:
    import warnings
    warnings.warn(
        "pygeospy: Rust core (_rustcore) not found. "
        "Performance-critical operations will use pure-Python fallbacks. "
        "Run `maturin develop --release` inside the _rustcore/ directory to build.",
        RuntimeWarning,
        stacklevel=2,
    )
