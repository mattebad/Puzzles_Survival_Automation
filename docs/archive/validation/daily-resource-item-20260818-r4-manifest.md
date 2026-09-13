# Daily Resource Item explicit final r4

## Task ID and objective
- Task ID: `daily-resource-item`
- Flow ID: `DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- Objective: correct only `_food_line` so exact `1K Food` accepts the supported
  metadata grammar while arbitrary item-name or trailing text fails closed.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `not recorded`
- `control_plane_owner`: `sol_parent`
- Revision ID: `daily-resource-item-20260818-r4`
- Stage type: `user_authorized_final_consolidated_repair`
- Product precondition: `not_applicable` for offline repair.
- Failure class: `diminishing_returns`
- Stage start UTC: `2026-08-19T01:48:11.847Z`
- Continuation checkpoint UTC: `2026-08-19T01:47:00.000Z`
- User continuation: explicitly authorized after the r3 compact handoff.

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | freeze, integration acceptance, live admission, termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | `_food_line` and focused regressions only |
| `independent_tester` | `gpt-5.6-terra-high` | one read-only trailing-text recheck |

## Immutable budgets
- One Luna repair and one Terra recheck. No further repair/review cycle.
- Preserve one parent live attempt, 12 total inputs, and exactly one Use.

## Frozen architecture decision
- Preserve every r1-r3 route, measured-card, reset, Daily successor, queue,
  registry, contract, evidence, ceiling, and scheduler decision unchanged.
- `_food_line` accepts item name exactly `1K Food` followed only by the complete
  supported metadata/control grammar. Supported quantity forms are
  `quantity 1`, `qty 1`, or `x 1`; supported owned-count and controls remain
  separately parsed.
- The parser validates the entire remaining token sequence. It must reject
  arbitrary prefixes, reordered names, suffixes, bundles, malformed or
  conflicting metadata, and any trailing text, including
  `1K Food x 1 Use Bundle`.

## Writable paths
- `scripts/daily_resource_item_bluestacks.py` — `_food_line` and the smallest
  directly required local metadata-grammar helper only.
- `tests/test_daily_resource_item_bluestacks.py` — accepted/rejected parser
  regressions only.

All other paths and symbols are read-only.

## Acceptance checks
- Accept exact supported forms including `1K Food x 1 Use`.
- Reject `1K Food x 1 Use Bundle`, prefixes, suffixes, bundles, reordered names,
  malformed quantity, non-one quantity for authorization, duplicate/conflicting
  metadata, and arbitrary trailing text.
- No navigation, route, contract, queue, evidence, ceiling, or scheduler diff.
- Focused tests, validation profile, compilation, and diff check pass.

## Validation commands
- `python -m unittest tests.test_daily_resource_item_bluestacks tests.test_flow_delivery_daily_resource_item_bluestacks tests.test_gameplay_flow_contracts tests.test_flow_delivery_validation_profiles`
- `python scripts/run_flow_delivery_validation.py focused --flow-id DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- `python -m py_compile scripts/daily_resource_item_bluestacks.py scripts/flow_delivery_daily_resource_item_bluestacks.py scripts/pnsctl.py`
- `git diff --check`

## Live budget
- Parent-only after Terra acceptance and parent integration.
- One conduct attempt, 12 total inputs, exact one `1K Food`, quantity one,
  exactly one Use, required resource/Daily/Home successors, no identical retry.

## Termination
- If Terra or parent integration finds any new concrete blocker, report it once
  and stop. No additional mutable or review turn is authorized.
