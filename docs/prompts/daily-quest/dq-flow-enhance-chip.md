# DQ-FLOW-ENHANCE-CHIP

Repository authority: catalog owns `enhance_chip`; matrix owns policy/status; backlog owns task. Main Quest
Claim excluded.

Scope: Chip enhancement, parameterized over selected chip and chip-specific postcondition.
Reuse gear enhancement engine, Commander Info route, safe action core. Route: Daily row →
Commander Info → Chip. Source: completed row and selected chip; target: exact enhance control;
successor: chip level/quality changed. Bind current source/target/successor.

Policy: evidence-gated material cost. Transaction: one exact dispatch, bounded retry, unresolved
block. Postcondition: selected chip enhancement confirmed. Recovery: fail closed on selection,
resource, stale-frame, or successor ambiguity. Daily maps `enhance_chip`; Claim separate.
Persistence/scheduler dormant.

Tests: shared-family ownership, chip/gear distinction, cost guard, replay, cardinality, successor,
Main negative, registration false, scheduler false. Bliss-native evidence required; GnBots never
authorizes. Future navigation read-only. Prohibit ADB, worker/VM, leases, journal migration, live
input/evidence, registration, scheduler eligibility. Current boundary: shared
`tasks/enhancement.py` plus `tasks/daily_enhancement.py` now implement selected-Daily Chip
ownership, one-star material guards, one-enhancement replay, and Daily 0/1 successor proof;
promotion still requires fresh Bliss-native Chip evidence. Tests:
`tests/test_enhance_chip.py` and `tests/test_daily_enhancement_chip.py`. Update docs/matrix/status
when contract changes.
Continue offline. Commit: `feat(tasks): complete Chip enhancement variant`.
