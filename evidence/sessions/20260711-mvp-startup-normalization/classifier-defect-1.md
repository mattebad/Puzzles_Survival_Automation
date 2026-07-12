# Keyguard classifier defect 1

Recorded: 2026-07-11, America/Chicago

- Test: offline authorization against the retained Cash Mall and Android launcher negatives using
  the first resumed implementation of `classify_known_keyguard`.
- Result: incorrect authorization; wallpaper/black-region similarity alone was too permissive.
  Cash Mall scored `0.844810` and the launcher scored `0.982039` against the keyguard fixture.
- No live input or device operation occurred from this defect.
- Revised hypothesis: the known non-secure surface must include the central
  `Unlock for all features and data` text-region match, not only wallpaper geometry.
- Correction: require the fixed-profile central unlock-text ROI to score at least `0.985`, while
  retaining the existing wallpaper geometry and policy predicates. Cash Mall and launcher must
  abstain before any live swipe authorization.
