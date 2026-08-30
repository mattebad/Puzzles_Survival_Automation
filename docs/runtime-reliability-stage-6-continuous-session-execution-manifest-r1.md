# Runtime Reliability Stage 6 continuous-session execution manifest r1

## Task ID and objective

- Task ID: `continuous-development-session-thin-conduct`
- Objective: Make one `DevelopmentSession` own initial observation through route-verified terminal recovery for Resource and World, while keeping `conduct` a thin admission/classification layer.

## Frozen stage control

- Host: `codex`
- Parent conversation ID: `01a02175-5bc3-7033-b401-621bb9041a4c`
- `control_plane_owner`: `sol_parent`
- Revision ID: `continuous-development-session-thin-conduct-r1`
- Stage type: `cross_contract_implementation`
- Product precondition: `not_applicable_offline_foundation`
- Failure class: `none`
- Stage start UTC: `2026-08-21T03:08:10.617Z`
- Continuation checkpoint UTC: `2026-08-21T02:08:11.674Z`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` / `architecture_planner` | `gpt-5.6-sol-medium` | Stage freeze, architecture, writable scope, acceptance, live admission, classification, status, and termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One mutable implementation turn within the exact allowlist |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only diff-and-acceptance review and, only if needed, one bounded recheck |
| `procedure_coordinator` / `escalation_architect` | `not used` | No authority |

## Immutable budgets

- One mutable implementation, one independent review, at most one parent-authorized consolidated repair and one recheck.
- One parent integration decision.
- At most one zero-input runtime observation and one navigation-only native shadow after all pre-canary gates pass.
- Zero Resource use, claims, purchases, Enhancement consumption, Flee, Gathering node/march input, combat, or currency input.
- No full repository discovery.
- At 60 elapsed minutes record a visible checkpoint; after 90 minutes, further managed delegation or live admission requires a later explicit user continuation.

## Frozen architecture decision

- Keep `DevelopmentSession` as the single authoritative ownership, observation, input-accounting, control-memory, evidence-topology, and terminal-summary boundary for migrated flows.
- Remove the separate `development-session observe` pre-step from live `conduct` for the migrated Resource and World paths. The first native observation is created, typed, retained, and passed to the adapter inside the same run-flow session.
- Keep `conduct` thin: framing/admission, exactly one run-flow invocation, route-specific verifier gating, convergence history, and final classification. It must not absorb Resource or World route planning.
- Promote Resource and World as the representative pair. Resource proves effect-authority/reconciliation continuity; World proves non-effect navigation, known-popup recovery, and terminal verification.
- Retain session-wide shared control memory for viewport/list signatures, direction, target history, settle history, recovery result, and pending semantic intent without giving that memory input authority.
- Emit exactly one read-only causal trace per attempt and explicitly label proof topology `continuous` or `composite`. A composite or unverified trace cannot become continuous or authorize `DONE`.
- A dispatch-bearing unknown effect is `effect_reconciliation_required`, not proof of failure or success. It blocks identical retry, remains persisted outside chat/process memory, and re-enters through observe-only reconciliation.
- Monitoring issue `MONITOR-UNOBSERVED-EFFECT-RECONCILIATION`: a real effect may occur while visual/semantic recognition misses it. This stage preserves the ambiguity and retry denial; future flow migrations must measure false-unknown frequency and improve flow-specific reconciliation without weakening effect authority.

Preserved invariants: SafetyStore and Resource effect authority; native 800×1280 current-frame binding; one runtime singleton; no nested ownership; existing route controllers and Home Atlas behavior; no generic Confirm; fail closed on unknown/contradictory state; no identical retry; production registration `NOT_REGISTERED`; scheduler disabled; protected evidence and unrelated work unchanged.

## Writable paths

Production:

- `scripts/pnsctl.py`
- `scripts/navigation_development_boundary.py`
- `tasks/flow_conductor.py`
- `scripts/flow_delivery_daily_resource_item_bluestacks.py`
- `scripts/flow_delivery_world_map_bluestacks.py`

Tests:

- `tests/test_development_session.py`
- `tests/test_navigation_development_boundary.py`
- `tests/test_flow_conductor.py`
- `tests/test_flow_delivery_lean_workflow.py`
- `tests/test_flow_delivery_daily_resource_item_bluestacks.py`
- `tests/test_world_map_navigation_bluestacks.py`

Parent-owned stage control and closure:

- `docs/runtime-reliability-stage-6-continuous-session-execution-manifest-r1.md`
- `docs/runtime-reliability-stage-6-flow-migration-packets.md`
- `docs/runtime-reliability-convergence-status.md`
- `CURRENT_HANDOFF.md`

No other production, test, fixture, plan, queue, backlog, registration, scheduler, or evidence path is writable without a parent architecture decision and a new frozen revision.

## Acceptance checks

- Resource and World live-conduct code paths invoke exactly one `development_session_run_flow` and never a separate `development_session_observe`.
- A validated typed initial observation and its native frame hash belong to the same session and are passed to the representative adapter.
- The adapter proves it is using the parent-owned active session; nested/subprocess `DevelopmentSession` ownership is rejected.
- One authoritative input count matches retained transports; no transport is counted twice or omitted.
- Session-wide control memory and exactly one causal trace remain observability/state only and never become input authority.
- Proof topology is explicit and fail closed: `continuous` requires one invocation/session chain; historical or cross-session proof remains `composite`.
- `conduct --live --max-inputs 1` is rejected for acceptance paths; direct one-input development diagnostics remain non-accepting evidence.
- Raw wrapper/process completion cannot produce `DONE`; the route-specific checked-in verifier must pass.
- Dispatch-bearing unknown effect or terminal state is preserved as reconciliation-required, cannot become `DONE`, and cannot authorize an identical retry.
- Resource retains its static-UTC identity, one-use ceiling, SafetyStore reservation/reconciliation, and no new live use.
- World retains zero resource/combat/node/march/formation/stamina/AP/currency inputs, current-frame binding, known-popup-only recovery, and Home terminal verification.
- Daily Claim, Nova, Enhancement, and Ultimate receive exact Medium migration packets. Enhancement stays truthfully composite without consumption; Ultimate never repeats Flee and is terminal-reconciliation-only.
- Focused, affected-package, shared-navigation, architecture, diff, and independent-review gates pass.
- Registration remains `NOT_REGISTERED`; scheduler eligibility remains disabled.

## Safety limits

- Allowed offline actions: edit only the allowlist; deterministic tests; checked-in focused/shared-navigation/architecture validators; retained-evidence reads only when directly referenced.
- Allowed live actions after parent integration acceptance: one zero-input `pnsctl development-session observe`; optionally one full World navigation-only shadow through `pnsctl conduct`, bounded by 12 total inputs and existing route limits.
- Disallowed: live Resource use; `--max-inputs 1` acceptance; separate pre-run observation for migrated conduct; nested runtime owner; generic popup dismissal; unknown-popup input; purchase/claim/Enhancement/Flee/Gathering/combat/currency input; registration; scheduling; push; full discovery.
- Scarlett Store remains an unknown surface until an independently grounded recognizer, reversible close binding, negative corpus, and verified successor contract exist. It receives zero input in this stage.

## Validation commands

- `python -m unittest tests.test_development_session tests.test_navigation_development_boundary tests.test_flow_conductor tests.test_flow_delivery_lean_workflow`
- `python -m unittest tests.test_flow_delivery_daily_resource_item_bluestacks tests.test_world_map_navigation_bluestacks`
- `python scripts/run_flow_delivery_validation.py focused --flow-id DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- `python scripts/run_flow_delivery_validation.py focused --flow-id WORLD-MAP-NAVIGATION-FOUNDATION`
- `python scripts/run_flow_delivery_validation.py shared-navigation --flow-id WORLD-MAP-NAVIGATION-FOUNDATION`
- `python scripts/run_flow_delivery_validation.py architecture --flow-id DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- `git diff --check`

## Live budget

- Live admission: `conditional_after_parent_integration_acceptance`
- Zero-input observation budget: one session, zero inputs.
- Optional native shadow: one full World navigation-only `pnsctl conduct` attempt, maximum 12 inputs under stricter route-local limits.
- Consequential/resource/combat/currency budget: zero.
- Runtime target: private local BlueStacks, checked-in standard 800×1280 profile and allowlisted serial only.

## Evidence/history references

- Stage 3 accepted control primitives: `docs/runtime-reliability-stage-3-control-primitives-execution-manifest-r3.md`.
- Resource retained accepted canary: `.local-captures/development-sessions/DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION-20260820T212159603189Z`.
- Existing World navigation fixtures/tests and directly referenced retained session paths only; do not recursively inspect evidence.
- Existing Enhancement evidence remains composite; existing Ultimate Flee evidence is immutable and must not be repeated.

## Escalation conditions

- Singleton ownership or input accounting regresses or becomes ambiguous.
- `conduct` begins absorbing flow-specific planning or policy decisions.
- A one-session contract cannot serve both Resource and World without flow-specific special cases in shared code.
- Unknown effect handling would require inferring success/failure, weakening retry denial, or broadening runtime authority.
- A new visual selector or popup action is required without independent ground truth.
- Retained evidence contradicts continuous-session or route-verifier claims.
- Tester and implementation evidence conflict, two materially different repairs would be required, or convergence stalls.
- Ordinary syntax/test defects remain `local_defect` and may receive only the one consolidated repair.
