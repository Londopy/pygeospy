/// raster.rs — Generic raster / pixel math for satellite and image analysis.
/// NDVI, band statistics, image preprocessing for OCR pipelines.

use pyo3::prelude::*;

// ── Band / index math ─────────────────────────────────────────────────────────

/// NDVI per pixel: (NIR - RED) / (NIR + RED).
/// Inputs are reflectance values (0–1 or raw DN — caller normalises).
pub fn ndvi_impl(red: &[f64], nir: &[f64]) -> Vec<f64> {
    red.iter().zip(nir.iter()).map(|(r, n)| {
        let denom = n + r;
        if denom.abs() < 1e-9 { 0.0 } else { (n - r) / denom }
    }).collect()
}

/// EVI (Enhanced Vegetation Index): 2.5 * (NIR - RED) / (NIR + 6*RED - 7.5*BLUE + 1)
pub fn evi_impl(red: &[f64], nir: &[f64], blue: &[f64]) -> Vec<f64> {
    red.iter().zip(nir.iter()).zip(blue.iter()).map(|((r, n), b)| {
        let denom = n + 6.0 * r - 7.5 * b + 1.0;
        if denom.abs() < 1e-9 { 0.0 } else { 2.5 * (n - r) / denom }
    }).collect()
}

/// MNDWI (Modified Normalized Difference Water Index): (GREEN - SWIR) / (GREEN + SWIR)
pub fn mndwi_impl(green: &[f64], swir: &[f64]) -> Vec<f64> {
    green.iter().zip(swir.iter()).map(|(g, s)| {
        let denom = g + s;
        if denom.abs() < 1e-9 { 0.0 } else { (g - s) / denom }
    }).collect()
}

/// Urban Heat Index: (SWIR - NIR) / (SWIR + NIR)
pub fn urban_heat_index_impl(swir: &[f64], nir: &[f64]) -> Vec<f64> {
    swir.iter().zip(nir.iter()).map(|(s, n)| {
        let denom = s + n;
        if denom.abs() < 1e-9 { 0.0 } else { (s - n) / denom }
    }).collect()
}

// ── Statistics ────────────────────────────────────────────────────────────────

/// Basic pixel statistics: (min, max, mean, std_dev, median).
pub fn pixel_statistics_impl(pixels: &[f64]) -> (f64, f64, f64, f64, f64) {
    if pixels.is_empty() { return (0.0, 0.0, 0.0, 0.0, 0.0); }

    let n = pixels.len() as f64;
    let mut sorted = pixels.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());

    let min  = sorted[0];
    let max  = *sorted.last().unwrap();
    let mean = sorted.iter().sum::<f64>() / n;
    let var  = sorted.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / n;
    let std  = var.sqrt();
    let mid  = sorted.len() / 2;
    let med  = if sorted.len() % 2 == 0 {
        (sorted[mid - 1] + sorted[mid]) / 2.0
    } else {
        sorted[mid]
    };

    (min, max, mean, std, med)
}

/// Histogram with `bins` equal-width buckets. Returns (bin_edges, counts).
pub fn histogram_impl(pixels: &[f64], bins: usize) -> (Vec<f64>, Vec<u64>) {
    if pixels.is_empty() || bins == 0 { return (vec![], vec![]); }
    let min = pixels.iter().cloned().fold(f64::INFINITY,  f64::min);
    let max = pixels.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let range = max - min;
    if range < 1e-12 { return (vec![min, max], vec![pixels.len() as u64]); }
    let width = range / bins as f64;
    let mut counts = vec![0_u64; bins];
    for &p in pixels {
        let idx = ((p - min) / width).floor() as usize;
        let idx = idx.min(bins - 1);
        counts[idx] += 1;
    }
    let edges = (0..=bins).map(|i| min + i as f64 * width).collect();
    (edges, counts)
}

// ── Image preprocessing ───────────────────────────────────────────────────────

/// Otsu binarization: compute optimal threshold from grayscale u8 histogram.
/// Returns the threshold value (0–255).
pub fn otsu_threshold_impl(pixels: &[u8]) -> u8 {
    let n = pixels.len();
    if n == 0 { return 128; }

    // Build histogram
    let mut hist = [0_u64; 256];
    for &p in pixels { hist[p as usize] += 1; }

    let total = n as f64;
    let mut sum_all = 0.0_f64;
    for i in 0..256 { sum_all += i as f64 * hist[i] as f64; }

    let mut sum_bg = 0.0_f64;
    let mut w_bg   = 0_u64;
    let mut best_var = 0.0_f64;
    let mut threshold = 128_u8;

    for t in 0_u8..=255 {
        w_bg += hist[t as usize];
        if w_bg == 0 { continue; }
        let w_fg = total as u64 - w_bg;
        if w_fg == 0 { break; }

        sum_bg += t as f64 * hist[t as usize] as f64;
        let mean_bg = sum_bg / w_bg as f64;
        let mean_fg = (sum_all - sum_bg) / w_fg as f64;

        let var = w_bg as f64 * w_fg as f64 * (mean_bg - mean_fg).powi(2);
        if var > best_var {
            best_var  = var;
            threshold = t;
        }
    }
    threshold
}

