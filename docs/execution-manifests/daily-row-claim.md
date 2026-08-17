# Daily Row Claim execution manifest

## Task ID and objective
- Task ID: `daily-row-claim`
- Flow ID: `DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`
- Manifest state: `CLAIM_PACKAGE_ACCEPTED_PREPARE_ADMITTED`
- Frozen repository candidate: `main@324d80badfa76ad3d1031b797dc600fcde8e6b40`
- Corrected freeze UTC: `2026-08-16T22:06:31.525Z`
- Objective: acquire current local-BlueStacks ordinary Daily row evidence, then deliver one exact free row-local Claim without registering or scheduling the handler.

## Execution routing and timing
- Host: `cursor`
- Parent conversation ID: `4caa8e49-ddb7-46dd-9cd9-d012c79fed47`

| Role | Exact model slug | Agent/session ID | Started UTC | Completed UTC | Usage-event UTC |
| --- | --- | --- | --- | --- | --- |
| `architecture_planner` | `gpt-5.6-sol-high` | `cursor-parent-4caa8e49-ddb7-46dd-9cd9-d012c79fed47` | `2026-08-16T21:47:52.176Z` | `2026-08-16T22:06:31.525Z` | `2026-08-16T21:47:53.879Z`; `2026-08-16T21:58:27.052Z`; `2026-08-16T22:03:52.371Z`; `2026-08-16T22:04:57.748Z`; `2026-08-16T22:05:16.632Z` |
| `execution_coordinator` | `gpt-5.6-luna-xhigh` | `not assigned` | `not started` | `not completed` | `not used` |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | `dba5cab5-8ce2-4525-ab52-50c4f6540f6b` | `not recorded` | `not recorded` | `pending exact match` |
| `independent_tester` | `gpt-5.6-terra-high` | `b40ecfb5-d3bf-49b9-9717-80ca76d292f6` | `not recorded` | `not recorded` | `pending exact match` |
| `escalation_architect` | `gpt-5.6-sol-medium` | `fbd0edc2-aea7-45af-be8c-d868a8925d6a` | `2026-08-16T21:53:24.225Z` | `2026-08-16T21:55:12.297Z` | `2026-08-16T21:54:02.016Z` |

## Frozen architecture decision
- The current active-development and canary target is the private local BlueStacks instance, package `com.global.ztmslg`, using the checked-in native `800x1280` profile and exact allowlisted local serial.
- Bliss is the later porting and deployment-acceptance target. It is not a prerequisite or substitute for this BlueStacks flow.
- The earlier Bliss-only bootstrap decision and escalation result are superseded by the user's runtime-phase clarification.
- Work remains evidence-first. The first runtime action is one receipt-bound zero-input observation through the existing local BlueStacks development-session command. No implementation change or Claim dispatch is authorized before that observation.
- The exact frozen reconnaissance command is:
  `python scripts/pnsctl.py development-session observe --max-inputs 0 --delegated-receipt <RECEIPT_DB> --agent-identity <LUNA_AGENT_ID> --task-id daily-row-claim --flow-id DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION --scenario selected-daily-row-evidence --variant ordinary-row`
- The command must consume a `reconnaissance` receipt, acquire and release singleton ownership, dispatch zero inputs, capture one current native BlueStacks frame, and retain a bound result and terminal summary.
- The bounded observer repair passed 47 delegated receipt/catalog tests and the five-test focused profile. Independent Terra High review and parent integration acceptance found no material defect.
- One receipt-bound zero-input observation completed against the clean committed candidate. It retained a native `800x1280` BlueStacks frame, dispatched zero inputs, and released ownership.
- The retained frame is Home, not the selected Daily screen and not an ordinary ready row. This revision therefore stops `EVIDENCE_REQUIRED` without navigation, Claim behavior, or retry.
- The user subsequently authorized end-to-end continuation. The next atomic stage is a newly frozen two-input navigation-only reconnaissance route; this supersedes the consumed zero-input stop without authorizing Claim behavior.
- The exact frozen reconnaissance command is:
  `python scripts/pnsctl.py development-session daily-row-reconnaissance --max-inputs 2 --delegated-receipt <RECEIPT_DB> --agent-identity <LUNA_AGENT_ID> --task-id daily-row-claim --flow-id DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION --scenario selected-daily-row-evidence --variant home-quest-daily`
