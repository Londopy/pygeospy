"""
pygeospy.terrain — DEM-based terrain analysis.

Rust core handles grid math (slope, TRI, viewshed).
Python layer manages DEM download, rasterio I/O, and export.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pygeospy._utils import rustcore, retry
from pygeospy._cache import cached
from pygeospy._types import TerrainResult, BoundingBox

logger = logging.getLogger("pygeospy.terrain")
_T = rustcore("terrain")


# ── DEM download ──────────────────────────────────────────────────────────────

@cached("dem", ttl=30 * 86400)
@retry(times=3, delay=2.0)
def download_dem(
    bbox: BoundingBox,
    dataset: str = "srtm30m",
    output_dir: str = ".",
) -> Path:
    """
    Download a DEM tile for a bounding box from Open-Topo-Data.
    Saves to output_dir and returns the file path.

    Supported datasets: srtm30m, srtm90m, aster30m, eudem25m, ned10m.
    """
    import httpx
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fname = output_dir / f"dem_{dataset}_{bbox.min_lat:.3f}_{bbox.min_lon:.3f}.tif"
    if fname.exists():
        return fname

    # Open-Topo-Data point array covering the bbox
    lats = [bbox.min_lat + i*(bbox.max_lat - bbox.min_lat)/9 for i in range(10)]
    lons = [bbox.min_lon + j*(bbox.max_lon - bbox.min_lon)/9 for j in range(10)]
    points = [f"{la:.6f},{lo:.6f}" for la in lats for lo in lons]
    locs   = "|".join(points)

    url  = f"https://api.opentopodata.org/v1/{dataset}?locations={locs}"
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # Save as a simple CSV (rasterio-compatible GeoTIFF would need gdal)
    rows = data.get("results", [])
    csv_path = fname.with_suffix(".csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("lat,lon,elevation\n")
        for r in rows:
            la  = r["location"]["lat"]
            lo  = r["location"]["lng"]
            el  = r.get("elevation", 0) or 0
            f.write(f"{la},{lo},{el}\n")

    logger.info(f"DEM CSV saved → {csv_path}")
    return csv_path


def load_dem_csv(csv_path: str | Path) -> tuple[list[list[float]], float]:
    """
    Load a simple lat/lon/elevation CSV into a 2D grid.
    Returns (dem_grid, cell_size_degrees).
    """
    import csv
    from math import sqrt

    rows = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((float(row["lat"]), float(row["lon"]), float(row["elevation"])))

    # Infer grid size
    n = int(sqrt(len(rows)))
    grid = []
    for i in range(n):
        grid.append([rows[i*n + j][2] for j in range(n)])

    lats = sorted(set(r[0] for r in rows))
    cell_size = (lats[-1] - lats[0]) / (len(lats) - 1) if len(lats) > 1 else 0.01
    # Convert degrees to approximate metres (1 deg lat ≈ 111,320 m)
    cell_size_m = cell_size * 111_320

    return grid, cell_size_m


def load_dem_rasterio(path: str | Path) -> tuple[list[list[float]], float]:
    """
    Load a GeoTIFF DEM using rasterio.
    Returns (dem_grid as list-of-lists, cell_size_m).
    """
    try:
        import rasterio
    except ImportError:
        raise ImportError("rasterio is required: pip install rasterio")

    with rasterio.open(path) as src:
        data   = src.read(1).tolist()  # first band
        transform = src.transform
        cell_size_m = abs(transform[0]) * 111_320  # rough degrees→m
    return data, cell_size_m


# ── Analysis functions ────────────────────────────────────────────────────────

def slope_aspect(dem: list[list[float]], cell_size_m: float = 30.0) -> dict:
    """
    Compute slope (degrees) and aspect (degrees, 0=N CW) for a DEM grid.

    Returns {"slope": [[...]], "aspect": [[...]]}
    """
    if _T:
        slope, aspect = _T.slope_aspect(dem, cell_size_m)
        return {"slope": slope, "aspect": aspect}
    # Pure-Python 3x3 kernel fallback
    return _py_slope_aspect(dem, cell_size_m)


def terrain_ruggedness_index(dem: list[list[float]]) -> list[list[float]]:
    """
    Terrain Ruggedness Index (Wilson & Gallant 2000).
    Higher values = more rugged terrain.
    """
    if _T:
        return _T.terrain_ruggedness_index(dem)
    return _py_tri(dem)


def viewshed(
    dem: list[list[float]],
    observer_row: int,
    observer_col: int,
    observer_height_m: float = 1.8,
    cell_size_m: float = 30.0,
    max_range_cells: Optional[int] = None,
) -> list[list[bool]]:
    """
    Compute viewshed: which cells are visible from the observer point?
    Returns a boolean grid (True = visible).
    """
    if _T:
        return _T.viewshed(dem, observer_row, observer_col,
                           observer_height_m, cell_size_m, max_range_cells)
    return _py_viewshed(dem, observer_row, observer_col, observer_height_m)


def elevation_profile(dem: list[list[float]], points: list[tuple[int, int]]) -> list[float]:
    """Extract elevation values along a sequence of (row, col) grid indices."""
    if _T:
        return _T.elevation_profile(dem, points)
    return [dem[r][c] for r, c in points if 0 <= r < len(dem) and 0 <= c < len(dem[0])]


def focal_mean(dem: list[list[float]], radius: int = 2) -> list[list[float]]:
    """Smooth a DEM with a focal mean filter (good pre-processing step)."""
    if _T:
        return _T.focal_mean(dem, radius)
    return _py_focal_mean(dem, radius)


def analyze(
    dem: list[list[float]],
    cell_size_m: float = 30.0,
    include_tri: bool = True,
    include_viewshed: bool = False,
    observer_row: int = 0,
    observer_col: int = 0,
) -> TerrainResult:
    """
    Run a full terrain analysis on a DEM grid.

    Returns a TerrainResult with slope, aspect, and optionally TRI + viewshed.
    """
    sa = slope_aspect(dem, cell_size_m)
    tri_grid = terrain_ruggedness_index(dem) if include_tri else None
    vs_grid  = viewshed(dem, observer_row, observer_col, cell_size_m=cell_size_m) if include_viewshed else None

    return TerrainResult(
        slope_grid=sa["slope"],
        aspect_grid=sa["aspect"],
        tri_grid=tri_grid,
        viewshed_grid=vs_grid,
        cell_size_m=cell_size_m,
    )


# ── Export ────────────────────────────────────────────────────────────────────

def export_geotiff(
    grid: list[list[float]],
    output_path: str,
    bbox: BoundingBox,
    crs: str = "EPSG:4326",
) -> str:
    """
    Export a 2D grid as a GeoTIFF.  Requires rasterio + numpy.
    """
    try:
        import numpy as np
        import rasterio
        from rasterio.transform import from_bounds
    except ImportError:
        raise ImportError("rasterio and numpy required: pip install rasterio numpy")

    arr   = np.array(grid, dtype=np.float32)
    rows, cols = arr.shape
    transform = from_bounds(
        bbox.min_lon, bbox.min_lat, bbox.max_lon, bbox.max_lat, cols, rows
    )
    with rasterio.open(
        output_path, "w",
        driver="GTiff",
        height=rows, width=cols,
        count=1,
        dtype=arr.dtype,
        crs=crs,
        transform=transform,
    ) as dst:
        dst.write(arr, 1)

    logger.info(f"GeoTIFF saved → {output_path}")
    return output_path


def export_csv(grid: list[list[float]], output_path: str) -> str:
    """Export a 2D grid as a flat row,col,value CSV."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("row,col,value\n")
        for r, row in enumerate(grid):
            for c, val in enumerate(row):
                f.write(f"{r},{c},{val:.4f}\n")
    logger.info(f"CSV saved → {output_path}")
    return output_path


