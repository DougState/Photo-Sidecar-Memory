# Changelog

## V1 — "Weekend CLI" (Approach A) ✓

> Ref: `gstack-plan.md` line 57 — Approach A: "Weekend CLI" (Minimal Viable)

Python CLI with taste.md, rawpy for preview extraction, vision API scoring,
and XMP sidecar-based Bridge integration. Five commands: `ingest`, `score`,
`route`, `report`, `xmp`.

### What shipped

- **CLI foundation** — Click-based entry point with per-run `--tag` support
- **NEF ingest** — rawpy extracts embedded JPEG previews; exiftool reads
  gold-standard EXIF (camera, lens, aperture, ISO, shutter, focal length)
- **Vision API scoring** — Sends preview + taste.md context to Claude/OpenAI;
  returns per-channel confidence with reasoning
- **Per-channel reports** — Markdown report with inline thumbnails grouped by
  channel assignment
- **XMP sidecar output** — Writes `.xmp` files next to each NEF so Adobe
  Bridge displays star ratings (from confidence), channel-name labels, and
  structured `ba:*` keywords for filtering
- **elimstat-product excluded** — Product shoot channel filtered from Bridge
  output (separate workflow)

### Commits

- `5c17689` Initial commit: bridge-assist photo sorting tool with NXD presets
- `ccb4042` Add README with project overview, usage, and channel documentation
- `41f9a75` Add design document for taste-driven RAW photo router
- `7a439f2` Add gstack skill routing rules to CLAUDE.md
- `24ca70a` Fix working dir resolution, image resize for API limits, and OpenAI detail level
- `2dbd3c9` Add per-run tag support and per-channel report layout
- `0fafe74` Use exiftool for gold-standard EXIF extraction from NEF files
- `8eaeff7` Add XMP sidecar command for Adobe Bridge integration
- `9f7c0ff` Use channel names as XMP labels, drop elimstat-product from Bridge output

### Status

- [x] `ingest` — NEF preview extraction + EXIF manifest
- [x] `score` — Vision API channel scoring
- [x] `route` — Symlink-based routing to channel directories
- [x] `report` — Markdown report generation
- [x] `xmp` — Adobe Bridge sidecar integration

### What's next (V2 — Approach B: "Taste Engine")

> Ref: `gstack-plan.md` line 67

Feedback loop: watch for PSD saves, diff RAW vs. final output, propose
taste.md amendments. Git-versioned taste history. SQLite for scoring accuracy
tracking over time.
