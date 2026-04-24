/// solar.rs — Solar geometry and shadow analysis.
/// Pure floating-point math, no I/O.  Called thousands of times during
/// latitude-band sweeps so keeping it in Rust gives a meaningful speedup.

use pyo3::prelude::*;
use std::f64::consts::PI;

const DEG2RAD: f64 = PI / 180.0;
const RAD2DEG: f64 = 180.0 / PI;

#[inline]
fn to_rad(d: f64) -> f64 { d * DEG2RAD }
#[inline]
fn to_deg(r: f64) -> f64 { r * RAD2DEG }

// ── Astronomical helpers ─────────────────────────────────────────────────────

/// Solar declination in degrees for a given Julian day-of-year (1–365).
/// δ = 23.45 × sin(360/365 × (doy − 81))  — peaks +23.45° at summer solstice (~doy 172)
pub fn solar_declination_impl(day_of_year: f64) -> f64 {
    23.45 * to_rad(360.0 / 365.0 * (day_of_year - 81.0)).sin()
}

/// Equation of time (minutes) — difference between apparent and mean solar time.
pub fn equation_of_time_impl(day_of_year: f64) -> f64 {
    let b = to_rad(360.0 / 365.0 * (day_of_year - 81.0));
    9.87 * (2.0 * b).sin() - 7.53 * b.cos() - 1.5 * b.sin()
}

/// Solar hour angle (degrees) from local solar time.
/// `hour_local_solar` is fractional hours (e.g. 13.5 = 13:30 solar time).
pub fn hour_angle_impl(hour_local_solar: f64) -> f64 {
    15.0 * (hour_local_solar - 12.0)
}

/// Local solar time (hours) from UTC hour + longitude + equation-of-time correction.
/// LSTM (Local Standard Time Meridian) is derived from longitude, not from UTC hour.
pub fn local_solar_time_impl(hour_utc: f64, longitude: f64, day_of_year: f64) -> f64 {
    let eot = equation_of_time_impl(day_of_year);
    let lstm = 15.0 * (longitude / 15.0).round(); // nearest 15° meridian
    hour_utc + (4.0 * (longitude - lstm) + eot) / 60.0
}

/// Solar elevation angle (degrees above horizon) for a given lat, lon, day, hour_utc.
pub fn solar_elevation_impl(lat: f64, lon: f64, day_of_year: f64, hour_utc: f64) -> f64 {
    let decl  = to_rad(solar_declination_impl(day_of_year));
    let latr  = to_rad(lat);
    let lst   = local_solar_time_impl(hour_utc, lon, day_of_year);
    let ha    = to_rad(hour_angle_impl(lst));

    let sin_el = latr.sin() * decl.sin()
        + latr.cos() * decl.cos() * ha.cos();
    to_deg(sin_el.asin())
}

/// Solar azimuth (degrees, 0=N, 90=E) for a given lat, lon, day, hour_utc.
pub fn solar_azimuth_impl(lat: f64, lon: f64, day_of_year: f64, hour_utc: f64) -> f64 {
    let decl  = to_rad(solar_declination_impl(day_of_year));
    let latr  = to_rad(lat);
    let lst   = local_solar_time_impl(hour_utc, lon, day_of_year);
    let ha    = to_rad(hour_angle_impl(lst));

    let sin_el  = latr.sin() * decl.sin() + latr.cos() * decl.cos() * ha.cos();
    let el_r    = sin_el.asin();

    let cos_az  = (decl.sin() - latr.sin() * el_r.sin()) / (latr.cos() * el_r.cos());
    let cos_az  = cos_az.clamp(-1.0, 1.0);
    let az_raw  = to_deg(cos_az.acos());

    // Afternoon correction
    if lst > 12.0 { 360.0 - az_raw } else { az_raw }
}

/// Shadow azimuth from sun azimuth (shadows point AWAY from sun).
pub fn shadow_azimuth_impl(sun_azimuth: f64) -> f64 {
    (sun_azimuth + 180.0) % 360.0
}

/// Shadow length ratio (shadow_length / object_height) from sun elevation.
pub fn shadow_length_ratio_impl(sun_elevation_deg: f64) -> f64 {
    if sun_elevation_deg <= 0.0 { return f64::INFINITY; }
    1.0 / to_rad(sun_elevation_deg).tan()
}

