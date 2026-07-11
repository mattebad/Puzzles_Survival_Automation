# RT-011 restart matrix record

Recorded: 2026-07-11, America/Chicago

## Decision

RT-011 passed for the dedicated Bliss PoC lifecycle paths tested here:

- app process restart: 3/3
- Android guest restart: 3/3 corrected recovery trials
- VM power-cycle restart: 2/2 clean power-off/start trials
- VM cold stop/start: 1/1 controlled cold trial
- ADB tunnel reconnect: successful for every completed VM recovery trial

No host reboot, host firewall change, public ADB exposure, account operation, tutorial action,
credential operation, purchase, or gameplay input was performed.

RT-012 observe-only soak remains required. RT-013 final Bliss pass/fail and runtime-profile
lock remain open because post-VirtIO-GL remote viewing, VM autostart ordering, and the required
12–24 hour host/NAS stability observation are not covered by this matrix.

## Runtime under test

- Domain: `PnS-BlissOS-PoC`
- Profile: Bliss OS 16.9.7 GApps / Android 13, VirtIO(3D), Mesa VirGL
- Package: `com.global.ztmslg`
- Physical display: `1280x800`
- Effective logical display: `800x1280`
- Density: `160`
- `wm user-rotation`: `free`; effective game orientation remained portrait
- ADB: guest `192.168.122.79:5555`, reached only through transient pinned SSH tunnel
  to controller-local `127.0.0.1:15555`
- Guest ADB authentication: `ro.adb.secure=0`; strict private network containment remains
  the accepted boundary from RT-008

## Safety preconditions

Before each VM lifecycle trial, the game process was force-stopped while no consequential
action was pending. After reconnect, Android was allowed to boot before any package launch.
When Android reported `mInputRestricted=true`, only the approved system startup sequence was
used: wake key, keyevent `82`, and `cmd window dismiss-keyguard`.

The game was launched only for observation. The retained Cash Mall frames show a recognized
authenticated game surface with no login, new-account, tutorial, wrong-account, CAPTCHA, or
session-loss prompt. No game dialog was answered. Account identity remains protected from
normal logs; prior authenticated-session evidence is retained in
`evidence/sessions/20260710-rt-003-virgl-trial-01/record.md`.

## Trial results

### App process restart

| Trial | Procedure | Result |
|---|---|---|
| 1 | Capture state; `am force-stop`; `am start -W`; capture after launch | Pass |
| 2 | Capture state; `am force-stop`; `am start -W`; capture after launch | Pass |
| 3 | Capture state; `am force-stop`; `am start -W`; capture after launch | Pass |

Observed on all trials:

- ADB state was `device`.
- Renderer remained `mesa`.
- Density remained `160`.
- Android input restriction was cleared before game observation.
- Post-launch activity was resumed and not stopped.
- Post-launch PNG showed the Cash Mall surface at the effective portrait profile.
- Before/after hashes are retained in `app-trial-1-hashes.txt` through
  `app-trial-3-hashes.txt`.

### Android guest restart

The completed trials used the approved `adb reboot -p` guest power-off path followed by
`virsh start`. Each trial independently re-established the tunnel and ADB connection.

| Trial | Boot/reconnect | Profile persistence | Game observation | Result |
|---|---|---|---|---|
| 1 | `sys.boot_completed=1`, ADB `device` | `800x1280`, 160 dpi, `free`, Mesa | Resumed activity and Cash Mall frame | Pass |
| 2 | `sys.boot_completed=1`, ADB `device` | `800x1280`, 160 dpi, `free`, Mesa | Resumed activity and Cash Mall frame | Pass |
| 3 | `sys.boot_completed=1`, ADB `device` | `800x1280`, 160 dpi, `free`, Mesa | Resumed activity and Cash Mall frame | Pass |

`vm-trial-1.txt` and `vm-trial-2.txt` retain the first two complete recovery records.
`vm-trial-1-recovery-adb-state.txt` and `vm-trial-1-recovery-host-states.txt` retain the
initial reconnect/host-state evidence. `vm-trial-1-failed.txt` records the abandoned
`virsh shutdown` attempt; it remained `running` and was not counted as a passed recovery.

### Controlled cold VM stop/start

Trial 3 used `virsh destroy` only after the game had been force-stopped, then polled until the
domain reported `shut off`, followed by `virsh start`. This was a dedicated-domain stop, not
a host or storage operation.

Observed:

- Domain reached `shut off`.
- `virsh start` succeeded.
- ADB reconnected and reported `device`.
- `sys.boot_completed=1`.
- Before keyguard dismissal, `mInputRestricted=true`; after the approved dismissal sequence,
  `mInputRestricted=false`.
- Display remained physical `1280x800`, logical `800x1280`, density `160`.
- Renderer remained Mesa.
- Game activity resumed with `mResumed=true`, `mStopped=false`.
- `vm-trial-3-cold-game.png` and `vm-trial-3-cold-game-after-5s.png` are visually correct
  Cash Mall frames. The two hashes differ only because the event countdown advanced; both
  are valid portrait PNGs.

Complete command output is in `vm-trial-3-cold.txt`; image hashes are in
`vm-trial-3-cold-hashes.txt`.

## Acceptance matrix

| Criterion | Evidence | Result |
|---|---|---|
| App restart repeatability | Three app before/after records, activity state, six retained hashes | Pass |
| Android restart repeatability | `vm-trial-1.txt`, `vm-trial-2.txt`, prior corrected guest-restart evidence | Pass |
| Clean VM power-cycle recovery | `vm-trial-1.txt`, `vm-trial-2.txt` | Pass |
| Controlled cold VM recovery | `vm-trial-3-cold.txt` and three retained PNG hashes | Pass |
| ADB/controller reconnect | ADB `device` after each completed recovery; RT-008 tunnel boundary | Pass |
| Display persistence | Pre/post `wm size`, density, rotation and visual PNGs | Pass |
| Renderer persistence | Pre/post `ro.hardware.egl=mesa` across VM trials | Pass |
| Game state/session persistence | Recognizable Cash Mall frames; no auth hard-stop state | Pass |
| Authentication hard-stop behavior | No login/tutorial/CAPTCHA/wrong-account state; no game input | Pass |
| Host safety boundary | No host reboot, broad network change, or existing-service action | Pass |
| Gameplay-action recovery | Explicit non-goal; no consequential action was pending | Not tested by design |

## Failure and correction record

The first attempt at VM shutdown used `virsh shutdown`, which did not complete and left the
domain `running`. The failure evidence is retained in `vm-trial-1-failed.txt` and the host
state poll in `vm-trial-1-recovery-host-states.txt`. Root cause is guest ACPI/power-menu
handling, not evidence of display, ADB, or renderer failure.

The bounded correction was `adb reboot -p` for clean guest power-off, followed by `virsh start`.
Two clean power-cycle trials passed. One controlled cold `virsh destroy`/`virsh start` trial
then passed. No repeated materially different failure approach is justified for RT-011.

## Rollback and final state

- No VM XML or boot configuration changed during RT-011.
- RT-001 XML and boot rollback artifacts remain authoritative.
- Game process was force-stopped during cleanup.
- ADB tunnel was closed during cleanup.
- No pointer overlay or test surface remains enabled.
- VM remains on selected Mesa VirGL profile with autostart disabled.

Next task: RT-012 observe-only stability soak. Do not enable gameplay automation before RT-013
locks the final runtime profile and all production gates pass.
