# Current handoff

## Current position

LB-03's Atlas-defined Home entry is live accepted and pushed through `827a85b`. The checkpoint
provides Atlas-wide startup zoom normalization and the demonstrated fractional-anchor ROI rounding
fix. Fresh current-frame geometry and route-owned successor
recognition remain the entry contract.

- Worktree: `C:/tmp/pns-lean-bot-backlog`; branch: `refactor/lean-bot-backlog`.
- Accepted checkpoint: pushed `827a85b` to `origin/refactor/lean-bot-backlog`.
- Old worktree `C:/tmp/pns-supply-depot-one-claim` is untouched; nothing was carried forward.
- The active backlog is above `<!-- ACTIVE_BACKLOG_END -->` in `BACKLOG.md`.
- Windows/BlueStacks first; NAS deferred. Preserve existing explicit gameplay approvals.
- Verification: 488 tests passed, 6 skipped. A zero-input live preflight and two-input Tavern
  navigation canary passed. The service then completed two eligible cycles with 15 inputs,
  four free recruits, verified persistence, and verified Home return after each cycle.
- The soak stopped safely at its four-recruit ceiling after 772.8 seconds. No route fault
  occurred. The user accepted this repeated-cycle result as satisfying LB-03; 1,800 seconds was
  not executed and must not be claimed.
- State is generation16 disabled and unblocked, failures0/max3, next due persisted, with no
  owner/run/input lock. The unresolved startup VIP record is unchanged.
- Evidence: `.local-captures/lb03-live-admission-20260918T224056406651Z/`.
- The accepted follow-up candidate is committed and pushed at `827a85b`.
- LB-04 through LB-08 remain planned and untouched. LB-09 Home/startup contextual popup
  recovery is live-proven from a naturally occurring popup. The separate cooldown-tier loop,
  stale-frame performance issue, ineffective short-pan selection, and lazy Home-analysis cache
  defect are repaired. Tavern/non-Home and post-consumption popup proof remain pending.
- The latest bounded Recruitment route completed with 7 inputs: one effective 92px Home pan,
  Tavern entry, one Basic free recruit, result Close, and verified safe return Home. No popup,
  paid input, duplicate recruit, or scheduler activation occurred.
- Final affected verification ran serially: 163 focused, 10 service/delivery, and 38 integration
  tests passed (211 total). Evidence: `.local-captures/lb09-panfix-rerun-20260919T041106Z/`.
- Do not resume S1c, contact prior agents, or retry the historical Campaign r2 attempt.

## LB-09 pan and successor-analysis repair

The retained 42px drag failure was an unhandled native dead zone, not successful camera motion.
The direct-pan planner now excludes policy candidates below the calibrated 65px effective floor,
selects the next safe viewport, and fails closed instead of reporting an unexecuted residual as a
binding state. A recognized Home frame can now lazily enrich its cached analysis with Atlas
localization when zoom/pan successor verification requires it.

The first post-repair run dispatched one bounded zoom input, then exposed and retained the cache
defect before any pan or recruit. Offline replay of that exact successor produced canonical Home
localization (confidence 0.9903, residual 0.116px). The materially changed rerun completed in
76 seconds with 7/12 inputs, accepted a measured 92px pan, bound Tavern from fresh Atlas geometry
(confidence 0.9968, residual 0.039px), performed one eligible Basic free recruit, and verified
terminal Home. The popup was absent throughout, so this is route/pan proof rather than new
Tavern or post-consumption popup-interruption proof.

## First live attempt — historical

Native preflight looked like Home but classified UNKNOWN; retained Atlas diagnostic raised
OpenCV OutOfMemory on a 16,384,000-byte allocation in 64-bit Python. Cause remained unproven.
One actual service launch then failed ADB readiness: emulator-5554 disappeared before route
creation/input. Parent stop instruction versus launch chronology was not independently resolved.
Main checked one BLOCKED run, zero inputs/actions, generation2 disabled gates, released lease
and empty input lock. Service exited1 after deliberate stop, without restart. State had been
initialized disabled by status; no existing operational database was migrated.
Evidence: `.local-captures/lb02-live/service-attempt-result.json`; retained files unchanged.


