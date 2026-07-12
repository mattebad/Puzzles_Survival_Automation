# MVP-QUEST-TO-CLAIM preflight

Recorded: 2026-07-12, America/Chicago

- Dependencies: M6-DQ-BOOTSTRAP, M7-SAFE-ACTION-CORE, and
  MVP-STARTUP-NORMALIZATION are Passed; `MVP-QUEST-TO-CLAIM` is Ready.
- Objective: complete at most one positively identified zero-cost R1 Daily Quest objective when
  needed, claim exactly one ordinary completed row, prove its postcondition, and stop.
- Safety boundary: every game input must use the M7 lease, policy, persistent journal, immediate
  recapture, exactly-one injected ADB transport call, and positive reconciliation. OS-only
  startup reconciliation remains separate.
- Acceptance and stop conditions: as specified in the canonical backlog and task request. Any
  unknown identity, cost, count, overlay, reset boundary, successor, transport result, or
  postcondition stops without retry.
- Rollback: preserve the task database and evidence first, release the lease only after complete
  reconciliation, force-stop the game when safe, and remove only task-scoped workers/ADB state.
  VM XML, qcow2, network, runtime profile, RT-017 backup, and unrelated workloads remain unchanged.
- Protected worktree: the eight pre-existing metadata-only entries hash-match `HEAD` and remain
  excluded from edits, staging, normalization, restoration, and commits.
