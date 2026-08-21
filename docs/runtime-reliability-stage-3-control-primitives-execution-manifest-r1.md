# Runtime Reliability Stage 3 control-primitives execution manifest

## Task ID and objective

- Task ID: `runtime-reliability-stage-3-control-primitives`
- Objective: Add three pure shared runtime-control primitives and a read-only causal trace projection, proven only through provenance-bound offline replay, without changing production flow adapters or runtime authority.

## Frozen stage control

- Host: `codex`
- Parent conversation ID: `01a02175-5bc3-7033-b401-621bb9041a4c`
- `control_plane_owner`: `sol_parent`
- Revision ID: `runtime-reliability-stage-3-control-primitives-r1`
- Stage type: `implementation`
- Product precondition: `not_applicable` (offline pure-primitives stage; no product action or runtime state is required)
- Failure class: `none`
- Stage start UTC: `2026-08-20T23:21:47.938Z`
- Continuation checkpoint UTC: `not recorded`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` / `architecture_planner` | `gpt-5.6-sol-medium` | Stage freeze, architecture, writable scope, integration acceptance, failure classification, status, and termination |
| `procedure_coordinator` | `not used` | No authority |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One mutable implementation turn within the assigned production/test/fixture paths only; self-checks but cannot change architecture or status |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only diff-and-acceptance review; reports findings only |
| `escalation_architect` | `not used unless an escalation condition occurs` | Architecture or safety conflicts only |

## Immutable budgets

- Per stage: one implementation, one review, at most one consolidated repair and one recheck, zero live attempts.
- Per parent conversation: this is revision 1 of at most three stage revisions; at most eight managed turns total.
- Timing: visible checkpoint at 60 minutes; after 90 minutes, further managed delegation requires recorded user continuation later than the stage start.

## Frozen architecture decision

- Decision: Add three small, pure, input-free value/state primitives: stable transition polling; list/card search state; and source-context modal/recovery classification. Add a separate read-only causal trace projection over existing observations, intents, transports, settled successors, semantic results, and terminal results. These are shared seams, not a controller framework.
- Consumer rule: each promoted primitive must be exercised by at least two distinct replay consumers without flow-specific branches in shared code. Typed flow facts and policy remain adapter-owned.
- Preserved invariants: SafetyStore remains the sole safety persistence boundary; native frames and current-frame target binding remain authoritative; runtime singleton ownership, fail-closed behavior, existing route controllers, existing product policies, and Home Atlas measured panning remain unchanged. The trace is observability only and cannot authorize or infer runtime success. Production flow adapters, production registration, and scheduler eligibility remain unchanged.

## Writable paths

Production (bounded implementer):

- `tasks/transition_stability.py`
- `tasks/list_search.py`
- `tasks/perception_bundle.py`
- `scripts/bluestacks_popup_recognition.py`
- `scripts/navigation_development_boundary.py`
- `scripts/runtime_trace_projection.py`

Tests and fixtures (bounded implementer):

- `tests/test_transition_stability.py`
- `tests/test_list_search.py`
- `tests/test_runtime_trace_projection.py`
- `tests/test_perception_bundle.py`
- `tests/test_navigation_development_boundary.py`
- `tests/test_vip_points_popup.py`
- minimal provenance-bound files under `tests/fixtures/runtime_control_sequences/`

Stage control and closure (parent only):

- `docs/runtime-reliability-stage-3-control-primitives-execution-manifest-r1.md`
- `docs/runtime-reliability-convergence-status.md`
- `CURRENT_HANDOFF.md`

No path outside this allowlist may be mutated without a parent-owned architecture decision and a new frozen revision.

## Acceptance checks

- Stable polling deterministically distinguishes transient, stable, timeout, and contradictory successors, preserves typed observations, and issues no input.
- List search inspects before motion; tracks frame/list signatures, displacement, and direction; stops on target visibility; detects no-motion and repeated states; permits at most one evidence-driven reversal; and issues no input during replay.
- Modal/recovery classification preserves source context, distinguishes contextual dismiss/recovery behavior, exposes no generic Confirm authority, and fails closed on unknown or contradictory surfaces.
- Trace projection joins `observation -> intent -> transport -> settled successor -> semantic result -> terminal result` without mutating authority/evidence, preserves unknown and contradictory states, and never infers transport or semantic success from dispatch alone.
- Resource, Enhancement, Claim, Nova, Ultimate, VIP, one shop/list flow, and Gathering/Search exercise applicable primitives using retained provenance-bound evidence. Missing proof is reported as `evidence_required`; no synthetic or placeholder proof is created.
- At least two distinct replay consumers exercise each promoted primitive.
- Shared modules contain no flow-specific product IDs, quantities, routes, selectors, or policy decisions; production flow adapters remain unchanged.
- Registration remains `NOT_REGISTERED`; scheduler eligibility remains disabled; runtime ownership remains absent; zero emulator/ADB/BlueStacks/gameplay input occurs.

## Safety limits

- Allowed actions: read repository state and targeted retained evidence; create the pure shared modules, typed seams, replay fixtures, and tests within the allowlist; run offline deterministic tests and validation profiles.
- Disallowed actions: emulator, ADB, BlueStacks, gameplay, runtime observation, `pnsctl development-session`, live canary, registration, scheduler changes, production adapter changes, SafetyStore changes, route-controller replacement, Home Atlas changes, generic Confirm authority, pushing, or committing the Stage 3 implementation.
- Runtime/session limits: no runtime session; singleton remains unowned; input budget is zero; consequential-action budget is zero.

## Validation commands

- `python -m unittest tests.test_transition_stability tests.test_list_search tests.test_runtime_trace_projection`
- `python -m unittest tests.test_perception_bundle tests.test_navigation_development_boundary tests.test_vip_points_popup`
- Replay tests for every represented flow class through the new primitive test modules and provenance-bound fixture corpus.
- `python scripts/run_flow_delivery_validation.py shared-navigation --flow-id DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- `python scripts/run_flow_delivery_validation.py architecture --flow-id DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- `git diff --check`

## Live budget

- Live admission: `not authorized`
- Input budget: `0`
- Iteration budget: `0`

## Evidence/history references

- `CURRENT_HANDOFF.md` at baseline closure commit `9e6f350b629c21f63eb89a0234ce902cfe664cb5`
- `docs/runtime-reliability-convergence-status.md`
- `.cursor/plans/p&s_runtime_reliability_convergence_program_e62703e1.plan.md`, Stage 5 only
- Completed context-only Resource child plan `C:/Users/burni/.cursor/plans/resource_effect_authority_integration_38cea4aa.plan.md`
- Targeted retained sessions and checked-in native assets/fixtures referenced by existing flow tests; evidence trees must not be recursively inspected or rewritten.

## Escalation conditions

- The approved plan is contradictory or incomplete.
- A genuinely new architecture decision is required.
- Safety authority is ambiguous or runtime-input authority would broaden.
- Tester and implementation evidence conflict.
- Two materially different repair hypotheses fail.
- Retained evidence contradicts a proposed primitive.
- Shared modules accumulate flow-specific product semantics, require replacing current route controllers, or cannot satisfy two distinct consumers without special cases.
- Convergence stalls (`diminishing_returns`): a repeat/known-hazard defect signature, at least three defects cluster in one subsystem, or two iterations make no furthest-progress advance.
- Ordinary syntax errors and parent-classified local defects may use the single consolidated repair; they do not independently authorize escalation.
