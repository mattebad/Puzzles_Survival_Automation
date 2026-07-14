# DQ-FLOW-TECH-UPGRADE

Repository authority: catalog owns `upgrade_tech`; matrix owns disabled policy/status; backlog owns task.
Main Quest Claim excluded.

Scope: Tech upgrade. Reuse tech identity and offline prerequisite model only. Route: Daily row →
Tech. Source: row, selected tech, prerequisites; target: exact research/upgrade control; successor:
tech level/state change. Bind source/target/successor to current frame.

Policy: DISABLED_POLICY; no consequential input, resource transaction, registration, or scheduler
eligibility. Offline prerequisite/level contract is implemented in
`tasks/tech_upgrade_disabled.py`; every research dispatch remains blocked. Postcondition: offline
contract proves no dispatch. Recovery: fail closed on prerequisite, cost, stale-frame, or successor
ambiguity. Daily maps `upgrade_tech`; Claim independent. Persistence dormant.

Tests: `tests/test_tech_upgrade_disabled.py` covers disabled validator, prerequisite model, no
registry, scheduler false, Main negative, Claim separation, and level successor replay. Bliss/GnBots
evidence cannot override policy. Future navigation read-only only. Update
docs/matrix/status. Commit: `docs(tasks): map every Daily objective to an execution task`. Continue
offline; stop only on policy contradiction.
