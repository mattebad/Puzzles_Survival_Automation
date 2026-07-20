# Verified-flow composition readiness review

Review date: 2026-07-20
Review task: `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION-FINAL-READINESS`
Reviewer model: Grok 4.5 High (parent-verified)

## Decision

**FAIL — COMPOSITION REMAINS BLOCKED**

Home Atlas navigate-building qualifies on production call graph, offline tests, and
retained live Bank / Headquarters-return evidence under
`.local-captures/home-atlas-seam-closure/`.

Supply Depot radial qualifies on committed production code at `437a52c` and on
offline adversarial tests, and the live session proves navigation-only building
entry, reversible radial interaction, Home recovery, and exit dispatch ROI
`(0,0,150,105)` via `events.jsonl`. However, the retained live
`radial-result.json` was produced about eight minutes before commit `437a52c`
and does **not** correspond to the committed exit-stage binder evidence schema:
it records Home exterior-close (`supply-depot-exterior-close-anchor` at
`[380,580,420,620]`) under `safe_exit_binding`, omits `exit_target_roi` and
`home_safe_exit_probe`, and omits action-level `pre_dispatch_frame_sha256`
fields that HEAD would emit. Under this review’s standard, live artifacts that
do not correspond to the committed implementation cannot close the
binder-authority seam.

No composition engine, DSL, generic autonomous runtime, or new route was
implemented in this review. `M6-DQ-TRANSITION-CORPUS` remains unactivated.
Registration remains `NOT_REGISTERED`. Scheduler remains disabled.
`CONFIRMED_NOT_DISPATCHED` remains `NON_DISPATCH_AUTHORITY_UNAVAILABLE`.

## Route 1 — Home Atlas

| Field | Evidence |
| --- | --- |
| Committed implementation hash | `e159dd9` (`fix(navigation): close home atlas verified route seams`); integration base `f093812` |
| Production entry point | `scripts/home_atlas_bluestacks.py` → `command_navigate_building` (CLI `navigate-building`; no separate `command_navigate`) |
| Actual transport call path | `command_navigate_building` → `_command_navigate_building_body` → `dispatch_verified_navigate_pan` → `CentralPolicy.issue_capability` → `SafeActionExecutor.execute` → seal-gated `runtime.swipe(fresh_capture, …)` → settled capture + `reconcile_pan` → `attach_navigate_terminal_reports` |
| Planning-frame binding | Planning frame used for disposition / drag geometry only; never used as issuance frame |
| Final pre-dispatch capture and semantic rebind | `runtime.capture("navigate-pan-pre-dispatch")` + `identity_from_captured` + `bluestacks_frame_validation`; capability issued against that fresh identity |
| Perception-bundle ownership | Planning: `build_navigate_perception_bundle` + `checked_navigation_inputs`; pre-dispatch binds complete `NativeFrameIdentity` |
| Session ownership | One `NavigationSession` from `create_session`; prepare / dispatch / reconcile against it |
| Observability | Terminal `attach_navigate_terminal_reports` → `report_navigation_session` |
| Calibration | `create_bluestacks_session_calibration` consumed by `DirectPanNavigator` / post-pan consideration |
| Radial semantics | N/A for this pan route |
| Safe-exit binder | N/A for this pan route |
| Policy boundary | Route-local `CentralPolicy` allowlist including the navigation task id; no production registration |
| Capability issuance and final consumption | Issue against fresh pre_dispatch observation; `SafeActionExecutor` consumes one-shot capability; seal token required for transport |
| Action-ledger states | `navigate_pan_execution_payload` exposes requested / authorized / dispatched / transport_observed / verified / completed / failed / unresolved |
| Transport-observed boundary | Executor `transport_calls > 0` / seal-gated swipe only |
| Semantic-verification boundary | Distinct `reconcile_pan` / `semantic_verified` after settled capture; transport success alone is not completion |
| Recovery boundary | Bounded navigate recovery already owned by the route; no consequential reopen |
| Exact live validation artifacts and result | `.local-captures/home-atlas-seam-closure/nav-bank/…045343322855Z/` (1 pan) and `…/nav-hq-return/…045441483238Z/` (2 pans); each pan planning digest ≠ `pre_dispatch_frame_sha256`; full action_ledger; `building_opened=false`; observability attached |
| Remaining direct bypasses | None on the qualifying navigate-building path. Sibling commands (`command_pan`, `command_scan_grid`, `command_open_building`, `command_recover_home`, `command_return_canonical`) still use direct transport but are outside this qualification graph |
| Qualification verdict | **PASS** for Home Atlas |

## Route 2 — Supply Depot

