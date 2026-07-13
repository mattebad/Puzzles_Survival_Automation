# Current runtime-proof handoff

Recorded: 2026-07-12, America/Chicago

## Current milestone and task state

- Milestones: M6 Production corpus — In Progress; M7 Deterministic service core — In Progress.
- Current task: MVP-QUEST-TO-CLAIM — Blocked at the Daily Quest reset-boundary guard. The offline
  freshness correction passed, and the resumed run safely confirmed Cash Mall→Home,
  Home→Quest (including positive exact-asset reconciliation), and Quest→Daily navigation. The
  current Daily Quest screen had six Go controls, no Claim, zero points, and reset time `00:08:33`,
  so the run stopped before scrolling or selecting a prerequisite. One pixel-identical static
  immediate frame was cancelled before dispatch and led to a capture+OCR timestamp-binding fix;
  65 tests pass. Frame age starts at successful monotonic capture completion;
  proposal/dispatch limits are 3.0/2.0 seconds, exact critical-ROI reuse is fail-closed, and two
  pre-dispatch attempts are audited within one prepared action. No prerequisite, Go,
  quest-completion, spend, or Claim input occurred. M6 and overall M7 remain In Progress. The
  retained purchase/top-up surface now has an offline escape-only classifier: only an independently
  verified isolated game Back arrow can authorize `SAFE_PROMOTIONAL_BACK`, with explicit forbidden
  regions, bounded successors, and a three-action limit. The complete offline suite is 78 tests.
- Latest resumed read-only reconciliation at remote time `2026-07-12T20:31:08-05:00` found an
  already-running task-scoped post-reset worker and resumed game activity, but the fresh
  `800x1280` frame was a purchase/top-up surface. Daily Quest recognition abstained, so the new
  game day/reset state could not be assigned. No lease, journal action, transport call, or game
  input occurred. The inspected worker/image were removed after preserving identity/log/activity
  evidence; the game was force-stopped and no task listener/tunnel remained. Details are in
  `evidence/sessions/20260712-mvp-quest-to-claim/reset-reconciliation-20260712.md`.
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
- Promotional escape review evidence: `evidence/sessions/20260712-mvp-quest-to-claim/promotional-escape/`;
  the retained top-up frame passed the isolated arrow detector offline at similarity `0.898225`. No
  live input or runtime access occurred during this implementation boundary.
- Current MVP attempt evidence: `evidence/sessions/20260712-mvp-quest-to-claim/`. The schema-v1 task database
  has no nonterminal/unresolved action and its lease is released. The game is force-stopped, task
  worker/ADB/image removed, VM running, and RT-017 intact. The pre-existing loopback 5037 daemon
  was present initially but absent at final verification; no public listener exists.

## Repository state

- Branch: `main`.
- Latest completed implementation boundary: `5bf6e54`
  (`fix(M7): calibrate pre-dispatch freshness`). The MVP closure remains task-scoped; the
  pre-existing unstaged entries remain untouched and no unrelated path is staged.
- Prior relevant policy/dependency commit: `7c932d2` (`docs(policy): remove risk acknowledgment gate`).
- The completed guarded keyguard branch, live-validation evidence, final Home/Base candidate, and
  passed task decision are included in the task-scoped closure boundary.
- RT-020 is removed from the committed backlog and plan; do not recreate it.
- Current dependency graph: `RT-012 → RT-013`; `RT-016A → M7-AccountGuard → later unattended automatic gameplay`; RT-014A is optional and does not delay RT-013.

## Runtime and rollback state

- VM: dedicated `PnS-BlissOS-PoC`, selected VirtIO(3D)/Mesa VirGL profile, running.
- Game: force-stopped after three resumed supervised no-spend navigation taps; no
  unattended gameplay input automation is enabled.
- ADB: the task-scoped loopback server was stopped and no 5037/5042/5555 listener remains; no
  external tunnel or temporary worker ADB server is active.
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

1. MVP-QUEST-TO-CLAIM remains blocked by the reset/game-day reconciliation and the latest unknown
   purchase/top-up surface. Resume only after fresh startup observation positively recognizes a
   safe canonical screen and the post-reset game day. No in-game user action is required. RT-016A
   remains a later manual-only account-guard task. If performed, manually navigate the
   already-provisioned authenticated game to expose numeric player/account and server/state
   identity, retaining only minimum redacted or access-restricted evidence. Do not automate login,
   credentials, account switching, tutorial, CAPTCHA, or profile navigation.

## Exact next command

Resume `MVP-QUEST-TO-CLAIM` after a fresh safe-screen and reset/game-day reconciliation with the
corrected freshness contract. Do not begin M6-DQ-TRANSITION-CORPUS; the required completed/unclaimed
and Claim transition evidence does not exist.

## Facts that must not be re-tested

RT-001 through RT-013 are passed and their retained evidence is authoritative unless contradictory
evidence is discovered. Do not repeat the graphics, display, ADB-isolation, capture,
input-fidelity, restart-matrix, or four-hour observe-only experiments, and do not run RT-014A
concurrently with any live runtime task. RT-019 and RT-021 are also closed; do not rerun the
profile-validator or worker-path trials without contradictory evidence.
