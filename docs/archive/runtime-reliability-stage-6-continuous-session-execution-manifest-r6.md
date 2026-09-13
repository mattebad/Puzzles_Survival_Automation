# Runtime Reliability Stage 6 continuous-session execution manifest r6

## Task ID and objective

- Task ID: `continuous-development-session-thin-conduct`
- Objective: Make structured external-blocker classification exact-token-only and close the remaining r5 authority leak.

## Frozen stage control

- Host: `codex`
- Parent conversation ID: `01a02175-5bc3-7033-b401-621bb9041a4c`
- `control_plane_owner`: `sol_parent`
- Revision ID: `continuous-development-session-thin-conduct-r6`
- Stage type: `exact_structured_token_architecture_correction`
- Product precondition: `not_applicable_offline_foundation`
- Failure class: `core_contract`
- Stage start UTC: `2026-08-21T22:00:40.988Z`
- Continuation checkpoint UTC: `2026-08-21T22:00:40.988Z`
- User authorization: explicit continuation after the r5 checkpoint.

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` / `architecture_planner` | `gpt-5.6-sol-medium` | Freeze, exact-token architecture, acceptance, status, termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One mutable implementation turn within exact allowlist |
| `independent_tester` | `gpt-5.6-terra-high` | One final read-only diff-and-acceptance review |
| `procedure_coordinator` / `escalation_architect` | `not used` | No authority |

## Immutable budgets

- One implementation and one independent review.
- No repair/recheck loop. Any must-fix finding terminates for user escalation.
- Zero live attempts, sessions, and runtime inputs.
- No full repository discovery.

## Frozen architecture decision

- Normalize each structured `status` and `terminal` value with strip/casefold and compare only by equality against `_EXTERNAL_BLOCKERS`.
- Never search structured values for embedded external-token substrings.
- Composed, namespaced, diagnostic, parser, or error statuses remain ordinary statuses unless their complete normalized value is an enumerated external token.
- Keep r5 free-text exact-token/boundary-safe narrow-phrase behavior unchanged.
- Preserve all r2 convergence, nested/same-layer precedence, stable-token fallback, r4 World verification, and runtime safety invariants.

## Writable paths

- `tasks/flow_conductor.py`
- `tests/test_flow_conductor.py`
- `docs/runtime-reliability-stage-6-continuous-session-execution-manifest-r6.md` (parent only)
- `docs/runtime-reliability-convergence-status.md` (parent closure only)
- `CURRENT_HANDOFF.md` (parent closure only)
- local ignored umbrella-plan todo status only (parent closure only)

All other paths are read-only.

## Acceptance checks

- `failed_manual_required_parse` and equivalent non-exact `status`/`terminal` values never return `EXTERNAL_BLOCK` solely from the embedded token.
- Exact `manual_required`, `manual_only_state`, and other enumerated structured values remain external.
- Same-layer and nested precedence remains correct.
- R5 local operator/`OperatorError` regressions remain normal convergence.
- R2 reconciliation convergence and r4 World tests remain green.
- No authority, registration, scheduling, or runtime-input change.

## Safety limits

- Allowed: offline edits and deterministic tests in the exact scope.
- Disallowed: runtime/emulator/ADB/gameplay input; live observation; evidence mutation; registration; scheduling; commit; push; downstream migration.
- Runtime/session limits: zero sessions and zero inputs.

## Validation commands

- Exact non-exact structured status/terminal regressions.
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

- R5 manifest SHA-256: `3e77b177c1a8ec1f1611a2eda3355263b48c66cdf3f34b20cf5d16df7c51d49e`.
- R5 independent finding and parent reproduction are recorded in current handoff/status.

## Escalation conditions

- Exact structured equality cannot preserve real external states.
- Any prior convergence, free-text, or World acceptance behavior regresses.
- Any must-fix finding remains after the r6 review.
- Any runtime authority broadening or live input is proposed.
