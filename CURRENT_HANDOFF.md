# Current runtime-proof handoff

## 2026-07-13 GnBots static-reference Phase A

- `.local-reference/` is excluded only in `.git/info/exclude`; it remains read-only, unstaged, and
  unavailable to production runtime.
- `docs/research/gnbots_trial_reference_manifest.md` and `.json` normalize relevant flows across all
  12 authorized modules with stable IDs, both source xywh and normalized xyxy ROIs, matcher
  settings, waits, swipes, loop bounds, recovery/completion semantics, direct/inferred status,
  unresolved helpers, and vendor weaknesses.
- No vendor JavaScript, binary, service, selector, or PNG was executed or promoted.
- `tests.test_reference_manifest` passes 5 tests, including exact ROI endpoint normalization and
  production dependency rejection.
- Phase A passed. Next unblocked item is Phase B coordinate calibration. Existing Personal Might,
  popup, backlog, handoff, tests, and retained evidence changes remain preserved.

## 2026-07-13 Personal Might Praise popup binding correction

- The narrow `PersonalMightPraiseHandler`, named route contracts, reset-time popup dismissal
  route, checked-in `pnsctl run-task --task praise` registration, and exact Daily Quest Claim
  reconciliation contracts are implemented and pass focused offline validation.
- Fresh runtime evidence positively recognized the logged-in reset popup as `Get Pts` with
  `Log in every day to get VIP pts`. Review showed the prior ROI `(200,590)-(440,710)` and
  tap `(320,650)` were above the actual Close button, over streak text. Correct visual binding
  is button ROI `(260,750)-(540,870)`, OCR `Close` bounds `(363,795)-(436,817)`, proposed
  center `(400,810)`.
- One prior navigation-only `DISMISS_RESET_POPUP` transaction was authorized and dispatched
  exactly once at the misbound ROI. Immediate and three post frames were identical; it was
  reconciled as proven no-effect in
  `evidence/sessions/20260713-personal-might-praise/live-popup-unresolved-005/`.
- Corrected live attempt used detected button bounds `(277,767)-(523,847)` and one tap at
  `(400,807)`. Mandatory full-frame artifact passed, including literal `Close`, title/body
  identity, interior margin, center-y gate, and old-point negative. Dispatch succeeded and the
  operator directly confirmed the popup disappeared. Executor failed to classify the resulting
  startup surface, so retained action `reset-popup-close-1783994269-2` still records unresolved;
  no second Close tap was sent.
- Phase 1 is live-confirmed by direct observation; journal reconciliation remains required.
  Phase 2 started from the retained Speedup Help surface but stopped after two equivalent
  `normalize-alliance-to-home` failures: first source target recognition failed; after binding
  the fixed-profile Back ROI to positive Speedup Help identity, immediate revalidation cancelled
  with `OVERLAY_STATE_CHANGED` before transport. No Praise or Claim input occurred. Evidence:
  `evidence/sessions/20260713-personal-might-praise/live-corrected-popup-006/`. Task worker and
  private task ADB were removed; VM remains running, backup intact, and no task listener remains.
  Phase 2 blocker evidence is retained in `live-phase2-route-007/` and `live-phase2-route-008/`.

## 2026-07-13 Alliance Help semantic correction

- The historical `(641,302)` action targeted the upper row-level button labeled Help at
  `(556,274)-(727,330)`. Its correct semantic kind is `ALLIANCE_HELP_ONE`; the visible request
  disappeared, proving one individual request was processed. Historical SQLite and screenshots
  remain immutable.
- Actual `ALLIANCE_HELP_ALL` is a separate lower-screen target at `(277,1188)-(523,1268)`, center
  `(400,1228)`. Code requires the literal Help All identity/template plus enforced lower-screen,
  separation, clipping, and interior-tap geometry. A candidate near `(641,302)` is denied.
- The Help allies catalog row is `LIVE_VALIDATED` for both individual Help and the actual lower
  Help All control.
