"""
pygeospy CLI — command-line interface built with Typer.

Usage examples
--------------
  pygeospy analyze photo.jpg
  pygeospy analyze photo.jpg --shadow-ratio 2.5 --shadow-azimuth 195 --export
  pygeospy analyze --ip 8.8.8.8
  pygeospy solar --lat 51.5 --lon -0.1 --doy 172 --hour 14
  pygeospy coords haversine 51.5 -0.1 48.85 2.35
  pygeospy exif photo.jpg
  pygeospy sar grid --lat 47.6 --lon -122.3 --radius 3.0 --cell 0.5
  pygeospy cache clear
  pygeospy info
"""
from __future__ import annotations

import sys
from typing import Optional

try:
    import typer
    from rich.console import Console
    from rich.table import Table
    _TYPER_OK = True
except ImportError:
    _TYPER_OK = False
    print("typer and rich are required for the CLI: pip install typer rich", file=sys.stderr)
    sys.exit(1)

app     = typer.Typer(help="pygeospy — GEOINT/OSINT analysis toolkit", pretty_exceptions_show_locals=False)
console = Console()

# ── Sub-command groups ────────────────────────────────────────────────────────

coords_app = typer.Typer(help="Coordinate math and conversions")
solar_app  = typer.Typer(help="Solar analysis")
exif_app   = typer.Typer(help="EXIF metadata extraction")
sar_app    = typer.Typer(help="Search and rescue grid generation")
cache_app  = typer.Typer(help="Cache management")

app.add_typer(coords_app, name="coords")
app.add_typer(solar_app,  name="solar")
app.add_typer(exif_app,   name="exif")
app.add_typer(sar_app,    name="sar")
app.add_typer(cache_app,  name="cache")


# ── analyze (main command) ────────────────────────────────────────────────────

@app.command("analyze")
def analyze(
    input_path: Optional[str]  = typer.Argument(None, help="Image, audio, IP, or text path"),
    ip:         Optional[str]  = typer.Option(None,   "--ip",             help="Analyze an IP address"),
    shadow_ratio:   Optional[float] = typer.Option(None, "--shadow-ratio",   "-sr", help="Shadow length / object height"),
    shadow_azimuth: Optional[float] = typer.Option(None, "--shadow-azimuth", "-sa", help="Shadow azimuth (degrees, 0=N)"),
    vision_backend: str             = typer.Option("none", "--vision",        help="Vision backend: none/claude/gpt4v/llava"),
    export:     bool            = typer.Option(False, "--export",          help="Export all formats"),
    output_dir: str             = typer.Option("pygeospy_output", "--out",   help="Output directory for exports"),
    parallel:   bool            = typer.Option(True,  "--parallel/--serial", help="Parallel module execution"),
    quiet:      bool            = typer.Option(False, "--quiet", "-q",     help="Suppress output except results"),
):
    """
    Analyze an image, audio file, IP, or text and produce a GeoResult.
    """
    from pygeospy.pipeline import analyze as _analyze

    target = ip or input_path
    if not target:
        console.print("[red]Error: provide an input path or --ip address[/red]")
        raise typer.Exit(1)

    if not quiet:
        console.print(f"[bold cyan]pygeospy analyze[/bold cyan] → [yellow]{target}[/yellow]")

    result = _analyze(
        target,
        shadow_ratio=shadow_ratio,
        shadow_azimuth=shadow_azimuth,
        vision_backend=vision_backend,
        parallel=parallel,
        output_dir=output_dir if export else None,
        export=export,
    )

    # Print summary
    console.rule("[bold]Results[/bold]")
    console.print(f"[bold]Summary:[/bold] {result.summary}")

    if result.candidate_coordinates:
        t = Table(title="Candidate Locations", show_header=True)
        t.add_column("#",          style="cyan",  width=4)
        t.add_column("Latitude",   style="green")
        t.add_column("Longitude",  style="green")
        t.add_column("Confidence", style="yellow")
        t.add_column("Sources")
        t.add_column("Country")
        for i, c in enumerate(result.candidate_coordinates[:5]):
            t.add_row(
                str(i+1),
                f"{c.location.lat:.5f}",
                f"{c.location.lon:.5f}",
                f"{c.confidence:.0%}",
                ", ".join(c.source_modules),
                c.country_hint or "—",
            )
        console.print(t)

    if result.candidate_countries:
        t2 = Table(title="Candidate Countries", show_header=True)
        t2.add_column("Country",     style="green")
        t2.add_column("Probability", style="yellow")
        for country, prob in result.candidate_countries[:5]:
            t2.add_row(country, f"{prob:.0%}")
        console.print(t2)

    if result.clues and not quiet:
        console.print(f"\n[dim]Detected {len(result.clues)} clues. "
                      f"Reasoning steps: {len(result.reasoning_chain)}[/dim]")

    if export:
        console.print(f"\n[green]Exports saved to:[/green] {output_dir}/")
        if result.map_html_path:
            console.print(f"  Map:    {result.map_html_path}")
        if result.report_path:
            console.print(f"  Report: {result.report_path}")


