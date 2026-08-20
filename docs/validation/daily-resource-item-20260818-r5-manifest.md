# Daily Resource Item architecture correction r5

## Task ID and objective
- Task ID: `daily-resource-item`
- Flow ID: `DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- Objective: replace the disproved Quest/Daily attribution route with the
  authoritative direct gameplay route:
  verified Home -> Bag -> Resources -> exact `1K Food` quantity one -> one
  `Use` -> positive item/resource successor -> verified Home.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `not recorded`
- `control_plane_owner`: `sol_parent`
- Revision ID: `daily-resource-item-20260818-r5`
- Stage type: `STEP_BACK_ARCHITECTURE_CORRECTION`
- Product precondition: `proven` by current zero-input native verified Home.
- Failure class: `diminishing_returns`
- Stage start UTC: `2026-08-19T02:31:46.118Z`
- Continuation checkpoint UTC: `2026-08-19T02:31:00.000Z`
- User continuation: explicitly authorized for this one architecture correction.

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | architecture freeze, integration acceptance, live admission, termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | one bounded correction turn |
| `independent_tester` | `gpt-5.6-terra-high` | one read-only corrected-plan review |

## Immutable budgets
- One Luna implementation and one Terra review. No open-ended repair/review
  cycle.
- One materially changed live proof after integration.
- Direct route ceiling: 4 inputs total: Bag, Resources, Use, return Home.
- Exactly one item-consumption dispatch.

## Frozen authority reconciliation
- The corrected active plan is authoritative and supersedes r1-r4 selected-
  Daily admission, Daily-progress, and Quest-first architecture.
- Semantic verification of the exact known gameplay transaction proves this
  Daily objective; Quest/Daily is not an action surface for this flow.
- Remove `current_selected_daily_catalog_admission`, `quest_screen`,
  `selected_daily_resource_item_admitted`, Daily reset/progress requirements,
  and every pre/post-Use Quest/Daily transition from this flow.
- Preserve the canonical flow ID, fixed conductor registration, exact-item
  parser, measured-card ownership, quantity-one and one-Use safety, no-Bulk
  boundary, scheduler-disabled state, and retained evidence history.

## Frozen architecture decision
- Source admission is current native 800x1280 verified Home with no unknown
  overlay. Do not normalize or visit Quest/Daily.
- Bind Bag from the verified Home navigation strip and positively recognize the
  Bag successor.
- Bind Resources from the current Bag frame and positively recognize the
  Resources successor.
- Bind the exact measured-card `1K Food` single `Use` control from the immediate
  current Resources frame. Dispatch once.
- Require immediate positive semantic transaction evidence: owned item count
  decreases and/or displayed Food resource increases. Transport alone is not
  success.
- Return to verified Home using only a positively recognized current-frame
  visible in-game control. Android Back is prohibited. Unknown return control
  fails closed without another input.
- Completion requires exactly one Use, positive semantic item/resource delta,
  and verified Home. It does not require a Daily row, reset identity, catalog
  admission, or Daily progress.

## Writable paths
- `scripts/daily_resource_item_bluestacks.py`
- `scripts/flow_delivery_daily_resource_item_bluestacks.py`
- `scripts/pnsctl.py` — only the corrected flow input ceiling.
- `tasks/flow_delivery_queue.json` — only Resource Item dependencies, route,
  acceptance, and ceiling language.
- `tasks/gameplay_flow_contracts/DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION.json`
- `tasks/daily_quest_catalog.json` — only remove selected-Daily/catalog-
  admission coupling while preserving identity/ownership and scheduler false.
- `tasks/daily_quest_execution_matrix.json` — only the Resource Item route and
  semantic acceptance correction.
- `tests/test_daily_resource_item_bluestacks.py`
- `tests/test_flow_delivery_daily_resource_item_bluestacks.py`
- `tests/test_gameplay_flow_contracts.py` — only corrected contract assertions.
- `tests/test_flow_delivery_validation_profiles.py` — only if existing flow
  profile assertions require corrected test counts/identity.

All other paths and flows are read-only. `CURRENT_HANDOFF.md` and the active
plan remain parent-owned; the plan changes only after accepted live success.

## Acceptance checks
- Production route contains no Quest/Daily navigation, recognizer, state,
  target, reset, admission, or progress gate.
- Queue and portfolio staging have no
  `current_selected_daily_catalog_admission` dependency.
- Gameplay contract starts at verified Home and contains only direct Bag,
  Resources, one Use, semantic item/resource successor, and verified Home.
- Catalog/matrix contain no claim that selected-Daily admission or Daily
  progress is required for this flow.
- All route/adapter/pnsctl/queue/contract ceilings agree on 4.
- Exact item, measured card, quantity one, one Use, disjoint never-selected
  `In bulk`, AP/Stamina/premium/unidentified negatives remain enforced.
- Completion requires resource/item delta plus verified Home; all Daily-
  progress result fields and validator requirements are removed.
- Focused tests prove the corrected direct route and prohibit Quest/Daily.

## Safety limits
- Allowed actions: verified Home -> Bag; Bag -> Resources; exact one
  `1K Food` Use; recognized visible return to Home.
- Disallowed: Quest/Daily; Claim; Android Back; `In bulk`; second Use;
  AP/Stamina items; premium/paid/diamond/real-money substitutions; unidentified
  items; arbitrary coordinates; identical retry.
- Runtime: local BlueStacks package `com.global.ztmslg`, native 800x1280, one
  pnsctl singleton session, 4 total inputs, 1 Use.

## Validation commands
- `python -m unittest tests.test_daily_resource_item_bluestacks tests.test_flow_delivery_daily_resource_item_bluestacks tests.test_gameplay_flow_contracts tests.test_flow_delivery_validation_profiles`
- `python scripts/run_flow_delivery_validation.py focused --flow-id DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- `python -m py_compile scripts/daily_resource_item_bluestacks.py scripts/flow_delivery_daily_resource_item_bluestacks.py scripts/pnsctl.py`
- `git diff --check`
- Parent dry-run:
  `python scripts/pnsctl.py conduct DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`

## Live budget
- Parent-only after Terra and integration acceptance.
- One materially changed direct-route conduct, maximum 4 inputs, exactly one
  Use, no identical retry.

## Evidence/history references
- Corrected plan:
  `.cursor/plans/daily_scheduler_promotion_1572d57c.plan.md`
- Current verified Home:
  `.local-captures/development-sessions/observe-20260819T023134278480Z`
  (`e565ac02c1cd18b2a49b93d6fe1b8fc902d73ee764134a7876d09a4ad779b909`).
- Disproved Quest-first attempt:
  `.local-captures/development-sessions/DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION-20260819T015603267315Z`.

## Termination
- If one new concrete blocker remains after this correction, report it once and
  stop. No additional repair/review cycle.
