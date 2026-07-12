# M7-SAFE-ACTION-CORE preflight

Recorded: 2026-07-12, America/Chicago

- Dependency: M6-DQ-BOOTSTRAP Passed at `c2c5a3d`.
- Objective: implement the minimum repository-only fail-closed action journal, lease, central
  policy, exactly-one-input executor, and reconciliation API for one future supervised trial.
- Acceptance: SQLite schema/versioning, durable lifecycle, exclusive lease, policy-only
  authorization, mandatory immediate recapture, exactly one injected transport call,
  positive postcondition confirmation, unresolved global blocking, crash-boundary tests, M6
  fixture denials, consistency checks, and secret scan all pass.
- Rollback: remove or disable only the new `safe_action_core` package and its tests; retain all
  test/evidence failures. No runtime state is changed.
- Live boundary: no Unraid, VM, ADB, game, container, tunnel, or runtime-network access is
  authorized or required.
- Protected worktree: the eight pre-existing metadata-only entries were hash-compared with
  `HEAD` before implementation and matched; they remain excluded from this task.
