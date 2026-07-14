# DQ-FLOW-HERO-UPGRADE

Repository authority: catalog owns `upgrade_hero`; matrix owns disabled policy/status; backlog owns task.
Main Quest Claim excluded.

Scope: Hero upgrade. Reuse hero identity and offline material model only. Route: Daily row →
Hero. Source: row, selected hero, current level; target: exact upgrade control; successor: hero
level/state change. Bind source/target/successor to current frame.

Policy: DISABLED_POLICY; no resource transaction, live input, runtime registration, or scheduler
eligibility. Offline selected-hero/material/level contract is implemented in
`tasks/hero_upgrade_disabled.py`; every upgrade dispatch remains blocked. Postcondition: offline
contract proves no dispatch. Recovery: fail closed on hero, material, cost, stale-frame, or
successor ambiguity. Daily maps `upgrade_hero`; Claim independent. Persistence dormant.

Tests: `tests/test_hero_upgrade_disabled.py` covers disabled validator, hero/material identity,
level successor replay, no registry, scheduler false, Main/ambiguous negatives, and Claim
separation. Bliss/GnBots cannot override policy. Future navigation read-only. Update docs/matrix/
status. Commit: `feat(tasks): add disabled Hero Upgrade contract`. Continue offline.
