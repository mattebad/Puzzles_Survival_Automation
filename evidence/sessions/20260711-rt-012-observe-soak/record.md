# RT-012 Unraid-local observe-only soak — Passed

Recorded: 2026-07-12, America/Chicago

## Decision

RT-012 Passed. The approved temporary unprivileged Docker observer ran locally on Unraid for the
full four-hour target and completed at the expected deadline. The complete cache-backed output
was preserved under this repository before runtime cleanup.

The run recorded 48 samples at the required 300-second cadence: sample 1 at the run start and
sample 48 at elapsed 14,100 seconds, followed by clean completion at the 14,400-second deadline.
This is the expected four-hour schedule for a sample-at-start observer. No sample was filtered or
discarded.

## Runtime identity and evidence

- Live cache source: `/mnt/cache/puzzle-survival-runtime/rt012/20260711-rt-012-observe-soak/`.
- Repository evidence: this directory, including `frames/`, `host/`, `samples.jsonl`, logs,
  identities, summaries, and retained preflight diagnostics.
- Observer: `rt012_unraid_observer.py` in temporary container
  `rt012-observer-20260711-1519`, UID 65534 (`nobody`), image digest recorded in
  `container-identity.json`.
- Supervisor: Unraid PID 3815606; host-metrics collector PID 3815737; both exited after normal
  completion. The container was removed by the task-owned supervisor only after its output was
  written; the output was retrieved before this decision.
- Start/end: `2026-07-11T20:19:33Z` through `2026-07-12T00:19:33Z`.
- Sampling: 48 PNGs and 48 host metric files.
- Evidence bytes: 38,374,564 bytes reported by the observer, below the 536,870,912-byte quota.

## Criterion review

| Criterion | Decision | Evidence / review |
|---|---|---|
| Complete four-hour duration | Passed | `summary.json`: requested 4 hours, `duration_completed=true`, `stop_reason=duration`, start/end exactly four hours apart. |
| Observer executed on Unraid | Passed | `observer-identity.json`: hostname `NAS`; `container-identity.json`; Unraid-local cache path and host supervisor records. |
| Survived external SSH detachment | Passed | Detached supervisor/container remained active after the launch SSH session ended; subsequent independent SSH inspection found the supervisor and running container. |
| Zero input commands | Passed | `summary.json` and observer identity record `gameplay_input_sent=false`; only package lifecycle launch and approved observation commands were used. |
| Read-only behavior | Passed | Unprivileged UID 65534, dropped capabilities, read-only container root, no Docker socket, no public listener, read-only ADB/game inspection; no gameplay input or account operation. |
| 100% valid PNGs | Passed | 48/48 decoded successfully; `decode_supported=true` for every frame. |
| 100% expected dimensions | Passed | 48/48 frames are `800x1280`; `invalid_frames=0`. |
| Zero corrupt or black frames | Passed | `black_frames=0`; every frame has non-black pixel statistics and retained PNG bytes. |
| p95 capture latency within threshold | Passed | p50 203.178 ms and p95 222.764 ms, below the 2-second backlog threshold. |
| Multi-signal freshness review | Passed | 48 unique SHA-256 frame hashes, maximum duplicate run 0, changing activity/surface digests, valid ADB transport, foreground package state on all samples, and changing countdown/overlay content in reviewed frames. |
| Complete runtime and NAS metrics | Passed with limitation | 48/48 host files and host collector `errors=0`; each includes VM state/stats/address, CPU/load, memory, cache growth, sensors, Docker health, listeners, routes, kernel log, and GPU-sample section. The live `intel_gpu_top` payload was empty, so new per-sample GPU utilization was not quantified; prior RT-004 correlated UHD 770/Mesa VirGL evidence remains authoritative. |
| No account/session hard-stop | Passed | No hard-stop signal in any sample; reviewed frames show authenticated Cash Mall and a normal Get Pts overlay, not login, tutorial, CAPTCHA, wrong-account, or session-loss state. |
| No host/runtime rejection condition | Passed for the run | VM was `running` in all host samples; observer and host summaries had no runtime/collector errors. Historical kernel warnings/errors, including July 9 NBD inspection messages, are retained in every host file and predate this run; they were not generated during RT-012. |
| Evidence quota respected | Passed | 38,374,564 bytes of 536,870,912 bytes used; observer stopped normally before quota. |

## Preserved anomalies and limitations

1. `preflight-diagnostic/` preserves the initial observer deadline-type failure; no runtime sample
   was lost from the four-hour run because it occurred before the final launch.
2. `preflight-diagnostic-2/` preserves the corrected one-sample diagnostic and manual visual
   review.
3. Host metric files retain historical kernel messages from prior NBD inspection and unrelated
   split-lock/NAS history. They were not filtered from evidence. No new matching event was
   observed during the RT-012 window.
4. The host GPU section was collected at every sample but contained no `intel_gpu_top` JSON
   payload. This is a measurement limitation, not a renderer rejection; RT-004 already proved
   correlated UHD 770/Mesa VirGL acceleration.

## Startup behavior observed

Launching `com.global.ztmslg` normally opens the authenticated Cash Mall screen. The reviewed
`800x1280` frame has the exact `Cash Mall` title, purchase/offer content, premium-currency header,
and a large top-left back arrow. This is normal authenticated game content, not login, tutorial,
wrong account, server/state selection, or session loss. The back arrow is the bounded no-spend
navigation target for later startup normalization; this evidence is development/reference
material only and does not replace final-runtime asset recapture.

## Rollback and final runtime state

The observer and host collector are no longer running; the temporary container is absent. The VM
configuration, disk, renderer, display, and private ADB exposure were not changed. After evidence
preservation, the already-provisioned game package was force-stopped and the temporary private ADB
connection was disconnected. VM autostart remains disabled. RT-001 rollback artifacts remain
intact.

## Next

RT-013 is now the next runtime-proof task. RT-016A remains a later independent account-guard
evidence task and must not block the technical Bliss runtime decision.
