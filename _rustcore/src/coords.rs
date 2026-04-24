/// coords.rs — Coordinate math: haversine, bearing, projections, bounding boxes.
/// All functions are pure/stateless with no I/O — ideal for tight loops.

use pyo3::prelude::*;
use std::f64::consts::PI;

const EARTH_RADIUS_KM: f64 = 6371.0088;
const DEG2RAD: f64 = PI / 180.0;
const RAD2DEG: f64 = 180.0 / PI;

// ── Helpers ──────────────────────────────────────────────────────────────────

#[inline]
fn to_rad(deg: f64) -> f64 { deg * DEG2RAD }

#[inline]
fn to_deg(rad: f64) -> f64 { rad * RAD2DEG }

#[inline]
fn wrap_bearing(b: f64) -> f64 {
    ((b % 360.0) + 360.0) % 360.0
}

// ── Core functions (also exposed as free Rust API) ────────────────────────────

/// Haversine great-circle distance in kilometres.
pub fn haversine_distance_impl(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> f64 {
    let dlat = to_rad(lat2 - lat1);
    let dlon = to_rad(lon2 - lon1);
    let a = (dlat / 2.0).sin().powi(2)
        + to_rad(lat1).cos() * to_rad(lat2).cos() * (dlon / 2.0).sin().powi(2);
    let c = 2.0 * a.sqrt().asin();
    EARTH_RADIUS_KM * c
}

/// Initial bearing from point 1 → point 2 (degrees, 0–360).
pub fn bearing_impl(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> f64 {
    let lat1r = to_rad(lat1);
    let lat2r = to_rad(lat2);
    let dlon  = to_rad(lon2 - lon1);
    let y = dlon.sin() * lat2r.cos();
    let x = lat1r.cos() * lat2r.sin() - lat1r.sin() * lat2r.cos() * dlon.cos();
    wrap_bearing(to_deg(y.atan2(x)))
}

/// Destination point given start, bearing (degrees), distance (km).
pub fn destination_point_impl(lat: f64, lon: f64, bearing_deg: f64, distance_km: f64) -> (f64, f64) {
    let latr = to_rad(lat);
    let lonr = to_rad(lon);
    let br   = to_rad(bearing_deg);
    let dr   = distance_km / EARTH_RADIUS_KM;

    let lat2 = (latr.sin() * dr.cos() + latr.cos() * dr.sin() * br.cos()).asin();
    let lon2 = lonr + (br.sin() * dr.sin() * latr.cos()).atan2(dr.cos() - latr.sin() * lat2.sin());
    (to_deg(lat2), to_deg(lon2))
}

/// Midpoint between two coordinates.
pub fn midpoint_impl(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> (f64, f64) {
    let lat1r = to_rad(lat1);
    let lat2r = to_rad(lat2);
    let dlon  = to_rad(lon2 - lon1);

    let bx = lat2r.cos() * dlon.cos();
    let by = lat2r.cos() * dlon.sin();

    let lat3 = (lat1r.sin() + lat2r.sin()).atan2(((lat1r.cos() + bx).powi(2) + by.powi(2)).sqrt());
    let lon3 = to_rad(lon1) + by.atan2(lat1r.cos() + bx);
    (to_deg(lat3), to_deg(lon3))
}

/// Cross-track distance (signed, km): distance of point P3 from the great-circle
/// defined by P1→P2. Positive = right of track, negative = left.
pub fn cross_track_distance_impl(
    lat1: f64, lon1: f64,
    lat2: f64, lon2: f64,
    lat3: f64, lon3: f64,
) -> f64 {
    let d13  = haversine_distance_impl(lat1, lon1, lat3, lon3) / EARTH_RADIUS_KM;
    let b13  = to_rad(bearing_impl(lat1, lon1, lat3, lon3));
    let b12  = to_rad(bearing_impl(lat1, lon1, lat2, lon2));
    EARTH_RADIUS_KM * ((d13.sin() * (b13 - b12).sin()).asin())
}

/// Along-track distance (km): how far along P1→P2 the closest point to P3 lies.
pub fn along_track_distance_impl(
    lat1: f64, lon1: f64,
    lat2: f64, lon2: f64,
    lat3: f64, lon3: f64,
) -> f64 {
    let d13 = haversine_distance_impl(lat1, lon1, lat3, lon3) / EARTH_RADIUS_KM;
    let xt  = cross_track_distance_impl(lat1, lon1, lat2, lon2, lat3, lon3) / EARTH_RADIUS_KM;
    EARTH_RADIUS_KM * ((d13.powi(2) - xt.powi(2)).sqrt()).asin()
}

/// Bounding box [min_lat, min_lon, max_lat, max_lon] from centre + radius (km).
pub fn bounding_box_impl(lat: f64, lon: f64, radius_km: f64) -> (f64, f64, f64, f64) {
    let dlat = to_deg(radius_km / EARTH_RADIUS_KM);
    let dlon = to_deg(radius_km / (EARTH_RADIUS_KM * to_rad(lat).cos()));
    (lat - dlat, lon - dlon, lat + dlat, lon + dlon)
}

/// Decimal degrees → degrees / minutes / seconds.
/// Returns (degrees: i32, minutes: i32, seconds: f64).
pub fn dd_to_dms_impl(dd: f64) -> (i32, i32, f64) {
    let abs = dd.abs();
    let deg = abs.floor() as i32;
    let min_full = (abs - deg as f64) * 60.0;
    let min = min_full.floor() as i32;
    let sec = (min_full - min as f64) * 60.0;
    (deg, min, sec)
}

/// DMS → decimal degrees. direction: 1 = N/E, -1 = S/W.
pub fn dms_to_dd_impl(degrees: i32, minutes: i32, seconds: f64, direction: i32) -> f64 {
    (degrees as f64 + minutes as f64 / 60.0 + seconds / 3600.0) * direction as f64
}

/// Convert lat/lon to UTM (easting, northing, zone_number).
/// Uses a simplified Transverse Mercator — accuracy ~1 m within zone.
pub fn latlon_to_utm_impl(lat: f64, lon: f64) -> (f64, f64, i32, String) {
    let zone_number = (((lon + 180.0) / 6.0).floor() as i32) + 1;
    let zone_letter = utm_zone_letter(lat);

    let latr  = to_rad(lat);
    let lon0r = to_rad((zone_number - 1) as f64 * 6.0 - 180.0 + 3.0);

    let a = 6378137.0_f64;
    let f = 1.0 / 298.257223563;
    let b = a * (1.0 - f);
    let e2 = (a * a - b * b) / (a * a);
    let _n  = (a - b) / (a + b);

    let nu = a / (1.0 - e2 * latr.sin().powi(2)).sqrt();
    let k0 = 0.9996;

    let t  = latr.tan();
    let c  = e2 / (1.0 - e2) * latr.cos().powi(2);
    let aa = latr.cos() * (lon0r - to_rad(lon)).sin();  // note: lon-lon0

    // Meridional arc
    let e2_ = e2;
    let m_a  = 1.0 - e2_ / 4.0 - 3.0 * e2_ * e2_ / 64.0 - 5.0 * e2_.powi(3) / 256.0;
    let m_b  = 3.0 * e2_ / 8.0 + 3.0 * e2_ * e2_ / 32.0 + 45.0 * e2_.powi(3) / 1024.0;
    let m_c  = 15.0 * e2_ * e2_ / 256.0 + 45.0 * e2_.powi(3) / 1024.0;
    let m_d  = 35.0 * e2_.powi(3) / 3072.0;
    let m    = a * (m_a * latr - m_b * (2.0 * latr).sin() + m_c * (4.0 * latr).sin() - m_d * (6.0 * latr).sin());

    let easting = k0 * nu * (aa
        + (1.0 - t * t + c) * aa.powi(3) / 6.0
        + (5.0 - 18.0 * t * t + t.powi(4) + 72.0 * c - 58.0 * e2 / (1.0 - e2)) * aa.powi(5) / 120.0)
        + 500_000.0;

    let mut northing = k0 * (m + nu * latr.tan() * (aa * aa / 2.0
        + (5.0 - t * t + 9.0 * c + 4.0 * c * c) * aa.powi(4) / 24.0
        + (61.0 - 58.0 * t * t + t.powi(4) + 600.0 * c - 330.0 * e2 / (1.0 - e2)) * aa.powi(6) / 720.0));

    if lat < 0.0 {
        northing += 10_000_000.0;
    }

    (easting, northing, zone_number, zone_letter)
}

fn utm_zone_letter(lat: f64) -> String {
    let letters = "CDEFGHJKLMNPQRSTUVWXX";
    let idx = ((lat + 80.0) / 8.0).floor() as usize;
    let idx = idx.min(20);
    letters.chars().nth(idx).unwrap_or('Z').to_string()
}

/// Great-circle polygon area in km² (shoelace on sphere).
pub fn polygon_area_impl(coords: &[(f64, f64)]) -> f64 {
    if coords.len() < 3 { return 0.0; }
    let n = coords.len();
    let mut area = 0.0_f64;
    for i in 0..n {
        let j = (i + 1) % n;
        let (lat1, lon1) = coords[i];
        let (lat2, lon2) = coords[j];
        area += to_rad(lon2 - lon1) * (2.0 + to_rad(lat1).sin() + to_rad(lat2).sin());
    }
    (area * EARTH_RADIUS_KM * EARTH_RADIUS_KM / 2.0).abs()
}

/// Batch haversine: compute distances from one origin to many points.
/// Returns Vec of distances in km.
pub fn batch_haversine_impl(
    origin_lat: f64, origin_lon: f64,
    points: &[(f64, f64)],
) -> Vec<f64> {
    points.iter()
        .map(|(lat, lon)| haversine_distance_impl(origin_lat, origin_lon, *lat, *lon))
        .collect()
}

// ── PyO3 wrappers ─────────────────────────────────────────────────────────────

#[pyfunction]
fn haversine_distance(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> f64 {
    haversine_distance_impl(lat1, lon1, lat2, lon2)
}

#[pyfunction]
fn bearing(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> f64 {
    bearing_impl(lat1, lon1, lat2, lon2)
}

#[pyfunction]
fn destination_point(lat: f64, lon: f64, bearing_deg: f64, distance_km: f64) -> (f64, f64) {
    destination_point_impl(lat, lon, bearing_deg, distance_km)
}

#[pyfunction]
fn midpoint(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> (f64, f64) {
    midpoint_impl(lat1, lon1, lat2, lon2)
}

#[pyfunction]
fn cross_track_distance(
    lat1: f64, lon1: f64,
    lat2: f64, lon2: f64,
    lat3: f64, lon3: f64,
) -> f64 {
    cross_track_distance_impl(lat1, lon1, lat2, lon2, lat3, lon3)
}

#[pyfunction]
fn along_track_distance(
    lat1: f64, lon1: f64,
    lat2: f64, lon2: f64,
    lat3: f64, lon3: f64,
) -> f64 {
    along_track_distance_impl(lat1, lon1, lat2, lon2, lat3, lon3)
}

#[pyfunction]
fn bounding_box(lat: f64, lon: f64, radius_km: f64) -> (f64, f64, f64, f64) {
    bounding_box_impl(lat, lon, radius_km)
}

#[pyfunction]
fn dd_to_dms(dd: f64) -> (i32, i32, f64) {
    dd_to_dms_impl(dd)
}

#[pyfunction]
fn dms_to_dd(degrees: i32, minutes: i32, seconds: f64, direction: i32) -> f64 {
    dms_to_dd_impl(degrees, minutes, seconds, direction)
}

#[pyfunction]
fn latlon_to_utm(lat: f64, lon: f64) -> (f64, f64, i32, String) {
    latlon_to_utm_impl(lat, lon)
}

#[pyfunction]
fn polygon_area(coords: Vec<(f64, f64)>) -> f64 {
    polygon_area_impl(&coords)
}

#[pyfunction]
fn batch_haversine(origin_lat: f64, origin_lon: f64, points: Vec<(f64, f64)>) -> Vec<f64> {
    batch_haversine_impl(origin_lat, origin_lon, &points)
}

/// Register all coord functions into the parent module as a sub-module.
pub fn register(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    let m = PyModule::new(parent.py(), "coords")?;
    m.add_function(wrap_pyfunction!(haversine_distance, &m)?)?;
    m.add_function(wrap_pyfunction!(bearing, &m)?)?;
    m.add_function(wrap_pyfunction!(destination_point, &m)?)?;
    m.add_function(wrap_pyfunction!(midpoint, &m)?)?;
    m.add_function(wrap_pyfunction!(cross_track_distance, &m)?)?;
    m.add_function(wrap_pyfunction!(along_track_distance, &m)?)?;
    m.add_function(wrap_pyfunction!(bounding_box, &m)?)?;
    m.add_function(wrap_pyfunction!(dd_to_dms, &m)?)?;
    m.add_function(wrap_pyfunction!(dms_to_dd, &m)?)?;
    m.add_function(wrap_pyfunction!(latlon_to_utm, &m)?)?;
    m.add_function(wrap_pyfunction!(polygon_area, &m)?)?;
    m.add_function(wrap_pyfunction!(batch_haversine, &m)?)?;
    parent.add_submodule(&m)?;
    Ok(())
}
