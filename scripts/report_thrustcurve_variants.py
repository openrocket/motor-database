import argparse
import base64
import hashlib
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET

import requests


MOTORS_METADATA_FILE = "data/thrustcurve.org/motors_metadata.json"
OUTPUT_FILE = "reports/thrustcurve_variants_report.html"
TC_API_DOWNLOAD = "https://www.thrustcurve.org/api/v1/download.json"
TC_BASE_URL = "https://www.thrustcurve.org"

HEADERS = {
    "User-Agent": "OpenRocket-VariantReport/1.0",
    "Content-Type": "application/json",
}

_DELAY_SPLIT_RE = re.compile(r"[-,]+")
REQUEST_TIMEOUT_SECONDS = 30
DOWNLOAD_RETRY_ATTEMPTS = 4
DOWNLOAD_RETRY_BASE_DELAY_SECONDS = 1.0


def ensure_curve_starts_at_zero(points):
    """Prepend an explicit ignition origin when the curve does not start at 0,0."""
    if not points:
        return points
    first_time, first_thrust = points[0]
    if first_time == 0.0 and first_thrust == 0.0:
        return points
    return [(0.0, 0.0), *points]


def load_motors_metadata():
    if os.path.exists(MOTORS_METADATA_FILE):
        with open(MOTORS_METADATA_FILE, "r") as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
    return {"motors": {}}


def normalize_delays(raw_value):
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    if not value:
        return None
    if value.upper() == "P":
        return "P"
    parts = [part.strip() for part in _DELAY_SPLIT_RE.split(value) if part.strip()]
    return ",".join(parts) if parts else None


def parse_rasp_text(content):
    metadata = None
    points = []

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        parts = stripped.split()
        if metadata is None:
            if len(parts) < 7:
                continue
            try:
                metadata = {
                    "designation": parts[0],
                    "common_name": parts[0],
                    "manufacturer": " ".join(parts[6:]),
                    "diameter_mm": float(parts[1]),
                    "length_mm": float(parts[2]),
                    "delays": normalize_delays(parts[3]),
                    "propellant_weight_g": float(parts[4]) * 1000.0,
                    "total_weight_g": float(parts[5]) * 1000.0,
                }
            except ValueError:
                metadata = None
        else:
            if len(parts) < 2:
                continue
            try:
                time_s = float(parts[0])
                thrust_n = float(parts[1])
            except ValueError:
                break
            points.append((time_s, thrust_n))
            if thrust_n == 0:
                break

    return metadata, ensure_curve_starts_at_zero(points)


def parse_rse_text(content):
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None, []

    engine = root.find(".//engine")
    if engine is None:
        return None, []

    designation = engine.get("code", "Unknown")
    common_name_match = re.match(r"^([A-Z][0-9]+)", designation)
    metadata = {
        "designation": designation,
        "common_name": common_name_match.group(1) if common_name_match else designation,
        "manufacturer": engine.get("mfg", "Unknown"),
        "diameter_mm": float(engine.get("dia", 0.0)),
        "length_mm": float(engine.get("len", 0.0)),
        "delays": normalize_delays(engine.get("delays", "")),
        "propellant_weight_g": float(engine.get("propWt", 0.0)),
        "total_weight_g": float(engine.get("initWt", 0.0)),
    }

    points = []
    data = engine.find("data")
    if data is not None:
        for point in data.findall("eng-data"):
            points.append((float(point.get("t", 0.0)), float(point.get("f", 0.0))))
    return metadata, ensure_curve_starts_at_zero(points)


def calculate_curve_stats(points):
    if not points:
        return {
            "point_count": 0,
            "burn_time_s": None,
            "total_impulse_ns": None,
            "avg_thrust_n": None,
            "max_thrust_n": None,
            "curve_fingerprint": None,
        }

    burn_time_s = points[-1][0]
    max_thrust_n = max(point[1] for point in points)
    total_impulse_ns = 0.0
    for index in range(1, len(points)):
        dt = points[index][0] - points[index - 1][0]
        avg_force = (points[index][1] + points[index - 1][1]) / 2.0
        total_impulse_ns += dt * avg_force

    avg_thrust_n = total_impulse_ns / burn_time_s if burn_time_s else None
    fingerprint_source = "|".join(f"{time_s:.3f}:{thrust_n:.2f}" for time_s, thrust_n in points)
    curve_fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()[:12]
    return {
        "point_count": len(points),
        "burn_time_s": burn_time_s,
        "total_impulse_ns": total_impulse_ns,
        "avg_thrust_n": avg_thrust_n,
        "max_thrust_n": max_thrust_n,
        "curve_fingerprint": curve_fingerprint,
    }


