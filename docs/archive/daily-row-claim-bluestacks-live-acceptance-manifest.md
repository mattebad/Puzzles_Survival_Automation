# Daily row Claim BlueStacks live acceptance

## Task ID and objective
- Task ID: `DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`
- Objective: prove one aggregate selected-Daily Claim from canonical Home, or retain a fail-closed terminal result.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `current Cursor conversation`
- `control_plane_owner`: `sol_parent`
- Revision ID: `daily-row-claim-live-acceptance-926659f-r3`
- Stage type: `live`
- Product precondition: `evidence_required`
- Failure class: `local_defect`
- Stage start UTC: `not recorded`
- Continuation checkpoint UTC: `not recorded`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-high` | Stage freeze, integration acceptance, live authority, failure classification, and termination |
| `procedure_coordinator` | `not used` | None |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | Revision-2 Home Quest recognition repair and self-check only |
| `independent_tester` | `gpt-5.6-terra-high` | Read-only admission review and repair recheck |
| `escalation_architect` | `not used` | None |

## Immutable budgets
- Per stage: one implementation, one review, at most one consolidated repair and one recheck, and one live iteration.
- Per parent conversation: three stage revisions and managed turns within the eight-turn limit.
- Timing: visible checkpoint at 60 minutes; at 90 minutes require recorded user continuation later than the stage start.

## Frozen architecture decision
- Use only `scripts/pnsctl.py` for BlueStacks runtime access and controller-issued single-use receipts for bounded reconnaissance or canary input.
- Bind Home, Quest, selected Daily, reset identity, and any ordinary free non-milestone Claim from current native 800x1280 frames.
- Permit at most two navigation inputs and one Claim input. A Claim can be dispatched exactly once only after immediate-before revalidation; success requires stable selected-Daily/reset identity, increased Daily points, and no remaining eligible ordinary Claim controls.
- Preserve no-direct-ADB, no-Bliss, no-registration, no-scheduling, no-second-Claim, singleton runtime, and retained-evidence boundaries.

## Writable paths
- `scripts/daily_row_claim_bluestacks.py`
- `tests/test_daily_row_claim_bluestacks.py`
- `BACKLOG.md`
- `CURRENT_HANDOFF.md`
- `tasks/flow_delivery_queue.json`
- `tasks/gameplay_flow_contracts/DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION.json`
- `docs/daily-row-claim-bluestacks-live-acceptance-manifest.md`

## Acceptance checks
- Clean committed candidate and candidate-bound focused and shared-navigation receipts.
- Zero-input observation proves the local BlueStacks package and native 800x1280 frame.
- Bounded Home to Quest to selected-Daily reconnaissance completes under its receipt.
- Fresh selected-Daily inspection proves reset identity and an eligible ordinary free non-milestone Claim, or terminates `evidence_required` without Claim input.
- One Claim tap proves points increased, selected-Daily/reset identity remained stable, and eligible ordinary Claim controls are exhausted.

## Safety limits
- Allowed actions: zero-input observation; at most two receipt-bound navigation taps; at most one receipt-bound ordinary Claim tap.
- Disallowed actions: direct ADB, Bliss tooling, milestone Claim, cost-bearing input, second Claim tap, another gameplay flow, registration, and scheduling.
- Runtime/session limits: singleton ownership; no combat or resource-affecting inputs; one final live iteration.

## Validation commands
- `python -m unittest tests.test_daily_row_claim_bluestacks`
- `python scripts/run_flow_delivery_validation.py focused --flow-id DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`
- `python scripts/run_flow_delivery_validation.py shared-navigation --flow-id DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`

## Live budget
- Live admission: `terminated evidence_required`
- Input budget: two navigation inputs plus one Claim input; zero inputs were dispatched in the terminal revision.
- Iteration budget: one; consumed by pre-input Home recognition failure.

## Evidence/history references
- Zero-input observation: `.local-captures/development-sessions/observe-20260817T054028182943Z`
- First pre-input reconnaissance failure: `.local-captures/development-sessions/delegated-e0dece90-4270-4cda-8aad-15bda0c689c0`
- Terminal pre-input reconnaissance failure: `.local-captures/development-sessions/delegated-3589bf46-33a8-4396-8517-fccce900dc15`
- Bounded implementer: `6ea97274-d39d-4ec9-a3e5-a6c61dc97b32`
- Independent tester/recheck: `cb31382e-0447-4370-b2c4-dbe289f1d260`

## Escalation conditions
- The terminal fresh frame visibly contains Quest while OCR fails to identify Quest, Bag, and Mail.
- This is the second materially different live recognition failure in the conversation and exhausts the third stage revision.
- Further implementation or live admission requires explicit user continuation and a new Sol-frozen stage.