# ── coords sub-commands ───────────────────────────────────────────────────────

@coords_app.command("haversine", context_settings={"ignore_unknown_options": True})
def coords_haversine(
    lat1: float = typer.Argument(...), lon1: float = typer.Argument(...),
    lat2: float = typer.Argument(...), lon2: float = typer.Argument(...),
):
    """Haversine distance between two coordinates (km)."""
    from pygeospy.coords import haversine
    d = haversine(lat1, lon1, lat2, lon2)
    console.print(f"Distance: [bold]{d:.3f} km[/bold] ({d*0.621371:.3f} miles)")


@coords_app.command("bearing", context_settings={"ignore_unknown_options": True})
def coords_bearing(
    lat1: float = typer.Argument(...), lon1: float = typer.Argument(...),
    lat2: float = typer.Argument(...), lon2: float = typer.Argument(...),
):
    """Initial bearing from point 1 → point 2."""
    from pygeospy.coords import bearing
    from pygeospy._utils import bearing_to_cardinal
    b = bearing(lat1, lon1, lat2, lon2)
    console.print(f"Bearing: [bold]{b:.2f}°[/bold] ({bearing_to_cardinal(b)})")


@coords_app.command("convert", context_settings={"ignore_unknown_options": True})
def coords_convert(
    lat: float = typer.Argument(...), lon: float = typer.Argument(...),
    fmt: str   = typer.Option("all", "--fmt", help="dd / dms / utm / mgrs / plus"),
):
    """Convert coordinates to different formats."""
    from pygeospy import coords
    fmts = ["dd", "dms", "utm", "mgrs"] if fmt == "all" else [fmt]
    for f in fmts:
        try:
            console.print(f"[cyan]{f.upper()}:[/cyan] {coords.format(lat, lon, f)}")
        except Exception as e:
            console.print(f"[yellow]{f.upper()}:[/yellow] {e}")


@coords_app.command("bbox", context_settings={"ignore_unknown_options": True})
def coords_bbox(
    lat: float = typer.Argument(...), lon: float = typer.Argument(...),
    radius: float = typer.Argument(..., help="Radius in km"),
):
    """Bounding box around a centre point."""
    from pygeospy.coords import bounding_box
    bb = bounding_box(lat, lon, radius)
    console.print(f"SW: {bb.min_lat:.5f}, {bb.min_lon:.5f}")
    console.print(f"NE: {bb.max_lat:.5f}, {bb.max_lon:.5f}")


# ── solar sub-commands ────────────────────────────────────────────────────────

