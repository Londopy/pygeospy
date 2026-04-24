/// terrain.rs — DEM raster analysis: slope, aspect, TRI, viewshed.
/// Operating over large grids (millions of cells) is where Rust earns its keep.

use pyo3::prelude::*;

// ── Core computations ─────────────────────────────────────────────────────────

/// Compute slope (degrees) and aspect (degrees, 0=N CW) from a DEM grid.
/// `cell_size` is the grid spacing in metres.
/// Returns (slope_grid, aspect_grid) each as row-major Vec<Vec<f64>>.
pub fn slope_aspect_impl(dem: &[Vec<f64>], cell_size: f64) -> (Vec<Vec<f64>>, Vec<Vec<f64>>) {
    let rows = dem.len();
    if rows < 3 { return (vec![], vec![]); }
    let cols = dem[0].len();
    if cols < 3 { return (vec![], vec![]); }

    let mut slope  = vec![vec![0.0_f64; cols]; rows];
    let mut aspect = vec![vec![f64::NAN; cols]; rows];

    for r in 1..(rows - 1) {
        for c in 1..(cols - 1) {
            // 3×3 Zevenbergen & Thorne kernel
            let a = dem[r-1][c-1]; let b = dem[r-1][c]; let cc = dem[r-1][c+1];
            let d = dem[r  ][c-1];                       let f = dem[r  ][c+1];
            let g = dem[r+1][c-1]; let h = dem[r+1][c]; let i = dem[r+1][c+1];

            let dz_dx = ((cc + 2.0*f + i) - (a + 2.0*d + g)) / (8.0 * cell_size);
            let dz_dy = ((a + 2.0*b + cc) - (g + 2.0*h + i)) / (8.0 * cell_size);

            let s = (dz_dx * dz_dx + dz_dy * dz_dy).sqrt();
            slope[r][c]  = s.atan().to_degrees();

            // Aspect: 0=N, 90=E, 180=S, 270=W
            let asp = dz_dx.atan2(-dz_dy).to_degrees();
            aspect[r][c] = (asp + 360.0) % 360.0;
        }
    }

    (slope, aspect)
}

/// Terrain Ruggedness Index (Wilson & Gallant 2000).
/// TRI[i][j] = sqrt(sum of squared elevation differences with 8 neighbours).
pub fn terrain_ruggedness_index_impl(dem: &[Vec<f64>]) -> Vec<Vec<f64>> {
    let rows = dem.len();
    if rows < 3 { return vec![]; }
    let cols = dem[0].len();
    let mut tri = vec![vec![0.0_f64; cols]; rows];

    for r in 1..(rows - 1) {
        for c in 1..(cols - 1) {
            let centre = dem[r][c];
            let mut sum_sq = 0.0;
            for dr in -1_i32..=1 {
                for dc in -1_i32..=1 {
                    if dr == 0 && dc == 0 { continue; }
                    let nr = (r as i32 + dr) as usize;
                    let nc = (c as i32 + dc) as usize;
                    let diff = dem[nr][nc] - centre;
                    sum_sq += diff * diff;
                }
            }
            tri[r][c] = sum_sq.sqrt();
        }
    }
    tri
}

/// Vector Ruggedness Measure (Sappington et al. 2007) — alternative to TRI.
/// Returns VRM values 0–1 (0=flat, 1=very rugged).
pub fn vector_ruggedness_measure_impl(
    slope_grid: &[Vec<f64>],
    aspect_grid: &[Vec<f64>],
    window: usize,
) -> Vec<Vec<f64>> {
    let rows = slope_grid.len();
    if rows == 0 { return vec![]; }
    let cols = slope_grid[0].len();
    let w = window as i32;
    let mut vrm = vec![vec![0.0_f64; cols]; rows];
    let _n = (2 * window + 1).pow(2) as f64;

    for r in 0..rows {
        for c in 0..cols {
            let mut sx = 0.0_f64;
            let mut sy = 0.0_f64;
            let mut sz = 0.0_f64;
            let mut count = 0_u32;

            for dr in -w..=w {
                for dc in -w..=w {
                    let nr = r as i32 + dr;
                    let nc = c as i32 + dc;
                    if nr < 0 || nr >= rows as i32 || nc < 0 || nc >= cols as i32 { continue; }
                    let slope_r = slope_grid[nr as usize][nc as usize].to_radians();
                    let asp_r   = aspect_grid[nr as usize][nc as usize].to_radians();
                    sx += slope_r.sin() * asp_r.sin();
                    sy += slope_r.sin() * asp_r.cos();
                    sz += slope_r.cos();
                    count += 1;
                }
            }
            let cn = count as f64;
            vrm[r][c] = 1.0 - (sx*sx + sy*sy + sz*sz).sqrt() / cn.max(1.0);
        }
    }
    vrm
}

