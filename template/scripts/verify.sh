#!/usr/bin/env bash
# Acceptance gate for this project. Written in M0, FROZEN at checkpoint 1.
#
#   scripts/verify.sh <M1|M2|...>
#
# Cumulative: verifying Mk runs every check for M1..Mk against a fresh real stack.
# The harness sets COMPOSE_PROJECT_NAME (unique per run) and HARNESS_ARTIFACTS (log dir)
# and tears the stack down afterwards. Run by hand, it uses a local project name.
# Exit 0 only if every check for the level ran and passed (NOT_RUN is a failure).
set -euo pipefail

[[ $# -eq 1 && "$1" =~ ^M([0-9]+)$ ]] || { echo "usage: scripts/verify.sh M<n>" >&2; exit 2; }
MILESTONE="$1"; LEVEL="${BASH_REMATCH[1]}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$(basename "$ROOT" | tr -cs 'a-z0-9' '-')-local}"
ART="${HARNESS_ARTIFACTS:-/tmp/${COMPOSE_PROJECT_NAME}-verify}"
mkdir -p "$ART"

# dc: app services only (what `up` starts). dct: includes the "test" profile (test runners).
dc()  { docker compose -p "$COMPOSE_PROJECT_NAME" -f compose.yaml "$@"; }
dct() { docker compose -p "$COMPOSE_PROJECT_NAME" -f compose.yaml --profile test "$@"; }

RAN=0
step() {  # step <label> <log-name> <command...>
  local label="$1" name="$2"; shift 2
  local log="$ART/$name.log" start=$SECONDS
  printf '==> %-56s ' "$label"
  if "$@" >"$log" 2>&1; then
    echo "ok ($((SECONDS - start))s)"; RAN=$((RAN + 1))
  else
    local rc=$?
    echo "FAILED (exit $rc)"; echo "---- tail of $log ----"; tail -n 60 "$log"
    dct ps -a >"$ART/failure-ps.log" 2>&1 || true
    dct logs --no-color --tail 80 >"$ART/failure-logs.log" 2>&1 || true
    echo "---- VERIFY $MILESTONE: FAIL ----"; exit 1
  fi
}

step "boot stack (build + wait for health)" boot dc up -d --build --wait --wait-timeout 300

# ---- checks per milestone level (M0 architect fills these in) ----------------------------
# Tag tests by milestone (pytest markers / Playwright tags) so level k runs M1..Mk.
if (( LEVEL >= 1 )); then
  step "backend tests M1..M${LEVEL} (live services)" backend \
    dct run --rm -T test python -c "raise SystemExit('verify.sh not configured yet: M0 replaces this step')"
fi
# if (( LEVEL >= 4 )); then
#   step "e2e tests (Playwright in container)" e2e dct run --rm -T e2e npx playwright test --grep "@m[1-${LEVEL}]"
# fi
# -------------------------------------------------------------------------------------------

(( RAN > 1 )) || { echo "no checks ran for $MILESTONE (NOT_RUN is not PASS)"; exit 1; }
echo "---- VERIFY $MILESTONE: PASS ($RAN steps) ----"
