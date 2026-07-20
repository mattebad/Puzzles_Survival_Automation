# Verified-flow composition readiness review

Review date: 2026-07-20 (Home Atlas seams closed by `e159dd9`; Supply Depot seams
closed by `SUPPLY-DEPOT-VERIFIED-ROUTE-SEAM-CLOSURE`)

## Decision

`RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION` remains **blocked**.

Home Atlas and Supply Depot readiness findings recorded after `f093812` / `f523f0f`
are now closed. Composition must not activate until a separate final readiness
review confirms both real live-validated routes reuse the shared architecture
without residual bypasses.

No composition engine, DSL, generic autonomous runtime, or new route was
implemented in this update. `M6-DQ-TRANSITION-CORPUS` remains unactivated.
Registration remains `NOT_REGISTERED`. Scheduler remains disabled.
`CONFIRMED_NOT_DISPATCHED` remains `NON_DISPATCH_AUTHORITY_UNAVAILABLE`.

## Route evidence

### Home Atlas navigate-building

| Field | Evidence |
| --- | --- |
| Production entry point | `scripts/home_atlas_bluestacks.py` → `command_navigate_building` |
| Capture binding | `identity_from_captured` + `build_navigate_perception_bundle` / checked navigation inputs on the planning frame; each pan additionally acquires a genuine `navigate-pan-pre-dispatch` capture |
| Session ownership | Creates and persists one authoritative `NavigationSession`; pans prepare/dispatch/reconcile against it |
| Observability | Terminal `attach_navigate_terminal_reports` → `report_navigation_session` |
| Calibration | `create_bluestacks_session_calibration` considered after reconciled pans |
| Radial use | N/A for this pan route |
| Safe-exit use | N/A for this pan route |
| Capability issuance / final consumption | `dispatch_verified_navigate_pan` issues against the fresh pre_dispatch observation, then `SafeActionExecutor.execute` consumes; transport swipes that fresh capture only inside the seal-gated callback |
| Transport boundary | `runtime.swipe` only inside seal-gated executor transport callback; direct bypass fail-closed |
| Live validation | Seam-closure regression under `.local-captures/home-atlas-seam-closure/`: Bank 1 pan + HQ return 2 pans; `building_opened=false`; each pan `planning digest ≠ pre_dispatch_frame_sha256` |
| Semantic verification boundary | Settled capture + pan reconciliation distinct from transport confirmation |
| Action ledger | Per-pan `action_ledger` exposes requested / authorized / dispatched / transport_observed / verified / completed / failed / unresolved |
| Remaining bypasses | **None for the two Home Atlas readiness findings.** Fresh pre_dispatch capture/rebind and full action-ledger parity are closed as of `HOME-ATLAS-VERIFIED-ROUTE-SEAM-CLOSURE`. |

### Supply Depot radial

| Field | Evidence |
| --- | --- |
| Production entry point | `scripts/home_atlas_bluestacks.py` → `command_supply_depot_radial` |
| Capture binding | Building, radial, and exit each acquire a genuine `*-pre-dispatch` capture; capability issuance and transport use that fresh frame; same-capture `FramePerceptionBundle` at each stage |
| Session ownership | One authoritative `NavigationSession` for the route lifecycle with prepare/dispatch/reconcile/safe-exit/home-recovered ledger updates |
| Observability | Terminal `attach_navigate_terminal_reports` → `report_navigation_session` |
| Calibration | N/A (non-pan route) |
| Radial use | Shared radial semantics + same-capture radial perception on the radial step |
| Safe-exit use | Facility exit runs `build_supply_depot_facility_safe_exit_probe` on the fresh pre_dispatch frame; capability and transport use the binder-selected candidate ROI exactly; fixed-ROI bypass rejected |
| Capability issuance / final consumption | Building, radial, and exit helpers each issue one-shot capability against the fresh pre_dispatch observation and consume through `SafeActionExecutor` |
| Transport boundary | `runtime.tap` only inside seal-gated executor transport callbacks; direct bypass fail-closed |
| Live validation | Seam-closure under `.local-captures/supply-depot-seam-closure/`: navigate-to-Supply-Depot then radial (`building_entry` + `radial_entry` + `safe_exit` confirmed; `supply_depot_radial_and_home_recovered`; distinct pre_dispatch frames; exit ROI equals facility binder back-arrow; zero claims) |
| Semantic verification boundary | Post-transport captures and successor recognizers distinct from transport; exit accepts high-confidence `ZOOMED_IN` Home after facility leave |
| Remaining bypasses | **None for the three Supply Depot readiness findings.** Fresh pre_dispatch capture/rebind, binder-selected exit ROI, and same-capture bundles are closed as of `SUPPLY-DEPOT-VERIFIED-ROUTE-SEAM-CLOSURE`. |

### Other routes (unchanged, non-qualifying)

Noah's Tavern and Troop-training return-home remain on route-local recognition and
direct `NativeRuntimePort` transport without `NavigationSession`, observability,
shared safe-exit binder, or capability firewall consumption. They do not close
readiness.

## Exact missing integrations (blocker)

Home Atlas findings and Supply Depot findings listed in the post-`f093812`/`f523f0f`
renewed review are **closed**.

Composition remains blocked only until a separate final readiness review confirms
two real live-validated routes reuse the required architecture without residual
bypasses and records a PASS decision.

Imports, dormant adapters, test mocks, metadata-only probes, and sealed direct
transport helpers do not count as readiness. Live transport success alone does
not waive a final readiness gate.

## Prerequisites for reconsideration

1. Re-run a final readiness review against the closed Home Atlas and Supply Depot
   production paths (and any other claimed qualifying routes).
2. Re-run offline focused/adversarial/governance/full-suite gates as required by
   that review.
3. Re-run one bounded live reversible validation per touched route when live
   behavior changes.
4. Renew this document with a PASS decision only when two real live-validated
   routes reuse the required architecture without bypasses.
5. Only then activate `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION`.
6. Leave `M6-DQ-TRANSITION-CORPUS` unactivated until composition completes under
   its own backlog authorization.
