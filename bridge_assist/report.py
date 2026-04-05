"""Report module: generate markdown summary with thumbnails and scores."""

import json
from datetime import datetime
from pathlib import Path

from .taste_parser import parse_taste_file


def generate_report(
    working_dir: Path,
    taste_path: Path,
    output_path: Path | None = None,
) -> str:
    """Generate a markdown report from scoring and routing results.

    Reads manifest.json, scores.json, and optionally routes.json.
    Outputs a markdown file with inline thumbnail references and score tables.
    """
    working_dir = Path(working_dir).resolve()
    manifest_path = working_dir / "manifest.json"
    scores_path = working_dir / "scores.json"
    routes_path = working_dir / "routes.json"

    if not manifest_path.exists():
        raise FileNotFoundError("No manifest.json found. Run 'bridge-assist ingest' first.")

    with open(manifest_path) as f:
        manifest = json.load(f)

    has_scores = scores_path.exists()
    has_routes = routes_path.exists()

    scores_data = {}
    if has_scores:
        with open(scores_path) as f:
            scores_data = json.load(f)

    routes_data = {}
    if has_routes:
        with open(routes_path) as f:
            routes_data = json.load(f)

    profile = parse_taste_file(taste_path)

    # Build report
    lines = []
    lines.append("# Bridge-Assist Sort Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Source: {manifest.get('source_dir', 'Unknown')}")
    lines.append(f"Total files: {manifest.get('total_files', 0)}")

    if has_scores:
        lines.append(f"Backend: {scores_data.get('backend', 'Unknown')}")
        lines.append(f"Scored: {scores_data.get('total_scored', 0)}")

    if has_routes:
        lines.append(f"Routed: {routes_data.get('total_images_routed', 0)} images -> {routes_data.get('total_assignments', 0)} assignments")

    lines.append("")

    # Channel summary
    if has_scores:
        lines.append("## Channel Summary")
        lines.append("")

        channel_counts = {ch.name: 0 for ch in profile.channels}
        channel_avg = {ch.name: [] for ch in profile.channels}

        for filename, file_scores in scores_data.get("scores", {}).items():
            for entry in file_scores.get("scores", []):
                ch = entry["channel"]
                conf = entry["confidence"]
                if ch in channel_avg:
                    channel_avg[ch].append(conf)
                    ch_def = profile.get_channel(ch)
                    thresh = ch_def.confidence_threshold if ch_def else 0.5
                    if conf >= thresh:
                        channel_counts[ch] += 1

        lines.append("| Channel | Above Threshold | Avg Confidence | Threshold |")
        lines.append("|---------|----------------|----------------|-----------|")
        for ch in profile.channels:
            avg = sum(channel_avg[ch.name]) / len(channel_avg[ch.name]) if channel_avg[ch.name] else 0
            lines.append(
                f"| {ch.name} | {channel_counts[ch.name]} | {avg:.2f} | {ch.confidence_threshold} |"
            )
        lines.append("")

    # Per-image details
    if has_scores:
        lines.append("## Image Scores")
        lines.append("")

        files = manifest.get("files", {})
        scores = scores_data.get("scores", {})
        routes = routes_data.get("routes", {}) if has_routes else {}

        for filename in sorted(files.keys()):
            file_info = files[filename]
            preview_path = file_info.get("preview_path", "")
            exif = file_info.get("exif", {})

            lines.append(f"### {filename}")
            lines.append("")

            # Thumbnail reference (relative path)
            preview_rel = Path(preview_path).name if preview_path else ""
            if preview_rel:
                lines.append(f"![{filename}](previews/{preview_rel})")
                lines.append("")

            # EXIF summary
            lines.append(
                f"*{exif.get('camera_model', '?')} | "
                f"{exif.get('focal_length', '?')}mm | "
                f"f/{exif.get('aperture', '?')} | "
                f"ISO {exif.get('iso', '?')} | "
                f"{exif.get('shutter_speed', '?')}s*"
            )
            lines.append("")

            # Scores table
            if filename in scores:
                file_scores = scores[filename].get("scores", [])
                lines.append("| Channel | Confidence | Routed | Reasoning |")
                lines.append("|---------|-----------|--------|-----------|")

                file_routes = routes.get(filename, [])
                routed_channels = {r["channel"] for r in file_routes}

                for entry in sorted(file_scores, key=lambda x: x["confidence"], reverse=True):
                    routed = "Yes" if entry["channel"] in routed_channels else ""
                    conf_bar = _confidence_bar(entry["confidence"])
                    reasoning = entry.get("reasoning", "")[:80]
                    lines.append(
                        f"| {entry['channel']} | {conf_bar} {entry['confidence']:.2f} | {routed} | {reasoning} |"
                    )
                lines.append("")

    # Skipped files
    skipped = manifest.get("skipped", [])
    if skipped:
        lines.append("## Skipped Files")
        lines.append("")
        for s in skipped:
            lines.append(f"- **{s['file']}**: {s['reason']}")
        lines.append("")

    # Errors
    if has_scores:
        errors = scores_data.get("errors", [])
        if errors:
            lines.append("## Scoring Errors")
            lines.append("")
            for e in errors:
                lines.append(f"- **{e['file']}**: {e['error']}")
            lines.append("")

    report_text = "\n".join(lines)

    # Write to file
    if output_path is None:
        output_path = working_dir / "sort-report.md"
    else:
        output_path = Path(output_path)

    output_path.write_text(report_text)
    print(f"Report written to {output_path}")

    return report_text


def _confidence_bar(conf: float, width: int = 10) -> str:
    """Generate a simple text confidence bar."""
    filled = round(conf * width)
    return "█" * filled + "░" * (width - filled)
