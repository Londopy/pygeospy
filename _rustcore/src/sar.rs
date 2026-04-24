/// sar.rs — Search and Rescue grid / polygon math.
/// Generates NASAR-style search zones, corridors, and probability rings.
/// All geometry is pure Rust; GPX/GeoJSON serialization stays in Python.

use pyo3::prelude::*;
use std::f64::consts::PI;

use crate::coords::{
    destination_point_impl, bearing_impl,
};

const DEG2RAD: f64 = PI / 180.0;

// ── Grid generation ───────────────────────────────────────────────────────────

/// Generate a rectangular search grid centred on (lat, lon).
/// `cell_km` is the side length of each cell.
/// `radius_km` is the half-extent of the grid (full grid = 2×radius square).
/// Returns a list of cell polygons: each cell is Vec<(lat,lon)> of 5 points (closed ring).
pub fn search_grid_impl(
    center_lat: f64,
    center_lon: f64,
    radius_km: f64,
    cell_km: f64,
) -> Vec<Vec<(f64, f64)>> {
    let n_cells = (2.0 * radius_km / cell_km).ceil() as i32;
    let mut cells = Vec::new();

    for row in 0..n_cells {
        for col in 0..n_cells {
            // SW corner of this cell
            let south_offset = (row as f64 - n_cells as f64 / 2.0) * cell_km;
            let west_offset  = (col as f64 - n_cells as f64 / 2.0) * cell_km;

            let sw = destination_point_impl(
                destination_point_impl(center_lat, center_lon, 180.0, -south_offset).0,
                destination_point_impl(center_lat, center_lon, 180.0, -south_offset).1,
                270.0,
                -west_offset,
            );

            let se = destination_point_impl(sw.0, sw.1, 90.0, cell_km);
            let ne = destination_point_impl(se.0, se.1, 0.0,  cell_km);
            let nw = destination_point_impl(sw.0, sw.1, 0.0,  cell_km);

            // Closed ring
            cells.push(vec![sw, se, ne, nw, sw]);
        }
    }
    cells
}

/// Generate search grid with named sector labels (A-Z, AA-AZ, ...).
/// Returns Vec of (label, Vec<(lat,lon)>) pairs.
pub fn named_search_grid_impl(
    center_lat: f64,
    center_lon: f64,
    radius_km: f64,
    cell_km: f64,
) -> Vec<(String, Vec<(f64, f64)>)> {
    let cells = search_grid_impl(center_lat, center_lon, radius_km, cell_km);
    cells.into_iter().enumerate().map(|(i, poly)| {
        let label = sector_label(i);
        (label, poly)
    }).collect()
}

fn sector_label(idx: usize) -> String {
    let alphabet = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    if idx < 26 {
        String::from(alphabet[idx] as char)
    } else {
        let first  = alphabet[(idx / 26) - 1] as char;
        let second = alphabet[idx % 26] as char;
        format!("{}{}", first, second)
    }
}

/// Generate a search corridor along a polyline of waypoints.
/// `width_km` is the total corridor width (half-width each side).
/// Returns list of polygon rings (one per segment).
pub fn corridor_search_impl(
    waypoints: &[(f64, f64)],
    width_km: f64,
) -> Vec<Vec<(f64, f64)>> {
    if waypoints.len() < 2 { return vec![]; }
    let half = width_km / 2.0;
    let mut segments = Vec::new();

    for i in 0..(waypoints.len() - 1) {
        let (lat1, lon1) = waypoints[i];
        let (lat2, lon2) = waypoints[i + 1];
        let brg = bearing_impl(lat1, lon1, lat2, lon2);
        let left  = (brg + 270.0) % 360.0;
        let right = (brg +  90.0) % 360.0;

        let sw = destination_point_impl(lat1, lon1, left,  half);
        let se = destination_point_impl(lat1, lon1, right, half);
        let ne = destination_point_impl(lat2, lon2, right, half);
        let nw = destination_point_impl(lat2, lon2, left,  half);

        segments.push(vec![sw, se, ne, nw, sw]);
    }
    segments
}

/// Generate probability-of-area (POA) rings.
/// Returns rings at specified radii (km) from IPP, representing probability bands.
/// Each ring is a polygon approximation (n_points vertices).
pub fn poa_rings_impl(
    ipp_lat: f64,
    ipp_lon: f64,
    radii_km: &[f64],
    n_points: usize,
) -> Vec<Vec<(f64, f64)>> {
    radii_km.iter().map(|&r| {
        (0..=n_points).map(|i| {
            let bearing = (i as f64 / n_points as f64) * 360.0;
            destination_point_impl(ipp_lat, ipp_lon, bearing, r)
        }).collect()
    }).collect()
}

/// Compute hasty-search urgency score (0–10) from subject profile inputs.
/// Higher = more urgent.
pub fn urgency_score_impl(
    age: u32,
    medical_condition: bool,
    last_seen_hours: f64,
    night_time: bool,
    adverse_weather: bool,
    terrain_difficult: bool,
) -> f64 {
    let mut score = 0.0_f64;

    // Age factor
    score += if age < 12 || age > 70 { 3.0 } else { 1.0 };

    // Medical
    score += if medical_condition { 2.5 } else { 0.0 };

    // Time missing (hours)
    score += (last_seen_hours / 4.0).min(2.0);

    // Environmental
    score += if night_time     { 1.0 } else { 0.0 };
    score += if adverse_weather { 1.0 } else { 0.0 };
    score += if terrain_difficult { 0.5 } else { 0.0 };

    score.min(10.0)
}