def decode_downloaded_file(result):
    data = result.get("data")
    if not data:
        return None
    try:
        return base64.b64decode(data).decode("utf-8", errors="ignore")
    except Exception:
        return None


def variant_filename(result):
    data_url = result.get("dataUrl") or ""
    if data_url:
        return data_url.rstrip("/").rsplit("/", 1)[-1]
    simfile_id = result.get("simfileId", "unknown")
    file_format = (result.get("format") or "unknown").lower()
    return f"{simfile_id}.{file_format}"


def absolutize_thrustcurve_url(url):
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return f"{TC_BASE_URL}{url}"
    return f"{TC_BASE_URL}/{url.lstrip('/')}"


def build_variant_summary(result, motor_meta):
    file_content = decode_downloaded_file(result)
    file_format = result.get("format", "Unknown")
    parsed_meta = None
    points = []

    if file_content and file_format == "RASP":
        parsed_meta, points = parse_rasp_text(file_content)
    elif file_content and file_format == "RockSim":
        parsed_meta, points = parse_rse_text(file_content)

    if not points:
        samples = result.get("samples") or []
        points = [(float(sample["time"]), float(sample["thrust"])) for sample in samples]
    points = ensure_curve_starts_at_zero(points)

    stats = calculate_curve_stats(points)
    parsed_meta = parsed_meta or {}

    return {
        "simfile_id": result.get("simfileId"),
        "filename": variant_filename(result),
        "format": file_format,
        "source": result.get("source"),
        "license": result.get("license"),
        "info_url": absolutize_thrustcurve_url(result.get("infoUrl")),
        "data_url": absolutize_thrustcurve_url(result.get("dataUrl")),
        "designation": parsed_meta.get("designation") or motor_meta.get("designation"),
        "common_name": parsed_meta.get("common_name") or motor_meta.get("commonName"),
        "manufacturer": parsed_meta.get("manufacturer") or motor_meta.get("manufacturer"),
        "diameter_mm": parsed_meta.get("diameter_mm") or motor_meta.get("diameter"),
        "length_mm": parsed_meta.get("length_mm") or motor_meta.get("length"),
        "delays": parsed_meta.get("delays") or normalize_delays(motor_meta.get("delays")),
        "propellant_weight_g": parsed_meta.get("propellant_weight_g") or motor_meta.get("propWeightG"),
        "total_weight_g": parsed_meta.get("total_weight_g") or motor_meta.get("totalWeightG"),
        "point_count": stats["point_count"],
        "burn_time_s": stats["burn_time_s"],
        "total_impulse_ns": stats["total_impulse_ns"],
        "avg_thrust_n": stats["avg_thrust_n"],
        "max_thrust_n": stats["max_thrust_n"],
        "curve_fingerprint": stats["curve_fingerprint"],
        "points": points,
    }


def normalize_comparison_value(value):
    if isinstance(value, float):
        return f"{value:.4f}"
    return value


def relative_spread(values):
    numeric = [value for value in values if isinstance(value, (int, float))]
    if len(numeric) < 2:
        return 0.0
    baseline = min(abs(value) for value in numeric if value is not None)
    if baseline == 0:
        return float("inf") if max(numeric) != min(numeric) else 0.0
    return (max(numeric) - min(numeric)) / baseline


