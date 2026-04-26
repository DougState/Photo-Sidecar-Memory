# Changelog

## V2 — "Taste Engine" (Approach B) — in progress

> Ref: `gstack-plan.md` line 67 — Approach B: feedback loop + taste history

Feedback loop for processed PSDs/TIFFs and a style discovery pipeline that
reverse-engineers output styles from a corpus of edited Photoshop files.
`taste.md` keeps defining input routing (where a NEF should go); the new
`STYLES.md` defines output styles (how the image is actually edited).

### What shipped

- **Taste engine Phase 1** — `record-feedback` matches processed PSD/TIFF files
  back to source NEFs via filename stem (strips Bridge/edit suffixes), reads
  PSD metadata without decoding pixels, infers the channel from layer counts,
  color mode, and metadata signals, and writes confirmations + corrections to
  SQLite (`feedback.db`). Includes `feedback-stats` for accuracy tracking.
- **XMP sidecar workflow** — `xmp` writes `.xmp` files next to each NEF so
  Adobe Bridge displays star ratings (from confidence), channel names as
  labels, and `ba:*` keywords for filtering. `elimstat-product` excluded from
  Bridge output (separate workflow).
- **Style mining** — `mine-styles` walks a folder of finished and in-progress
  PSD/PSB files, fingerprints each one mechanically (layer trees, blend modes,
  adjustment kinds, masks, smart objects, text), groups iteration chains
  save-to-save, clusters similar fingerprints (HDBSCAN with KMeans fallback),
  and asks Claude to name each cluster from thumbnails plus the mechanical
  signal. Produces a draft `STYLES.md` for human review.
- **`psd_introspect` module** — shared lazy PSD reader used by both the
  inferrer and the style miner. Handles partial introspection for files
  larger than 1GB (basic metadata only, no layer walk) so multi-GB PSBs do
  not OOM the process. Per-file timeout (default 120s) and resumable
  fingerprint extraction via JSONL cache.
- **`mine-styles`, `styles-report`, `styles-inspect`** — three new CLI
  commands. Resume-safe: interrupt at any time and re-run.

### Commits (so far)

- `2f4399d` Add taste engine Phase 1: feedback recording from processed PSD/TIFF files
- `199eede` Document XMP sidecar and taste engine CLI commands in README

### What's next (V2 continued)

- Live file watcher for PSD saves (auto-record feedback on save)
- `taste.md` amendment proposals from feedback drift
- Promote `styles_draft.md` → `STYLES.md` and wire it into the routing prompt
- Vision-naming refinement (per-cluster thumb count, prompt iteration)

---

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
