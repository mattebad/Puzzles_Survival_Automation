# RT-012 preflight

Recorded: 2026-07-11, America/Chicago

## Task

- Task ID: RT-012.
- Objective: complete the 4-hour Unraid-local, observe-only Bliss runtime-selection soak.
- Satisfied dependency: RT-011 passed; its restart-matrix evidence remains authoritative.

## Acceptance criteria

- Four-hour target completed; a shorter run is diagnostic only.
- Observer executes on Unraid, survives external SSH disconnect, remains read-only, and sends
  zero game input.
- Observer identity, start time, expected end time, logs, evidence path, and quota are recorded.
- 300-second sampling, cache-backed evidence, and 512 MiB evidence quota are enforced.
- Every expected frame is a valid, non-black `800x1280` PNG; p95 capture latency is no greater
  than 2 seconds.
- Freshness is assessed with multiple signals; identical full-screen hashes alone do not fail the
  task.
- ADB/game health, foreground state, VM/QEMU, host CPU/RAM/GPU/temperature, cache growth,
  listeners, Docker/NAS health, and recent host errors are captured.
- No account/session hard-stop or host/runtime rejection condition occurs.
- Manual visual/authentication-state review is retained before the task is passed.

## Intended operations

- Use a Python observer running locally on Unraid as the approved execution model.
- The Unraid host has no Python executable, so run the observer in a temporary unprivileged
  container using the already-present local image; this is the approved temporary unprivileged
  Docker observer model.
- Use host networking only because the existing NAS-local ADB server listens on loopback; the
  container has no published listener, no Docker socket, no elevated capabilities, and only a
  read-only ADB binary mount plus the cache-backed evidence mount.
- Connect only to the existing private VM ADB endpoint, launch the already-provisioned package
  for observation if needed, capture read-only frames/health, and collect read-only host metrics.
- Write the live run under a cache-backed Unraid directory, then retrieve the retained evidence
  into this repository after completion.
- Do not change the VM XML, disk, renderer, display profile, ADB exposure, game account, or game
  state beyond the approved package launch needed for observation.

## Verification procedure

- Verify the remote observer process/container identity, command, user, start time, deadline,
  output path, and quota before disconnecting SSH.
- Confirm direct private ADB connectivity and record profile/renderer/game health without input.
- Monitor only at the natural 300-second interval and expected completion; do not busy-poll.
- At completion, validate sample count/timestamps, PNG decode/dimensions/black-frame results,
  latency distribution, multi-signal freshness fields, host metric completeness, quota, and
  zero-input audit.
- Review representative frames and authentication/session state manually before making a
  criterion-by-criterion pass decision.

## Evidence and rollback

- Live evidence directory: cache-backed Unraid path recorded by the observer and its manifest.
- Repository evidence directory: `evidence/sessions/20260711-rt-012-observe-soak/`.
- Retain logs, samples, frames, process identity, hashes, and any failure artifacts.
- Rollback: stop only the observer after completion or failure; disconnect the private ADB
  observation connection; leave the VM on the known Mesa VirGL profile with the game force-stopped.
  Do not delete or overwrite the Bliss disk, redefine unrelated domains, reboot Unraid, or broaden
  network exposure.

## Permissions and dependencies

- Required: existing development SSH access to `root@nas.local` solely to launch, inspect, stop,
  and retrieve the observer; local/private VM ADB access already established by RT-008/RT-011.
- No host reboot, VM storage change, public ADB/viewer exposure, gameplay input, credentials inside
  the observer, or production service permission is authorized.
- Expected credential dependency: process-only `UNRAID_TEMP_PASSWORD` for this session; it will
  not be written to repository files, evidence, scripts, or durable logs.
- Expected manual-user dependency: none to begin the observe-only run. Stop and request the user
  if login, tutorial, CAPTCHA, account/session restoration, unknown game state, or other mandatory
  manual navigation appears. Manual visual/authentication review remains required before passing.

## Retained preflight attempt

- `preflight-diagnostic/` is retained as failure/diagnostic evidence.
- The temporary observer launched the already-provisioned package and verified the expected display,
  density, and Mesa renderer, but captured zero frames because the first implementation compared a
  float epoch with a `datetime` while entering its sample loop.
- No runtime rejection, account hard-stop, gameplay input, or host mutation occurred. The game was
  returned to force-stopped state before the corrected preflight.
- Revised hypothesis: the observer transport and startup path are valid; the error is limited to
  deadline-loop typing. The smallest justified change is the `utc_now() < deadline` comparison.

## Corrected preflight verification

- `preflight-diagnostic-2/` is retained as successful bounded diagnostic evidence, not a pass for
  RT-012. It launched the provisioned package, captured one valid `800x1280` non-black frame with
  the game foreground, measured 198.365 ms capture latency, observed no hard-stop signal, and
  shut down cleanly on signal with zero ADB failures.
- Manual visual review confirmed the frame was the authenticated game surface (`Cash Mall`), not a
  login, tutorial, CAPTCHA, or account-restoration state. No purchase or gameplay input occurred.
- The package was force-stopped and the private ADB connection disconnected before the full run.
