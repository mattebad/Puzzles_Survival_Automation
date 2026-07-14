# DQ-FLOW-RESOURCE-BOOST

Repository authority: catalog owns `boost_resource_building_output`; matrix owns disabled policy/status;
backlog owns task. Main Quest Claim excluded.

Scope: boost any resource building output. Reuse building identity and offline boost model only.
Route: Daily row → selected resource building → boost. Source: row/building/resource identity;
target: exact boost control; successor: output boost state/timer. Bind current frame.

Policy: DISABLED_POLICY; no item/resource transaction, registration, scheduler eligibility, or live
input. Resource-building identity/duration replay is implemented in
`tasks/resource_boost_disabled.py`; every boost dispatch remains blocked. Postcondition: offline
contract proves no dispatch. Recovery: fail closed on building, resource, duration, stale frame, or
successor ambiguity. Daily maps `boost_resource_building_output`; Claim independent. Persistence
dormant.

Tests: `tests/test_resource_boost_disabled.py` covers resource-building identity, duration/cost
guards, disabled dispatch, no registry, scheduler false, Main/ambiguous negatives, and Claim
separation. Bliss/GnBots cannot override policy. Future navigation read-only. Update docs/matrix/
status. Commit: `feat(tasks): add disabled resource boost contract`. Continue offline.
