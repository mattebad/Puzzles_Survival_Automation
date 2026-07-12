# RT-017 secured post-provisioning runtime recovery backup — Passed

Recorded: 2026-07-11, America/Chicago

## Decision

RT-017 Passed. A restricted, restorable post-provisioning backup of the selected Bliss runtime is
preserved on cache storage without overwriting the live qcow2. The backup is bound to the RT-019
profile, includes VM/graphics rollback and EFI/GRUB state, and passed offline qcow2/XML restore
validation. The original dedicated VM was restarted after the controlled copy and remains the
only defined/running domain involved.

## Backup identity and access

- Backup directory: `/mnt/cache/domains/PnS-BlissOS-PoC/rollback/20260711-rt017-runtime-backup/`.
- Directory mode: `700`; all backup files, including qcow2, XML, EFI/GRUB, manifest, and restore
  outputs: `600`.
- Source qcow2 at the stopped-copy boundary: `/mnt/cache/domains/PnS-BlissOS-PoC/system.qcow2`,
  `13522501632` bytes, mode `644`.
- Backup qcow2: `system.qcow2`, `13522501632` bytes, mode `600`, SHA-256
  `9631805e29767a1abacb5703ec570acbd9eacaadaaabfa78ab91802558636161`.
- Source and backup hashes matched at the copy boundary. Starting the original VM afterward is
  allowed to update live qcow2 metadata; the backup remains the immutable stopped-state restore
  point.
- Profile binding: `pns-blissos-poc-virgl-800x1280-v1`, profile content hash
  `195c145e5779b13d1f65708a6b3ef31f6cbdb934b33854f886f1091aa583d742`.
- Complete backup hashes and restricted artifact inventory: `remote-backup/artifact-sha256.txt`.

## Included artifacts

- `system.qcow2`: stopped-state copy of the selected 64 GiB virtual disk.
- `persistent-domain.xml`: saved persistent VM XML, SHA-256
  `45cc3319bf60075fab822a213de9a20e10a15cad40afb08b0c3229abc0cebf16`.
- `selected-virgl.xml`: selected candidate XML, SHA-256
  `9ed03ee6cabedbabf30271fbffe2869b0d5c96207e90a1927c6122f5f7f97c16`.
- `baseline-qxl.xml`: RT-001 QXL/SwiftShader rollback XML, SHA-256
  `f8011eeed1e3f464ad317610973e74bf97f2c922c261142eab51c7f9c002624e`.
- `efi/EFI/BlissOS/`: complete EFI directory, including `grub.cfg`; the extracted `grub.cfg`
  SHA-256 is `ad642353d73bd67657d64cfe78df05f15945af216943f1221b161621658f1fe1`.
- `boot/grub/android.cfg`: SHA-256
  `b5090c8d99fa2f65c7c3228712d563258498f7d34d317bd127c78d150d2c42f4`.
- `boot/grub/grubenv`: SHA-256
  `cc7e18cd9bd8536b6a166aec6e0095b2f29faa04e40515baa2c508ba3c8c6dc1`.
- `profile-binding.json`: RT-019 profile ID/hash and RT-017 source VM binding.
- `restore-test.xml`: offline XML whose disk source points only to the backup qcow2, SHA-256
  `93fa5c2aefccf69bb05f9ef80b1af6f852cf865290247610d51035475bcc47fe`.
- `restore-qemu-argv.txt`: successful QEMU argument translation, SHA-256
  `d22b3e722fc27582c434a8d81d19efaecc9cb4b5075976e26132550515b455ea`.

## Controlled procedure and restore test

1. Verified cache capacity before mutation: approximately 1.75 TB available and source qcow2
   approximately 13.5 GB.
2. Verified the game was force-stopped, stopped only `PnS-BlissOS-PoC`, and confirmed `shut off`.
3. Copied the source qcow2 to a new target with no-overwrite check, then matched source/backup
   hashes and restricted the target.
4. Attached the source qcow2 through `/dev/nbd15` read-only. p1 was vfat `BLISS_EFI`; p2 was
   ext4 `BlissOS` and was mounted `ro,noload` because it reported a journal-recovery marker.
5. Copied EFI/GRUB state, disconnected NBD, removed only empty temporary mount directories, and
   verified no NBD pid remained.
6. Created `restore-test.xml` by changing only its disk source to the backup copy. The persistent
   XML retained the original live source path.
7. `virt-xml-validate restore-test.xml domain` passed; `virsh domxml-to-native qemu-argv` passed;
   `qemu-img info --force-share` reported qcow2, virtual size `68719476736`, actual size
   `13530874880`, `dirty-flag=false`, and `corrupt=false`; `qemu-img check --force-share` returned
   `No errors were found on the image.`
8. No duplicate domain was defined, started, or undefined. No competing account session was
   present because the selected VM was shut off during copy/restore validation and the game was
   force-stopped before and after the task.
9. Restarted only the original `PnS-BlissOS-PoC`; final `virsh domstate` is `running`. No public
   ADB listener, external tunnel, gameplay input, account operation, or host reboot occurred.

## Criterion review

| Criterion | Decision | Evidence / rationale |
|---|---|---|
| Complete qcow2/XML/EFI/GRUB backup artifacts and hashes | Passed | Restricted cache target, matching qcow2 hash, persistent/selected/baseline XML, complete EFI tree, `android.cfg`, `grubenv`, and artifact hash list are retained. |
| Runtime-profile version bound to backup | Passed | `profile-binding.json` binds RT-019 profile ID and canonical hash; manifest and RT-019 evidence are retained. |
| Restricted access | Passed | Backup directory mode 700 and every file mode 600, including qcow2 and restore artifacts. |
| Restoration procedure recreates selected profile without overwriting live runtime | Passed | Backup-only restore XML validates and translates to QEMU argv; no duplicate domain was defined and persistent/live XML was not changed. |
| Restore testing without competing live account session | Passed | Original VM was shut off during copy/restore validation; game was force-stopped; no account or gameplay action occurred. |
| Independent hash/manifest review | Passed | Artifact list, source/backup digest, RT-003 boot hashes, RT-019 profile binding, qcow2 info/check, XML validation, and final state are retained. |
| Original runtime and rollback state preserved | Passed | Original VM restarted and is running on selected profile; source path and RT-001/RT-003 rollback artifacts remain intact; no NBD mount remains. |

## Rollback and next work

RT-017 rollback is the original selected VM and qcow2, which were never overwritten. The backup
is an additional restore point and can be disabled/removed only through an explicitly scoped
future retention operation. RT-017 is complete; startup-normalization work may begin only under
its separate observe/dry-run/supervised validation gates.

## Review conclusion

All RT-017 acceptance criteria are supported by retained artifacts and independent validation.
The wrapper, NBD, and mount anomalies are preserved in `orchestration-failures.md`; no failed
operation was hidden or treated as a backup success.