- The actual lower action `alliance-help-1783986842` passed the pre-dispatch artifact and sent
  exactly one tap at `(400,1228)`. The first post frame positively contains the transient exact
  message `No help request currently`; later frames returned to Speedup Help. The immutable source
  journal is retained and the reconciled copy is confirmed with zero unresolved/nonterminal actions.
- MVP-QUEST-TO-CLAIM remains Blocked; no Claim or Daily Quest completion is proven, and
  M6-DQ-TRANSITION-CORPUS remains downstream.

## 2026-07-13 live Daily Quest inventory and unresolved Alliance Help action

- The current run used the selected Daily Quest gate and a complete bounded overlapping-scroll
  inventory. The list contained no ordinary Claim row. It included the exact Help allies row at
  0/10; other rows were upgrades, training, combat, stamina/AP, gathering, purchases, research,
  enhancements, donation, Supply Depot, or other unsupported/strategic actions. Full inventory and
  frame provenance are retained in
  evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/.
- Help allies Go was used only as navigation and its destination was corrected from a temporary
  Cash Mall-first classifier to ALLIANCE using the retained post OCR: Alliance coin header,
  Daily reset time 19:00:00, the Build Lv.20 Gas Field request, and Help 0/30. No purchase
  control was touched.
- The first supported task handler is AllianceHelpHandler, committed in c1b32e7. Reset
  reconciliation assigned daily-2026-07-13 outside the configured guard. One exact zero-cost Help
  action was authorized and dispatched exactly once at (650,350). The immediate post-dispatch
  frame remained Help 0/30, so the expected positive postcondition was not proven and
  alliance-help-20260713-001 is unresolved. No retry or further input was sent.
- The unresolved journal state is intentionally preserved. The lease was released only after
  journal reconciliation; the task worker and task ADB server were removed afterward. The game
  remains on Alliance Help so the unresolved live evidence is not destroyed. No Claim input,
  objective completion, spend, account, combat, or OS input occurred.

Recorded: 2026-07-13, America/Chicago

## 2026-07-13 live continuation

- The focused typed-task refactor is committed in `e24b304`, with the local Quest successor
  correction in `1c87219`; the fixed-profile navigation contract remains local-ROI based and does
  not require whole-frame equality.
- The fresh continuation started from the approved private unprivileged worker. One verified
  promotional Back reached Home/Base, Home→Quest and Quest→Daily each dispatched once and were
  confirmed from fresh local-ROI successor evidence without retry, and two bounded Daily Quest
  list swipes were dispatched through the safe-action executor.
- Daily Quest was positively recognized, but current points/reset text was not readable enough to
  assign a current `game_day_id`. The visible objectives were Vehicle Depot upgrade, Ultimate
  Challenge, Hunt Zombie, Train Fighter, Own Lv.211 Hero, Gathered Food, and Attack a player's
  Headquarters and win. None is a supported zero-cost R1 handler, and no ordinary Claim row,
  Alliance Help objective, or explicitly free Supply Depot objective was present. No Go or Claim
  input occurred. MVP remains Blocked.
- The live schema-v1 journal is retained at
  `evidence/sessions/20260712-mvp-quest-to-claim/live-20260713/actions.sqlite3`; all actions are
  terminal, with zero unresolved/nonterminal records and a released lease. The task worker and
  its ADB server were removed after evidence preservation; the game was force-stopped; no task
  listener or tunnel remains; the VM is running and RT-017 is intact.
- Full dependency-complete offline validation is 96 passing tests. RT-019 and all six promoted M6
  assets remain passing. Details are in
  `evidence/sessions/20260712-mvp-quest-to-claim/live-continuation-20260713.md`.

## 2026-07-13 selected Daily-tab correction and retest

- The false-positive Main Quest/Daily Quest classification is corrected by `4f26889`: selected
  Daily recognition now requires the selected-tab state and an explicit Main Quest negative.
- The first live retest proved a separate target defect: the old broad tab ROI centered the tap at
  `(400,190)`, below the live tab label. The screen stayed Main Quest; the navigation-only record is
  retained as a no-effect unresolved navigation record, not an unresolved consequential action.
