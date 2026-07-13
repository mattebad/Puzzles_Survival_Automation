# Deterministic navigation simplification

Recorded: 2026-07-12, America/Chicago

## Decision

Navigation is now an explicit NAVIGATION_ONLY action class. It authorizes from a fresh RT-019 frame, a recognized source or approved escape source, stable local source anchors, a locally recognized target ROI, clear target overlay/danger separation, and a bounded successor set. Full-frame hashes remain audit evidence and do not authorize or deny navigation.

ZERO_COST_CONSEQUENTIAL retains the persistent prepared/input_sent/confirmed/unresolved journal, one transport call, and positive postcondition requirement. SPEND_OR_STRATEGIC remains denied.

Navigation has a separate bounded lifecycle: proposed, dispatched, reached_successor, safe_no_effect, and navigation_failed. One retry is allowed only after positive proof that a navigation-only input had no effect. An unknown navigation successor requests bounded recovery but does not create an unresolved consequential-action block.

## Retained regression

- Source: live-nav-home-quest-promo-001-source.png
- Immediate-before: live-nav-home-quest-promo-001-immediate-before-1.png
- Promoted Home reference: M6 home-base-settled.png
- Full-frame source/immediate similarity: 0.993561
- Bottom-navigation source/immediate similarity: 0.992875
- Quest-target source/immediate similarity: 1.000000
- Both retained frames classify as HOME_BASE and detect home-quest-entry.
- Changes confined to the animated center do not affect recognition.
- Target disappearance, target-intersecting overlay, and dangerous-control intersection deny.

## Validation

- Complete Python suite: 85 passed.
- RT-019 manifest: valid; input lock false.
- M6 executable corpus: 6/6 assets valid; input lock false.
- Diff check: passed.
- Protected crlf-reconciliation.json SHA-256 remained 62450f89a34a1872e5b1e6100f94dc641037b3f724026dc7e0f8af35906596c3.
- No live runtime access or input occurred during this implementation boundary.
