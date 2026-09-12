# Stage 10 phase 2 World navigation promotion r4

## Control
- Task: `stage-10-phase-2-navigation-r4`.
- Parent: `gpt-5.6-sol-medium`, sole control-plane and live-runtime owner.
- Mutable role: one mapped `gpt-5.6-luna-xhigh` bounded implementation.
- Independent role: one mapped read-only independent tester review.
- User continuation: explicit on 2026-08-25.
- Entry HEAD: `3800d5a88ee5454fe0b4a7b7039e1ea84c68226d`, synchronized with upstream and clean before r3 admission changes.
- Failure class entering r4: `local_defect`; no r3 live attempt or gameplay input occurred.

## Frozen repair
The r3 final zero-input observations are visually Home and footer OCR reads exactly `world`, but `_footer_control_binding` rejects because the current frame contains both exact measured World-button ROI `[36,1242,112,1265]` and a transient broad footer contour such as `[0,1168,634,1271]`.

The repair may change only `scripts/world_map_navigation_bluestacks.py` and exact World recognizer tests. It must:
1. Preserve current-frame OCR identity, source-frame hash binding, and independently measured geometry.
2. Prefer one uniquely smallest exact footer candidate only when it is inside `_FOOTER_NAVIGATION_REGION`, overlaps the exact footer text sufficiently, and every competing associated candidate strictly contains it or is its broad ancestor.
3. Continue rejecting broad-only candidates, multiple non-nested candidates, mixed World/Home/Base labels, stale frames, unknown modals, and candidates outside the footer region.
4. Never introduce fixed-coordinate input authority, template authority, Daily authority, or an input retry.
5. Keep the prior broad-ROI clipping repair and all existing World safety behavior.

## Acceptance
- Exact retained r3 frames recognize `HOME_READY` and bind `[36,1242,112,1265]`.
- Broad-only and distinct non-nested ambiguity regressions fail closed.
- World suite, focused automation-service/World profile, and DevelopmentSession suite pass.
- Independent review returns no must-fix finding.
- First/duplicate/reopened-store scheduler pulses remain zero-transport and fenced.
- A fresh zero-input frame is `HOME_READY` before at most one live canary.
- Final registration is disabled on every terminal path.

## Safety
- Exact route only: `HOME_READY -> World -> Search -> World -> HOME_READY`.
- Maximum 20 navigation/allowlisted-popup inputs.
- Zero Daily, claim, resource, combat, purchase, maintenance, AP/stamina, currency, node, march, formation, or occupancy-override input.
- Unknown/blocked/ambiguous result closes the canary budget; no identical retry.
- Phases 3-6 remain unadmitted until Phase 2 acceptance. Phase 7 combat remains unauthorized.

## Outcome
- The bounded Luna repair changed only the footer candidate selector and its exact tests. Parent validation passed 97 World, automation-service, scheduler, and DevelopmentSession tests.
- The mapped Terra High read-only review returned `ADMIT_MATERIALLY_CHANGED_CANARY` with no findings.
- First and reopened-store offline pulses used `.local-orchestrator/stage-10-phase-2-r4.sqlite3`: World was selected once with `transport_count=0`; the duplicate returned `NO_ELIGIBLE_TASK`.
- Fresh zero-input observation `.local-captures/development-sessions/observe-20260825T203537709174Z` captured the native 800×1280 frame with zero dispatch/input and released ownership.
- The one live canary completed at `.local-captures/development-sessions/WORLD-MAP-NAVIGATION-FOUNDATION-20260825T203558442951Z`.
- It issued four navigation inputs and zero popup, Daily, claim, resource, combat, purchase, maintenance, AP/stamina, currency, node, march, formation, or occupancy-override inputs.
- Continuous evidence verifies `HOME_READY -> World -> Search -> World -> HOME_READY`, `navigation_only_complete`, terminal `HOME_READY`, persistent checkpoints unchanged, and ownership released.
- Registration was consumed before runtime and ended `NOT_REGISTERED`; registered flows are empty and scheduler eligibility is false.
- Parent decision: `ACCEPT_PHASE_2`. Phase 3 requires separate admission. Phase 7 combat remains unauthorized.
