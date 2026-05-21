"""Lazy PSD/PSB introspection — extract layer structure without decoding pixels.

Used by both the inferrer (single-file channel hint) and the style miner
(corpus-wide fingerprint extraction). Designed to be safe on huge PSB
composites: per-file size threshold, optional timeout via SIGALRM, and a
graceful "partial" fallback that records header/metadata only when the file
is too big to walk fully.
"""

from __future__ import annotations

import json
import os
import signal
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Files larger than this default are introspected in "partial" mode: we record
# size/mtime/path and skip the layer walk. Tunable per-call.
DEFAULT_PARTIAL_THRESHOLD_BYTES = 1_000_000_000  # 1 GB
DEFAULT_TIMEOUT_SECONDS = 120

# Adjustment-layer kind strings produced by psd-tools. Anything matching one
# of these is counted in `adjustment_breakdown`.
ADJUSTMENT_KINDS = {
    "brightnesscontrast": "brightness_contrast",
    "curves": "curves",
    "exposure": "exposure",
    "levels": "levels",
    "vibrance": "vibrance",
    "huesaturation": "hue_saturation",
    "colorbalance": "color_balance",
    "blackandwhite": "black_and_white",
    "photofilter": "photo_filter",
    "channelmixer": "channel_mixer",
    "colorlookup": "color_lookup",
    "invert": "invert",
    "posterize": "posterize",
    "threshold": "threshold",
    "selectivecolor": "selective_color",
    "gradientmap": "gradient_map",
}

FILL_KINDS = {"solidcolorfill", "gradientfill", "patternfill"}

COLOR_MODE_NAMES = {
    0: "bitmap",
    1: "grayscale",
    2: "indexed",
    3: "rgb",
    4: "cmyk",
    7: "multichannel",
    8: "duotone",
    9: "lab",
}


# ---------------------------------------------------------------------------
# Timeout helper
# ---------------------------------------------------------------------------

class IntrospectionTimeout(Exception):
    pass


@contextmanager
def _timeout(seconds: int):
    """Raise IntrospectionTimeout if the block runs longer than `seconds`.

    Uses SIGALRM (Unix only). On platforms without SIGALRM, this is a no-op.
    """
    if seconds <= 0 or not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handler(signum, frame):
        raise IntrospectionTimeout(f"PSD introspection exceeded {seconds}s")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


# ---------------------------------------------------------------------------
# Fingerprint dataclass
# ---------------------------------------------------------------------------

@dataclass
class Fingerprint:
    path: str
    relpath: str
    tier: str
    project_chain: list[str]
    size_bytes: int
    mtime: str
    suffix: str
    image: dict = field(default_factory=dict)
    layers: dict = field(default_factory=dict)
    text_snippets: list[str] = field(default_factory=list)
    tree_signature: str = ""
    partial_introspection: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Fingerprint":
        return cls(**d)


# ---------------------------------------------------------------------------
# Helpers for layer classification
# ---------------------------------------------------------------------------

def _normalize_kind(kind: str) -> str:
    """Bucket psd-tools kind strings into stable category labels."""
    if kind == "group":
        return "group"
    if kind == "psdimage":
        return "root"
    if kind == "type":
        return "text"
    if kind == "smartobject":
        return "smart_object"
    if kind == "shape":
        return "shape"
    if kind in ADJUSTMENT_KINDS:
        return "adjustment"
    if kind in FILL_KINDS:
        return "fill"
    if kind == "pixel":
        return "pixel"
    return kind or "unknown"


def _adjustment_label(kind: str) -> str | None:
    """Return the canonical adjustment-type label for an adjustment kind."""
    return ADJUSTMENT_KINDS.get(kind)


def _opacity_bucket(opacity: int | None) -> str:
    if opacity is None:
        return "unknown"
    pct = (opacity / 255.0) * 100 if isinstance(opacity, int) else opacity * 100
    if pct >= 99.5:
        return "100"
    if pct >= 70:
        return "70-99"
    if pct >= 30:
        return "30-69"
    return "<30"


