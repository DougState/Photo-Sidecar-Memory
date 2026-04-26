# SESSION.md — Bridge-Assist

> Agent-facing state file. Read this first at the start of any Claude session touching this project. User-facing docs live in `README.md`; the original design rationale lives in `gstack-plan.md`; this file tracks *working state*.

---

## 1. Project Context

**What it is:** Bridge-Assist — a CLI tool that automatically sorts and routes Nikon D800 NEF files into workflow channels based on post-process intent. Uses vision AI (Claude or GPT-4o) to score photos against a human-authored `taste.md` specification, then routes them into channel directories with derivative outputs. Not a quality sorter, a **post-process intent engine**.

**Stack:**
- Python 3.11+ (Click CLI framework)
- Vision API backends: Anthropic Claude Sonnet 4, OpenAI GPT-4o (single-backend per run, selectable via `--backend`)
- rawpy for NEF preview extraction, Pillow for image processing, exiftool for EXIF
- ImageMagick for derivative generation (proof JPEGs, TIFs)
- psd-tools + watchdog for taste engine feedback loop
- SQLite for feedback database
- Build: `pip install -e .` via setuptools (`pyproject.toml`)

**Environment:**
- Primary dev/test machine: Mac Mini (macOS, Homebrew Python 3.13)
- Photos stored on external drive "Mauna Kea" (`/Volumes/Mauna Kea/`)
- API keys set via environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)
- Virtual environment at `.venv/` in project root

**Distribution:** GitHub (`DougState/AI-Photo-Sort`), MIT license.

---

## 2. Current State (overwrite each session)

**Version:** 0.1.0 (latest shipped on `main`, commit `199eede`)

**Active branch:** `feature/taste-discovery-ps-works` — taste discovery pipeline (PSD/PSB style mining).

**What works / is stable:**
- Full ingest pipeline: NEF preview extraction (rawpy), EXIF metadata (exiftool), manifest generation
- Vision API scoring: Claude Sonnet 4 and GPT-4o backends, single-call multi-channel scoring, image resize for API limits, retry on failure
- Per-run tagging (`--tag hawaii-2026`): separate manifest/scores/routes/report per run, auto-derived from folder name
- Routing: threshold-based channel assignment, symlink to original NEFs, ImageMagick derivative generation (warm proofs, green proofs, composite TIFs, Instagram crops)
- Per-channel report layout: Markdown report organized by channel (contact sheet style), full reasoning text, confidence bars
- XMP sidecar output for Adobe Bridge: star ratings from confidence, channel-name labels, `ba:*` keywords
- Taste engine Phase 1: `record` and `record-dir` commands match processed PSD/TIFF back to source NEFs, infer channels from folder context and file metadata, store confirmations/corrections in SQLite
- Feedback reporting: `feedback --summary` and `feedback --accuracy` for per-channel stats
- Working directory resolution: `.bridge-assist/` always at project root (cwd), not inside source folder
- taste.md parsing and validation (`bridge-assist validate`)
- **Style mining pipeline (new on `feature/taste-discovery-ps-works`):** `bridge-assist mine-styles`, `styles-report`, `styles-inspect`. Phase 1 walker extracts mechanical fingerprints (layer trees, adjustment histograms, blend modes, masks, text, smart objects) from PSD/PSB without decoding pixels. Phase 2 detects iteration chains (sibling-stem, nested-folder, camera-prefix heuristics) and diffs each chain save-to-save. Phase 3 renders thumbnails (embedded preview, fall back to low-res composite). Phase 4 vectorizes + clusters via HDBSCAN with KMeans fallback. Phase 5 calls Claude on a per-cluster prompt (thumbs + fingerprint summary + chain diffs) to propose names/intents/signals. All phases are resumable; outputs land in `.bridge-assist/styles/`.
- **PSD introspection module (`bridge_assist/psd_introspect.py`):** shared lazy reader used by both the style miner and the existing `inferrer.py`. Single source of truth for layer walks, adjustment-kind classification, partial introspection, and per-file timeouts.
- **Test suite (`tests/test_taste_discovery.py`):** 16 unit + integration tests covering psd_introspect helpers, chain detection, featurization, and a full mine-styles smoke test on synthetic PSDs. All passing.

