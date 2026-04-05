"""Route module: symlink routing + ImageMagick output transforms."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from .taste_parser import parse_taste_file, TasteProfile


def _run_magick(args: list[str]) -> bool:
    """Run an ImageMagick convert/magick command. Returns True on success."""
    # Try 'magick' first (ImageMagick 7), fall back to 'convert' (ImageMagick 6)
    for cmd in ["magick", "convert"]:
        try:
            result = subprocess.run(
                [cmd] + args,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                return True
            # If magick exists but failed, don't try convert
            if cmd == "magick":
                print(f"    WARNING: ImageMagick error: {result.stderr.strip()}")
                return False
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            print("    WARNING: ImageMagick timed out")
            return False

    print("    WARNING: ImageMagick not found (tried 'magick' and 'convert')")
    return False


def _check_imagemagick() -> bool:
    """Check if ImageMagick is available."""
    for cmd in ["magick", "convert"]:
        try:
            subprocess.run([cmd, "-version"], capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return False


# ---------------------------------------------------------------------------
# Per-channel output transforms (from preview JPEGs, not full RAW)
# ---------------------------------------------------------------------------

def _transform_soft_warms(preview_path: Path, output_dir: Path, stem: str) -> list[Path]:
    """Soft Warms proof: warm tone simulation from preview (NX-D grade is the real output)."""
    outputs = []
    # sRGB JPG proof (simulates the warm grade direction)
    srgb = output_dir / f"{stem}_warm_proof_srgb.jpg"
    success = _run_magick([
        str(preview_path),
        "-modulate", "95,120,95",  # Slight darken, boost sat, warm hue shift
        "-gamma", "0.94",
        "-quality", "92",
        str(srgb),
    ])
    if success and srgb.exists():
        outputs.append(srgb)

    # Full-res TIF for Photoshop pipeline
    tif = output_dir / f"{stem}_warm_proof.tif"
    success = _run_magick([
        str(preview_path),
        "-depth", "16",
        str(tif),
    ])
    if success and tif.exists():
        outputs.append(tif)

    return outputs


def _transform_soft_greens(preview_path: Path, output_dir: Path, stem: str) -> list[Path]:
    """Soft Greens proof: green-toned preview."""
    output = output_dir / f"{stem}_green_proof.jpg"
    success = _run_magick([
        str(preview_path),
        "-modulate", "100,110,105",  # Slight green-warm shift
        "-quality", "92",
        str(output),
    ])
    return [output] if success and output.exists() else []


def _transform_instagram(preview_path: Path, output_dir: Path, stem: str) -> list[Path]:
    """Instagram-ready center crop: 1080x1080 (1:1) and 1080x1350 (4:5)."""
    outputs = []

    # 1:1 square crop
    square = output_dir / f"{stem}_ig_1080sq.jpg"
    success = _run_magick([
        str(preview_path),
        "-gravity", "center",
        "-crop", "1:1+0+0",  # Aspect ratio crop
        "-resize", "1080x1080",
        "-sharpen", "0x0.5",
        "-quality", "85",
        str(square),
    ])
    if success and square.exists():
        outputs.append(square)

    # 4:5 portrait crop
    portrait = output_dir / f"{stem}_ig_1080x1350.jpg"
    success = _run_magick([
        str(preview_path),
        "-gravity", "center",
        "-crop", "4:5+0+0",
        "-resize", "1080x1350",
        "-sharpen", "0x0.5",
        "-quality", "85",
        str(portrait),
    ])
    if success and portrait.exists():
        outputs.append(portrait)

    return outputs


def _transform_composite_base(preview_path: Path, output_dir: Path, stem: str) -> list[Path]:
    """Full-res TIFF for compositing (from preview — proof quality for v1)."""
    output = output_dir / f"{stem}_composite.tiff"
    success = _run_magick([
        str(preview_path),
        "-depth", "16",
        str(output),
    ])
    return [output] if success and output.exists() else []


def _transform_elimstat_product(preview_path: Path, output_dir: Path, stem: str) -> list[Path]:
    """Elimstat product: multiple sizes, sRGB, neutral, optimized JPEG."""
    outputs = []
    for width in [2400, 1200, 600]:
        output = output_dir / f"{stem}_elimstat_{width}px.jpg"
        success = _run_magick([
            str(preview_path),
            "-resize", f"{width}x{width}>",  # Shrink only, preserve aspect
            "-colorspace", "sRGB",
            "-quality", "85",
            "-strip",  # Remove metadata for web
            str(output),
        ])
        if success and output.exists():
            outputs.append(output)

    return outputs


def _transform_bw_monochrome(preview_path: Path, output_dir: Path, stem: str) -> list[Path]:
    """B&W monochrome proof: grayscale conversion from preview."""
    outputs = []

    # High contrast "Severe" style
    severe = output_dir / f"{stem}_bw_severe.jpg"
    success = _run_magick([
        str(preview_path),
        "-colorspace", "Gray",
        "-contrast-stretch", "2%x1%",
        "-quality", "92",
        str(severe),
    ])
    if success and severe.exists():
        outputs.append(severe)

    # Softer "1960s" style
    vintage = output_dir / f"{stem}_bw_1960s.jpg"
    success = _run_magick([
        str(preview_path),
        "-colorspace", "Gray",
        "-modulate", "105,0,100",
        "-gamma", "1.1",
        "-quality", "92",
        str(vintage),
    ])
    if success and vintage.exists():
        outputs.append(vintage)

    return outputs


# Channel name -> transform function
CHANNEL_TRANSFORMS = {
    "soft-warms": _transform_soft_warms,
    "soft-greens": _transform_soft_greens,
    "instagram": _transform_instagram,
    "composite-base": _transform_composite_base,
    "elimstat-product": _transform_elimstat_product,
    "bw-monochrome": _transform_bw_monochrome,
}


# ---------------------------------------------------------------------------
# Main routing pipeline
# ---------------------------------------------------------------------------

def route_all(
    working_dir: Path,
    taste_path: Path,
    threshold_override: float | None = None,
    dry_run: bool = False,
    clean: bool = False,
    scores_name: str = "scores.json",
    manifest_name: str = "manifest.json",
    routes_name: str = "routes.json",
) -> dict:
    """Route scored images into channel directories with symlinks and derivatives.

    Reads scores and manifest from working_dir.
    Creates routes/ subdirectories with symlinks to original NEFs
    and ImageMagick-derived outputs from preview JPEGs.
    """
    working_dir = Path(working_dir).resolve()
    scores_path = working_dir / scores_name
    manifest_path = working_dir / manifest_name

    if not scores_path.exists():
        raise FileNotFoundError(
            f"No {scores_name} found. Run 'bridge-assist score' first."
        )
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No {manifest_name} found. Run 'bridge-assist ingest' first."
        )

    with open(scores_path) as f:
        scores_data = json.load(f)
    with open(manifest_path) as f:
        manifest = json.load(f)

    profile = parse_taste_file(taste_path)
    routes_dir = working_dir / "routes"

    has_magick = _check_imagemagick()
    if not has_magick:
        print("WARNING: ImageMagick not found. Routing will create symlinks only (no derivatives).")

    # Clean previous routes if requested
    if clean and routes_dir.exists() and not dry_run:
        shutil.rmtree(routes_dir)
        print("Cleaned previous routing outputs.")

    # Build routing plan
    routing_plan = {}  # filename -> list of channel assignments
    scores = scores_data.get("scores", {})

    for filename, file_scores in scores.items():
        assignments = []
        for score_entry in file_scores.get("scores", []):
            channel_name = score_entry["channel"]
            confidence = score_entry["confidence"]
            channel_def = profile.get_channel(channel_name)

            # Determine threshold
            if threshold_override is not None:
                thresh = threshold_override
            elif channel_def:
                thresh = channel_def.confidence_threshold
            else:
                thresh = 0.5

            if confidence >= thresh:
                assignments.append({
                    "channel": channel_name,
                    "confidence": confidence,
                    "reasoning": score_entry.get("reasoning", ""),
                })

        if assignments:
            routing_plan[filename] = assignments

    # Report plan
    total_assignments = sum(len(a) for a in routing_plan.values())
    print(f"Routing plan: {len(routing_plan)} images -> {total_assignments} channel assignments")

    if dry_run:
        print("\n--- DRY RUN (no files created) ---")
        for filename, assignments in sorted(routing_plan.items()):
            for a in assignments:
                print(f"  {filename} -> {a['channel']} (confidence: {a['confidence']:.2f})")
        return {"plan": routing_plan, "dry_run": True}

    # Execute routing
    route_results = {}

    for filename, assignments in routing_plan.items():
        file_info = manifest.get("files", {}).get(filename)
        if not file_info:
            print(f"  WARNING: {filename} not in manifest, skipping")
            continue

        nef_path = Path(file_info["nef_path"])
        preview_path = Path(file_info["preview_path"])
        stem = nef_path.stem
        file_results = []

        for assignment in assignments:
            channel_name = assignment["channel"]
            channel_dir = routes_dir / channel_name
            channel_dir.mkdir(parents=True, exist_ok=True)

            # Create symlink to original NEF
            symlink_path = channel_dir / nef_path.name
            if not symlink_path.exists():
                try:
                    symlink_path.symlink_to(nef_path)
                except OSError as e:
                    print(f"    WARNING: Could not create symlink for {filename}: {e}")

            # Generate derivatives via ImageMagick
            derivatives = []
            if has_magick and preview_path.exists():
                transform_fn = CHANNEL_TRANSFORMS.get(channel_name)
                if transform_fn:
                    print(f"  {filename} -> {channel_name} (derivatives)...", end=" ", flush=True)
                    derivatives = transform_fn(preview_path, channel_dir, stem)
                    print(f"{len(derivatives)} files")
                else:
                    print(f"  {filename} -> {channel_name} (symlink only, no transform defined)")
            else:
                print(f"  {filename} -> {channel_name} (symlink only)")

            file_results.append({
                "channel": channel_name,
                "confidence": assignment["confidence"],
                "symlink": str(symlink_path),
                "derivatives": [str(d) for d in derivatives],
            })

        route_results[filename] = file_results

    # Write routing results
    route_data = {
        "routed_at": __import__("datetime").datetime.now().isoformat(),
        "taste_file": str(taste_path),
        "threshold_override": threshold_override,
        "total_images_routed": len(route_results),
        "total_assignments": sum(len(r) for r in route_results.values()),
        "routes": route_results,
    }

    routes_json_path = working_dir / routes_name
    with open(routes_json_path, "w") as f:
        json.dump(route_data, f, indent=2)

    print(f"\nRouted {len(route_results)} images with {route_data['total_assignments']} channel assignments")
    print(f"Routes: {routes_dir}")

    return route_data
