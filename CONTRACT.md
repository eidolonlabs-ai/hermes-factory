# Harness contract (shared)

The rules every harness in this family follows, whatever the platform: `hermes-agent-harness`,
`codex-harness-template`, `agy-software-factory`, and future siblings. Each repo implements
them natively, in its own language and with its own platform features. This file and the
`contract/` folder are copied between repos. When a rule changes, change it everywhere.

Version: 1.1

## 1. Definition of done

A milestone is done when, and only when, the **gate** for that milestone exits 0 on the exact
code being merged. The agent's own report ("completed", "all tests pass") is never evidence.

## 2. The gate

Run by the harness, outside the agent's session, on the candidate worktree. Steps, first
failure stops:

| # | Step | Fails when |
|---|---|---|
| 1 | Scope | a changed path is outside the milestone's `allowed_paths`, or a protected path changed (stop for a human) |
| 2 | Frozen | any frozen file differs from the freeze commit, or is missing |
| 3 | Hygiene | `.env` or a private key is tracked, or `.env` exists and is not git-ignored |
| 4 | Verify | `scripts/verify.sh <milestone>` exits non-zero (it boots the real stack, §4) |
| 5 | Holdouts | the holdout command exits non-zero |
| 6 | Diff audit | a high-severity finding (secret, dynamic exec, SQL interpolation) in changed files |
| 7 | Candidate hash | the code changed while the gate ran |

Steps a project does not use (no holdouts, no audit) are reported `NOT_RUN`.

## 3. Check results

Every check reports `PASS`, `FAIL` or `NOT_RUN`. **`NOT_RUN` is never `PASS`.** When
`require_tests` is on (the default), a gate with no test check that actually ran is a
failure. A missing test script, an unreachable Docker daemon, or an empty check list is
`NOT_RUN`, not green.

## 4. Real stack, end to end

The gate tests the running system, not a simulation of it. Each project has a Docker Compose
file with every service it needs (database, API, web app, …) plus a test service. The gate
boots the stack, waits for health checks, runs integration tests against the live services and
browser E2E tests (Playwright) against the live UI, and tears the stack down afterwards.

- No mocked databases or in-memory substitutes in gate tests. External third-party APIs may be
  replaced by a local fake *service* in the compose file.
- Each run uses its own compose project name, network and volumes; no fixed
  `container_name`, no published host ports during the gate, no Docker socket or privileged
  containers, no bind mounts outside the project.
- Teardown always runs, and the gate fails if containers outside its own project changed.
- Opt-out only for projects that cannot run in Linux containers, with a written reason; their
  gate reports say "not isolated".

## 5. `scripts/verify.sh`

- Usage: `scripts/verify.sh <milestone>` — runs every check for milestones up to and including
  `<milestone>` (cumulative). Milestone ids are `M0`, `M1`, …
- Exit 0 = pass, anything else = fail. No interactive prompts.
- Verbose output goes to log files; stdout ends with a short summary.
- Never touches resources it did not create (no host-wide prune, no other compose projects).
- Frozen at checkpoint 1 along with the tests it runs.

## 6. Freeze and holdouts

- **Freeze** happens once, at checkpoint 1, after a human approves the plan. The harness
  records the commit and the list of frozen files. Builders may **add** tests; they may not
  change or delete frozen ones.
- **Holdouts** are tests written in M0 and removed from the repository at freeze. The harness
  copies them in only while gating and removes them afterwards. Builders and reviewers see
  only failing test ids and assertion messages, never holdout source.
- Holdouts are a discipline, not a secret: in permission-bypass modes an agent can read any
  file the user can. Say so in each repo's docs.

## 7. Roles

- **Architect** writes the contract (M0). Read-only during intake.
- **Builder** implements one milestone in an isolated worktree.
- **Reviewer** runs in a fresh context, ideally from a different vendor than the builder.
  It reproduces each defect with a failing test before fixing it, and its changes pass the
  same gate.
- **Human** approves the plan (checkpoint 1) and any milestone marked `checkpoint`, and
  decides on protected-path changes.

## 8. Guard policy

An in-agent guard (hook) blocks honest mistakes early. It is a convenience: the gate remains
the authority. `contract/guard-cases.json` lists the required decisions; every repo runs
those cases against its own guard in CI.

- **Deny:** writes to `.env*` (except `.env.example`, `.env.sample`, `.env.template`,
  `.env.test`), private keys (`id_rsa`, `id_ed25519`, `id_ecdsa`, `id_dsa`, `*.pem`, `*.key`),
  `.git/` internals, the harness control directory, holdout files, and frozen files.
  Destructive commands (`rm -rf /` or `~`, `mkfs`, fork bombs), `git push`, `--no-verify`,
  host-wide Docker prune, pipe-to-shell installs.
- **Ask** (deny when unattended): `git reset --hard`, `git clean -f…`, interactive rebase.
- Shell writes count as writes: redirects, `tee`, `cp`/`mv`/`ln` (including `-t`), `sed -i`,
  `dd of=`, `git checkout -- <path>`, through `sh -c` / `bash -c`, `$(…)` and backticks.
- Paths are normalised (`a/../.env` is `.env`). Paths outside the repo are not the guard's
  concern.

## 9. Records

- Run state lives **outside** the project repository, so agents cannot edit the record of
  their own runs.
- Each run writes one `result.json` atomically (see `contract/result.schema.json`).
- Human interventions are counted, so different harnesses can be compared fairly.

## 10. Benchmarks

`examples/chronograph/` is the shared yardstick: an intake benchmark (an incomplete master
spec; a good architect asks before building) and a build benchmark (HANDOFF + clarifications;
measure wall time, interventions, and findings from a cross-vendor audit).
