# DQ-FLOW-SPEEDUP

Repository authority: catalog owns `speedup_using_items`; matrix owns disabled policy/status; backlog owns
task. Main Quest Claim excluded.

Scope: Speedup 180 minutes using items. Reuse timer identity and offline duration model only.
Route: Daily row → selected timer → speedup. Source: row, timer, item inventory; target: exact
speedup control; successor: timer duration decreased and progress confirmed. Bind current frame.

Policy: DISABLED_POLICY; no item consumption, transaction, registration, scheduler eligibility, or
live input. Postcondition: offline contract proves no dispatch. Recovery: fail closed on timer,
duration, item, stale-frame, or successor ambiguity. Daily maps `speedup_using_items`; Claim separate.
Persistence dormant.

Tests: 180-minute quantity model, disabled validator, no registry, scheduler false, Main negative,
Claim separation. Bliss/GnBots cannot override policy. Future navigation read-only. Update docs/
matrix/status. Commit: `docs(tasks): map every Daily objective to an execution task`. Continue offline.
