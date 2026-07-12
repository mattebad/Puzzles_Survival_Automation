# M6-DQ-BOOTSTRAP — Detector defect 2

Recorded: 2026-07-12, America/Chicago

## Observation

The fresh final-runtime Daily Quest frame visibly contains the Quest title, selected Daily Quest
tab, milestone points, `Daily Quest Pts: 0`, reset countdown, incomplete rows, and multiple Go
controls. The first bootstrap recognizer run abstained because its `daily_header` ROI ended at
`y=330`, above the points/reset line, and its broad row OCR did not preserve the short `Go` button
text.

## Impact

No Daily Quest row, Go, Claim, quest, purchase, resource, or other gameplay input occurred. The
immediate and settled Daily Quest frames and OCR output remain retained.

## Revised hypothesis and correction

The final profile is stable, but the bootstrap ROIs need to include the points/reset band and
inspect the right-side button regions separately. Expand the header ROI through the observed
points/reset band and recognize Go/non-claim controls from tight button ROIs plus OCR/color-shape
evidence. Keep Claim input permanently denied and retain clipped/ambiguous abstention.
