# DQ-FLOW-CHALLENGES

Repository authority: catalog owns proven `ruins_challenge`; matrix owns disabled policy/status;
backlog owns task. Ultimate Challenge is excluded as PROVEN_MAIN_OBJECTIVE. Main Quest Claim
excluded.

Scope: Ruins Challenge route only. Route: Daily row → declared challenge. Source: selected-Daily
row and challenge identity; target: exact challenge control; successor: challenge result/progress.
Bind current frame.

Policy: DISABLED_POLICY; no challenge entry, resource transaction, registration, scheduler eligibility,
or live input. Ruins Challenge identity/cost/result replay is implemented in
`tasks/challenge_disabled.py`; Ultimate Challenge remains Main-only and every entry dispatch is
blocked. Postcondition: offline contract proves no dispatch. Recovery: fail closed on challenge,
cost, stale-frame, or result ambiguity. Claim independent. Persistence dormant.

Tests: `tests/test_challenge_disabled.py` covers Ruins identity, cost/AP guards, disabled dispatch,
no registry, scheduler false, selected-Daily provenance, Ultimate/Main/ambiguous negatives, and
Claim separation. Bliss/GnBots cannot override policy. Future navigation read-only. Update
docs/matrix/status. Commit: `feat(tasks): add disabled Ruins Challenge contract`. Continue offline.
