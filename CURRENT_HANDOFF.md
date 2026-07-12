# Current runtime-proof handoff

Recorded: 2026-07-11, America/Chicago

## Current milestone and task state

- Milestone: M3 Direct Bliss runtime proof — Passed; downstream post-selection gates are pending.
- Current task: RT-017 — Passed; RT-013, RT-019, and RT-021 passed, and the secured backup and
  offline restore validation are complete.
- Independent later task: RT-016A — Pending; stable redacted account/server identity evidence is absent and remains required for M7-AccountGuard, not RT-013.
- RT-013 dependency: `RT-012 → RT-013`.
- Tasks completed during this run: RT-012 passed; RT-013 passed with Bliss selected; RT-019
  passed with the versioned runtime profile; RT-021 passed with direct worker/reconnect evidence;
  Cash Mall startup behavior recorded as a stable runtime fact.

## Repository state

- Branch: `main`.
- Latest committed boundary before RT-017 closure: `6d4773c` (`task(RT-021): prove Unraid worker
  ADB path`). The RT-017 task-scoped commit closes the current boundary.
- Prior relevant policy/dependency commit: `7c932d2` (`docs(policy): remove risk acknowledgment gate`).
- Working tree contains the RT-012 evidence/observer implementation, Cash Mall documentation, and this handoff.
- RT-020 is removed from the committed backlog and plan; do not recreate it.
- Current dependency graph: `RT-012 → RT-013`; `RT-016A → M7-AccountGuard → later unattended automatic gameplay`; RT-014A is optional and does not delay RT-013.

## Runtime and rollback state

- VM: dedicated `PnS-BlissOS-PoC`, selected VirtIO(3D)/Mesa VirGL profile, running.
- Game: force-stopped after RT-012 rollback; no gameplay input automation enabled.
- ADB: private NAS-local ADB server remains loopback-only; RT-012 connection disconnected and no
  external tunnel is active. RT-021 direct worker proof used a temporary UID-65534 host-network
  container with an isolated local ADB server port; all RT-021 containers and that port were
  removed afterward.
- Observer: temporary container `rt012-observer-20260711-1519` and host collector completed and were removed/stopped after evidence preservation.
- Supervisor: completed normally at 2026-07-12 00:19:36 America/Chicago.
- VM autostart: disabled.
- Android startup state: after the RT-021 guest restart, the non-secure keyguard remained showing
  (`mIsSecure=false`, `mInputRestricted=true`) after the approved dismissal sequence; no credential
  action was attempted. Game is force-stopped. RT-017 preserved this no-input state.
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
- No RT-016A identity-evidence directory exists yet because its required manual identity exposure has not occurred.

## Exact blocker and required user action

1. No current RT-012 or RT-013 execution blocker; the supplied password was used only in
   process-local environment state and is not retained.
2. RT-016A remains a later manual-only account-guard task. If performed, manually navigate the already-provisioned authenticated game to expose numeric player/account and server/state identity, retaining only minimum redacted or access-restricted evidence. Do not automate login, credentials, account switching, tutorial, CAPTCHA, or profile navigation.

## Exact next command

Begin MVP-STARTUP-NORMALIZATION preflight. Use the presumptive Python/direct ADB/OpenCV stack;
keep the game force-stopped until the offline/observe-only gates pass, and stop for any secure
credential or unresolved OS/keyguard state.

## Facts that must not be re-tested

RT-001 through RT-013 are passed and their retained evidence is authoritative unless contradictory
evidence is discovered. Do not repeat the graphics, display, ADB-isolation, capture,
input-fidelity, restart-matrix, or four-hour observe-only experiments, and do not run RT-014A
concurrently with any live runtime task. RT-019 and RT-021 are also closed; do not rerun the
profile-validator or worker-path trials without contradictory evidence.
