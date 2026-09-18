# Atlas-defined Home building entry

## Scope and checkpoint

Checkpoint `bc93ea7fcb8bf7cef38c9fe28a3bbf0f05ab0233` is pushed to `origin/refactor/lean-bot-backlog`. The follow-up uncommitted candidate centralizes bounded Atlas startup normalization and fixes the demonstrated fractional-anchor ROI rounding defect. Its live proof completed two eligible service cycles; the user accepted the intentional four-recruit safety stop at 772.8 seconds as satisfying LB-03 despite the unexecuted 1,800-second wall-time target. Commit/push remains a separate authorization checkpoint.

Goal: use a building's Atlas-space interaction anchor, transformed by fresh camera localization, for Home entry. Building-name OCR must not veto an otherwise valid geometric binding. Each flow must still recognize its expected destination or radial before the next action.

Non-goals: changing resolution, weakening localization, adding another visual building classifier, rewriting navigation, introducing leases/recovery frameworks, changing reward/claim/recruitment policy, fixing unrelated accounting, or claiming day/night or unattended live reliability.

## Evidence and existing structure

The stopped soak retained successful Atlas localization (confidence 0.9806, residual 0.2325px). Its search region contained a readable Tavern label, but label candidate selection chose scenery at `(309,501,365,521)` and OCR returned `ux <i`/blank. Offline OCR on the retained search region reads the expected label. Evidence: `.local-captures/lb02-live/soak-20260916T042200Z/noahs-tavern-unified-recruitment-20260916T042601097412Z/`.

Existing components are sufficient:
- `SemanticBuilding`: polygon, navigation anchor, interaction eligibility and platform policy.
- `LocalizationResult`: current-frame digest, canonical zoom, transform, confidence/ambiguity, stale/overlay state.
- `BuildingBinding`: frame-bound target ROI, confidence and semantic evidence.
- `bind_visible_building`: shared by the Home driver, Tavern, Ruins, training and Research Lab consumers.
- Supply Depot has a separate OCR-gated building binder that must be removed in favour of the shared binder.
- Nova already carries `ResearchLabTapProvenance` and separately recognizes its radial/template target. Supply Depot separately binds Claim Supply versus Upgrade.

## Shared contract

### Atlas-flow startup normalization

Every supported flow that uses the Home/world Atlas must establish canonical camera state at
the beginning of the flow. If a fresh, overlay-free Home frame is already fully zoomed out, the
flow may proceed without a normalization input. If the frame positively identifies a supported
noncanonical zoom, the flow must use the existing zoom-normalization transport for at most two
inputs, recapture after each input,
and require fresh fully-zoomed-out localization before Atlas planning or binding. Unknown,
ambiguous, stale, overlaid, unsupported, repeated, no-progress, or exhausted recovery states fail
closed. Observation-only preflights remain zero-transport and may report that normalization is
required; they do not replace the live flow's normalization responsibility.

### Atlas interaction anchor

Follow the existing navigation-anchor model:
- Add optional `SemanticBuilding.interaction_anchor_override` and an `interaction_anchor` property.
- Load optional JSON `interaction_anchor` as a finite two-coordinate Atlas-space point. Keep it separate from `navigation_anchor`; panning placement is not tap authorization.
- Without an explicit override, use the existing building polygon centroid. It is a geometric default, not a guessed screen coordinate. Reject invalid/degenerate polygons or a centroid outside the polygon; do not silently move the point.
- Author explicit centroid-equivalent anchors for the three selected entry buildings using existing geometry: Tavern `(355,757.5)`, Research Lab `(835,520)`, Supply Depot `(1246.7,976.1)`. These preserve existing full-footprint centre taps; they are not new live calibrations. Other eligible buildings retain validated polygon-centroid defaults.
- Preserve non-actionable building declarations and platform `actionable:false` restrictions. Do not make mapped but HUD-obstructed buildings actionable.

### Binding API and geometry

Keep the shared name and existing return type:

`bind_visible_building(frame, localization, building, *, diagnostics=None) -> BuildingBinding | None`

