# MVP-STARTUP-NORMALIZATION preflight

Recorded: 2026-07-11, America/Chicago

## Task

- Task ID: `MVP-STARTUP-NORMALIZATION`
- Objective: safely normalize the already-provisioned `com.global.ztmslg` startup from its
  normal authenticated Cash Mall screen to a positively recognized Home/Base screen.
- Status at preflight: ready; execution begins with this preflight and the task is marked In
  Progress in `BACKLOG.md`.

## Satisfied dependencies

- RT-017: Passed; restricted post-provisioning recovery backup and offline restore review retained.
- RT-019: Passed; runtime profile and compatibility validator locked.
- RT-021: Passed; direct Unraid worker-to-private-VM ADB path proven with an explicit constrained
  host-network fallback.
- RT-013: Passed; Bliss OS 16.9.7 GApps/Android 13 x86_64, VirtIO(3D)/Mesa VirGL profile selected.
- RT-012: Passed; four-hour observe-only evidence retained.

## Acceptance criteria

1. Offline/reference Cash Mall recognition passes using multiple positive features: exact title or
   title-region evidence, mall header/layout, top-left back-control evidence, and purchase/offer
   context.
2. Live observe-only classification uses a fresh `800x1280` frame and positively classifies the
   source or safely returns UNKNOWN; it does not send input.
3. Dry-run annotation identifies the recognized back-arrow ROI and denies all purchase, offer,
   premium-currency, and confirmation controls.
4. One supervised validation, only after all guards pass, sends exactly one bounded no-spend tap
   to the recognized top-left back arrow and retains before/target/input/after evidence.
5. The postcondition is a positive Home/Base recognition. Timeout, unexpected successor, unknown
   overlay, stale frame, input ambiguity, or unresolved Android keyguard blocks the flow without a
   retry.
6. The game is force-stopped after the trial, no Daily Quest flow begins, and no account,
   credential, tutorial, profile, purchase, or server/state navigation occurs.

## Intended changes and operations

- Add a small Python/OpenCV recognizer and dry-run/live-observation CLI using direct ADB capture;
  use local OCR only if a demonstrated ROI requires it.
- Add development/reference asset metadata and retained annotated evidence; reference images do
  not become production recognition assets.
- Run offline recognition against the retained Cash Mall reference and available negative frames.
- Use a temporary unprivileged Unraid worker container for live observe-only capture, with no
  external SSH tunnel, no public ADB, no game input, and cache-backed evidence.
- Attempt only the already-approved non-secure keyguard reconciliation sequence. If the OS remains
  input-restricted or presents an unknown/secure state, stop and preserve the blocker.
- Do not launch a supervised tap unless the source frame is freshly and positively recognized as
  Cash Mall, the target remains unchanged on immediate recapture, and no overlay is present.

## Verification procedure

1. Validate the recognizer and metadata offline, including positive Cash Mall and negative Android
   launcher/keyguard/game non-Cash frames.
2. Review the offline scores and annotated target ROI.
3. Capture one or more fresh frames through the direct Unraid worker path; record dimensions,
   hashes, runtime state, package state, and keyguard policy without input.
4. If the fresh source and OS guards pass, recapture immediately, perform one dry-run target
   annotation, then authorize one supervised no-spend back-arrow tap only.
5. Recapture with a bounded timeout and require positive Home/Base recognition.
6. Preserve all before/target/input/after/failure artifacts, force-stop the game, remove temporary
   worker artifacts, run repository/evidence/secret validation, review the complete diff, and
   commit this task separately if passed.

## Evidence directory

`evidence/sessions/20260711-mvp-startup-normalization/`

Expected artifacts include preflight, recognizer source/tests, offline results, reference/negative
asset manifest, live worker logs/inspect data, fresh frames, annotations, blocker or decision
record, and final validation output. Credentials and unredacted account identifiers are excluded.

## Rollback procedure

- If any guard fails, do not send input; retain the failed observation and mark the outcome
  UNKNOWN or Blocked as applicable.
- After any authorized bounded navigation trial, force-stop `com.global.ztmslg` through the
  temporary worker and remove only the temporary worker/container and its local ADB state.
- Do not modify the qcow2, VM XML, Android account/session, runtime profile, ADB exposure, or
  unrelated Unraid services. No spend rollback is required because only the top-left no-spend
  navigation is authorized.

## Permissions and manual dependency

- Required permissions: repository evidence/code writes; process-local use of the supplied SSH
  credential; temporary unprivileged Docker worker on Unraid; read-only VM/package/ADB observation;
  and, only after promotion, one task-scoped supervised game tap.
- Expected credential dependency: none for the game; the game is already provisioned/authenticated.
- Manual-user dependency: if the approved keyguard reconciliation does not clear the non-secure
  input restriction, the user must manually clear/confirm the Android keyguard or safe startup
  surface. No credential entry, profile navigation, login, account switching, or tutorial action
  will be automated.
- Active-runtime conflict check: no observer, tunnel, or other VM/game/ADB experiment is active;
  the game is force-stopped and only the dedicated Bliss VM is running.