**What has been tested at scale:**
- Hawaii 2026 shoot: 499 NEFs ingested (2.5 min), scored via Claude (75 min, 0 errors), full scores in `scores-hawaii-2026.json`
- **Style mining full corpus run** (PS Works/, 831 PSD/PSB files, 2026-04-26):
  - Phase 1 extraction: 56 min, ~0.3 files/sec, 27 size-guarded (1-6GB PSBs).
  - Phase 2 chains: 758 chains detected.
  - Phase 3 thumbs: 802 embedded extractions, 26 size-skipped, 2 composited, 1 error. ~50 min.
  - Phase 4 cluster: HDBSCAN gave 8 real clusters + 163-file noise bucket = 9 total. min_cluster_size=20.
  - Phase 5 vision: Claude named all 9 clusters with intent/signals/signature moves/example outputs. ~2 min.
  - Output: `.bridge-assist/styles/styles_draft.md` (14 KB, 9 named styles).
- Cluster sizes: cinematic-fantasy-composite (347, the baseline), infrared-dream-composite (163, was HDBSCAN noise), dramatic-monochrome-selective (95), cinematic-book-cover (51), surreal-sky-composite (46), dramatic-sky-composite (41), vibrant-surreal-composite (21), fantasy-forest-composite (20), panoramic-surreal-composite (20).

**What is in flight:**
- **Human review of `styles_draft.md` and promotion to project-root `STYLES.md`.** The 9 auto-named clusters need a designer's pass: rename anything Claude got wrong, split anything that mashes two real styles together, merge near-duplicates (several clusters share the "composite" / "surreal" word — likely consolidation candidates), and decide what to do with cluster -1 (HDBSCAN's noise bucket, 163 files; Claude gave it a coherent name but mechanically these are just outliers — verify visually before keeping). When done, `cp .bridge-assist/styles/styles_draft.md ./STYLES.md`, edit, and commit.

---

## 3. Next Actions (prioritized)

_(Update at the end of each session. Keep this short, 3 to 7 items max.)_

1. **Review `styles_draft.md` and promote to `STYLES.md`.** Auto-naming is done — 9 candidate styles for 804 clustered files. Open `.bridge-assist/styles/styles_draft.md`, walk each cluster (use `bridge-assist styles-inspect <id>` to see members + features). Decisions to make: (a) accept/rename Claude's labels, (b) split `cinematic-fantasy-composite` (347 files, very broad) if visual inspection finds 2-3 real sub-styles, (c) keep or drop `infrared-dream-composite` (cluster -1, HDBSCAN noise — these may be a real style or genuine outliers), (d) merge any near-duplicates (lots of "*-composite" names — possibly consolidate). When happy: `cp .bridge-assist/styles/styles_draft.md ./STYLES.md`, edit voice to match `taste.md` style, commit on `feature/taste-discovery-ps-works`, open PR.
2. **Run route + report on the Hawaii 2026 scored data.** Scores are done (`scores-hawaii-2026.json`, 499 images). Need to run `bridge-assist route --taste ./taste.md --tag hawaii-2026` and `bridge-assist report --taste ./taste.md --tag hawaii-2026` to complete the pipeline and see the per-channel contact sheet at scale.
2. **Fix EXIF extraction for D800 Nikon-specific fields.** The sort report currently shows `Unknownmm f/Unknown ISO Unknown` for the MT88026 test image. exiftool integration (commit `0fafe74`) should resolve this, but the Hawaii run needs verification. If EXIF is still missing, check whether exiftool is installed and the ingest code is actually calling it.
3. **Test the taste engine feedback loop end-to-end.** Phase 1 is built (`record`, `record-dir`, `feedback`) but hasn't been tested with real processed files (PSDs from Photoshop, TIFs from Capture One). Need to process a few Hawaii images through the actual NX-D/Photoshop workflow and then run `record-dir` to verify the matcher logic.
4. **Add `--only-unscored` resumption test.** The flag exists in the score command. Verify it correctly skips already-scored images when resuming a partially-completed run (kill mid-run, then resume with `--only-unscored`).
5. **Consider batch/parallel scoring.** At 9 seconds per image, 499 images took 75 minutes. Investigate whether the Anthropic API supports concurrent requests and whether batching 3-5 images in parallel would be safe and faster.
6. **Write a minimal test suite.** No tests exist. Priority targets: `taste_parser.py` (parse/validate taste.md), `tagged_filename()` helper in cli.py, `parse_scores_response()` JSON extraction in score.py, `_confidence_bar()` in report.py.
7. **Create DECISIONS.md.** Architectural decisions are scattered across `gstack-plan.md`, `docs/`, and conversation history. Consolidate: why single-call multi-channel scoring, why Claude > OpenAI for taste scoring, why symlinks not copies, why per-channel report layout, why page-scoped XMP labels.

