"""
geoint.export — Maps, reports, and file exports from any module.
Pure Python: Folium, Jinja2, geopandas.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional, Any

from geoint._types import GeoResult, CandidateLocation, LatLon

logger = logging.getLogger("geoint.export")

# ── Folium interactive map ─────────────────────────────────────────────────────

def interactive_map(
    result: GeoResult,
    output_path: str = "geoint_map.html",
    tiles: str = "OpenStreetMap",
) -> str:
    """
    Build a layered Folium HTML map from a GeoResult.
    Includes: candidate locations, clue markers, and lat-band overlays.
    """
    try:
        import folium
        from folium.plugins import MarkerCluster
    except ImportError:
        raise ImportError("folium required: pip install folium")

    # Determine centre
    if result.candidate_coordinates:
        best = result.best_location
        center = [best.location.lat, best.location.lon] if best else [0, 0]
        zoom   = 6
    else:
        center = [20, 0]
        zoom   = 2

    m = folium.Map(location=center, zoom_start=zoom, tiles=tiles)

    # ── Candidate location markers ────────────────────────────────────────────
    if result.candidate_coordinates:
        cluster = MarkerCluster(name="Candidate Locations").add_to(m)
        for i, cand in enumerate(result.candidate_coordinates):
            color = "red" if i == 0 else "orange" if i < 3 else "gray"
            popup_html = (
                f"<b>Candidate #{i+1}</b><br>"
                f"Lat: {cand.location.lat:.5f}<br>"
                f"Lon: {cand.location.lon:.5f}<br>"
                f"Confidence: {cand.confidence:.0%}<br>"
                f"Sources: {', '.join(cand.source_modules)}"
            )
            folium.Marker(
                [cand.location.lat, cand.location.lon],
                popup=folium.Popup(popup_html, max_width=300),
                icon=folium.Icon(color=color, icon="map-marker"),
                tooltip=f"#{i+1} ({cand.confidence:.0%})",
            ).add_to(cluster)

    # ── Clue markers ──────────────────────────────────────────────────────────
    clue_group = folium.FeatureGroup(name="Clues", show=False)
    for clue in result.clues:
        # Only plot clues that have coordinate-like values
        loc = getattr(clue.narrows_to, "lat", None)
        if loc is not None:
            folium.CircleMarker(
                [clue.narrows_to.lat, clue.narrows_to.lon],
                radius=8,
                color="blue",
                fill=True,
                popup=f"<b>{clue.source}:{clue.clue_type}</b><br>{clue.value}",
                tooltip=f"{clue.clue_type}: {clue.confidence:.0%}",
            ).add_to(clue_group)
    clue_group.add_to(m)

    # ── Layer control ──────────────────────────────────────────────────────────
    folium.LayerControl().add_to(m)

    m.save(output_path)
    logger.info(f"Interactive map → {output_path}")
    return output_path


def map_from_geojson(
    geojson_data: dict,
    output_path: str = "map.html",
    color: str = "blue",
    tooltip_property: Optional[str] = None,
) -> str:
    """Render any GeoJSON FeatureCollection as an interactive Folium map."""
    try:
        import folium
    except ImportError:
        raise ImportError("folium required: pip install folium")

    m = folium.Map(location=[20, 0], zoom_start=3)
    folium.GeoJson(
        geojson_data,
        style_function=lambda f: {"color": color, "weight": 2, "fillOpacity": 0.1},
        tooltip=folium.GeoJsonTooltip(
            fields=[tooltip_property] if tooltip_property else [],
            aliases=[tooltip_property] if tooltip_property else [],
        ) if tooltip_property else None,
    ).add_to(m)

    # Fit bounds
    try:
        import json as _json
        coords = []
        for feat in geojson_data.get("features", []):
            geom = feat.get("geometry", {})
            if geom.get("type") == "Point":
                coords.append(geom["coordinates"])
        if coords:
            lats = [c[1] for c in coords]
            lons = [c[0] for c in coords]
            m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
    except Exception:
        pass

    m.save(output_path)
    return output_path


# ── File exports ──────────────────────────────────────────────────────────────

def to_geojson(result: GeoResult, output_path: str = "result.geojson") -> str:
    """Export candidates and clues as a GeoJSON FeatureCollection."""
    features = []

    for i, cand in enumerate(result.candidate_coordinates):
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [cand.location.lon, cand.location.lat],
            },
            "properties": {
                "rank":       i + 1,
                "confidence": cand.confidence,
                "sources":    cand.source_modules,
                "country":    cand.country_hint,
                "notes":      cand.notes,
            },
        })

    fc = {"type": "FeatureCollection", "features": features}
    with open(output_path, "w") as f:
        json.dump(fc, f, indent=2)
    logger.info(f"GeoJSON → {output_path}")
    return output_path


def to_csv(result: GeoResult, output_path: str = "result.csv") -> str:
    """Export candidate locations as CSV."""
    with open(output_path, "w") as f:
        f.write("rank,lat,lon,confidence,country,sources,notes\n")
        for i, cand in enumerate(result.candidate_coordinates):
            sources = "|".join(cand.source_modules)
            f.write(f"{i+1},{cand.location.lat},{cand.location.lon},"
                    f"{cand.confidence:.3f},{cand.country_hint or ''},"
                    f"{sources},{cand.notes}\n")
    logger.info(f"CSV → {output_path}")
    return output_path


def to_kml(result: GeoResult, output_path: str = "result.kml") -> str:
    """Export candidate locations as KML."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "<Document>",
        f"  <name>geoint Analysis</name>",
    ]
    for i, cand in enumerate(result.candidate_coordinates):
        lines += [
            "  <Placemark>",
            f"    <name>Candidate #{i+1} ({cand.confidence:.0%})</name>",
            f"    <description>Sources: {', '.join(cand.source_modules)}</description>",
            "    <Point>",
            f"      <coordinates>{cand.location.lon},{cand.location.lat},0</coordinates>",
            "    </Point>",
            "  </Placemark>",
        ]
    lines += ["</Document>", "</kml>"]
    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    logger.info(f"KML → {output_path}")
    return output_path


