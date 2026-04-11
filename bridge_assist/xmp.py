"""Write XMP sidecar files so Adobe Bridge displays AI scores as native metadata.

Bridge reads .xmp files placed next to image files automatically. This module
maps bridge-assist channel scores to:
  - xmp:Rating (1-5 stars) from the top channel confidence
  - xmp:Label (color name) from the primary channel
  - dc:subject keywords with per-channel scores for Bridge's Filter panel
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

CHANNEL_TO_LABEL = {
    "soft-warms": "soft-warms",
    "soft-greens": "soft-greens",
    "composite-base": "composite-base",
    "bw-monochrome": "bw-monochrome",
    "instagram": "instagram",
}

SKIP_CHANNELS = {"elimstat-product"}

XMP_TEMPLATE = """\
<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description
      xmlns:xmp="http://ns.adobe.com/xap/1.0/"
      xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"
      xmlns:lr="http://ns.adobe.com/lightroom/1.0/"
      xmp:Rating="{rating}"
      xmp:Label="{label}">
      <dc:subject>
        <rdf:Bag>
{keyword_lines}
        </rdf:Bag>
      </dc:subject>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
"""


def confidence_to_stars(confidence: float) -> int:
    """Map a 0.0-1.0 confidence to Bridge's 1-5 star rating."""
    if confidence >= 0.9:
        return 5
    if confidence >= 0.75:
        return 4
    if confidence >= 0.6:
        return 3
    if confidence >= 0.4:
        return 2
    return 1


def _filter_scores(scores: list[dict]) -> list[dict]:
    """Remove channels that don't belong in Bridge output."""
    return [s for s in scores if s["channel"] not in SKIP_CHANNELS]


def build_keywords(scores: list[dict], backend: str | None = None) -> list[str]:
    """Build dc:subject keyword list from channel scores.

    Keywords are structured so Bridge's Filter panel groups them:
      - "ba:channel:soft-warms" (filterable by channel assignment)
      - "ba:score:soft-warms:0.82" (includes confidence value)
      - "ba:top:bw-monochrome" (marks the highest-scoring channel)
      - "bridge-assist" (general tag for all AI-scored images)
    """
    keywords = ["bridge-assist"]

    if backend:
        keywords.append(f"ba:backend:{backend}")

    scores = _filter_scores(scores)
    if not scores:
        return keywords

    top = max(scores, key=lambda s: s["confidence"])
    keywords.append(f"ba:top:{top['channel']}")

    for s in scores:
        conf = s["confidence"]
        ch = s["channel"]
        keywords.append(f"ba:score:{ch}:{conf:.2f}")
        if conf >= 0.5:
            keywords.append(f"ba:channel:{ch}")

    return keywords


def generate_xmp(
    scores: list[dict],
    backend: str | None = None,
) -> str:
    """Generate XMP sidecar XML content for one image."""
    filtered = _filter_scores(scores)
    if not filtered:
        return _render_xmp(rating=0, label="", keywords=["bridge-assist"])

    top = max(filtered, key=lambda s: s["confidence"])
    rating = confidence_to_stars(top["confidence"])
    label = CHANNEL_TO_LABEL.get(top["channel"], "")
    keywords = build_keywords(scores, backend=backend)

    return _render_xmp(rating=rating, label=label, keywords=keywords)


def _render_xmp(rating: int, label: str, keywords: list[str]) -> str:
    keyword_lines = "\n".join(
        f"          <rdf:li>{kw}</rdf:li>" for kw in keywords
    )
    return XMP_TEMPLATE.format(
        rating=rating,
        label=label,
        keyword_lines=keyword_lines,
    )


def write_xmp_sidecars(
    scores_path: Path,
    manifest_path: Path,
    dry_run: bool = False,
    clean: bool = False,
) -> dict:
    """Write .xmp sidecar files next to each NEF in the source directory.

    Returns a summary dict with counts.
    """
    with open(scores_path) as f:
        scores_data = json.load(f)
    with open(manifest_path) as f:
        manifest = json.load(f)

    backend = scores_data.get("backend")
    all_scores = scores_data.get("scores", {})
    all_files = manifest.get("files", {})
    source_dir = Path(manifest["source_dir"])

    written = 0
    skipped = 0
    cleaned = 0
    errors = []

    for filename, file_info in all_files.items():
        nef_path = Path(file_info["nef_path"])
        xmp_path = nef_path.with_suffix(".xmp")

        if clean and xmp_path.exists():
            xmp_path.unlink()
            cleaned += 1

        if filename not in all_scores:
            skipped += 1
            continue

        entry = all_scores[filename]
        image_scores = entry.get("scores", [])
        xmp_content = generate_xmp(image_scores, backend=backend)

        if dry_run:
            print(f"  [DRY RUN] Would write: {xmp_path.name}")
            written += 1
            continue

        try:
            xmp_path.write_text(xmp_content, encoding="utf-8")
            written += 1
        except OSError as e:
            errors.append(f"{filename}: {e}")

    return {
        "written": written,
        "skipped": skipped,
        "cleaned": cleaned,
        "errors": errors,
        "source_dir": str(source_dir),
        "dry_run": dry_run,
    }
