# DQ-FLOW-BUILDING-UPGRADE

Repository authority: catalog owns `upgrade_building`; matrix owns disabled policy/status; backlog owns task.
Main Quest Claim excluded.

Scope: proven generic building-upgrade row only. Vehicle Depot wording is PROVEN_MAIN_OBJECTIVE
and is not a Daily alias or handler variant. Reuse building identity and offline route model only.
Route: Daily row → building target. Source: row,
building identity, and current level; target: exact upgrade control; successor: level change.
Bind all recognizers to current frame in any future implementation.

Policy: DISABLED_POLICY; no material spend, transaction, registration, scheduler eligibility, or
live input. Offline generic building identity/level contract is implemented in
`tasks/building_upgrade_disabled.py`; Vehicle Depot remains Main-only and every dispatch blocks.
Postcondition: offline contract proves no dispatch. Recovery: fail closed on ambiguous building,
cost, stale frame, or successor. Daily maps `upgrade_building`; Claim separate. Persistence dormant.

Tests: `tests/test_building_upgrade_disabled.py` covers generic identity reconciliation, Main-
negative Vehicle Depot rejection, disabled validator, no registry, scheduler false, offline model,
and Claim separation. Bliss/GnBots cannot override policy. Future
navigation read-only. Update docs/matrix/status. Commit:
`docs(tasks): map every Daily objective to an execution task`. Continue offline.
