# Nova Praise lean reproof — frozen revision r4

## Task ID and objective
- Task / flow: `nova-praise` / `NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE`
- Objective: accept zoom-independent Home proof and require the recovery-aware
  viewport planner before any Research Lab building dispatch.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `ea68e8f4-5604-40a8-b4f1-a3efad312113`
- `control_plane_owner`: `sol_parent`
- Revision ID: `nova-praise-lean-reproof-r4`
- Stage type: `step_back_cross_contract_redesign`
- Product precondition: `proven`
- Failure class: `core_contract`
- Stage start UTC: `2026-08-18T04:22:00.000Z`
- Continuation checkpoint UTC: `2026-08-18T04:22:00.000Z`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | stage freeze, integration acceptance, live, termination |
| `procedure_coordinator` | not used | not applicable |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | assigned paths and checks only |
| `independent_tester` | `gpt-5.6-terra-high` | read-only diff and acceptance review |
| `escalation_architect` | not used | not applicable |

## Immutable budgets
- One bounded implementation, one independent review, at most one consolidated
  repair and one recheck.
- User-authorized continuation ceiling: three further live attempts.
- One runtime operator; all attempts remain convergence-governed and terminate
  on a repeated signature, disproven design, manual-only state, or safety block.

## Frozen architecture decision
- `recognize_home_nav()` is the zoom-independent Home identity gate for the
  native BlueStacks profile. It may establish Home context but never authorizes
  a target or transport by itself.
- Atlas localization remains responsible for camera/zoom state, target
  projection, and current-frame semantic building binding.
- `BlueStacksLocalizeFirstHomeDriver.observe()` must consult its
  recovery-aware `DirectPanNavigator` before returning `COMPLETE`; a
  semantically bound building cannot bypass radial-footprint, HUD-clearance,
  recovery-zone, or viewport-placement checks.
- On the retained failing frame, Home correlation `0.9673` admits bounded
  canonical recovery while the planner's `PAN` result prevents the disproven
  Research Lab tap at `[595,371]`.
- All r3 immediate-before Nova and paid-surface checks remain unchanged.

## Writable paths
- `scripts/nova_praise_bluestacks.py`
- `scripts/home_atlas_bluestacks.py`
- `tests/test_nova_navigation_canary.py`
- `tests/test_home_atlas_verified_route.py`
- `docs/validation/nova-praise-lean-reproof-20260817-r4-manifest.md`
- `docs/validation/nova-praise-lean-reproof-20260817-ledger.md`
- `CURRENT_HANDOFF.md`

## Acceptance checks
- A native frame with Home nav correlation at or above `0.90` establishes Home
  context even when atlas localization is zoomed or not yet canonical.
- Non-Home native frames and invalid geometry do not gain Home authority.
- The retained failing Home frame produces `RECOVER_ZOOM` before canonical
  recovery and `PAN` after recovery; it cannot produce `COMPLETE` at the
  disproven viewport.
- A planner-approved current frame with a same-digest semantic Research Lab
  binding still produces `COMPLETE`.
- Existing Nova navigation, Home-atlas route, centralized boundary, and
  `pnsctl` focused tests pass.
- Independent tester reports no concrete acceptance or safety defect.

## Safety limits
- Allowed actions: bounded Home zoom recovery, planner-directed Home pan,
  Research Lab/Nova navigation, one free Praise pulse, and documented safe
  return.
- Disallowed actions: identical retries, atlas-only target dispatch, unplanned
  Research Lab taps, paid/confirmation inputs, real-money actions, manual-only
  state automation, and any non-`pnsctl` runtime input.
- Runtime/session limits: singleton ownership, current-frame revalidation,
  native 800x1280 frames, fail closed on unknown, and the user's remaining
  three-attempt ceiling.

## Validation commands
- `python -m unittest tests.test_home_atlas_verified_route tests.test_nova_navigation_canary`
- `python -m unittest tests.test_nova_praise_centralized_boundary tests.test_pnsctl_nova_praise`
- checked-in focused profile and shared-navigation profile before live admission
- parent integration gate over manifest, diff, receipts, and tester findings

## Live budget
- Live admission: `not authorized until integration acceptance`
- Input budget: bounded by the supervised flow and checked-in runtime policy
- Iteration budget: three further attempts authorized by the user

## Evidence/history references
- `docs/validation/nova-praise-lean-reproof-20260817-ledger.md`
- retained failing frame:
  `.local-captures/flow-delivery/NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE/nova-praise-one-free-pulse-20260818T041746757474Z/frames/0005-canary-home-02-immediate-before.png`
- zero-input continuation observation:
  `.local-captures/development-sessions/observe-20260818T042322760242Z`

## Escalation conditions
- Approved plan is contradictory or incomplete.
- Safety authority is ambiguous.
- Tester and implementation evidence conflict.
- Live evidence disproves the planner-gated design.
- A repeated defect signature or no furthest-progress advance is
  `diminishing_returns` and ends further identical attempts.
