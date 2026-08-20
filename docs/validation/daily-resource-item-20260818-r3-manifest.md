# Daily Resource Item final r3

## Task ID and objective
- Task ID: `daily-resource-item`
- Flow ID: `DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- Objective: preserve exact `1K Food` identity while recognizing the supported
  `x <integer>` quantity field as metadata rather than item-name text.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `not recorded`
- `control_plane_owner`: `sol_parent`
- Revision ID: `daily-resource-item-20260818-r3`
- Stage type: `final_bounded_repair`
- Product precondition: `not_applicable` for offline repair.
- Failure class: `diminishing_returns`
- Stage start UTC: `2026-08-19T00:47:00.000Z`
- Continuation checkpoint UTC: `2026-08-19T00:47:00.000Z`
- User continuation: explicitly authorized in this conversation after r2
  recheck exhaustion.

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | freeze, integration acceptance, live admission, termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | exact parser repair only |
| `independent_tester` | `gpt-5.6-terra-high` | read-only diff/acceptance review |

## Immutable budgets
- This is the third and final stage revision.
- One Luna implementation and one Terra review. No further repair/recheck stage
  is authorized.
- Preserve r2's one live attempt, 12 total inputs, and exactly one Use.

## Frozen architecture decision
- Preserve all accepted r2 measured-card, exact-name, reset, Daily successor,
  route, input-ceiling, and scheduler-disabled behavior.
- Parse the semantic item-name field as exactly `1K Food`.
- Treat `x <positive integer>` as a quantity metadata boundary only when the
  marker and integer form one validated quantity token pair after the exact item
  name. It must not permit arbitrary suffix/prefix item-name words.
- The existing authorization still requires quantity exactly one, owned count,
  measured-card containment, exact Use containment, and all safety negatives.

## Writable paths
- `scripts/daily_resource_item_bluestacks.py`
- `tests/test_daily_resource_item_bluestacks.py`

All other files are read-only.

## Acceptance checks
- Exact measured-card line `1K Food x 1 Use` is parsed as item name `1K Food`
  plus quantity one and remains authorizable when all other evidence passes.
- `1K Food x 2`, malformed `x`, prefix/suffix/bundle names, ambiguous metadata,
  and controls outside the card remain rejected.
- No route, ceiling, registry, queue, contract, or scheduler behavior changes.
- Focused tests and compilation pass.

## Validation commands
- `python -m unittest tests.test_daily_resource_item_bluestacks tests.test_flow_delivery_daily_resource_item_bluestacks tests.test_gameplay_flow_contracts tests.test_flow_delivery_validation_profiles`
- `python scripts/run_flow_delivery_validation.py focused --flow-id DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- `python -m py_compile scripts/daily_resource_item_bluestacks.py scripts/flow_delivery_daily_resource_item_bluestacks.py scripts/pnsctl.py`
- `git diff --check`

## Live budget
- Parent-only after Terra acceptance and parent integration.
- One attempt, 12 total inputs, exactly one Use, no identical retry.

## Escalation conditions
- Any further must-fix review finding, failed integration gate, or design-
  disproving evidence terminates managed repair and is reported to the user.