- The route starts only from a fresh native Home frame that spatially binds the bottom `Quest` control, revalidates immediately before dispatch, taps it once, positively recognizes the Quest screen and its top `Daily` tab from the successor frame, revalidates that exact tab immediately before one second tap, and then captures the selected-Daily terminal frame.
- Recognition must use current-frame native geometry and spatial OCR/visual semantics. Bliss templates and retained coordinates alone cannot authorize either tap.
- The route has no swipe, Back, Claim, reward, resource, purchase, combat, registration, scheduler, or recovery authority. Any unrecognized source, target, successor, overlay, stale frame, transport ambiguity, or non-Daily terminal state stops `evidence_required` without retry.
- Legacy `run-task daily-claim` remains unauthorized because it can dispatch Claim and is not delegated-receipt-bound.
- If the observed frame is not the selected Daily screen with one fully visible ordinary ready row, stop `evidence_required`. Do not add navigation or Claim behavior under reconnaissance authority.
- After accepted source evidence exists, the parent must freeze the evidence-bound implementation revision before assigning Claim code. That revision will preserve `AvailableDailyClaimObservation` as the domain contract, require independent current-frame row/target geometry and a same-objective successor, and reject synthetic references as live provenance.
- The eventual free Claim is an `ordinary_development` zero-cost reward claim. Claims do not use a consequential-action lifecycle; combat dispatch and real-money confirmation remain the only consequential classes.

## Reused foundations and dependency check
- Reuse the accepted selected-Daily inventory and game-day/reset identity from `DQ-FOUNDATION-DAILY-INVENTORY`.
- Reuse the offline authorization and postcondition structure in `tasks/available_daily_claim.py`.
- Preserve the accepted exact Personal Might Claim path; it does not authorize generalized Claim geometry.
- Preserve the delegated receipt controller and zero-input ownership-release contract.
- Current authority remains `EVIDENCE_REQUIRED`, `NOT_REGISTERED`, scheduler-ineligible, composition-blocked, and M6-inactive.
- The queue remains non-active because its Daily Row Claim entry is blocked on fresh source/target/successor evidence.

## Frozen reconnaissance-repair writable paths
- Production: `scripts/pnsctl.py`
- Tests: `tests/test_delegated_runtime_receipts.py`
- The repair must rewrite retained terminal artifacts fail-closed after any post-capture failure and validate the retained frame hash, receipt/result bindings, zero counts, terminal status, and ownership release before recording success.
- The fallback artifact-write regression is repaired: durable `evidence_required` terminal recording now precedes fallible fallback artifact persistence.
- Repair budget: two of three repair turns used; the repair package is tester-accepted and parent-accepted.
- No runtime access is authorized during the repair.
- Queue, catalog, matrix, policy, registry, registration, scheduler, composition, M6, and Bliss state remain unchanged.
- `scripts/flow_delivery_control.py` and all other production/test paths remain excluded.