Remove the obsolete `ocr` argument and OCR/candidate-selection implementation when no remaining runtime consumer needs it. No compatibility alias, opt-in OCR mode or second building-entry implementation.

A successful binding requires:
1. Native 800x1280 frame and matching BlueStacks profile/platform.
2. Fresh, recognized, unambiguous canonical fully-zoomed-out localization; preserve existing confidence/quality contracts. Reject stale, overlay, missing/nonfinite/singular transform and frame-digest mismatch.
3. An interaction-eligible mapped building, valid finite polygon and interaction anchor inside its footprint.
4. The interaction point transformed with the same inverse camera transform as the building polygon. Respect homogeneous-coordinate validity; reuse existing projection machinery rather than an independent transform convention.
5. A usable target ROI centred on the transformed anchor (integer rounding tolerance at most one pixel), inside the projected building footprint and the existing HUD-free interaction region. Respect existing minimum safe-region constraints, including Supply Depot's 55x55 policy where applicable. Never obtain a different tap point by clipping the building and taking the visible fragment's centre. If the anchor or a safe hit region is unavailable, return no binding and let the existing planner expose it or stop.
6. The returned binding names the exact building, is associated with the current frame and reports Atlas/anchor evidence, not fabricated OCR evidence.

Preserve the existing conservatively inset footprint extent where it remains safe and centred; do not replace every target with an arbitrary tiny click box. Flow integration must audit consumers that also use a building binding as a safe-exit exclusion region, so changing the tap geometry does not silently weaken their building/obstruction masks.

If planner changes are necessary, keep them confined to this contract: an unsafe interaction anchor must not be reported as complete; use the existing bounded pan/clamp/no-progress handling. Navigation anchors and camera-coverage protections remain intact.

Diagnostics should identify localization failure or unsafe target, show anchor source, Atlas/screen anchor and resulting ROI. Remove obsolete `label_not_read` runtime admission branches and label-crop sidecars from the entry path; retain descriptive label metadata as historical Atlas provenance where otherwise useful.

This is geometric navigation authority, not visual proof of the destination. It does not promise detection of arbitrary floating icons. Respect current obstruction signals/HUD exclusions, place anchors away from known controls, and stop on an unexpected successor rather than repeating the building tap or issuing a consequential action.

## Flow integration and successor contract

Migrate every current shared binding consumer and retire `bind_supply_depot_building`; callers use `bind_visible_building` with the mapped Supply Depot building. Do not leave a wrapper that preserves the old OCR gate. Keep Supply's source-frame identity checks at its entry boundary.

Entry sequence:

`fresh localized Home -> mapped building anchor -> one authorized navigation tap -> fresh capture -> expected screen/radial -> flow-specific control`

- Tavern: recognize Noah's Tavern and the selected tier before any free recruit. Preserve reward-independent completion, daily caps, persistent cooldowns and all stop/duplicate guards.
- Nova: preserve successful Research Lab tap provenance, bounded successor freshness and current-frame Nova radial-template binding. Do not require the underlying building name once the radial is open. OCR for actual menu content may remain corroborating under the existing contract.
- Supply Depot: preserve current-frame Claim Supply/Upgrade separation and destination-screen verification. An already established building-tap transition must not fail solely because the radial obscures the building name. Preserve supported already-open radial admission; do not treat an arbitrary Home frame as a radial.
- Other shared consumers (Ruins, training, Bioenhancer and generic Home entry): keep their current expected-successor and action-policy checks. Changing building entry must not authorize downstream gameplay or alter route declarations.

Do not add universal successor logic to the Atlas binder: each flow knows what its building opens.

## Implementation boundary

The candidate changes the Atlas model/binder/planner, the existing Home-entry consumers, Supply's duplicate Home binder, and focused regressions as one integrated LB-03 slice. All `bind_visible_building` callers use three positional arguments plus optional diagnostics; no compatibility alias, OCR argument, Supply-only source-frame argument, or second entry implementation remains. Parent integration owns the complete diff and verification; no model-role sequence is an acceptance gate.

## Offline acceptance