/// Sun elevation from shadow length ratio (inverse of above).
pub fn elevation_from_shadow_ratio_impl(shadow_ratio: f64) -> f64 {
    if shadow_ratio <= 0.0 { return 90.0; }
    to_deg((1.0 / shadow_ratio).atan())
}

/// Given a sun elevation and azimuth (and day hint), return candidate latitude band
/// as (min_lat, max_lat).  Uses a brute-force search over latitudes ±90 degrees.
pub fn latitude_band_from_solar_impl(
    sun_elevation: f64,
    sun_azimuth: f64,
    day_of_year: f64,
    hour_utc_hint: f64,
    tolerance_deg: f64,
) -> Vec<(f64, f64)> {
    let mut candidates: Vec<f64> = Vec::new();
    let step = 0.5_f64;
    let mut lat = -89.5_f64;

    while lat <= 89.5 {
        // Test longitudes that put the sun roughly at hour_utc_hint
        // We invert: what longitude gives solar noon at hour_utc_hint?
        // lon = (12 - hour_utc) * 15  (approx, ignoring EoT)
        let lon_est = (12.0 - hour_utc_hint) * 15.0;

        let el  = solar_elevation_impl(lat, lon_est, day_of_year, hour_utc_hint);
        let az  = solar_azimuth_impl(lat, lon_est, day_of_year, hour_utc_hint);

        if (el - sun_elevation).abs() < tolerance_deg
            && (az - sun_azimuth).abs() < tolerance_deg * 2.0
        {
            candidates.push(lat);
        }
        lat += step;
    }

    // Merge contiguous bands
    if candidates.is_empty() { return vec![]; }
    let mut bands: Vec<(f64, f64)> = Vec::new();
    let mut start = candidates[0];
    let mut prev  = candidates[0];

    for &c in &candidates[1..] {
        if c - prev > step * 2.0 {
            bands.push((start, prev));
            start = c;
        }
        prev = c;
    }
    bands.push((start, prev));
    bands
}

/// Sunrise and sunset UTC times for a given lat/lon and day.
/// Returns (sunrise_utc, sunset_utc) in decimal hours.  Returns (NaN, NaN) for
/// polar night / midnight sun.
pub fn sunrise_sunset_impl(lat: f64, lon: f64, day_of_year: f64) -> (f64, f64) {
    let decl  = to_rad(solar_declination_impl(day_of_year));
    let latr  = to_rad(lat);
    let cos_ha = -(latr.tan() * decl.tan());

    if cos_ha < -1.0 { return (f64::NAN, f64::NAN); } // midnight sun
    if cos_ha >  1.0 { return (f64::NAN, f64::NAN); } // polar night

    let ha_deg  = to_deg(cos_ha.acos());
    let lstm    = 15.0 * (lon / 15.0).round();
    let eot     = equation_of_time_impl(day_of_year);
    let noon_utc = 12.0 - (4.0 * (lon - lstm) + eot) / 60.0;

    let half = ha_deg / 15.0;
    (noon_utc - half, noon_utc + half)
}

/// Solar noon UTC for a given longitude and day.
pub fn solar_noon_utc_impl(lon: f64, day_of_year: f64) -> f64 {
    let eot  = equation_of_time_impl(day_of_year);
    let lstm = 15.0 * (lon / 15.0).round();
    12.0 - (4.0 * (lon - lstm) + eot) / 60.0
}

/// Estimate season from shadow ratio and hemisphere.
/// Returns "winter" | "spring/autumn" | "summer".
pub fn season_from_shadow_ratio_impl(shadow_ratio: f64, northern_hemisphere: bool) -> String {
    // Higher shadow ratio = lower sun = winter (in that hemisphere)
    // Approximate: elevation < 30 = winter, 30–60 = spring/autumn, >60 = summer
    let el = elevation_from_shadow_ratio_impl(shadow_ratio);
    let raw = if el < 30.0 {
        "winter"
    } else if el < 60.0 {
        "spring/autumn"
    } else {
        "summer"
    };
    // Flip for southern hemisphere
    if !northern_hemisphere {
        match raw {
            "winter" => "summer".to_string(),
            "summer" => "winter".to_string(),
            other    => other.to_string(),
        }
    } else {
        raw.to_string()
    }
}

