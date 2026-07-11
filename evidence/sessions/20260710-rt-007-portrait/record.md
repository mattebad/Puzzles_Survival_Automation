# RT-007 portrait display profile — in progress

Date: 2026-07-10 (America/Chicago)

## Starting profile

- VirtIO(3D)/Mesa VirGL candidate selected.
- Physical display 1280×800 at 160 dpi.
- Android Home naturally landscape; the game requests portrait and produces correct 800×1280 PNGs.
- Game force-stopped at the start of RT-007.

## Candidate A — user rotation lock 1

Applying `wm user-rotation lock 1` as an individual command produced a correct 800×1280 Android
Home frame. `wm fixed-to-user-rotation enabled` and `wm user-rotation` initially reported
`lock 1`. Launching the game produced a correct 800×1280 frame, but the app changed user rotation
back to `free`. This is visually usable but does not satisfy a persistent global lock.

## Candidate B — ignore app orientation requests

`wm set-ignore-orientation-request true`, fixed-to-user enabled, and rotation lock 1 persisted, but
the game capture contained large black regions and only partial UI tiles. Candidate B is rejected.

Rollback was immediately applied:

- `wm set-ignore-orientation-request false`
- `wm fixed-to-user-rotation default`
- `wm user-rotation free`

The next captured game frame was complete and visually correct, proving rollback.

## Candidate C — logical size override

Executed 2026-07-11 (America/Chicago), after force-stopping the game and capturing the current
Home frame. The first binary-capture attempt failed locally before changing Android settings; that
failure is retained in the session history. The retry applied exactly:

- `wm set-ignore-orientation-request false`
- `wm fixed-to-user-rotation default`
- `wm user-rotation lock 0`
- `wm size 800x1280`
- `wm density 160`

Observed settings after the change:

- Physical display: `1280x800`
- Override display: `800x1280`
- Physical density: `160`
- User rotation: `lock 0` immediately after setup
- Fixed-to-user rotation: `default`
- App orientation requests: enabled (`ignoreOrientationRequest false`)

`home-size-800x1280.png` is a complete, non-black `800x1280` Android Home frame. Launching
`com.global.ztmslg` without any gameplay input produced complete `800x1280` Cash Mall frames;
the two frames five seconds apart have different hashes and a moving event countdown. The game
was force-stopped after observation.

## Restart observations

The first three exploratory guest-restart captures intentionally remain as failure evidence:

- `wm size 800x1280` and density 160 persisted after every reboot.
- Android came up with `mInputRestricted=true`; the game activity was present but stopped with
  `NO_SURFACE`, so the early captures showed Home and one nearly-black wake-transition frame.
- No game input was sent and no account state was changed.

The cause was Android's post-boot keyguard/input restriction, not display-size loss. The safe,
non-game OS sequence `KEYCODE_WAKEUP`, keyevent `82`, and `cmd window dismiss-keyguard` changed
`mInputRestricted` to false without credentials. Explicitly starting
`com.games37.sdk.AtlasPluginDemoActivity` then resumed the game and produced a complete frame.
Diagnostics are retained in `post-restart-launch-diagnostic.txt`, `post-restart-unlock-state.txt`,
and `post-unlock-launch.txt`.

Three corrected guest-restart trials were then run. Each trial:

1. waited for `sys.boot_completed=1`;
2. verified physical `1280x800`, override `800x1280`, density `160`, and app-controlled portrait;
3. dismissed only the non-secure Android keyguard path above;
4. explicitly launched the already-provisioned game;
5. captured two frames, five seconds apart, then force-stopped the game.

All three trials resumed the game with `mResumed=true`, `mStopped=false`, and complete `800x1280`
Cash Mall frames. Trial 1's second frame showed a transient in-game `Request timed out.
Reconnect now?` overlay; no dialog input was sent. This is retained as network/overlay evidence,
not a display drift or black-frame failure. Trials 2 and 3 remained visually complete.

## Profile decision

Candidate C is accepted as the effective final portrait display profile for the remaining runtime
gates:

- Renderer: Mesa VirGL through selected VirtIO(3D), unchanged.
- Logical capture/display profile: `800x1280`.
- Physical guest display: `1280x800`.
- Density: `160`.
- Orientation: effective portrait, Android configuration `port`/`ROTATION_0`, with the game
  allowed to request portrait. Global `wm user-rotation lock` is not used because the game returns
  it to `free`; forcing global ignore-orientation previously corrupted rendering (Candidate B).
- System bars/viewport: stable across the corrected restart trials; game content fills the same
  portrait frame.
- Startup requirement: perform the safe Android keyguard dismissal before app launch; this is
  ordinary OS lifecycle control, not credential, tutorial, or gameplay automation.

This locks an effective pixel profile while explicitly retaining the global-rotation limitation.
The profile rollback is `wm size reset`, `wm density 160`, `wm set-ignore-orientation-request false`,
`wm fixed-to-user-rotation default`, and `wm user-rotation free`; the known-working SwiftShader
and VM XML rollback remain unchanged.

## Current state and next action

- RT-007 evidence is complete for the effective profile; no purchase, account, tutorial, or
  gameplay tap was sent.
- Game is force-stopped; no input automation or SSH/ADB tunnel remains active.
- Candidate C settings remain applied for downstream capture/input tests.
- RT-008 (ADB containment) and RT-010 (capture fidelity) are now ready. RT-009 input testing
  remains blocked until its non-game test surface is selected.