---

## 4. Session Log (append-only)

| Date | Summary | Outcome |
|------|---------|---------|
| 2026-04-05 | Initial setup: Python 3.13 venv, ImageMagick, fixed pyproject.toml build backend, cleared stale sandbox data | Full environment working on Mac Mini with Mauna Kea drive |
| 2026-04-05 | First end-to-end test with MT88026 NEF: ingest, score (Claude), route, report | Pipeline works. Fixed image resize bug (D800 previews exceeded 5MB API limit). Fixed working dir resolution (was creating .bridge-assist inside source folder). |
| 2026-04-05 | Claude vs OpenAI scoring comparison (both at high detail) | Claude scores more critically and specifically. OpenAI inflates by +0.05 to +0.25. Same routing outcome on test image but Claude reasoning is more actionable. Analysis saved to `docs/OpenAI_Anthropic_Diffs.md`. |
| 2026-04-05 | Report restructure: per-channel layout, removed 80-char reasoning truncation | Report now organized by channel (contact sheet style) instead of per-image. Full reasoning visible. |
| 2026-04-05 | Added `--tag` support for per-run namespacing | All commands accept `--tag`. Ingest auto-derives tag from folder name. Files: `manifest-{tag}.json`, `scores-{tag}.json`, `routes-{tag}.json`, `sort-report-{tag}.md`. |
| 2026-04-05 | Hawaii 2026 ingest + score (499 NEFs via Claude) | 499/499 ingested (2.5 min), 499/499 scored (75 min, 0 errors). Data in `scores-hawaii-2026.json`. |
| 2026-04-07 | Switched to exiftool for EXIF extraction | rawpy/Pillow were missing Nikon-specific fields. exiftool gives gold-standard EXIF. |
| 2026-04-11 | XMP sidecar command for Adobe Bridge | `bridge-assist xmp` writes .xmp files next to NEFs. Bridge reads star ratings, labels, keywords. |
| 2026-04-11 | Taste engine Phase 1: feedback recording | `record`, `record-dir`, `feedback` commands. Matches processed PSD/TIFF to source NEFs. SQLite storage. Channel inference from folder context and file metadata. |
| 2026-04-11 | README update with XMP and taste engine docs | Full CLI reference in README. |
| 2026-04-26 | Created SESSION.md from SESSION-Sample.md template | Project state documented for agent continuity. |
| 2026-04-26 | Built taste-discovery / style-mining pipeline on `feature/taste-discovery-ps-works` | New `bridge_assist/psd_introspect.py` (shared lazy PSD reader) + `bridge_assist/style_miner.py` (5-phase pipeline: fingerprint → chain → thumb → cluster → name). New CLI commands: `mine-styles`, `styles-report`, `styles-inspect`. 16 tests in `tests/test_taste_discovery.py`, all passing. Smoke test on 25 PSDs produced 7 candidate clusters and a `styles_draft.md`. Size guard for >1GB PSBs working as intended. |
| 2026-04-26 | Full corpus style-mining run on PS Works/ (831 PSD/PSB) | Phase 1 56 min, Phase 3 50 min, full pipeline ~1h45m end-to-end. 9 candidate styles named via Claude vision: cinematic-fantasy-composite (347, baseline), infrared-dream-composite (163 from HDBSCAN noise), dramatic-monochrome-selective (95), cinematic-book-cover (51), surreal-sky-composite (46), dramatic-sky-composite (41), vibrant-surreal-composite (21), fantasy-forest-composite (20), panoramic-surreal-composite (20). 27 files size-guarded. Draft at `.bridge-assist/styles/styles_draft.md`, awaiting human review and promotion to `STYLES.md`. |

---

