# Stage 10 phase 2 bounded navigation promotion manifest r1

## Control
- Task ID: `stage-10-phase-2-navigation`
- Revision: `runtime-reliability-stage-10-phase-2-navigation-r1`
- Host: `codex`
- Parent: `gpt-5.6-sol-medium`, sole control-plane owner
- Implementer: `gpt-5.6-luna-xhigh`, one bounded implementation
- Tester: `gpt-5.6-terra-high`, one read-only acceptance review and at most one finding-only recheck
- Failure class entering r1: `core_contract`
- Phase 1 prerequisite: accepted and published at `1b0c975313d7f79e6708dda3ab5af00b4ccd91ae`

## Candidate and product precondition
- Exact flow: `WORLD-MAP-NAVIGATION-FOUNDATION`.
- Accepted capability: Stage 6 continuous-session World adapter and verifier; typed product record `world_map_navigation-v1`; BlueStacks profile `pns-bluestacks-5-p64-800x1280-v1`; zero-cost navigation only.
- Missing proof intentionally owned by this phase: one current uninterrupted native `HOME_READY -> World -> Search -> World -> HOME_READY` canary with semantic successors and canonical safe terminal.
- Existing product/route prohibitions remain: no node selection, Gathering, march, formation, occupancy override, AP, stamina, resource, currency, Daily action, claim, combat, purchase, or maintenance action.

## Architecture
Add the smallest bounded scheduler-to-parent handoff needed for promotion:
1. The checked-in production registry remains the sole registration authority and defaults every flow disabled.
2. It may represent at most one phase-canary registration. A registered entry requires an exact checked-in handler ID and BlueStacks profile; all other entries remain null-handler, `disabled`, `NOT_REGISTERED`, and scheduler-ineligible.
3. The scheduler pulse may select the one registered flow and persist its occurrence, but the selection handler is zero-transport and returns a terminal parent-canary-required result. It cannot bind a target, create a runtime session, acquire ownership, invoke a route, or authorize input.
4. The parent separately runs the existing `scripts/pnsctl.py development-session run-flow` World path after tests, independent review, parent integration acceptance, and a fresh zero-input observation.
5. World evidence records the actual phase registration at dispatch without weakening route guards. The checked-in registration is returned to disabled after acceptance or failure; scheduler state and evidence remain history.

## Writable paths
- `automation_service/registry.py`
- `automation_service/handlers.py`
- `automation_service/service.py`
- `automation_service/cli.py`
- `scripts/pnsctl.py`
- `scripts/flow_delivery_world_map_bluestacks.py`
- `tasks/flow_delivery_disabled_production_registry.json`
- `tests/test_automation_service_contracts.py`
- `tests/test_automation_service_handlers.py`
- `tests/test_automation_service_cli.py`
- `tests/test_automation_service_scheduler.py`
- `tests/test_pnsctl_scheduler_pulse.py`
- `tests/test_world_map_navigation_bluestacks.py`
- Parent closure only: `CURRENT_HANDOFF.md`, `docs/runtime-reliability-convergence-status.md`, this manifest.

## Acceptance
- Registry rejects zero-or-multiple malformed registrations and every broad/mismatched handler/profile grant; disabled is still the default.
- Exactly World can be phase-registered in r1; status reports one registered flow and 22 disabled flows.
- One offline pulse selects World, starts no runtime, performs zero transport, persists a terminal selection fence, and a duplicate/restart pulse cannot select it again.
- Selection carries accepted product revision, exact registration status, scheduler eligibility, runtime-owner availability, clock/reset agreement, and no unresolved occurrence.
- Scheduler code does not import or invoke BlueStacks/runtime/route transport.
- Existing Stage 9 rollback/reset/unresolved regressions remain passing.
- World route still requires one active parent-owned `DevelopmentSession`, current typed/hash/invocation-bound observation, current-frame targets, semantic successors, zero forbidden inputs, and canonical terminal.
- Any blocked/unknown live result disables registration and does not authorize an identical retry.

## Validation and live budget
- Run exact registry/selection/duplicate/restart regressions, affected automation-service and World suites, then the focused World profile.
- Terra reviews only this diff and these acceptance criteria; style/speculative hardening are excluded.
- Parent integration acceptance precedes runtime admission.
- Run one fresh direct zero-input observation.
- Live budget after all gates: one World full-route canary, maximum 20 navigation/popup inputs as already bounded by the route; zero resource/Daily/combat/purchase/maintenance inputs.
- No phase 3 admission is implied by phase 2 acceptance.

## Final disposition
- `REJECTED_LOCAL_DEFECT`; no live canary or Phase 2 gameplay input occurred.
- Focused candidate checks passed 18 scheduler-bridge, 21 scheduler-persistence, and 57 World tests.
- Initial Terra review found that blocked/unknown live outcomes did not durably revoke registration.
- The one permitted repair added one-shot atomic registration consumption and immutable dispatch-time registration evidence.
- Terra recheck found that post-consumption World evidence verification reloaded the disabled registry instead of the immutable dispatch-time snapshot, making a valid canary unverifiable.
- The permitted Heavy repair/recheck cycle was exhausted. Parent rolled every implementation, test, registration, and scheduler change back to the published Phase 1 boundary.
- Final registration is `NOT_REGISTERED`; scheduler eligibility is false; registered flows are empty.
- Phases 3–6 remain unadmitted because required Phase 2 safety/semantic acceptance failed. Phase 7 remains unauthorized.