/// Lost person behavior radius estimates by profile type.
/// Returns (typical_km, max_km) for several ISRID-derived profiles.
pub fn lost_person_radius_impl(profile: &str) -> (f64, f64) {
    // Source: International Search and Rescue Incident Database (ISRID)
    match profile.to_lowercase().as_str() {
        "hiker"           => (2.9, 14.5),
        "hunter"          => (3.6, 16.0),
        "child_1_3"       => (0.5, 1.6),
        "child_4_6"       => (0.8, 3.0),
        "child_7_9"       => (1.6, 4.0),
        "child_10_12"     => (2.0, 5.0),
        "child_13_15"     => (2.5, 7.0),
        "despondent"      => (2.3, 8.8),
        "alzheimer"       => (0.8, 5.0),
        "dementia"        => (0.8, 5.0),
        "outdoor_worker"  => (3.9, 18.0),
        "trail_runner"    => (5.0, 25.0),
        "mountain_biker"  => (8.0, 35.0),
        "horseback"       => (6.0, 25.0),
        "atv"             => (12.0, 55.0),
        "snowmobiler"     => (15.0, 60.0),
        _                 => (3.0, 15.0), // generic default
    }
}

/// Generate expand-and-shrink creeping-line search pattern.
/// Returns ordered waypoints to fly / walk.
pub fn expanding_square_impl(
    ipp_lat: f64,
    ipp_lon: f64,
    leg_spacing_km: f64,
    legs: u32,
) -> Vec<(f64, f64)> {
    let mut waypoints = vec![(ipp_lat, ipp_lon)];
    let mut current   = (ipp_lat, ipp_lon);
    let bearings = [0.0_f64, 90.0, 180.0, 270.0]; // N, E, S, W
    let mut bear_idx = 0_usize;
    let mut step_count = 1_u32;
    let mut steps_this_dir = 1_u32;
    let mut dir_changes = 0_u32;

    for _ in 0..legs {
        let bearing = bearings[bear_idx % 4];
        let dist = leg_spacing_km * step_count as f64;
        current = destination_point_impl(current.0, current.1, bearing, dist);
        waypoints.push(current);

        dir_changes += 1;
        bear_idx += 1;
        if dir_changes % 2 == 0 {
            steps_this_dir += 1;
        }
        step_count = steps_this_dir;
    }
    waypoints
}

// ── PyO3 wrappers ─────────────────────────────────────────────────────────────

#[pyfunction]
fn search_grid(center_lat: f64, center_lon: f64, radius_km: f64, cell_km: f64) -> Vec<Vec<(f64, f64)>> {
    search_grid_impl(center_lat, center_lon, radius_km, cell_km)
}

#[pyfunction]
fn named_search_grid(center_lat: f64, center_lon: f64, radius_km: f64, cell_km: f64) -> Vec<(String, Vec<(f64, f64)>)> {
    named_search_grid_impl(center_lat, center_lon, radius_km, cell_km)
}

#[pyfunction]
fn corridor_search(waypoints: Vec<(f64, f64)>, width_km: f64) -> Vec<Vec<(f64, f64)>> {
    corridor_search_impl(&waypoints, width_km)
}

#[pyfunction]
#[pyo3(signature = (ipp_lat, ipp_lon, radii_km, n_points=64))]
fn poa_rings(ipp_lat: f64, ipp_lon: f64, radii_km: Vec<f64>, n_points: usize) -> Vec<Vec<(f64, f64)>> {
    poa_rings_impl(ipp_lat, ipp_lon, &radii_km, n_points)
}

#[pyfunction]
fn urgency_score(
    age: u32,
    medical_condition: bool,
    last_seen_hours: f64,
    night_time: bool,
    adverse_weather: bool,
    terrain_difficult: bool,
) -> f64 {
    urgency_score_impl(age, medical_condition, last_seen_hours, night_time, adverse_weather, terrain_difficult)
}

#[pyfunction]
fn lost_person_radius(profile: &str) -> (f64, f64) {
    lost_person_radius_impl(profile)
}

#[pyfunction]
fn expanding_square(ipp_lat: f64, ipp_lon: f64, leg_spacing_km: f64, legs: u32) -> Vec<(f64, f64)> {
    expanding_square_impl(ipp_lat, ipp_lon, leg_spacing_km, legs)
}

pub fn register(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    let m = PyModule::new(parent.py(), "sar")?;
    m.add_function(wrap_pyfunction!(search_grid, &m)?)?;
    m.add_function(wrap_pyfunction!(named_search_grid, &m)?)?;
    m.add_function(wrap_pyfunction!(corridor_search, &m)?)?;
    m.add_function(wrap_pyfunction!(poa_rings, &m)?)?;
    m.add_function(wrap_pyfunction!(urgency_score, &m)?)?;
    m.add_function(wrap_pyfunction!(lost_person_radius, &m)?)?;
    m.add_function(wrap_pyfunction!(expanding_square, &m)?)?;
    parent.add_submodule(&m)?;
    Ok(())
}
