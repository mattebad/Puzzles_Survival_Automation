# Runtime Reliability Stage 6 continuous-session execution manifest r3

## Task ID and objective

- Task ID: `continuous-development-session-thin-conduct`
- Objective: Close the two externally confirmed r2 acceptance gaps for one-input World diagnostics and nested external-blocker precedence without changing the continuous-session architecture.

## Frozen stage control

- Host: `codex`
- Parent conversation ID: `01a02175-5bc3-7033-b401-621bb9041a4c`
- `control_plane_owner`: `sol_parent`
- Revision ID: `continuous-development-session-thin-conduct-r3`
- Stage type: `final_core_contract_correction`
- Product precondition: `not_applicable_offline_foundation`
- Failure class: `core_contract`
- Stage start UTC: `2026-08-21T19:16:54.686Z`
- Continuation checkpoint UTC: `2026-08-21T19:16:54.686Z`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` / `architecture_planner` | `gpt-5.6-sol-medium` | Final stage freeze, architecture, scope, acceptance, classification, status, and termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One mutable r3 implementation turn within the exact allowlist |
| `independent_tester` | `gpt-5.6-terra-high` | One final read-only diff-and-acceptance review |
| `procedure_coordinator` / `escalation_architect` | `not used` | No authority |

## Immutable budgets

- This is the third and final Stage 6 revision in this conversation.
- One r3 implementation and one r3 review, reaching the eight-managed-turn conversation ceiling.
- No r3 repair or recheck is authorized. Any must-fix finding terminates Stage 6 for user escalation; do not patch again.
- Zero live attempts, zero runtime sessions, and zero runtime inputs.
- No full repository discovery.

## Frozen architecture decision

Finding 1 — World search-entry diagnostic:

- Preserve `SEARCH_ENTRY_ONLY_PATH` as a useful one-input semantic diagnostic ending at `WORLD_SEARCH_OPEN`.
- Mark its retained delivery result and causal trace with non-accepting diagnostic topology, never `continuous` acceptance topology.
- The checked-in World verifier may validate diagnostic evidence integrity and semantics but must return a distinct non-accepting result such as `diagnostic_verified`, with `acceptance_eligible: false`; it must never return production-style `verified` for this path.
- Any conductor/verification consumer that requires status `verified` must therefore refuse `DONE` for search-entry evidence. Full World navigation and supported terminal recovery semantics remain unchanged.

Finding 2 — nested external blockers:

- Inspect every layer yielded by `_summary_layers()` for external-blocker statuses and blocker/reason/next-action text.
- External/manual-only state has precedence before verified `DONE` and before reconciliation-required convergence, regardless of outer/nested ordering.
- Return the exact matching nested blocker text when present, otherwise the stable external token.
- Preserve r2 reconciliation behavior when no external blocker exists: `DONE` veto plus bounded `CONTINUE` → `STEP_BACK` → `ESCALATE` convergence.

Preserved invariants: all r1/r2 DevelopmentSession, typed observation, ownership, trace, input-accounting, Resource authority, World current-frame/popup/Home safety, route controllers, thin conduct, registration `NOT_REGISTERED`, scheduler disabled, and zero runtime authority.

## Writable paths

Production:

- `scripts/flow_delivery_world_map_bluestacks.py`
- `tasks/flow_conductor.py`

Tests:

- `tests/test_world_map_navigation_bluestacks.py`
- `tests/test_flow_conductor.py`

Parent-owned control and closure:

- `docs/runtime-reliability-stage-6-continuous-session-execution-manifest-r3.md`
- `docs/runtime-reliability-convergence-status.md`
- `CURRENT_HANDOFF.md`
- local ignored umbrella plan todo status only

All other production, tests, adapters, session modules, evidence, manifests, migration packets, queues, registration, scheduler, and plan content are read-only.

## Acceptance checks

- Live/dry-run search-entry result topology is diagnostic/non-accepting rather than continuous acceptance proof.
- Search-entry causal trace is read-only and explicitly diagnostic/non-accepting.
- World verifier returns `diagnostic_verified` (or an equally explicit non-accepting status) plus `acceptance_eligible: false` for `SEARCH_ENTRY_ONLY_PATH` after full integrity/semantic verification.
- Full World navigation retains `verified`, continuous topology, terminal Home, and zero effect classes.
- A conductor verification consumer cannot turn diagnostic World evidence into `DONE`.
- An outer completed/reconciliation summary with nested `manual_required` returns `EXTERNAL_BLOCK` and the nested reason/token.
- The inverse nesting order and deeply nested route/result layers behave identically.
- External blockers are evaluated before verified `DONE` and reconciliation convergence.
- R2 first/repeated/post-step-back reconciliation tests remain green.
- Existing World full route, recovery, popup, target-binding, evidence-order, and zero-effect tests remain green.
- No production path outside the two exact files changes.

## Safety limits

- Allowed: offline edits to four exact code/test paths; deterministic unit and checked-in validation profiles.
- Disallowed: runtime/emulator/ADB/gameplay input; live observation/shadow; Resource use; popup input; adapter/session/effect-authority changes outside scope; registration; scheduling; commit; push; evidence mutation.
- Runtime/session limits: zero runtime sessions and zero inputs.

## Validation commands

- exact new diagnostic-ineligibility tests in `tests.test_world_map_navigation_bluestacks`
- exact new reversed/deep nested external-blocker tests in `tests.test_flow_conductor`
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

- R1 manifest SHA-256: `ac3fc7bb21008aabaa77857b23ad94b026c115f7ffd5644afac3e1b9ef03202d`.
- R2 manifest SHA-256: `8287ac1c5f2d4cc55e6fb7c7f796428b833a7210514b7cde8d71db500b7d4a1a`.
- Independent external review findings are reproduced and recorded in `CURRENT_HANDOFF.md` and `docs/runtime-reliability-convergence-status.md`.

## Escalation conditions

- Diagnostic non-acceptance cannot be enforced without weakening full World semantic verification.
- External-block precedence cannot be made all-layer without changing unrelated conductor decisions.
- A new must-fix safety or acceptance defect appears in the r3 review.
- Any runtime evidence or input is proposed or used.
