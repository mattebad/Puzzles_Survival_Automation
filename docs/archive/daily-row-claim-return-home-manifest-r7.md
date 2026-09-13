# Daily row Claim verified Home return

## Task ID and objective
- Task ID: `DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`
- Objective: make every successful aggregate Daily Claim back out and positively verify Base/Home before terminal completion, then prove the return without repeating the current-reset Claim.

## Explicit policy exception
- The user explicitly authorized continuing in this chat and bypassing/resetting the prior three-stage conversation cap on 2026-08-17.
- This exception authorizes exactly this bounded return-Home stage. It does not weaken runtime safety, singleton ownership, receipt binding, review, test, evidence, registration, or scheduler restrictions.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `current Cursor conversation`
- `control_plane_owner`: `sol_parent`
- Revision ID: `daily-row-claim-return-home-r7`
- Stage type: `implementation-review-live`
- Product precondition: `proven_selected_daily_after_claim`
- Failure class: `local_defect`
- Stage start UTC: `not recorded`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | Architecture, integration acceptance, live admission, failure classification, and termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One bounded implementation and focused self-check |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only defect-first review |
| `procedure_coordinator` | `not used` | None |
| `escalation_architect` | `not used` | None |

## Frozen architecture
- Keep `scripts/pnsctl.py` as the only runtime interface.
- Extend the canonical canary from one input to two: one aggregate Claim followed by one bounded Android Back.
- The Claim subaction must retain all current eligibility, current-frame, reset, cost, milestone, points-increase, and Claim-exhaustion gates.
- After Claim success, capture a fresh selected-Daily frame, positively recognize selected Daily, dispatch exactly one Back, poll boundedly, and require template-based `HOME` recognition.
- Canary terminal completion requires both the Claim semantic postcondition and verified Home. Unknown or non-Home successor is `evidence_required`; no second Back or Claim.
- Add a receipt-bound `return-home` mode with exactly one navigation input. It starts only from positively recognized selected Daily and exists to prove/recover the missing terminal step without repeating a same-reset Claim.
- `return-home` must fail closed from Home, Quest, unknown, overlay, wrong dimensions, or stale input.
- Preserve VIP popup handling unchanged.

## Writable paths
- `scripts/daily_row_claim_bluestacks.py`
- `scripts/bluestacks_native_runtime.py` (repair only: optional Back target identity, default unchanged)
- `scripts/pnsctl.py`
- `tests/test_daily_row_claim_bluestacks.py`
- `docs/daily-row-claim-return-home-manifest-r7.md` only for compact implementation receipts if needed

All other files are read-only during implementation.

## Acceptance checks
- Canonical canary records two actions in order: `daily-claim:aggregate`, then `daily-claim:return-home`.
- Canary cannot report completed unless final template Home recognition succeeds.
- Return-Home mode records one navigation action, one input, selected-Daily source/immediate-before, immediate-post/polls as needed, and final Home.
- Current selected-Daily state after the accepted Claim can be returned Home without another Claim.
- Home/Quest/unknown sources, stale immediate-before, overlay, extra Back, and non-Home terminal fail closed.
- pnsctl parser, receipt specification, exact action bindings, artifact validation, and result identity cover both modes.
- Existing Claim, selected-Daily, template Home, VIP, reset, and cost-negative tests remain passing.

## Offline validation
- `python -m unittest tests.test_daily_row_claim_bluestacks`
- `python -m unittest tests.test_home_nav_recognition`
- `python -m unittest tests.test_available_daily_claim`
- focused and shared-navigation profiles after independent review

## Live budget
- No live input during implementation or review.
- After clean commit and parent acceptance: one `return-home` receipt, one navigation input, zero resource inputs, zero combat inputs.
- Do not issue another current-reset Claim.

## Required returns
- Luna: changed paths, compact diff, exact tests/results, blockers; no integration/live claim.
- Terra: material findings only or explicit no findings; no repair authorization.
- Parent: explicit integration decision and one live return result.

## Parent-authorized consolidated repair
- Finding 1: the reconnaissance permit rejects action identities containing `claim`; freeze the navigation identity as `daily-return-home`.
- Finding 2: native Back currently reserves fixed identity `android-back`; add an optional `target_identity` parameter defaulting to `android-back`, and pass `daily-return-home` only from this route so the native reservation exactly matches its receipt.
- Finding 3: parameterize the helper's expected consequence class so canary uses `ordinary_development` and return-home-only uses `navigation_only`.
- Finding 4: runtime and artifact acceptance must require explicit `template_home.recognized == true`; generic `HOME` is insufficient.
- One Luna repair and one Terra recheck are authorized. No live input is authorized until both pass and the parent accepts integration.
