"""Ingest module: extract JPEG previews and EXIF metadata from NEF files."""

import json
import os
import struct
from datetime import datetime
from pathlib import Path

import rawpy
from PIL import Image
from PIL.ExifTags import TAGS


def extract_preview(nef_path: Path, output_dir: Path) -> Path | None:
    """Extract the embedded JPEG preview from a NEF file.

    The D800 stores a full-res JPEG inside each NEF. This is much faster
    than decoding the full 36MP RAW for thumbnail/scoring purposes.
    """
    try:
        with rawpy.imread(str(nef_path)) as raw:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                preview_path = output_dir / f"{nef_path.stem}_preview.jpg"
                with open(preview_path, "wb") as f:
                    f.write(thumb.data)
                return preview_path
            elif thumb.format == rawpy.ThumbFormat.BITMAP:
                # Fallback: convert bitmap thumbnail to JPEG
                preview_path = output_dir / f"{nef_path.stem}_preview.jpg"
                img = Image.fromarray(thumb.data)
                img.save(str(preview_path), "JPEG", quality=92)
                return preview_path
    except Exception as e:
        print(f"  WARNING: Could not extract preview from {nef_path.name}: {e}")
        return None


def read_exif(nef_path: Path) -> dict:
    """Read EXIF metadata from a NEF file using Pillow.

    Returns a dict with human-readable tag names. Falls back gracefully
    if EXIF data is missing or unreadable.
    """
    exif_data = {}
    try:
        with Image.open(nef_path) as img:
            raw_exif = img.getexif()
            if raw_exif:
                for tag_id, value in raw_exif.items():
                    tag_name = TAGS.get(tag_id, str(tag_id))
                    # Convert bytes and other non-serializable types
                    if isinstance(value, bytes):
                        try:
                            value = value.decode("utf-8", errors="replace")
                        except Exception:
                            value = str(value)
                    elif isinstance(value, (tuple, list)):
                        value = str(value)
                    exif_data[tag_name] = value
    except Exception as e:
        print(f"  WARNING: Could not read EXIF from {nef_path.name}: {e}")

    return exif_data


def parse_exif_for_scoring(exif: dict) -> dict:
    """Extract the specific EXIF fields needed for vision API scoring prompts."""
    return {
        "camera_model": exif.get("Model", "Unknown"),
        "lens": exif.get("LensModel", exif.get("LensInfo", "Unknown")),
        "focal_length": _parse_rational(exif.get("FocalLength", "Unknown")),
        "aperture": _parse_rational(exif.get("FNumber", "Unknown")),
        "iso": exif.get("ISOSpeedRatings", exif.get("PhotographicSensitivity", "Unknown")),
        "shutter_speed": exif.get("ExposureTime", "Unknown"),
        "date_taken": exif.get("DateTimeOriginal", exif.get("DateTime", "Unknown")),
        "image_width": exif.get("ImageWidth", exif.get("ExifImageWidth", "Unknown")),
        "image_height": exif.get("ImageLength", exif.get("ExifImageHeight", "Unknown")),
    }


def _parse_rational(value) -> str:
    """Convert EXIF rational values to readable strings."""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str) and value != "Unknown":
        return value
    return str(value)


def ingest_folder(source_dir: Path, working_dir: Path) -> dict:
    """Ingest all NEF files from source_dir.

    Creates:
      - working_dir/previews/  (extracted JPEG previews)
      - working_dir/manifest.json  (EXIF data + file metadata)

    Returns the manifest dict.
    """
    source_dir = Path(source_dir).resolve()
    working_dir = Path(working_dir).resolve()

    if not source_dir.is_dir():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")

    previews_dir = working_dir / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)

    # Find all NEF files (case-insensitive)
    nef_files = sorted(
        [f for f in source_dir.iterdir() if f.suffix.upper() == ".NEF"],
        key=lambda f: f.name,
    )

    if not nef_files:
        raise FileNotFoundError(f"No NEF files found in {source_dir}")

    manifest = {
        "source_dir": str(source_dir),
        "working_dir": str(working_dir),
        "ingested_at": datetime.now().isoformat(),
        "total_files": len(nef_files),
        "files": {},
        "skipped": [],
    }

    print(f"Ingesting {len(nef_files)} NEF files from {source_dir}")

    for i, nef_path in enumerate(nef_files, 1):
        print(f"  [{i}/{len(nef_files)}] {nef_path.name}...", end=" ")

        # Extract preview
        preview_path = extract_preview(nef_path, previews_dir)
        if preview_path is None:
            manifest["skipped"].append({
                "file": nef_path.name,
                "reason": "preview extraction failed",
            })
            print("SKIPPED")
            continue

        # Read EXIF
        exif = read_exif(nef_path)
        scoring_exif = parse_exif_for_scoring(exif)

        # Get file size
        file_size = nef_path.stat().st_size

        # Get preview dimensions
        try:
            with Image.open(preview_path) as img:
                preview_width, preview_height = img.size
        except Exception:
            preview_width, preview_height = None, None

        manifest["files"][nef_path.name] = {
            "nef_path": str(nef_path),
            "preview_path": str(preview_path),
            "preview_width": preview_width,
            "preview_height": preview_height,
            "file_size_bytes": file_size,
            "exif": scoring_exif,
        }
        print("OK")

    # Write manifest
    manifest_path = working_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    print(f"\nIngested {len(manifest['files'])} files, skipped {len(manifest['skipped'])}")
    print(f"Manifest: {manifest_path}")
    print(f"Previews: {previews_dir}")

    return manifest