- `f3373f8` tightened the fixed-profile Daily-tab target to `(300,70,500,140)`, center `(400,105)`.
  A new journaled Quest→Daily action dispatched exactly one tap at `(400,105)` and positively
  confirmed the selected Daily Quest successor. No Daily Quest rows or objectives were inspected.
- Fresh retest evidence and schema-v1 database are retained in
  `evidence/sessions/20260712-mvp-quest-to-claim/live-selected-tab-retest-20260713/`. The full
  offline suite is 100 passing tests; RT-019 and all six M6 assets pass.
- Cleanup completed: game force-stopped, task worker removed, lease released, no task listener or
  tunnel remained, VM running, and RT-017 intact. The pre-existing ADB daemon was not killed or
  recreated.

## Current milestone and task state

- Milestones: M6 Production corpus — In Progress; M7 Deterministic service core — In Progress.
- Current task: MVP-QUEST-TO-CLAIM — Blocked after the 2026-07-13 live inventory selected the
  exact Help allies zero-cost R1 candidate but its first Alliance Help transaction remained
  unresolved after one dispatch. The action journal requires manual positive reconciliation before
  any later consequential input. No Claim row was present, no quest completion was proven, and no
  Claim input occurred. The typed navigation/task-module contracts remain local-ROI based; the
  AllianceHelpHandler is the first narrow supported handler. M6 and overall M7 remain In Progress.

- Independent later task: RT-016A — Pending; stable redacted account/server identity evidence is absent and remains required for M7-AccountGuard, not RT-013.
- RT-013 dependency: `RT-012 → RT-013`.
- Tasks completed in the preceding M5 run: M5-CUSTOM-BASELINE passed with 100 replay
  capture/classification operations, 25 target annotations, 10 OCR operations, ten gesture mocks,
  and five reconnect mocks; M5-AIRTEST and M5-MAA were rejected early with no live operations.
  M5-DECISION passed and authorized M6 corpus work. Earlier completed boundaries remain
  authoritative: RT-012, RT-013, RT-017, RT-019, RT-021, and MVP-STARTUP-NORMALIZATION.
- Tasks completed in this M6 boundary: M6-DQ-BOOTSTRAP passed. Fresh final-runtime Home/Base,
  Quest, and Daily Quest reconciliation frames, six profile-compatible assets, scroll overlap
  evidence, fail-closed synthetic fixtures, and cleanup evidence are retained. No Claim, Go,
  quest-completion, spend, or consequential gameplay input was recorded.
- Task completed in this repository-only M7 boundary: M7-SAFE-ACTION-CORE passed with no Unraid,
  VM, ADB, game, container, tunnel, or runtime-network access. Synthetic executor-success inputs
  were test-only and no production Claim-positive asset was created.
- Promotional escape review and live blocker evidence: `evidence/sessions/20260712-mvp-quest-to-claim/promotional-escape/`;
  the retained top-up frame passed the isolated arrow detector offline at similarity `0.898225`.
  The later bounded run sent one verified Back tap, reconciled Home/Base, then cancelled Home→Quest
  before dispatch on source change. No Claim-positive asset was created.
- Current MVP attempt evidence: `evidence/sessions/20260712-mvp-quest-to-claim/`. The schema-v1 task database
  has no nonterminal/unresolved action and its lease is released. The game is force-stopped, task
  worker/ADB/image removed, VM running, and RT-017 intact. The pre-existing loopback 5037 daemon
  was present initially but absent at final verification; no public listener exists.

## Repository state

- Branch: `main`.
- Latest completed implementation boundary: `1c87219`
  (`fix(tasks): use local Quest successor anchors`), following `e24b304` and `8483981`.
  The previous startup boundary was `d6fd1c7` (`fix(startup): accept bounded promotional successors`), following `5cec210`
  (`fix(startup): allow bounded verified promotional back`). The MVP closure remains task-scoped; the
  pre-existing unstaged entries remain untouched and no unrelated path is staged.
- Prior relevant policy/dependency commit: `7c932d2` (`docs(policy): remove risk acknowledgment gate`).
- The completed guarded keyguard branch, live-validation evidence, final Home/Base candidate, and
  passed task decision are included in the task-scoped closure boundary.
