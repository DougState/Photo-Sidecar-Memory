"""Ingest module: extract JPEG previews and EXIF metadata from NEF files."""

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import rawpy
from PIL import Image


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
                preview_path = output_dir / f"{nef_path.stem}_preview.jpg"
                img = Image.fromarray(thumb.data)
                img.save(str(preview_path), "JPEG", quality=92)
                return preview_path
    except Exception as e:
        print(f"  WARNING: Could not extract preview from {nef_path.name}: {e}")
        return None


_HAS_EXIFTOOL: bool | None = None


def _check_exiftool() -> bool:
    """Check once whether exiftool is available on PATH."""
    global _HAS_EXIFTOOL
    if _HAS_EXIFTOOL is None:
        _HAS_EXIFTOOL = shutil.which("exiftool") is not None
    return _HAS_EXIFTOOL


def read_exif(nef_path: Path) -> dict:
    """Read EXIF metadata from a NEF file.

    Uses exiftool (gold standard) when available, with Pillow as fallback.
    exiftool reads full Makernote data from NEFs including lens ID, accurate
    dimensions, and all shooting parameters. Pillow only sees the 160x120
    embedded thumbnail EXIF, which misses most D800 fields.
    """
    if _check_exiftool():
        return _read_exif_exiftool(nef_path)
    return _read_exif_pillow(nef_path)


def _read_exif_exiftool(nef_path: Path) -> dict:
    """Read EXIF via exiftool subprocess.

    Runs without -n so LensID resolves to a human-readable lens name.
    Uses -j for JSON output. Numeric fields (FNumber, ISO, etc.) come
    back as strings like "f/11.0" which parse_exif_for_scoring handles.
    """
    try:
        result = subprocess.run(
            ["exiftool", "-j", str(nef_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)[0]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, IndexError) as e:
        print(f"  WARNING: exiftool failed for {nef_path.name}: {e}")
    return _read_exif_pillow(nef_path)


def _read_exif_pillow(nef_path: Path) -> dict:
    """Fallback EXIF reader using Pillow. Limited for RAW files."""
    from PIL.ExifTags import TAGS

    exif_data = {}
    try:
        with Image.open(nef_path) as img:
            raw_exif = img.getexif()
            if raw_exif:
                for tag_id, value in raw_exif.items():
                    tag_name = TAGS.get(tag_id, str(tag_id))
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
    """Extract the specific EXIF fields needed for vision API scoring prompts.

    Handles both exiftool keys (human-readable strings) and Pillow keys.
    exiftool without -n returns values like "11.0" (aperture), "1/200" (shutter),
    "48.0 mm" (focal length). We normalize these for the scoring prompt.
    """
    focal = exif.get("FocalLength", "Unknown")
    if isinstance(focal, (int, float)):
        focal = f"{focal:.0f}"
    elif isinstance(focal, str) and focal != "Unknown":
        focal = focal.replace(" mm", "").strip()

    aperture = exif.get("FNumber", exif.get("Aperture", "Unknown"))
    if isinstance(aperture, (int, float)):
        aperture = f"{aperture:.1f}"

    shutter = exif.get("ExposureTime", exif.get("ShutterSpeed", "Unknown"))
    if isinstance(shutter, (int, float)):
        if shutter < 1:
            denom = round(1 / shutter)
            shutter = f"1/{denom}"
        else:
            shutter = f"{shutter:.1f}s"

    iso = exif.get("ISO", exif.get("ISOSpeedRatings",
          exif.get("PhotographicSensitivity", "Unknown")))

    lens = exif.get("LensID", exif.get("LensModel",
           exif.get("LensInfo", "Unknown")))

    return {
        "camera_model": exif.get("Model", "Unknown"),
        "lens": str(lens) if lens else "Unknown",
        "focal_length": str(focal),
        "aperture": str(aperture),
        "iso": str(iso),
        "shutter_speed": str(shutter),
        "date_taken": exif.get("DateTimeOriginal", exif.get("DateTime", "Unknown")),
        "image_width": exif.get("ImageWidth", exif.get("ExifImageWidth", "Unknown")),
        "image_height": exif.get("ImageHeight", exif.get("ExifImageHeight",
                        exif.get("ImageLength", "Unknown"))),
    }


def ingest_folder(source_dir: Path, working_dir: Path, manifest_name: str = "manifest.json") -> dict:
    """Ingest all NEF files from source_dir.

    Creates:
      - working_dir/previews/  (extracted JPEG previews)
      - working_dir/{manifest_name}  (EXIF data + file metadata)

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
    manifest_path = working_dir / manifest_name
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    print(f"\nIngested {len(manifest['files'])} files, skipped {len(manifest['skipped'])}")
    print(f"Manifest: {manifest_path}")
    print(f"Previews: {previews_dir}")

    return manifest
