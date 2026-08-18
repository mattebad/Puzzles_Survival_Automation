# Nova Praise lean reproof — frozen revision r5

This revision supersedes only r4's bottom-navigation Home identity decision.
The r4 recovery-aware planner gate and all r3 Nova action-boundary checks remain.

## Frozen stage control
- Task / flow: `nova-praise` / `NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE`
- Revision ID: `nova-praise-lean-reproof-r5`
- Stage type: `home_identity_correction`
- Product precondition: `proven`
- Failure class: `core_contract`
- Stage start / user correction UTC: `2026-08-18T04:37:00.000Z`
- `control_plane_owner`: `gpt-5.6-sol-medium`
- `bounded_implementer`: `gpt-5.6-luna-xhigh`
- `independent_tester`: `gpt-5.6-terra-high`

## Frozen architecture correction
- The fixed bottom navigation bar is global and therefore cannot establish
  explicit Home identity. Nova must not consult `recognize_home_nav()` for Home
  context or target authority.
- Home Atlas remains the Home-specific authority. A fully localized/canonical
  result establishes Home directly.
- For bounded canonical recovery only, a noncanonical Home Atlas registration
  may establish measured Home context when it reports `ZOOMED_IN` or
  `INTERMEDIATE`, confidence at least `0.85`, residual at most `3.0`, no
  ambiguity, no stale state, and no overlay.
- That measured context authorizes only the existing bounded zoom-recovery
  path. Atlas localization, the recovery-aware viewport planner, current-frame
  semantic Research Lab binding, and runtime revalidation remain required
  before any target dispatch.
- Retained evidence: the original source is `ZOOMED_IN`, confidence
  `0.962349`, residual `0.241842`, ambiguity `none`, stale `false`, overlay
  `false`; the recovered frame is canonical at confidence `0.990995`.

## Writable paths
- `scripts/nova_praise_bluestacks.py`
- `tests/test_nova_navigation_canary.py`
- `docs/validation/nova-praise-lean-reproof-20260817-r5-manifest.md`
- `docs/validation/nova-praise-lean-reproof-20260817-ledger.md`
- `CURRENT_HANDOFF.md`

## Acceptance
- Nova production code does not import or call `recognize_home_nav`.
- High-quality zoomed/intermediate Home Atlas registration establishes only
  measured Home context and permits bounded canonical recovery.
- Low-confidence, high-residual, ambiguous, stale, overlay, invalid, and
  unrelated frames fail closed.
- The r4 planner still returns `PAN` on the retained disproven Research Lab
  viewport and never dispatches that binding directly.
- Focused Nova and Home navigation tests pass; independent review finds no
  concrete regression.

## Safety and live budget
- No bottom-nav-only Home, target, or transport authority.
- Singleton/current-frame/native-profile/fail-closed rules remain unchanged.
- Live admission remains blocked until deterministic checks, independent
  review, parent integration acceptance, and zero-input observation complete.
- The user-authorized ceiling remains three further live attempts; repeated
  signatures or a disproven design terminate earlier.