## Offline continuation before retry

Historical repair: `scripts/startup_normalization.py` navigation OCR changed only PSM6 to
PSM11. The retained Home frame went from zero to six navigation terms; edge/scene checks,
thresholds, OS/source guards and input protections were unchanged. Both independent Home
classifiers passed. Tavern semantic recognition/preflight still returned UNKNOWN/
`current_source_not_recognized`; no unconditional acceptance or Atlas fallback was added.
Atlas independently accepted fully zoomed-out Home (confidence0.982839, residual0.205928px).

Read-only existing-server inspection found emulator-5554 available, HD-Adb/HD-Player running,
listeners5037/5555; no restart, readiness helper, fresh capture or input. Availability did not
explain the earlier disappearance. OOM cause remains unproven: all30 Atlas references completed,
peak working set388MiB/commit1.12GiB; OpenCV still reported24threads despite the environment
request for1. No SIFT/resource-policy change or verified thread cap followed.

Retained-frame smoke and nine negatives passed; navigation/service-recruitment suites:21 tests.
The protected source hash stayed unchanged; no fixture, operational-state mutation or live
gameplay proof was produced. Only the OCR correction and brief operating notes changed.

## Live retry — attempt 2

One user-requested task subagent used the existing canonical database after verifying the
prior zero-input ADB failure. It cleared that inspected block once and temporarily enabled
only service/Recruitment. No fresh scheduling state or duplicate standalone preflight was used.

The real service connected to `emulator-5554` and `com.global.ztmslg`; Home/Atlas recognition
and navigation succeeded far enough to issue exactly three inputs: zoom out, camera pan,
and Tavern building tap. The next captured frame visibly shows Noah's Tavern / Adv. Recruit,
with the free-single control, but the route rejected it as `unknown_or_stale_noahs_tavern_state`.
Main inspected that frame and the three native dispatch events. No recruit, paid action,
result dismissal or return-Home input followed. Do not claim live cooldown or gameplay success.

Service terminal: BLOCKED, next due null, no verified maintenance transition. Tier values in
the result remain revision-0 `never_observed` defaults, not observed remaining-attempt counts.
Canonical input/action counters remain zero because this native route logs navigation in
its event file; the actual input count for attempt 2 is three, not zero.

Main checked final gates disabled (generation 4), new inspection block retained, null service
lease owner and empty runtime-input lock. `lb02-attempt2` exited code 1 after the first terminal
report, without restart. No additional game inputs, product changes, tests, commit or push.
The prior attempt and offline-continuation evidence remain unchanged.

Latest result: `.local-captures/lb02-live/attempt2-20260915T221754Z/attempt2-result.json`.
It links the service log, native route result/events, final frame and unchanged state paths.
Next correction is Tavern recognition against that retained Advanced recruitment frame;
do not force a recruit or add another live attempt to diagnose it.

## Offline recognizer investigation — after attempt 2

A user-requested scout/task probe reproduced UNKNOWN/STOP on the retained native frame:
header OCR `a 2`, title `AUV. RECPUIL`; fresh observation, no OCR exception, count/free/paid
branch never reached. A grayscale-header plus `auv` alias experiment produced a zero-cost
single decision using the existing one-attempt fallback, but was never applied. Grayscale
alone still failed. Home, missing header/title/free and stale negatives remained non-recruitable;
masking Free while paid10x remained selected another tier. No Basic/Int/cooldown coverage.

Main found crop clipping instead: the old title began at y105, below glyph tops around y90,
and the header included part of that title. Complete header `(180,10,620,60)` and title
`(150,75,650,145)` read correctly with unchanged BGR/3x cubic/PSM6. This superseded new aliases
or grayscale. The comparison used two crop OCR calls, not another full-controller/live run.

Evidence/probes: `.local-captures/lb02-offline-recognition-20260915T223147Z/report.json`,
with adjacent `title-grayscale-comparison.json` and `crop-boundary-comparison.json`.
Original PNG hashes stayed unchanged; no source/test/state/gate/live changes, suite, commit or push.

