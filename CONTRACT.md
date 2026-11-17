# Harness contract (shared)

The rules every harness in this family follows, whatever the platform: `hermes-agent-harness`,
`codex-harness-template`, `agy-software-factory`, and future siblings. Each repo implements
them natively, in its own language and with its own platform features. This file and the
`contract/` folder are copied between repos. When a rule changes, change it everywhere.

Version: 1

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
| 4 | Verify | `scripts/verify.sh <milestone>` exits non-zero |
| 5 | Holdouts | the holdout command exits non-zero |
| 6 | Diff audit | a high-severity finding (secret, dynamic exec, SQL interpolation) in changed files |
| 7 | Candidate hash | the code changed while the gate ran |

Steps a project does not use (no holdouts, no audit) are reported `NOT_RUN`.

## 3. Check results

Every check reports `PASS`, `FAIL` or `NOT_RUN`. **`NOT_RUN` is never `PASS`.** When
`require_tests` is on (the default), a gate with no test check that actually ran is a
failure. A missing test script, an unreachable Docker daemon, or an empty check list is
`NOT_RUN`, not green.

## 4. `scripts/verify.sh`

- Usage: `scripts/verify.sh <milestone>` — runs every check for milestones up to and including
  `<milestone>` (cumulative). Milestone ids are `M0`, `M1`, …
- Exit 0 = pass, anything else = fail. No interactive prompts.
- Verbose output goes to log files; stdout ends with a short summary.
- Never touches resources it did not create (no host-wide prune, no other compose projects).
- Frozen at checkpoint 1 along with the tests it runs.

## 5. Freeze and holdouts

- **Freeze** happens once, at checkpoint 1, after a human approves the plan. The harness
  records the commit and the list of frozen files. Builders may **add** tests; they may not
  change or delete frozen ones.
- **Holdouts** are tests written in M0 and removed from the repository at freeze. The harness
  copies them in only while gating and removes them afterwards. Builders and reviewers see
  only failing test ids and assertion messages, never holdout source.
- Holdouts are a discipline, not a secret: in permission-bypass modes an agent can read any
  file the user can. Say so in each repo's docs.

## 6. Roles

- **Architect** writes the contract (M0). Read-only during intake.
- **Builder** implements one milestone in an isolated worktree.
- **Reviewer** runs in a fresh context, ideally from a different vendor than the builder.
  It reproduces each defect with a failing test before fixing it, and its changes pass the
  same gate.
- **Human** approves the plan (checkpoint 1) and any milestone marked `checkpoint`, and
  decides on protected-path changes.

## 7. Guard policy

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

## 8. Records

- Run state lives **outside** the project repository, so agents cannot edit the record of
  their own runs.
- Each run writes one `result.json` atomically (see `contract/result.schema.json`).
- Human interventions are counted, so different harnesses can be compared fairly.

## 9. Benchmarks

`examples/chronograph/` is the shared yardstick: an intake benchmark (an incomplete master
spec; a good architect asks before building) and a build benchmark (HANDOFF + clarifications;
measure wall time, interventions, and findings from a cross-vendor audit).
