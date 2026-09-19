# Daily row Claim lean live acceptance

## Task ID and objective
- Task ID: `DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`
- Objective: run the canonical template/color route from Home to selected Daily and prove at most one aggregate Claim.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `current Cursor conversation`
- `control_plane_owner`: `sol_parent`
- Revision ID: `daily-row-claim-lean-live-r5`
- Stage type: `live`
- Product precondition: `proven`
- Failure class: `none`
- Stage start UTC: `not recorded`
- Continuation checkpoint UTC: `not recorded`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | Live admission, runtime ownership, failure classification, and termination |
| `procedure_coordinator` | `not used` | None |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | Completed implementation only; no live authority |
| `independent_tester` | `gpt-5.6-terra-high` | Completed read-only review only |
| `escalation_architect` | `not used` | None |

## Frozen candidate
- Commit: `b3f28b8`
- Implementation self-check: 74 Daily tests passed with 16 retired OCR tests skipped; 3 Home tests passed; 9 aggregate-contract tests passed.
- Independent review: Terra High reported no material findings.
- Parent integration: focused profile 9 and shared-navigation profile 18 passed; template/color one-tap candidate accepted for this live stage.

## Frozen architecture decision
- Use only `scripts/pnsctl.py`.
- One staged live iteration may use a reconnaissance receipt for Home → Quest → Daily and, only if the selected-Daily safety preconditions are proven, one canary receipt for exactly one aggregate Claim.
- Template Home and HSV gold Claim binding are authoritative for those controls. Selected Daily, reset identity, points, cost/milestone/overlay negatives, and immediate-before revalidation remain mandatory.
- Success requires points increase and zero remaining eligible ordinary Claim controls.

## Safety limits
- Allowed inputs: at most two navigation taps plus at most one ordinary aggregate Claim tap.
- Disallowed: second Claim, milestone Claim, red Go, resource/currency input, combat, direct ADB, Bliss, another gameplay flow, registration, or scheduling.
- Unknown state or failed recognition stops before the next input.
- Singleton runtime ownership is required and automatically released.

## Validation and live commands
- Zero-input observation already proved package `com.global.ztmslg`, native `800x1280`, frame SHA-256 `fc2ceea5a8ffebdd90a16f5bda225df89c81562d7f26b11fe79a654c8d2152fe`, and released ownership.
- Issue one exact reconnaissance receipt and run `pnsctl development-session daily-row-reconnaissance` with maximum two inputs.
- If reconnaissance proves selected Daily and releases ownership, issue one exact canary receipt and run `pnsctl development-session daily-row-claim --mode canary` with maximum one input.

## Live budget
- Live admission: authorized.
- Total input ceiling: three.
- Claim input ceiling: one.
- Iteration budget: one staged reconnaissance-plus-conditional-canary sequence.

## Evidence requirements
- Retain source, immediate-before, transport, immediate-post, semantic result, and annotated target.
- Report transport separately from semantic acceptance.
- Classify any failure before repair; identical retries are prohibited.
