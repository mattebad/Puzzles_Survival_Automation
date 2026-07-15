# Runtime input safety policy

This document is the canonical procedure for live input. It does not authorize a task, register a
handler, enable a scheduler, or replace the active backlog contract.

## Coordinate and source contract

- The production coordinate space is raw full-frame `800×1280` at the fixed
  `pns-blissos-poc-virgl-800x1280-v1` profile.
- A crop-local point `(x, y)` translates to full-frame `(left + x, top + y)` only when the crop
  origin and frame dimensions are recorded. Dispatch must use the translated full-frame point.
- A scaled preview, rendered thumbnail, stale capture, untranslated OCR crop, or vendor coordinate
  never authorizes input.
- Before any input, recognize the positive source state, exact local target identity, target
  geometry, cost, quantity, overlay state, package/profile identity, and expected successor.
- Target geometry must be inside the full-frame bounds, have an interior dispatch margin, and not
  intersect a forbidden control or overlay.

## Pre-dispatch sequence

1. Confirm the active task authorizes the action class and the global unresolved-action gate is
   clear.
2. Capture a current raw frame and positively recognize the source.
3. Bind the exact target from that same frame, including semantic label or identity and local
   association to the source row/control.
4. Capture the mandatory immediate-before frame through the supported operator interface.
5. Re-run source, target, geometry, cost, quantity, overlay, and profile checks against the
   immediate-before frame.
6. Dispatch only the authorized number of inputs through `scripts/pnsctl.py` and persist the action
   record before observing the successor.

## Target movement and rebinding

Compare the source and immediate-before target identity, bounds, row association, and forbidden
regions. A moved target may be rebound only when the same semantic control remains positively
identified, the movement is within the task's declared narrow tolerance, the new bounds are fully
visible and safe, and the rebinding is recorded in the action artifact. A generic nearest-target,
broad ROI, OCR-only, or stale-coordinate rebinding is forbidden.

## Overlays and popup handling

Unknown, cost, resource, premium, account, login, tutorial, CAPTCHA, or session overlays block.
Generic popup cleanup is disabled during consequential preparation and dispatch. A named
navigation-only popup handler may run only when its source identity, target, and terminal
navigation postcondition are independently declared.

## Input limits and semantic verification

- Navigation-only actions and consequential actions are separate classes.
- A consequential action normally permits one transport input. Polling, recapture, and postcondition
  observation are not retries.
- Transport success, command exit status, screen change, or a full-screen hash alone is never a
  semantic success signal.
- The postcondition must be a task-declared positive signal: result identity, row/count/resource
  delta, cooldown transition, or another explicit semantic change.
- An ambiguous consequential result becomes `unresolved`; stop, preserve evidence, release or
  transfer the lease according to policy, and reconcile. Never issue an identical blind retry.
- Navigation ambiguity remains navigation diagnostic state and must not clear, downgrade, or alter
  a consequential action record.

## Stop conditions

Stop before transport on source change, target ambiguity, profile mismatch, bounds failure,
unexpected overlay, stale evidence, missing game-day identity, active unresolved consequential
action, lease loss, unknown account state, or an authorization mismatch. Stop after transport when
the semantic postcondition is ambiguous or contradictory.