- RT-020 is removed from the committed backlog and plan; do not recreate it.
- Current dependency graph: `RT-012 → RT-013`; `RT-016A → M7-AccountGuard → later unattended automatic gameplay`; RT-014A is optional and does not delay RT-013.

## Runtime and rollback state

- VM: dedicated `PnS-BlissOS-PoC`, selected VirtIO(3D)/Mesa VirGL profile, running.
- Game: remains on the Alliance Help screen because the unresolved Help action evidence must be preserved; no further input is authorized.
- ADB: the task worker and its task ADB server were removed after evidence preservation; the approved pre-existing loopback daemon at 127.0.0.1:5037 was left untouched. No external tunnel or public/published listener remains.
  RT-021 direct worker proof used a temporary UID-65534 host-network container with an isolated
  local ADB server port; all RT-021 containers and that port were removed afterward.
- Observer: temporary container `rt012-observer-20260711-1519` and host collector completed and were removed/stopped after evidence preservation.
- Supervisor: completed normally at 2026-07-12 00:19:36 America/Chicago.
- VM autostart: disabled.
- Android startup state: resumed observe-only capture found the known safe launcher surface with
  `showing=false`, `secure=false`, and `mInputRestricted=false`. No additional keyguard swipe or
  HOME input was sent. The game reached Cash Mall, received exactly one authorized back-arrow tap,
  reached positively recognized Home/Base, and was force-stopped during cleanup.
- Read-only Unraid reconciliation on 2026-07-12 confirmed the VM is `running`, autostart is
  disabled, no RT-012/MVP/observer container or related process remains, the RT-017 backup
  directory/qcow2 remains present, and no temporary 5038/5040/5555 listener remains. The game is
  force-stopped during M6 cleanup. Fresh M6 reconciliation confirmed Android boot complete,
  logical `800x1280`, density 160, nonblocking keyguard, and the game activity foreground before
  cleanup. The exited M6 workers were inspected, their evidence preserved, and removed; only the
  pre-existing loopback ADB server on `127.0.0.1:5037` remained, with no external tunnel or
  published listener.
- Rollback: RT-001 baseline XML, disk identity, graphics rollback, and boot-state evidence remain retained; no disk replacement or destructive VM storage action occurred.

## Evidence

- RT-011: `evidence/sessions/20260711-rt-011-restart-matrix/` — passed restart matrix.
- RT-012 preflight and live evidence target: `evidence/sessions/20260711-rt-012-observe-soak/`.
- RT-012 prior blocker: `evidence/sessions/20260711-rt-012-soak-auth-block/record.md`.
- Live cache-backed evidence: `/mnt/cache/puzzle-survival-runtime/rt012/20260711-rt-012-observe-soak/`.
- RT-012 result: 48 valid, non-black `800x1280` frames; zero ADB failures; p95 capture 222.764 ms; 48 host metric files; 38,374,564 bytes under quota.
- Cash Mall reference: `evidence/sessions/20260711-rt-012-observe-soak/cash-mall-startup-reference.png`.
- RT-013 decision: `evidence/sessions/20260711-rt-013-runtime-decision/record.md`; preflight:
  `evidence/sessions/20260711-rt-013-runtime-decision/preflight.md`.
- RT-019 preflight: `evidence/sessions/20260711-rt-019-runtime-profile-manifest/preflight.md`.
- RT-019 decision/evidence: `evidence/sessions/20260711-rt-019-runtime-profile-manifest/record.md`.
- Runtime profile: `runtime-profile/manifest.json`; profile ID
  `pns-blissos-poc-virgl-800x1280-v1`; canonical hash
  `195c145e5779b13d1f65708a6b3ef31f6cbdb934b33854f886f1091aa583d742`.