/// Line-of-sight / viewshed from an observer point.
/// Uses a simple ray-march algorithm.
/// `observer_height_m`: height of observer above DEM (e.g. 1.8 for standing person).
/// Returns a flat boolean grid (row-major, true = visible).
pub fn viewshed_impl(
    dem: &[Vec<f64>],
    observer_row: usize,
    observer_col: usize,
    observer_height_m: f64,
    _cell_size_m: f64,
    max_range_cells: Option<usize>,
) -> Vec<Vec<bool>> {
    let rows = dem.len();
    if rows == 0 { return vec![]; }
    let cols = dem[0].len();
    let mut vis = vec![vec![false; cols]; rows];

    let obs_elev = dem[observer_row][observer_col] + observer_height_m;
    let max_r = max_range_cells.unwrap_or(usize::MAX);

    for r in 0..rows {
        for c in 0..cols {
            let dr = r as i32 - observer_row as i32;
            let dc = c as i32 - observer_col as i32;
            let dist_cells = ((dr * dr + dc * dc) as f64).sqrt();
            if dist_cells as usize > max_r { continue; }
            if dist_cells < 1e-6 {
                vis[r][c] = true;
                continue;
            }
            // March along the ray; if any intermediate point is higher, target is not visible
            let steps = dist_cells.ceil() as usize;
            let mut blocked = false;

            for step in 1..steps {
                let t = step as f64 / dist_cells;
                let ir = (observer_row as f64 + t * dr as f64).round() as usize;
                let ic = (observer_col as f64 + t * dc as f64).round() as usize;
                if ir >= rows || ic >= cols { break; }

                let horizon_elev = obs_elev + (dem[r][c] - obs_elev) * t;
                if dem[ir][ic] > horizon_elev {
                    blocked = true;
                    break;
                }
            }
            vis[r][c] = !blocked;
        }
    }
    vis
}

/// Extract elevation profile along a sequence of (row, col) indices.
pub fn elevation_profile_impl(dem: &[Vec<f64>], points: &[(usize, usize)]) -> Vec<f64> {
    points.iter()
        .filter_map(|(r, c)| dem.get(*r).and_then(|row| row.get(*c)).copied())
        .collect()
}

/// Simple focal mean (moving average) smoothing for DEM pre-processing.
pub fn focal_mean_impl(dem: &[Vec<f64>], radius: usize) -> Vec<Vec<f64>> {
    let rows = dem.len();
    if rows == 0 { return vec![]; }
    let cols = dem[0].len();
    let r = radius as i32;
    let mut out = vec![vec![0.0_f64; cols]; rows];

    for row in 0..rows {
        for col in 0..cols {
            let mut sum = 0.0;
            let mut n = 0_u32;
            for dr in -r..=r {
                for dc in -r..=r {
                    let nr = row as i32 + dr;
                    let nc = col as i32 + dc;
                    if nr >= 0 && nr < rows as i32 && nc >= 0 && nc < cols as i32 {
                        sum += dem[nr as usize][nc as usize];
                        n += 1;
                    }
                }
            }
            out[row][col] = sum / n as f64;
        }
    }
    out
}

/// Identify local maxima (ridge/peak pixels) in a DEM grid.
pub fn local_maxima_impl(dem: &[Vec<f64>]) -> Vec<(usize, usize, f64)> {
    let rows = dem.len();
    if rows < 3 { return vec![]; }
    let cols = dem[0].len();
    let mut peaks = Vec::new();

    for r in 1..(rows - 1) {
        for c in 1..(cols - 1) {
            let v = dem[r][c];
            let is_max = (-1_i32..=1).all(|dr| (-1_i32..=1).all(|dc| {
                if dr == 0 && dc == 0 { true }
                else { dem[(r as i32 + dr) as usize][(c as i32 + dc) as usize] <= v }
            }));
            if is_max { peaks.push((r, c, v)); }
        }
    }
    peaks
}

// ── PyO3 wrappers ─────────────────────────────────────────────────────────────

#[pyfunction]
fn slope_aspect(dem: Vec<Vec<f64>>, cell_size: f64) -> (Vec<Vec<f64>>, Vec<Vec<f64>>) {
    slope_aspect_impl(&dem, cell_size)
}

#[pyfunction]
fn terrain_ruggedness_index(dem: Vec<Vec<f64>>) -> Vec<Vec<f64>> {
    terrain_ruggedness_index_impl(&dem)
}

#[pyfunction]
fn vector_ruggedness_measure(
    slope_grid: Vec<Vec<f64>>,
    aspect_grid: Vec<Vec<f64>>,
    window: usize,
) -> Vec<Vec<f64>> {
    vector_ruggedness_measure_impl(&slope_grid, &aspect_grid, window)
}

#[pyfunction]
#[pyo3(signature = (dem, observer_row, observer_col, observer_height_m, cell_size_m, max_range_cells=None))]
fn viewshed(
    dem: Vec<Vec<f64>>,
    observer_row: usize,
    observer_col: usize,
    observer_height_m: f64,
    cell_size_m: f64,
    max_range_cells: Option<usize>,
) -> Vec<Vec<bool>> {
    viewshed_impl(&dem, observer_row, observer_col, observer_height_m, cell_size_m, max_range_cells)
}

#[pyfunction]
fn elevation_profile(dem: Vec<Vec<f64>>, points: Vec<(usize, usize)>) -> Vec<f64> {
    elevation_profile_impl(&dem, &points)
}

#[pyfunction]
fn focal_mean(dem: Vec<Vec<f64>>, radius: usize) -> Vec<Vec<f64>> {
    focal_mean_impl(&dem, radius)
}

#[pyfunction]
fn local_maxima(dem: Vec<Vec<f64>>) -> Vec<(usize, usize, f64)> {
    local_maxima_impl(&dem)
}

pub fn register(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    let m = PyModule::new(parent.py(), "terrain")?;
    m.add_function(wrap_pyfunction!(slope_aspect, &m)?)?;
    m.add_function(wrap_pyfunction!(terrain_ruggedness_index, &m)?)?;
    m.add_function(wrap_pyfunction!(vector_ruggedness_measure, &m)?)?;
    m.add_function(wrap_pyfunction!(viewshed, &m)?)?;
    m.add_function(wrap_pyfunction!(elevation_profile, &m)?)?;
    m.add_function(wrap_pyfunction!(focal_mean, &m)?)?;
    m.add_function(wrap_pyfunction!(local_maxima, &m)?)?;
    parent.add_submodule(&m)?;
    Ok(())
}
