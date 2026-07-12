# Synthetic fail-closed validation results

Recorded: 2026-07-12, America/Chicago

- `manifest-missing-profile.json`: rejected, exit 1; missing profile metadata was detected.
- `manifest-mismatched-profile.json`: rejected, exit 1; profile identifier mismatch was detected.
- `manifest-stale-production.json`: rejected, exit 1; stale production asset was rejected.
- `container-output.txt` supplied as a frame: rejected, exit 1; non-PNG input was rejected.
- Temporary black `800x1280` PNG: rejected, exit 1; black frame was rejected.

The temporary black fixture was created outside the repository and removed after the check. These
fixtures are validation-only and are not executable production assets.
