# Changelog

All notable changes to **pygeospy** will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Planned
- Web UI (FastAPI + Leaflet)
- pygeospy.crowd — crowd-sourced Wikidata location signals
- pygeospy.timeline — multi-image temporal reconstruction
- QGIS plugin
- PyPI release

---

## [0.2.1] — 2026-08-01

### Fixed
- **The Rust core never compiled.** `_rustcore/src/sar.rs` carried 25 trailing
  NUL bytes (introduced in f210396), so cargo rejected the file with
  "unknown start of token: \u{0}" on every platform. Every build since then
  has silently fallen back to pure Python. Bytes stripped; a CI guard
  (`scripts/check_encoding.py`) now fails the build if NUL bytes or invalid
  UTF-8 reappear in any source file.
- **Cross-platform packaging**: release workflow now uploads wheels from the correct
  path and builds an sdist — previously only a Windows wheel reached PyPI, making
  `pip install pygeospy` fail on Linux and macOS.
- **Windows text encoding**: all text file writes (HTML/KML/GeoJSON/Markdown reports,
  CSV, GPX, cache) now use UTF-8 explicitly; report generation no longer crashes with
  `UnicodeEncodeError` on Windows (cp1252 default).
- **HTML report generation** crashed on every platform: CSS braces in the template
  broke `str.format()`; switched to `string.Template`.
- `pygeospy info` crashed with `NameError` (referenced old `geoint` module name).
- `pygeospy.geo.w3w_to_latlon` used `os` before importing it (`NameError`).
- CLI commands now accept negative coordinates (`coords haversine 51.5 -0.1 …`).
- Rust-core detection no longer reports "available" when the `_rustcore/` source
  directory is picked up as an empty namespace package.

### Changed
- Cache directory is now platform-native: `%LOCALAPPDATA%\pygeospy\cache` (Windows),
  `~/Library/Caches/pygeospy` (macOS), `$XDG_CACHE_HOME`/`~/.cache/pygeospy` (Linux);
  `PYGEOSPY_CACHE_DIR` overrides everywhere.
- Aligned Python floor at 3.10 (`abi3-py310`, README badge).
- Renamed all leftover `geoint` references (module docs, Makefile targets,
  User-Agent strings, default output dirs) to `pygeospy`.

### Added
- MIT `LICENSE` file (was referenced but missing).
- CI workflow: pytest matrix on Ubuntu/macOS/Windows x Python 3.10-3.12,
  plus a Rust-core wheel-build job (asserts the compiled extension actually
  loads on each OS) and ruff lint.
- `.gitattributes` normalising line endings across platforms.

### Internal
- Cleaned ~35 unused imports, 4 dead local variables, and a stray `import pyotp`
  in the Plus Code fallback path; `ruff check` is now clean.

## [0.2.0] — 2026-04-23

### Added

**Phase 3 modules:**
- `pygeospy.visual` — Visual clue extraction with pluggable vision backends
  (Claude, GPT-4V, LLaVA/Ollama, rule-based fallback)
  - Infrastructure, road signs, vegetation, architecture, vehicle signals
  - Country probability inference from detected clues
- `pygeospy.chronos` — Temporal analysis
  - Time-of-day estimation from shadow geometry
  - Season detection from vegetation/snow signals
  - Vehicle model era estimation
  - Weather archive lookup via Meteostat API
- `pygeospy.language` — Linguistic analysis
  - OCR pipeline (Tesseract + EasyOCR fallback)
  - Script detection (18 writing systems)
  - Phone number, postal code, TLD, currency symbol detection
  - Sign text → geocoding pipeline
- `pygeospy.network` — Network OSINT
  - IP → ASN → datacenter/residential classification
  - WiGLE BSSID geolocation
  - MAC OUI manufacturer lookup
  - Email header IP extraction and geolocation
  - Certificate transparency log queries
- `pygeospy.satellite` — Satellite imagery
  - Sentinel-2 product search via Copernicus OData API
  - NDVI, EVI, MNDWI, Urban Heat Index (Rust-accelerated)
  - NDVI differencing change detection
  - OpenAerialMap integration
