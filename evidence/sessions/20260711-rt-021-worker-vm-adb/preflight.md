# RT-021 preflight — unprivileged Unraid worker-to-VM ADB path

Recorded: 2026-07-11, America/Chicago

## Task

- Task ID: RT-021
- Objective: prove the actual production communication path from an unprivileged Unraid
  container to the selected Bliss VM without an external SSH tunnel.
- Satisfied dependencies: RT-013 Passed with Bliss selected; RT-019 Passed with profile ID
  `pns-blissos-poc-virgl-800x1280-v1`; RT-008 private libvirt networking retained; no RT-012
  observer, external tunnel, or competing runtime experiment is active.

## Acceptance criteria

1. A temporary least-privilege Unraid container reaches the private guest ADB endpoint with no
   external tunnel active.
2. The container captures a valid `800x1280` PNG and observes package/lifecycle state without
   sending gameplay input.
3. The same container reconnects after the approved dedicated-guest restart path.
4. The endpoint remains inaccessible from a normal LAN client and no host LAN `:5555` listener
   is introduced.
5. Container privileges, mounts, image, network, and configuration are reproducible and contain
   no unnecessary host authority.
6. Temporary runtime artifacts are removed and the selected VM/network state is preserved.

## Intended changes and operations

- Read-only host inventory: VM state, private guest endpoint, host listeners, image identity, and
  available ADB binary.
- First attempt: temporary Docker bridge-network container, UID `65534:65534`, read-only root,
  no-new-privileges, all capabilities dropped, bounded CPU/memory/PIDs, no Docker socket, no
  published ports, and read-only ADB binary mount. The container starts its own ADB server in its
  tmpfs home and connects directly to `192.168.122.79:5555`.
- Observe package state and capture one frame; use only ADB observation/lifecycle commands.
- If the bridge path passes, perform one approved dedicated-guest restart/reconnect trial and a
  LAN negative probe. If it fails, retain the failure evidence and revise the network hypothesis
  before any smallest justified fallback. Do not use more than three materially different failed
  attempts.
- Remove the temporary container and record final state; update evidence, BACKLOG.md, the plan,
  and CURRENT_HANDOFF.md only after the acceptance review.

## Verification procedure

- Record container inspect/configuration and runtime identity, UID, capabilities, mounts, network,
  image digest, and no-published-port state.
- Record direct ADB connect, device state, package/activity observation, PNG dimensions/hash,
  lifecycle/reconnect result, and input-command audit.
- Probe `nas.local:5555` and the private guest endpoint from a normal LAN client without broadening
  firewall/routing; retain the negative result and do not expose ADB publicly.
- Independently review all acceptance criteria, failed attempts, final runtime state, rollback,
  repository diff, and secret scan before marking RT-021 Passed.

## Evidence, rollback, permissions, dependencies

- Evidence directory: `evidence/sessions/20260711-rt-021-worker-vm-adb/`.
- Rollback: stop/remove only the temporary test container and its local tmpfs/evidence mount;
  retain the existing private VM network and selected runtime. If guest restart is used, return
  the dedicated VM to the running, game-force-stopped state through the approved path.
- Permissions required: repository write access; process-local Unraid SSH administrative access
  for read-only orchestration and the explicitly scoped dedicated-VM lifecycle check. No host
  reboot, firewall broadening, VM XML change, qcow2 change, public ADB/viewer exposure, or
  gameplay input.
- Expected credential dependency: the already-provided Unraid SSH credential may be used only in
  process-local environment state and never in evidence, logs, scripts, or command history.
- Expected manual-user dependency: none; no login, account switching, state/server selection,
  profile navigation, CAPTCHA, or credential action is required.

## Safety boundary

The game remains force-stopped before the test. The first container operation is observe-only;
any guest restart is the existing approved dedicated-VM lifecycle path and is followed by ADB,
display, package, and game-force-stop reconciliation. No gameplay input or Cash Mall navigation
is authorized.
