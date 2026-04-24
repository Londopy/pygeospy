# Changelog

All notable changes to **geoint** will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Planned
- Web UI (FastAPI + Leaflet)
- geoint.crowd — crowd-sourced Wikidata location signals
- geoint.timeline — multi-image temporal reconstruction
- QGIS plugin
- PyPI release

---

## [0.2.0] — 2026-04-23

### Added

**Phase 3 modules:**
- `geoint.visual` — Visual clue extraction with pluggable vision backends
  (Claude, GPT-4V, LLaVA/Ollama, rule-based fallback)
  - Infrastructure, road signs, vegetation, architecture, vehicle signals
  - Country probability inference from detected clues
- `geoint.chronos` — Temporal analysis
  - Time-of-day estimation from shadow geometry
  - Season detection from vegetation/snow signals
  - Vehicle model era estimation
  - Weather archive lookup via Meteostat API
- `geoint.language` — Linguistic analysis
  - OCR pipeline (Tesseract + EasyOCR fallback)
  - Script detection (18 writing systems)
  - Phone number, postal code, TLD, currency symbol detection
  - Sign text → geocoding pipeline
- `geoint.network` — Network OSINT
  - IP → ASN → datacenter/residential classification
  - WiGLE BSSID geolocation
  - MAC OUI manufacturer lookup
  - Email header IP extraction and geolocation
  - Certificate transparency log queries
- `geoint.satellite` — Satellite imagery
  - Sentinel-2 product search via Copernicus OData API
  - NDVI, EVI, MNDWI, Urban Heat Index (Rust-accelerated)
  - NDVI differencing change detection
  - OpenAerialMap integration
- `geoint.acoustic` — Audio geolocation (experimental)
  - Bird species identification via BirdNET/birdnetlib
  - Siren tone classification (UK/USA/EU/Japan/Russia)
  - Language identification via Whisper (offline)
  - Species range → region mapping
- `geoint.pipeline` — Unified analysis engine
  - `geoint.pipeline.analyze(input)` → `GeoResult`
  - Parallel module execution (ThreadPoolExecutor)
  - Auto-detect input type (image, audio, IP, coords, text)
  - Confidence-weighted candidate aggregation

**Rust core (`_rustcore`):**
- `raster.rs` — NDVI, EVI, MNDWI, UHI, pixel statistics, Otsu binarization,
  median filter, linear stretch, histogram
- `sar.rs` — named grid sectors, expanding square pattern, `poa_rings`
  with configurable vertex count

**Infrastructure:**
- `geoint._cache` — Disk-based API response cache with TTL
- `geoint._types` — Unified `GeoResult`, `Clue`, `CandidateLocation` types
- `geoint.cli` — Full Typer CLI: `analyze`, `coords`, `solar`, `exif`, `sar`, `cache`, `info`
- `geoint.export` — HTML report template, Markdown export, `export_all()`

### Changed
- `geoint.coords.format()` now accepts `"mgrs"` and `"plus"` formats
- `geoint.solar.analyze_shadow()` returns full `SolarResult` with clue objects
- All modules gracefully degrade when optional deps are missing

---

## [0.1.0] — Initial release

### Added

- `geoint.coords` — Coordinate toolkit (Rust core)
  - Haversine distance and bearing
  - Destination point, midpoint, cross-track distance
  - Bounding box generation
  - DD ↔ DMS ↔ UTM conversions
  - Batch haversine for geocoding loops
  - Elevation API (Open-Topo-Data)
  - Timezone inference (timezonefinder)
- `geoint.solar` — Solar analysis (Rust core)
  - Solar elevation and azimuth
  - Shadow azimuth from sun direction
  - Shadow ratio ↔ sun elevation
  - Latitude band sweep from shadow geometry
  - Sunrise/sunset times
  - Season estimation
  - GeoJSON lat-band export
- `geoint.exif` — EXIF metadata forensics (Python)
  - GPS coordinate extraction (exifread + Pillow)
  - Camera fingerprinting
  - Forensic scrub detection
  - Batch directory processing
  - Folium GPS map output
- `geoint.terrain` — DEM analysis (Rust core)
  - Slope and aspect (Zevenbergen & Thorne kernel)
  - Terrain Ruggedness Index (Wilson & Gallant)
  - Line-of-sight viewshed (ray-march)
  - Elevation profile extraction
  - Focal mean smoothing
  - GeoTIFF and CSV export
- `geoint.osm` — OpenStreetMap / Overpass (Python)
  - Feature query by type within radius
  - Building footprint extraction
  - Road density → urban/rural classification
  - Architectural tag analysis
  - Named region boundary download
  - GeoJSON and KML export
- `geoint.geo` — Geocoding (Python)
  - Address → coords via Nominatim
  - Reverse geocoding
  - IP geolocation via ip-api.com
  - Bulk geocoding with rate-limit handling
  - What3Words compatibility layer
- `geoint.sar` — Search and Rescue (Rust core + Python)
  - NASAR-style search grid with sector labels
  - Hasty-search corridor generation
  - POA rings from ISRID profiles
  - Urgency scoring
  - GPX export
- `geoint.export` — Export and visualization (Python)
  - Layered Folium HTML map
  - GeoJSON, KML, GPX, CSV export
  - HTML and Markdown intel reports
- `_rustcore` — Rust extension
  - `coords.rs`, `solar.rs`, `terrain.rs`, `sar.rs`, `raster.rs`
  - PyO3 bindings with pure-Python fallbacks
- `Makefile` — build, test, lint, clean targets
- `pyproject.toml` — maturin + hatch build system
- Full test suite (pytest, ~60 tests, no network required)
