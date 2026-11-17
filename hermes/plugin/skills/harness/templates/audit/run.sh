#!/bin/bash
# Read-only cross-vendor audit: {claude,codex} x each repo-<name>/ clone in this dir.
# Usage: put clean clones at ./repo-a ./repo-b (+ same HANDOFF.md/CLARIFICATIONS.md in each),
# copy prompt.md + schema.json here, then: ./run.sh a b
A=$(cd "$(dirname "$0")" && pwd)
P="$(cat $A/prompt.md)"
for r in "$@"; do
  ( cd $A/repo-$r && ENABLE_CLAUDEAI_MCP_SERVERS=false timeout 3600 claude -p "$P" \
      --model opus --effort high --tools "Read,Grep,Glob" \
      --strict-mcp-config --mcp-config '{"mcpServers":{}}' --output-format json \
      > $A/claude-$r.json 2> $A/claude-$r.err; echo "claude-$r rc=$?" >> $A/done.log ) &
  ( timeout 3600 codex exec -C $A/repo-$r -s read-only -c model_reasoning_effort='"high"' \
      --output-schema $A/schema.json -o $A/codex-$r.json --json "$P" \
      > $A/codex-$r.jsonl 2> $A/codex-$r.err; echo "codex-$r rc=$?" >> $A/done.log ) &
done
wait
echo ALL_AUDITS_DONE
