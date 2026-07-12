# RT-013 final Bliss runtime decision — Passed

Recorded: 2026-07-11, America/Chicago

## Decision

Bliss Passed as the final technical runtime for the Puzzles & Survival proof-of-concept.

The selected runtime is the dedicated `PnS-BlissOS-PoC` VM using the validated VirtIO(3D)/Mesa
VirGL profile, the effective `800x1280` portrait capture profile, private ADB containment, and
the already-provisioned authenticated game package. RT-012 completed the required four-hour
Unraid-local observe-only gate. No contradictory evidence was found in the earlier passed gates
or the retained RT-012 anomalies.

This is a technical runtime selection. It does not authorize login, account switching, server or
state selection, profile navigation, purchases, or unattended gameplay. Post-selection work is
authorized only through the separately scoped RT-017, RT-019, RT-021, and later task-specific
promotion gates.

## Dependency and scope review

- RT-001 through RT-011: passed retained evidence; no contradictory evidence discovered.
- RT-012: Passed, complete four-hour Unraid-local observe-only soak.
- RT-016A: intentionally not required for RT-013; remains the later manual-only M7-AccountGuard
  identity-evidence task.
- RT-014A: optional private viewer transport proof; not a runtime-selection blocker.
- RT-015: deferred VM autostart/worker-order documentation; no host reboot is authorized here.
- RT-019: full versioned runtime-profile manifest/schema is a separate downstream task and is not
  recreated in this decision record.

## Criterion matrix

| Runtime-selection criterion | Decision | Retained evidence and rationale |
|---|---|---|
| Bliss installation, Play/game compatibility, ABI support, and package launch | Passed | RT-001 baseline and RT-003 retained Bliss OS 16.9.7 GApps/Android 13, game package `com.global.ztmslg` version `7.0.278`, ARM/ABI compatibility, and successful authenticated game rendering. |
| Authenticated-session persistence without a runtime hard stop | Passed | RT-003, RT-007, RT-011, and RT-012 show the provisioned game surface without login, tutorial, CAPTCHA, wrong-account, state/server-selection, or session-loss prompts. No credential or account operation was automated. |
| Reversible graphics configuration | Passed | RT-003/RT-004/RT-005 prove the VirtIO(3D)/Mesa VirGL candidate and a boot-tested QXL/SwiftShader rollback. Candidate XML and baseline XML hashes are retained. |
| Accelerated renderer and host GPU behavior | Passed | RT-003/RT-004 prove Mesa VirGL/OpenGL ES 3.2, Intel UHD 770 Render/3D correlation, safe sampled temperatures, and no sampled GPU reset. RT-012's empty live `intel_gpu_top` payload is retained as a measurement limitation, not a contradictory renderer result. |
| Unattended boot entry | Passed | RT-006 records three unattended cold boots using the saved VirGL entry and retains the no-hardware rollback boot. |
| Effective display profile | Passed | RT-007 records physical `1280x800`, logical `800x1280`, density `160`, effective portrait orientation, stable system bars/viewport, and three corrected guest-restart trials. The global rotation-lock limitation and rollback commands are explicit. |
| Private ADB boundary | Passed with limitation | RT-008 proves the guest endpoint is reachable through private libvirt networking and the approved host path, with no host/LAN `:5555` listener or public exposure. Bliss reports `ro.adb.secure=0`; containment, not protocol authentication, is the accepted boundary. |
| Input coordinate fidelity | Passed for the tested non-game surface | RT-009 proves 9 taps and 4 swipes before and after guest restart, all dimensions valid, all markers detected, maximum error `4.031 px` within the `8 px` tolerance. This is not gameplay authorization. |
| Capture fidelity and freshness | Passed | RT-010 records 8 valid unique `800x1280` PNGs, no adjacent duplicates, changing content, and approximately `1.015 s` p50 / `1.026 s` p95 capture latency. |
| Restart and reconnect behavior | Passed | RT-011 records 3 app restarts, 3 corrected Android/guest recoveries, 2 clean VM power-cycles, 1 controlled cold VM stop/start, display/renderer persistence, and ADB reconnect. The failed initial shutdown approach is retained. |
| Four-hour Unraid-local observe-only stability gate | Passed | RT-012 records 48 five-minute samples through the exact four-hour deadline, 48 valid non-black frames, zero ADB failures, p95 `222.764 ms`, complete host metrics, zero input, no hard stop, and quota compliance. Historical NBD/kernel anomalies remain retained and were not generated during the run. |
| NAS/runtime safety during the selection window | Passed for the bounded run | RT-012 VM state remained `running`, host collector errors were zero, the temporary observer was unprivileged/read-only and removed after evidence preservation, and no unrelated service or storage mutation occurred. Longer 24-hour/72-hour/7-day/21-day validation remains later work. |
| Optional remote viewer after VirtIO-GL | Not an RT-013 gate | RT-014A remains optional and does not reject Bliss. Production observation uses the private ADB path; viewer input is not enabled. |
| VM autostart and worker ordering | Not an RT-013 gate; deferred | RT-015 is a later deployment/runbook task. No Unraid host reboot is required or authorized. |
| Strong numeric account/server identity evidence | Not an RT-013 gate; deferred | RT-016A remains a manual-only M7-AccountGuard prerequisite. Existing authenticated-session and hard-stop evidence is sufficient for technical runtime selection; no profile navigation is performed here. |
| Production unprivileged worker-to-VM ADB path | Downstream gate | RT-021 is authorized next to prove the actual Unraid-local worker path without an external tunnel. Its pending status does not reject this technical selection. |