def to_gpx(result: GeoResult, output_path: str = "result.gpx") -> str:
    """Export candidate locations as GPX waypoints."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">',
    ]
    for i, cand in enumerate(result.candidate_coordinates):
        lines.append(
            f'<wpt lat="{cand.location.lat}" lon="{cand.location.lon}">'
            f'<name>Candidate_{i+1}</name>'
            f'<desc>{cand.confidence:.0%} confidence</desc>'
            f'</wpt>'
        )
    lines.append("</gpx>")
    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    logger.info(f"GPX → {output_path}")
    return output_path


# ── HTML / Markdown report ────────────────────────────────────────────────────

_REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>geoint Analysis Report</title>
<style>
  body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:1rem;background:#f9f9f9;color:#222}
  h1{color:#1a3a5c}h2{color:#2a5a8c;border-bottom:1px solid #ccc}
  table{border-collapse:collapse;width:100%}
  th,td{text-align:left;padding:.5rem .75rem;border-bottom:1px solid #ddd}
  th{background:#e8f0fe}
  .badge{display:inline-block;padding:.2rem .6rem;border-radius:999px;font-size:.8rem;font-weight:600}
  .high{background:#d4edda;color:#155724}.med{background:#fff3cd;color:#856404}
  .low{background:#f8d7da;color:#721c24}
  .clue-source{font-variant:small-caps;color:#555}
  pre{background:#eee;padding:1rem;border-radius:4px;overflow-x:auto;font-size:.85rem}
</style>
</head>
<body>
<h1>🔍 geoint Analysis Report</h1>
<p><b>Input:</b> {input_path} &nbsp;|&nbsp; <b>Type:</b> {input_type}</p>

<h2>Top Candidates</h2>
<table>
  <tr><th>#</th><th>Coordinates</th><th>Confidence</th><th>Country</th><th>Sources</th></tr>
  {candidate_rows}
</table>

{country_section}

<h2>Evidence Chain</h2>
<ol>
  {reasoning_items}
</ol>

<h2>Detected Clues ({n_clues})</h2>
<table>
  <tr><th>Source</th><th>Type</th><th>Value</th><th>Confidence</th><th>Notes</th></tr>
  {clue_rows}
</table>

<h2>Summary</h2>
<pre>{summary}</pre>

<hr><p style="color:#888;font-size:.8rem">Generated by geoint v0.2 · github.com/yourusername/geoint</p>
</body></html>"""


