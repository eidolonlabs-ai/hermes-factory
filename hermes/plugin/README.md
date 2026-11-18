# Hermes Factory Plugin (`factory`)

Standalone Hermes Agent plugin providing deterministic tool guardrails, verification nudges, and bundled factory workflow skills for **hermes-factory**.

## What Ships

- [`plugin.yaml`](plugin.yaml): Plugin manifest declaring `pre_tool_call` and `pre_verify` hooks (`requires_hermes: ">=0.23.0"`).
- [`__init__.py`](__init__.py): Plugin entrypoint (`register(ctx)`) registering the bundled skills and wiring `pre_tool_call` -> `factory-hook` (blocking writes to `.factory/`, frozen files, holdouts, secrets, and `git push`, failing closed if the engine is absent) and `pre_verify` -> `scripts/verify.sh <milestone>` reminder.
- `skills/`: 8 unified `factory-*` workflow skills (`factory-pipeline`, `factory-setup`, `factory-intake`, `factory-plan`, `factory-build`, `factory-verify`, `factory-review`, `factory-status`) plus `factory` and `factory-worker` (`SKILL.md` files + shared `references/` and `templates/` under `skills/factory/`). All skills call the `factory` CLI engine rather than duplicating scripts inside each skill folder.

## Validate Locally

```bash
hermes plugins validate ./hermes/plugin
hermes plugins doctor ./hermes/plugin
```

Notice `hermes plugins validate` writes no extra bytecode when tested, and `python3 -m unittest discover -s tests` validates plugin registration and hook behavior.

## Install

Recommended full installation (installs `factory` + `factory-hook` via `uv` or `pipx`, clones your active profile into `factory-coder` / `factory-worker`, and registers skills + this plugin):

```bash
curl -fsSL https://raw.githubusercontent.com/eidolonlabs-ai/hermes-factory/main/install.sh | bash
```

Or install manually with `uv` + `factory setup`:

```bash
uv tool install git+https://github.com/eidolonlabs-ai/hermes-factory
factory setup
```

Standalone plugin installation (assumes `factory` and `factory-hook` are already on `PATH`):

```bash
hermes -p factory-coder plugins install eidolonlabs-ai/hermes-factory/hermes/plugin --enable
```

The `pre_tool_call` guard activates only inside the `factory-coder` profile or inside an active `factory run` worktree (`FACTORY_ROOT` set), leaving your default profile untouched.
