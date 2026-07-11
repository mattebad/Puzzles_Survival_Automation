# RT-010 capture fidelity — passed

Date: 2026-07-11 (America/Chicago)

## Scope

Validate ADB PNG capture on the selected Mesa VirGL profile without gameplay input:

- fixed dimensions and valid PNG decoding;
- changing-frame freshness;
- SHA256 manifestability;
- end-to-end capture latency;
- boot/display metadata.

## Method

Added and ran `scripts/test-capture-fidelity.ps1` against the existing transient localhost SSH
tunnel and serial `127.0.0.1:15555`. The already-provisioned game was explicitly launched for
observation only, then force-stopped in cleanup. No game tap, purchase, dialog response, account
operation, tutorial action, or credential operation occurred.

Command parameters:

- Samples: 8
- Interval: 2000 ms
- Expected dimensions: `800x1280`
- Density observed: `160`
- Renderer/profile: selected VirtIO(3D)/Mesa VirGL

## Results

Machine-readable results:

- `summary.json`
- `captures.csv`
- `capture-001.png` through `capture-008.png`

All 8 captures decoded as valid PNGs with `800x1280` dimensions.

- Invalid dimensions: `0`
- Unique hashes: `8/8`
- Adjacent duplicate samples: `0`
- Maximum duplicate run: `0`
- Capture latency minimum: `1007.818 ms`
- Capture latency p50: `1014.772 ms`
- Capture latency p95: `1026.136 ms`
- Capture latency maximum: `1027.104 ms`
- Freshness observed: `true`

Visual inspection of first and last frames found complete Cash Mall content with no black,
corrupt, resized, rotated, or letterboxed frame. The event countdown changed between frames.
The screen remained an observe-only paid-state screen; no action was sent.

## Acceptance

Passed. PNG decoding, fixed dimensions, changing hashes, staleness signal, latency distribution,
and evidence hashes are recorded. The measured approximately one-second ADB capture latency is
now part of downstream frame-age and timeout budgets.

## Rollback and next work

Observation-only; no durable runtime mutation. Game was force-stopped and the tunnel was closed.
RT-008 ADB containment and RT-009 non-game input fidelity remain. RT-011 restart matrix follows
once RT-008 and RT-009 pass.