@solar_app.command("position", context_settings={"ignore_unknown_options": True})
def solar_position(
    lat:  float = typer.Argument(...),
    lon:  float = typer.Argument(...),
    doy:  int   = typer.Argument(..., help="Day of year (1-365)"),
    hour: float = typer.Argument(..., help="UTC hour (0-24)"),
):
    """Calculate sun position at a location and time."""
    from pygeospy.solar import solar_elevation, solar_azimuth, shadow_azimuth, shadow_length_ratio
    from pygeospy._utils import bearing_to_cardinal
    el  = solar_elevation(lat, lon, doy, hour)
    az  = solar_azimuth(lat, lon, doy, hour)
    sh_az = shadow_azimuth(az)
    ratio = shadow_length_ratio(el)
    console.print(f"[cyan]Sun elevation:[/cyan]  {el:.2f}°")
    console.print(f"[cyan]Sun azimuth:[/cyan]    {az:.2f}° ({bearing_to_cardinal(az)})")
    console.print(f"[cyan]Shadow azimuth:[/cyan] {sh_az:.2f}° ({bearing_to_cardinal(sh_az)})")
    console.print(f"[cyan]Shadow ratio:[/cyan]   {ratio:.3f} × object height")


@solar_app.command("from-shadow", context_settings={"ignore_unknown_options": True})
def solar_from_shadow(
    ratio:   float = typer.Argument(..., help="Shadow length / object height"),
    azimuth: float = typer.Argument(..., help="Shadow azimuth (degrees, 0=N)"),
    doy:     int   = typer.Option(172, "--doy", help="Day-of-year hint"),
    hour:    float = typer.Option(12.0, "--hour", help="UTC hour hint"),
):
    """Infer latitude bands from shadow ratio and azimuth."""
    from pygeospy.solar import latitude_band_from_shadow
    solar = latitude_band_from_shadow(ratio, azimuth, doy, hour)
    console.print(f"Sun elevation: {solar.sun_elevation:.2f}°")
    console.print(f"Sun azimuth:   {solar.sun_azimuth:.2f}°")
    console.print(f"Season:        {solar.estimated_season}")
    console.print(f"Hemisphere:    {solar.hemisphere_hint or 'unknown'}")
    if solar.candidate_lat_bands:
        console.print(f"Candidate latitude bands ({len(solar.candidate_lat_bands)}):")
        for lo, hi in solar.candidate_lat_bands:
            console.print(f"  {lo:.1f}° to {hi:.1f}°")
    else:
        console.print("[yellow]No candidate latitude bands found[/yellow]")


# ── exif sub-commands ─────────────────────────────────────────────────────────

