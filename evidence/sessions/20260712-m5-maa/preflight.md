# M5-MAA preflight

Recorded: 2026-07-12, America/Chicago

## Task

- Task ID: M5-MAA
- Objective: evaluate whether MaaFramework provides a measurable benefit for the representative
  startup flow without introducing uncontrolled pipeline actions, retries, or policy bypass.
- Satisfied dependencies: M5-CUSTOM-BASELINE Passed (`d7cbca5`); M5-AIRTEST Rejected
  (`d74d345`); MVP startup-normalization corpus retained; RT-019 and RT-021 Passed.
- Acceptance criteria: use the identical retained corpus and target/policy contract; evaluate
  capture/profile enforcement, Cash Mall/Ending Soon/Home/Base recognition, detector and OCR
  coverage, stale/unknown rejection, one-input/immediate-recapture semantics, reconnect behavior,
  unprivileged-worker packaging, CPU/memory implications, diagnostics, testability,
  maintainability, deployment complexity, and SQLite/controller compatibility; retain an
  evidence-backed Passed or Rejected decision.

## Intended operations

1. Perform read-only local availability and native/package inspection. No Maa package, native
   library, CLI, or pipeline runtime is installed in the current worker environment.
2. Review the official MaaFramework API/pipeline/dependency surface and compare it with the
   RT-021 unprivileged worker boundary and the central project policy contract.
3. Run only offline/mock policy-contract review against the same five-fixture corpus. Do not
   start a native framework runtime, install dependencies, connect ADB, launch the game, or send
   input.
4. Preserve the candidate's failure/early-rejection reason if it cannot be packaged and wrapped
   cleanly without a material new native dependency or policy bypass.

## Verification procedure

- Record module/CLI/native availability, dependency and packaging facts, and official-source
  links.
- Use the passed custom baseline `benchmark.json` as the reference measurement set; do not
  manufacture live Cash Mall taps to fill candidate counts.
- Verify that pipeline/action semantics would remain behind the project policy gate and that
  stale, profile-mismatch, unknown-overlay, repeated-input, and target-overlap cases remain
  denied.
- Independently review every criterion, retain unsupported/failed claims, run secret scans and
  repository consistency checks, inspect the complete task diff, and commit one Maa-scoped
  decision.

## Evidence and rollback

- Evidence directory: `evidence/sessions/20260712-m5-maa/`.
- Planned artifacts: `preflight.md`, `record.md`, `availability.json`, and any small static
  policy-review result needed to support the decision.
- Required credentials/manual dependency: none. No SSH, VM, ADB, game, account, or user input is
  required; this candidate boundary is repository-only.
- Permissions: repository write for task evidence and one Git commit; no package installation,
  host operation, or unrelated workload change.
- Rollback: remove only task-scoped Maa evidence/prototype files if rejected; preserve the custom
  baseline, Airtest rejection, MVP corpus, runtime, backup, profile, and unrelated worktree
  files.
