# RT-003 VirtIO-GPU/VirGL trial 01

Date: 2026-07-10 (America/Chicago)

## Objective and boundary

Test the smallest host-supported VirtIO(3D) delta while preserving the QXL/SwiftShader rollback
profile. Only the dedicated `PnS-BlissOS-PoC` VM was changed. Home Assistant, Docker workloads,
host networking, the iGPU driver, and storage layout were not modified. No gameplay action or
purchase input was sent.

## Rollback

- Baseline XML: `/mnt/cache/domains/PnS-BlissOS-PoC/rollback/20260710-rt001-qxl-baseline.xml`
- Baseline SHA-256: `f8011eeed1e3f464ad317610973e74bf97f2c922c261142eab51c7f9c002624e`
- Candidate XML: `/mnt/cache/domains/PnS-BlissOS-PoC/rollback/20260710-rt003-virgl-trial-01.xml`
- Candidate SHA-256: `9ed03ee6cabedbabf30271fbffe2869b0d5c96207e90a1927c6122f5f7f97c16`
- Disk identity was preserved: `/mnt/cache/domains/PnS-BlissOS-PoC/system.qcow2`.
- Rollback command after a clean VM stop: `virsh define --validate <baseline XML>`.

## Exact XML delta

- Retained VNC.
- Added `egl-headless` with render node
  `/dev/dri/by-path/pci-0000:00:02.0-render`.
- Replaced QXL with one primary VirtIO video device.
- Added `<acceleration accel3d="yes"/>`.
- Preserved domain UUID, disk, firmware/NVRAM, CPU, memory, network, input, and watchdog settings.

The candidate passed `virt-xml-validate ... domain` and `virsh domxml-to-native qemu-argv`.
The live command line contained `-display egl-headless` and `virtio-vga-gl`.

The syntax was derived from this host's installed Unraid VM manager and checked against the
[official Unraid VirGL guidance](https://docs.unraid.net/unraid-os/using-unraid-to/create-virtual-machines/vm-setup/)
and [libvirt domain XML reference](https://libvirt.org/formatdomain.html).

## Boot and renderer results

- Manual first boot: selected `VM Options` then `QEMU/KVM - Virgl - SW-FFMPEG`.
- Android completed boot with `ro.hardware.egl=mesa`.
- Renderer: `Mesa, virgl (Mesa Intel(R) UHD Graphics 770 (ADL-S GT1))`.
- OpenGL ES: 3.2, Mesa 24.0.8.
- System display after boot: 1280×800 at 160 dpi.
- Game capture rotated correctly to 800×1280.
- Game package rendered correctly and the authenticated session persisted.
- Game resumed on Cash Mall; no purchase, confirmation, or other game tap was sent.

After the first manual selection, three cold boots with no GRUB keys each reached
`sys.boot_completed=1` using the same Mesa VirGL renderer at 1280×800. Android does not
automatically launch the game; ordinary package lifecycle control remains required.

## Capture and resource evidence

- Two portrait game frames five seconds apart had distinct SHA-256 hashes.
- End-to-end ADB screenshot/pull samples were 296 ms and 310 ms.
- Early boot QEMU sample: about 117% CPU and 5.02 GiB RSS.
- Game-render sample: about 88.8% CPU and 5.31 GiB RSS.
- `intel_gpu_top` attributed active Render/3D work to the QEMU PID; sampled client busy values
  included about 18%, 34%, and 22%, with aggregate Render/3D samples up to about 61%.
- Post-trial host memory: about 11 GiB available.
- Temperatures: CPU 38°C, PECI 41°C, motherboard 36°C, NVMe composite 48.9°C.
- Home Assistant remained running with its prior 2 GiB allocation.
- No i915/DRM reset, hang, fault, OOM, or QEMU startup error was found in the sampled logs.

## Console limitation

VNC works at OVMF/GRUB, but after the VirtIO-GL guest driver activates the VNC screenshot reports
`Display output is not active.` Android ADB PNG capture remains correct. This is not a boot or
renderer failure, but a production remote-view path such as tunneled scrcpy must be proven before
runtime selection.

## Failed/invalid attempts retained

- The first generated XML kept Unraid's redundant `enable="yes"` attribute on the egl-headless
  `gl` element; native translation passed but strict schema validation failed. Removing only that
  attribute matched the official libvirt form and passed both validations.
- `virsh shutdown` delivered an ACPI power event that opened Android's power menu. One
  coordinate-verified system `Power off` tap completed the shutdown; later `adb shell reboot -p`
  completed clean shutdowns without UI input.
- One attempted trial-2 orchestration was invalid because local PowerShell intercepted a remote
  substitution. The VM remained shut off and that attempt was not counted. The corrected trial 2
  subsequently passed.

## Offline boot evidence

With the VM cleanly stopped, the qcow2 was attached to unused `/dev/nbd15` read-only. Each
partition was mounted read-only, inspected, unmounted, and disconnected; the final checks confirmed
that `/sys/block/nbd15/pid` was absent.

- EFI config: `/EFI/BlissOS/grub.cfg`, SHA-256
  `ad642353d73bd67657d64cfe78df05f15945af216943f1221b161621658f1fe1`.
- Menu config: `/boot/grub/android.cfg`, SHA-256
  `b5090c8d99fa2f65c7c3228712d563258498f7d34d317bd127c78d150d2c42f4`.
- GRUB environment backup SHA-256:
  `cc7e18cd9bd8536b6a166aec6e0095b2f29faa04e40515baa2c508ba3c8c6dc1`.
- Timeout: five seconds.
- VirGL arguments: `HWC=drm_minigbm GRALLOC=minigbm_arcvm`.
- No-hardware arguments: `nomodeset HWACCEL=0`.
- Saved entry after selection: `VM Options -> ... QEMU/KVM - Virgl - SW-FFMPEG`.

## Rollback and restoration result

The preserved QXL XML was defined and booted through the no-hardware entry. It reached
`sys.boot_completed=1`, `ro.hardware.egl=swiftshader`, Google SwiftShader/OpenGL ES 3.0, and
1024×768 at 160 dpi. The candidate was then redefined, VirGL selected once to restore its saved
default, and Android again reached `sys.boot_completed=1` with Mesa VirGL/OpenGL ES 3.2 at
1280×800.

The game was relaunched after restoration and produced a correct 800×1280 Cash Mall frame with
the authenticated session intact and no login/tutorial/CAPTCHA/session-loss prompt. No game tap
was sent. The package was then force-stopped and Android Home selected using approved lifecycle
and system controls.

## Final status

- RT-002: passed.
- RT-003: passed, including rollback boot and candidate restoration.
- RT-004: passed using boot, game, and post-rollback aligned renderer/GPU/resource samples.
- RT-005 graphics decision: accept the VirtIO(3D)/Mesa VirGL profile for subsequent Bliss gates.
- RT-006: passed three unattended cold boots with the saved VirGL entry.

The VM was left running the candidate at Android home, game force-stopped, no gameplay automation
enabled. RT-007 portrait display locking is next. VNC inactivity after driver activation remains a
known requirement for the remote-view gate.