def html_report(result: GeoResult, output_path: str = "geoint_report.html") -> str:
    """Generate a standalone HTML intelligence summary report."""

    def conf_badge(c):
        cls = "high" if c >= 0.7 else "med" if c >= 0.4 else "low"
        return f'<span class="badge {cls}">{c:.0%}</span>'

    # Candidate rows
    cand_rows = ""
    for i, cand in enumerate(result.candidate_coordinates[:10]):
        lat, lon = cand.location.lat, cand.location.lon
        cand_rows += (
            f"<tr><td>{i+1}</td>"
            f"<td>{lat:.5f}, {lon:.5f}</td>"
            f"<td>{conf_badge(cand.confidence)}</td>"
            f"<td>{cand.country_hint or '—'}</td>"
            f"<td>{', '.join(cand.source_modules)}</td></tr>\n"
        )

    # Countries
    country_section = ""
    if result.candidate_countries:
        rows = "".join(
            f"<tr><td>{c}</td><td>{conf_badge(p)}</td></tr>"
            for c, p in sorted(result.candidate_countries, key=lambda x: -x[1])[:5]
        )
        country_section = f"<h2>Candidate Countries</h2><table><tr><th>Country</th><th>Probability</th></tr>{rows}</table>"

    reasoning_items = "".join(f"<li>{step}</li>\n" for step in result.reasoning_chain)

    clue_rows = ""
    for clue in result.clues:
        clue_rows += (
            f"<tr>"
            f"<td><span class='clue-source'>{clue.source}</span></td>"
            f"<td>{clue.clue_type}</td>"
            f"<td>{clue.value}</td>"
            f"<td>{conf_badge(clue.confidence)}</td>"
            f"<td>{clue.notes}</td>"
            f"</tr>\n"
        )

    html = _REPORT_TEMPLATE.format(
        input_path=result.input_path or "—",
        input_type=result.input_type,
        candidate_rows=cand_rows or "<tr><td colspan='5'>No candidates found.</td></tr>",
        country_section=country_section,
        reasoning_items=reasoning_items or "<li>No reasoning steps recorded.</li>",
        clue_rows=clue_rows or "<tr><td colspan='5'>No clues detected.</td></tr>",
        n_clues=len(result.clues),
        summary=result.summary or "No summary generated.",
    )

    with open(output_path, "w") as f:
        f.write(html)
    logger.info(f"HTML report → {output_path}")
    return output_path


def markdown_report(result: GeoResult, output_path: str = "geoint_report.md") -> str:
    """Generate a Markdown intelligence summary."""
    lines = [
        "# geoint Analysis Report",
        f"\n**Input:** `{result.input_path or '—'}` | **Type:** {result.input_type}",
        "\n## Top Candidates\n",
        "| # | Coordinates | Confidence | Country | Sources |",
        "|---|-------------|------------|---------|---------|",
    ]
    for i, cand in enumerate(result.candidate_coordinates[:5]):
        lines.append(
            f"| {i+1} | {cand.location.lat:.5f}, {cand.location.lon:.5f} "
            f"| {cand.confidence:.0%} | {cand.country_hint or '—'} "
            f"| {', '.join(cand.source_modules)} |"
        )

    if result.candidate_countries:
        lines += ["\n## Candidate Countries\n", "| Country | Probability |", "|---------|-------------|"]
        for c, p in sorted(result.candidate_countries, key=lambda x: -x[1])[:5]:
            lines.append(f"| {c} | {p:.0%} |")

    lines += ["\n## Reasoning Chain\n"]
    for i, step in enumerate(result.reasoning_chain, 1):
        lines.append(f"{i}. {step}")

    lines += ["\n## Detected Clues\n", "| Source | Type | Value | Confidence |", "|--------|------|-------|------------|"]
    for clue in result.clues:
        lines.append(f"| {clue.source} | {clue.clue_type} | {clue.value} | {clue.confidence:.0%} |")

    if result.summary:
        lines += ["\n## Summary\n", f"```\n{result.summary}\n```"]

    content = "\n".join(lines)
    with open(output_path, "w") as f:
        f.write(content)
    logger.info(f"Markdown report → {output_path}")
    return output_path


# ── Quick-export helper ────────────────────────────────────────────────────────

def export_all(
    result: GeoResult,
    output_dir: str = ".",
    prefix: str = "geoint",
) -> dict[str, str]:
    """
    Export a GeoResult to all formats: HTML report, GeoJSON, KML, GPX, and map.
    Returns a dict of {format: path}.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}

    paths["report"]  = html_report(result, str(out / f"{prefix}_report.html"))
    paths["geojson"] = to_geojson(result, str(out / f"{prefix}.geojson"))
    paths["kml"]     = to_kml(result,     str(out / f"{prefix}.kml"))
    paths["gpx"]     = to_gpx(result,     str(out / f"{prefix}.gpx"))
    paths["map"]     = interactive_map(result, str(out / f"{prefix}_map.html"))
    paths["markdown"]= markdown_report(result, str(out / f"{prefix}_report.md"))

    result.map_html_path  = paths["map"]
    result.report_path    = paths["report"]
    result.geojson_path   = paths["geojson"]

    return paths
