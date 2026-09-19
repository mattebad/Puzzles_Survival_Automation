# Daily row Claim selected-tab repair and live recheck

## Task ID and objective
- Task ID: `DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`
- Objective: replace the remaining OCR-gated selected-Daily successor check with the existing visual tab-state proof, then perform one final canonical live recheck.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `current Cursor conversation`
- `control_plane_owner`: `sol_parent`
- Revision ID: `daily-row-claim-selected-tab-repair-r6`
- Stage type: `repair-and-live`
- Product precondition: `proven`
- Live failure class: `local_defect`
- Stage start UTC: `not recorded`
- Continuation checkpoint UTC: `not recorded`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | Repair authorization, integration acceptance, live admission, and termination |
| `procedure_coordinator` | `not used` | None |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One classified repair and focused self-check |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only recheck |
| `escalation_architect` | `not used` | None |

## Immutable budgets
- One consolidated Luna repair and one Terra recheck.
- One parent integration checkpoint.
- One live reconnaissance-plus-conditional-canary recheck.
- No second repair in this conversation.

## Classified live evidence
- Receipt: `ff8e1873-88d5-4ad6-8a2d-52a22782e49c`
- Home template passed at correlation `0.967302`.
- Home → Quest completed.
- Quest → Daily input was transported.
- Immediate post remained Main Quest while the screen loaded.
- Poll 04 visibly proved selected Daily, `Daily Quest Pts: 20`, `Reset Time: 03:49:38`, one gold `Claim`, and red `Go` controls.
- `recognize_daily_selected()` rejected poll 04 only because its OCR output omitted the stylized selected `Daily Quest` title.
- No Claim input occurred; total inputs were two navigation taps and ownership was released.

## Frozen repair
- Reuse `_selected_daily_visual_context(frame, tokens)` inside `DailyRowClaimRecognizer.recognize_daily_selected()`.
- The successor must not require OCR of the selected `Daily Quest` title.
- Preserve main/alliance spatial context, visual selected-tab margin, full-frame overlay rejection, fixed native profile, and no input authority.
- Do not redesign Quest-entry binding, Claim binding, reset/points parsing, cost/milestone checks, receipt handling, polling, or VIP behavior.

## Writable paths
- `scripts/daily_row_claim_bluestacks.py`
- `tests/test_daily_row_claim_bluestacks.py`
- `docs/daily-row-claim-selected-tab-repair-manifest-r6.md` only for a compact receipt if needed

All other paths are read-only.

## Acceptance checks
- The retained poll-04 frame is positively recognized as selected Daily when selected-title OCR is absent.
- The retained Main Quest frame is rejected as selected Daily.
- Unknown/malformed tab geometry and overlays remain fail-closed.
- Existing template Home and HSV Claim tests remain passing.
- Focused Daily, Home, and aggregate-contract suites pass.

## Live safety limits
- After repair, review, clean commit, and parent acceptance, one final staged live sequence is allowed.
- Maximum two navigation taps plus one aggregate Claim tap.
- No milestone, red Go, resource/currency, combat, direct ADB, Bliss, scheduler, or other-flow input.
- No identical retry: the recheck is authorized only by the concrete selected-tab repair.

## Required returns
- Luna: changed paths, compact diff, exact tests/results, blockers; no integration claim.
- Terra: material findings only or explicit no-findings; no repair authorization.
- Parent: explicit integration decision and live result classification.
