# Runtime Reliability Stage 6 continuous-session execution manifest r5

## Task ID and objective

- Task ID: `continuous-development-session-thin-conduct`
- Objective: Remove overbroad free-text external-blocker authority while preserving structured manual/external precedence and r4 World verification corrections.

## Frozen stage control

- Host: `codex`
- Parent conversation ID: `01a02175-5bc3-7033-b401-621bb9041a4c`
- `control_plane_owner`: `sol_parent`
- Revision ID: `continuous-development-session-thin-conduct-r5`
- Stage type: `step_back_redesign_under_explicit_same_chat_authorization`
- Product precondition: `not_applicable_offline_foundation`
- Failure class: `diminishing_returns`
- Stage start UTC: `2026-08-21T21:38:23.195Z`
- Continuation checkpoint UTC: `2026-08-21T21:38:23.195Z`
- User authorization: continue within this chat through completion.

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` / `architecture_planner` | `gpt-5.6-sol-medium` | Redesign freeze, scope, acceptance, classification, status, termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One mutable implementation turn within exact allowlist |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only diff-and-acceptance review |
| `procedure_coordinator` / `escalation_architect` | `not used` | No authority |

## Immutable budgets

- One implementation and one independent review.
- No repair/recheck loop in r5; any must-fix finding terminates for user escalation.
- Zero live attempts, runtime sessions, and runtime inputs.
- No full repository discovery.

## Frozen architecture decision

- Structured `status` and `terminal` external tokens are the classification authority.
- `blocker`, `reason`, and `next_action` may independently classify external state only when they contain an existing exact external token or a narrowly enumerated unambiguous phrase such as `account state`, `operator must`, or `requires operator`.
- Generic words such as `operator`, exception names such as `OperatorError`, and local repair/error instructions never create external authority by themselves.
- When structured status/terminal supplies the external match, preserve text only if it meets the narrow unambiguous rule; otherwise return the stable structured token.
- Preserve all r2 convergence behavior and all accepted r4 World topology/acceptance checks unchanged.

## Writable paths

Production:

- `tasks/flow_conductor.py`

Tests:

- `tests/test_flow_conductor.py`

Parent-owned closure:

- `docs/runtime-reliability-stage-6-continuous-session-execution-manifest-r5.md`
- `docs/runtime-reliability-convergence-status.md`
- `CURRENT_HANDOFF.md`
- local ignored umbrella-plan todo status only

All other paths are read-only.

## Acceptance checks

- `status: failed`, `next_action: repair the local operator error` follows normal local convergence, not `EXTERNAL_BLOCK`.
- `OperatorError: ...` text does not independently create external authority.
- Structured `manual_required` still returns `EXTERNAL_BLOCK` before DONE/reconciliation.
- Unambiguous phrases used by existing nested/same-layer tests retain their exact text.
- Stable-token fallback remains correct for unrelated text.
- Existing r2 convergence and all r4 World verification tests remain green.
- No unrelated or runtime-authority change.

## Safety limits

- Allowed: offline edits to the exact production/test paths and deterministic tests.
- Disallowed: runtime/emulator/ADB/gameplay input, live observation, evidence mutation, registration, scheduling, commit, push, downstream migration.
- Runtime/session limits: zero sessions and zero inputs.

## Validation commands

- Exact generic-operator and `OperatorError` regressions.
- `python -m unittest tests.test_flow_conductor`
- `python -m unittest tests.test_flow_conductor tests.test_world_map_navigation_bluestacks`
- `python -m unittest tests.test_flow_conductor tests.test_development_session tests.test_navigation_development_boundary tests.test_flow_delivery_lean_workflow`
- `python -m unittest tests.test_flow_delivery_daily_resource_item_bluestacks tests.test_world_map_navigation_bluestacks`
- checked-in Resource focused, World focused, shared-navigation, and architecture profiles after review acceptance.
- `git diff --check`

## Live budget

- Live admission: `not_authorized`
- Input budget: zero
- Iteration budget: zero

## Evidence/history references

- R4 manifest SHA-256: `11a8d2695003f11e6b9a7ed0409948011d6ecf411e270f8f606c8894f24614f4`.
- R4 recheck regression and parent reproduction are recorded in current handoff/status.

## Escalation conditions

- Narrow phrase matching cannot preserve required external semantics without generic substring authority.
- R2 convergence or r4 World acceptance behavior regresses.
- Any must-fix finding remains after the r5 review.
- Any runtime input or authority broadening is proposed.