## Frozen bounded-navigation reconnaissance writable paths
- Production: `scripts/pnsctl.py`
- Production: `scripts/daily_row_claim_bluestacks.py`
- Tests: `tests/test_daily_row_claim_bluestacks.py`
- Tests: `tests/test_delegated_runtime_receipts.py`
- The implementation may add only the dedicated receipt-bound `development-session daily-row-reconnaissance` command and the two-step local BlueStacks navigation recognizer/controller.
- It must retain the source, immediate-before, Quest successor, Daily immediate-before, and selected-Daily terminal frames; record every action and semantic result; and durably record terminal `observed` or `evidence_required` after singleton release.
- It must not register the flow runner, alter the queue/matrix/catalog, implement Claim recognition or dispatch, add scrolling, or broaden any shared navigation authority.
- Validation accepted: 57 package tests passed; the focused five-test profile passed with receipt digest `5600942762cd365d99679014acafc9d8fe13c81a1fd6ddc680c5cca03d774658`.
- Independent Terra High recheck accepted with no material findings after repair of full-frame modal rejection and durable failure-record ordering. Parent integration acceptance is `accepted`.
- The first accepted live reconnaissance consumed receipt `e9653d82-a3f9-4a7d-ae5c-c562a76f5525` and dispatched one navigation tap. Immediate post evidence remained positively Home; no Quest transition occurred, no second input was sent, and ownership released.
- The retained immediate-before binding was `(204,1194,439,1280)`, whose center `(321,1237)` lands on the bottom label band rather than the visible Quest icon/control body. This is a safe no-effect with a materially new geometry hypothesis, not authority for an identical retry.
- One bounded repair may adjust only the Home Quest binding to include the current-frame icon/control body above the OCR label while retaining OCR spatial association, full-frame overlay rejection, fresh revalidation, and all existing receipt limits. It must add an independent regression proving the dispatched point lies in the icon/control band and not the clipped label band.
- After two rejected geometry hypotheses, escalation architect `e4555491-3fee-4e40-a725-709dc1faf9b8` froze a current-frame supported-point contract. OCR must uniquely establish `Quest` and its immediate neighboring bottom-navigation labels; their current centers define the Quest ownership lane and a label-relative icon band.
- The binding must use an original, non-morphology-created visual support mask. Components may structure candidates, but dispatch authority comes only from a maximum-clearance point whose complete `3x3` neighborhood is supported in that original mask. The target ROI is exactly the odd-sized `3x3` box around that point, so the unchanged runtime center dispatch lands on proven pixels rather than a contour or label-relative bounding-box center.
- Reject absent adjacent labels, neighboring-lane distractors, boundary-touching/broad/background components, insufficient clearance, morphology-only bridges, and equally valid components. Record the label ROI, ownership lane, icon band, component ROI, selected point, clearance, and raw-support verdict. Immediate-before recognition recomputes the entire contract.
- The supported-point implementation passed 66 package tests and the five-test focused profile with receipt digest `819fc3ad8e13bdf2a2e286e8ef705febedc07254b8c9e4a6404bd9d3e3722cf7`. Independent Terra High review `43a864ab-bbdf-462e-8fbe-28890af820cb` accepted with no material findings, and parent integration acceptance is `accepted`.
- Fresh receipt `5dd7d35b-cb70-4261-a26f-f993e33300e7` sent zero inputs because its source frame was already the Main Quest screen, not Home. The retained native frame positively shows `Quest`, selected `Main Quest`, unselected `Daily Quest`, and ordinary quest rows.
- This proves the earlier Home tap did transition successfully after the route's single immediate-post capture. The prior `unknown_successor` was premature sampling, not a failed transport. The supported-point target was not dispatched in the zero-input run and remains accepted offline.
- The route must now support bounded no-input successor polling after Home→Quest and a separately receipt-bound Quest→Daily continuation from this proven intermediate state. Polling may capture fresh frames for a bounded timeout but may not dispatch another Home tap.
- Exact continuation command:
  `python scripts/pnsctl.py development-session daily-row-reconnaissance --max-inputs 1 --delegated-receipt <RECEIPT_DB> --agent-identity <LUNA_AGENT_ID> --task-id daily-row-claim --flow-id DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION --scenario selected-daily-row-evidence --variant quest-daily-continuation`