/// Sweep of all longitudes: given known lat + elevation, return the UTC hour
/// and longitude pair that matches.
pub fn infer_utc_longitude(
    lat: f64,
    sun_elevation: f64,
    day_of_year: f64,
    tolerance: f64,
) -> Vec<(f64, f64)> {
    let mut results = Vec::new();
    let mut hour = 6.0_f64;
    while hour <= 18.0 {
        let mut lon = -180.0_f64;
        while lon <= 180.0 {
            let el = solar_elevation_impl(lat, lon, day_of_year, hour);
            if (el - sun_elevation).abs() < tolerance {
                results.push((hour, lon));
            }
            lon += 1.0;
        }
        hour += 0.5;
    }
    results
}

// ── PyO3 wrappers ─────────────────────────────────────────────────────────────

#[pyfunction]
fn solar_declination(day_of_year: f64) -> f64 {
    solar_declination_impl(day_of_year)
}

#[pyfunction]
fn equation_of_time(day_of_year: f64) -> f64 {
    equation_of_time_impl(day_of_year)
}

#[pyfunction]
fn local_solar_time(hour_utc: f64, longitude: f64, day_of_year: f64) -> f64 {
    local_solar_time_impl(hour_utc, longitude, day_of_year)
}

#[pyfunction]
fn solar_elevation(lat: f64, lon: f64, day_of_year: f64, hour_utc: f64) -> f64 {
    solar_elevation_impl(lat, lon, day_of_year, hour_utc)
}

#[pyfunction]
fn solar_azimuth(lat: f64, lon: f64, day_of_year: f64, hour_utc: f64) -> f64 {
    solar_azimuth_impl(lat, lon, day_of_year, hour_utc)
}

#[pyfunction]
fn shadow_azimuth(sun_azimuth: f64) -> f64 {
    shadow_azimuth_impl(sun_azimuth)
}

#[pyfunction]
fn shadow_length_ratio(sun_elevation_deg: f64) -> f64 {
    shadow_length_ratio_impl(sun_elevation_deg)
}

#[pyfunction]
fn elevation_from_shadow_ratio(shadow_ratio: f64) -> f64 {
    elevation_from_shadow_ratio_impl(shadow_ratio)
}

#[pyfunction]
fn latitude_band_from_solar(
    sun_elevation: f64,
    sun_azimuth: f64,
    day_of_year: f64,
    hour_utc_hint: f64,
    tolerance_deg: f64,
) -> Vec<(f64, f64)> {
    latitude_band_from_solar_impl(sun_elevation, sun_azimuth, day_of_year, hour_utc_hint, tolerance_deg)
}

#[pyfunction]
fn sunrise_sunset(lat: f64, lon: f64, day_of_year: f64) -> (f64, f64) {
    sunrise_sunset_impl(lat, lon, day_of_year)
}

#[pyfunction]
fn solar_noon_utc(lon: f64, day_of_year: f64) -> f64 {
    solar_noon_utc_impl(lon, day_of_year)
}

#[pyfunction]
fn season_from_shadow_ratio(shadow_ratio: f64, northern_hemisphere: bool) -> String {
    season_from_shadow_ratio_impl(shadow_ratio, northern_hemisphere)
}

#[pyfunction]
fn infer_utc_longitude_py(lat: f64, sun_elevation: f64, day_of_year: f64, tolerance: f64) -> Vec<(f64, f64)> {
    infer_utc_longitude(lat, sun_elevation, day_of_year, tolerance)
}

pub fn register(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    let m = PyModule::new(parent.py(), "solar")?;
    m.add_function(wrap_pyfunction!(solar_declination, &m)?)?;
    m.add_function(wrap_pyfunction!(equation_of_time, &m)?)?;
    m.add_function(wrap_pyfunction!(local_solar_time, &m)?)?;
    m.add_function(wrap_pyfunction!(solar_elevation, &m)?)?;
    m.add_function(wrap_pyfunction!(solar_azimuth, &m)?)?;
    m.add_function(wrap_pyfunction!(shadow_azimuth, &m)?)?;
    m.add_function(wrap_pyfunction!(shadow_length_ratio, &m)?)?;
    m.add_function(wrap_pyfunction!(elevation_from_shadow_ratio, &m)?)?;
    m.add_function(wrap_pyfunction!(latitude_band_from_solar, &m)?)?;
    m.add_function(wrap_pyfunction!(sunrise_sunset, &m)?)?;
    m.add_function(wrap_pyfunction!(solar_noon_utc, &m)?)?;
    m.add_function(wrap_pyfunction!(season_from_shadow_ratio, &m)?)?;
    m.add_function(wrap_pyfunction!(infer_utc_longitude_py, &m)?)?;
    parent.add_submodule(&m)?;
    Ok(())
}
