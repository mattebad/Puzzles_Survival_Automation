# Live observe-only orchestration failure 1

Recorded: 2026-07-11, America/Chicago

- Operation: start the task-scoped unprivileged Unraid worker for fresh observation and the
  approved OS-only keyguard reconciliation.
- Result: failed before container creation.
- Failure: Docker rejected
  `type=bind,src=/mnt/cache/puzzle-survival-runtime/mvp-startup-normalization/20260711-live-observe-2037,dst=/evidence,rw`
  because `rw` is not a valid `--mount` key/value field for this Docker version.
- Runtime impact: no container was created; no VM, game, ADB, display, or input state changed.
- Retained remote target: `/mnt/cache/puzzle-survival-runtime/mvp-startup-normalization/20260711-live-observe-2037/`.
- Revised hypothesis: omit the default read-write flag from the evidence bind mount and retain
  the same fixed image, host-network boundary, UID 65534, read-only root, capability drop,
  resource limits, and read-only ADB mount.
