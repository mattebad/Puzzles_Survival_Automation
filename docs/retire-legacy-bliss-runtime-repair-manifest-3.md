# Retire Legacy Bliss Runtime — repair stage 3

## Task ID and objective
- Task ID: `retire-legacy-bliss-runtime`
- Objective: Align the pre-dispatch freshness test fixture with the BlueStacks-only central policy introduced by repair stage 2.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `6f7e9bb4-7ecf-4dfe-ac13-98cf0ba2b2fa`
- `control_plane_owner`: `sol_parent`
- Revision ID: `retire-legacy-bliss-runtime-repair-3`
- Stage type: `repair`
- Product precondition: `proven`
- Failure class: `local_defect`
- Stage start UTC: `not recorded`
- Continuation checkpoint UTC: `not recorded`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-high` | Stage freeze, integration acceptance, live authority, and termination |
| `procedure_coordinator` | `not used` | None |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | Assigned fixture repair and self-check only |
| `independent_tester` | `gpt-5.6-terra-high` | Read-only final recheck |
| `escalation_architect` | `not used` | None |

## Immutable budgets
- Per stage: one implementation, one review, at most one repair and one recheck, and zero live attempts.
- Per parent conversation: this is the third and final stage revision.

## Frozen architecture decision
- Pre-dispatch freshness tests exercise active policy behavior and therefore use `pns-bluestacks-5-p64-800x1280-v1` for successful-path fixtures.
- Retired Bliss denial remains covered by the dedicated input-capability firewall negative tests.
- No production behavior, documentation authority, runtime, registration, scheduling, or historical evidence changes are permitted.

## Writable paths
- `tests/test_pre_dispatch_freshness.py`

## Acceptance checks
- `python -m unittest tests.test_pre_dispatch_freshness` passes.
- Dedicated retired-profile denial tests continue to pass.
- Repair-stage focused tests and `git diff --check` pass.
- One Terra High read-only final recheck reports no material findings.

## Safety limits
- Allowed actions: one offline test-fixture correction.
- Disallowed actions: production edits, emulator input, direct ADB, live canary, registration, scheduling, evidence mutation, and unrelated cleanup.
- Runtime/session limits: no development session and zero input.

## Validation commands
- `python -m unittest tests.test_pre_dispatch_freshness tests.test_input_capability_firewall tests.test_safe_action_core tests.test_daily_row_claim_bluestacks`
- `git -c core.whitespace=cr-at-eol diff --check`

## Live budget
- Live admission: `not authorized`
- Input budget: `0`
- Iteration budget: `0`

## Evidence/history references
- Stage 2 self-check identified the stale retired-profile fixture after the central policy repair.

## Escalation conditions
- The fixture change does not restore the intended freshness assertions.
- Dedicated retired-profile denial regresses.
- Tester and implementation evidence conflict.