## 5. Known Issues / Gotchas

Things that will bite the next session if you forget them:

- **API keys must be exported in the shell session.** They're not in a .env file. Set `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` before running `score`. See `docs/api-key-rotation.md` for rotation instructions (gitignored for security).
- **The old API keys from the initial session were exposed in chat and rotated.** The keys in `api-key-rotation.md` are the compromised ones. Current working keys are set in `~/.zshrc` on the Mac Mini.
- **Working directory is always cwd/.bridge-assist/, not source_dir/.bridge-assist/.** This was a bug that was fixed. If someone reverts `_resolve_working_dir()` in cli.py, `score` will fail to find `manifest.json` when run from the project root.
- **D800 embedded previews are full-resolution (7360x4912).** They are ~3-4MB as JPEG. `encode_image_base64()` in score.py resizes to 2048px max and compresses to stay under 4.5MB base64. If you remove or weaken the resize, Claude's API will reject with "image exceeds 5 MB maximum."
- **OpenAI is set to `detail: "high"`.** It was originally `"low"` (512px thumbnail) for cost savings. Bumped to `"high"` for fair comparison. If cost becomes a concern, revert to `"low"` in score.py line 233.
- **macOS resource fork files (`._*.NEF`) in source folders.** The ingest command encounters these on the Mauna Kea external drive. rawpy correctly fails to extract a preview, and they get logged as "skipped." This is expected behavior, not a bug.
- **`--only-unscored` reads from existing scores file.** If you change the tag between runs, `--only-unscored` won't find previous scores (different filename). This is correct — different tags are different runs.
- **Previews are shared across tags.** All ingest runs write to the same `previews/` directory. Preview filenames are based on the NEF stem, so re-ingesting the same photos with a different tag just overwrites the same preview files (harmless).
- **The `scores.json` and `manifest.json` (untagged) are from the MT88026 single-image test.** The Hawaii data uses `scores-hawaii-2026.json` and `manifest-hawaii-2026.json`. Don't confuse the two.
- **exiftool must be installed for EXIF extraction.** If missing, ingest falls back to Pillow which gives incomplete metadata (the "Unknownmm f/Unknown" problem). Install via `brew install exiftool`.
- **Style mining requires `scikit-learn` and `numpy`.** Optionally `hdbscan` (KMeans fallback kicks in if missing). All installed in `.venv`. If you recreate the venv, `pip install -e .` will pull them via pyproject.toml.
- **PSDs >1GB are size-guarded.** `bridge_assist/psd_introspect.py` records partial fingerprints (path/size/mtime/tier/chain) for files above `partial_threshold_bytes` (default 1GB) and skips the layer walk to avoid OOM and 6GB-PSB pathologies. These files appear in fingerprints.jsonl with `error: "size_above_threshold"` but **do not enter clustering**. They still count for chain detection (so a chain ending in a 4GB PSB still tracks earlier saves). If you raise the threshold, also raise the per-file timeout.
- **Per-file PSD parse timeout: 120s.** Anything heavier raises `TimeoutError` and is logged as an error fingerprint. Bump via `--timeout` on `mine-styles` if you have giant-but-parseable files.
- **`.bridge-assist/styles/` is gitignored.** Do **not** commit fingerprints.jsonl, thumbnails, or `styles_draft.md`. The promoted `STYLES.md` belongs at the project root and IS committed.
- **`STYLES.md` and `taste.md` are separate.** `taste.md` defines input-routing channels (where a NEF goes). `STYLES.md` defines output styles (how an image was edited). They coexist; do not merge.
- **Resumable extraction.** Re-running `mine-styles` skips fingerprints already on disk. To force a clean re-extract, delete `.bridge-assist/styles/fingerprints.jsonl` (or just that file's matching entries).

---

## 6. Key Files (orient fast here)

| File | Lines | Why it matters |
|------|-------|----------------|
| `bridge_assist/cli.py` | 484 | CLI entry point. All commands, `--tag` support, `_resolve_working_dir()`, `_resolve_taste()`, `tagged_filename()` helper. |
| `bridge_assist/score.py` | 369 | Vision API scoring. Prompt builder, image resize/encode, Claude + OpenAI adapters, `parse_scores_response()` JSON extraction, `score_all()` pipeline with retry. |
| `bridge_assist/route.py` | 358 | Routing engine. Threshold comparison, symlink creation, ImageMagick derivative generation. Channel transform functions (warm proof, green proof, composite TIF, Instagram crop). |
| `bridge_assist/ingest.py` | 233 | NEF preview extraction (rawpy), EXIF reading (exiftool/Pillow), manifest generation. |
| `bridge_assist/report.py` | 200 | Per-channel Markdown report generator. Contact sheet layout with thumbnails, confidence bars, full reasoning. |
| `bridge_assist/xmp.py` | 183 | XMP sidecar writer for Adobe Bridge. Star ratings, labels, keywords from scores. |
| `bridge_assist/feedback_db.py` | 207 | SQLite feedback database. Records confirmations/corrections from processed files. |
| `bridge_assist/inferrer.py` | 172 | Channel inference from processed file metadata (folder name, PSD layers, color mode, ICC profile). Now delegates PSD reads to `psd_introspect.py`. |
| `bridge_assist/matcher.py` | 122 | Matches processed PSD/TIFF filenames back to source NEFs in the manifest. |
| `bridge_assist/taste_parser.py` | 128 | Parses taste.md into `Channel` and `TasteProfile` dataclasses. Validation logic. |
| `bridge_assist/nxd_parser.py` | 190 | Parses Nikon Capture NX-D preset files (XMP metadata). |
| `bridge_assist/psd_introspect.py` | ~370 | Shared lazy PSD/PSB reader. `Fingerprint` dataclass, partial-introspection size guard, per-file timeout, layer-tree walker, adjustment classifier, embedded thumbnail extractor, JSONL I/O. Used by both `inferrer.py` and `style_miner.py`. |
| `bridge_assist/style_miner.py` | ~970 | Five-phase taste discovery pipeline. Walks PSD corpus → chains saves → thumbs → clusters (HDBSCAN/KMeans) → calls Claude for per-cluster naming. Resume-safe. Outputs to `.bridge-assist/styles/`. |
| `tests/test_taste_discovery.py` | ~440 | Unit + integration tests for the style miner. 16 tests. |
| `taste.md` | 69 | **The product.** Human-authored creative specification. 6 channels with intent, signals, thresholds. (Input routing.) |
| `STYLES.md` | TBD | **Companion product.** Human-curated output-style library, derived from `mine-styles` then edited. (Output identity.) |
| `gstack-plan.md` | — | Original design document. Problem statement, approaches considered, architecture. |
| `pyproject.toml` | 27 | Package config. Dependencies, entry point, Python version requirement. |
| `requirements.txt` | 5 | Pip dependencies (click, rawpy, Pillow, anthropic, openai). |

**Working data** (in `.bridge-assist/`, gitignored):

| File | Purpose |
|------|---------|
| `manifest.json` / `manifest-{tag}.json` | Ingested file list, EXIF, preview paths |
| `scores.json` / `scores-{tag}.json` | Vision API scoring results per image |
| `routes.json` / `routes-{tag}.json` | Routing decisions and derivative paths |
| `sort-report.md` / `sort-report-{tag}.md` | Human-readable Markdown report |
| `feedback.db` | SQLite taste engine feedback database |
| `previews/` | Extracted JPEG previews from NEFs |
| `routes/` | Channel directories with symlinks and derivatives |
| `styles/fingerprints.jsonl` | Per-PSD mechanical fingerprints (append-only, resume-safe) |
| `styles/chain_diffs.jsonl` | Per-chain save-to-save layer diffs |
| `styles/thumbs/` | Per-fingerprint preview JPEGs (cached) |
| `styles/candidate_styles.json` | Cluster assignments + mechanical centroids |
| `styles/styles_draft.md` | Human-readable cluster draft (rename to `STYLES.md` when reviewed) |

---

## 7. Discipline (read this, then do it)

At the end of every session:

1. **Overwrite** "Current State" to reflect reality.
2. **Append** one row to the Session Log (date, one-line summary, outcome).
3. **Refresh** Next Actions — remove what's done, add what surfaced.
4. Move any new gotchas into "Known Issues."
5. If architectural decisions were made, note them here until a `DECISIONS.md` is created.

When starting a new session or delegating to a sub-agent, point it at this file first.