/// Apply threshold to produce binary image (0 or 255).
pub fn binarize_impl(pixels: &[u8], threshold: u8) -> Vec<u8> {
    pixels.iter().map(|&p| if p >= threshold { 255 } else { 0 }).collect()
}

/// 3×3 median filter (noise reduction for OCR preprocessing).
/// `width` is the image width in pixels.
pub fn median_filter_3x3_impl(pixels: &[u8], width: usize) -> Vec<u8> {
    let n = pixels.len();
    if width == 0 || n == 0 { return pixels.to_vec(); }
    let height = n / width;
    let mut out = pixels.to_vec();
    let w = width as i32;
    let h = height as i32;

    for row in 1..(h - 1) {
        for col in 1..(w - 1) {
            let mut kernel = Vec::with_capacity(9);
            for dr in -1_i32..=1 {
                for dc in -1_i32..=1 {
                    let idx = ((row + dr) * w + (col + dc)) as usize;
                    kernel.push(pixels[idx]);
                }
            }
            kernel.sort_unstable();
            out[(row * w + col) as usize] = kernel[4];
        }
    }
    out
}

/// Linear stretch (contrast normalisation) of pixel values to 0–255.
pub fn linear_stretch_impl(pixels: &[u8]) -> Vec<u8> {
    let min = *pixels.iter().min().unwrap_or(&0) as f64;
    let max = *pixels.iter().max().unwrap_or(&255) as f64;
    let range = (max - min).max(1.0);
    pixels.iter().map(|&p| ((p as f64 - min) / range * 255.0).round() as u8).collect()
}

// ── PyO3 wrappers ─────────────────────────────────────────────────────────────

#[pyfunction]
fn ndvi(red: Vec<f64>, nir: Vec<f64>) -> Vec<f64> {
    ndvi_impl(&red, &nir)
}

#[pyfunction]
fn evi(red: Vec<f64>, nir: Vec<f64>, blue: Vec<f64>) -> Vec<f64> {
    evi_impl(&red, &nir, &blue)
}

#[pyfunction]
fn mndwi(green: Vec<f64>, swir: Vec<f64>) -> Vec<f64> {
    mndwi_impl(&green, &swir)
}

#[pyfunction]
fn urban_heat_index(swir: Vec<f64>, nir: Vec<f64>) -> Vec<f64> {
    urban_heat_index_impl(&swir, &nir)
}

#[pyfunction]
fn pixel_statistics(pixels: Vec<f64>) -> (f64, f64, f64, f64, f64) {
    pixel_statistics_impl(&pixels)
}

#[pyfunction]
fn histogram(pixels: Vec<f64>, bins: usize) -> (Vec<f64>, Vec<u64>) {
    histogram_impl(&pixels, bins)
}

#[pyfunction]
fn otsu_threshold(pixels: Vec<u8>) -> u8 {
    otsu_threshold_impl(&pixels)
}

#[pyfunction]
fn binarize(pixels: Vec<u8>, threshold: u8) -> Vec<u8> {
    binarize_impl(&pixels, threshold)
}

#[pyfunction]
fn median_filter_3x3(pixels: Vec<u8>, width: usize) -> Vec<u8> {
    median_filter_3x3_impl(&pixels, width)
}

#[pyfunction]
fn linear_stretch(pixels: Vec<u8>) -> Vec<u8> {
    linear_stretch_impl(&pixels)
}

pub fn register(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    let m = PyModule::new(parent.py(), "raster")?;
    m.add_function(wrap_pyfunction!(ndvi, &m)?)?;
    m.add_function(wrap_pyfunction!(evi, &m)?)?;
    m.add_function(wrap_pyfunction!(mndwi, &m)?)?;
    m.add_function(wrap_pyfunction!(urban_heat_index, &m)?)?;
    m.add_function(wrap_pyfunction!(pixel_statistics, &m)?)?;
    m.add_function(wrap_pyfunction!(histogram, &m)?)?;
    m.add_function(wrap_pyfunction!(otsu_threshold, &m)?)?;
    m.add_function(wrap_pyfunction!(binarize, &m)?)?;
    m.add_function(wrap_pyfunction!(median_filter_3x3, &m)?)?;
    m.add_function(wrap_pyfunction!(linear_stretch, &m)?)?;
    parent.add_submodule(&m)?;
    Ok(())
}
