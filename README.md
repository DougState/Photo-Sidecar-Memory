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
git clone https://github.com/DougState/Photo-Sidecar-Memory.git
cd Photo-Sidecar-Memory
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

### Adobe Bridge Integration

```bash
# Write XMP sidecar files next to each NEF for Bridge to read
bridge-assist xmp --tag hawaii-2026
bridge-assist xmp --dry-run         # Preview without writing
bridge-assist xmp --clean           # Remove old sidecars before writing
```

Bridge displays star ratings (from confidence), channel-name labels, and `ba:*` keywords for filtering.

### Taste Engine (Feedback Loop)

Record what you actually process to track AI accuracy over time:

```bash
# Record feedback for a single processed file
bridge-assist record /path/to/Photoshop/_FWR5471.psd --tag hawaii-2026

# Batch-record all PSD/TIFF files in a directory
bridge-assist record-dir /path/to/CaptureOne/ --tag hawaii-2026

# View recent feedback entries
bridge-assist feedback --tag hawaii-2026

# Aggregated stats per channel (confirmations vs corrections)
bridge-assist feedback --summary --tag hawaii-2026

# AI accuracy report — the "learning curve" metric
bridge-assist feedback --accuracy --tag hawaii-2026
```

The system matches processed files back to source NEFs by filename stem, infers the channel from folder context (Photoshop/ → composite-base, CaptureOne/ → soft-warms, FilmPack/ → bw-monochrome) and file metadata (PSD layer count, color mode, ICC profile), then records whether the AI's original score was confirmed or corrected.

### Style Mining (Discover Output Styles from Photoshop History)

`taste.md` defines *input routing* (where a NEF should go). `STYLES.md` defines *output styles* (how an image is actually edited). The `mine-styles` command derives the latter by walking a folder of finished and in-progress PSD/PSB files, fingerprinting each one mechanically (layer trees, blend modes, adjustment kinds, masks, smart objects, text), grouping iteration chains save-to-save, clustering similar fingerprints, and asking Claude to name each cluster from thumbnails plus the mechanical signal.

```bash
# Walk a corpus of PSDs/PSBs and produce a draft style library
bridge-assist mine-styles "/Volumes/Mauna Kea/PS Works"

# Skip thumbs + vision for a fast mechanical-only pass (no API spend)
bridge-assist mine-styles --skip-thumbs --skip-vision "/Volumes/Mauna Kea/PS Works"

# Limit for smoke-testing
bridge-assist mine-styles --limit 25 --skip-vision "/Volumes/Mauna Kea/PS Works"

# Inspect cluster sizes, top features, and the draft path
bridge-assist styles-report

# Drill into a single cluster (sources + chain diffs)
bridge-assist styles-inspect 3
```

Output lands in `.bridge-assist/styles/` (gitignored): `fingerprints.jsonl`, `chain_diffs.jsonl`, `thumbs/`, `candidate_styles.json`, `styles_draft.md`. Review the draft, edit cluster names/intents/signals/example outputs by hand, then promote the file to project-root `STYLES.md` and commit. The pipeline is resume-safe — interrupt at any time and re-run.

Files larger than 1GB are recorded with partial metadata only (path/size/mtime/tier/chain) and skipped from the layer walk to avoid OOM on multi-GB PSBs. They still participate in chain detection.

## Output Structure

```
.bridge-assist/
  previews/           # Extracted JPEG previews
  manifest.json       # EXIF data + file metadata
  scores.json         # Vision API scoring results
  feedback.db         # SQLite feedback database (taste engine)
  routes/
    soft-warms/       # Symlinks to NEFs + warm-graded proof JPEGs
    soft-greens/      # Symlinks to NEFs + green-graded proof JPEGs
    composite-base/   # Symlinks to NEFs + full-res TIF proofs
    instagram/        # Symlinks to NEFs + 1080px cropped JPEGs
    ...
  styles/             # Style mining outputs (mine-styles)
    fingerprints.jsonl
    chain_diffs.jsonl
    thumbs/
    candidate_styles.json
    styles_draft.md   # Review and promote to project-root STYLES.md
```

## Cost

Single-pass multi-channel scoring keeps API costs low. A 100-image shoot costs under $5. Each image is scored for all channels in one API call (~$0.02-0.05 per image).

## Roadmap

**v1:** CLI with taste.md, rawpy preview extraction, vision API scoring, symlink routing, ImageMagick derivatives, Markdown reports, XMP sidecar output for Adobe Bridge.

**v2 (in progress):** Taste engine feedback loop — matches processed PSD/TIFF files back to source NEFs, infers channels, records confirmations and corrections in SQLite. Accuracy tracking over time. Style mining — discovers output styles from a corpus of edited PSDs/PSBs (`mine-styles`) and produces a draft `STYLES.md`. Next: live file watcher, taste.md amendment proposals, vision-naming refinement.

## License

MIT
