# RT-019 versioned runtime-profile manifest — Passed

Recorded: 2026-07-11, America/Chicago

## Decision

RT-019 Passed. The selected Bliss runtime now has a versioned manifest, an immutable profile ID,
a recomputable canonical content hash, an asset compatibility contract, and a fail-closed
validator. Missing or mismatched asset metadata produces `GLOBAL_INPUT_LOCK` before any input.

This task records the runtime contract only. It does not change the VM, qcow2, GRUB, ADB, game,
account, or startup state, and it does not create production recognition assets or authorize
gameplay input.

## Manifest and validator

- Manifest: `runtime-profile/manifest.json`.
- Schema: `runtime-profile/schema.json`.
- Validator: `scripts/validate-runtime-profile.py`.
- Documentation: `runtime-profile/README.md`.
- Profile ID: `pns-blissos-poc-virgl-800x1280-v1`.
- Profile version: `1.0.0`.
- Manifest canonical content SHA-256: `195c145e5779b13d1f65708a6b3ef31f6cbdb934b33854f886f1091aa583d742`.
- Hash procedure: remove only `profile_content_sha256`, serialize with sorted keys, compact
  separators, UTF-8 encoding, and SHA-256 the resulting bytes.
- Compatibility metadata required on every future asset: `asset_id`, `asset_schema_version`,
  `profile_id`, `profile_content_sha256`, and `asset_kind`.
- Mismatch/missing metadata action: `GLOBAL_INPUT_LOCK`.
- The compatible and mismatched metadata JSON files are development-only validator fixtures; the
  Cash Mall PNG remains development/reference material and is not a production asset.

## Read-only runtime metadata review

The selected runtime remained unchanged during review:

- `virsh domstate PnS-BlissOS-PoC`: `running`.
- Current `virsh dumpxml` SHA-256: `428a9c62216acfbd1b17d9eda4219c28dafc8af5f2337fdea1455397044d1090`.
  This is a live XML serialization and can differ from the selected saved candidate because it
  includes runtime state. The compatibility source remains the preserved candidate XML.
- Selected candidate XML SHA-256: `9ed03ee6cabedbabf30271fbffe2869b0d5c96207e90a1927c6122f5f7f97c16`.
- RT-001 rollback XML SHA-256: `f8011eeed1e3f464ad317610973e74bf97f2c922c261142eab51c7f9c002624e`.
- Active qcow2: `/mnt/cache/domains/PnS-BlissOS-PoC/system.qcow2`, format `qcow2`, virtual size
  `68719476736` bytes, actual size `13530088448` bytes at review, `dirty-flag=false`,
  `corrupt=false`.
- The first read-only `qemu-img info` attempt correctly refused the active image's shared write
  lock. The explicit `--force-share` read-only inspection then succeeded; the limitation and
  output are retained here rather than bypassed by stopping or altering the VM.
- Retained GRUB/EFI hashes remain the RT-003 values in the manifest and supporting record:
  EFI `ad642353d73bd67657d64cfe78df05f15945af216943f1221b161621658f1fe1`, Android config
  `b5090c8d99fa2f65c7c3228712d563258498f7d34d317bd127c78d150d2c42f4`, and grubenv
  `cc7e18cd9bd8536b6a166aec6e0095b2f29faa04e40515baa2c508ba3c8c6dc1`.

## Criterion review

| Criterion | Decision | Evidence |
|---|---|---|
| Complete versioned runtime-profile manifest | Passed | `runtime-profile/manifest.json` records Bliss/Android, VM, XML, qcow2, GRUB, graphics, display, package, transport, startup, account-guard, rollback, and evidence facts. |
| Immutable profile identifier and verifiable hash | Passed | Profile ID/version and canonical SHA-256 are recorded above; the validator recomputes the digest. |
| Asset compatibility schema | Passed | `runtime-profile/schema.json` and manifest compatibility section require profile ID/hash and schema version. |
| Reject missing or mismatched compatibility | Passed | Validator exit 2 and `GLOBAL_INPUT_LOCK` for the intentional mismatch fixture; output retained in `validation-output.txt`. |
| Future asset documentation and global input lock | Passed | `runtime-profile/README.md` requires metadata and says profile changes require recapture/replay; validator never authorizes input and fails closed. |
| Independent XML/qcow2/GRUB/hash review | Passed with active-image limitation | Read-only host metadata and retained RT-003/RT-013 hashes agree with the manifest. Active qcow2 content hash is deferred to RT-017 because the image is live; no storage mutation was attempted. |
| Secret/account safety | Passed | No credentials, numeric account IDs, profile navigation, login, account switching, purchases, or gameplay input were used or stored. |

## Rollback and final state

- Rollback is documentation/asset gating only: disable the new manifest or assets that lack a
  matching profile; retain RT-013's selected runtime and RT-001/RT-003 rollback artifacts.
- VM remains running on VirtIO(3D)/Mesa VirGL; game remains force-stopped; no observer or external
  ADB tunnel is active; ADB remains private/loopback-only.
- No qcow2, VM XML, GRUB, display, network, ADB, or game state was changed.

## Review conclusion

All RT-019 acceptance criteria are supported by retained files and repeatable validator output.
The active-image hash limitation is explicit and assigned to RT-017's secured backup scope; it is
not concealed or treated as a runtime rejection.
