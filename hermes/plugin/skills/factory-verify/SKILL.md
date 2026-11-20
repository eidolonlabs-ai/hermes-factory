---
name: factory-verify
description: "Phase 4A external real-stack gate (`factory gate`) and live UI preview verification (`factory preview` + headless browser). Enforces `NOT_RUN !== PASS`."
version: 0.1.0
author: Hermes
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [Software-Factory, Verification, Docker, Browser]
    related_skills: [factory-pipeline, factory-review]
---

# factory-verify: Phase 4A External Gate & Live Preview Verification

Decide pass/fail solely from external exit codes and real-stack UI checks—never from a builder's self-report.

## 1. Run External Gate (`NOT_RUN !== PASS`)
Run `factory gate --final` in background + notify (`terminal(background=true, notify=true)`):
- Enforces **Scope**, **Frozen**, **Hygiene**, **Verify** (`scripts/verify.sh <milestone>` on real Docker Compose services, never mocked DBs), **Holdouts**, **Diff Audit**, **Candidate Hash**, and **Compose Teardown**.
- `NOT_RUN` is never `PASS`. Report host-stack runs (`stack.type: host`) explicitly as `"not isolated"`.
- On red gates, show the failing check name and the tail log path—never dump huge logs into chat.

## 2. Live UI Preview & Browser Checks
Start the published preview stack and inspect the running application:
```bash
factory preview
```
Verify key workflows and responsive layouts at **desktop (`1440x900`)** and **mobile (`390x844`)** using browser tools (or headless Chrome `--headless=new --window-size=1440,900 --virtual-time-budget=8000 --screenshot=out.png URL` if `browser_exec` times out). Always stop the preview when done:
```bash
factory preview --down
```
Proceed to `factory-review`.
