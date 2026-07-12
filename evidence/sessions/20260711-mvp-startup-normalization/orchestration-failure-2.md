# Live observe-only orchestration failure 2

Recorded: 2026-07-11, America/Chicago

- Operation: corrected temporary unprivileged Unraid worker with the evidence mount fixed.
- Result: container started as UID/GID `65534:65534` but ADB aborted before connection because its
  default home was `/nonexistent` and it could not create `/nonexistent/.android`.
- Captures: `frame-before.png` and `frame-after.png` were zero bytes; no keyguard or game input
  command reached the device because ADB initialization failed.
- Container identity: `765aac0c5f7122a2993e1bf2cb1dc06918ee272b59e0ad908597685dcc9745fa`.
- Exit code: `134`.
- Runtime impact: no VM, game, display, or ADB guest state changed; container was removed after
  the failure. Complete inspect/log/output files are retained under
  `remote-cache/20260711-live-observe-2039/`.
- Revised hypothesis: explicitly set the temporary container `HOME` to writable `/tmp` while
  preserving the same least-privilege, read-only, host-network, and no-game-input boundary.
