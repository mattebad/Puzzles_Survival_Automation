# RT-017 preflight — secured post-provisioning runtime recovery backup

Recorded: 2026-07-11, America/Chicago

## Task

- Task ID: RT-017
- Objective: preserve a restricted, restorable post-provisioning backup of the selected Bliss
  runtime without overwriting the live qcow2 or changing the selected VM configuration.
- Satisfied dependencies: RT-013 Passed with Bliss selected; RT-019 Passed with profile ID
  `pns-blissos-poc-virgl-800x1280-v1`; RT-021 Passed. The game is force-stopped and no observer,
  external tunnel, or competing live runtime experiment is active.

## Acceptance criteria

1. New backup artifacts include the qcow2, VM XML, required EFI/GRUB state, hashes, and the
   runtime-profile version without credentials or account identifiers.
2. Backup storage is restricted and the backup is restorable without overwriting the live runtime.
3. The restoration procedure is tested offline against the backup and records that no competing
   live account session was present.
4. Independent hash/manifest review supports the selected profile and rollback path.
5. The original VM and qcow2 remain intact; final runtime state is reconciled safely.

## Intended changes and operations

- Use the preflight-confirmed cache capacity and create a new task-owned backup directory only;
  refuse to reuse an existing target.
- Verify the game is force-stopped, stop only `PnS-BlissOS-PoC` using the already-approved
  dedicated-domain lifecycle path, and copy the qcow2 with no source overwrite.
- Save persistent VM XML, selected/rollback XML, EFI `grub.cfg`, `/boot/grub/android.cfg`, and
  `grubenv` through read-only NBD inspection; disconnect NBD and unmount all temporary mounts.
- Record SHA-256, size, mode, profile ID/hash, source paths, and restoration instructions.
- Run `qemu-img info/check`, XML validation, and QEMU-argv translation against an offline restore
  XML whose disk source points to the backup. Do not define, start, or undefine a duplicate VM.
- Restart only the original selected VM, verify it is running, and retain the game force-stopped.

## Verification procedure

- Independently review source/backup hashes, qcow2 metadata, XML identity, EFI/GRUB hashes,
  profile compatibility, access modes, and the no-competing-session state.
- Confirm the restore-test XML references only the backup copy, validates successfully, and does
  not alter the persistent domain or live qcow2.
- Review complete diff, secret scan, final VM/game/ADB state, rollback state, and all retained
  failures before marking RT-017 Passed.

## Evidence, rollback, permissions, dependencies

- Evidence directory: `evidence/sessions/20260711-rt-017-runtime-backup/`.
- Backup target: task-owned restricted cache storage under
  `/mnt/cache/domains/PnS-BlissOS-PoC/rollback/20260711-rt017-runtime-backup/`; exact path and
  hashes are recorded after creation.
- Rollback: retain the original live qcow2 and VM XML; if a backup operation fails, remove only
  the incomplete task-owned backup after preserving failure evidence. Never overwrite the source.
- Permissions required: process-local Unraid SSH root for the scoped dedicated-VM stop/start,
  cache copy, read-only NBD inspection, metadata hashing, and offline validation. No host reboot,
  unrelated workload, firewall, network, public ADB, or game input.
- Expected credential dependency: the already-provided SSH credential may be used only in
  process-local environment state and never in repository/evidence/logs/scripts/command history.
- Expected manual-user dependency: none; no account, login, tutorial, CAPTCHA, profile navigation,
  or credential operation is required.

## Safety boundary

The source VM is dedicated and currently running with the game force-stopped. The only live
operation is a bounded stop/copy/start of this domain; no duplicate domain is defined, no source
disk is replaced, and no gameplay input is sent.
