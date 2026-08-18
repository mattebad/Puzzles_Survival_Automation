# Visual ground truth and live-validation discipline

This policy governs how a visual asset earns the authority to drive live input,
and how live-runtime claims are proven. It is a hard precondition for any live
dispatch that depends on visual recognition. `AGENTS.md` references it; this file
is the canonical detail.

## Asset identity and provenance

- Never trust a visual asset's filename, label, metadata, or passing tests as
  proof of identity. Visually inspect every new or changed template before it can
  authorize live input.
- Retain independent target ground truth: native source frame, source hash, crop
  coordinates, template hash, runtime profile, and an annotated source showing
  the selected ROI and nearby semantic label.
- Tests must not derive expected identity, ROI, geometry, or provenance from the
  same constants, metadata, or asset used by production recognition. Circular
  agreement is not validation.
- OCR validates a target only when the text is spatially associated with that
  target. Text elsewhere in the frame is context, not proof that the matched
  control has that identity.

## Binding before dispatch

- Before the first live dispatch for a changed visual selector, inspect the fresh
  immediate-before native frame with the bound ROI overlaid and positively
  confirm the intended control.
- Bind from the current native frame. Retained coordinates describe retained
  evidence, not a live target; use bounded visual matching plus independently
  measured current-frame geometry.

## Home semantics

- Keep Home semantics distinct. `HOME_READY`, positive Home registration, safe
  atlas localization, and `HOME_CANONICAL` are different claims. A strong
  wrong-zoom registration may prove Home context but must not authorize atlas
  coordinates, panning, or building binding until the supported zoom and
  localization requirements are met.

## After dispatch and route proof

- After any dispatched input, assume runtime state changed. Recovery requires
  exact successor recognition and immediate-before revalidation; never reuse the
  prior state's authority.
- Prove supported intermediate-state continuation and the canonical end-to-end
  route. Success from an already-open radial does not prove Home-to-target
  navigation.
- Contradictory visual evidence invalidates passing tests. Surface any asset,
  label, ROI, geometry, or semantic mismatch immediately and prohibit live input
  until corrected.