## Applied crop correction

The user-requested task subagent corrected only the two source ROI constants and a geometry
comment; existing OCR processing and `aqv` normalization remain unchanged. No `auv` alias.
The real retained Advanced frame now yields NOAHS_TAVERN / Adv. Recruit / RECRUIT_FREE,
quantity 1 and cost 0, with zero dispatches. Old ROIs reproduce UNKNOWN. Retained Home and
synthetic missing-header/title/free and stale cases remain non-recruitable; the missing-free
case still sees paid Recruit 10x. A native-coordinate image regression catches the clipping.
Main ran `python -m unittest tests.test_noahs_tavern_recruit tests.test_noahs_tavern_navigation`:
44 tests passed. No directly referenced native Basic/Int/cooldown frames were available.
Evidence: `.local-captures/lb02-crop-fix-20260915T2252Z/probe-results.json`.
The user subsequently reset to Home and authorized attempt 3 below. The UI reset did not reset
persisted cooldown/count state.

## Live attempt 3 and binding diagnosis

Main captured and visually verified native Home, inspected the prior zero-recruit recognition
block, then ran unmodified `AutomationService.serve` with a one-terminal stop callback.
Existing state was reused. Exactly one camera pan occurred; no Tavern tap or recruitment.
The final retained image is visually Home with Tavern visible, but terminal Home was not
programmatically verified. Native stop: `home_atlas_binding_not_proven`; next due remains null.
Both gates are disabled (generation 6), lease owner null, native lock empty; process exited 0,
no restart. Maintenance task state remains empty; canonical consecutive failures is now 3.

Offline replay of the exact final frame: Atlas recognized fully zoomed-out Home, confidence
0.978844, residual 0.253870 px, no ambiguity. `bind_visible_building` then failed its semantic
label predicate after 14 OCR calls. The broad crop includes busy scene; its 80-pixel focused
fallback visibly clips the initial N. Widening alone still failed. Isolating the complete
label line, with unchanged color/resize and existing PSM 13, read `Noah's Tavern`.
Those diagnostic coordinates are not a generalized or applied production fix.

The separate Home classifier's false result was not the final blocker: `_atlas_binding`
does not consult it. Its navigation hits (3) meet threshold; scene hits (1) miss the required 2.
Do not misdiagnose this as failed Atlas localization or bypass the target-label requirement.
Recommend a shared complete-label extraction fix within the projected region, explicit
crop/OCR/failing-predicate diagnostics, and replay across retained camera offsets and negatives.
No additional live input, product changes, tests, commit or push during this attempt/diagnosis.
Evidence: `.local-captures/lb02-live/attempt3-20260915T231940Z/attempt3-result.json`.

## Shared label binding repair — verified offline

The task subagent repaired `tasks/home_atlas_vision.py` and Tavern route diagnostics.
Main caught a Bank regression in the first narrow vertical-band prototype; the final extractor
segments and groups complete glyph lines across the existing projected search region instead.
It uses padded text bounds, strict existing label policy, at most two OCR calls and a 15-second
per-call timeout. The Tavern-specific canonical-text injection was removed, not expanded.

Final native replay: five Tavern frames across three camera positions, plus Bank and Fighter
Camp, bind successfully with current-frame identity and safe target ROIs. Main inspected the
actual extracted crops. Wrong/missing label, wrong profile and ineligible-target cases reject.
Main exercised the actual unified failure path using input-forbidden replay: both JSON and
raised error report `home_atlas_label_not_read`, with raw OCR, bounds and crop artifacts.
Synthetic stale/overlay/ambiguity/frame-mismatch/low-confidence route cases also reject.

Main fixed diagnostic guard ordering so an unavailable native binder rejects before image
processing, propagated the precise exception reason, and removed obsolete error/OCR-mode
assertions without removing blocked/no-input coverage. Final affected suite: 185 tests PASS.
Real-image regressions cover different label identities and positions. No claim of universal
OCR or coverage of every building/UI variant: this remains the locked BlueStacks 800x1280 renderer.

