# Daily Row Claim execution manifest r4

## Task ID and objective
- Task ID: `daily-row-claim`
- Objective: Tolerate bounded transient OCR loss during Home Quest
  immediate-before revalidation without reserving or transporting input until a
  fresh frame positively re-proves the exact target.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `6f7e9bb4-7ecf-4dfe-ac13-98cf0ba2b2fa`
- `control_plane_owner`: `sol_parent`
- Revision ID: `daily-row-claim-r4`
- Stage type: `local_defect_repair`
- Product precondition: `proven`
- Failure class: `local_defect`
- Stage start UTC: `2026-08-17T03:02:27.470Z`
- Continuation checkpoint UTC: `2026-08-17T03:02:27.470Z`

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
- R3 used four managed turns. R4 may use at most four managed turns.
- Explicit user continuation is recorded. The active policy permits same-chat
  continuation while these conversation budgets remain available.

## Frozen architecture decision
- Decision: Preserve the accepted r3 Home visual binding and the shared
  `DevelopmentSession` contract. Add bounded, no-input fresh-frame polling
  inside the Daily route's immediate-before dispatch callback when exact Home
  recognition is transiently absent. Dispatch only from the first fresh frame
  that positively re-proves `HOME` plus `home-quest-entry`; if none does, stop
  `evidence_required` without receipt reservation or runtime transport.
- Preserved invariants: every poll uses `session.observe`, all frames and
  recognitions are retained, the final dispatch source is fresh and
  runtime-ready, target geometry comes only from that frame, and successor
  authority is unchanged. No generic fallback, fixed coordinate, identical
  receipt reuse, second gameplay flow, or Claim authority is added.

## Writable paths
- Production: `scripts/daily_row_claim_bluestacks.py`
- Tests: `tests/test_daily_row_claim_bluestacks.py`

## Acceptance checks
- Exact regression: initially recognized Home source, failed first
  immediate-before OCR, then one bounded fresh poll positively re-proves the
  exact Quest target and dispatches once from that polled frame.
- Negative regression: all bounded polls fail and runtime transport/reservation
  remain absent; terminal evidence is `evidence_required`.
- Retained evidence records ordered poll frames, recognitions, source hashes,
  and the exact frame used for dispatch.
- Existing immediate-before freshness, package, profile, overlay, ambiguity,
  target-identity, and geometry gates remain negative.
- Affected Daily package suite and focused flow profile pass; independent review
  reports no material defect; parent integration accepts before live admission.

## Safety limits
- Allowed actions after integration acceptance: one receipt-bound
  `home-quest-entry` and one receipt-bound `quest-daily-tab` navigation input.
- Disallowed actions: Claim, Go, milestone, resource, combat, Cash Mall,
  registration, scheduling, composition, M6, Bliss, direct ADB, generic recovery,
  or any other gameplay flow.
- Runtime/session limits: singleton ownership; bounded no-input observation
  polling; at most two navigation transports; zero resource-affecting inputs;
  zero combat confirmations.

## Validation commands
- `python -m unittest tests.test_daily_row_claim_bluestacks`
- `python scripts/run_flow_delivery_validation.py focused --flow-id DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`

## Live budget
- Live admission: authorized only after implementation self-check, independent
  review, parent integration acceptance, and a clean committed candidate.
- Input budget: two navigation transports.
- Iteration budget: one r4 Home-to-Daily reconnaissance attempt.

## Evidence/history references
- R3 candidate: `1a3de21a5e6bdeba070e649a454f1609d9013cd2`
- Consumed r3 receipt: `b4657bc0-7da6-4278-8876-000d2b8781e4`
- Positively recognized source SHA-256:
  `51fb7d684b05b3b0055d59ce9d25f41da52a1f4d2a517e07f166790345e453f8`
- Failed immediate-before SHA-256:
  `2057f078d7f57e73640474370ff13e68dded6c6e913d401f8c9a2d75a0c4dbc3`
- R3 runtime events/actions were empty, `runtime_input_count` was zero,
  ownership released, and unresolved state was clear. Its session-local input
  budget counter was one.
- All consumed Daily receipts remain immutable and must not be repeated.

## Escalation conditions
- Approved plan is contradictory or incomplete.
- A genuinely new architecture decision is required.
- Safety authority is ambiguous.
- Tester and implementation evidence conflict.
- Two materially different repair hypotheses fail.
- Live evidence disproves the accepted design.
- Ordinary test failures, syntax errors, and known repairs do not escalate.
