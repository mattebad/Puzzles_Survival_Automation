# GNB-PHASE-B — coordinate calibration

Recorded: 2026-07-13, America/Chicago

## Outputs

- `calibration/transform.py`
- `docs/research/gnbots_bliss_coordinate_calibration.md`
- `docs/research/gnbots_bliss_coordinate_calibration.json`
- `tests/test_coordinate_calibration.py`

## Candidate models

Tested direct 2×, source top/bottom 12-logical-pixel viewport insets, independent X/Y scaling,
and fitted axis-aligned affine scale plus offset. Point and normalized xyxy ROI transforms,
residuals, containment, and correction support are deterministic.

Five retained correspondences cover Quest, Daily tab, More, Rankings target bounds, and standard
Back. Direct 2× is retained as simplest global starting candidate. A provisional
`bottom-navigation` correction is supported by Quest and More. No correction is invented for
single-correspondence Back or Rankings families.

Every candidate and report is explicitly non-authorizing. Production still requires current
Bliss-native target recognition and immediate-frame binding.

## Important diagnosis

Raw 800×1280 word-level OCR measured Rankings bounds `(602,1138)-(690,1167)`, center `(646,1152)`.
The prior broad target `(0,1120)-(800,1185)` centered at `(400,1152)` is not a valid Rankings
binding and can intercept the Help/guide control. No new live input was sent.

## Verification

`python -m unittest tests.test_coordinate_calibration tests.test_reference_manifest`

Result: 16 tests passed.

Missing Personal Might, Claim-positive, Town/world, and march screens remain explicit evidence
dependencies. Phase B Passed; Phase C is unblocked.