| Field | Evidence |
| --- | --- |
| Committed implementation hash | `437a52c` (`fix(navigation): close supply depot verified route seams`); integration base `f523f0f` |
| Production entry point | `scripts/home_atlas_bluestacks.py` → `command_supply_depot_radial` |
| Actual transport call path | `command_supply_depot_radial` → `dispatch_verified_supply_depot_building_tap` → `dispatch_verified_supply_depot_radial_tap` → `dispatch_verified_supply_depot_exit_tap` (each: fresh pre_dispatch → `CentralPolicy.issue_capability` → `SafeActionExecutor.execute` → seal-gated `runtime.tap`) → Home successor reconcile → `record_home_recovered` → `attach_navigate_terminal_reports` |
| Planning-frame binding | Planning / immediate-before frames exist per stage; final issuance uses distinct `*-pre-dispatch` captures |
| Final pre-dispatch capture and semantic rebind | `_acquire_supply_depot_pre_dispatch` for building / radial / exit; live frames `0003`, `0007`, `0011` are distinct native 800×1280 pre-dispatch captures |
| Perception-bundle ownership | `build_supply_depot_building_perception_bundle`, `build_supply_depot_radial_perception_bundle`, `build_supply_depot_exit_perception_bundle` on the critical path before capability issuance |
| Session ownership | One `NavigationSession` owns building, radial, safe-exit, and Home recovery; live checkpoint `home_recovered` |
| Observability | Terminal `attach_navigate_terminal_reports` → `report_navigation_session`; live terminal success with three reconciled ledger entries |
| Calibration | N/A (non-pan route) |
| Radial semantics | `build_supply_depot_radial_semantics` consumed on the production radial path; live `radial_semantics` / `radial_perception_bundle` present |
| Safe-exit binder consumption | HEAD: `build_supply_depot_facility_safe_exit_probe` → `require_binder_selected_safe_exit_roi` → `reject_fixed_exit_roi_bypass`; `_emit` separates `home_safe_exit_probe` vs facility `safe_exit_binding` and records `exit_target_roi`. **Live retained result does not match that schema** (see blocker) |
| Policy boundary | Route-local `CentralPolicy` allowlist; `authorize_dispatch=false` on binder; capability is sole dispatch authority |
| Capability issuance and final consumption | Each stage issues against its fresh pre_dispatch observation and exact rebound ROI; executor consumes one-shot capability |
| Action-ledger states | `_execution_payload` requested / authorized / dispatched / transport_observed / verified / completed (+ optional pre_dispatch / exit_target fields under HEAD) |
| Transport-observed boundary | Seal-gated `runtime.tap` only inside executor callbacks |
| Semantic-verification boundary | Post-transport captures + successor recognizers distinct from transport; exit accepts high-confidence Home after facility leave |
| Recovery boundary | Bounded Home recovery + post-live zoom recovery dirs; no claim path |
| Exact live validation artifacts and result | `.local-captures/supply-depot-seam-closure/live-radial/supply-depot-radial-20260720T053642329260Z/`: reason `supply_depot_radial_and_home_recovered`; building/radial/safe_exit all transport_observed+verified+completed; `events.jsonl` exit tap `supply-depot-back-arrow` ROI `[0,0,150,105]`; Home recovered; `daily_free_attempts` remains 9; `CONFIRMED_NOT_DISPATCHED=NON_DISPATCH_AUTHORITY_UNAVAILABLE`. Supporting nav under `…/nav-supply-depot/` |
| Remaining direct bypasses | Committed code closes cached-recapture, fixed-ROI independent authorization, and exterior-close-as-exit on the radial path. **Retained live result still misattributes Home exterior-close as `safe_exit_binding`**, so binder-governed live proof remains open under this review bar |
| Qualification verdict | **FAIL** for composition (live binder-evidence correspondence) |

## Shared architecture qualification

| Seam | Home Atlas | Supply Depot | Jointly qualifies |
| --- | --- | --- | --- |
| Immutable same-capture perception | yes | yes (code + live frames) | no (SD live binder evidence gap) |
| Complete native-frame identity | yes | yes | yes |
| Authoritative resumable `NavigationSession` | yes | yes | yes |
| Navigation observability | yes | yes | yes |
| Bounded calibration | yes | N/A | yes where applicable |
| Shared radial semantics | N/A | yes | yes where applicable |
| Shared BlueStacks safe-exit binding | N/A | code yes / live evidence no | **no** |
| `CentralPolicy` | yes | yes | yes |
| `SafeActionExecutor` | yes | yes | yes |
| One-shot capability issuance and final consumption | yes | yes | yes |
| Fresh pre-dispatch capture and semantic rebind | yes | yes | yes |
| Route/session/action/target/profile/frame/geometry binding | yes | yes | yes |
| Executor-only transport | yes | yes | yes |
| Separate transport and semantic-verification boundaries | yes | yes | yes |
| Complete action-ledger and terminal reconciliation | yes | yes (session/SafetyStore); result JSON incomplete vs HEAD | borderline → no for this bar |
| Bounded recovery | yes | yes | yes |
| Live reversible validation | yes | partial (transport/Home yes; binder result schema no) | **no** |
| Fail-closed stale/ambiguous/mixed-capture/unauthorized | yes | yes (offline) | yes offline |

