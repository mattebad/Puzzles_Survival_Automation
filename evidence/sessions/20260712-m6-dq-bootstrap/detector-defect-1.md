# M6-DQ-BOOTSTRAP — Detector defect 1

Recorded: 2026-07-12, America/Chicago

## Observation

The fresh final-runtime Quest screen was visually recognized as Quest with Main Quest selected and
the Daily Quest tab visible. The first offline helper run abstained because local OCR returned
`ln guest___dallyquest_` for the tab region; the exact substring check did not accept the OCR
variant `dallyquest`.

## Impact

No Daily Quest tab input was sent. No quest, Go, Claim, purchase, or resource action occurred.
The source frame, OCR output, and settled Quest screenshots remain retained under
`remote-cache/20260712-home-quest-nav/`.

## Revised hypothesis and correction

The screen evidence is sufficient, but OCR needs bounded tolerance for common character and
separator errors. Add local fuzzy phrase matching for the exact semantic phrase `Daily Quest`
using a high similarity threshold and retain the existing positive screen/layout requirements.
Do not add generic substring authorization or coordinate-only fallback.