- The continuation receipt permits only action identity `quest-daily-tab`, class `navigation`, one total input, zero resource inputs, and zero combat confirmations. It starts only from a positively recognized Main Quest frame, revalidates the current Daily tab immediately before dispatch, taps once, and polls without further input until selected Daily is positively recognized or the bounded timeout expires.
- Continuation/polling validation accepted: 74 package tests passed; the focused five-test profile passed with receipt digest `8f5d2f64d1396ad98c7d223761ba1def1155ab8a7d8941081c63b7159d975fea`. Independent Terra High review `8cf20171-989e-4b33-8e42-891fc334321b` found no material defect, and parent integration acceptance is `accepted`.
- Receipt `d7e12b72-121a-48ff-a8fc-717f2e90e3d0` sent zero inputs because Tesseract did not extract the stylized top `Quest` title. The same current native frame reliably extracted spatially associated `Daily` + `Quest`, `Alliance` + `Activity`, and `Recom'd` semantics, and independently bound the Daily tab.
- One bounded recognition repair may replace the brittle title-only gate with current-frame Quest-page semantics requiring the Daily Quest tab pair, Alliance Activity tab pair, and recommendation/list context in their expected relative layout. It must remain negative for unrelated screens, selected Daily, missing/fragmented tab pairs, overlays, and out-of-layout text. The Daily target remains OCR-derived and immediately revalidated.
- The repaired continuation passed 81 package tests and the five-test focused profile with receipt digest `5e0879e445fa9c365c0f89d04f201d50997fe25b2b6c55125e8e974175ece727`. Independent Terra High recheck `2e730112-4980-4f42-a4d6-60b375618089` accepted with no material findings, and parent integration acceptance is `accepted`.
- Receipt `3715f787-11f2-4ba2-8048-dc9f098c6797` dispatched exactly one `quest-daily-tab` input and retained selected-Daily terminal frame `runtime/daily-row-reconnaissance-20260816T233831898689Z/frames/0007-quest-daily-tab-poll-04.png`, SHA-256 `7bc93840435f41d274b7b6b12fa863df9d0789924545ef614178b8a62d8882f6`. Ownership released; no resource or combat input occurred.
- Parent visual inspection accepts that native `800x1280` frame as selected Daily source evidence. It shows Daily Quest points `0`, a positive reset timer, and three fully visible ordinary ready rows with row-local Claim controls.
- The evidence-bound implementation target is the second visible row only: catalog objective `consume_stamina`, displayed `Consume 20 Stamina (36/20)`, reward `Pts +5`. Progress authorization is `current >= required`, not exact equality. The first Zombie Lair row and third Speedup row are excluded from this canary.
- The implementation must dynamically rebind the selected Daily state, exact catalog objective text, progress, ordinary row panel, row-local Claim control, points, and reset timer from the current native frame. It must reject Main, milestone chests, `Go`, clipped rows, adjacent Claim controls, duplicate objective candidates, overlays, nonzero/unknown cost surfaces, and any mismatch with `consume_stamina`.
- Before Claim dispatch, a receipt-bound zero-input prepare mode must retain the raw native frame, source hash, independently measurable row bounds, Claim ROI, OCR/visual semantics, game-day/reset identity, and an annotated full-frame overlay. Parent must visually accept that overlay. Prepare authority cannot dispatch.
- Exact prepare command:
  `python scripts/pnsctl.py development-session daily-row-claim --mode prepare --max-inputs 0 --delegated-receipt <RECEIPT_DB> --agent-identity <LUNA_AGENT_ID> --task-id daily-row-claim --flow-id DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION --scenario consume-stamina-row-claim --variant consume-stamina-prepare`
- Canary mode may then consume one canary receipt bound only to action identity `daily-row-claim:consume_stamina`, action class `reward_claim`, consequence class `ordinary_development`, one total input, zero resource inputs, and zero combat confirmations. It must recapture and revalidate immediately before transport and reserve before dispatch.
- Exact canary command:
  `python scripts/pnsctl.py development-session daily-row-claim --mode canary --max-inputs 1 --delegated-receipt <RECEIPT_DB> --agent-identity <LUNA_AGENT_ID> --task-id daily-row-claim --flow-id DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION --scenario consume-stamina-row-claim --variant consume-stamina-canary`
- Success requires an immediate selected-Daily successor proving the same `consume_stamina` row no longer has a ready Claim or Daily Quest points increased by exactly `5`. Unchanged/ambiguous/wrong-objective successors remain `evidence_required`; no retry.
- The exact canary tightens this to selected Daily under the same displayed-countdown-derived reset identity and an independently parsed Daily Quest points increase of exactly `5`; row disappearance or OCR absence alone is diagnostic and never success.
- Validation accepted: 112 affected package tests passed; the focused nine-test profile passed with receipt digest `d3b58ad94c9ab85e35413938c4745de3738415c5237c2c2ebb4bbc91400088f0`. Independent Terra High recheck `f3f6404d-0ce5-44bb-b090-e892681c695a` accepted with no material findings, and parent integration acceptance is `accepted`.
- Prepare receipt schema integration accepted: the neutral inert binding is `daily-row-prepare-observation` / `observation` under max inputs `0`; the old identity containing `claim` is forbidden. The affected suite passed 115 tests and focused validation passed 9 with digest `6b55f7c410a26503644bc16bf45dbc5e5d92e464a94778938dccbe8e21d13d1b`; Terra recheck `70ba550e-a061-49ad-9181-a8d3556b3dc4` and parent integration both accepted.