1. Real retained failed-soak Home frame now yields a Tavern anchor binding using actual Atlas localization, with no label OCR. Its projected point/ROI must be visually checked against the actual building, not merely asserted nonempty.
2. Previously successful Tavern/native Bank frames remain bound at their mapped buildings. Demonstrate camera translation/scale mapping and an explicit non-centroid anchor; the navigation anchor must not silently change the interaction point.
3. Stale/digest mismatch, ambiguous/low-quality localization, wrong profile/zoom, overlay, unsafe/off-screen anchor, non-actionable building and invalid geometry/transform must not yield a tap. Preserve viable edge-pan behaviour rather than accepting clipped-centre retargeting.
4. A text-free/altered-label frame with otherwise valid supplied localization must not fail building binding. Label brightness is not an entry predicate. Synthetic lighting changes are labelled synthetic; they do not establish real night localization.
5. Tavern route replay reaches the recognized destination before recruitment. A wrong successor yields no recruit.
6. Nova and Supply radial replays accept their legitimate fresh contextual radials without the obscured building label, but reject missing/wrong controls, stale provenance and inappropriate successors; no Claim/Praise/paid operation is newly authorized.
7. Update existing tests for the changed contract. Delete obsolete tests that only assert mandatory building OCR or its wording/crop internals; retain/add tests for real geometry, safety and transition regressions. No snapshot re-pinning or mocks that simply echo the new implementation.
8. Run the affected suites once edits settle and a throwaway real retained-frame smoke. Do not run the project-wide suite. Report unavailable real night/transition/upgrade coverage rather than inventing it.
9. Operational service state remains generation14 disabled with the Home-label inspection block and existing cooldown/count/VIP records unchanged. No live proof, block clearance or automatic retry is part of this delivery.

## Offline result

The settled affected command passed 369 tests with 4 skipped. Durable evidence is retained in `.local-captures/lb03-atlas-entry-20260918T185758Z/`: the exact failed-soak Tavern frame, attempt-2 and attempt-3 Tavern camera positions, native Bank, and a label-erased/OCR-forbidden Tavern frame all localized and bound with zero inputs. Annotated overlays were visually inspected and place the projected polygon, anchor and target ROI on the intended Tavern or Bank building inside the HUD-safe box.

Sixteen no-input negatives cover stale/overlay/profile/zoom/low and nonfinite confidence/excessive and nonfinite residual/digest mismatch/singular and nonfinite transform/degenerate polygon/non-actionable/off-screen anchor/Supply coverage below 55×55/concave-notch rejection. Read-only SQLite URI inspection preserved generation-14 disabled service and Recruitment, the `home_atlas_label_not_read` block with failure count 1, scheduler cooldown/count rows, released ownership/runtime lock, and the unresolved startup VIP ledger; database and WAL hashes did not change.

This offline evidence alone did not establish a real night/day transition, live Supply or Nova entry, other-building live reliability, or prolonged/repeated-cycle operation. The live continuation below supplies Tavern and repeated-cycle evidence while retaining the stated duration and building-coverage limitations.

## Live result

The admitted candidate passed a zero-input Tavern binding preflight and one navigation-only
round trip with two inputs: Atlas-bound Tavern entry and verified safe return to Home. The
subsequent service soak completed two eligible recruitment cycles. Both cycles used fresh Atlas
binding, recognized Tavern, persisted verified tier cooldown/count changes, and returned to Home.
Across the soak, retained native events contain 15 inputs and exactly four free recruits; no paid
input or duplicate recruit occurred. The second cycle waited for the persisted Basic cooldown.

The soak stopped at its configured four-recruit ceiling after 772.8 seconds. Service and
Recruitment are disabled at generation 16, ownership and the runtime-input lock are released,
and the unresolved startup VIP record is unchanged. This is live Tavern and repeated-cycle proof,
accepted by the user as LB-03 live closure, not a completed 1,800-second prolonged soak. It
still does not establish real lighting transitions or live Supply, Nova, or other-building entry. Evidence is retained under
`.local-captures/lb03-live-admission-20260918T224056406651Z/`.