def _blend_mode_str(layer) -> str:
    bm = getattr(layer, "blend_mode", None)
    if bm is None:
        return "normal"
    name = getattr(bm, "name", str(bm))
    return name.lower()


def _has_mask(layer) -> bool:
    fn = getattr(layer, "has_mask", None)
    try:
        return bool(fn()) if callable(fn) else bool(fn)
    except Exception:
        return False


def _read_text_snippet(layer) -> str | None:
    """Best-effort text extraction from a type layer."""
    text = getattr(layer, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()[:60]
    engine_data = getattr(layer, "engine_dict", None)
    if engine_data:
        try:
            txt = str(engine_data).strip()
            if txt:
                return txt[:60]
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Tree signature (compact recursive shape descriptor)
# ---------------------------------------------------------------------------

KIND_SIGIL = {
    "group": "G",
    "pixel": "P",
    "adjustment": "A",
    "text": "T",
    "smart_object": "S",
    "shape": "H",
    "fill": "F",
}


def _tree_signature(layer, depth: int = 0, max_depth: int = 5) -> str:
    """Recursive compact signature like 'G[A,A,P]G[T,P]'.

    Only descends `max_depth` levels to keep signatures bounded.
    """
    kind = _normalize_kind(getattr(layer, "kind", ""))
    sigil = KIND_SIGIL.get(kind, "?")
    if kind == "root":
        children = []
        try:
            for child in layer:
                children.append(_tree_signature(child, depth, max_depth))
        except Exception:
            return sigil
        return ",".join(children) if children else sigil
    if kind != "group" or depth >= max_depth:
        return sigil
    children = []
    try:
        for child in layer:
            children.append(_tree_signature(child, depth + 1, max_depth))
    except Exception:
        return sigil
    return f"{sigil}[{','.join(children)}]"


# ---------------------------------------------------------------------------
# Main introspection entry points
# ---------------------------------------------------------------------------

def project_chain_for(path: Path, root: Path | None) -> list[str]:
    """Compute the folder breadcrumb chain from `root` to `path.parent`."""
    if root is None:
        return [path.parent.name]
    try:
        rel = path.parent.relative_to(root)
    except ValueError:
        return [path.parent.name]
    parts = [p for p in rel.parts if p]
    return parts


def tier_for(project_chain: list[str]) -> str:
    """Map the top-level folder to a tier slug."""
    if not project_chain:
        return "unknown"
    top = project_chain[0].lower()
    return {
        "top cuts": "top_cuts",
        "abstracts": "abstracts",
        "mugsy & tigger": "mugsy_tigger",
        "rough drafts": "rough_drafts",
        "rough drafts 2": "rough_drafts_2",
    }.get(top, top.replace(" ", "_").replace("&", "and"))


def _read_basic(path: Path, root: Path | None) -> Fingerprint:
    """Construct a Fingerprint with file-system-only data (no PSD parse)."""
    stat = path.stat()
    chain = project_chain_for(path, root)
    return Fingerprint(
        path=str(path),
        relpath=str(path.relative_to(root)) if root else path.name,
        tier=tier_for(chain),
        project_chain=chain,
        size_bytes=stat.st_size,
        mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        suffix=path.suffix.lower(),
    )


def introspect(
    path: Path,
    root: Path | None = None,
    partial_threshold_bytes: int = DEFAULT_PARTIAL_THRESHOLD_BYTES,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Fingerprint:
    """Extract a Fingerprint from a PSD/PSB file.

    Files above `partial_threshold_bytes` are recorded as partial: only the
    file-system metadata is captured, no layer walk attempted. This keeps the
    pipeline fast and memory-safe on multi-GB composites.

    On timeout, parse error, or any other exception, returns a Fingerprint
    with `error` populated and `partial_introspection=True`.
    """
    fp = _read_basic(path, root)

    if fp.size_bytes > partial_threshold_bytes:
        fp.partial_introspection = True
        fp.error = f"size_above_threshold ({fp.size_bytes} > {partial_threshold_bytes})"
        return fp

    try:
        with _timeout(timeout_seconds):
            from psd_tools import PSDImage

            psd = PSDImage.open(str(path))
            _populate_image(fp, psd)
            _populate_layers(fp, psd)
            fp.tree_signature = _tree_signature(psd)
    except IntrospectionTimeout as e:
        fp.partial_introspection = True
        fp.error = f"timeout: {e}"
    except Exception as e:
        fp.partial_introspection = True
        fp.error = f"{type(e).__name__}: {e}"

    return fp


def _populate_image(fp: Fingerprint, psd) -> None:
    color_mode = getattr(psd, "color_mode", None)
    color_mode_name = COLOR_MODE_NAMES.get(int(color_mode), str(color_mode).lower()) if color_mode is not None else "unknown"
    icc_name = _read_icc_name(psd)
    fp.image = {
        "width": int(getattr(psd, "width", 0)),
        "height": int(getattr(psd, "height", 0)),
        "color_mode": color_mode_name,
        "bit_depth": int(getattr(psd, "depth", 0) or 0),
        "icc_name": icc_name,
        "channels": int(getattr(psd, "channels", 0) or 0),
        "has_thumbnail": bool(_safe_call(getattr(psd, "has_thumbnail", lambda: False))),
    }


def _read_icc_name(psd) -> str | None:
    """Best-effort ICC profile name from image_resources."""
    try:
        from psd_tools.constants import Resource
        res = psd.image_resources
        if Resource.ICC_PROFILE in res:
            blob = res[Resource.ICC_PROFILE].data
            if isinstance(blob, (bytes, bytearray)) and len(blob) >= 132:
                desc = blob[:1024].decode("ascii", errors="ignore")
                for marker in ("Adobe RGB", "sRGB", "ProPhoto", "Display P3", "ColorMatch", "Apple RGB", "Generic RGB", "Nikon"):
                    if marker.lower() in desc.lower():
                        return marker
                return f"icc_profile_{len(blob)}bytes"
    except Exception:
        pass
    return None


def _safe_call(fn):
    try:
        return fn() if callable(fn) else fn
    except Exception:
        return None


def _populate_layers(fp: Fingerprint, psd) -> None:
    total = 0
    groups = 0
    smart_objects = 0
    type_layers = 0
    pixel_layers = 0
    fills = 0
    shapes = 0
    with_mask = 0
    adjustment_breakdown: dict[str, int] = {}
    blend_modes: dict[str, int] = {}
    opacity_buckets: dict[str, int] = {"100": 0, "70-99": 0, "30-69": 0, "<30": 0, "unknown": 0}
    text_snippets: list[str] = []

    for layer in psd.descendants():
        total += 1
        kind_raw = getattr(layer, "kind", "") or ""
        kind = _normalize_kind(kind_raw)

        if kind == "group":
            groups += 1
        elif kind == "smart_object":
            smart_objects += 1
        elif kind == "text":
            type_layers += 1
            snippet = _read_text_snippet(layer)
            if snippet and len(text_snippets) < 12:
                text_snippets.append(snippet)
        elif kind == "pixel":
            pixel_layers += 1
        elif kind == "fill":
            fills += 1
        elif kind == "shape":
            shapes += 1
        elif kind == "adjustment":
            label = _adjustment_label(kind_raw) or kind_raw
            adjustment_breakdown[label] = adjustment_breakdown.get(label, 0) + 1

        bm = _blend_mode_str(layer)
        blend_modes[bm] = blend_modes.get(bm, 0) + 1

        opacity = getattr(layer, "opacity", None)
        opacity_buckets[_opacity_bucket(opacity)] += 1

        if _has_mask(layer):
            with_mask += 1

    fp.layers = {
        "total": total,
        "groups": groups,
        "smart_objects": smart_objects,
        "type_layers": type_layers,
        "pixel_layers": pixel_layers,
        "fill_layers": fills,
        "shape_layers": shapes,
        "with_mask": with_mask,
        "adjustment_breakdown": adjustment_breakdown,
        "blend_mode_histogram": blend_modes,
        "opacity_buckets": opacity_buckets,
    }
    fp.text_snippets = text_snippets


# ---------------------------------------------------------------------------
# Backwards-compat helper for inferrer.py
# ---------------------------------------------------------------------------

def read_basic_metadata(path: Path) -> dict:
    """Returns the small dict shape that `inferrer._read_psd_metadata` used:
        { color_mode, layer_count, width, height, channel_count }

    Implemented by calling `introspect()` and projecting the relevant fields.
    Gracefully degrades on any error.
    """
    fp = introspect(path)
    if fp.error and not fp.image:
        return {}
    out: dict = {}
    if fp.image.get("color_mode"):
        out["color_mode"] = fp.image["color_mode"]
    if fp.image.get("width"):
        out["width"] = fp.image["width"]
    if fp.image.get("height"):
        out["height"] = fp.image["height"]
    if fp.image.get("channels"):
        out["channel_count"] = fp.image["channels"]
    if fp.layers.get("total") is not None:
        out["layer_count"] = fp.layers["total"]
    return out


# ---------------------------------------------------------------------------
# Thumbnail extraction
# ---------------------------------------------------------------------------

def extract_thumbnail(
    path: Path,
    output_path: Path,
    max_size: int = 512,
    composite_threshold_bytes: int = 500_000_000,
    timeout_seconds: int = 60,
) -> tuple[bool, str]:
    """Generate a thumbnail JPG at `output_path`.

    Strategy:
      1. Use the embedded PSD thumbnail if present (free, no pixel decode).
      2. Else, for files under `composite_threshold_bytes`, run psd.composite()
         at low res.
      3. Else, give up and return False.

    Returns (success, method) where method is one of: 'embedded', 'composite',
    'skip_size', 'no_thumb', 'error'.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    size = path.stat().st_size

    try:
        with _timeout(timeout_seconds):
            from psd_tools import PSDImage

            psd = PSDImage.open(str(path))

            if _safe_call(getattr(psd, "has_thumbnail", lambda: False)):
                thumb = _safe_call(getattr(psd, "thumbnail", None))
                if thumb is not None:
                    thumb.thumbnail((max_size, max_size))
                    thumb.convert("RGB").save(output_path, "JPEG", quality=85)
                    return True, "embedded"

            if size > composite_threshold_bytes:
                return False, "skip_size"

            img = psd.composite()
            if img is None:
                return False, "no_thumb"
            img.thumbnail((max_size, max_size))
            img.convert("RGB").save(output_path, "JPEG", quality=85)
            return True, "composite"
    except IntrospectionTimeout:
        return False, "timeout"
    except Exception as e:
        return False, f"error:{type(e).__name__}"


# ---------------------------------------------------------------------------
# JSONL helpers (used by style_miner)
# ---------------------------------------------------------------------------

def write_fingerprint_jsonl(fp: Fingerprint, jsonl_path: Path) -> None:
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(fp.to_dict(), ensure_ascii=False) + "\n")


def read_fingerprints_jsonl(jsonl_path: Path) -> list[Fingerprint]:
    if not jsonl_path.exists():
        return []
    out: list[Fingerprint] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(Fingerprint.from_dict(json.loads(line)))
            except Exception:
                continue
    return out


def already_fingerprinted_paths(jsonl_path: Path) -> set[str]:
    """Return set of paths already in the JSONL (for resume)."""
    if not jsonl_path.exists():
        return set()
    seen: set[str] = set()
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                seen.add(json.loads(line)["path"])
            except Exception:
                continue
    return seen
