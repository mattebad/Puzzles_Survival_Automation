# M6-DQ-BOOTSTRAP — Observer orchestration failure 1

Recorded: 2026-07-12, America/Chicago

## Attempt

The first temporary observer used the approved RT-021 shape: host networking only for the private
guest path; UID/GID `65534:65534`; read-only root; all capabilities dropped; no-new-privileges;
64-PID, 256 MiB, and 0.5 CPU limits; read-only ADB binary mount; no Docker socket; no published
port; and cache-backed evidence at
`/mnt/cache/puzzle-survival-runtime/m6-dq-bootstrap/20260712-resume-observe/`.

## Result

The container exited before starting ADB because `/evidence/worker-output.txt` could not be
created. The task evidence directory had been created as mode `700` owned by `root:root`, while
the worker ran as UID/GID `65534:65534`. No screenshot, ADB command, game input, package lifecycle
operation, VM change, or runtime mutation occurred. The temporary container was removed by
`--rm`.

## Revised hypothesis and correction

The failure is an evidence-mount ownership/permission mismatch, not an ADB or runtime failure.
The smallest correction is to change ownership only on this task-owned cache evidence directory
to UID/GID `65534:65534`, retain the same read-only worker and network restrictions, and rerun one
observe-only baseline. No unrelated storage or container will be modified.
