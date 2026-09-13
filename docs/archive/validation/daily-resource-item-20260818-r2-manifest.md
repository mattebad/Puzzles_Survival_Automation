# Daily Resource Item STEP_BACK r2

## Task ID and objective
- Task ID: `daily-resource-item`
- Flow ID: `DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- Objective: replace r1's proximity-based item control binding with measured
  current-frame card ownership and make the complete source-to-Home route
  executable within its declared input ceiling.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `not recorded`
- `control_plane_owner`: `sol_parent`
- Revision ID: `daily-resource-item-20260818-r2`
- Stage type: `STEP_BACK_REDESIGN`
- Product precondition: `not_applicable` for offline redesign; current
  selected-Daily identity remains a fail-closed live precondition.
- Failure class: `diminishing_returns`
- Stage start UTC: `2026-08-19T00:36:08.178Z`
- Continuation checkpoint UTC: `2026-08-19T00:36:08.178Z`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | redesign freeze, integration acceptance, live admission, failure classification, termination |
| `procedure_coordinator` | `not used` | none |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | one bounded redesign implementation |
| `independent_tester` | `gpt-5.6-terra-high` | one read-only diff and acceptance review |
| `escalation_architect` | `not used` | none |

## Immutable budgets
- This is stage revision 2 of at most 3 and the task's single permitted
  STEP_BACK redesign.
- One Luna implementation, one Terra review, at most one consolidated repair
  and one recheck, one parent integration checkpoint, and one live attempt.
- Live input ceiling: 12 total route inputs; exactly one item-consumption
  dispatch. The extra ceiling is route capacity, not permission to retry.

## Frozen architecture decision
- Preserve r1's canonical flow ID, queue/registry/contract wiring, source Daily
  admission, stable reset binding, separate completed successor, scheduler
  disabled state, no-Claim boundary, and no unproven Android Back.
- Replace all distance-only `Use` association with a measured current-frame
  Resources item card/row. Use the existing visual horizontal
  separator/current-pixel panel measurement convention from
  `scripts/daily_row_claim_bluestacks.py::_measure_daily_row_panel`, or an
  equivalent deterministic local implementation.
- Authorization requires: recognized Resources context; exactly one `1K Food`
  semantic anchor; one visually proven card containing the complete item
  anchor, owned count, exact quantity one, and exactly one `Use`; and the
  selected `Use` ROI fully inside that same card. Adjacent-row controls are
  excluded by the measured card bounds. A visible `In bulk` control may exist
  only when it is fully inside the same card, spatially disjoint from `Use`,
  and never selected.
- Synthetic OCR proximity without visual card proof must fail closed.
- Set the route, adapter, `pnsctl` default, queue acceptance, gameplay contract,
  and tests to one consistent maximum of 12. The expected VIP-over-Home route
  needs 11 inputs; all 12 remain individually source/successor bound.

## Writable paths
- `scripts/daily_resource_item_bluestacks.py`
- `scripts/flow_delivery_daily_resource_item_bluestacks.py`
- `scripts/pnsctl.py` — only the Daily Resource Item conduct input ceiling.
- `tasks/flow_delivery_queue.json` — only the Daily Resource Item input ceiling
  and acceptance text.
- `tasks/gameplay_flow_contracts/DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION.json`
  — only the route ceiling/evidence wording.
- `tests/test_daily_resource_item_bluestacks.py`
- `tests/test_flow_delivery_daily_resource_item_bluestacks.py`

All other paths are read-only. Do not alter r1 history, the active plan,
BACKLOG, CURRENT_HANDOFF, scheduler code, unrelated flows, retained evidence,
or local runtime state.

## Acceptance checks
- A neighboring row/card `Use` can never satisfy the `1K Food` authorization.
- Blank/synthetic pixels with plausible OCR fail because no visual item card is
  proven.
- A visually proven single card with exact `1K Food`, owned count, quantity
  one, exact `Use`, and disjoint visible `In bulk` is authorized.
- Card ambiguity, clipped card, control outside/straddling card, overlapping
  bulk, premium/AP/Stamina/unidentified evidence, or multiple Use controls fail
  closed.
- All flow/adapter/registry/contract/queue ceilings agree on 12.
- The full optional-VIP route can reach final verified Home without exceeding
  12, while executed `daily-resource-item:use-1k-food` count remains exactly
  one.
- The r1 focused tests plus new card-ownership and full-route budget
  regressions pass.

## Safety limits
- Allowed: exact known-benign VIP Close; bounded source/successor-proven
  navigation; one measured-card-bound `1K Food` Use; visible in-game return.
- Forbidden: proximity-only Use; adjacent-row Use; `In bulk`; any second Use;
  AP/Stamina items; premium/paid/diamond/real-money substitutions; unknown
  items; Claim; unproven Android Back; identical retry; direct ADB or Bliss.
- Runtime: one pnsctl singleton session, package `com.global.ztmslg`, native
  800x1280, at most 12 total inputs, exactly one consumption dispatch.

## Validation commands
- `python -m unittest tests.test_daily_resource_item_bluestacks tests.test_flow_delivery_daily_resource_item_bluestacks tests.test_gameplay_flow_contracts tests.test_flow_delivery_validation_profiles`
- `python scripts/run_flow_delivery_validation.py focused --flow-id DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- `python -m py_compile scripts/daily_resource_item_bluestacks.py scripts/flow_delivery_daily_resource_item_bluestacks.py scripts/pnsctl.py`
- Parent dry-run after integration:
  `python scripts/pnsctl.py conduct DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`

## Live budget
- Parent-only after implementation self-check, Terra review, and explicit
  integration acceptance.
- One supervised conduct attempt; 12 total inputs; exactly one Use; no
  identical retry.

## Evidence/history references
- `docs/validation/daily-resource-item-20260818-r1-manifest.md`
- r1 Terra recheck: completed-Daily and reset fixes resolved; proximity binding
  unresolved; optional-VIP route requires 11 inputs against old ceiling 10.
- Current zero-input observation:
  `.local-captures/development-sessions/observe-20260819T001810812238Z`.

## Escalation conditions
- This redesign cannot establish a current-frame card ownership proof.
- The full route cannot fit within 12 without weakening action-specific checks.
- Review finds a concrete safety or acceptance defect that disproves the
  redesigned architecture.
- A live attempt disproves the design. Because the single STEP_BACK is spent, a
  second distinct failed redesign is a genuine user escalation.
