# Daily Resource Item observed-list redesign r6

## Task and authority
- Task ID: `daily-resource-item`
- Flow ID: `DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- Revision: `daily-resource-item-20260818-r6`
- Stage type: `SECOND_DISTINCT_REDESIGN`
- User continuation: explicitly authorized after native r5 evidence disproved
  the four-input mechanics.
- Direct objective authority remains:
  verified Home -> Bag `Resource & Speedup` -> exact `1K Food` single `Use`
  -> positive inventory/Food delta -> verified Home.
- Quest/Daily and Android Back remain prohibited.

## Roles
- `control_plane_owner`: `gpt-5.6-sol-medium`
- `bounded_implementer`: `gpt-5.6-luna-xhigh`
- `independent_tester`: `gpt-5.6-terra-high`

## Observed product facts
- Native 800x1280 Bag evidence:
  `.local-captures/development-sessions/observe-20260819T025359621634Z/observe.png`.
- Bag opens directly on selected `Resource & Speedup`; no second tab tap is
  required or authorized.
- `1K Food` is below the initial visible fold.
- The visible top-left Bag back arrow is measured from the current Resources
  frame. Its one-input receipt returned to settled verified Home:
  `.local-captures/development-sessions/DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION-20260819T025813732596Z`.
- Bag and Home transitions may require a settled-successor capture.

## Frozen route and budgets
1. Admit only current native verified Home with no unknown overlay.
2. Bind the measured Bag icon from the current Home frame and wait for a
   positively recognized `Resource & Speedup` successor.
3. Inspect the current list before scrolling.
4. If exact `1K Food` is absent, perform at most eight upward list swipes in a
   recognized, overlay-free central content lane disjoint from visible `Use`
   controls. Rebind every immediate-before frame.
5. Each swipe must produce a materially changed item-list/OCR signature.
   Repeated/stalled/unknown content stops before another input.
6. Bind one exact measured-card `1K Food` ordinary `Use` control. The separate
   `In bulk` control must remain disjoint and must never be selected. The
   single-item `Use` semantics authorize quantity one.
7. Dispatch exactly one `Use`; require positive owned-item decrement and/or
   Food-resource increase.
8. Bind the measured current-frame Bag back arrow and require settled verified
   Home.

- Maximum inputs: 11 = Bag + at most 8 swipes + Use + return Home.
- Item-use ceiling: exactly one.
- No Claim, Quest/Daily, AP/Stamina item, premium substitution, Android Back,
  unidentified target, arbitrary coordinate, stalled duplicate swipe, or
  identical retry.

## Writable paths
- `scripts/daily_resource_item_bluestacks.py`
- `scripts/flow_delivery_daily_resource_item_bluestacks.py`
- `scripts/pnsctl.py` only for this flow ceiling
- `tasks/flow_delivery_queue.json` only this flow row
- `tasks/gameplay_flow_contracts/DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION.json`
- `tasks/daily_quest_catalog.json` only this flow route/ceiling
- `tasks/daily_quest_execution_matrix.json` only this flow route/ceiling
- `tests/test_daily_resource_item_bluestacks.py`
- `tests/test_flow_delivery_daily_resource_item_bluestacks.py`
- `tests/test_gameplay_flow_contracts.py` only this contract
- `tests/test_flow_delivery_validation_profiles.py` only this profile
- `tasks/flow_delivery_validation_profiles.json` only this profile if needed

`CURRENT_HANDOFF.md`, this manifest, and the active plan remain parent-owned.
The plan changes only after accepted live success.

## Acceptance and validation
- No Quest/Daily symbol or action enters the production route.
- No redundant Resources-tab tap is dispatched.
- Every swipe is current-frame bound, content-lane constrained, progress
  checked, and capped at eight.
- Exact item/card, single `Use`, disjoint never-selected `In bulk`, forbidden
  item negatives, one-use ceiling, semantic delta, and verified Home remain
  fail closed.
- Route, adapter, pnsctl, queue, catalog/matrix, and contract agree on 11.
- Focused unit suite, checked-in focused profile, `py_compile`, and
  `git diff --check` pass before review.
- One Terra High review precedes live admission.
- After parent integration acceptance: zero-input Home observation, conductor
  dry run, then one bounded live conduct. Ordinary local recognizer defects may
  be repaired-and-continued only with materially changed behavior.

## Termination
- DONE only after one `Use`, positive semantic delta, verified Home, retained
  evidence, released singleton, plan completion, and queue/handoff closeout.
- Stop before `daily-milestone-claim`.
- Escalate rather than weakening safety if eight progressing swipes cannot
  expose exact `1K Food`, the current product state is unsupported, or a new
  architecture decision has no dominant safe option.
