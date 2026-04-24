use pyo3::prelude::*;

pub mod coords;
pub mod solar;
pub mod terrain;
pub mod sar;
pub mod raster;

/// _rustcore — Rust-accelerated backend for the geoint library.
///
/// Exposes five sub-modules:
///   _rustcore.coords   – coordinate math and projections
///   _rustcore.solar    – solar / shadow geometry
///   _rustcore.terrain  – DEM raster analysis
///   _rustcore.sar      – search-and-rescue grid generation
///   _rustcore.raster   – generic raster / pixel math
#[pymodule]
fn _rustcore(m: &Bound<'_, PyModule>) -> PyResult<()> {
    coords::register(m)?;
    solar::register(m)?;
    terrain::register(m)?;
    sar::register(m)?;
    raster::register(m)?;

    m.add("__version__", "0.1.0")?;
    m.add("__doc__", "Rust-accelerated GEOINT computation core")?;
    Ok(())
}
