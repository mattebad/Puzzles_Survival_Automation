# M6-DQ-BOOTSTRAP — Observer orchestration failure 2

Recorded: 2026-07-12, America/Chicago

## Attempt

The second observer corrected the task-owned evidence-directory ownership and retained the same
RT-021 constraints: UID/GID `65534:65534`; host networking only for the private guest path;
read-only root; all capabilities dropped; no-new-privileges; 64-PID, 256 MiB, and 0.5 CPU limits;
read-only ADB binary mount; no Docker socket; no published port; and cache-backed evidence.

## Result

The worker started with UID/GID `65534:65534`, but ADB aborted before connecting because the
read-only container root made `/tmp/.android` unwritable:

`adb_utils.cpp:316 Cannot mkdir '/tmp/.android': Read-only file system`

No screenshot, device connection, game command, input, package lifecycle operation, VM change, or
runtime mutation occurred. The temporary container was removed by `--rm`; the failure log remains
in the cache-backed task evidence directory.

## Revised hypothesis and correction

The remaining failure is temporary ADB home-state initialization under a read-only root, not an
ADB transport or game-state failure. The smallest correction is to add only a bounded writable
`/tmp` tmpfs to the same unprivileged container and rerun one observe-only baseline. No image,
VM, game, network, or unrelated container will be modified.
