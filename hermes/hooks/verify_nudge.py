#!/usr/bin/env python3
"""Hermes `pre_verify` shell hook for the harness-coder profile.

Fires when the agent is about to finish a turn in which it edited code. Once per turn it
reminds the agent to run the milestone's acceptance script itself before stopping. It never
runs the gate: the harness gate, outside the agent, remains the authority.
"""
import json
import os
import sys


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        print("{}")
        return 0
    extra = payload.get("extra") or {}
    milestone = os.environ.get("HARNESS_MILESTONE", "")
    if extra.get("attempt") or not extra.get("coding", True) or not milestone or milestone == "M0":
        print("{}")
        return 0
    print(json.dumps({
        "action": "continue",
        "message": (f"Before finishing: run `scripts/verify.sh {milestone}` (logs to files, read the "
                    "tail), fix any failure at the root cause, commit, then finish. Do not edit "
                    "frozen files or weaken tests. The external gate will re-run everything."),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
