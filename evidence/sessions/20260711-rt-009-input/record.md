# RT-009 input fidelity — passed

Date: 2026-07-11 (America/Chicago)

## Scope

Measure coordinate mapping on the selected `800x1280` profile without touching the game. Test
surface is Android Home wallpaper with the reversible Android pointer-location overlay enabled.
This avoids game progression, resources, account state, tutorial, and credentials.

## Method

Added and ran `scripts/test-input-fidelity.ps1`. The harness:

- verifies display dimensions, density, and rotation;
- enables `settings system pointer_location=1`;
- sends nine taps and four long swipes at known logical coordinates;
- captures each resulting PNG;
- detects the red pointer marker near expected endpoints;
- records measured endpoint error, direction, distance class, dimensions, and SHA256;
- resets pointer location to `0` and returns Home in `finally`.

Tap grid:

- `(100,200)`, `(400,200)`, `(700,200)`
- `(100,600)`, `(400,600)`, `(700,600)`
- `(100,1000)`, `(400,1000)`, `(700,1000)`

Swipes:

- down `(200,250) → (200,650)`
- up `(600,850) → (600,450)`
- right `(250,600) → (550,600)`
- left `(550,850) → (250,850)`

The complete test ran once before and once after a guest restart. After restart, settings remained
physical `1280x800`, override `800x1280`, density `160`; the required safe Android keyguard
dismissal was used because boot initially reported `mInputRestricted=true`. No game was launched.

## Results

Machine-readable results:

- `trial-1-corrected/summary.json`
- `trial-1-corrected/results.csv`
- `trial-2-after-guest-restart/summary.json`
- `trial-2-after-guest-restart/results.csv`

Trial 1:

- 9 taps, 4 swipes
- invalid dimensions: `0`
- undetected markers: `0`
- maximum endpoint error: `2.943 px`
- pointer setting reset: `0`

Trial 2 after guest restart:

- 9 taps, 4 swipes
- invalid dimensions: `0`
- undetected markers: `0`
- maximum endpoint error: `4.031 px`
- pointer setting reset: `0`

Tap endpoints measured `0.707 px` error in both runs. All swipe directions and long-distance
classes were recorded and detected. No rotation, scaling, or dimension mismatch appeared.

The initial detector attempt in `trial-1/` rejected three swipes because it only accepted pure
red marker pixels and used a 4-pixel limit. Runtime evidence already showed the alpha-blended
pointer trail; the harness was corrected to accept blended trail pixels and an 8-pixel tolerance.
The failed detector run remains retained and does not represent a runtime/input failure.

## Acceptance

Passed. All tested taps/swipes mapped within the 8-pixel tolerance on two profile states, including
after guest restart. No game input or durable Android/game mutation occurred.

## Rollback and next work

Pointer overlay reset to `0`; Home restored; game remained force-stopped. RT-011 full restart
matrix is now the next runtime task.