## Deferred evidence-bound implementation paths
These paths are candidates only and are not writable under `FROZEN_RECONNAISSANCE`:
- `tasks/available_daily_claim.py`
- `scripts/flow_delivery_daily_row_claim_bluestacks.py`
- `scripts/pnsctl.py`
- `tasks/flow_delivery_bluestacks_registry.json`
- `tasks/gameplay_flow_contracts/DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION.json`
- `tests/test_available_daily_claim.py`
- `tests/test_gameplay_flow_contracts.py`
- `tests/test_flow_delivery_daily_row_claim.py`
- `tests/test_daily_row_claim_bluestacks.py`

## Frozen evidence-bound Claim writable paths
- Production: `tasks/available_daily_claim.py`
- Production: `scripts/daily_row_claim_bluestacks.py`
- Production: `scripts/pnsctl.py`
- Production: `scripts/bluestacks_native_runtime.py` only for a backward-compatible optional delegated action-class parameter on `tap`; default behavior remains navigation.
- Tests: `tests/test_available_daily_claim.py`
- Tests: `tests/test_daily_row_claim_bluestacks.py`
- Tests: `tests/test_delegated_runtime_receipts.py`
- Tests: `tests/test_bluestacks_native_runtime.py`
- No flow registry, queue, catalog, matrix, scheduler, composition, M6, or registration mutation is authorized.

## Required states and transitions
- Reconnaissance: `FROZEN_RECONNAISSANCE_REPAIR -> OBSERVER_REPAIRED -> TESTER_ACCEPTED -> PARENT_INTEGRATION_ACCEPTED -> RECONNAISSANCE_RECEIPT_ISSUED -> ZERO_INPUT_OBSERVED -> SOURCE_EVIDENCE_ACCEPTED`.
- Evidence negative: any wrong profile, package, dimensions, receipt binding, ownership state, missing frame/result/summary, or non-selected-Daily frame transitions to `EVIDENCE_REQUIRED`.
- Later implementation revision: `SOURCE_EVIDENCE_ACCEPTED -> OFFLINE_IMPLEMENTED -> TESTER_ACCEPTED -> PARENT_INTEGRATION_ACCEPTED -> CANARY_ADMITTED`.
- Later canary: `READY_TO_CLAIM -> CLAIM_DISPATCHED_ONCE -> CLAIMED_OR_POINTS_INCREASED -> TERMINAL_DAILY_SELECTED`.
- Any stale target, Main tab, incomplete or clipped row, `GO`, milestone chest, adjacent control, overlay, reset ambiguity, unknown cost, nonzero cost, wrong quantity, unchanged successor, wrong objective, transport ambiguity, or missing immediate postcondition stops fail-closed without identical retry.

## Persistence and idempotency
- Reconnaissance receipt result identity: `daily-row-claim:reconnaissance:selected-daily-row-evidence`.
- Future Claim reservation key: `daily-row-claim:<game_day_id>:<objective_key>:claim`.
- Establish the game-day identity once per development session and bind all future source and successor evidence to it.
- Reserve any future Claim before dispatch and reconcile only from the immediate semantic successor. An unknown result does not reopen the one-Claim budget.

## Acceptance checks
- The existing observation command is present only under `development-session` and requires all delegated receipt bindings.
- It consumes only a `reconnaissance` receipt with `max_total_inputs=0`, zero resource-affecting inputs, and zero combat confirmations.
- It may use only the checked-in local BlueStacks ADB executable and exact allowlisted private serial through `pnsctl`; it cannot dispatch tap, swipe, key, text, shell-input, Claim, purchase, resource, march, or combat actions.
- It validates `com.global.ztmslg` and native `800x1280` on local BlueStacks before retaining `observe.png`.
- It retains source SHA-256, result identity, `result.json`, `summary.json`, zero input count, terminal status, and proven singleton release.
- It rereads and validates retained evidence before terminal success and leaves fail-closed artifacts after any post-capture, checkpoint, or ownership-release failure.
- It does not mutate `BACKLOG.md`, `CURRENT_HANDOFF.md`, `tasks/flow_delivery_queue.json`, registration, scheduling, composition, M6, BlueStacks configuration, Bliss configuration, or unrelated Git state.
- Existing delegated-receipt and zero-input observation tests are the acceptance basis for this unchanged command.

