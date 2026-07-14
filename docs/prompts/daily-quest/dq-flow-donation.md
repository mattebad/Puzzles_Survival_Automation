# DQ-FLOW-DONATION

Repository authority: catalog owns `donate_alliance_tech`; matrix owns disabled policy/status; backlog owns
task. Main Quest Claim excluded.

Scope: Alliance tech donation. Reuse Alliance route and offline donation model only. Route: Daily
row → Alliance tech. Source: row, tech target, donation inventory; target: exact donate control;
successor: donation count/tech progress. Bind current source/target/successor.

Policy: DISABLED_POLICY; no item/currency transaction, runtime registration, scheduler eligibility,
or live input. Alliance Technology target/resource replay is implemented in
`tasks/donation_disabled.py`; every donation dispatch remains blocked. Postcondition: offline
contract proves no dispatch. Recovery: fail closed on target, resource, stale frame, or successor
ambiguity. Daily maps `donate_alliance_tech`; Claim separate. Persistence dormant.

Tests: `tests/test_donation_disabled.py` covers target/resource identity, cost and count arithmetic,
disabled dispatch, no registry, scheduler false, Main/ambiguous negatives, and Claim separation.
Bliss/GnBots cannot override policy. Future navigation read-only. Update docs/matrix/status. Commit:
`feat(tasks): add disabled donation contract`. Continue offline.
