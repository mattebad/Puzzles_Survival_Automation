# Stage 10 phase 1 observation-only scheduler promotion manifest

## Task ID and objective
- Task ID: `stage-10-phase-1-observation-projection`
- Objective: compare the authoritative scheduler's zero-transport eligibility decisions with current disabled product state and prove persistence/fencing behavior without registering or dispatching any flow.

## Frozen stage control
- Host: `codex`
- Parent conversation ID: `current-task`
- `control_plane_owner`: `sol_parent`
- Revision ID: `runtime-reliability-stage-10-phase-1-observation-r1`
- Stage type: `observation_only_cross_contract_live`
- Product precondition: `proven` — Stage 9 is published through `d10d8c63f2ccd52525cb76f87f851d0c00c86943`; the affected suite passes 39 tests; all BlueStacks flows are disabled, not registered, and scheduler-ineligible.
- Failure class: `none`
- Stage start UTC: `2026-08-25T16:12:00.000Z`
- Continuation checkpoint UTC: `not recorded`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | stage freeze, phase admission, integration acceptance, runtime ownership, classification, termination |
| `procedure_coordinator` | `not used` | none |
| `bounded_implementer` | `not used` | no production mutation admitted |
| `independent_tester` | `gpt-5.6-terra-high` | read-only final diff and acceptance review after phases 1–6 |
| `escalation_architect` | `not used` | none |

## Immutable budgets
- One observation-only phase attempt; zero gameplay inputs and zero transports.
- No implementation or repair is admitted in this revision.
- Parent conversation remains bounded by the repository's three-revision/eight-managed-turn ceiling for Heavy redesign work; ordinary evidence-required dispositions do not create revisions.

## Frozen architecture decision
- Decision: use only `scripts/pnsctl.py automation-service status`, the offline `automation-service pulse`, focused deterministic scheduler tests, and one `development-session observe --max-inputs 0`. The production scheduler remains disabled and receives no target binding, session authority, or transport authority.
- Preserved invariants: `UtcPulseCoordinator` remains the sole kernel; SQLite remains sole invocation/occurrence authority; every flow stays disabled/NOT_REGISTERED/ineligible; singleton observation is zero-input; retained evidence is not relabeled current.

## Writable paths
- `CURRENT_HANDOFF.md`
- `docs/runtime-reliability-convergence-status.md`
- `docs/execution-manifests/runtime-reliability-stage-10-phase-1-observation-r1.md`

## Acceptance checks
- Status reports no registered flows and scheduler eligibility false for every allowlisted flow.
- Offline pulse selects no candidate and reports zero dispatch/transport.
- Focused tests prove disabled/unaccepted exclusion, duplicate pulse, restart, clock rollback, reset disagreement, and unresolved-occurrence behavior.
- A zero-input DevelopmentSession observes current private BlueStacks state, writes compact evidence, and releases singleton ownership with transport count zero.

## Safety limits
- Allowed actions: read-only status, deterministic offline pulse against an attributable temporary SQLite state, and current-frame observation with input ceiling zero.
- Disallowed actions: registration, eligibility enablement, handler start, gameplay input, scheduler target/session binding, resource action, claim, combat, purchase, maintenance, Daily action, direct ADB, or another controller.
- Runtime/session limits: exactly one parent-owned observation session, zero inputs, zero transport, automatic singleton acquisition/release.

## Validation commands
- `python -m unittest tests.test_automation_service_scheduler tests.test_automation_service_contracts tests.test_automation_service_operations tests.test_automation_service_cli tests.test_scheduler_invocation_state tests.test_scheduler tests.test_scheduler_sqlite tests.test_scheduler_retirement tests.test_pnsctl_scheduler_pulse`
- Exact duplicate/restart/rollback/reset/unresolved selectors from the same modules.
- `python scripts/pnsctl.py automation-service status`
- `python scripts/pnsctl.py automation-service pulse --state-path <temporary phase state> --account-id stage10-observe --server-id local --reset-id phase1 --now-utc-epoch <fixed epoch>`
- `python scripts/pnsctl.py development-session observe --max-inputs 0 --task-id stage-10-phase-1-observation-projection --flow-id WORLD-MAP-NAVIGATION-FOUNDATION --scenario scheduler-eligibility-observation --variant zero-input`

## Live budget
- Live admission: `authorized for zero-input observation only`
- Input budget: `0`
- Iteration budget: `1`

## Evidence/history references
- Stage 9 closure: `docs/execution-manifests/runtime-reliability-stage-9-scheduler-r3.md` plus commits `543bf98a17925a8ca5feb61a13a6701e8cad33b1`, `a9c222e43692466d2f644d70160f40797c20402c`, and `d10d8c63f2ccd52525cb76f87f851d0c00c86943`.
- Current scheduler status and the phase-specific offline SQLite state/DevelopmentSession result become phase evidence; prior gameplay evidence remains historical.

## Escalation conditions
- Any flow appears registered or scheduler-eligible before explicit later-phase admission.
- Any offline pulse creates target binding, runtime ownership, handler start, transport, or unresolved state.
- Runtime-owner conflict, stale/unknown observation safety, manual-only state, or nonzero transport.
- A repeat failure or no furthest-progress advance is `diminishing_returns`; do not retry identically.