def summarize_focused_differences(variants):
    focused = []

    delays = {normalize_comparison_value(variant.get("delays")) for variant in variants}
    if len(delays) > 1:
        focused.append({"label": "Delays", "key": "delays"})

    designations = {normalize_comparison_value(variant.get("designation")) for variant in variants}
    if len(designations) > 1:
        focused.append({"label": "Designation", "key": "designation"})

    burn_values = [variant.get("burn_time_s") for variant in variants if variant.get("burn_time_s") is not None]
    burn_spread = relative_spread(burn_values)
    if burn_spread > 0.01:
        focused.append({"label": "Burn", "key": "burn_time_s", "spread": burn_spread})

    impulse_values = [variant.get("total_impulse_ns") for variant in variants if variant.get("total_impulse_ns") is not None]
    impulse_spread = relative_spread(impulse_values)
    if impulse_spread > 0.01:
        focused.append({"label": "Impulse", "key": "total_impulse_ns", "spread": impulse_spread})

    curve_fingerprints = {normalize_comparison_value(variant.get("curve_fingerprint")) for variant in variants}
    if len(curve_fingerprints) > 1:
        focused.append({"label": "Curve", "key": "curve_fingerprint"})

    return focused


def collect_variant_differences(variants):
    return [difference["key"] for difference in summarize_focused_differences(variants)]


def format_difference_summary(focused_differences):
    if not focused_differences:
        return "No differences"

    parts = []
    for difference in focused_differences:
        label = difference["label"]
        spread = difference.get("spread")
        if spread is not None:
            parts.append(f"{label} ({spread * 100:.1f}%)")
        else:
            parts.append(label)
    return ", ".join(parts)


