# Supply Depot STEP_BACK r1

## Task ID and objective
- Task ID: `supply-depot`
- Objective: replace the disproven native zoom transport with the retained proven
  Scrcpy zoom-out seam, then preserve the bounded Supply Depot flow.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `not recorded`
- `control_plane_owner`: `sol_parent`
- Revision ID: `supply-depot-step-back-20260818-r1`
- Stage type: `repair`
- Product precondition: `proven`
- Failure class: `local_defect`
- Stage start UTC: `2026-08-18T17:07:00.110Z`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | stage freeze, acceptance, live, termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | assigned repair only |
| `independent_tester` | `gpt-5.6-terra-high` | read-only diff/acceptance review |

## Frozen architecture decision
- Use `ScrcpyMotionEventZoomTransport.zoom_out_once` through
  `LocalBlueStacksRuntime.dispatch_external_zoom`; do not alter the shared
  `LocalBlueStacksRuntime.zoom_out` implementation in this atomic repair.
- Preserve singleton ownership, current-frame source proof, one input accounting
  event, no Android Back, and no paid Supply Depot control.

## Writable paths
- `scripts/supply_depot_free_canary.py`
- `tests/test_flow_delivery_supply_depot_bluestacks.py`

## Acceptance checks
- The canary constructs the retained Scrcpy zoom transport from checked-in paths.
- Zoom dispatch remains inside `DevelopmentSession.run_action`.
- Focused Supply Depot tests pass.

## Safety limits
- No live input by the implementer or reviewer.
- No scheduler/registration changes.
- No other production paths may change.

## Validation commands
- `python -m unittest tests.test_flow_delivery_supply_depot_bluestacks tests.test_supply_depot tests.test_supply_depot_vision`
- `python -m py_compile scripts/supply_depot_free_canary.py`

## Live budget
- Live admission: parent-only after review
- Input budget: `10`
- Iteration budget: one materially changed conduct attempt

## Evidence/history references
- `.local-captures/development-sessions/SUPPLY-DEPOT-BLUESTACKS-INTEGRATION-20260818T170634903191Z/`
- Post-zoom frame proves the old transport enlarged the Home scene.
