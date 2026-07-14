# DQ-FLOW-RECRUITMENT

Repository authority: catalog owns `recruit_noahs_tavern`; matrix owns status/policy; backlog owns task.
Main Quest Claim excluded.

Scope: Recruit 5x in Noah's Tavern. Reuse Daily inventory, Tavern route, free-recruitment
contract, safe action core. Route: Daily row → Noah's Tavern. Source: completed row and Tavern
availability; target: exact recruitment control; successor: recruitment count increased. Bind all
to current frame.

Policy: evidence-gated free action; verify quota and no resource cost before promotion. Transaction:
bounded exact recruitment dispatch with unresolved blocking. Postcondition: requested count confirmed.
Recovery: fail closed on insufficient free quota, stale frame, ambiguity, or partial result.
Daily reconciliation maps `recruit_noahs_tavern`; Claim independent. Persistence/scheduler dormant.

Tests: offline free-contract replay, five-count semantics, dispatch cardinality, successor proof,
registration/scheduler dormancy, and Main negative recognition. Bliss-native evidence required;
GnBots is provenance only. Future navigation read-only. Prohibit ADB, worker/VM, lease/journal
changes, live input/evidence, registration, scheduler eligibility. Update docs/matrix/status.
Current boundary: existing `tasks/free_recruitment.py` and `tests/test_free_recruitment.py` provide
pure free-single replay semantics; fresh Bliss-native Tavern target and positive result remain
required for promotion. Commit: `feat(tasks): complete free Recruitment offline contract`.
Continue offline.