def fetch_motor_variants(motor_id, max_results):
    payload = {
        "motorIds": [motor_id],
        "data": "both",
        "maxResults": max_results,
    }
    last_error = None

    for attempt in range(1, DOWNLOAD_RETRY_ATTEMPTS + 1):
        try:
            response = requests.post(
                TC_API_DOWNLOAD,
                json=payload,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code != 200:
                raise RuntimeError(f"download failed with status {response.status_code}")

            body = response.json()
            if body.get("error"):
                raise RuntimeError(body["error"])
            return body.get("results", [])
        except (requests.RequestException, ValueError, RuntimeError) as error:
            last_error = error
            if attempt == DOWNLOAD_RETRY_ATTEMPTS:
                break
            delay_seconds = DOWNLOAD_RETRY_BASE_DELAY_SECONDS * attempt
            print(
                f"  [Retry {attempt}/{DOWNLOAD_RETRY_ATTEMPTS - 1}] download failed for {motor_id}: {error}. "
                f"Retrying in {delay_seconds:.1f}s..."
            )
            time.sleep(delay_seconds)

    raise RuntimeError(f"download failed for {motor_id}: {last_error}")


def select_motors(metadata, manufacturer=None, designation=None, motor_ids=None, limit=None, include_single=False):
    selected = []
    wanted_ids = set(motor_ids or [])
    for motor_id, motor_meta in metadata.get("motors", {}).items():
        if wanted_ids and motor_id not in wanted_ids:
            continue
        if manufacturer:
            haystack = f"{motor_meta.get('manufacturer', '')} {motor_meta.get('manufacturerAbbrev', '')}".lower()
            if manufacturer.lower() not in haystack:
                continue
        if designation:
            haystack = f"{motor_meta.get('designation', '')} {motor_meta.get('commonName', '')}".lower()
            if designation.lower() not in haystack:
                continue
        if not include_single and int(motor_meta.get("dataFiles", 0) or 0) < 2:
            continue
        selected.append((motor_id, motor_meta))

    selected.sort(key=lambda item: (item[1].get("manufacturer", ""), item[1].get("designation", ""), item[0]))
    if limit is not None:
        selected = selected[:limit]
    return selected


def analyze_motor(motor_id, motor_meta, max_results):
    raw_variants = fetch_motor_variants(motor_id, max_results=max_results)
    variants = [build_variant_summary(result, motor_meta) for result in raw_variants]
    variants.sort(key=lambda variant: (variant["format"] or "", variant["source"] or "", variant["filename"]))
    focused_differences = summarize_focused_differences(variants)
    differences = [difference["key"] for difference in focused_differences]
    return {
        "motor_id": motor_id,
        "motor_meta": motor_meta,
        "variants": variants,
        "differences": differences,
        "focused_differences": focused_differences,
        "difference_summary": format_difference_summary(focused_differences),
        "has_differences": bool(differences),
    }


def format_value(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def build_summary(entries):
    diff_counts = {}
    motors_with_differences = 0
    for entry in entries:
        if entry["has_differences"]:
            motors_with_differences += 1
        for difference in entry["focused_differences"]:
            field = difference["label"]
            diff_counts[field] = diff_counts.get(field, 0) + 1
    top_fields = sorted(diff_counts.items(), key=lambda item: (-item[1], item[0]))
    return {
        "motor_count": len(entries),
        "motors_with_differences": motors_with_differences,
        "top_fields": top_fields,
    }


def render_curve_plot(variants, motor_id):
    width = 960
    height = 260
    padding_left = 52
    padding_right = 18
    padding_top = 18
    padding_bottom = 34
    plot_width = width - padding_left - padding_right
    plot_height = height - padding_top - padding_bottom

    all_points = [point for variant in variants for point in variant.get("points", [])]
    if not all_points:
        return "<p class='plot-note'>No thrust curve samples available for plotting.</p>"

    max_time = max(point[0] for point in all_points) or 1.0
    max_force = max(point[1] for point in all_points) or 1.0
    colors = ["#8b3d2e", "#2c7a7b", "#d97706", "#5b21b6", "#be185d", "#1d4ed8"]

    def scale_x(time_s):
        return padding_left + (time_s / max_time) * plot_width

    def scale_y(force_n):
        return padding_top + plot_height - (force_n / max_force) * plot_height

    paths = []
    markers = []
    legends = []
    for index, variant in enumerate(variants):
        points = variant.get("points", [])
        if not points:
            continue
        color = colors[index % len(colors)]
        path = " ".join(f"{scale_x(time_s):.2f},{scale_y(force_n):.2f}" for time_s, force_n in points)
        paths.append(
            f"<polyline fill='none' stroke='{color}' stroke-width='2.2' points='{path}' />"
        )
        circles = "".join(
            f"<circle cx='{scale_x(time_s):.2f}' cy='{scale_y(force_n):.2f}' r='3' fill='{color}' opacity='0.75' />"
            for time_s, force_n in points
        )
        markers.append(circles)
        legends.append(
            "<span class='plot-legend-item'>"
            f"<span class='plot-swatch' style='background:{color}'></span>"
            f"{html.escape(variant['filename'])}"
            "</span>"
        )

    y_ticks = []
    for step in range(5):
        value = (max_force / 4.0) * step
        y = scale_y(value)
        y_ticks.append(
            f"<line x1='{padding_left}' y1='{y:.2f}' x2='{width - padding_right}' y2='{y:.2f}' class='plot-grid' />"
            f"<text x='{padding_left - 8}' y='{y + 4:.2f}' text-anchor='end' class='plot-axis-label'>{value:.0f}</text>"
        )

    x_ticks = []
    for step in range(5):
        value = (max_time / 4.0) * step
        x = scale_x(value)
        x_ticks.append(
            f"<line x1='{x:.2f}' y1='{padding_top}' x2='{x:.2f}' y2='{height - padding_bottom}' class='plot-grid' />"
            f"<text x='{x:.2f}' y='{height - 10}' text-anchor='middle' class='plot-axis-label'>{value:.2f}</text>"
        )

    return (
        f"<div class='curve-plot-block' id='curve-plot-{html.escape(motor_id)}'>"
        "<div class='plot-header'>Thrust curve comparison</div>"
        f"<svg viewBox='0 0 {width} {height}' class='curve-plot' role='img' aria-label='Thrust curve comparison plot'>"
        f"{''.join(y_ticks)}{''.join(x_ticks)}"
        f"<line x1='{padding_left}' y1='{height - padding_bottom}' x2='{width - padding_right}' y2='{height - padding_bottom}' class='plot-axis' />"
        f"<line x1='{padding_left}' y1='{padding_top}' x2='{padding_left}' y2='{height - padding_bottom}' class='plot-axis' />"
        f"{''.join(paths)}"
        f"{''.join(markers)}"
        f"<text x='{width / 2:.2f}' y='{height - 4}' text-anchor='middle' class='plot-axis-title'>Time (s)</text>"
        f"<text x='16' y='{height / 2:.2f}' text-anchor='middle' transform='rotate(-90 16 {height / 2:.2f})' class='plot-axis-title'>Force (N)</text>"
        "</svg>"
        f"<div class='plot-legend'>{''.join(legends)}</div>"
        "</div>"
    )


def render_html_report(entries, output_path):
    summary = build_summary(entries)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    rows = []
    for entry in entries:
        motor_meta = entry["motor_meta"]
        subtitle = f"{motor_meta.get('commonName', '')} | motorId: {entry['motor_id']}"
        detail_row_id = f"details-{entry['motor_id']}"
        plot_html = render_curve_plot(entry["variants"], entry["motor_id"])
        row_class = "motor-row"
        summary_class = "diff-summary"
        if not entry["has_differences"]:
            row_class += " no-diff"
            summary_class += " no-diff-text"

        header_row = (
            "<tr>"
            "<th>Variant</th><th>Format</th><th>Source</th><th>License</th><th>Delays</th>"
            "<th>Designation</th><th>Diameter</th><th>Length</th><th>Points</th>"
            "<th>Burn</th><th>Impulse</th><th>Curve Fingerprint</th>"
            "</tr>"
        )
        body_rows = []
        for variant in entry["variants"]:
            body_rows.append(
                "<tr>"
                f"<td><a href='{html.escape(variant.get('data_url') or variant.get('info_url') or '#')}'>{html.escape(variant['filename'])}</a></td>"
                f"<td>{html.escape(format_value(variant['format']))}</td>"
                f"<td>{html.escape(format_value(variant['source']))}</td>"
                f"<td>{html.escape(format_value(variant['license']))}</td>"
                f"<td>{html.escape(format_value(variant['delays']))}</td>"
                f"<td>{html.escape(format_value(variant['designation']))}</td>"
                f"<td>{html.escape(format_value(variant['diameter_mm']))}</td>"
                f"<td>{html.escape(format_value(variant['length_mm']))}</td>"
                f"<td>{html.escape(format_value(variant['point_count']))}</td>"
                f"<td>{html.escape(format_value(variant['burn_time_s']))}</td>"
                f"<td>{html.escape(format_value(variant['total_impulse_ns']))}</td>"
                f"<td><code>{html.escape(format_value(variant['curve_fingerprint']))}</code></td>"
                "</tr>"
            )

        rows.append(
            f"<tr class='{row_class}'>"
            f"<td>{html.escape(motor_meta.get('manufacturer', 'Unknown'))}</td>"
            f"<td>{html.escape(motor_meta.get('designation', entry['motor_id']))}</td>"
            f"<td class='{summary_class}'>{html.escape(entry['difference_summary'])}</td>"
            f"<td><button type='button' class='details-toggle' aria-expanded='false' aria-controls='{html.escape(detail_row_id)}'>More details</button></td>"
            "</tr>"
            f"<tr id='{html.escape(detail_row_id)}' class='detail-row' hidden>"
            "<td colspan='4'>"
            f"<div class='detail-panel'><p class='subtitle'>{html.escape(subtitle)}</p>"
            f"{plot_html}"
            "<table class='detail-table'>"
            f"<thead>{header_row}</thead>"
            f"<tbody>{''.join(body_rows)}</tbody>"
            "</table></div>"
            "</td></tr>"
        )

    top_field_rows = "".join(
        f"<li><strong>{html.escape(field)}</strong>: {count} motor(s)</li>"
        for field, count in summary["top_fields"][:10]
    ) or "<li>No differences found.</li>"

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ThrustCurve Variant Report</title>
  <style>
    :root {{
      --bg: #f4efe8;
      --panel: #fffaf4;
      --ink: #1f2933;
      --muted: #52606d;
      --accent: #8b3d2e;
      --accent-soft: #f7d8c9;
      --border: #d9c7b8;
      --diff: #8b3d2e;
      --same: #2f6b47;
    }}
    body {{
      margin: 0;
      font-family: Georgia, "Iowan Old Style", serif;
      background: radial-gradient(circle at top, #fffdf9 0%, var(--bg) 55%, #eadfce 100%);
      color: var(--ink);
    }}
    main {{
      max-width: 1400px;
      margin: 0 auto;
      padding: 32px 20px 60px;
    }}
    .hero {{
      background: color-mix(in srgb, var(--panel) 92%, white);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: 0 10px 30px rgba(58, 45, 35, 0.08);
      padding: 24px;
      margin-bottom: 22px;
    }}
    h1, h2 {{
      margin: 0 0 8px;
      line-height: 1.1;
    }}
    .subtitle {{
      color: var(--muted);
      margin: 0 0 14px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin: 18px 0;
    }}
    .stat {{
      background: #fff;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
    }}
    .stat .label {{
      display: block;
      color: var(--muted);
      font-size: 0.88rem;
    }}
    .stat .value {{
      display: block;
      font-size: 1.5rem;
      margin-top: 6px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
      background: #fff;
      border-radius: 12px;
      overflow: hidden;
    }}
    th, td {{
      border-bottom: 1px solid #eadfd2;
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #f7efe6;
      position: sticky;
      top: 0;
    }}
    tr:nth-child(even) td {{
      background: #fffaf5;
    }}
    a {{
      color: var(--accent);
    }}
    .table-controls {{
      display: inline-block;
      margin-top: 16px;
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .table-controls input {{
      margin-right: 8px;
    }}
    .no-diff {{
      display: none;
    }}
    .show-no-diff .no-diff {{
      display: table-row;
    }}
    .no-diff-text {{
      color: #7b8794;
      font-style: italic;
    }}
    .details-toggle {{
      cursor: pointer;
      color: var(--accent);
      font-weight: 600;
      border: 1px solid var(--border);
      background: #fffaf5;
      border-radius: 999px;
      padding: 6px 12px;
    }}
    .detail-row td {{
      padding: 0;
      background: #fbf6ef;
    }}
    .detail-panel {{
      padding: 18px 18px 20px;
    }}
    .curve-plot-block {{
      margin: 6px 0 16px;
      padding: 14px 14px 10px;
      background: #fffdf9;
      border: 1px solid var(--border);
      border-radius: 14px;
    }}
    .plot-header {{
      font-weight: 600;
      margin-bottom: 8px;
    }}
    .curve-plot {{
      width: 100%;
      height: auto;
      display: block;
      background: linear-gradient(180deg, #fff 0%, #fffaf4 100%);
      border-radius: 10px;
    }}
    .plot-axis {{
      stroke: #52606d;
      stroke-width: 1.2;
    }}
    .plot-grid {{
      stroke: #e7ddd2;
      stroke-width: 1;
    }}
    .plot-axis-label {{
      fill: #52606d;
      font-size: 11px;
      font-family: Georgia, "Iowan Old Style", serif;
    }}
    .plot-axis-title {{
      fill: #1f2933;
      font-size: 12px;
      font-family: Georgia, "Iowan Old Style", serif;
    }}
    .plot-legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 14px;
      margin-top: 10px;
      font-size: 0.9rem;
      color: var(--muted);
    }}
    .plot-legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}
    .plot-swatch {{
      width: 12px;
      height: 12px;
      border-radius: 999px;
      display: inline-block;
    }}
    .plot-note {{
      color: var(--muted);
      font-style: italic;
      margin: 6px 0 2px;
    }}
    .detail-table {{
      margin-top: 10px;
    }}
    code {{
      font-size: 0.85rem;
    }}
    ul {{
      margin: 10px 0 0;
      padding-left: 20px;
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>ThrustCurve Variant Report</h1>
      <p class="subtitle">Comparison of downloadable simfiles per motor, focused on fields that diverge across RASP, RockSim, cert, manufacturer, and user-submitted variants.</p>
      <div class="stats">
        <div class="stat"><span class="label">Motors analyzed</span><span class="value">{summary['motor_count']}</span></div>
        <div class="stat"><span class="label">Motors with differences</span><span class="value">{summary['motors_with_differences']}</span></div>
        <div class="stat"><span class="label">Most common diff fields</span><span class="value">{len(summary['top_fields'])}</span></div>
      </div>
      <h2>Most common difference fields</h2>
      <ul>{top_field_rows}</ul>
      <label class="table-controls">
        <input id="toggle-no-diff" type="checkbox">
        Show motors with no differences
      </label>
    </section>
    <table id="motor-table">
      <thead>
        <tr>
          <th>Manufacturer</th>
          <th>Motor</th>
          <th>Differences</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </main>
  <script>
    const toggleNoDiff = document.getElementById("toggle-no-diff");
    const motorTable = document.getElementById("motor-table");
    toggleNoDiff.addEventListener("change", () => {{
      motorTable.classList.toggle("show-no-diff", toggleNoDiff.checked);
    }});
    for (const button of document.querySelectorAll(".details-toggle")) {{
      button.addEventListener("click", () => {{
        const detailRow = document.getElementById(button.getAttribute("aria-controls"));
        const expanded = button.getAttribute("aria-expanded") === "true";
        const nextExpanded = !expanded;
        button.setAttribute("aria-expanded", nextExpanded ? "true" : "false");
        button.textContent = nextExpanded ? "Hide details" : "More details";
        detailRow.hidden = !nextExpanded;
      }});
    }}
  </script>
</body>
</html>
"""

    with open(output_path, "w") as f:
        f.write(html_doc)


def generate_report(output_path, manufacturer=None, designation=None, motor_ids=None, limit=None, include_single=False, max_results=20):
    metadata = load_motors_metadata()
    selected = select_motors(
        metadata,
        manufacturer=manufacturer,
        designation=designation,
        motor_ids=motor_ids,
        limit=limit,
        include_single=include_single,
    )
    if not selected:
        raise RuntimeError("no motors matched the selection criteria")

    entries = []
    failed_motors = []
    for motor_id, motor_meta in selected:
        print(f"Analyzing {motor_meta.get('manufacturer', 'Unknown')} {motor_meta.get('designation', motor_id)}...")
        try:
            entries.append(analyze_motor(motor_id, motor_meta, max_results=max_results))
        except Exception as error:
            print(f"  [Error] Skipping {motor_meta.get('manufacturer', 'Unknown')} {motor_meta.get('designation', motor_id)} ({motor_id}): {error}")
            failed_motors.append(
                {
                    "motor_id": motor_id,
                    "manufacturer": motor_meta.get("manufacturer", "Unknown"),
                    "designation": motor_meta.get("designation", motor_id),
                    "error": str(error),
                }
            )

    if not entries:
        raise RuntimeError("all selected motors failed to analyze")

    render_html_report(entries, output_path)
    if failed_motors:
        print(f"Completed with {len(failed_motors)} skipped motor(s) due to download errors.")
    return entries


def main():
    parser = argparse.ArgumentParser(description="Generate an HTML report comparing ThrustCurve simfile variants.")
    parser.add_argument("--output", default=OUTPUT_FILE, help="path to the generated HTML report")
    parser.add_argument("--manufacturer", help="filter motors by manufacturer name or abbreviation")
    parser.add_argument("--designation", help="filter motors by designation or common name")
    parser.add_argument("--motor-id", action="append", dest="motor_ids", help="analyze a specific motor ID; repeatable")
    parser.add_argument("--limit", type=int, help="maximum number of motors to analyze")
    parser.add_argument("--include-single", action="store_true", help="include motors with only one advertised data file")
    parser.add_argument("--max-results", type=int, default=20, help="maximum number of download variants to fetch per motor")
    args = parser.parse_args()

    entries = generate_report(
        output_path=args.output,
        manufacturer=args.manufacturer,
        designation=args.designation,
        motor_ids=args.motor_ids,
        limit=args.limit,
        include_single=args.include_single,
        max_results=args.max_results,
    )
    differing = sum(1 for entry in entries if entry["has_differences"])
    print(f"Wrote {args.output} with {len(entries)} motors analyzed; {differing} show differences.")


if __name__ == "__main__":
    main()