@exif_app.command("extract")
def exif_extract(
    image: str   = typer.Argument(..., help="Image file path"),
    json_out: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Extract EXIF metadata from an image."""
    from pygeospy.exif import extract, forensic_flags
    import json
    r = extract(image)
    if json_out:
        console.print(json.dumps(r.raw_exif, indent=2, default=str))
        return
    console.print(f"[cyan]GPS:[/cyan]        {'YES' if r.has_gps else 'NO'}")
    if r.coordinates:
        console.print(f"[cyan]Coordinates:[/cyan] {r.coordinates.lat:.5f}, {r.coordinates.lon:.5f}")
    console.print(f"[cyan]Camera:[/cyan]     {r.camera_make or '—'} {r.camera_model or ''}")
    console.print(f"[cyan]Timestamp:[/cyan]  {r.timestamp or '—'}")
    console.print(f"[cyan]Lens:[/cyan]       {r.lens or '—'}")
    flags = forensic_flags(r)
    if flags:
        console.print("\n[yellow]⚠ Forensic flags:[/yellow]")
        for f in flags:
            console.print(f"  • {f}")


@exif_app.command("batch")
def exif_batch(
    directory: str = typer.Argument(..., help="Directory to scan"),
    output:    str = typer.Option("exif_batch.csv", "--out", help="CSV output path"),
    map_out:   str = typer.Option("", "--map", help="HTML map output (optional)"),
):
    """Batch extract EXIF from all images in a directory."""
    from pygeospy.exif import batch_extract, map_gps_points
    results = batch_extract(directory)
    with_gps = [r for r in results if r.get("has_gps")]
    console.print(f"Processed {len(results)} images, {len(with_gps)} have GPS.")
    import csv
    with open(output, "w", newline="", encoding="utf-8") as f:
        if results:
            w = csv.DictWriter(f, fieldnames=results[0].keys())
            w.writeheader(); w.writerows(results)
    console.print(f"CSV saved: {output}")
    if map_out and with_gps:
        map_gps_points(results, map_out)
        console.print(f"Map saved: {map_out}")


# ── SAR sub-commands ──────────────────────────────────────────────────────────

@sar_app.command("grid")
def sar_grid(
    lat:    float = typer.Option(..., "--lat",    help="IPP latitude"),
    lon:    float = typer.Option(..., "--lon",    help="IPP longitude"),
    radius: float = typer.Option(2.0, "--radius", help="Search radius (km)"),
    cell:   float = typer.Option(0.5, "--cell",   help="Cell size (km)"),
    out:    str   = typer.Option("sar_grid.geojson", "--out"),
    gpx:    str   = typer.Option("", "--gpx", help="Also export GPX"),
):
    """Generate a NASAR search grid."""
    from pygeospy.sar import search_grid, to_geojson, grid_to_gpx
    features = search_grid(lat, lon, radius, cell)
    to_geojson(features, out)
    console.print(f"[green]Grid saved:[/green] {out} ({len(features)} cells)")
    if gpx:
        grid_to_gpx(features, gpx)
        console.print(f"[green]GPX saved:[/green]  {gpx}")


@sar_app.command("urgency")
def sar_urgency(
    age:     int   = typer.Option(...,   "--age",     help="Subject age"),
    medical: bool  = typer.Option(False, "--medical", help="Known medical condition"),
    hours:   float = typer.Option(4.0,   "--hours",   help="Hours since last seen"),
    night:   bool  = typer.Option(False, "--night",   help="After dark"),
    weather: bool  = typer.Option(False, "--weather", help="Adverse weather"),
    terrain: bool  = typer.Option(False, "--terrain", help="Difficult terrain"),
):
    """Calculate SAR urgency score."""
    from pygeospy.sar import urgency_score
    score = urgency_score(age, medical, hours, night, weather, terrain)
    color = "red" if score["score"] >= 6 else "yellow" if score["score"] >= 4 else "green"
    console.print(f"Urgency score: [{color}]{score['score']}/10[/{color}] — {score['priority']}")


# ── cache sub-commands ────────────────────────────────────────────────────────

@cache_app.command("stats")
def cache_stats():
    """Show disk cache statistics."""
    from pygeospy._cache import get_cache
    namespaces = ["elevation", "geocode", "reverse_geo", "ip_geo", "osm_features",
                  "osm_bbox", "osm_boundary", "dem", "timezone", "sentinel_products"]
    t = Table(title="Cache Statistics")
    t.add_column("Namespace"); t.add_column("Entries"); t.add_column("Size")
    for ns in namespaces:
        c = get_cache(ns)
        s = c.stats()
        t.add_row(ns, str(s["entries"]), f"{s['size_bytes']//1024} KB")
    console.print(t)


@cache_app.command("clear")
def cache_clear(namespace: Optional[str] = typer.Argument(None, help="Namespace to clear (all if omitted)")):
    """Clear cached API responses."""
    from pygeospy._cache import get_cache
    namespaces = [namespace] if namespace else [
        "elevation", "geocode", "reverse_geo", "ip_geo", "osm_features",
        "osm_bbox", "osm_boundary", "dem", "timezone", "sentinel_products",
    ]
    total = 0
    for ns in namespaces:
        total += get_cache(ns).clear()
    console.print(f"[green]Cleared {total} cache entries.[/green]")


# ── info command ──────────────────────────────────────────────────────────────

@app.command("info")
def info():
    """Show pygeospy version and Rust core status."""
    import pygeospy
    from pygeospy._utils import RUST_AVAILABLE
    console.print(f"[bold]pygeospy[/bold] v{pygeospy.__version__}")
    status = "[green]✓ available[/green]" if RUST_AVAILABLE else "[yellow]✗ not compiled[/yellow]"
    console.print(f"Rust core (_rustcore): {status}")
    if not RUST_AVAILABLE:
        console.print("[dim]Run `maturin develop --release` inside _rustcore/ to build.[/dim]")


def main():
    app()


if __name__ == "__main__":
    main()
