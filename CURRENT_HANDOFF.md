# Current runtime-proof handoff

Recorded: 2026-07-12, America/Chicago

## Current milestone and task state

- Milestone: M5 Framework bake-off — Passed.
- Current task: M5-DECISION — Passed; custom Python/direct ADB/OpenCV/local OCR selected. Final
  decision evidence is under `evidence/sessions/20260712-m5-decision/`. M6 production corpus is
  Ready but was not started in this run.
- Independent later task: RT-016A — Pending; stable redacted account/server identity evidence is absent and remains required for M7-AccountGuard, not RT-013.
- RT-013 dependency: `RT-012 → RT-013`.
- Tasks completed during this run: M5-CUSTOM-BASELINE passed with 100 replay
  capture/classification operations, 25 target annotations, 10 OCR operations, ten gesture mocks,
  and five reconnect mocks; M5-AIRTEST and M5-MAA were rejected early with no live operations.
  M5-DECISION passed and authorized M6 corpus work. Earlier completed boundaries remain
  authoritative: RT-012, RT-013, RT-017, RT-019, RT-021, and MVP-STARTUP-NORMALIZATION.

## Repository state

- Branch: `main`.
- Latest committed boundaries before final M5 closure: `efd7aef` (`task(M5): reject MaaFramework
  adapter`), `d74d345` (`task(M5): reject Airtest adapter`), `d7cbca5` (`task(M5): benchmark
  custom control stack`), and `70efbfd` (`task(MVP): automate guarded startup normalization`).
  The M5-DECISION task-scoped closure is the final commit of this run; no unrelated path is
  staged.
- Prior relevant policy/dependency commit: `7c932d2` (`docs(policy): remove risk acknowledgment gate`).
- The completed guarded keyguard branch, live-validation evidence, final Home/Base candidate, and
  passed task decision are included in the task-scoped closure boundary.
- RT-020 is removed from the committed backlog and plan; do not recreate it.
- Current dependency graph: `RT-012 → RT-013`; `RT-016A → M7-AccountGuard → later unattended automatic gameplay`; RT-014A is optional and does not delay RT-013.

## Runtime and rollback state

- VM: dedicated `PnS-BlissOS-PoC`, selected VirtIO(3D)/Mesa VirGL profile, running.
- Game: force-stopped after one explicitly authorized supervised no-spend startup tap; no
  unattended gameplay input automation is enabled.
- ADB: the documented NAS-local ADB server remains loopback-only and idle with no attached device
  in the 2026-07-12 read-only query; no external tunnel or temporary worker ADB server is active.
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
  force-stopped by retained RT-021/MVP cleanup evidence; no attached device was available for a
  current package query, so no new live command was issued.
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

## Exact blocker and required user action

1. No current blocker. M5 passed without new live input, Airtest and MaaFramework were rejected
  early without package or runtime mutation, and the resumed startup-normalization MVP previously
  passed with no additional keyguard swipe, exactly one supervised no-spend back-arrow tap,
  positive Home/Base, and cleanup.
2. RT-016A remains a later manual-only account-guard task. If performed, manually navigate the
   already-provisioned authenticated game to expose numeric player/account and server/state
   identity, retaining only minimum redacted or access-restricted evidence. Do not automate login,
   credentials, account switching, tutorial, CAPTCHA, or profile navigation.

## Exact next command

The next ready milestone is M6 production corpus capture/selection using the selected custom
stack. Do not start M6 or Daily Quest in this completed M5 run; the next task must create a fresh
M6 preflight and final-runtime corpus plan.

## Facts that must not be re-tested

RT-001 through RT-013 are passed and their retained evidence is authoritative unless contradictory
evidence is discovered. Do not repeat the graphics, display, ADB-isolation, capture,
input-fidelity, restart-matrix, or four-hour observe-only experiments, and do not run RT-014A
concurrently with any live runtime task. RT-019 and RT-021 are also closed; do not rerun the
profile-validator or worker-path trials without contradictory evidence.