## Safety limits
- Allowed now: one offline bounded implementation in the frozen bounded-navigation reconnaissance allowlist.
- Allowed only after focused checks, independent Terra High acceptance, parent integration acceptance, and a clean frozen candidate: one reconnaissance receipt with exactly two navigation identities (`home-quest-entry`, `quest-daily-tab`), `max_total_inputs=2`, zero resource inputs, and zero combat confirmations.
- Disallowed outside the one accepted receipt: navigation, Claim binding or dispatch, queue activation, registration, scheduling, direct ADB outside `pnsctl`, ad hoc remote shell, Bliss access, and evidence fabrication.
- Reconnaissance live budget: one Home-to-Quest-to-Daily run, two navigation inputs, zero resource-affecting inputs, zero combat confirmations.
- Future Claim budget: not authorized by this revision.
- Real-money Cash Mall confirmation is unsupported.

## Validation commands
- `python -m unittest tests.test_daily_row_claim_bluestacks tests.test_delegated_runtime_receipts tests.test_catalog_and_pnsctl`
- `python -m unittest tests.test_delegated_runtime_receipts tests.test_catalog_and_pnsctl`
- `python scripts/run_flow_delivery_validation.py focused --flow-id DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`
- Shared-navigation validation is required only if a later evidence-bound revision changes navigation.
- Full repository discovery remains manual-only.

## Evidence references
- Reused offline contract: `tasks/available_daily_claim.py`
- Reused selected-Daily authority: `tasks/daily_quest_execution_matrix.json`
- Reused exact Personal Might proof references are listed in the execution matrix and are not generalized target proof.
- Required new reconnaissance evidence: one current local BlueStacks `observe.png`, its SHA-256, delegated receipt/result binding, terminal `result.json`, terminal `summary.json`, and ownership release.
- Retained negative reconnaissance evidence: `.local-captures/development-sessions/delegated-e35dba54-4f14-4c51-900e-d8c2081bdecc/observe.png`, SHA-256 `d44e79eefc47b261f1c490bb3686a44097b422f0500ff967fdb09a9630760729`; receipt `e35dba54-4f14-4c51-900e-d8c2081bdecc`, digest `09d67380eb6a1e99a78d6d9783eead55037131f23120be070de14d775880da4f`; zero inputs; ownership released; native frame visually confirmed as Home.
- Required later source ground truth: native source frame, source hash, row bounds, Claim ROI, annotated full-frame source, nearby objective/progress semantics, runtime profile, and game-day identity.
- Required later successor proof: immediate post frame showing the same objective row no longer ready/visible or a positive Daily points delta.

## Milestones
- Architecture frozen: `yes`
- Offline implemented: `yes` (observer repair and bounded navigation reconnaissance)
- Tester accepted: `yes` (observer repair and bounded navigation reconnaissance)
- Live proven: `no`
- Merged: `no`
- Registration state: `NOT_REGISTERED`
- Scheduler eligibility: `false`

## Escalation conditions
- The approved plan is contradictory or incomplete.
- A genuinely new architecture decision is required.
- Safety authority is ambiguous.
- Tester and implementation evidence conflict.
- Two materially different repair hypotheses fail.
- Live evidence disproves the accepted design.
- Ordinary test failures, syntax errors, and known repairs do not escalate.

## Stop conditions
- Stop repairs after tester acceptance or after the third total repair turn. A fourth repair requires explicit user authorization, a refrozen manifest, a compact handoff, and a fresh execution chat.
- Stop or refreeze from retained evidence if the one two-input reconnaissance does not positively reach selected Daily with a fully visible ordinary ready row; do not retry identically.
- Stop before any Claim implementation until the parent freezes the evidence-bound revision.
- Stop after any unknown runtime, ownership, transport, evidence, or semantic result; do not retry identically.

## Next authorized action
- Commit the accepted Claim package locally without push, issue one exact zero-input prepare receipt, run prepare once, and visually inspect the annotated immediate source before any canary receipt.
