# RT-021 Unraid worker-to-VM ADB path — Passed with explicit network limitation

Recorded: 2026-07-11, America/Chicago

## Decision

RT-021 Passed. An unprivileged temporary Unraid Docker worker reached the private Bliss guest
ADB endpoint without an external SSH tunnel, captured valid frames, observed the provisioned
package, reconnected after the approved dedicated-VM restart path, and passed the normal-LAN
negative checks. The temporary containers were removed and the selected VM remained running.

The environment-specific network result is explicit: the default Docker bridge path returned
`Connection refused` to the private libvirt guest. The passing proof therefore used Docker host
networking only after that bounded failure, with UID `65534:65534`, read-only root, all capabilities
dropped, no-new-privileges, bounded resources, no Docker socket, no published ports, a read-only
ADB binary mount, and an isolated container-local ADB server port `5038`. This is a measured
host-network boundary, not a public ADB exposure or an external tunnel. A future production
worker should retain this explicit isolation or replace it with a dedicated point-to-point
worker/libvirt network before deployment.

## Runtime identity and attempts

- VM: `PnS-BlissOS-PoC`, final state `running`; game force-stopped; no observer or external SSH
  tunnel active.
- Image: `monarch-gpt-wrapper-api:latest`, digest
  `sha256:4febd12f7989492ef63bebcf49376b8377579495067cf37457f959f9f692e349`.
- Guest endpoint: `192.168.122.79:5555` on private libvirt NAT.
- ADB binary: `/mnt/cache/domains/PnS-BlissOS-PoC/tools/platform-tools/adb`, mounted read-only.
- Attempt 1, Docker bridge: UID 65534 container started its own ADB server, direct connection
  returned `Connection refused`, and the retained frame was zero bytes. No game input occurred.
- Attempt 2, host network with `ADB_SERVER_SOCKET`: ADB treated `127.0.0.1:5038` as a remote
  server and could not start; zero-byte frame. This was a tool configuration failure, not a
  transport decision.
- Attempt 3, host network with `ANDROID_ADB_SERVER_PORT=5038`: direct connection succeeded;
  the container reported `device`, Android `13`, and installed `com.global.ztmslg` package paths.
  The historical activity component used in an earlier observer was not present, so the launch
  returned Activity-not-found; this is retained and no alternate activity was guessed. A valid
  800x1280 Android Home/taskbar frame was captured and the game was force-stopped.

## Reconnect evidence

The passing worker container requested `adb reboot -p` after force-stopping the game. The dedicated
VM reached `shut off`; only `PnS-BlissOS-PoC` was then started with `virsh start`. After one natural
20-second boot interval, a fresh UID-65534 host-network container connected directly to the guest:

- ADB state: `device`.
- `sys.boot_completed`: `1`.
- Physical size: `1280x800`.
- Override size: `800x1280`.
- Physical density: `160`.
- Package paths: present for `com.global.ztmslg` and its split APKs.
- Reconnect frame: valid `800x1280` PNG, 272443 bytes, SHA-256
  `278F69B4AF633F53F02C51D465F824B388A6D6F29F7B058AC06EFAF724BCA539`.
- The post-restart frame showed Android's non-secure keyguard with routine setup notifications,
  not a game or authentication state. No credential was entered and no game input occurred.

The documented non-secure keyguard sequence was attempted during final reconciliation. The
retained window-policy output reports `mIsSecure=false` but `mInputRestricted=true`; no credential
prompt was automated. The game remains force-stopped, and this known startup-keyguard condition
is retained for the later startup health gate.

## Capture evidence

| Frame | Result | SHA-256 |
|---|---|---|
| `remote-cache/host-attempt-3/frame-host-attempt-3.png` | valid `800x1280`, 283216 bytes | `BB1108E76B84D113097D35CC7F5D9CA48666085E9047768BD7D873102D79BFC8` |
| `remote-cache/reconnect-corrected/frame-reconnect.png` | valid `800x1280`, 272443 bytes | `278F69B4AF633F53F02C51D465F824B388A6D6F29F7B058AC06EFAF724BCA539` |
| `remote-cache/final-reconcile/frame-final-reconcile.png` | valid `800x1280`, 265543 bytes | `3B9F8B7411E144D41BCA7C7FF2979453B7364EB0DDDE71C5774DD2EE6C148714` |

The two failed attempts' zero-byte frames are retained under their attempt directories and were
not filtered from review.

## Criterion review

| Criterion | Decision | Evidence / rationale |
|---|---|---|
| Unprivileged worker reaches private ADB without external tunnel | Passed with limitation | Host-network attempt 3 connected directly to `192.168.122.79:5555` with no SSH tunnel. Docker bridge refusal is retained; host networking is explicitly justified and constrained. |
| Screenshot capture succeeds | Passed | Three independently validated PNGs are `800x1280`; hashes and sizes are retained. |
| Package status/lifecycle observation without gameplay input | Passed | Android 13, package paths, activity state, and force-stop cleanup were observed. The invalid activity launch is retained; no control was guessed. |
| Reconnect after guest restart | Passed | `adb reboot -p` → dedicated VM `shut off` → `virsh start` → fresh worker ADB `device`, boot complete, display/profile, package, and PNG evidence. |
| Normal LAN cannot reach ADB | Passed | Windows probes to `192.168.122.79:5555` and `nas.local:5555` both returned `False`; final host listener review found no `:5555` or temporary `:5038` listener. |
| Least privilege and reproducibility | Passed with host-network limitation | UID 65534, read-only root, all caps dropped, no-new-privileges, 256 MiB/0.5 CPU/64 PIDs, no Docker socket, no published ports, read-only ADB mount, fixed image digest, and task-scoped evidence mount are retained in inspect JSON. |
| Temporary artifacts removed and runtime preserved | Passed | All RT-021 containers were removed; VM is `running`; game is force-stopped; no VM XML, qcow2, firewall, routing, or public exposure changed. |

## Rollback and next work

Rollback is complete: temporary containers and their process-local ADB servers are gone; private
VM networking and the selected runtime are unchanged. The non-secure keyguard remains visible
after restart reconciliation, with no credential action attempted. RT-017 secured recovery backup
is the next ready infrastructure task; startup-navigation input remains prohibited until the
required infrastructure gates are complete.

## Review conclusion

Every RT-021 acceptance criterion is supported by retained positive, negative, and failure
evidence. The Docker bridge failure, host-network justification, invalid activity component,
wrapper failures, and non-secure keyguard limitation are explicit. No public ADB, external tunnel,
gameplay input, account operation, credential, or unrelated service change occurred.
