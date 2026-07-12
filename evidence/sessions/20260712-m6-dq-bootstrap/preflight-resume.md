# M6-DQ-BOOTSTRAP — Resumed preflight

Recorded: 2026-07-12, America/Chicago

The prior credential blocker is cleared through the project-local process-only `.env` variables
`UNRAID_TEMP_USERNAME` and `UNRAID_TEMP_PASSWORD`. Values were not printed, copied, or written to
repository/evidence files.

## Authenticated read-only reconciliation

- Repository: `HEAD=2ca17d3`; the task remains the only M6 task in scope.
- Pre-existing unstaged entries: all eight working content hashes still match their `HEAD` blobs;
  they remain untouched and unstaged.
- Unraid host: `NAS`; read-only probe time `2026-07-12T12:19:15-05:00`.
- VM: `PnS-BlissOS-PoC` is `running`, 4 vCPU, 6 GiB configured/used memory, autostart disabled.
- RT-017 backup: `/mnt/cache/domains/PnS-BlissOS-PoC/rollback/20260711-rt017-runtime-backup/`
  exists mode `700`; backup qcow2 exists mode `600`, size `13522501632` bytes; artifact hash list
  exists mode `600`.
- Live VM disk remains `/mnt/cache/domains/PnS-BlissOS-PoC/system.qcow2`.
- Relevant temporary Docker containers: none found.
- ADB/listeners: host loopback ADB server `127.0.0.1:5037` is listening; no temporary `5038–5045`
  or guest/public `5555` listener was reported. Host `adb` is not installed, so the approved
  unprivileged worker path is required for device observation.
- External tunnel/process probe: no matching SSH tunnel, plink, scrcpy, or ADB process was reported.
- No authenticated command changed VM, game, ADB, worker, tunnel, listener, storage, or backup
  state. The game process/package state still requires direct worker observation below.

## Resume operation authorization

The next operation is a temporary UID/GID `65534:65534` host-networked Docker observer using the
already-proven RT-021 shape. It will use a cache-backed task evidence directory, read-only ADB
binary mount, read-only root, dropped capabilities, no-new-privileges, bounded CPU/memory/PIDs,
no Docker socket, no published port, and zero game input. It will capture a fresh profile/policy/
activity/frame baseline before any bounded navigation is considered.

Rollback remains removal of only the temporary observer and its local ADB server, preservation of
all output, and force-stop cleanup if required. VM XML/qcow2/profile/network state remains out of
scope.
