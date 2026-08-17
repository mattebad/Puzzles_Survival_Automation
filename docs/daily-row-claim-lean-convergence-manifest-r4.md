# Daily row Claim lean convergence

## Task ID and objective
- Task ID: `DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`
- Objective: make the proven template-Home and color-Claim approach canonical inside the existing receipt-bound one-tap route, and retire the receipt-free duplicate.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `current Cursor conversation`
- `control_plane_owner`: `sol_parent`
- Revision ID: `daily-row-claim-lean-convergence-r4`
- Stage type: `implementation`
- Product precondition: `proven`
- Failure class: `local_defect`
- Stage start UTC: `not recorded`
- Continuation checkpoint UTC: `not recorded`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | Stage freeze, architecture, integration acceptance, live admission, failure classification, and termination |
| `procedure_coordinator` | `not used` | None |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | Assigned implementation paths and focused self-check only |
| `independent_tester` | `gpt-5.6-terra-high` | Read-only diff and acceptance review |
| `escalation_architect` | `not used` | None |

## Immutable budgets
- One Luna implementation and one Terra review.
- At most one parent-classified Luna repair and one Terra recheck.
- No live input in this implementation stage.
- A later parent integration checkpoint may freeze one separate live stage.

## Frozen architecture decision
- Keep `scripts/pnsctl.py` and `scripts/daily_row_claim_bluestacks.py` as the only supported Daily Claim runtime path.
- Replace OCR-derived Home navigation authority with `tasks.home_nav_recognition.recognize_home_nav`.
- Port the proven HSV gold-button binding into the canonical aggregate recognizer; OCR may remain only for selected-Daily identity, points, reset deadline, and spatially associated negative/cost evidence.
- Preserve exactly one aggregate Claim tap, current-frame revalidation, receipt reservation, singleton ownership, reset identity, cost/milestone/overlay rejection, points increase, Claim exhaustion, and canonical safety behavior.
- Compare the successor against the tap-authorizing immediate-before recognition, not the earlier source recognition.
- Retire `scripts/daily_claim_canary.py` as an executable runtime bypass. A compatibility shim may explain the canonical `pnsctl` command but must not acquire runtime ownership or dispatch input.
- Preserve the exact VIP popup handling unchanged.

## Writable paths
- `scripts/daily_row_claim_bluestacks.py`
- `scripts/daily_claim_canary.py`
- `tests/test_daily_row_claim_bluestacks.py`
- `docs/daily-row-claim-lean-convergence-manifest-r4.md` only for implementation receipt fields if needed

All other files are read-only. In particular, preserve the existing uncommitted user work in:
- `BACKLOG.md`
- `CURRENT_HANDOFF.md`
- `tasks/flow_delivery_queue.json`
- `tasks/gameplay_flow_contracts/DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION.json`
- `docs/daily-row-claim-bluestacks-live-acceptance-manifest.md`

## Acceptance checks
- Retained real Home fixtures pass through the template adapter and non-Home fixtures fail.
- Home recognition does not require Quest/Hero/Bag/Mail OCR.
- Gold Claim controls are detected without reading stylized `Claim` text and red `Go` controls are rejected.
- Canonical authorization still requires selected Daily, reset identity, points, free/non-milestone safety, current-frame binding, and exactly one input.
- Successor proof uses the immediate-before points/reset baseline.
- The standalone canary cannot dispatch runtime input.
- Existing exact VIP popup tests remain unchanged and passing.

## Safety limits
- Allowed implementation: recognition adapter, color detector, immediate-before baseline correction, standalone-script retirement, focused tests.
- Disallowed implementation: scheduler, registration, `pnsctl` receipt-schema changes, direct ADB, Bliss, milestone Claim, resource actions, second Claim tap, broad OCR redesign outside this flow.
- Runtime/session limits: zero live inputs in this stage.

## Validation commands
- `python -m unittest tests.test_daily_row_claim_bluestacks`
- `python -m unittest tests.test_home_nav_recognition`
- `python -m unittest tests.test_available_daily_claim`

The checked-in focused/shared-navigation runners remain parent integration checks because they write receipts.

## Evidence/history references
- Template recognizer commit: `0817980`
- Lean canary commit: `338e22b`
- Terminal OCR failure: `.local-captures/development-sessions/delegated-3589bf46-33a8-4396-8517-fccce900dc15`
- Prior live-acceptance manifest: `docs/daily-row-claim-bluestacks-live-acceptance-manifest.md`

## Required implementer return
- Changed paths and compact diff summary.
- Exact focused test commands and results.
- Any remaining material blocker.
- No integration, live-admission, or completion claim.

## Escalation conditions
- The template/color approach cannot preserve the one-tap safety contract.
- Current tests reveal a real conflict between aggregate mechanics and cost/milestone exclusion.
- A change outside the writable paths is required.
- Ordinary test failures and known local repairs do not escalate.
