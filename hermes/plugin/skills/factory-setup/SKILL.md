---
name: factory-setup
description: "Phase 0 workspace & machine setup for Hermes Factory (`factory doctor`, `factory setup`, `factory init`)."
version: 0.1.0
author: Hermes
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [Software-Factory, Setup, Docker]
    related_skills: [factory-pipeline, factory-intake]
---

# factory-setup: Phase 0 Workspace & Machine Setup

Prepare the host environment and target Git repository before intake or milestone execution.

## Machine Prerequisites & Diagnostics

1. Ensure the engine is installed (`uv tool install git+https://github.com/eidolonlabs-ai/hermes-factory`, then `factory setup` to install skills, `factory-coder` / `factory-worker` profiles, and the guard plugin).
2. Check logins and Docker Compose availability:
   ```bash
   factory doctor
   ```
   Expired `claude` / `codex` logins cause instant attempt failures—verify first.

## Project Initialization & Context Hygiene

1. Initialize or enter the target Git repo (`git init -b main` if new) and scaffold factory templates:
   ```bash
   factory init
   ```
   *(For projects that genuinely cannot run inside Linux containers, use `factory init --stack host --reason "..."`; gates will report "not isolated".)*
2. Preserve existing repository files and ensure `AGENTS.md` (`CLAUDE.md -> AGENTS.md`) enforces context hygiene: redirect heavy build/test logs to `${FACTORY_ARTIFACTS:-/tmp}` and inspect only exit codes and tail lines.
3. For existing repositories, establish the baseline checks inside `scripts/verify.sh` before moving to `factory-intake`.
