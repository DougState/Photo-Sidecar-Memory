"""Score module: vision API scoring with adapter layer for Claude and OpenAI."""

import base64
import json
import os
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from .taste_parser import TasteProfile, parse_taste_file


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_scoring_prompt(profile: TasteProfile, exif: dict) -> str:
    """Build the vision API prompt from taste profile and EXIF data."""
    global_prefs = "\n".join(f"- {p}" for p in profile.global_preferences)

    channels_block = ""
    for ch in profile.channels:
        channels_block += f"""
### {ch.name}
- Intent: {ch.intent}
- Signals: {ch.signals}
"""

    return f"""You are evaluating a photograph for multiple creative workflow channels.

PHOTOGRAPHER'S GLOBAL PREFERENCES:
{global_prefs}

EXIF DATA:
- Camera: {exif.get('camera_model', 'Unknown')}
- Lens: {exif.get('lens', 'Unknown')}
- Focal length: {exif.get('focal_length', 'Unknown')}mm
- Aperture: f/{exif.get('aperture', 'Unknown')}
- ISO: {exif.get('iso', 'Unknown')}
- Shutter: {exif.get('shutter_speed', 'Unknown')}

Score this image for ALL of the following channels. For each, rate suitability from 0.0 to 1.0.

CHANNELS:
{channels_block}

Return ONLY a JSON array with no other text:
[
  {{"channel": "channel-name", "confidence": 0.82, "reasoning": "brief explanation..."}},
  ...
]

Score every channel listed above. Be calibrated:
- 0.9-1.0: Definitely process for this channel
- 0.7-0.9: Strong candidate
- 0.5-0.7: Maybe, depends on the rest of the shoot
- Below 0.5: Probably not"""


MAX_IMAGE_DIMENSION = 2048
MAX_BASE64_BYTES = 4_500_000  # Stay under 5MB API limit after encoding overhead


def encode_image_base64(image_path: Path) -> str:
    """Read an image, resize if needed for API limits, return base64-encoded string."""
    from PIL import Image
    import io

    with Image.open(image_path) as img:
        w, h = img.size
        if max(w, h) > MAX_IMAGE_DIMENSION:
            img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.LANCZOS)

        buf = io.BytesIO()
        quality = 85
        img.save(buf, format="JPEG", quality=quality)

        while buf.tell() > MAX_BASE64_BYTES and quality > 40:
            quality -= 10
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)

        return base64.b64encode(buf.getvalue()).decode("utf-8")


