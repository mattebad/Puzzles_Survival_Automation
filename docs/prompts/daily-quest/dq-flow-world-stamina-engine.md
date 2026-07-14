# DQ-FLOW-WORLD-STAMINA-ENGINE

Repository authority: matrix owns shared primitive status/policy; catalog owns only objective identity;
backlog owns task. Main Quest Claim excluded.

Scope: offline shared world navigation and stamina/AP accounting primitive for proven Zombie Lair,
gathering, and future world flows. Hunt Zombie and Headquarters candidates are not Daily scope.
Reuse world route recognizers,
resource counters, safe action core. Route: Daily row → world target. Source: current world/home
frame and resource state; target: exact world destination; successor: stable destination/resource
state. Bind current frame before any future consequential input.

Policy: offline-only contract; no resource transaction or live action now. Postcondition: route
and budget model deterministic, never authorization. Recovery: fail closed on stale route, resource
uncertainty, or unresolved action. Daily reconciliation is per objective; Claim independent.
Persistence/scheduler dormant.

Tests: route fixture replay, counter semantics, budget bounds, stale-day rejection, family ownership,
and no-runtime-state assertions. Bliss-native evidence only; GnBots geometry cannot authorize.
Future navigation read-only. Prohibit ADB, worker/VM, leases, journal migration, live input/evidence,
registration, and scheduler eligibility. Current boundary: `tasks/world_stamina.py` and
`tests/test_world_stamina.py` provide pure route/resource replay; no world action is executable.
Update primitive docs/matrix. Commit: `feat(tasks): add World stamina offline primitive`. Continue
offline.
