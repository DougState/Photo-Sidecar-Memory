"""Match processed files (PSD/TIFF) back to their source NEF via filename stem.

Handles common Photoshop naming patterns:
  _FWR5464.psd          -> _FWR5464.NEF (exact match)
  _FWR5464-edit.tif     -> _FWR5464.NEF (suffix stripped)
  _FWR5464 copy.tif     -> _FWR5464.NEF (Photoshop "copy" suffix)
  _FWR2677-polulu.tif   -> _FWR2677.NEF (descriptive suffix stripped)
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

WATCHED_EXTENSIONS = {".psd", ".psb", ".tif", ".tiff"}

STRIP_SUFFIXES = re.compile(
    r"(?:"
    r"\s*copy(?:\s*\d+)?"   # " copy", " copy 2"
    r"|-\w[\w-]*"           # "-edit", "-layer", "-polulu-overlook"
    r"|\s+\(\d+\)"          # " (1)", " (2)"
    r")+$",
    re.IGNORECASE,
)


@dataclass
class MatchResult:
    processed_path: Path
    nef_filename: str | None
    nef_path: str | None
    match_method: str
    confidence: float


def _extract_camera_prefix(stem: str) -> str | None:
    """Extract the camera-generated prefix (e.g. '_FWR5464', '_BIG0894').

    D800 filenames start with an optional underscore, then 3 uppercase letters,
    then 4 digits.
    """
    m = re.match(r"^(_?[A-Z]{3,4}\d{4,5})", stem)
    return m.group(1) if m else None


def _candidate_stems(processed_path: Path) -> list[str]:
    """Generate candidate NEF stems from a processed filename, ordered by specificity."""
    stem = processed_path.stem
    candidates = [stem]

    stripped = STRIP_SUFFIXES.sub("", stem)
    if stripped != stem:
        candidates.append(stripped)

    prefix = _extract_camera_prefix(stem)
    if prefix and prefix not in candidates:
        candidates.append(prefix)

    return candidates


def match_to_nef(
    processed_path: Path,
    manifest: dict,
) -> MatchResult:
    """Match a processed file to its source NEF using the manifest.

    Tries exact stem match first, then progressively strips suffixes.
    """
    if processed_path.suffix.lower() not in WATCHED_EXTENSIONS:
        return MatchResult(
            processed_path=processed_path,
            nef_filename=None,
            nef_path=None,
            match_method="unsupported_extension",
            confidence=0.0,
        )

    files = manifest.get("files", {})
    candidates = _candidate_stems(processed_path)

    for i, candidate in enumerate(candidates):
        for nef_filename in files:
            nef_stem = Path(nef_filename).stem
            if nef_stem.lower() == candidate.lower():
                method = "exact" if i == 0 else ("stripped" if i == 1 else "prefix")
                conf = 1.0 if method == "exact" else (0.9 if method == "stripped" else 0.8)
                return MatchResult(
                    processed_path=processed_path,
                    nef_filename=nef_filename,
                    nef_path=files[nef_filename].get("nef_path"),
                    match_method=method,
                    confidence=conf,
                )

    return MatchResult(
        processed_path=processed_path,
        nef_filename=None,
        nef_path=None,
        match_method="no_match",
        confidence=0.0,
    )


def load_manifest(manifest_path: Path) -> dict:
    """Load a manifest JSON file."""
    with open(manifest_path) as f:
        return json.load(f)


def load_scores(scores_path: Path) -> dict:
    """Load a scores JSON file."""
    with open(scores_path) as f:
        return json.load(f)


def get_original_scores(nef_filename: str, scores_data: dict) -> list[dict]:
    """Retrieve the original AI scores for a given NEF filename."""
    entry = scores_data.get("scores", {}).get(nef_filename)
    if entry:
        return entry.get("scores", [])
    return []