def parse_scores_response(response_text: str, expected_channels: list[str]) -> list[dict]:
    """Parse the JSON array from a vision API response.

    Strategy:
    1. Try direct JSON parse
    2. Regex extract first [...] array
    3. Raise on failure
    """
    # Strategy 1: direct parse
    try:
        result = json.loads(response_text)
        if isinstance(result, list):
            return _validate_scores(result, expected_channels)
    except json.JSONDecodeError:
        pass

    # Strategy 2: regex extract
    match = re.search(r"\[.*\]", response_text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return _validate_scores(result, expected_channels)
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse scores from response: {response_text[:200]}...")


def _validate_scores(scores: list[dict], expected_channels: list[str]) -> list[dict]:
    """Validate and normalize score entries."""
    validated = []
    for entry in scores:
        if not isinstance(entry, dict):
            continue
        channel = entry.get("channel", "")
        confidence = entry.get("confidence", 0)
        reasoning = entry.get("reasoning", "")

        # Clamp confidence to [0, 1]
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.0

        validated.append({
            "channel": channel,
            "confidence": confidence,
            "reasoning": str(reasoning),
        })

    return validated


# ---------------------------------------------------------------------------
# Vision API adapters
# ---------------------------------------------------------------------------

class VisionAdapter(ABC):
    """Abstract base for vision API backends."""

    @abstractmethod
    def score_image(self, image_path: Path, prompt: str) -> str:
        """Send image + prompt to the vision API, return raw response text."""
        ...

    @abstractmethod
    def name(self) -> str:
        ...


class ClaudeVisionAdapter(VisionAdapter):
    """Anthropic Claude vision API adapter."""

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("BRIDGE_ASSIST_API_KEY")
        if not self.api_key:
            raise ValueError("No API key. Set ANTHROPIC_API_KEY or BRIDGE_ASSIST_API_KEY env var.")
        self.model = model

    def name(self) -> str:
        return f"claude ({self.model})"

    def score_image(self, image_path: Path, prompt: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        image_data = encode_image_base64(image_path)

        message = client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        )
        return message.content[0].text


class OpenAIVisionAdapter(VisionAdapter):
    """OpenAI GPT-4 Vision API adapter."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o"):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("BRIDGE_ASSIST_API_KEY")
        if not self.api_key:
            raise ValueError("No API key. Set OPENAI_API_KEY or BRIDGE_ASSIST_API_KEY env var.")
        self.model = model

    def name(self) -> str:
        return f"openai ({self.model})"

    def score_image(self, image_path: Path, prompt: str) -> str:
        import openai

        client = openai.OpenAI(api_key=self.api_key)
        image_data = encode_image_base64(image_path)

        response = client.chat.completions.create(
            model=self.model,
            max_tokens=1024,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_data}",
                                "detail": "high",
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt + "\n\nReturn the result as a JSON object with a 'scores' key containing the array.",
                        },
                    ],
                }
            ],
        )
        text = response.choices[0].message.content
        # OpenAI JSON mode wraps in an object — extract the array
        try:
            obj = json.loads(text)
            if "scores" in obj:
                return json.dumps(obj["scores"])
        except (json.JSONDecodeError, TypeError):
            pass
        return text


def get_adapter(backend: str = "claude", api_key: str | None = None) -> VisionAdapter:
    """Factory: get a vision adapter by name."""
    if backend == "claude":
        return ClaudeVisionAdapter(api_key=api_key)
    elif backend == "openai":
        return OpenAIVisionAdapter(api_key=api_key)
    else:
        raise ValueError(f"Unknown backend: {backend}. Use 'claude' or 'openai'.")


# ---------------------------------------------------------------------------
# Main scoring pipeline
# ---------------------------------------------------------------------------

def score_all(
    working_dir: Path,
    taste_path: Path,
    backend: str = "claude",
    api_key: str | None = None,
    only_unscored: bool = False,
    retry_on_failure: bool = True,
) -> dict:
    """Score all ingested images against taste.md channels.

    Reads manifest.json from working_dir, scores each image via the vision API,
    and writes scores.json to working_dir.
    """
    working_dir = Path(working_dir).resolve()
    manifest_path = working_dir / "manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No manifest.json found in {working_dir}. Run 'bridge-assist ingest' first."
        )

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Parse taste profile
    profile = parse_taste_file(taste_path)
    channel_names = profile.channel_names()

    # Load existing scores if only_unscored
    scores_path = working_dir / "scores.json"
    existing_scores = {}
    if only_unscored and scores_path.exists():
        with open(scores_path) as f:
            existing_data = json.load(f)
            existing_scores = existing_data.get("scores", {})

    # Initialize adapter
    adapter = get_adapter(backend, api_key)
    print(f"Scoring with {adapter.name()}")
    print(f"Channels: {', '.join(channel_names)}")

    scores = dict(existing_scores)  # Start from existing if any
    errors = []
    files = manifest.get("files", {})
    total = len(files)

    for i, (filename, file_info) in enumerate(files.items(), 1):
        if only_unscored and filename in existing_scores:
            print(f"  [{i}/{total}] {filename}... CACHED")
            continue

        preview_path = Path(file_info["preview_path"])
        if not preview_path.exists():
            errors.append({"file": filename, "error": "preview file missing"})
            print(f"  [{i}/{total}] {filename}... MISSING PREVIEW")
            continue

        exif = file_info.get("exif", {})
        prompt = build_scoring_prompt(profile, exif)

        print(f"  [{i}/{total}] {filename}...", end=" ", flush=True)

        # Score with retry
        for attempt in range(2 if retry_on_failure else 1):
            try:
                response_text = adapter.score_image(preview_path, prompt)
                image_scores = parse_scores_response(response_text, channel_names)
                scores[filename] = {
                    "scores": image_scores,
                    "scored_at": datetime.now().isoformat(),
                    "backend": adapter.name(),
                }
                print("OK")
                break
            except Exception as e:
                if attempt == 0 and retry_on_failure:
                    print(f"RETRY ({e})...", end=" ", flush=True)
                    time.sleep(1)
                else:
                    errors.append({"file": filename, "error": str(e)})
                    print(f"ERROR: {e}")

    # Write scores.json
    scores_data = {
        "taste_file": str(taste_path),
        "backend": adapter.name(),
        "scored_at": datetime.now().isoformat(),
        "total_scored": len(scores),
        "total_errors": len(errors),
        "channel_names": channel_names,
        "scores": scores,
        "errors": errors,
    }

    with open(scores_path, "w") as f:
        json.dump(scores_data, f, indent=2)

    print(f"\nScored {len(scores)} images, {len(errors)} errors")
    print(f"Scores: {scores_path}")

    return scores_data
