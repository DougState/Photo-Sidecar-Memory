"""Parse taste.md into structured channel definitions and global preferences."""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Channel:
    name: str
    intent: str = ""
    signals: str = ""
    output: str = ""
    confidence_threshold: float = 0.5


@dataclass
class TasteProfile:
    channels: list[Channel] = field(default_factory=list)
    global_preferences: list[str] = field(default_factory=list)

    def get_channel(self, name: str) -> Channel | None:
        for ch in self.channels:
            if ch.name == name:
                return ch
        return None

    def channel_names(self) -> list[str]:
        return [ch.name for ch in self.channels]


def parse_taste_file(taste_path: Path) -> TasteProfile:
    """Parse a taste.md file into a TasteProfile.

    Expected format:
      ## Channels
      ### channel-name
      - Intent: ...
      - Signals: ...
      - Output: ...
      - Confidence threshold: 0.75

      ## Global Preferences
      - Preference 1
      - Preference 2
    """
    taste_path = Path(taste_path)
    if not taste_path.exists():
        raise FileNotFoundError(f"Taste file not found: {taste_path}")

    text = taste_path.read_text()
    profile = TasteProfile()

    # Split into sections by ## headers
    sections = re.split(r"^## ", text, flags=re.MULTILINE)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        if section.startswith("Channels"):
            # Parse each ### channel
            channel_blocks = re.split(r"^### ", section, flags=re.MULTILINE)
            for block in channel_blocks[1:]:  # skip the "Channels" header itself
                channel = _parse_channel_block(block)
                if channel:
                    profile.channels.append(channel)

        elif section.startswith("Global Preferences"):
            lines = section.split("\n")[1:]  # skip header line
            for line in lines:
                line = line.strip()
                if line.startswith("- "):
                    profile.global_preferences.append(line[2:].strip())

    return profile


def _parse_channel_block(block: str) -> Channel | None:
    """Parse a single channel block from taste.md."""
    lines = block.strip().split("\n")
    if not lines:
        return None

    name = lines[0].strip()
    channel = Channel(name=name)

    for line in lines[1:]:
        line = line.strip()
        if line.startswith("- Intent:"):
            channel.intent = line.split(":", 1)[1].strip()
        elif line.startswith("- Signals:"):
            channel.signals = line.split(":", 1)[1].strip()
        elif line.startswith("- Output:"):
            channel.output = line.split(":", 1)[1].strip()
        elif line.startswith("- Confidence threshold:"):
            try:
                channel.confidence_threshold = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass

    return channel


def validate_taste_file(taste_path: Path) -> list[str]:
    """Validate a taste.md file. Returns a list of error messages (empty = valid)."""
    errors = []

    try:
        profile = parse_taste_file(taste_path)
    except FileNotFoundError as e:
        return [str(e)]

    if not profile.channels:
        errors.append("No channels defined. Expected ## Channels section with ### channel-name subsections.")

    for ch in profile.channels:
        if not ch.intent:
            errors.append(f"Channel '{ch.name}': missing Intent field")
        if not ch.signals:
            errors.append(f"Channel '{ch.name}': missing Signals field")
        if not ch.output:
            errors.append(f"Channel '{ch.name}': missing Output field")
        if ch.confidence_threshold < 0 or ch.confidence_threshold > 1:
            errors.append(f"Channel '{ch.name}': confidence threshold {ch.confidence_threshold} out of range [0, 1]")

    return errors