- `pygeospy.acoustic` — Audio geolocation (experimental)
  - Bird species identification via BirdNET/birdnetlib
  - Siren tone classification (UK/USA/EU/Japan/Russia)
  - Language identification via Whisper (offline)
  - Species range → region mapping
- `pygeospy.pipeline` — Unified analysis engine
  - `pygeospy.pipeline.analyze(input)` → `GeoResult`
  - Parallel module execution (ThreadPoolExecutor)
  - Auto-detect input type (image, audio, IP, coords, text)
  - Confidence-weighted candidate aggregation

**Rust core (`_rustcore`):**
- `raster.rs` — NDVI, EVI, MNDWI, UHI, pixel statistics, Otsu binarization,
  median filter, linear stretch, histogram
- `sar.rs` — named grid sectors, expanding square pattern, `poa_rings`
  with configurable vertex count

**Infrastructure:**
- `pygeospy._cache` — Disk-based API response cache with TTL
- `pygeospy._types` — Unified `GeoResult`, `Clue`, `CandidateLocation` types
- `pygeospy.cli` — Full Typer CLI: `analyze`, `coords`, `solar`, `exif`, `sar`, `cache`, `info`
- `pygeospy.export` — HTML report template, Markdown export, `export_all()`

### Changed
- `pygeospy.coords.format()` now accepts `"mgrs"` and `"plus"` formats
- `pygeospy.solar.analyze_shadow()` returns full `SolarResult` with clue objects
- All modules gracefully degrade when optional deps are missing

---

## [0.1.0] — Initial release

### Added

- `pygeospy.coords` — Coordinate toolkit (Rust core)
  - Haversine distance and bearing
  - Destination point, midpoint, cross-track distance
  - Bounding box generation
  - DD ↔ DMS ↔ UTM conversions
  - Batch haversine for geocoding loops
  - Elevation API (Open-Topo-Data)
  - Timezone inference (timezonefinder)
- `pygeospy.solar` — Solar analysis (Rust core)
  - Solar elevation and azimuth
  - Shadow azimuth from sun direction
  - Shadow ratio ↔ sun elevation
  - Latitude band sweep from shadow geometry
  - Sunrise/sunset times
  - Season estimation
  - GeoJSON lat-band export
- `pygeospy.exif` — EXIF metadata forensics (Python)
  - GPS coordinate extraction (exifread + Pillow)
  - Camera fingerprinting
  - Forensic scrub detection
  - Batch directory processing
  - Folium GPS map output
- `pygeospy.terrain` — DEM analysis (Rust core)
  - Slope and aspect (Zevenbergen & Thorne kernel)
  - Terrain Ruggedness Index (Wilson & Gallant)
  - Line-of-sight viewshed (ray-march)
  - Elevation profile extraction
  - Focal mean smoothing
  - GeoTIFF and CSV export
- `pygeospy.osm` — OpenStreetMap / Overpass (Python)
  - Feature query by type within radius
  - Building footprint extraction
  - Road density → urban/rural classification
  - Architectural tag analysis
  - Named region boundary download
  - GeoJSON and KML export
- `pygeospy.geo` — Geocoding (Python)
  - Address → coords via Nominatim
  - Reverse geocoding
  - IP geolocation via ip-api.com
  - Bulk geocoding with rate-limit handling
  - What3Words compatibility layer
- `pygeospy.sar` — Search and Rescue (Rust core + Python)
  - NASAR-style search grid with sector labels
  - Hasty-search corridor generation
  - POA rings from ISRID profiles
  - Urgency scoring
  - GPX export
- `pygeospy.export` — Export and visualization (Python)
  - Layered Folium HTML map
  - GeoJSON, KML, GPX, CSV export
  - HTML and Markdown intel reports
- `_rustcore` — Rust extension
  - `coords.rs`, `solar.rs`, `terrain.rs`, `sar.rs`, `raster.rs`
  - PyO3 bindings with pure-Python fallbacks
- `Makefile` — build, test, lint, clean targets
- `pyproject.toml` — maturin + hatch build system
- Full test suite (pytest, ~60 tests, no network required)
