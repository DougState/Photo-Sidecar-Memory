#!/usr/bin/env bash
# Bridge-Assist — environment initialization and smoke tests
# Run at the start of every long-running agent session.
#
# Exits 0 if the harness is healthy, non-zero if a hard prerequisite is missing.

set -u

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
BLUE=$'\033[0;34m'
BOLD=$'\033[1m'
RESET=$'\033[0m'

ok()   { printf "%s[ ok ]%s %s\n"   "$GREEN"  "$RESET" "$1"; }
warn() { printf "%s[warn]%s %s\n"   "$YELLOW" "$RESET" "$1"; }
err()  { printf "%s[fail]%s %s\n"   "$RED"    "$RESET" "$1"; }
info() { printf "%s[info]%s %s\n"   "$BLUE"   "$RESET" "$1"; }
hdr()  { printf "\n%s== %s ==%s\n"  "$BOLD"   "$1"     "$RESET"; }

HARD_FAILS=0
SOFT_FAILS=0

cd "$(dirname "$0")"
PROJECT_ROOT="$(pwd)"
info "project root: $PROJECT_ROOT"

# ---------------------------------------------------------------------------
hdr "Tooling"
# ---------------------------------------------------------------------------

if command -v python3 >/dev/null 2>&1; then
  PY_VERSION=$(python3 --version 2>&1)
  ok  "python3 found ($PY_VERSION)"
else
  err "python3 not found"
  HARD_FAILS=$((HARD_FAILS + 1))
fi

if command -v jq >/dev/null 2>&1; then
  ok  "jq found ($(jq --version))"
else
  warn "jq not found — '/session-start' and feature_list inspection will be clunky (brew install jq)"
  SOFT_FAILS=$((SOFT_FAILS + 1))
fi

if command -v exiftool >/dev/null 2>&1; then
  ok  "exiftool found ($(exiftool -ver))"
else
  warn "exiftool not found — EXIF extraction during ingest will fall back to rawpy only"
  SOFT_FAILS=$((SOFT_FAILS + 1))
fi

if command -v magick >/dev/null 2>&1 || command -v convert >/dev/null 2>&1; then
  ok  "ImageMagick found"
else
  warn "ImageMagick not found — derivative generation during route will fail (brew install imagemagick)"
  SOFT_FAILS=$((SOFT_FAILS + 1))
fi

if command -v git >/dev/null 2>&1; then
  ok  "git found ($(git --version))"
else
  err "git not found"
  HARD_FAILS=$((HARD_FAILS + 1))
fi

# ---------------------------------------------------------------------------
hdr "Virtualenv"
# ---------------------------------------------------------------------------

if [ -d ".venv" ] && [ -x ".venv/bin/python" ]; then
  VENV_PY_VERSION=$(.venv/bin/python --version 2>&1)
  ok  ".venv present ($VENV_PY_VERSION)"
  PYTHON=".venv/bin/python"
else
  warn ".venv missing or broken — create with: python3 -m venv .venv && source .venv/bin/activate && pip install -e ."
  PYTHON="python3"
  SOFT_FAILS=$((SOFT_FAILS + 1))
fi

# ---------------------------------------------------------------------------
hdr "Package installation"
# ---------------------------------------------------------------------------

if "$PYTHON" -c "import bridge_assist" >/dev/null 2>&1; then
  ok  "bridge_assist importable"
else
  err "bridge_assist not importable — run: $PYTHON -m pip install -e ."
  HARD_FAILS=$((HARD_FAILS + 1))
fi

# Quick dependency smoke
for mod in click rawpy PIL anthropic openai psd_tools watchdog; do
  if "$PYTHON" -c "import $mod" >/dev/null 2>&1; then
    ok  "  dep: $mod"
  else
    warn "  dep missing: $mod"
    SOFT_FAILS=$((SOFT_FAILS + 1))
  fi
done

# ---------------------------------------------------------------------------
hdr "API keys"
# ---------------------------------------------------------------------------

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  ok  "ANTHROPIC_API_KEY set"
elif [ -n "${BRIDGE_ASSIST_API_KEY:-}" ]; then
  ok  "BRIDGE_ASSIST_API_KEY set (alias)"
else
  warn "ANTHROPIC_API_KEY not set — `score` and `mine-styles` Phase 5 will fail"
  SOFT_FAILS=$((SOFT_FAILS + 1))
fi

if [ -n "${OPENAI_API_KEY:-}" ]; then
  ok  "OPENAI_API_KEY set"
else
  info "OPENAI_API_KEY not set — only Claude backend available"
fi

# ---------------------------------------------------------------------------
hdr "Harness files"
# ---------------------------------------------------------------------------

REQUIRED=(
  "CLAUDE.md"
  "claude-progress.txt"
  "feature_list.json"
  "init.sh"
  "SESSION.md"
  "README.md"
  "taste.md"
  "pyproject.toml"
)
for f in "${REQUIRED[@]}"; do
  if [ -f "$f" ]; then
    ok  "$f"
  else
    err "$f missing"
    HARD_FAILS=$((HARD_FAILS + 1))
  fi
done

REQUIRED_DIRS=(
  "bridge_assist"
  "tests"
  "docs/history"
  "docs/history/sessions"
)
for d in "${REQUIRED_DIRS[@]}"; do
  if [ -d "$d" ]; then
    ok  "$d/"
  else
    warn "$d/ missing — creating"
    mkdir -p "$d"
  fi
done

# Feature list summary (jq optional)
if command -v jq >/dev/null 2>&1 && [ -f feature_list.json ]; then
  TOTAL=$(jq -r '.summary.total'   feature_list.json 2>/dev/null || echo "?")
  PASS=$(jq  -r '.summary.passing' feature_list.json 2>/dev/null || echo "?")
  FAIL=$(jq  -r '.summary.failing' feature_list.json 2>/dev/null || echo "?")
  BLOCK=$(jq -r '.summary.blocked' feature_list.json 2>/dev/null || echo "?")
  info "features: $TOTAL total / $PASS passing / $FAIL failing / $BLOCK blocked"
fi

# ---------------------------------------------------------------------------
hdr "Git state"
# ---------------------------------------------------------------------------

if [ -d .git ]; then
  BRANCH=$(git branch --show-current 2>/dev/null || echo "(detached)")
  info "branch: $BRANCH"
  CHANGED=$(git status --porcelain | wc -l | tr -d ' ')
  if [ "$CHANGED" = "0" ]; then
    ok  "working tree clean"
  else
    info "$CHANGED uncommitted change(s)"
  fi
  echo
  echo "recent commits:"
  git log --oneline -5 | sed 's/^/  /'
else
  warn "not a git repo (skipping git state)"
fi

# ---------------------------------------------------------------------------
hdr "Summary"
# ---------------------------------------------------------------------------

if [ "$HARD_FAILS" -eq 0 ] && [ "$SOFT_FAILS" -eq 0 ]; then
  ok  "harness healthy — all checks passed"
  exit 0
elif [ "$HARD_FAILS" -eq 0 ]; then
  warn "harness usable — $SOFT_FAILS soft warning(s); see above"
  exit 0
else
  err "harness has $HARD_FAILS hard failure(s) and $SOFT_FAILS warning(s) — fix before continuing"
  exit 1
fi
