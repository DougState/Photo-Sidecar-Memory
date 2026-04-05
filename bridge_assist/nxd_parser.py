"""Parse Nikon Capture NX-D (.nxd) preset files.

NXD files are XMP-based XML containing Nikon-specific adjustment parameters.
This module extracts the creative parameters that define each preset's intent:
tone curves, LCH adjustments, picture control settings, white balance, exposure.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class NXDPreset:
    """Parsed NXD preset with creative parameters."""
    name: str
    path: str
    family: str  # e.g., "NXD Soft Warms", "NXD Elimstat"
    subfamily: str  # e.g., "Browns Golds Oranges", "BW"

    # Exposure
    exposure: float = 0.0

    # Picture Control
    contrast: int = 0
    saturation: int = 0
    hue: int = 0
    brightness: int = 0
    sharpening: int = 0

    # White Balance
    color_temp: int = 0
    wb_method: str = ""

    # Tone curves
    rgb_gamma: float = 1.0
    tone_curve_points: int = 0

    # LCH
    lch_gamma: float = 1.0
    lch_chroma_points: int = 0
    lch_hue_points: int = 0

    @property
    def is_neutral(self) -> bool:
        """True if preset applies minimal creative adjustment."""
        return (
            self.contrast == 0
            and self.saturation == 0
            and self.hue == 0
            and self.lch_chroma_points == 0
        )

    @property
    def is_warm_grade(self) -> bool:
        """True if preset matches the Soft Warms signature."""
        return (
            self.contrast <= -100
            and self.saturation >= 100
            and self.hue <= -100
            and self.lch_gamma < 1.0
        )

    @property
    def is_green_grade(self) -> bool:
        """True if preset matches the Soft Greens signature."""
        return (
            self.contrast <= -100
            and self.saturation >= 100
            and self.color_temp > 5500
            and self.lch_gamma >= 1.0
        )

    def summary(self) -> str:
        """One-line human-readable summary."""
        flags = []
        if self.is_neutral:
            flags.append("neutral")
        if self.is_warm_grade:
            flags.append("warm-grade")
        if self.is_green_grade:
            flags.append("green-grade")
        if self.exposure != 0:
            flags.append(f"exp {self.exposure:+.1f}")
        return f"{self.name} ({self.family}/{self.subfamily}) [{', '.join(flags) or 'styled'}]"


def _get_param(text: str, tag: str, default: str = "0") -> str:
    """Extract a single parameter value from NXD XMP text."""
    m = re.search(rf"<BASIC_PARAM:{tag}>(.*?)</BASIC_PARAM:{tag}>", text)
    return m.group(1) if m else default


def parse_nxd_file(filepath: Path) -> NXDPreset:
    """Parse a single .nxd file into an NXDPreset."""
    filepath = Path(filepath)

    with open(filepath, "r", errors="replace") as f:
        text = f.read()

    # Determine family and subfamily from directory structure
    parts = filepath.parts
    name = filepath.stem
    family = ""
    subfamily = ""

    # Known family directory names (skip "NXD Presets" which is the container)
    FAMILY_NAMES = {"NXD Soft Warms", "NXD Soft Greens", "NXD Elimstat", "D800 Settings"}

    for i, part in enumerate(parts):
        if part in FAMILY_NAMES:
            family = part
            if i + 1 < len(parts) and parts[i + 1] != filepath.name:
                subfamily = parts[i + 1]
            break

    def _float(val: str) -> float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    def _int(val: str) -> int:
        try:
            return int(round(float(val)))
        except (ValueError, TypeError):
            return 0

    return NXDPreset(
        name=name,
        path=str(filepath),
        family=family,
        subfamily=subfamily,
        exposure=_float(_get_param(text, "EXP")),
        contrast=_int(_get_param(text, "PC_LATEST_CONTRAST")),
        saturation=_int(_get_param(text, "PC_LATEST_SATURATION")),
        hue=_int(_get_param(text, "PC_LATEST_HUE")),
        brightness=_int(_get_param(text, "PC_LATEST_BRIGHTNESS")),
        sharpening=_int(_get_param(text, "PC_LATEST_SHAPENING")),
        color_temp=_int(_get_param(text, "WB_COLORTEMP")),
        wb_method=_get_param(text, "WB_METHOD", ""),
        rgb_gamma=_float(_get_param(text, "TC_RGB_GAMMA", "1")),
        tone_curve_points=_int(_get_param(text, "TC_RGB_TABLE_POINT_COUNT")),
        lch_gamma=_float(_get_param(text, "LCH_ML_GAMMA", "1")),
        lch_chroma_points=_int(_get_param(text, "LCH_CR_TABLE_POINT_COUNT")),
        lch_hue_points=_int(_get_param(text, "LCH_HU_TABLE_POINT_COUNT")),
    )


def scan_preset_directory(preset_dir: Path) -> list[NXDPreset]:
    """Recursively scan a directory for .nxd and .NCP preset files."""
    preset_dir = Path(preset_dir)
    presets = []

    if not preset_dir.is_dir():
        return presets

    for root, dirs, files in os.walk(preset_dir):
        for filename in sorted(files):
            filepath = Path(root) / filename
            if filepath.suffix.lower() in (".nxd",):
                try:
                    preset = parse_nxd_file(filepath)
                    presets.append(preset)
                except Exception as e:
                    print(f"  WARNING: Could not parse {filepath.name}: {e}")

    return presets


def summarize_presets(presets: list[NXDPreset]) -> str:
    """Generate a human-readable summary of a preset collection."""
    if not presets:
        return "No presets found."

    lines = [f"Found {len(presets)} presets:\n"]

    # Group by family
    families: dict[str, list[NXDPreset]] = {}
    for p in presets:
        key = p.family or "Unknown"
        families.setdefault(key, []).append(p)

    for family, family_presets in sorted(families.items()):
        lines.append(f"  {family} ({len(family_presets)} presets)")
        for p in family_presets:
            lines.append(f"    {p.summary()}")

    return "\n".join(lines)
