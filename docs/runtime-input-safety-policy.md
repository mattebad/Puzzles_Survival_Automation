# Runtime input safety policy

This project is in active development. Planned gameplay is ordinary development interaction and is
run through `scripts/pnsctl.py development-session`; there is no per-action consequential lifecycle.
Real-money Cash Mall confirmation is unsupported.

## Session boundary

- `pnsctl` automatically validates the expected package and native 800×1280 runtime, acquires the
  singleton runtime lock, creates one compact local session record, applies bounded input limits,
  writes a terminal summary, and releases ownership on normal or exceptional exit.
- A session may contain navigation, taps, swipes, zoom, Back, dialogs, claims, rewards, recruitment,
  resource collection or spending, Zombie Lairs, zombie attacks, other combat, challenges,
  maintenance, recovery, and complete end-to-end flow execution.
- No ordinary action requires queue activation, a per-action lease, a prepared/input-sent/reconciled
  journal, a global unresolved record, zero-transport replay, production preflight, manual attempt
  increments, or persistent-artifact mutation.

## Action-specific checks

- Use a fresh raw 800×1280 frame when the action requires visual binding. Bind visible targets from
  that frame, translate crop-local geometry to full-frame coordinates, and reject out-of-bounds or
  unsafe overlay intersections.
- Home zoom requires the expected package, sufficient current native Home context, and bounded
  gesture geometry. It does not require canonical Atlas localization or an off-screen building.
- A target tap needs current-frame evidence sufficient to bind that target. A tested fixed-screen
  control may use its action-specific binding without unrelated whole-flow source gates.
- Transport success alone is not semantic success. Capture useful immediate-post evidence and
  recognize the successor. Unknown results trigger bounded recognition or recovery inside the same
  session.
- Do not repeat an identical ineffective input. Continue only after a concrete diagnosis and a
  materially changed implementation or condition.

## Cash Mall stop

If a path reaches a real-money Cash Mall payment surface, it may observe or safely leave the surface
but must reject the payment confirmation before transport. Do not create approval or journal
infrastructure for real-money purchasing.
