# Bridge Assist — Taste-Driven RAW Photo Router

A CLI tool that automatically sorts and routes Nikon D800 NEF files into workflow channels based on post-process intent. Instead of manually rating files in Adobe Bridge, Bridge Assist reads a human-authored `taste.md` specification and uses vision AI to score each photo against your creative channels — then routes and prepares derivative outputs.

This isn't a photo quality sorter. It's a **post-process intent engine**. It answers: *"What does this RAW file want to become?"* A warm-toned Tuscany 1968 composite? A garden shade green grade? An Instagram square? A product catalog hero shot?

## How It Works

```
NEF files → extract preview → vision API scores against taste.md → route to channels → generate derivatives
```

1. **Ingest** — Extracts embedded JPEG previews from D800 NEF files (instant, no full RAW decode) and reads EXIF metadata into a manifest.
2. **Score** — Sends each preview + EXIF + taste.md context to a vision API in a single call that scores ALL channels simultaneously (~$0.02-0.05 per image).
3. **Route** — Creates channel directories with symlinks to original NEFs plus derivative outputs (proof-quality JPEGs/TIFs generated via ImageMagick from the extracted previews).
4. **Report** — Generates a Markdown summary with thumbnails, scores, and channel assignments.

Images can land in multiple channels. A woodland scene might score above threshold for both `soft-warms` and `composite-base`.

## Channels

Bridge Assist routes to channels defined in `taste.md`. The default profile includes:

| Channel | Intent | Key Signals |
|---------|--------|-------------|
| **soft-warms** | Artistic warm grade via NX-D presets (Tuscany 1968, France 1968). TIF for print, sRGB JPG for web. | Rich tonal range, warm natural light, earthy tones, foreground-to-background depth |
| **soft-greens** | Natural green-toned treatment. Garden and shade photography. | Lush vegetation, garden scenes, green foliage dominant, cooler palette |
| **composite-base** | Base layer for multi-layer Photoshop PSB/PSD composites. | Good subject-background separation, clean edges, narrative possibilities |
| **bw-monochrome** | Black and white via D800 MONOCHROME Picture Controls (1960s vintage, Severe high-contrast). | Strong shapes, dramatic contrast, form over color |
| **instagram** | Social media, square or 4:5 crop. | Visual impact at small size, survives aggressive cropping, scroll-stopping |

## taste.md

The taste file is the product. It's a human-readable, version-controlled specification of your creative judgment — diffable, forkable, shareable. It defines:

- **Channels** with intent, visual signals, NXD preset families, output specs, and confidence thresholds
- **Global preferences** that apply across all channels
- **Confidence calibration** (0.9+ = definitely process, 0.7-0.9 = strong candidate, 0.5-0.7 = maybe, <0.5 = probably not)

Each channel references specific Nikon Capture NX-D preset families included in `NXD Presets/`. These encode tone curves, LCH adjustments, picture controls, white balance, and exposure compensation as XMP metadata.

## Installation

Requires Python 3.11+ and [ImageMagick](https://imagemagick.org/).

```bash
git clone https://github.com/DougState/AI-Photo-Sort.git
cd AI-Photo-Sort
pip install -r requirements.txt
```

Or install as a package:

```bash
pip install -e .
```

## Usage

```bash
# Set your API key
export BRIDGE_ASSIST_API_KEY=sk-...

# 1. Extract previews and EXIF from a folder of NEFs
bridge-assist ingest ./raw-folder

# 2. Score against taste.md channels (single API call per image)
bridge-assist score --taste ./taste.md

# 3. Route to channel directories with symlinks + derivative outputs
bridge-assist route
bridge-assist route --threshold 0.7   # Override all per-channel thresholds
bridge-assist route --dry-run         # Preview routing without creating files
bridge-assist route --clean           # Remove previous outputs before re-routing

# 4. Generate a Markdown report
bridge-assist report --output ./sort-report.md
```

Commands run in order: `ingest` -> `score` -> `route` -> `report`. Each is idempotent.

Only `score` calls the vision API. `route` and `report` work entirely from cached `scores.json` and `manifest.json`.

## Output Structure

```
.bridge-assist/
  previews/           # Extracted JPEG previews
  manifest.json       # EXIF data + file metadata
  scores.json         # Vision API scoring results
  routes/
    soft-warms/       # Symlinks to NEFs + warm-graded proof JPEGs
    soft-greens/      # Symlinks to NEFs + green-graded proof JPEGs
    composite-base/   # Symlinks to NEFs + full-res TIF proofs
    instagram/        # Symlinks to NEFs + 1080px cropped JPEGs
    ...
```

## Cost

Single-pass multi-channel scoring keeps API costs low. A 100-image shoot costs under $5. Each image is scored for all channels in one API call (~$0.02-0.05 per image).

## Roadmap

**v1 (current):** CLI with taste.md, rawpy preview extraction, vision API scoring, symlink routing, ImageMagick derivatives, Markdown reports.

**v2:** Feedback loop — watches for PSD saves, diffs RAW vs. final output, proposes taste.md amendments. SQLite scoring history for accuracy tracking over time. The taste.md changelog becomes a diffable record of how your creative eye evolves.

## License

MIT