Evidence: `.local-captures/lb02-shared-binding-fix-20260916T003701Z/delivery-result.json`,
including final replay and actual unified-runner proof references. No live input, block
clearance, service start, persisted-state reset, commit or push. Main verified gates remain
disabled at generation 6, prior inspection block/failure count 3 intact, lease/lock empty.

## Live attempt 4 — VIP closed, service not started

User requested a task-subagent retry and reported the idle/reset VIP popup. The existing
shared startup helper is already in this worktree; no old-worktree code was copied.
`recognize_reset_popup` identified exact VIP_POINTS_GET_PTS, body text and literal Close.
The task subagent used the supported recovery/runtime with a one-input cap and fresh
authorization/dispatch captures. Native events contain exactly one navigation-only Close;
no service-route inputs, Tavern entry, recruitment, paid action or cooldown/count update.

The settled native frame shows the popup absent and Home city visible; Main inspected it.
The helper's `recognize_home_nav` template check scored 0.3359435201 against its 0.90 floor.
It therefore persisted `unresolved:unexpected_successor`. This is a different Home predicate
from the earlier OCR/Atlas checks. The repaired building-label binding was not exercised live.
No visual override or second Close was attempted; Recruitment stayed unstarted.

Main independently verified all gates disabled at generation 6, prior Recruitment block and
consecutive failures 3 retained, empty maintenance task state, released service/startup leases,
and empty native input lock. The startup action remains unresolved in
`.local-orchestrator/startup-recovery-actions.sqlite3`; do not erase or re-key it to retry.
The VIP helper process exited 4; the other attempt4 helpers exited 0, all without restart.

Evidence: `.local-captures/lb02-live/attempt4-20260916T012252Z/attempt4-result.json`
and `parent-verification.json` beside it. No product/test changes, test-suite run, commit or push.
Next useful work is offline diagnosis of this exact Home successor/template mismatch, not
another live attempt or a lower threshold without representative negative evidence.

## LB-09 ticket and live attempt 5

User requested the popup interruption ticket, then another live retry. LB-09 is planned in
the active backlog: shared detection/dismissal, separate dismissal and resumption outcomes,
context-aware continuation, stale-target invalidation and no duplicate consuming input.
It was not implemented. The task subagent ran one real service pass from freshly admitted Home,
without repeating VIP Close or requiring the unrelated startup Home-nav template.

After inspection and explicit retry authorization, existing state APIs cleared the repaired
Recruitment binding block and re-armed only consecutive failures from 3 to 0. Historical runs,
max_attempts=3, gameplay state and the prior startup ledger were retained.
The repaired binding accepted Noah's Tavern and opened it. Native events show exactly three
inputs: Tavern entry, free Advanced Recruit 1x, and result Close.

Main inspected the source/result/final images: source has Daily free attempts: 1 and Free
Recruit 1x; result shows Griffin Frag x1; after Close, Advanced shows Free in 1d 23:59:54.
The token balance stays 274. This is visible gameplay/cooldown evidence, not successful
automatic reconciliation. Route stopped at `recruit_postcondition_not_proven`, never returned
Home, reported zero completed recruits, and left maintenance task state empty/next due null.
Returned revision-0 tier values are defaults, not observed remaining free attempts.
The route also reports recruitment_dispatch_count=0/claim_dispatched=false despite the native
free-recruit event. Do not use those flags or canonical zero counters to justify repeating it.

Main independently verified generation-8 service/flow gates disabled, new inspection block
retained, consecutive failures 1, no active run/lease/native lock, and prior VIP action still
unresolved. The operator wrapper hit a closed-database error in cleanup; a bounded finalizer
disabled the gates successfully. All processes exited without restart. Do not reuse that
wrapper unchanged; keep cleanup inside the state lifetime as in the prior safe launcher.

Evidence: `.local-captures/lb02-live/attempt5-20260916T015052776722Z/attempt5-result.json`
and adjacent `parent-verification.json`. No product/test changes, tests, commit or push.
Next is offline investigation of the exact after-recruit verification/accounting failure;
preserve the consumed-attempt evidence and block instead of issuing another free recruit.

## Applied cooldown/free-control repair — verified offline

