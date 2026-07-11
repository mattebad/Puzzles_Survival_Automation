# Initial retained-evidence record

Recorded: 2026-07-10, America/Chicago

## Scope

This record inventories evidence already present before new runtime work. No VM, guest, game,
host, network, or storage mutation was performed.

## Verified observations

- Fourteen PNG artifacts were hashed and dimension-checked in `evidence/manifest.csv`.
- `boot-menu.png` shows Bliss OS 16.9.7 live, default, PC-mode, installation, VM Options,
  debugging, and advanced menu entries.
- `vm-options.png` shows QEMU/KVM VirGL SW-FFMPEG and VBox/VMWare no-hardware choices.
- `live-boot-35s.png` and `live-qemu-virgl-sw-60s.png` are byte-identical SHA-256
  `c5b6a9...d1a54e`, supporting a stalled-frame observation for that earlier VirGL trial.
- `live-vbox-nohw-60s.png` reached the Android setup screen at 1280×800 in the earlier live trial.
- `orientation-fixed.png` shows an installed Android home surface at 1024×768 with the game icon.
- `after-app-restart-45s.png` is a 1024×768 retained post-restart frame.

These images do not contain the current VM XML, installed GRUB configuration, Android renderer
properties, or synchronized host metrics. They therefore do not satisfy RT-001 or justify
changing/rejecting the candidate by themselves.

## Live-access attempt

Command shape: strict-host-key SSH in batch mode to the plan-documented `root@nas.local` endpoint,
then read-only `hostname`, time, and `virsh list --all`.

Initial result: host was reachable, but key authentication failed. The user subsequently authorized
temporary password authentication. It was used only in process memory and was not written to the
repository or evidence.

## Rollback state

The existing VM and evidence were not changed. The known-working SwiftShader configuration is
presumed to remain on the host, but it is not yet recoverable from repository evidence because
its inactive XML has not been captured.

## Next action

Resolve the newly observed in-game authentication hard-stop manually and confirm the expected
account remains active. Do not tap the dialog or restart the VM automatically. After manual
resolution, capture a fresh observe-only frame and complete RT-001 before designing any graphics
delta.

## Files added

- `README.md`
- `BACKLOG.md`
- `evidence/manifest.csv`
- `scripts/collect-runtime-baseline.ps1`
- this record

## Verification executed

- Parsed `scripts/collect-runtime-baseline.ps1` with the PowerShell language parser. The first
  run found an invalid VM-name quoting expression; it was corrected and the parser then passed.
- Recomputed SHA-256 and decoded dimensions for all 14 manifest entries: passed.
- Inspected the five boot/menu/display screenshots cited above visually.
- Checked the local SSH agent: no agent socket/key was available.

No gameplay input was enabled or sent.

## Live RT-001 continuation

- Dedicated domain: `PnS-BlissOS-PoC`, UUID `5500a07f-4352-4ce5-b1cf-7cf668e3a9f4`.
- State at collection: running, autostart disabled, 4 vCPU, 6 GiB RAM.
- Disk: `/mnt/cache/domains/PnS-BlissOS-PoC/system.qcow2`, 64 GiB virtual capacity,
  approximately 13.4 GB allocated.
- Network: libvirt `default`, VirtIO NIC, `192.168.122.79/24`.
- Working rollback graphics profile: QXL with VNC; no VirGL render node in inactive XML.
- Host-side XML backup:
  `/mnt/cache/domains/PnS-BlissOS-PoC/rollback/20260710-rt001-qxl-baseline.xml`, mode 0600,
  SHA-256 `f8011eeed1e3f464ad317610973e74bf97f2c922c261142eab51c7f9c002624e`.
- Guest ABI list: x86_64, arm64-v8a, x86, armeabi-v7a, armeabi.
- Renderer: Google SwiftShader, OpenGL ES 3.0; encoded OpenGL version `196608`.
- Display: physical 1024×768 at 160 dpi; user rotation 0; accelerometer rotation disabled.
- Game package version: `7.0.278`.
- Host at sample: about 12 GiB memory available; CPU 50°C; PECI 49.5°C; NVMe composite
  48.9°C; PoC QEMU approximately 271% CPU and 6.38 GiB RSS. Home Assistant remained running.
- Full command outputs and hashes: `evidence/sessions/20260710-220953-rt-001-baseline/`.

The lossless `guest-baseline.png` frame revealed the message “Your account has been logged in on
another device.” This is an authentication/session hard-stop under the service plan. No Confirm
tap or other game input was sent. RT-001 and all VM restart/graphics work are externally blocked
until manual resolution.