- RT-021 preflight: `evidence/sessions/20260711-rt-021-worker-vm-adb/preflight.md`.
- RT-021 decision/evidence: `evidence/sessions/20260711-rt-021-worker-vm-adb/record.md`.
- RT-017 preflight: `evidence/sessions/20260711-rt-017-runtime-backup/preflight.md`.
- RT-017 decision/evidence: `evidence/sessions/20260711-rt-017-runtime-backup/record.md`.
- Startup-normalization: `evidence/sessions/20260711-mvp-startup-normalization/record.md`; fresh
  worker cache copies are under `remote-cache/20260711-keyguard-reconcile-observe-2055/`,
  `remote-cache/20260711-cash-mall-observe-2120/`, and
  `remote-cache/20260711-cash-mall-input-2125/`.
- Resumed startup preflight: `evidence/sessions/20260711-mvp-startup-normalization/preflight-resume.md`.
- Resumed decision: `evidence/sessions/20260711-mvp-startup-normalization/record.md` final
  criterion review; Home/Base candidate manifest is
  `evidence/sessions/20260711-mvp-startup-normalization/home-base-candidate-manifest.json`.
- No RT-016A identity-evidence directory exists yet because its required manual identity exposure has not occurred.
- M5 custom baseline: `evidence/sessions/20260712-m5-custom-baseline/`; benchmark JSON records
  100 replay operations, 25 target annotations, 10 OCR calls, ten gesture mocks, five reconnect
  mocks, and the retained RT-010/RT-021 transport facts.
- M5 Airtest: `evidence/sessions/20260712-m5-airtest/`; early rejection records absent module/CLI,
  official dependency surface, missing central policy adapter, zero live operations, and the
  identical-corpus non-viability decision.
- M5 MaaFramework: `evidence/sessions/20260712-m5-maa/`; early rejection records absent
  native/package adapter, official native/pipeline surface, missing central policy adapter, zero
  live operations, and the identical-corpus non-viability decision.
- M5 final decision: `evidence/sessions/20260712-m5-decision/`; custom stack selected, rejected
  candidates compared, M6 authorized within scope, and no M6/Daily Quest work started.
- M6-DQ-BOOTSTRAP preflight and historical blocker: `evidence/sessions/20260712-m6-dq-bootstrap/preflight.md`.
- M6-DQ-BOOTSTRAP retained bootstrap captures, replay, and transport blocker:
  `evidence/sessions/20260712-m6-dq-bootstrap/`; final-runtime Daily Quest frames and
  `runtime-transport-blocker.md` are retained. The passed asset manifest, current reconciliation,
  scroll fingerprint, synthetic fixture results, and cleanup evidence are retained in the same
  directory.
- M7-SAFE-ACTION-CORE: `evidence/sessions/20260712-m7-safe-action-core/`; preflight, schema and
  lifecycle design, 44-test result, crash-boundary matrix, fixture review, and criterion decision
  are retained there.

## Blocker and required user action

1. `MVP-QUEST-TO-CLAIM` remains Blocked because the short Help All validation did not prove
   Daily Quest progress or produce a Claim row. The historical `alliance-help-20260713-001`
   tap at `(650,350)` was a proven-no-effect mistarget in the separate operational copy; its
   original journal remains immutable historical evidence.
2. No unresolved or nonterminal action remains in the reconciled operational journal, and no
   further consequential input is authorized until a fresh Daily Quest observation establishes
   current progress and an eligible objective or Claim row. Do not retry the historical tap.
3. Resume with the checked-in `scripts/pnsctl.py` interface, fresh runtime/profile reconciliation,
   and the existing single-objective MVP boundary. `M6-DQ-TRANSITION-CORPUS` remains downstream.
4. No credentials, login, tutorial, account switching, CAPTCHA, or profile navigation may be
   automated. RT-016A remains a separate later manual-only account-guard task.


## Facts that must not be re-tested

RT-001 through RT-013 are passed and their retained evidence is authoritative unless contradictory
evidence is discovered. Do not repeat the graphics, display, ADB-isolation, capture,
input-fidelity, restart-matrix, or four-hour observe-only experiments, and do not run RT-014A
concurrently with any live runtime task. RT-019 and RT-021 are also closed; do not rerun the
profile-validator or worker-path trials without contradictory evidence.
