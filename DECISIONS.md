# DECISIONS.md

> Architectural and operational decisions for bridge-assist. Each entry records *what* was decided, *why*, and *what was rejected*. Append-only — supersede entries with a new entry, do not edit history. Newest first.

---

## 2026-05-21 — Public mirror strip list: expand for taste-engine, style-mining, and agent-harness landing on `main`

**Supersedes:** the strip list in the 2026-05-09 entry (the strategy itself is unchanged; only the strip list grows).

**Context:** On 2026-05-21, `feature/taste-discovery-ps-works` was fast-forwarded onto `main`, bringing the taste engine, the PSD style-mining pipeline, the long-running agent harness (`init.sh`, `claude-progress.txt`, `feature_list.json`, `.claude/`, `docs/history/`), `SESSION.md`, `CHANGELOG.md`, and an HTML-first output-policy note (`CLAUDE.html-example.md`). The 2026-05-09 entry had already anticipated that `SESSION.md` and `CHANGELOG.md` would need stripping once they landed on `main`. They have.

**Decision — full strip list (authoritative as of 2026-05-21):**

| Path | Reason |
|------|--------|
| `CLAUDE.md` | Agent rules and skill routing — internal workflow |
| `CLAUDE.html-example.md` | HTML-first output-policy note for AI agents |
| `SESSION.md` | Long-form working state (current branch, in-flight work) |
| `CHANGELOG.md` | Internal change log |
| `DECISIONS.md` | This file — captures internal mirror strategy |
| `gstack-plan.md` | Internal design doc |
| `data_types.csv` | Unused reference |
| `init.sh` | Harness setup script — references `SESSION.md` and `feature_list.json`, would fail on a fresh public clone |
| `claude-progress.txt` | Per-session activity log |
| `feature_list.json` | Harness feature tracker |
| `.claude/` (directory) | Claude IDE settings (auto-allow permissions for harness reads) |
| `docs/SESSION-Sample.md` | SESSION.md template — meta-doc for the harness pattern |
| `docs/history/` (directory) | Per-session notes — harness scaffolding |

**Kept on public mirror:**
- All of `bridge_assist/` (including the new `feedback_db.py`, `inferrer.py`, `matcher.py`, `psd_introspect.py`, `style_miner.py`).
- All of `NXD Presets/` (the full preset library).
- `tests/test_taste_discovery.py`.
- `docs/OpenAI_Anthropic_Diffs.md`, `docs/weights.md` (publishable analyses).
- `README.md` (with the clone-URL rewrite), `taste.md`, `pyproject.toml`, `requirements.txt`, `.gitignore`.

**Why expand:**
- Harness files (`init.sh`, `claude-progress.txt`, `feature_list.json`, `.claude/`, `docs/history/`) are personal-workflow scaffolding for long-running agent sessions, not part of the product. `init.sh` in particular would fail loudly on a fresh clone of the public repo because it expects `SESSION.md` and `feature_list.json` to exist.
- `CLAUDE.html-example.md` records an opinionated output-format preference for AI agents working in this codebase. Not interesting to public consumers.
- `docs/SESSION-Sample.md` is a template explaining how to use the harness — meta-doc for the workflow.

**Mechanism reminder (unchanged from 2026-05-09):**
1. `git checkout -B public-mirror main` — recreate the branch from the current `main` HEAD.
2. `git rm` every path in the strip list above.
3. Rewrite the README clone URL from `AI-Photo-Sort` to `Photo-Sidecar-Memory` (currently README.md lines 47-48).
4. `git commit -m "Sanitize for public mirror"`.
5. `git push public public-mirror:main --force`.

**Consequences:**
- Sanitization commit on `public-mirror` now removes 13 paths (was 4 in the 2026-05-09 entry).
- This entry is the source of truth. Any new internal file landing on `main` should trigger another superseding entry that reproduces the full updated strip list — do not chase changes through entry diffs.

---

## 2026-05-09 — Public mirror strategy: rebuild from private `main`

**Decision:** The public repository [`DougState/Photo-Sidecar-Memory`](https://github.com/DougState/Photo-Sidecar-Memory) is maintained as a force-pushed mirror of the private `DougState/AI-Photo-Sort` `main` branch, with a small sanitization step (clone-URL rewrite) applied via a dedicated `public-mirror` branch.

**Mechanism:**
1. Private `main` is the canonical source of truth. All development happens on private branches and merges into private `main`.
2. A `public-mirror` branch is rebased on `main` whenever a public release is desired. It carries one or more sanitization commits on top of `main`:
   - Rewrite the README clone URL from `AI-Photo-Sort` to `Photo-Sidecar-Memory`.
   - Remove internal-only files that happen to be tracked on `main`: `CLAUDE.md` (gstack agent rules), `gstack-plan.md` (internal design doc), `data_types.csv` (unused reference).
3. `public-mirror` is force-pushed to the public repo's `main` (`git push public public-mirror:main --force`).
4. Public repo gets the full preset library, README, `taste.md`, `bridge_assist/` modules, `docs/`, and `pyproject.toml`. Files listed in step 2 are stripped at the public-mirror layer, never from private `main`.

**Why:**
- The public repo had drifted to a single stale commit with a renamed channel (`product-catalog` instead of `elimstat-product`). Cherry-picking forward would require re-resolving that rename for every commit.
- Force-pushing a clean snapshot from private `main` gives the public a working, current codebase in one shot.
- A dedicated `public-mirror` branch isolates public-facing edits (clone URLs, sanitized example paths) from private `main`, so private development doesn't have to think about public concerns and the public repo doesn't accumulate internal noise.

**Rejected alternative — Cherry-pick feature by feature:**
Walking each commit forward (bug fixes → XMP work → taste engine → style mining → product-channel removal) would preserve commit history on the public side. Rejected because the public repo has no consumers yet, history continuity has zero current value, and the rename conflict makes every cherry-pick a manual merge.

**Rejected alternative — Make private `main` itself public-safe:**
Editing the private `main` README to point at the public repo would mean a private dev who clones the private repo gets a wrong clone command. Rejected to keep `main` accurate for private use.

**Consequences:**
- Public repo `main` history will be force-pushed periodically. Anyone who forks the public repo must expect this.
- The `public-mirror` branch lives only in the local repo and is recreated from `main` on each release. Don't rely on its commit hashes.
- If the public repo ever gains real contributors, this strategy must be revisited (force-push breaks PRs).

**Files that must stay out of the public repo:**
- `api-key-rotation.md` (gitignored — contains rotated leaked keys)
- `.bridge-assist/` (gitignored — working cache with paths to your photo library)
- `MT88026/`, `*.psb`, `*.mpt`, `._*`, `*.code-workspace` (gitignored — large working binaries and macOS metadata)
- `CLAUDE.md`, `gstack-plan.md`, `data_types.csv` — tracked on private `main` but stripped on the `public-mirror` branch.
- `SESSION.md`, `CHANGELOG.md` — currently kept private by virtue of not being on `main` (they live on later branches). If they ever land on `main`, add them to the public-mirror strip list.

---