Two real production routes exist (not wrappers around one route; not test-only reuse). Joint composition readiness still fails on Supply Depot live binder-evidence correspondence.

## Exact blocker

| Field | Value |
| --- | --- |
| Route | Supply Depot radial |
| Production functions | `command_supply_depot_radial` / `dispatch_verified_supply_depot_exit_tap` / `_emit` |
| Missing seam | Live-proven facility safe-exit binder selection recorded in artifacts that match committed HEAD (`safe_exit_binding` = `supply-depot-facility-back-arrow`, `exit_target_roi` equals binder-selected and dispatched ROI, early Home probe under `home_safe_exit_probe`, action `pre_dispatch_frame_sha256` fields) |
| Why it prevents composition | Retained live `radial-result.json` (session `20260720T053642329260Z`, ~00:36 local) predates `437a52c` (~00:44 local) and still presents Home exterior-close as `safe_exit_binding`. Review standard rejects treating non-corresponding live artifacts, or exit ROI coincidence with the legacy constant alone, as binder-governed production reuse proof |

## Narrow follow-on

`SUPPLY-DEPOT-VERIFIED-ROUTE-LIVE-BINDER-EVIDENCE` remains **Blocked**.

Live revalidation under HEAD (artifacts under
`.local-captures/supply-depot-live-binder-evidence/`) did **not** produce facility binder evidence:

| Attempt | Session | Outcome |
| --- | --- | --- |
| 1 | `live-radial/…T165456489362Z` | Building entry verified; Claim Supply dispatched at `[555,551,725,657]` opened Upgrade panel → `unexpected_successor` / blocked; `home_safe_exit_probe` emitted (packaging OK); facility `safe_exit_binding` / `exit_target_roi` never reached |
| 2 | `live-radial-2/…T165939763069Z` | Building entry dispatched; fresh radial pre-dispatch fail-closed with `RADIAL_REBIND_FAILED` (no Claim Supply tap); no terminal `radial-result.json` |

**Root cause (binding closure):** attempt-1 radial OCR included building-title `Sup` inside
`SUPPLY_DEPOT_RADIAL_ROI`. `_claim_supply_roi_from_data` previously unioned every `clai*`/`sup*`
token, so `Sup` + `Claim` + `Suppl` produced Upgrade-covering `[555,551,725,657]`. Active task
`SUPPLY-DEPOT-RADIAL-TARGET-BINDING-CLOSURE` pairs Claim with a nearby Supply token and rejects
distant building-label contamination. This is **not** a result-packaging bug: HEAD already
separates `home_safe_exit_probe` from facility `safe_exit_binding`. Renew LIVE-BINDER only after
the binding closure commit; do not treat the pre-`437a52c` seam-closure session as
HEAD-corresponding binder evidence.

## Prerequisites for reconsideration

1. Complete `SUPPLY-DEPOT-RADIAL-TARGET-BINDING-CLOSURE`, then renew
   `SUPPLY-DEPOT-VERIFIED-ROUTE-LIVE-BINDER-EVIDENCE` with retained artifacts matching HEAD
   (`safe_exit_binding` = `supply-depot-facility-back-arrow`, `exit_target_roi` equals binder and
   dispatched ROI, `home_safe_exit_probe` isolated, action `pre_dispatch_*` present).
2. Renew this document with an explicit PASS only when both routes jointly qualify without residual bypasses.
3. Only then activate `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION`.
4. Leave `M6-DQ-TRANSITION-CORPUS` unactivated until composition completes under its own backlog authorization.

## Offline validation (this review)

- Focused: `tests/test_home_atlas_verified_route.py` + `tests/test_supply_depot_verified_route.py` → 48 passed
- Architecture regressions: perception-bundle, navigation-session, observability, calibration, radial, safe-exit, capability-firewall, SafeActionExecutor, governance → 270 passed
- Full repository suite → **900 passed, 1 skipped**
- Governance validation passed; handoff JSON parse OK
- No live BlueStacks/ADB/game input during this review
- No push
