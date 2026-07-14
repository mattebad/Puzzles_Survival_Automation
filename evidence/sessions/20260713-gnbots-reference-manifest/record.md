# GNB-PHASE-A — normalized static reference manifest

Recorded: 2026-07-13, America/Chicago

## Boundary

- Read-only static inspection of 12 authorized free-trial JavaScript modules and metadata.
- No JavaScript, vendor binary, DLL, installer, capture script, helper, emulator service, or
  endpoint executed.
- `.local-reference/` excluded only through `.git/info/exclude`.
- No vendor source or PNG staged, copied, promoted, or made reachable from production runtime.

## Outputs

- `docs/research/gnbots_trial_reference_manifest.md`
- `docs/research/gnbots_trial_reference_manifest.json`
- `tests/test_reference_manifest.py`

Manifest entries use stable `GNB-*` identifiers and retain both source `[x,y,width,height]` and
normalized `[x1,y1,x2,y2]` geometry. Anomalous decoded values remain explicit and non-actionable.
Direct observations, inference, unresolved helpers, recovery, completion semantics, and known
vendor weaknesses are recorded.

## Verification

Command:

`python -m unittest tests.test_reference_manifest`

Result: 5 tests passed.

Validated:

- all 12 authorized modules have stable entries;
- IDs are unique;
- required flow fields exist;
- every recorded ROI satisfies `x2=x+width`, `y2=y+height`;
- production Python under `safe_action_core/`, `tasks/`, and `scripts/` contains no
  `.local-reference`, `gnbots-trial`, or decoded-script dependency;
- restrictions remain fail-closed.

## Decision

Phase A Passed. Phase B coordinate calibration is unblocked. No live runtime or game input was
used.