The timer OCR was correct; permissive matching combined “Free in…” with the paid Recruit 1x
label and fabricated a remaining free attempt. The task subagent repaired
`tasks/noahs_tavern_recruit_vision.py`: exact Free Recruit 1x label, existing purple enabled
evidence and no positive cooldown are required for availability inference. Positive timers
remain active independently of button wording. Explicit counts, including Basic counts, remain.
No OCR aliases, crop changes, lower thresholds or postcondition-verifier changes.

Main replayed the retained native before/reward/after sequence through the real controller:
postcondition accepted, consumed Advanced count and UTC cooldown persisted in temporary SQLite,
restored after reopening, and duplicate Advanced recruitment denied. Unrelated Basic/Int state
was preserved. The screen timer is 172794 seconds; existing persistence uses the full 172800-second
policy interval from verification time. No change to that conservative policy.

Final verification: 72 affected tests PASS, including the real after-close fixture and synthetic
disabled-control, misleading timer, and Basic cooldown/contradictory-label cases. Main required
restoration of the accidentally truncated test tail before acceptance and strengthened the
Basic guard to exercise the recognizer, not preconstructed observations.

Evidence: `.local-captures/lb02-cooldown-control-fix-20260916T022139Z/delivery-result.json`.
Operational rows were unchanged: gates disabled generation 8, prior block/failure count retained,
maintenance still empty and VIP unresolved record preserved. No live retry, commit or push.
Dispatch-accounting flags, operator-wrapper cleanup and LB-09 remain outside this repair.
Native replay establishes the Advanced transition, not live Home return or every tier's imagery.

## Live attempt 6 — Intermediate Nova EXP result rejected

User returned to Home and authorized one full service pass after the cooldown/control repair.
The task subagent used fresh normal Home/Atlas admission, cleared only the inspected previous
block and preserved retry/gameplay facts. No VIP recovery or repeat Advanced recruit occurred.
Native events contain three inputs: one Home camera pan, Tavern entry, and one free Intermediate
recruit. Main inspected the source (Daily free attempts:1, Free Recruit 1x) and result
(5K Nova EXP x1); token balance remains117. Four post-input captures show the identical result.

Exact stop: `RECRUITMENT_REQUIRES_INSPECTION:recruit_result_not_recognized`.
Main's offline replay reads “5K Nova EXP” correctly and detects the Close color/geometry.
`tasks/noahs_tavern_recruit_vision.py` accepts a result only when reward OCR contains “frag”
or “antiserum”; this valid reward fails that predicate and returns UNKNOWN. No result Close,
new cooldown/count projection or Home return occurred. This failed before the repaired
after-close cooldown path, not because that repair rejected a cooldown.

Returned tier values are defaults; maintenance state remains empty. Advanced was not dispatched
again, but its cooldown was not observed/persisted in this run. Preserve both consumed free
attempts and do not trust zero completed/dispatch counters as permission to repeat them.
Main verified all gates disabled generation10, failures2/max3, new block retained, no active
run/service lease/native lock, and prior VIP unresolved action preserved. `lb02-attempt6`
exited0 without restart or cleanup error.

Evidence: `.local-captures/lb02-live/attempt6-20260916T024024482907Z/attempt6-result.json`,
with adjacent `parent-verification.json` and `result-recognition-diagnosis.json`.
No product/test changes, test suite, commit or push. Next repair is result recognition coverage
against retained valid rewards and wrong-screen negatives; no automatic fix-and-live-retry.

## Prior offline verification

Passed: 120 focused tests across service integration, CLI, handlers, canonical/legacy scheduler,
native runtime, and recruitment/navigation/delivery modules. The guarded scenario executes the
real unified runner and controller with scripted recognition/transport: Basic recruit, Home return,
600-second cooldown, restart and later eligibility, Basic midnight rollover with Int./Advanced
cooldowns retained, second-owner refusal, idle/emergency stop, and stop after consuming input.
Also reproduced/fixed reopening matured persisted tiers whose unopened tabs have no visible count.
Home localization allocation errors retain diagnostics and block without further input.

