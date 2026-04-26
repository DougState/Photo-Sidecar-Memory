"""Infer which taste channel a processed file belongs to.

Three inference signals, weighted by reliability:
  1. Folder name mapping (strongest, configurable)
  2. File metadata (layer count, color mode, ICC profile)
  3. Original AI scores as tiebreaker

Folder mappings are defined in FOLDER_CHANNEL_MAP and can be extended
via a future ## Watch Config section in taste.md.
"""

from dataclasses import dataclass, field
from pathlib import Path

FOLDER_CHANNEL_MAP: dict[str, list[str]] = {
    "photoshop": ["composite-base", "soft-warms", "soft-greens"],
    "captureone": ["soft-warms", "soft-greens", "bw-monochrome"],
    "filmpack": ["bw-monochrome", "soft-warms"],
    "capture one": ["soft-warms", "soft-greens", "bw-monochrome"],
}


@dataclass
class InferenceResult:
    channel: str
    confidence: float
    method: str
    signals: dict = field(default_factory=dict)


def _folder_signal(processed_path: Path) -> list[str]:
    """Derive candidate channels from the folder the file lives in."""
    for parent in processed_path.parents:
        folder_key = parent.name.lower()
        if folder_key in FOLDER_CHANNEL_MAP:
            return FOLDER_CHANNEL_MAP[folder_key]
    return []


def _metadata_signal(processed_path: Path) -> dict:
    """Read file metadata for channel inference clues.

    Returns a dict of signals: color_mode, layer_count, has_icc, bit_depth.
    Gracefully degrades if psd-tools or Pillow can't read the file.
    """
    signals: dict = {}
    suffix = processed_path.suffix.lower()

    if suffix in (".psd", ".psb"):
        signals.update(_read_psd_metadata(processed_path))
    elif suffix in (".tif", ".tiff"):
        signals.update(_read_tiff_metadata(processed_path))

    return signals


def _read_psd_metadata(path: Path) -> dict:
    """Extract metadata from PSD/PSB without loading pixel data.

    Delegates to `psd_introspect.read_basic_metadata` so the inferrer and the
    style miner share a single PSD-reading code path.
    """
    try:
        from .psd_introspect import read_basic_metadata
        return read_basic_metadata(path)
    except ImportError:
        return {}
    except Exception:
        return {}


def _read_tiff_metadata(path: Path) -> dict:
    """Extract metadata from TIFF files."""
    signals: dict = {}
    try:
        from PIL import Image
        with Image.open(path) as img:
            signals["color_mode"] = img.mode.lower()
            signals["width"] = img.width
            signals["height"] = img.height
            icc = img.info.get("icc_profile")
            if icc:
                signals["has_icc"] = True
                if b"CMYK" in icc or b"cmyk" in icc:
                    signals["icc_hint"] = "cmyk"
    except Exception:
        pass
    return signals


def _channel_from_metadata(signals: dict, folder_candidates: list[str]) -> str | None:
    """Use metadata to disambiguate among folder candidates or detect channel outright."""
    color_mode = signals.get("color_mode", "")
    layer_count = signals.get("layer_count", 0)

    if "grayscale" in color_mode or color_mode in ("l", "la"):
        return "bw-monochrome"

    if signals.get("icc_hint") == "cmyk" or "cmyk" in color_mode:
        return "composite-base"

    if layer_count >= 3:
        if "composite-base" in folder_candidates:
            return "composite-base"

    return None


def infer_channel(
    processed_path: Path,
    original_scores: list[dict] | None = None,
) -> InferenceResult:
    """Infer the taste channel for a processed file.

    Uses folder context, file metadata, and original AI scores.
    """
    folder_candidates = _folder_signal(processed_path)
    metadata = _metadata_signal(processed_path)
    all_signals = {"folder_candidates": folder_candidates, **metadata}

    meta_channel = _channel_from_metadata(metadata, folder_candidates)
    if meta_channel:
        return InferenceResult(
            channel=meta_channel,
            confidence=0.85,
            method="metadata",
            signals=all_signals,
        )

    if original_scores and folder_candidates:
        best_match = None
        best_conf = -1.0
        for score in original_scores:
            if score["channel"] in folder_candidates and score["confidence"] > best_conf:
                best_match = score["channel"]
                best_conf = score["confidence"]
        if best_match:
            return InferenceResult(
                channel=best_match,
                confidence=min(0.8, best_conf),
                method="folder+scores",
                signals=all_signals,
            )

    if folder_candidates:
        return InferenceResult(
            channel=folder_candidates[0],
            confidence=0.6,
            method="folder_default",
            signals=all_signals,
        )

    if original_scores:
        top = max(original_scores, key=lambda s: s["confidence"])
        return InferenceResult(
            channel=top["channel"],
            confidence=min(0.5, top["confidence"]),
            method="scores_only",
            signals=all_signals,
        )

    return InferenceResult(
        channel="unknown",
        confidence=0.0,
        method="none",
        signals=all_signals,
    )
