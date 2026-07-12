# M5-AIRTEST preflight

Recorded: 2026-07-12, America/Chicago

## Task

- Task ID: M5-AIRTEST
- Objective: evaluate whether a policy-constrained Airtest adapter provides a measurable benefit
  over the passed custom baseline for the representative startup flow.
- Satisfied dependencies: M5-CUSTOM-BASELINE Passed (`d7cbca5`); MVP startup-normalization
  corpus retained; RT-019 and RT-021 Passed.
- Acceptance criteria: use the identical retained corpus and target/policy contract; evaluate
  capture/profile enforcement, Cash Mall/Ending Soon/Home/Base recognition, one detector and one
  OCR ROI, stale/unknown rejection, one-input/immediate-recapture semantics, reconnect behavior,
  unprivileged-worker packaging, CPU/memory implications, diagnostics, testability,
  maintainability, deployment complexity, and SQLite/controller compatibility; retain an
  evidence-backed Passed or Rejected decision.

## Intended operations

1. Perform read-only local availability and dependency inspection. Airtest is not installed in
   the current worker environment; no package installation or network dependency change is
   authorized by this task.
2. Review the official Airtest packaging/API surface and compare it with the RT-021 unprivileged
   worker boundary and the central project policy contract.
3. Run a minimal offline/mock adapter contract against the same five-fixture corpus, with no
   Airtest default watcher, coordinate script, retry, live ADB, or game input.
4. Preserve the candidate's failure/early-rejection reason if the required adapter cannot be
   evaluated cleanly without a material new dependency or policy bypass.

## Verification procedure

- Record module/CLI availability, dependency and packaging facts, and official-source links.
- Use the passed custom baseline `benchmark.json` as the reference measurement set; do not
  manufacture live Cash Mall taps to fill candidate counts.
- Verify the candidate cannot authorize an input outside the project policy contract and that
  stale, profile-mismatch, unknown-overlay, repeated-input, and target-overlap cases remain
  denied.
- Perform an independent review of every criterion, retain all failed/unsupported claims, run
  secret scans and repository consistency checks, inspect the complete task diff, and commit one
  Airtest-scoped decision.

## Evidence and rollback

- Evidence directory: `evidence/sessions/20260712-m5-airtest/`.
- Planned artifacts: `preflight.md`, `record.md`, `availability.json`, and any small mock result
  or failure evidence required to support the decision.
- Required credentials/manual dependency: none. No SSH, VM, ADB, game, account, or user input is
  required; this candidate boundary is repository-only.
- Permissions: repository write for task evidence and one Git commit; no package installation,
  host operation, or unrelated workload change.
- Rollback: remove only task-scoped Airtest evidence/prototype files if rejected; preserve the
  custom baseline, MVP corpus, runtime, backup, profile, and all unrelated worktree files.
