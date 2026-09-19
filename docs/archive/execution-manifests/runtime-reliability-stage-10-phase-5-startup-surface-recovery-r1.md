# Stage 10 phase 5 shared startup-surface recovery r1

## Task ID and objective
- Task ID: `runtime-reliability-stage-10-phase-5-startup-surface-recovery-r1`.
- Objective: Add one shared, typed, fail-closed startup recovery seam for the exact Scarlett 3-Day Pack surface while preserving VIP behavior and DevelopmentSession accounting.

## Frozen stage control
- Host: `cursor`.
- Parent conversation ID: `stage-10-phase-5-reproof-20260826`.
- `control_plane_owner`: `sol_parent`.
- Revision ID: `runtime-reliability-stage-10-phase-5-startup-surface-recovery-r1`.
- Stage type: `implementation`.
- Product precondition: `proven`.
- Failure class: `none`.
- Stage start UTC: `2026-08-26T17:59:59.546Z`.
- Continuation checkpoint UTC: `not recorded`.

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | stage freeze, acceptance, live, termination |
| `procedure_coordinator` | `not used` | optional checklist assistance only |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | assigned paths only |
| `independent_tester` | `gpt-5.6-terra-high` | read-only review/recheck |
| `escalation_architect` | `gpt-5.6-sol-medium` | architecture conflicts only |

## Immutable budgets
- Per stage: one implementation, one review, at most one repair and one recheck, one live attempt.
- Per parent conversation: at most three stage revisions and eight managed turns.
- Timing: visible checkpoint at 60 minutes; at 90 minutes require recorded user continuation later than the stage start.

## Frozen architecture decision
- Decision: Keep the flow-owned DevelopmentSession as the sole runtime/input owner and add a shared `pnsctl.py` pre-flow seam that classifies the retained first frame before typed route observation. Extend `startup_recovery.py` with typed Scarlett recognition/reconciliation; route modules only retain route-specific successor recognition and no duplicate startup dismissal.
- Preserved invariants: VIP_POINTS_GET_PTS behavior; current-frame hash/profile/geometry/title/semantic/ROI binding; forbidden payment-region exclusion; fail-closed unknown commercial surfaces; exact one-input recovery ceiling; fresh post-recovery route frame; split recovery/route/total ledger accounting; singleton ownership; no Android Back; no registration or scheduler authority; protected evidence unchanged; no identical retry.

## Writable paths
- `scripts/startup_recovery.py`
- `scripts/pnsctl.py`
- `scripts/startup_surface_recognition.py` (only if required)
- `scripts/flow_delivery_campaign_bluestacks.py` (duplicate removal/accounting only)
- `scripts/noahs_tavern_recruit_bluestacks.py` (duplicate removal/accounting only)
- `tests/test_startup_recovery.py`
- `tests/test_development_session.py`
- `tests/test_flow_delivery_campaign_bluestacks.py`
- `tests/test_flow_delivery_recruitment_bluestacks.py`
- `tests/test_noahs_tavern_recruit.py`
- `tasks/assets/navigation/800x1280/scarlett-three-day-pack-positive.png`
- `tasks/assets/navigation/800x1280/scarlett-three-day-pack-annotated.png`
- `tasks/assets/navigation/800x1280/scarlett-three-day-pack-provenance.json`
- `docs/execution-manifests/runtime-reliability-stage-10-phase-5-startup-surface-recovery-r1.md`
- `docs/android-back-state-matrix.md` only if needed to distinguish visible in-game Back from Android Back.

## Acceptance checks
- Exact Scarlett full-page positive recognition passes only with the retained native profile, `800x1280` geometry, current-frame hash, exact title-associated semantic evidence, safe in-game Back ROI `(11,54,72,117)`, forbidden payment/Confirm ROIs, expected successor, and maximum one input.
- Title-only, price-only, similar-shop, wrong-geometry, missing-purchase-exclusion, scaled/cropped, stale/hash-mismatched, and ambiguous/multiple-target inputs fail closed.
- Existing `VIP_POINTS_GET_PTS` behavior is unchanged.
- Every supported development flow runs the shared classifier before typed route initial observation; unknown commercial/payment surfaces block.
- After one Scarlett Back, disappearance plus a retained successor reconciles as `surface_dismissed_successor_captured`; an unallowlisted successor stops as `evidence_required` without another input.
- Recovery/route/total counts are exact and one DevelopmentSession/runtime owner and ledger are retained.
- Deterministic native positive/annotation/provenance evidence is checked in without payment-region intersection.

## Safety limits
- Allowed actions: zero-input classification and, only after exact current-frame revalidation, one visible in-game Scarlett Back input; capture immediate-before, transport, immediate-post/settled successor and semantic evidence.
- Disallowed actions: Android Back; purchase/Buy/Purchase/Confirm or payment-region taps; guessed successor dismissal; identical retry; live input during implementation; registration/scheduler/product-record changes; direct ADB/BlueStacks transport; app restart; stash/commit/push.
- Runtime/session limits: one flow-owned DevelopmentSession/runtime owner and ledger; recovery reserve conditional on exact recognition; maximum one Scarlett recovery input in Stage A; fresh post-recovery frame is the route's typed initial observation; unknown commercial surfaces block.

## Validation commands
- `python -m unittest tests.test_startup_recovery tests.test_development_session`
- `python -m unittest tests.test_flow_delivery_campaign_bluestacks tests.test_flow_delivery_recruitment_bluestacks tests.test_noahs_tavern_recruit`
- `python scripts/run_flow_delivery_validation.py shared-navigation --flow-id CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY`
- `python scripts/validate_governance.py`
- `git diff --check`
## Live budget
- Live admission: `not authorized`.
- Input budget: `zero`.
- Iteration budget: `one implementation, one review, at most one repair and one recheck`.

## Evidence/history references
- Fresh native precondition: `.local-captures/development-sessions/observe-20260826T175959000083Z/observe.png` (native `800x1280`, SHA-256 `f828bfa09af4d8085d69d432d471ede67f7bc5562a43a5fc58454ff3bd3ecbdc`).
- Retained prior observation: `.local-captures/development-sessions/observe-20260826T174701943034Z/observe.png` (SHA-256 `1f5d29b3a1ec49fd8beee446563014dc435fcb34082eb970d461c03b5e9033fb`).
- Frozen plan: `.cursor/plans/stage_10_phase_5_startup_surface_recovery_and_campaign_reproof.plan.md`.

## Escalation conditions
- Approved plan is contradictory or incomplete.
- A genuinely new architecture decision is required.
- Safety authority is ambiguous.
- Tester and implementation evidence conflict.
- Two materially different repair hypotheses fail.
- Live evidence disproves the accepted design.
- Convergence stalls (`diminishing_returns`).
