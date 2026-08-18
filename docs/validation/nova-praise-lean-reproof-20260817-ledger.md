# Nova Praise lean reproof — flow-attempt ledger

## Header
- Task ID / flow ID: `nova-praise` / `NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE`
- Product goal: one current-reset free Praise pulse from canonical Home, with exact decrement/cooldown proof and canonical Home regained.
- Input ceiling: `8` total inputs for the task; at most `1` Praise and `1` Nova-screen Back.
- Inputs used in accepted live pulse: `4` navigation (`1` pan, `2` taps,
  `1` Nova-screen Back); `1` Praise

## Framing gate
- [x] Intent match — terminal postcondition is exact free-Praise semantic proof plus canonical Home.
- [x] No documented-unsafe input — Home and radial Back are excluded; only the retained exact Nova-screen Back transition may be used.
- [x] No manual-only precondition — login, tutorial, CAPTCHA, account selection, and credential entry are stops.
- [x] Consequential actions enumerated — project policy treats Praise as ordinary interaction; the route still isolates exactly one account-changing zero-cost Praise. No combat or real-money confirmation exists.
- [x] Decisions resolved — the verified reset ID selects a fresh guard path; no historical guard is overwritten.
- [x] Durable-knowledge-consulted list is non-empty.

## Furthest-progress ratchet
- Furthest confirmed milestone:
  `current_reset_one_free_praise_confirmed_and_canonical_home_regained`
- Input index at that milestone: `5`
- Evidence references:
  - `.local-captures/flow-delivery/NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE/nova-praise-one-free-pulse-20260818T044710604641Z/result.json`
  - `.local-captures/flow-delivery/NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE/nova-praise-one-free-pulse-20260818T044710604641Z/frames/0017-canary-return-01-settled.png`
  - `.local-captures/development-sessions/observe-20260818T045302438159Z/observe.png`

## Durable knowledge consulted before this attempt
- `docs/android-back-state-matrix.md`
- `docs/runtime-input-safety-policy.md`
- `docs/visual-ground-truth-policy.md`
- `tasks/gameplay_flow_contracts/NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE.json`
- `docs/validation/gf-nova-praise-supervised-20260722-manifest.json`
- `.local-captures/flow-delivery/NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE/nova-praise-one-free-pulse-20260722T223535494658Z/events.jsonl`

## Iteration record
| # | Outcome | Defect signature | Ratchet after | Safety envelope intact | Decision | Rule fired |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `blocked_pre_input` | `home_zoomed_confidence_0.8689_below_0.90` | `current_reset_home_observed` | yes; zero input | `CONTINUE` after exact repair | local defect, no execution budget consumed |
| 2 | `blocked_navigation_only` | `home_atlas_bound_research_lab_roi_hit_37games_surface` | `current_reset_home_normalized` | Praise boundary intact; target binding disproved | `ESCALATE_USER` | second distinct live failure / diminishing returns |
| 3 | `completed_semantically; wrapper_unresolved` | `return_successor_recognized_without_home_context` | `one_free_praise_and_canonical_home` | yes; journal confirmed and no repeat Praise | `STOP_DONE` after retained/current Home proof | local postcondition defect after furthest-progress advance |

## Convergence counters
- Iterations since furthest-progress advance: `0`
- Distinct defect signatures this task: `3`
- Repeat defect signatures this task: `0`
- Per-subsystem defect counts:
  `Home context authority: 1; Home Atlas target planning: 1; terminal recognition handoff: 1`
- STEP_BACK redesigns spent this task: `2` (the second followed explicit user
  continuation and correction that the bottom nav is global)

## Fail-closed teardown
- Known-benign exit dialog: Cancel only, never Confirm.
- Unknown or consequential modal: retain evidence, state it explicitly, and stop.
- Never issue an identical retry for teardown.
- Current terminal surface: canonical Home. The accepted live pulse used the
  planner-required pan before Research Lab entry and did not repeat the
  disproven ROI.
- Both current-reset guards were archived only after proven-no-effect receipts:
  `b4a4e2844bc361dcb6d818e90a4bb0945bc44236afa903dbbcc65027f4468900`
  and `cc40bd360c8fb92de2f54bff04dc986a6c0f778e5516087ca88f3b4e39c0b980`.
- The accepted pulse journal is confirmed: attempts `7 -> 6`, cooldown `296s`,
  exactly one Praise transport, action ID
  `nova-praise-a36bddde311fd157d2227705e616c42258c5133a8b53d1ad4d5b9c175d7c8dbe`.
- The live wrapper recorded `maximum_safe_return_inputs` because the settled
  successor was recognized without supplying Home context. The retained
  successor independently localizes as `HOME_LOCALIZED`, confidence
  `0.990524`, residual `0.113707`; a later zero-input observation remains
  fully zoomed out Home at confidence `0.989691`, residual `0.123705`.
- The local handoff defect is repaired and covered by
  `test_return_home_supplies_atlas_context_to_settled_recognition`; the 84-test
  Home/Nova navigation command passes. No second Praise attempt is permitted or
  needed; two of the user's three continuation attempts remain unused.

## Validation closeout
- `tests.test_nova_navigation_canary` plus
  `tests.test_home_atlas_verified_route`: `84` passed after the terminal repair.
- Nova boundary/controller packages: `61` passed.
- Shared-navigation profile: `18` passed, receipt
  `5e4d0504b05c0c188640e0ecc09c8674749778a0f4ce9cdc2fffb245236f51de`.
- Focused profile's `166` tests retain exactly three unrelated baseline
  workflow-metadata failures: stale queue attempt count, stale queue order/count,
  and stale AGENTS wording assertions. No changed production-path test fails.
- Independent r5 review/recheck: no findings after measured Home authority was
  confined to bounded zoom recovery.
