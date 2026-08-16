# BlueStacks-to-Bliss development assessment

## Decision

BlueStacks is the current primary development, reconnaissance, replay, and canary target. Build and
accept the local automation portfolio there first. Bliss OS 16.9.7 is the later porting and
deployment-acceptance target for package `com.global.ztmslg` at the canonical logical viewport
800×1280 portrait and 160 dpi; it is not a prerequisite for current BlueStacks flow development.

Both supplied BlueStacks screenshots are native 800×1280 PNGs, not scaled previews. One is
user-confirmed zoomed in and the other fully zoomed out; the latter still does not show the entire
base. Coordinates are valid only for their exact captured BlueStacks profile and camera state.
They do not transfer between zoom states or become Bliss coordinates by sharing pixel dimensions.

## Platform-neutral device boundary

A reusable ADB device interface should expose only the operations needed by deterministic task
modules and safety policy:

- enumerate already-connected/private devices and bind one explicit serial;
- obtain platform/profile metadata, physical frame size, logical viewport, DPI, orientation,
  foreground package, and monotonic/wall-clock timestamps;
- capture a raw PNG frame and retain its hash/provenance;
- dispatch bounded `tap`, `swipe`, and `back` only through the current action executor;
- report transport outcome separately from semantic result;
- never initiate a public listener, implicit `adb connect`, generic shell, vendor selector, or
  hidden coordinate transform.

Task logic should receive frames and typed input callbacks. It should not know whether the bound
implementation is BlueStacks or Bliss, but it must see an immutable device-profile identifier so
evidence and detector calibration cannot cross platforms silently.

## What the repository already supports

The current abstractions substantially support local discovery:

- `scripts/bluestacks_flow_collector.py` already provides explicit-serial ADB capture, strict
  800×1280 checks, passive and record-only modes, hashed manifests, a mock frame source, and no
  implicit `adb connect`.
- `safe_action_core` already accepts injected capture and transport callbacks, keeping task state
  machines largely independent of an emulator brand.
- `scripts/pnsctl.py` remains the supported operational interface where an operation exists; the
  collector is a bounded evidence tool, not a second production runtime interface.

No replacement manual-flow collector is needed. Current BlueStacks work should keep using the
checked-in typed runtime/profile boundaries and explicit evidence provenance. Later Bliss porting
must bind a separate device profile and reacquire native evidence without registering tasks,
enabling scheduling, or weakening the single-runtime-operator rule.

## Evidence separation

Store or manifest every artifact under a platform identity such as:

```text
platform: bluestacks | bliss
device_profile_id: <stable local identifier>
logical_viewport: 800x1280
physical_frame: <captured PNG dimensions>
dpi: <observed value>
package: com.global.ztmslg
source_kind: raw_adb | derived_crop | recording_frame
parent_sha256: <required for crops>
```

BlueStacks and Bliss positives, negatives, templates, OCR samples, thresholds, and route results
must be evaluated separately. A combined report may compare them, but must not pool calibration
samples or label a BlueStacks pass as Bliss acceptance.

## Viewport and DPI normalization

- Reject any raw frame that is not the expected orientation and dimensions for its declared
  profile. Letterboxing, host-window screenshots, Android navigation overlays, rotation, and
  resized previews are different profiles.
- Use logical coordinates only after the current full frame, foreground package, source screen,
  bounds, and overlay state are positive.
- Do not scale vendor 400×652 coordinates, the 781×1248 annotated chat image, or BlueStacks-local
  coordinates into Bliss.
- Reacquire semantic anchors independently on Bliss. If both platforms happen to produce the same
  ROI, record that as an observed result rather than an assumed transform.
- Treat DPI, font scale, Android display size, language, and system-bar behavior as profile inputs,
  even when the PNG remains 800×1280.

## Template and OCR portability risks

BlueStacks and Bliss can differ in GPU renderer, texture filtering, font rasterization, gamma,
color management, animation timing, compression, system bars, touch feedback, and update cadence.
Consequences include:

- template scores that move across a threshold despite identical geometry;
- color masks that drift or bloom at edges;
- text baselines, stroke widths, kerning, and countdown glyphs changing enough to affect OCR;
- notification badges, ads, webviews, and emulator overlays occluding an otherwise stable anchor;
- animation frames or loading delays invalidating fixed waits;
- host screenshots looking correct while differing from raw ADB frames.

Prefer local shape/color plus a named successor for stable icons, and bounded OCR tied to an icon
or screen anchor for counters and timers. Calibrate thresholds per platform and retain hard
negatives; do not lower a global threshold until it accepts both platforms.

## Minimum Bliss verification before a route is complete

A route developed with BlueStacks discovery evidence is not complete until an explicitly
authorized Bliss task records and passes all of the following:

1. Current raw ADB 800×1280/160 dpi source recognition with `com.global.ztmslg` foreground,
   canonical Town/camera state where applicable, and no blocking overlay.
2. Independent Bliss target acquisition from full-frame evidence; no imported or scaled
   BlueStacks/vendor coordinate.
3. Source, immediate-before revalidation, one policy-allowed transport action at the consequential
   boundary, immediate-post, and a named semantic success result.
4. At least the route's critical busy/unavailable/insufficient/confirmation negative state, proving
   the detector stops safely instead of treating transport or disappearance as success.
5. For resource-changing actions, exact before/after count or quest-state reconciliation and no
   blind retry; ambiguous outcomes remain unresolved.
6. The required game-day binding, journal action, lease, evidence manifest, and unresolved-gate
   checks under current repository policy.
7. Focused offline tests plus the route's Bliss positive and negative acceptance checks. Scheduler
   eligibility and registration remain disabled unless a separate authorized backlog task promotes
   them.

## Recommended future atomic task

After the current handoff's already-authorized passive BlueStacks smoke is complete, the highest
value product task is `EVIDENCE-HOME-UI-BLISS-BASELINE`: capture and normalize one canonical raw
Bliss town-home frame plus build/research queue, camp, and Pit state variants. It requires explicit
backlog activation and runtime authorization. A shared BlueStacks device-profile adapter should be
a later atomic task only when direct local replay, beyond the existing manual collector, is needed.