Guarded configured-CLI smoke: disabled state remained disabled, zero device-connection attempts,
signal handlers restored, ownership released. CLI `serve --help` also ran. No full suite or live
operation. Python 3.12 lacked OpenCV; verification used the existing Python 3.9 environment.
Synthetic navigation tests were isolated from real SIFT after allocation failures; one obsolete
conductor wiring test was removed. Final 120-test run passed with `OPENCV_FOR_THREADS_NUM=1`.

Runtime path: `cli.main` -> `AutomationService.serve` -> `UtcPulseCoordinator` ->
`RecruitmentExecutionHandler` -> `run_noahs_tavern_unified_recruitment` ->
`NoahTavernIntegratedRoute`. Ordinary inputs retain session ownership. The existing flow block
marks an interrupted/uncertain pass until inspection; successful canonical terminal projection
clears it. Cooldowns wait outside Tavern. See `docs/automation-service.md` for invocation/limits.

## Reward-independent completion — offline

Task subagent implemented the scoped contract; Main completed integration and verification.
Close uses literal label OCR inside the existing red control, only with pending free context,
and is issued once. Fresh same-tier cooldown proves consumption; remaining count comes from
the authorized source, not result text, quest progress or the post-screen counter.
Native Nova and reward-erased Nova now reach Close. Retained Advanced before/result/after
passes with temporary SQLite persistence/restart; synthetic Basic4->3 and Int1->0 also pass.
78 affected tests pass, including service execution/restart without device transport.
Generation10 gates, inspection block, consumed-attempt evidence and operational state unchanged.
No live capture/input, operational reconciliation, dispatch-accounting change or LB-09 work.
Evidence: `.local-captures/lb02-cooldown-success-contract-20260916T025512Z/delivery-result.json`.

## Successful live pass — attempt7

Same task subagent ran one authorized service pass from user-reported Home. Six native inputs:
Tavern entry, Basic free, Close, Int tab, Adv tab, safe Back. Main saw Maverick Frag x1,
Basic Free in00:09:56, Int22:40:28, Adv1d21:50:02 and settled Home. No Int/Adv recruit repeated.
Scheduler invocation persisted Basic daily count1/remaining4 and all three deadlines;
next due2026-09-16T04:11:47.161664Z. Cached Int/Adv counts1 are not observed free availability.
The scheduler's generic Home/action-total fields are not completion proof; route/events are.
One launcher failed before service import (operator.py shadowed stdlib); corrected launch exited0.
Main verified generation12 gates disabled, failures0, no lease/input lock/active run and unchanged
VIP unresolved record. No product changes/tests; no later-due live pass or unattended proof.
Evidence: `.local-captures/lb02-live/attempt7-20260916T035700Z/attempt7-result.json`
and adjacent `parent-verification.json`.

## LB-03 Atlas-defined Home entry — live results

The pushed `bc93ea7` cutover separates interaction anchors from camera-placement anchors and
removes building-name OCR from Home-entry authority. The follow-up candidate centralizes
bounded startup zoom normalization for Home/world-Atlas flows and corrects an off-by-one
fractional-anchor ROI rejection demonstrated by the first live canary. The combined affected
suite passed 488 tests with 6 skipped.

A zero-input live preflight localized canonical Home at 0.991 confidence and bound Tavern.
The subsequent navigation-only canary performed exactly Tavern entry and safe return, accepted
the Tavern successor, verified terminal Home, and issued zero recruit inputs.

The supervised service soak completed two eligible Recruitment cycles with natural cooldown
waiting. Native events contain 15 inputs and exactly four free recruits. Both cycles used fresh
Atlas binding, persisted verified cooldown/count state, and returned to Home. The first cycle
performed one bounded Atlas pan and recruited Advanced, Basic and Intermediate; the second
waited for Basic eligibility and recruited Basic once. No paid or duplicate recruit occurred.

