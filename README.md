# pygeospy 🌍

> **Python GEOINT/OSINT library with a Rust-accelerated core.**
> Given any image, coordinates, IP, or set of clues — produce a location.

[![PyPI](https://img.shields.io/pypi/v/pygeospy)](https://pypi.org/project/pygeospy/)
[![CI](https://github.com/Londopy/pygeospy/actions/workflows/ci.yml/badge.svg)](https://github.com/Londopy/pygeospy/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![Platforms](https://img.shields.io/badge/platforms-linux%20%7C%20macos%20%7C%20windows-lightgrey)](https://pypi.org/project/pygeospy/#files)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Rust](https://img.shields.io/badge/rust-core-orange)](https://rustlang.org)

---

## Install

```bash
pip install pygeospy
```

Prebuilt wheels are published for **Linux (x86-64), macOS (Apple Silicon), and
Windows (x86-64)** on CPython 3.10+. On those platforms the Rust core is included
and no toolchain is needed. Anywhere else, pip builds from the source
distribution, which requires a [Rust toolchain](https://rustup.rs); if the build
is skipped or fails, the library still imports and runs on its pure-Python
fallbacks (see [Rust core](#building-the-rust-core)).

Optional heavy dependencies (vision, OCR, audio, etc.) live behind extras:

```bash
pip install "pygeospy[all]"         # everything
pip install "pygeospy[coords,exif]" # pick modules
```

Verify the install — and whether the Rust core is active:

```bash
pygeospy info
# pygeospy v0.2.1
# Rust core (_rustcore): ✓ available
```

> Run this from **outside** a checkout of this repository. From the repo root the
> local `pygeospy/` source directory shadows the installed package, and you will
> see the pure-Python fallback instead of the wheel you just installed.

---

## What makes pygeospy different?

| Feature | pygeospy | Other OSINT tools |
|---------|----------|-------------------|
| **Rust core** | ✓ 10–100× faster batch math | Pure Python only |
| **SAR module** | ✓ NASAR grids + ISRID profiles | Not available |
| **Full pipeline** | ✓ `analyze(anything)` → coordinates | Module-only APIs |
| **Acoustic analysis** | ✓ BirdNET + siren classification | Not available |
| **Offline-first** | ✓ LLaVA/Ollama, zero API keys needed | Cloud-dependent |

---

## Quick Start

```python
import pygeospy

# Haversine distance (Rust-accelerated)
dist = pygeospy.coords.haversine(51.5, -0.1, 48.85, 2.35)
print(f"London → Paris: {dist:.1f} km")

# Shadow → latitude band
result = pygeospy.solar.latitude_band_from_shadow(
    shadow_ratio=2.5,       # shadow is 2.5× taller than object
    shadow_azimuth_deg=195, # shadow points south-southwest
)
print(f"Candidate latitude bands: {result.candidate_lat_bands}")
print(f"Season: {result.estimated_season}")

# EXIF extraction
exif = pygeospy.exif.extract("photo.jpg")
if exif.has_gps:
    print(f"GPS: {exif.coordinates}")

# Full pipeline analysis
result = pygeospy.pipeline.analyze(
    "mystery_photo.jpg",
    shadow_ratio=2.5,
    shadow_azimuth_deg=195,
    vision_backend="llava",  # offline, no API key needed
    export=True,             # saves HTML report, GeoJSON, KML, GPX
)
print(result.summary)
```

---

## Modules

### v0.1 — Foundation

| Module | Description | Backend |
|--------|-------------|---------|
| `pygeospy.coords` | Haversine, bearing, UTM, MGRS, bounding boxes, elevation API | Rust + Python |
| `pygeospy.solar` | Shadow → sun angle → latitude bands, sunrise/sunset | Rust + Python |
| `pygeospy.exif` | GPS, camera fingerprinting, forensic scrub detection, batch | Python |
| `pygeospy.terrain` | Slope, aspect, TRI, viewshed, elevation profile | Rust + Python |
| `pygeospy.osm` | Overpass queries, building footprints, road density | Python |
| `pygeospy.geo` | Nominatim geocoding, reverse geo, IP geolocation | Python |
| `pygeospy.sar` | NASAR grid, corridors, POA zones, urgency scoring | Rust + Python |
| `pygeospy.export` | Folium maps, HTML reports, GeoJSON/KML/GPX | Python |

### v0.2 — Visual Intelligence

| Module | Description | Backend |
|--------|-------------|---------|
| `pygeospy.visual` | Infrastructure/sign/vegetation/vehicle clues, Claude/GPT-4V/LLaVA | Python |
| `pygeospy.chronos` | Shadow → time of day, vegetation → season, weather archives | Python |
| `pygeospy.language` | OCR, script detection (18 systems), sign geocoding | Python |
| `pygeospy.network` | IP/ASN, WiGLE BSSID, MAC OUI, email headers, crt.sh | Python |
| `pygeospy.satellite` | Sentinel-2 search, NDVI/EVI/MNDWI, change detection | Rust + Python |
| `pygeospy.acoustic` | BirdNET species → region, siren tones, Whisper language | Python |
| `pygeospy.pipeline` | Unified `analyze()` engine, parallel execution | Python |

---

## CLI

```bash
# Full analysis
pygeospy analyze mystery_photo.jpg --shadow-ratio 2.5 --shadow-azimuth 195 --export

# Solar position
pygeospy solar position 51.5 -0.1 172 14.0

# Shadow → latitude bands
pygeospy solar from-shadow 2.5 195 --doy 172

# EXIF extraction
pygeospy exif extract photo.jpg

# Coordinate conversion
pygeospy coords convert 48.8566 2.3522 --fmt all

# Haversine
pygeospy coords haversine 51.5 -0.1 48.85 2.35

# SAR grid
pygeospy sar grid --lat 47.6 --lon -122.3 --radius 3.0 --cell 0.5 --out grid.geojson

# SAR urgency
pygeospy sar urgency --age 8 --medical --hours 6 --night

# IP analysis
pygeospy analyze --ip 8.8.8.8

# Cache management
pygeospy cache stats
pygeospy cache clear
```

---

## Architecture

```
pygeospy/
├── _rustcore/               # Rust crate (PyO3, abi3)
│   └── src/
│       ├── lib.rs           # Module entry point
│       ├── coords.rs        # Haversine, bearing, UTM, bbox
│       ├── solar.rs         # Solar elevation/azimuth, shadow geometry
│       ├── terrain.rs       # Slope, aspect, TRI, viewshed
│       ├── sar.rs           # Grid generation, POA rings, urgency
│       └── raster.rs        # NDVI, EVI, pixel statistics, Otsu
├── pygeospy/                # Python package
│   ├── __init__.py
│   ├── _types.py            # GeoResult, Clue, LatLon, BoundingBox
│   ├── _utils.py            # Shared utilities, rate limiter
│   ├── _cache.py            # Disk cache with TTL
│   ├── coords.py            # Rust wrapper + elevation/timezone APIs
│   ├── solar.py             # Rust wrapper + GeoJSON export
│   ├── exif.py              # EXIF extraction and forensics
│   ├── terrain.py           # Rust wrapper + DEM download
│   ├── osm.py               # Overpass API queries
│   ├── geo.py               # Nominatim + IP lookup
│   ├── sar.py               # Rust wrapper + GPX export
│   ├── export.py            # Folium maps, HTML reports
│   ├── visual.py            # Vision model integration
│   ├── chronos.py           # Temporal analysis
│   ├── language.py          # OCR + linguistic analysis
│   ├── network.py           # IP/network OSINT
│   ├── satellite.py         # Sentinel-2 + spectral indices
│   ├── acoustic.py          # Audio geographic signals
│   ├── pipeline.py          # Unified analysis engine
│   └── cli.py               # Typer CLI
├── tests/
│   ├── test_coords.py
│   ├── test_solar.py
│   ├── test_sar.py
│   ├── test_terrain.py
│   └── test_pipeline.py
├── scripts/
│   ├── check_encoding.py    # CI guard: no NUL bytes / valid UTF-8
│   └── release.py           # bump changelog + versions together
├── .github/workflows/
│   ├── ci.yml               # tests (3 OS x 3 Python), Rust build, lint, changelog
│   └── release.yml          # wheels + sdist -> PyPI (OIDC) -> GitHub Release
├── pyproject.toml
├── CHANGELOG.md             # Keep a Changelog, validated by patchnotes
├── Makefile
└── README.md
```

The compiled extension is installed as `pygeospy._rustcore` (inside the package),
not as a top-level module — so the `_rustcore/` crate directory in the repo root
cannot shadow it.

---

## Example: Brick-Wall-to-Coordinates Pipeline

The classic GEOINT workflow, automated:

```python
import pygeospy

# Step 1: Check EXIF
exif = pygeospy.exif.extract("brick_wall.jpg")
# → No GPS found, EXIF timestamp: 2024-06-15 14:23:00

# Step 2: Solar analysis from shadow
solar = pygeospy.solar.analyze_shadow(
    shadow_ratio=2.1,        # measured from image
    shadow_azimuth_deg=200,  # estimated from image
    timestamp_utc="2024-06-15T14:23:00Z",
)
# → Candidate bands: 35°N–55°N (northern summer afternoon)

# Step 3: Visual clues (offline with LLaVA)
pygeospy.visual.set_backend("llava")
clues = pygeospy.visual.extract_clues("brick_wall.jpg")
# → brick bond: English bond → Northern Europe / UK
# → mortar: white repointing → post-1950 UK
# → stone sill: grey limestone → Northern England / Scotland

# Step 4: OSM region narrowing
from pygeospy._types import BoundingBox
bb = BoundingBox(50, -5, 58, 2)  # England
arch = pygeospy.osm.architectural_tags(53.8, -1.5, radius_m=500)

# Step 5: Full pipeline
result = pygeospy.pipeline.analyze(
    "brick_wall.jpg",
    shadow_ratio=2.1,
    shadow_azimuth_deg=200,
    vision_backend="llava",
    export=True,
)
print(result.summary)
print(result.candidate_countries[:3])
```

---

## Building the Rust Core

The Rust core builds to a single abi3 extension — `pygeospy/_rustcore.*.so` on
Linux/macOS, `pygeospy/_rustcore.*.pyd` on Windows — that works across Python
3.10+ without recompiling per version.

If the extension is missing, **every module falls back to pure Python
automatically** (with a `RuntimeWarning` at import). Results are identical; only
the batch-heavy paths are slower. Nothing is unavailable without Rust.

```bash
# Prerequisites: a Rust toolchain (https://rustup.rs) and maturin
pip install maturin

# Development build — installs into the active virtualenv.
# NOTE: maturin develop requires an ACTIVATED virtualenv; it will not install
# into a bare system Python.
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
maturin develop --release

# Or build a wheel and install it
maturin build --release -o dist
pip install dist/*.whl
```

Check which backend is live:

```python
from pygeospy._utils import RUST_AVAILABLE
print(RUST_AVAILABLE)   # True once the extension is built and importable
```

---

## Vision Model Backends

```python
import pygeospy.visual as v

# Claude (best accuracy, requires API key)
v.set_backend("claude", api_key="sk-ant-...")

# GPT-4V (requires OpenAI API key)
v.set_backend("gpt4v", api_key="sk-...")

# LLaVA via Ollama — FULLY OFFLINE, no API key needed
# Install: https://ollama.ai  then: ollama pull llava:13b
v.set_backend("llava", base_url="http://localhost:11434", model="llava:13b")

# Rule-based only (no model) — this is the DEFAULT
v.set_backend("none")
```

**What the backend actually determines.** Visual clue extraction (brick bond,
signage, vegetation, vehicles) is performed by the vision model, not by pygeospy.
With `"none"` — the default — `visual.extract_clues()` returns little or nothing,
and pipeline runs on an image with no EXIF GPS will find few clues. The
brick-wall example below is the plumbing working end to end with a model
attached; the inference quality is the model's, and the clue-to-country mapping
is a coarse keyword table, not a trained geolocator. Treat candidate countries as
a ranked hypothesis to investigate, not an answer.

---

## Optional API Keys

| Service | Module | Required? | Notes |
|---------|--------|-----------|-------|
| Anthropic Claude | `visual` | Optional | Best visual analysis |
| OpenAI GPT-4V | `visual` | Optional | Alternative |
| ip-api.com | `geo`, `network` | Optional | Free tier: 45 req/min |
| WiGLE | `network` | Optional | Wi-Fi BSSID lookup |
| What3Words | `geo` | Optional | W3W address conversion |
| Meteostat | `chronos` | Optional | Historical weather |
| Open-Topo-Data | `coords`, `terrain` | Free / no key | Elevation data |

All core features work without any API keys.

---

## Testing

```bash
pip install pytest
PYTHONPATH=. pytest tests/ -v
```

71 tests, no network required. They exercise the pure-Python paths by default;
CI additionally runs the whole suite against a built Rust core on Linux, macOS,
and Windows.

### Other checks CI runs

```bash
pip install ruff patchnotes

ruff check pygeospy/ tests/       # lint
python scripts/check_encoding.py  # no NUL bytes / valid UTF-8 in sources
patchnotes CHANGELOG.md validate --strict
```

`scripts/check_encoding.py` exists because a stray run of NUL bytes appended to
`_rustcore/src/sar.rs` once made cargo reject the file outright, silently
disabling the Rust core for months while the pure-Python fallback covered for it.

---

## Roadmap

- Web UI (FastAPI + Leaflet)
- `pygeospy.crowd` — crowd-sourced Wikidata location signals
- `pygeospy.timeline` — multi-image temporal reconstruction
- QGIS plugin
- Wheels for Linux aarch64 and macOS x86-64

---

## Contributing

Changes are tracked in [`CHANGELOG.md`](CHANGELOG.md), which follows
[Keep a Changelog](https://keepachangelog.com) and is validated in CI with
[patchnotes](https://github.com/Londopy/patchnotes). Add your entry under
`## [Unreleased]` using one of the standard sections (`Added`, `Changed`,
`Deprecated`, `Removed`, `Fixed`, `Security`) — a non-standard heading or a
non-ISO date fails the build with an annotation on the offending line.

On release, `python scripts/release.py <version>` moves the `[Unreleased]` block
into a dated release and syncs the version across `pyproject.toml` and
`pygeospy/__init__.py` (CI fails if those drift). The tag's changelog entry then
becomes the GitHub Release body automatically.

---

## License

MIT © pygeospy contributors
