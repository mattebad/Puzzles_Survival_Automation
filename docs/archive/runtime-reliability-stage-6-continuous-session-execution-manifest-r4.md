# Runtime Reliability Stage 6 continuous-session execution manifest r4

## Task ID and objective

- Task ID: `continuous-development-session-thin-conduct`
- Objective: Close the two independently confirmed r3 core-contract defects while preserving the accepted continuous-session architecture and zero-input safety envelope.

## Frozen stage control

- Host: `codex`
- Parent conversation ID: `01a02175-5bc3-7033-b401-621bb9041a4c`
- `control_plane_owner`: `sol_parent`
- Revision ID: `continuous-development-session-thin-conduct-r4`
- Stage type: `explicitly_authorized_same_chat_continuation`
- Product precondition: `not_applicable_offline_foundation`
- Failure class: `core_contract`
- Stage start UTC: `2026-08-21T21:23:03.003Z`
- Continuation checkpoint UTC: `2026-08-21T21:23:03.003Z`
- User authorization: explicit same-chat continuation after the r3 terminal checkpoint.

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` / `architecture_planner` | `gpt-5.6-sol-medium` | Manifest freeze, architecture, scope, acceptance, classification, status, and termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One mutable implementation turn within the exact allowlist |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only diff-and-acceptance review; one recheck only if a repair is authorized |
| `procedure_coordinator` / `escalation_architect` | `not used` | No authority |

## Immutable budgets

- This user-authorized continuation has one implementation and one independent review.
- At most one parent-classified consolidated repair and one recheck are available.
- Zero live attempts, zero runtime sessions, and zero runtime inputs.
- No full repository discovery.

## Frozen architecture decision

Finding 1 — same-layer external-blocker precedence:

- Inspect both `status` and `terminal` independently in every summary layer; a benign/completed value in one field must never hide an external/manual-only value in the other.
- Inspect blocker, reason, and next-action text in the same fail-closed pass.
- External/manual-only state precedes verified `DONE` and reconciliation convergence.
- Preserve the exact matching blocker text when present, otherwise the stable matching external token.

Finding 2 — World acceptance metadata consistency:

- Diagnostic search-entry evidence must retain `proof_topology: diagnostic`, `acceptance_eligible: false`, and non-accepting `diagnostic_verified` semantics.
- Full/recovery accepting evidence must retain continuous topology and must not carry explicit non-accepting metadata.
- Any contradiction between route class, result topology, trace topology, or acceptance eligibility fails closed before `verified`.
- Absence of `acceptance_eligible` on continuous legacy/current evidence remains accepting-compatible; an explicit false value is contradictory and rejected.

Preserved invariants: one authoritative `DevelopmentSession`, typed session-bound initial observation, retained transport accounting, read-only causal trace, Resource effect authority, World current-frame/popup/Home safety, thin conduct, bounded convergence, registration `NOT_REGISTERED`, scheduler disabled, and zero runtime authority.

## Writable paths

Production:

- `tasks/flow_conductor.py`
- `scripts/flow_delivery_world_map_bluestacks.py`

Tests:

- `tests/test_flow_conductor.py`
- `tests/test_world_map_navigation_bluestacks.py`

Parent-owned control and closure:

- `docs/runtime-reliability-stage-6-continuous-session-execution-manifest-r4.md`
- `docs/runtime-reliability-convergence-status.md`
- `CURRENT_HANDOFF.md`
- local ignored umbrella-plan todo status only

All other production, tests, evidence, manifests, queues, registration, scheduler, and plan content are read-only.

## Acceptance checks

- `status: completed` plus `terminal: manual_required` returns `EXTERNAL_BLOCK`, never `DONE`, including nested equivalents.
- The inverse same-layer order and status-only/terminal-only external states behave consistently.
- Existing all-layer external-blocker and r2 reconciliation convergence tests remain green.
- Continuous World evidence explicitly marked `acceptance_eligible: false` in either result or causal trace fails closed.
- Diagnostic World evidence still returns `diagnostic_verified` with `acceptance_eligible: false`.
- Full/recovery evidence without contradictory metadata still returns `verified` and remains continuous.
- Conduct cannot turn either contradictory evidence form into `DONE`.
- No runtime-input, registration, scheduling, or unrelated behavior changes.

## Safety limits

- Allowed: offline edits to the four exact code/test paths and deterministic checked-in validation profiles.
- Disallowed: emulator/ADB/BlueStacks/gameplay input; live observation/shadow; evidence mutation; registration; scheduling; commit; push; downstream migration.
- Runtime/session limits: zero runtime sessions and zero inputs.

## Validation commands

- Exact new same-layer blocker and contradictory-eligibility regressions.
- `python -m unittest tests.test_flow_conductor tests.test_world_map_navigation_bluestacks`
- `python -m unittest tests.test_flow_conductor tests.test_development_session tests.test_navigation_development_boundary tests.test_flow_delivery_lean_workflow`
- `python -m unittest tests.test_flow_delivery_daily_resource_item_bluestacks tests.test_world_map_navigation_bluestacks`
- `python scripts/run_flow_delivery_validation.py focused --flow-id DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- `python scripts/run_flow_delivery_validation.py focused --flow-id WORLD-MAP-NAVIGATION-FOUNDATION`
- `python scripts/run_flow_delivery_validation.py shared-navigation --flow-id WORLD-MAP-NAVIGATION-FOUNDATION`
- `python scripts/run_flow_delivery_validation.py architecture --flow-id DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- `git diff --check`

## Live budget

- Live admission: `not_authorized`
- Input budget: zero
- Iteration budget: zero live iterations

## Evidence/history references

- R3 manifest SHA-256: `e9a96bb63543966ef007183de92018c814c5053f20de45991698129c4d7d984f`.
- R3 final reviewer findings and parent reproductions are recorded in `CURRENT_HANDOFF.md` and `docs/runtime-reliability-convergence-status.md`.

## Escalation conditions

- Either fix requires changing the continuous-session architecture or broadening runtime authority.
- A must-fix safety or acceptance defect remains after the available repair/recheck.
- Tester and implementation evidence conflict.
- Any runtime evidence or input is proposed or used.