The configured four-recruit ceiling stopped the process after 772.8 seconds, before the
1,800-second deadline. The user accepted this successful repeated-cycle evidence as LB-03 live
closure. It is not a completed 1,800-second prolonged soak. Cleanup left service and
Recruitment disabled and unblocked at generation16, failures0/max3, next due persisted, no active run/lease/input lock,
and the startup VIP unresolved record unchanged. Evidence:
`.local-captures/lb03-live-admission-20260918T224056406651Z/`.

Limitations: full 1,800-second duration, real night/day transition, and live Supply/Nova or
other-building entry remain unproved. The accepted checkpoint is pushed.

## LB-09 live verification — Home context proven, route blocked

`docs/lb09-contextual-popup-recovery-design.md` records the frozen store-free contextual VIP
helper, its tri-state dismissal/absence/readiness result, one-Close session bound, fresh-target
revalidation, route-scoped action keys, and Recruitment accounting. The helper and Recruitment
integration are committed at `36e7af0`. The active route
owns successor recognition; startup Scarlett/commercial handling and the unresolved startup VIP ledger
remain isolated.

The implementation covers the phase-aware `pending_action_key`/`pending_result` contract,
stale-command invalidation, safe-return re-observation, and navigation-versus-recruitment
accounting. Independent helper, accounting, integration, and route reviews passed after the
safe-return stale-Back finding was repaired. Offline verification passed: the focused command
passed 135 tests with 1 skipped, and the additional changed-route command passed 50 tests.
Python compilation and `git diff --check` passed; Python LSP was unavailable. These are focused
checks, not a full-suite result.

A naturally occurring exact `VIP_POINTS_GET_PTS` popup covered Home. The route dispatched one
route-scoped contextual Close, captured a fresh popup-free recognized Home frame, reconciled
`popup_dismissed_resume_ready`, recomputed Atlas entry, entered Tavern, and performed exactly one
Basic free recruit plus its normal result Close and verified cooldown. No duplicate recruit or
startup-ledger mutation occurred.

The broader pass is not accepted: it then alternated Int./Advanced tier selections even though
each selected tier showed cooldown, reached the existing 12-input ceiling, and stopped in Tavern
without a terminal Home return. No retry ran. Service/Recruitment remained disabled at generation
16 with no active run, lease, or runtime-input lock. Tavern/non-Home and post-consumption popup
recovery remain unproved. Evidence:
`.local-captures/lb09-live-canary-20260919T021900Z/live-verification.json`.

## Existing machine-readable state

