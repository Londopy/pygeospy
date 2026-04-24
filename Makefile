# geoint Makefile
# ─────────────────────────────────────────────────────────────────────────────
# Common tasks for development, building, and testing.
# Requires: Rust toolchain, maturin, Python ≥ 3.10

.PHONY: help build dev test lint fmt clean docs install install-all

PYTHON ?= python3
MATURIN ?= maturin
PYTEST  ?= pytest

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Rust core build ───────────────────────────────────────────────────────────

build:  ## Build Rust core in release mode
	cd _rustcore && $(MATURIN) build --release

dev:  ## Build Rust core in dev mode (fast, unoptimised)
	$(MATURIN) develop --manifest-path _rustcore/Cargo.toml

dev-release:  ## Build Rust core in release mode and install in editable mode
	$(MATURIN) develop --release --manifest-path _rustcore/Cargo.toml

# ── Python install ────────────────────────────────────────────────────────────

install:  ## Install geoint with core dependencies (no optional extras)
	$(PYTHON) -m pip install -e .

install-all:  ## Install geoint with ALL optional dependencies
	$(PYTHON) -m pip install -e ".[all]"

install-dev:  ## Install dev dependencies (pytest, ruff, mypy, etc.)
	$(PYTHON) -m pip install -e ".[all]" pytest ruff mypy maturin rich

# ── Tests ─────────────────────────────────────────────────────────────────────

test:  ## Run full test suite
	$(PYTEST) tests/ -v

test-fast:  ## Run tests excluding slow/network tests
	$(PYTEST) tests/ -v -m "not slow and not network"

test-coords:  ## Run only coordinate tests
	$(PYTEST) tests/test_coords.py -v

test-solar:  ## Run only solar tests
	$(PYTEST) tests/test_solar.py -v

test-sar:  ## Run only SAR tests
	$(PYTEST) tests/test_sar.py -v

test-terrain:  ## Run only terrain tests
	$(PYTEST) tests/test_terrain.py -v

test-pipeline:  ## Run only pipeline tests
	$(PYTEST) tests/test_pipeline.py -v

test-cov:  ## Run tests with coverage report
	$(PYTEST) tests/ --cov=geoint --cov-report=html --cov-report=term-missing

# ── Lint / format ─────────────────────────────────────────────────────────────

lint:  ## Run ruff linter
	ruff check geoint/ tests/

fmt:   ## Auto-format with ruff
	ruff format geoint/ tests/

typecheck:  ## Run mypy type checker
	mypy geoint/

# ── Rust checks ───────────────────────────────────────────────────────────────

rust-check:  ## Check Rust code compiles (no linking)
	cd _rustcore && cargo check

rust-test:  ## Run Rust unit tests
	cd _rustcore && cargo test

rust-fmt:   ## Format Rust code
	cd _rustcore && cargo fmt

rust-clippy:  ## Run Rust clippy linter
	cd _rustcore && cargo clippy -- -D warnings

# ── Docs ──────────────────────────────────────────────────────────────────────

docs:  ## Build documentation (requires mkdocs)
	mkdocs build

docs-serve:  ## Serve docs locally
	mkdocs serve

# ── Build & release ───────────────────────────────────────────────────────────

wheel:  ## Build Python wheel (includes compiled Rust)
	$(MATURIN) build --release --manifest-path _rustcore/Cargo.toml

sdist:  ## Build source distribution
	$(PYTHON) -m build --sdist

# ── Demo ──────────────────────────────────────────────────────────────────────

demo-coords:  ## Quick demo: London → Paris distance
	$(PYTHON) -c "import geoint; print(f'London→Paris: {geoint.coords.haversine(51.5,-0.1,48.85,2.35):.1f} km')"

demo-solar:   ## Quick demo: solar position at London
	$(PYTHON) -c "import geoint; print(f'Solar elevation London noon Jun: {geoint.solar.solar_elevation(51.5,-0.1,172,12.0):.1f}°')"

demo-sar:     ## Quick demo: SAR urgency score
	$(PYTHON) -c "import geoint; print(geoint.sar.urgency_score(75, medical_condition=True, last_seen_hours=6))"

# ── Clean ─────────────────────────────────────────────────────────────────────

clean:  ## Remove build artefacts
	rm -rf dist/ build/ target/ *.egg-info htmlcov/ .coverage
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "_rustcore*.so" -delete
	find . -name "_rustcore*.pyd" -delete

clean-cache:  ## Clear geoint API cache (~/.cache/geoint/)
	$(PYTHON) -c "from geoint.cli import app; import typer; app(standalone_mode=False)" cache clear || \
	rm -rf ~/.cache/geoint/
