# MVP-STARTUP-NORMALIZATION resumed preflight

Recorded: 2026-07-11, America/Chicago

## Task and objective

- Task ID: `MVP-STARTUP-NORMALIZATION` resumed from the prior Blocked state.
- Objective: reconcile only the known non-secure Bliss Android keyguard using one bounded,
  positively guarded upward swipe, then complete exactly one Cash Mall-to-Home/Base startup trial.
- Current task status: execution begins with this resumed preflight; backlog status is In Progress.

## Satisfied dependencies and prior evidence

- RT-017, RT-019, and RT-021: Passed.
- Prior offline Cash Mall recognition and dry-run annotation: Passed.
- Prior blocker: known non-secure Android keyguard/setup surface remained after the OS-only sequence;
  no game input occurred and all temporary workers were removed.
- Runtime profile: `pns-blissos-poc-virgl-800x1280-v1`, logical `800x1280`.

## Authorized scope

- Observe-only capture and policy/activity review.
- OS-only `KEYCODE_WAKEUP`, keyevent `82`, and `cmd window dismiss-keyguard`.
- At most one central upward swipe, only after all keyguard predicates and known-surface visual
  classification pass. The swipe is not a generic unlock bypass and applies only to this known
  non-secure, already-provisioned Bliss startup surface.
- One `HOME` keyevent only if the post-swipe state is non-secure, non-blocking, and requires launcher
  settling. No game input occurs during keyguard reconciliation.
- After successful OS reconciliation: approved package launch, fresh Cash Mall classification,
  immediate recapture, one supervised no-spend Cash Mall back-arrow tap, and positive Home/Base
  verification.

## Acceptance criteria

1. Observe-only evidence records boot completion, keyguard showing/secure/input restriction, focus,
   fresh frame timestamp/hash, and valid `800x1280` dimensions.
2. Dismissal authorization requires `sys.boot_completed=1`, showing=true, secure=false,
   `mInputRestricted=true`, positive known unlock-surface classification, no credential/security
   screen, force-stopped game, and no unresolved gameplay action.
3. At most one upward swipe is sent; immediate policy/frame verification proves keyguard no longer
   blocks input without a secure prompt. A failed or uncertain swipe is not retried.
4. The guarded branch is implemented fail-closed with fixtures/tests and versioned-profile checks.
5. Game launch reaches positively recognized Cash Mall; exactly one fresh-frame-authorized back-arrow
   tap occurs; positive Home/Base recognition follows; no spend or unintended action occurs.
6. Before, target, immediate-after, settled-after, keyguard, launch, and cleanup evidence is
   retained; runtime rollback and repository validation pass.

## Intended operations

- Add a fail-closed non-secure-keyguard classifier and bounded reconciliation helper to the small
  Python/OpenCV startup helper; retain existing Cash Mall logic and no generic unlock behavior.
- Run one temporary unprivileged Unraid worker with cache-backed evidence and a private local ADB
  server. No external tunnel, public listener, Docker socket, or unrelated workload changes.
- Perform no swipe unless the observe-only predicates and visual fixture match pass.
- Use the known package lifecycle command only after safe launcher reconciliation; do not guess an
  activity component. Do not begin Daily Quest or any later workflow.

## Verification and evidence

- Evidence directory: `evidence/sessions/20260711-mvp-startup-normalization/`.
- First capture: policy, activity, state, screenshot, timestamp, and hash.
- Offline keyguard fixture tests: retained prior before/after keyguard frames must pass; Cash Mall,
  launcher, and mismatched-profile frames must abstain.
- Live: capture before, swipe, immediate-after, settled-after, and package/activity state through
  the Unraid worker; validate PNGs, hashes, dimensions, policy state, and exact input count.
- Cash Mall: launch boundedly, classify, annotate, immediate recapture, tap once, and require
  positive Home/Base using final-profile features. Stop on unknown, stale, secure, or unexpected.
- Rollback: force-stop game; remove temporary worker/ADB state; never modify qcow2, VM XML, or
  unrelated services.

## Permissions and manual dependency

- Process-local use of the supplied Unraid SSH credential; no credential is written to evidence,
  logs, scripts, or repository.
- Temporary unprivileged worker on Unraid with read-only ADB binary mount and cache evidence mount.
- One task-scoped OS swipe and one task-scoped game back-arrow tap only at their separately guarded
  promotion stages.
- No user credential, login, account/profile/server-state, tutorial, CAPTCHA, purchase, or spend
  operation is expected or authorized.
