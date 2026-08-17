# Daily Row Claim execution manifest r3

## Task ID and objective
- Task ID: `daily-row-claim`
- Objective: Repair the current native Home Quest binding so the already-accepted
  Home-to-Daily route can freshly inventory the completed Zombie Lair row.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `6f7e9bb4-7ecf-4dfe-ac13-98cf0ba2b2fa`
- `control_plane_owner`: `sol_parent`
- Revision ID: `daily-row-claim-r3`
- Stage type: `local_defect_repair`
- Product precondition: `proven`
- Failure class: `local_defect`
- Stage start UTC: `2026-08-17T02:30:26.068Z`
- Continuation checkpoint UTC: `not recorded`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | Stage freeze, integration acceptance, live admission, and termination |
| `procedure_coordinator` | `not used` | Not applicable |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | Assigned production and test paths only |
| `independent_tester` | `gpt-5.6-terra-high` | Read-only defect-first review |
| `escalation_architect` | `not used` | Not applicable |

## Immutable budgets
- Per stage: one implementation, one review, at most one consolidated repair
  and one recheck, one live attempt.
- Per parent conversation: at most three stage revisions and eight managed turns.
- Timing: visible checkpoint at 60 minutes; at 90 minutes require recorded user
  continuation later than the stage start.

## Frozen architecture decision
- Decision: Preserve the accepted OCR-derived Quest label and navigation-lane
  geometry. Repair only the current-frame visual-component proof needed to bind
  that exact Quest control from retained native Home evidence. Do not add fixed
  coordinates, generic icon matching, fallback taps, or broaden any non-Home
  authority.
- Preserved invariants: local BlueStacks only, native `800x1280`,
  `scripts/pnsctl.py` only for runtime, immediate-before revalidation, no direct
  ADB, no second gameplay flow, no Claim input in this stage, and no identical
  retry without the repaired candidate.

## Writable paths
- Production: `scripts/daily_row_claim_bluestacks.py`
- Tests: `tests/test_daily_row_claim_bluestacks.py`

## Acceptance checks
- Add an exact regression using the retained current Home source semantics that
  proves one row-local `home-quest-entry` target and remains negative for missing,
  ambiguous, out-of-lane, overlay, or wrong-label evidence.
- Run the exact regression, the affected Daily package suite, and the focused
  Daily flow profile once.
- Independent tester reports no material correctness, runtime-safety, acceptance,
  regression, or maintainability defect.
- Parent integration confirms the patch stays inside the frozen architecture
  before one new reconnaissance receipt is issued.

## Safety limits
- Allowed actions after integration acceptance: one receipt-bound
  `home-quest-entry` and one receipt-bound `quest-daily-tab` navigation input.
- Disallowed actions: Claim, Go, milestone, resource, combat, Cash Mall,
  registration, scheduling, composition, M6, Bliss, direct ADB, generic recovery,
  or any other gameplay flow.
- Runtime/session limits: singleton ownership, at most two navigation inputs,
  zero resource-affecting inputs, and zero combat confirmations.

## Validation commands
- `python -m unittest tests.test_daily_row_claim_bluestacks`
- `python scripts/run_flow_delivery_validation.py focused --flow-id DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`

## Live budget
- Live admission: authorized only after implementation self-check, independent
  review, and parent integration acceptance.
- Input budget: two navigation inputs.
- Iteration budget: one repaired Home-to-Daily reconnaissance attempt.

## Evidence/history references
- Retained source:
  `.local-captures/development-sessions/delegated-9ba8b6e5-3c79-49df-9d96-8ac24a9421fd/runtime/daily-row-reconnaissance-20260817T022942663935Z/frames/0001-home-source.png`
- Source SHA-256:
  `0efd272a66314b944978f1b7acd82c9482d3ba02b13585b5ac4dd2694be80d8e`
- Terminal receipt: `9ba8b6e5-3c79-49df-9d96-8ac24a9421fd`; zero inputs,
  ownership released, `evidence_required`.
- The consumed scan receipt
  `54d8447d-da30-4115-a7a0-1c6209f54dd0` remains immutable and must not be
  repeated.

## Escalation conditions
- Approved plan is contradictory or incomplete.
- A genuinely new architecture decision is required.
- Safety authority is ambiguous.
- Tester and implementation evidence conflict.
- Two materially different repair hypotheses fail.
- Live evidence disproves the accepted design.
- Ordinary test failures, syntax errors, and known repairs do not escalate.
