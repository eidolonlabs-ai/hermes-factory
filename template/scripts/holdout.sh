#!/usr/bin/env bash
# Runs the holdout tests for a milestone. Written in M0, FROZEN at checkpoint 1.
# The factory copies holdouts into tests/holdout/ just before calling this, and removes them
# afterwards; the stack is already up (same COMPOSE_PROJECT_NAME as verify.sh).
#
#   scripts/holdout.sh <M1|M2|...>
set -euo pipefail
[[ $# -eq 1 && "$1" =~ ^M([0-9]+)$ ]] || { echo "usage: scripts/holdout.sh M<n>" >&2; exit 2; }
LEVEL="${BASH_REMATCH[1]}"
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -d tests/holdout ]] || { echo "no holdout tests present (NOT_RUN)"; exit 3; }

(( LEVEL >= 1 )) || exit 0
EXPR="m1"
for (( i=2; i<=LEVEL; i++ )); do
  EXPR="$EXPR or m$i"
done

# Example for pytest; the M0 architect adapts this. Keep -rA so failures list test ids.
docker compose -p "$COMPOSE_PROJECT_NAME" -f compose.yaml --profile test \
  run --rm -T test python -m pytest tests/holdout -q -rA -m "$EXPR"
