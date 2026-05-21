# CLAUDE.md — Bridge-Assist

## Long-Running Agent Harness

**START EVERY SESSION WITH THIS RITUAL:**

```bash
# 1. Verify working directory
pwd

# 2. Run initialization and smoke tests
./init.sh

# 3. Read progress and feature status
cat claude-progress.txt
cat feature_list.json | jq '.summary'

# 4. Check git status
git status && git log --oneline -5
```

Or simply run: `/session-start`

### Harness Files

| File | Purpose |
|------|---------|
| `init.sh` | Environment setup and smoke tests |
| `claude-progress.txt` | Session activity log (update after each task) |
| `feature_list.json` | Granular feature tracking with pass/fail status |
| `docs/history/` | Session documentation and past work records |
| `SESSION.md` | Long-form working state, current branch context, next actions |

### Session Workflow

1. Run startup ritual above.
2. Read `SESSION.md` Sections 2-3 ("Current State" and "Next Actions") for context.
3. Skim `docs/history/sessions/` for relevant past notes.
4. Pick the highest-priority failing feature from `feature_list.json`.
5. Work on **ONE feature at a time**.
6. Test thoroughly before marking complete.
7. Append a line to `claude-progress.txt` after completing each feature.
8. Flip the feature's `status` to `"passing"` in `feature_list.json` once verified.
9. Git commit with format: `FEATURE: [ID] - [description]`.

---

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health

---

## Development Rules

- Python 3.11+. Use the project's `.venv/` (`source .venv/bin/activate` or invoke `.venv/bin/python` directly).
- Install in editable mode: `pip install -e .` from project root.
- API keys via env vars: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (also `BRIDGE_ASSIST_API_KEY` alias).
- Working dir for `.bridge-assist/` is always project root (cwd), not the source folder.
- Photos live on external drive `/Volumes/Mauna Kea/` — paths in tests must tolerate spaces.
- Run tests with `python -m pytest tests/ -v` from project root.
- The `score` step is the only one that calls the vision API. `route` and `report` are deterministic from cached JSON.

## Project Commands

```bash
# Pipeline (per-tag runs are isolated):
bridge-assist ingest <folder> [--tag NAME]
bridge-assist score  --taste ./taste.md [--tag NAME] [--backend claude|openai]
bridge-assist route  --taste ./taste.md [--tag NAME] [--threshold 0.7] [--dry-run] [--clean]
bridge-assist report --taste ./taste.md [--tag NAME] [--output ./sort-report.md]

# Bridge integration:
bridge-assist xmp --tag NAME [--dry-run] [--clean]

# Taste engine (feedback loop):
bridge-assist record /path/to/file.psd --tag NAME
bridge-assist record-dir /path/to/folder --tag NAME
bridge-assist feedback --tag NAME [--summary | --accuracy]

# Style mining (PSD/PSB corpus → STYLES.md draft):
bridge-assist mine-styles <folder> [--skip-thumbs] [--skip-vision] [--limit N]
bridge-assist styles-report
bridge-assist styles-inspect <cluster_id>

# Validation:
bridge-assist validate ./taste.md
```
