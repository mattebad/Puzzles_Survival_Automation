# RT-019 preflight — versioned runtime-profile manifest

Recorded: 2026-07-11, America/Chicago

## Task

- Task ID: RT-019
- Objective: lock the selected Bliss runtime as a versioned, reproducible profile and define
  the compatibility contract that future recognition assets must carry before input.
- Satisfied dependencies: RT-013 Passed with Bliss selected; RT-017 is parallel and is not a
  prerequisite. RT-008 private networking and RT-013 selected-profile facts are available as
  evidence inputs.

## Acceptance criteria

1. A complete versioned runtime-profile manifest records the selected Bliss/Android, VM, XML,
   qcow2, GRUB, renderer, display, package, ADB isolation, startup/keyguard, account-guard,
   rollback, and evidence facts without credentials or sensitive account identifiers.
2. The manifest has an immutable profile identifier and a verifiable content hash.
3. An asset compatibility schema requires the profile identifier/hash and schema version.
4. A validator rejects missing, malformed, or mismatched profile/asset compatibility metadata.
5. Future asset documentation requires profile compatibility metadata and locks all input on
   mismatch; no gameplay input is implemented or authorized by RT-019.

## Intended changes and operations

- Perform read-only metadata inspection of the selected VM XML, qcow2 identity, EFI/GRUB hashes,
  and existing RT-013 evidence. Do not alter VM or storage state.
- Add the minimum versioned manifest, JSON Schema, validator, and development-only compatible /
  mismatched metadata examples needed to prove the contract.
- Add RT-019 evidence containing validation outputs, hash calculations, and a criterion review.
- Update BACKLOG.md, the canonical plan only for the stable manifest/schema fact, and
  CURRENT_HANDOFF.md; run consistency and secret scans; inspect the diff; create one RT-019
  task-scoped commit.

## Verification procedure

- Independently compare each manifest field with RT-013 and the read-only runtime metadata.
- Validate the manifest against the schema and recompute its canonical content hash.
- Run the validator against a compatible asset metadata example and an intentionally mismatched
  example; confirm the mismatch is rejected with the global input-lock outcome.
- Review absence of credentials, account IDs, gameplay input, VM mutations, and unrelated files.

## Evidence, rollback, permissions, dependencies

- Evidence directory: `evidence/sessions/20260711-rt-019-runtime-profile-manifest/`.
- Rollback: remove or disable only the new manifest/schema/validator and future assets that lack
  compatibility evidence; retain the selected runtime and RT-013 rollback artifacts. No runtime
  rollback command is needed.
- Permissions required: repository write access; read-only SSH access to inspect selected VM
  metadata. No host mutation, VM lifecycle operation, storage write, ADB input, or game input.
- Expected credential dependency: the already-provided Unraid SSH credential may be used only in
  process-local environment state for read-only inspection; it must not enter files or output.
- Expected manual-user dependency: none.

## Safety boundary

The VM remains running on the selected profile, the game remains force-stopped, ADB remains
private/loopback-only, and no observer or external tunnel is active. RT-019 does not authorize
startup navigation, Cash Mall input, account/profile navigation, purchases, or gameplay.
