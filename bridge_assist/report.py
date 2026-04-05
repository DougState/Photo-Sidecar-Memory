"""Report module: generate markdown summary with thumbnails and scores."""

import json
from datetime import datetime
from pathlib import Path

from .taste_parser import parse_taste_file


def generate_report(
    working_dir: Path,
    taste_path: Path,
    output_path: Path | None = None,
    manifest_name: str = "manifest.json",
    scores_name: str = "scores.json",
    routes_name: str = "routes.json",
    report_name: str = "sort-report.md",
) -> str:
    """Generate a markdown report from scoring and routing results.

    Two sections:
    1. Channel Summary table (shoot overview)
    2. Per-Channel sections with images sorted by confidence (contact sheet style)

    At scale (hundreds of images), the per-channel layout lets photographers
    review routing decisions channel by channel instead of scrolling through
    every image individually.
    """
    working_dir = Path(working_dir).resolve()
    manifest_path = working_dir / manifest_name
    scores_path = working_dir / scores_name
    routes_path = working_dir / routes_name

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
    files = manifest.get("files", {})
    scores = scores_data.get("scores", {}) if has_scores else {}
    routes = routes_data.get("routes", {}) if has_routes else {}

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
        lines.append(
            f"Routed: {routes_data.get('total_images_routed', 0)} images "
            f"-> {routes_data.get('total_assignments', 0)} assignments"
        )

    lines.append("")

    # -- Channel Summary table --
    if has_scores:
        lines.append("## Channel Summary")
        lines.append("")

        channel_images: dict[str, list[dict]] = {ch.name: [] for ch in profile.channels}

        for filename, file_scores in scores.items():
            for entry in file_scores.get("scores", []):
                ch_name = entry["channel"]
                if ch_name in channel_images:
                    channel_images[ch_name].append({
                        "file": filename,
                        "confidence": entry["confidence"],
                        "reasoning": entry.get("reasoning", ""),
                    })

        lines.append("| Channel | Routed | Total Scored | Avg Confidence | Threshold |")
        lines.append("|---------|--------|-------------|----------------|-----------|")
        for ch in profile.channels:
            imgs = channel_images[ch.name]
            avg = sum(i["confidence"] for i in imgs) / len(imgs) if imgs else 0
            above = sum(1 for i in imgs if i["confidence"] >= ch.confidence_threshold)
            lines.append(
                f"| {ch.name} | {above} | {len(imgs)} | {avg:.2f} | {ch.confidence_threshold} |"
            )
        lines.append("")

        # -- Per-Channel sections --
        for ch in profile.channels:
            imgs = sorted(channel_images[ch.name], key=lambda x: x["confidence"], reverse=True)
            above = [i for i in imgs if i["confidence"] >= ch.confidence_threshold]
            below = [i for i in imgs if i["confidence"] < ch.confidence_threshold]

            lines.append(f"## {ch.name}")
            lines.append("")
            lines.append(f"*{ch.intent}*")
            lines.append(f"Threshold: {ch.confidence_threshold} | "
                         f"Routed: {len(above)} | Rejected: {len(below)}")
            lines.append("")

            if above:
                lines.append("### Routed")
                lines.append("")
                _write_image_table(lines, above, files, routes, ch.name, routed=True)

            if below:
                lines.append("### Below Threshold")
                lines.append("")
                _write_image_table(lines, below, files, routes, ch.name, routed=False)

    # -- Skipped files --
    skipped = manifest.get("skipped", [])
    if skipped:
        lines.append("## Skipped Files")
        lines.append("")
        for s in skipped:
            lines.append(f"- **{s['file']}**: {s['reason']}")
        lines.append("")

    # -- Scoring errors --
    if has_scores:
        errors = scores_data.get("errors", [])
        if errors:
            lines.append("## Scoring Errors")
            lines.append("")
            for e in errors:
                lines.append(f"- **{e['file']}**: {e['error']}")
            lines.append("")

    report_text = "\n".join(lines)

    if output_path is None:
        output_path = working_dir / report_name
    else:
        output_path = Path(output_path)

    output_path.write_text(report_text)
    print(f"Report written to {output_path}")

    return report_text


def _write_image_table(
    lines: list[str],
    images: list[dict],
    manifest_files: dict,
    routes: dict,
    channel_name: str,
    routed: bool,
) -> None:
    """Write a table of images for a single channel section."""
    lines.append("| | File | Confidence | EXIF | Reasoning |")
    lines.append("|---|------|-----------|------|-----------|")

    for img in images:
        filename = img["file"]
        file_info = manifest_files.get(filename, {})
        preview_path = file_info.get("preview_path", "")
        exif = file_info.get("exif", {})

        preview_rel = Path(preview_path).name if preview_path else ""
        thumb = f"![](previews/{preview_rel})" if preview_rel else ""

        exif_str = (
            f"{exif.get('focal_length', '?')}mm "
            f"f/{exif.get('aperture', '?')} "
            f"ISO {exif.get('iso', '?')}"
        )

        conf_bar = _confidence_bar(img["confidence"])
        reasoning = img["reasoning"]

        lines.append(
            f"| {thumb} | {filename} | {conf_bar} {img['confidence']:.2f} | {exif_str} | {reasoning} |"
        )

    lines.append("")


def _confidence_bar(conf: float, width: int = 10) -> str:
    """Generate a simple text confidence bar."""
    filled = round(conf * width)
    return "\u2588" * filled + "\u2591" * (width - filled)
