# DQ-FLOW-SPEEDUP

Repository authority: catalog owns `speedup_using_items`; matrix owns disabled policy/status; backlog owns
task. Main Quest Claim excluded.

Scope: Speedup 180 minutes using items. Reuse timer identity and offline duration model only.
Route: Daily row → selected timer → speedup. Source: row, timer, item inventory; target: exact
speedup control; successor: timer duration decreased and progress confirmed. Bind current frame.

Policy: DISABLED_POLICY; no item consumption, transaction, registration, scheduler eligibility, or
live input. The 180-minute timer/item replay contract is implemented in
`tasks/speedup_disabled.py`; every speedup dispatch remains blocked. Postcondition: offline
contract proves no dispatch. Recovery: fail closed on timer, duration, item, stale-frame, or
successor ambiguity. Daily maps `speedup_using_items`; Claim separate. Persistence dormant.

Tests: `tests/test_speedup_disabled.py` covers 180-minute quantity, timer/item arithmetic, disabled
dispatch, no registry, scheduler false, Main/ambiguous negatives, and Claim separation. Bliss/GnBots
cannot override policy. Future navigation read-only. Update docs/matrix/status. Commit:
`feat(tasks): add disabled speedup contract`. Continue offline.
