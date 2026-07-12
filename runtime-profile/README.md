# Runtime-profile compatibility contract

`manifest.json` is the selected Bliss runtime profile. It is versioned separately from
recognition assets. The manifest is not a credential store and contains no account identifier.

Every future recognition asset or asset metadata record must carry:

- `asset_id`
- `asset_schema_version`
- `profile_id`
- `profile_content_sha256`
- `asset_kind`

The validator recomputes the manifest hash from canonical JSON after removing only
`profile_content_sha256`. Missing, malformed, or mismatched metadata produces
`GLOBAL_INPUT_LOCK`; it must never authorize input. Assets captured after a runtime/profile
change require a new profile version and full compatibility replay.

The `asset-metadata.*.example.json` files are development-only validator fixtures. They are
not production recognition assets and do not replace final locked-runtime recapture. The
Cash Mall reference is normal authenticated startup content; it remains subject to the bounded,
positive-recognition startup-normalization rules recorded in the manifest and plan.

Validate from the repository root:

```text
python scripts/validate-runtime-profile.py
python scripts/validate-runtime-profile.py --asset runtime-profile/asset-metadata.compatible.example.json
python scripts/validate-runtime-profile.py --asset runtime-profile/asset-metadata.mismatch.example.json
```
