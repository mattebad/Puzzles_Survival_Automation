# DQ-FLOW-TRAINING

Repository authority: catalog owns `train_fighter`, `train_rider`, `train_shooter`, `train_vehicle`; matrix
owns disabled policy/status; backlog owns task. Main Quest Claim excluded.

Scope: parameterized training variants with distinct unit identities. Reuse training route and
offline resource model. Route: Daily row → training facility → selected unit. Source: row and
unit/facility; target: exact training control; successor: queue/count progress. Bind current frame.

Policy: DISABLED_POLICY; no resource transaction, dispatch, or promotion. Postcondition: offline
contract proves no live action. Recovery: fail closed on ambiguous unit, cost, queue, or successor.
Daily reconciliation preserves four keys; Claim independent. Persistence/scheduler dormant.

Tests: variant separation, no duplicate ownership, disabled-flow validator, no registry entry,
scheduler false, offline queue model, Main negative, and Claim separation. Bliss/GnBots evidence
cannot override policy. Future navigation read-only only. Prohibit runtime registration, scheduler
eligibility, ADB, live input/evidence, worker/VM, leases, journal migration. Update docs/matrix/status.
Commit: `docs(tasks): map every Daily objective to an execution task`. Continue offline.
