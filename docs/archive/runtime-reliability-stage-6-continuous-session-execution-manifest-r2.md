# Runtime Reliability Stage 6 continuous-session execution manifest r2

## Task ID and objective

- Task ID: `continuous-development-session-thin-conduct`
- Objective: Correct the r1 reconciliation-required convergence defect without changing the accepted continuous-session architecture or representative adapters.

## Frozen stage control

- Host: `codex`
- Parent conversation ID: `01a02175-5bc3-7033-b401-621bb9041a4c`
- `control_plane_owner`: `sol_parent`
- Revision ID: `continuous-development-session-thin-conduct-r2`
- Stage type: `step_back_core_contract_repair`
- Product precondition: `not_applicable_offline_foundation`
- Failure class: `core_contract`
- Stage start UTC: `2026-08-21T18:20:39.840Z`
- Continuation checkpoint UTC: `2026-08-21T18:20:39.840Z`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` / `architecture_planner` | `gpt-5.6-sol-medium` | Stage freeze, architecture, writable scope, acceptance, classification, status, and termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One mutable correction turn within the exact allowlist |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only review of the r2 diff and frozen acceptance |
| `procedure_coordinator` / `escalation_architect` | `not used` | No authority |

## Immutable budgets

- One r2 implementation and one r2 read-only review.
- No r2 repair is pre-authorized. Any new must-fix issue returns to the parent for classification and termination/escalation under the conversation budget.
- R1 history remains immutable: one implementation, review, repair, and recheck already occurred.
- Zero live attempts and zero runtime inputs in r2.
- No full repository discovery.

## Frozen architecture decision

- Preserve the full r1 continuous-session candidate unchanged except for conductor classification and its exact tests.
- Treat `effect_reconciliation_required` as a hard `DONE` veto, not as an unconditional early `CONTINUE` return.
- On the first no-progress reconciliation-required summary, return `CONTINUE` with the stable signature `effect_reconciliation_required` when no more specific blocker exists.
- Feed subsequent identical no-progress summaries through the existing defect-signature and `iterations_since_progress` convergence logic: repeated state reaches `STEP_BACK`; after the existing one-step-back budget is spent, repetition reaches `ESCALATE`.
- A genuine new furthest milestone may still reset no-progress counting and return `CONTINUE` without proving the effect.
- Never infer effect success or failure, never produce `DONE`, never authorize identical transport retry, and never classify reconciliation-required as an external product blocker merely to avoid convergence.

Preserved invariants: all r1 Resource/World/session/trace/ownership/input-accounting changes; SafetyStore and effect authority; current-frame binding; route-verifier gating; thin `conduct`; registration `NOT_REGISTERED`; scheduler disabled; zero runtime input.

## Writable paths

Production:

- `tasks/flow_conductor.py`

Tests:

- `tests/test_flow_conductor.py`

Parent-owned stage control and closure:

- `docs/runtime-reliability-stage-6-continuous-session-execution-manifest-r2.md`
- `docs/runtime-reliability-convergence-status.md`
- `CURRENT_HANDOFF.md`
- local ignored umbrella plan todo status only

Every other r1 production, test, fixture, evidence, migration-packet, queue, registration, scheduler, and plan-content path is read-only.

## Acceptance checks

- A completed/evidence-verified summary with `effect_reconciliation_required` can never return `DONE`.
- First no-progress reconciliation-required iteration returns `CONTINUE` and records its signature.
- Second identical no-progress iteration returns `STEP_BACK` through the existing convergence mechanism.
- A further identical iteration after the step-back budget is spent returns `ESCALATE`.
- A changed furthest-progress milestone returns `CONTINUE` and resets the existing no-progress counter without clearing reconciliation-required or proving an effect.
- Nested `result`/route layers carrying reconciliation-required receive the same behavior.
- Existing ordinary blocked-flow, external-blocker, verified-DONE, furthest-progress, and diminishing-returns tests remain unchanged and pass.
- No adapter, session, trace, effect-authority, input-accounting, product-policy, registration, or scheduler code changes.

## Safety limits

- Allowed: offline edit of the two exact code/test paths; deterministic tests; focused/shared-navigation/architecture validation after integration.
- Disallowed: runtime/emulator/ADB/gameplay input; adapter edits; Resource use; popup interaction; live observation/shadow; registration; scheduling; commit; push; evidence mutation.
- Runtime/session limits: zero runtime sessions and zero inputs.

## Validation commands

- `python -m unittest tests.test_flow_conductor.FlowConductorTests.test_effect_reconciliation_never_becomes_done`
- exact new repeated-reconciliation regressions in `tests.test_flow_conductor`
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

- R1 manifest: `docs/runtime-reliability-stage-6-continuous-session-execution-manifest-r1.md`, SHA-256 `ac3fc7bb21008aabaa77857b23ad94b026c115f7ffd5644afac3e1b9ef03202d`.
- R1 independent adapter-admission finding and resolved recheck are recorded in `CURRENT_HANDOFF.md` and `docs/runtime-reliability-convergence-status.md`.
- R1 final parent blocker: unconditional reconciliation-required early return bypasses repeated-defect/diminishing-returns classification.

## Escalation conditions

- The correction requires changing adapters, session ownership, effect authority, or runtime-input policy.
- Reconciliation-required cannot preserve both fail-closed effect semantics and bounded convergence through the existing conductor state.
- Ordinary flow outcomes regress or the r2 reviewer finds a concrete new safety/acceptance defect.
- Any runtime evidence is proposed or used.