# ── Pure-Python fallbacks ─────────────────────────────────────────────────────

def _py_slope_aspect(dem, cell_size):
    rows, cols = len(dem), len(dem[0])
    slope  = [[0.0]*cols for _ in range(rows)]
    aspect = [[float("nan")]*cols for _ in range(rows)]
    import math
    for r in range(1, rows-1):
        for c in range(1, cols-1):
            a, b, cc = dem[r-1][c-1], dem[r-1][c], dem[r-1][c+1]
            d = dem[r][c-1]; f = dem[r][c+1]
            g, h, i = dem[r+1][c-1], dem[r+1][c], dem[r+1][c+1]
            dzdx = ((cc + 2*f + i) - (a + 2*d + g)) / (8*cell_size)
            dzdy = ((a + 2*b + cc) - (g + 2*h + i)) / (8*cell_size)
            s = math.sqrt(dzdx**2 + dzdy**2)
            slope[r][c]  = math.degrees(math.atan(s))
            asp = math.degrees(math.atan2(dzdx, -dzdy))
            aspect[r][c] = (asp + 360) % 360
    return {"slope": slope, "aspect": aspect}


def _py_tri(dem):
    rows, cols = len(dem), len(dem[0])
    import math
    tri = [[0.0]*cols for _ in range(rows)]
    for r in range(1, rows-1):
        for c in range(1, cols-1):
            ctr = dem[r][c]
            sq  = sum((dem[r+dr][c+dc] - ctr)**2
                      for dr in (-1,0,1) for dc in (-1,0,1)
                      if not (dr==0 and dc==0))
            tri[r][c] = math.sqrt(sq)
    return tri


def _py_viewshed(dem, obs_r, obs_c, obs_h):
    rows, cols = len(dem), len(dem[0])
    import math
    vis = [[False]*cols for _ in range(rows)]
    obs_elev = dem[obs_r][obs_c] + obs_h
    for r in range(rows):
        for c in range(cols):
            dr = r - obs_r; dc = c - obs_c
            dist = math.sqrt(dr*dr + dc*dc)
            if dist < 1e-6:
                vis[r][c] = True; continue
            steps = int(dist)
            blocked = False
            for step in range(1, steps):
                t = step / dist
                ir = round(obs_r + t*dr); ic = round(obs_c + t*dc)
                if not (0 <= ir < rows and 0 <= ic < cols): break
                horizon = obs_elev + (dem[r][c] - obs_elev) * t
                if dem[ir][ic] > horizon:
                    blocked = True; break
            vis[r][c] = not blocked
    return vis


def _py_focal_mean(dem, radius):
    rows, cols = len(dem), len(dem[0])
    out = [[0.0]*cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            vals = [dem[r+dr][c+dc]
                    for dr in range(-radius, radius+1)
                    for dc in range(-radius, radius+1)
                    if 0 <= r+dr < rows and 0 <= c+dc < cols]
            out[r][c] = sum(vals) / len(vals)
    return out
