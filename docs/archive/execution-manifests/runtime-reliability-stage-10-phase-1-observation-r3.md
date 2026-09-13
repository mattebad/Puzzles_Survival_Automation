# Stage 10 phase 1 direct zero-input observation repair manifest r3

## Task ID and objective
- Task ID: `stage-10-phase-1-observation-projection`
- Objective: repair the sole Terra finding so the parent-owned direct observation path accepts an exact zero input ceiling and proves safe terminal ownership release.

## Frozen stage control
- Host: `codex`
- Parent conversation ID: `current-task-continuation-20260825T170712Z`
- `control_plane_owner`: `sol_parent`
- Revision ID: `runtime-reliability-stage-10-phase-1-observation-r3`
- Stage type: `bounded_safety_boundary_repair_then_observation`
- Product precondition: `proven` — r2 offline status/pulse and focused replay passed; Terra returned one must-fix acceptance finding before live admission.
- Failure class: `local_defect`
- Stage start UTC: `2026-08-25T17:07:12.000Z`
- Continuation checkpoint UTC: `2026-08-25T17:07:12.000Z`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | frozen repair, integration acceptance, runtime admission, classification, termination |
| `procedure_coordinator` | `not used` | none |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | one repair turn limited to the exact writable production/test paths |
| `independent_tester` | `gpt-5.6-terra-high` | one read-only recheck of the classified finding and repair diff |
| `escalation_architect` | `not used` | none |

## Immutable budgets
- Third and final phase-1 revision in this execution chat.
- One bounded Luna repair, one Terra recheck, no second repair.
- One direct zero-input observation attempt after tests, recheck, and parent integration acceptance.
- Zero gameplay inputs, zero transports, zero registration changes.

## Frozen architecture decision
- Decision: retain the parent-owned ordinary observation route; permit `max_inputs == 0` only for `development_session_observe`, pass `allow_zero_inputs=True` to `DevelopmentSession`, set a truthful observed terminal, and verify singleton ownership release before returning success. Negative input ceilings remain rejected. No generic run-flow or action path gains zero-input authority.
- Preserved invariants: existing delegated receipt path is unchanged; only the observation command may use the new direct zero ceiling; checkpoint mutation remains prohibited; output/summary must report zero input, no lifecycle state, and released ownership; no target binding, handler, scheduler runtime authority, registration, or gameplay transport is introduced.

## Writable paths
- `scripts/pnsctl.py`
- `tests/test_development_session.py`
- Parent closure only: `CURRENT_HANDOFF.md`, `docs/runtime-reliability-convergence-status.md`, `docs/execution-manifests/runtime-reliability-stage-10-phase-1-observation-r3.md`

## Acceptance checks
- `development_session_observe(max_inputs=0)` enters one `DevelopmentSession` with `allow_zero_inputs=True`, observes once, writes native evidence, exits, proves ownership released, and returns `input_count=0`, `ownership_released=true`, `lifecycle_state_created=false`.
- A release failure or checkpoint mutation cannot return observed success.
- Negative ceilings reject before ownership acquisition.
- Existing delegated zero-input observation tests and ordinary positive-ceiling observation behavior remain passing.
- The r2 offline pulse/status and eight-test scheduler replay remain authoritative and unchanged.
- Terra recheck resolves the exact r2 finding with no new must-fix regression.

## Safety limits
- Allowed actions: offline tests and one parent-owned direct zero-input observation after all gates.
- Disallowed actions: any gameplay input, transport, registration, scheduler eligibility, target/session binding, flow handler, resource action, claim, combat, purchase, maintenance, Daily action, direct ADB, or delegated live operator.
- Runtime/session limits: one parent-owned singleton observation, exact input ceiling zero, automatic release required for success.

## Validation commands
- Exact new regression in `tests.test_development_session`.
- `python -m unittest tests.test_development_session tests.test_delegated_runtime_receipts`
- Reuse r2's passing 39-test affected suite, eight-test replay, disabled status, and duplicate offline pulse because no scheduler path changes.
- After Terra and parent acceptance: `python scripts/pnsctl.py development-session observe --max-inputs 0 --task-id stage-10-phase-1-observation-projection --flow-id WORLD-MAP-NAVIGATION-FOUNDATION --scenario scheduler-eligibility-observation --variant zero-input`

## Live budget
- Live admission: `blocked until repair tests, Terra recheck, and parent integration acceptance`
- Input budget: `0`
- Iteration budget: `1`

## Evidence/history references
- Terra r2 finding: direct ordinary observation currently rejects `max_inputs=0` at `scripts/pnsctl.py` ordinary-observation guard.
- r2 offline results: 23 disabled flows, no registered flow, scheduler ineligible, two candidate-null/zero-transport pulses, eight replay tests passing.

## Escalation conditions
- Repair affects any non-observation input path or delegated receipt contract.
- Tests or recheck show nonzero dispatch, unproven release, checkpoint mutation, or success on failure.
- Live observation reaches manual-only state, reports input/transport, or cannot prove release.
- No additional repair is authorized; any must-fix after recheck is `diminishing_returns` or user escalation.