The structured shape remains for existing consumers; legacy names do not reinstate ceremony.
Current enablement/ownership below was checked after the bounded LB-03 service soak stopped.
Static canonical registration was not changed. The legacy `production_registration` field
retains the unchanged JSON-registry posture (`NOT_REGISTERED`), not the canonical service
registry. Offline fixtures and retained live evidence remain distinct.
<!-- CURRENT_HANDOFF_STATE_BEGIN -->
{
  "schema_version": 3,
  "branch": "refactor/lean-bot-backlog",
  "head_binding": "5c8431e8c4502a8df57b734137b967c05540ffa8",
  "last_product_candidate_head": "827a85b8e685bc15aaf03c559a5a7df66718d876",
  "ahead_behind": {
    "source": "compute_from_git"
  },
  "attributable_dirty_paths": [
    "BACKLOG.md",
    "CURRENT_HANDOFF.md",
    "docs/lb09-contextual-popup-recovery-design.md"
  ],
  "task_start_worktree": {
    "tracked_dirty_paths": [
      "AGENTS.md",
      "BACKLOG.md",
      "CURRENT_HANDOFF.md",
      "docs/backlog-task-contract.md"
    ],
    "protected_untracked_paths": []
  },
  "protected_user_owned_paths": [
    "Stop-PnS-OMP.ps1",
    ".local-captures/",
    ".local-reference/",
    "evidence/"
  ],
  "current_task_id": "LB-09",
  "current_task_state": "home_context_live_proven_route_passed",
  "next_task_id": "LB-09",
  "next_task_activation_status": "non_home_popup_proof_waits_for_natural_occurrence",
  "active_task_or_flow": "LB-09 contextual VIP popup recovery",
  "active_delivery_stage": "live_route_passed",
  "active_execution_manifest_path": null,
  "development_lease_state": "absent",
  "runtime_ownership_state": "none",
  "writable_agent_state": "none",
  "unresolved_action_state": "startup_vip_action_unresolved_preserved",
  "latest_focused_validation_result": "PASS: 211 serialized affected tests (163 focused + 10 service/delivery + 38 integration); Python compilation and git diff --check pass; not a full-suite result",
  "latest_architecture_validation_result": "PASS: independent helper, accounting, integration, and route reviews; safe-return stale-Back finding repaired; startup VIP ledger and native/route accounting remain isolated",
  "latest_full_suite_result": "PASS: 488 tests, 6 skipped",
  "current_live_attempt_state": "route_completed_popup_absent",
  "current_evidence_or_session_reference": ".local-captures/lb09-panfix-rerun-20260919T041106Z/noahs-tavern-unified-recruitment-20260919T041110785460Z/unified-recruitment-result.json",
  "last_safe_completed_step": "Bounded Recruitment route completed one Basic free recruit and verified terminal Home after measured Atlas pan progress",
  "exact_next_permitted_action": "No further live input is required; checkpoint the repaired route while preserving pending non-Home popup proof",
  "current_blocker": "non_home_and_post_consumption_popup_proof_pending",
  "prohibited_repeated_action": "Do not repeat consumed recruits before recognized eligibility, trust generic zero counters over native evidence, reset gameplay state or retry automatically; preserve VIP unresolved record",
  "stage_revision": "lb09-home-context-live-proven-route-passed",
  "stage_type": "live_verification",
  "product_precondition": "met",
  "failure_class": "none_current_route",
  "budgets": {
    "stage_revisions_used": 0,
    "managed_turns_used": 0,
    "live_attempts_used": 11,
    "runtime_inputs_used": 46
  },
  "retained_terminal_disposition": {
    "task_id": "runtime-reliability-stage-10-phase-5-campaign-ap-r2",
    "state": "blocked_evidence_required",
    "evidence_or_session_reference": ".local-captures/development-sessions/CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY-20260826T214745064655Z",
    "no_retry_disposition": "Historical occurrence remains closed; no identical retry authorized"
  },
  "registration_and_scheduler": {
    "production_registration": "NOT_REGISTERED",
    "scheduler_enabled": false,
    "active_runtime": "none"
  },
  "journals_and_lease": {
    "development_lease_status": "absent",
    "active_prepared_input_sent_unresolved_action_ids": [
      "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE:startup-recovery:vip-reset-close:694e10fd13a56b5e"
    ],
    "historical_journals": "retained_immutable"
  },
  "evidence": {
    "evidence_requirement": "HOME_CONTEXT_PROVEN_ROUTE_PASSED_NON_HOME_POPUP_PENDING",
    "evidence_requirement_reason": "Natural Home popup recovery is proven and the repaired popup-free Recruitment route completed with terminal Home; Tavern/non-Home and post-consumption popup recovery remain unproved.",
    "active_evidence_manifest": ".local-captures/lb09-panfix-rerun-20260919T041106Z/noahs-tavern-unified-recruitment-20260919T041110785460Z/unified-recruitment-result.json",
    "monitoring_issue": "none in latest bounded run; exact popup remained absent",
    "do_not_recursively_inspect_parent_evidence_tree": true
  },
  "control_owner": "parent_agent",
  "control_parent_conversation_id": "lean-recruitment-service",
  "deferred_independent_review": "Independent helper, accounting, integration, and route reviews passed after the safe-return stale-Back repair; no further mandatory review",
  "stage_7_ordered_plan": [],
  "next_three_atomic_tasks": [
    "Checkpoint the repaired bounded route without additional live input",
    "Preserve the exact-popup-only contract and existing startup VIP ledger",
    "Collect Tavern/non-Home or post-consumption popup proof only when it occurs naturally"
  ],
  "latest_live_validation_result": "PASS: 7/12 inputs; measured 92px Home pan, fresh Tavern Atlas binding, one Basic free recruit, result closure, and verified terminal Home; exact VIP popup absent"
}
<!-- CURRENT_HANDOFF_STATE_END -->
