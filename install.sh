#!/usr/bin/env bash
# Install or update hermes-agent-harness for the current user. Idempotent.
#
#   curl -fsSL https://raw.githubusercontent.com/theRealMarkCastillo/hermes-agent-harness/main/install.sh | bash
#   ./install.sh              from a checkout: editable install, edits take effect at once
#   ./install.sh --dry-run    print what would change
#
# What it does:
#   1. installs the engine (`harness`, `harness-hook`) as an isolated tool with uv or pipx
#   2. runs `harness setup`: Hermes skills, the harness-coder / harness-worker profiles and the
#      guard plugin. Your default profile's config is never modified.
set -euo pipefail

REPO_URL="git+https://github.com/theRealMarkCastillo/hermes-agent-harness"
DRY=0
for a in "$@"; do [[ "$a" == "--dry-run" ]] && DRY=1; done
say() { echo "==> $*"; }
run() { if (( DRY )); then echo "[dry-run] $*"; else "$@"; fi; }

# Running from a checkout? (not the case for `curl | bash`)
SRC=""
SELF="${BASH_SOURCE[0]:-}"
if [[ -n "$SELF" && -f "$SELF" ]]; then
  DIR="$(cd "$(dirname "$SELF")" && pwd)"
  if [[ -f "$DIR/pyproject.toml" && -d "$DIR/harness" ]]; then SRC="$DIR"; fi
fi

if command -v uv >/dev/null 2>&1; then
  say "engine: uv tool install${SRC:+ (editable, $SRC)}"
  if [[ -n "$SRC" ]]; then run uv tool install --force --python ">=3.11" --editable "$SRC"
  else run uv tool install --force --python ">=3.11" "$REPO_URL"; fi
  BIN="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
elif command -v pipx >/dev/null 2>&1; then
  say "engine: pipx install${SRC:+ (editable, $SRC)}"
  if [[ -n "$SRC" ]]; then run pipx install --force --editable "$SRC"
  else run pipx install --force "$REPO_URL"; fi
  BIN="${PIPX_BIN_DIR:-$HOME/.local/bin}"
else
  echo "error: need uv or pipx to install the engine." >&2
  echo "  install uv:  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi
case ":$PATH:" in *":$BIN:"*) ;; *) echo "    note: add $BIN to PATH"; export PATH="$BIN:$PATH";; esac

say "hermes: harness setup"
if (( DRY )); then
  if command -v harness >/dev/null 2>&1 && harness setup --dry-run 2>/dev/null; then :
  else echo "[dry-run] harness setup"; fi
else
  harness setup
fi

say "done. Next: harness doctor"