## Selected runtime/profile facts

- Runtime: Bliss OS `16.9.7` GApps / Android `13`, x86_64 VM.
- VM: `PnS-BlissOS-PoC`; UUID `5500a07f-4352-4ce5-b1cf-7cf668e3a9f4`.
- Graphics: VirtIO primary video with `accel3d`, `egl-headless`, and the Intel UHD 770 render
  node `/dev/dri/by-path/pci-0000:00:02.0-render`; guest renderer Mesa VirGL, OpenGL ES 3.2,
  Mesa 24.0.8.
- Display: physical `1280x800`; effective logical capture `800x1280`; density `160`; app-driven
  portrait; global rotation lock is not relied upon.
- Game: `com.global.ztmslg`, version `7.0.278`; package is already provisioned and authenticated.
- Startup: Android boot/keyguard state must be safely reconciled before launch. Launching the game
  normally opens Cash Mall, not Home/Base. The startup normalization flow must positively
  recognize Cash Mall, recapture immediately, authorize at most one bounded no-spend tap on the
  recognized top-left back arrow, recapture, and require positive Home/Base recognition. This is
  recorded for later startup-navigation work; no input was sent in RT-013.
- ADB/network: guest endpoint `192.168.122.79:5555` on private libvirt NAT; no LAN/public ADB;
  the transient SSH tunnel was development-only and is closed. RT-021 must prove the production
  Unraid worker path.
- Rollback: RT-001 QXL/SwiftShader baseline XML
  `/mnt/cache/domains/PnS-BlissOS-PoC/rollback/20260710-rt001-qxl-baseline.xml`, SHA-256
  `f8011eeed1e3f464ad317610973e74bf97f2c922c261142eab51c7f9c002624e`; RT-003 selected candidate
  XML `/mnt/cache/domains/PnS-BlissOS-PoC/rollback/20260710-rt003-virgl-trial-01.xml`, SHA-256
  `9ed03ee6cabedbabf30271fbffe2869b0d5c96207e90a1927c6122f5f7f97c16`; RT-007 display rollback
  commands remain recorded. The qcow2 path and identity were not changed.

## Cash Mall startup behavior

The retained development/reference frame
`../20260711-rt-012-observe-soak/cash-mall-startup-reference.png` is an `800x1280` Cash Mall
screen captured from the already-provisioned runtime. It contains the exact `Cash Mall` title,
mall offer/purchase context, premium-currency header, and large top-left back arrow. Cash Mall is
a normal authenticated game state, not login, tutorial, wrong account, server/state selection,
session loss, or an authentication hard stop. The reference does not replace final locked-runtime
recapture for production recognition assets.

## Fallback trigger

Do not start a fallback because RT-014A, RT-015, RT-016A, RT-019, or RT-021 is pending. Trigger
the isolated ReDroid-in-Linux-VM proof only if a remaining Bliss runtime-selection gate produces
new contradictory evidence or a documented hard rejection, such as repeatable invalid/black frame
output, renderer/display drift, unrecoverable restart failure, ADB containment failure, or a
failed bounded stability gate. Any fallback would require its own preflight, evidence, rollback,
and task-scoped decision.

## Post-selection authorization

Bliss Passed authorizes the next independent infrastructure tasks: RT-017 secured post-
provisioning recovery backup, RT-019 versioned runtime-profile manifest/schema, and RT-021
unprivileged Unraid worker-to-VM ADB proof. They remain sequential for live VM operations. It also
authorizes preparation of the startup-normalization MVP only after those required gates and with
its explicit validation order. It does not authorize gameplay automation, account/profile
navigation, spending, or any action outside a separately promoted supervised-validation task.

## Final runtime and rollback state

- VM is running on the selected VirtIO(3D)/Mesa VirGL profile; autostart remains disabled.
- Game was force-stopped after RT-012 cleanup; no gameplay input or startup-navigation input is
  active.
- No observer, supervisor, or external ADB tunnel is active. ADB remains private/loopback-only
  at the host boundary.
- RT-001, RT-003, RT-007, and RT-012 rollback/evidence artifacts remain intact.

## Review conclusion

Every RT-013 acceptance item is either Passed, Passed with an explicit limitation, or documented
as a downstream/non-gate item. No unsupported conclusion, failed attempt, or anomaly was filtered
out. Bliss is selected; the rejection fallback is not triggered.
