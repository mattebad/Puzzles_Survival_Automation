# Verified-flow composition readiness review

Review date: 2026-07-19 (renewed after `f093812` and `f523f0f`)

## Decision

`RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION` remains **blocked**.

Two real BlueStacks routes now live-validated capability-bound navigation
(`HOME-ATLAS-VERIFIED-ROUTE-INTEGRATION` as `f093812`,
`SUPPLY-DEPOT-VERIFIED-ROUTE-INTEGRATION` as `f523f0f`), but they do **not** yet
jointly reuse the complete shared architecture without remaining integration
gaps. Composition must not activate until the missing integrations below are
closed on the production route paths.

No composition engine, DSL, generic autonomous runtime, or new route was
implemented in this review. `M6-DQ-TRANSITION-CORPUS` remains unactivated.
Registration remains `NOT_REGISTERED`. Scheduler remains disabled.
`CONFIRMED_NOT_DISPATCHED` remains `NON_DISPATCH_AUTHORITY_UNAVAILABLE`.

## Route evidence

### Home Atlas navigate-building

| Field | Evidence |
| --- | --- |
| Production entry point | `scripts/home_atlas_bluestacks.py` → `command_navigate_building` |
| Capture binding | `identity_from_captured` + `build_navigate_perception_bundle` / checked navigation inputs on the immediate-before frame |
| Session ownership | Creates and persists one authoritative `NavigationSession`; pans prepare/dispatch/reconcile against it |
| Observability | Terminal `attach_navigate_terminal_reports` → `report_navigation_session` |
| Calibration | `create_bluestacks_session_calibration` considered after reconciled pans |
| Radial use | N/A for this pan route |
| Safe-exit use | N/A for this pan route |
| Capability issuance / final consumption | `dispatch_verified_navigate_pan` → `CentralPolicy.issue_capability` + `SafeActionExecutor.execute` |
| Transport boundary | `runtime.swipe` only inside seal-gated executor transport callback; direct bypass fail-closed |
| Live validation | Passed under `.local-captures/home-atlas-verified-route/` (Bank pan + HQ return; `building_opened=false`) |
| Semantic verification boundary | Settled capture + pan reconciliation distinct from transport confirmation |
| Remaining bypasses | Executor `recapture()` returns the cached issuance observation (no fresh frame capture/rebind at the final pre_dispatch boundary). Result payload exposes executor/transport/semantic fields but not the full distinct requested/authorized/dispatched/transport_observed/verified/completed ledger required for composition parity. |

### Supply Depot radial

| Field | Evidence |
| --- | --- |
| Production entry point | `scripts/home_atlas_bluestacks.py` → `command_supply_depot_radial` |
| Capture binding | Same-capture `NativeFrameIdentity` for building/radial/exit; radial path builds `build_supply_depot_radial_perception_bundle`. Building and exit dispatches bind identity/ROI without a full `FramePerceptionBundle` on those steps |
| Session ownership | One authoritative `NavigationSession` for the route lifecycle with prepare/dispatch/reconcile/safe-exit/home-recovered ledger updates |
| Observability | Terminal `attach_navigate_terminal_reports` → `report_navigation_session` |
| Calibration | N/A (non-pan route) |
| Radial use | Shared radial semantics + same-capture radial perception on the radial step |
| Safe-exit use | `build_supply_depot_safe_exit_probe` records a non-authorizing same-capture binder result in evidence, but `dispatch_verified_supply_depot_exit_tap` taps the fixed `SUPPLY_DEPOT_EXIT_TARGET_ROI` and does **not** consume the binder candidate geometry |
| Capability issuance / final consumption | Building, radial, and exit helpers each issue one-shot capability and consume through `SafeActionExecutor` |
| Transport boundary | `runtime.tap` only inside seal-gated executor transport callbacks; direct bypass fail-closed |
| Live validation | Passed as `live-radial-5` under `.local-captures/supply-depot-verified-route/` (`building_entry` + `radial_entry` + `safe_exit` all confirmed; `supply_depot_radial_and_home_recovered`; zero claims) |
| Semantic verification boundary | Post-transport captures and successor recognizers distinct from transport; exit accepts high-confidence `ZOOMED_IN` Home after facility leave |
| Remaining bypasses | (1) Executor `recapture()` returns cached issuance observation on building/radial/exit helpers — no fresh pre_dispatch capture/rebind. (2) Shared BlueStacks safe-exit binder is probe/evidence-only and does not govern the executed exit ROI. (3) Building/exit steps lack full same-capture `FramePerceptionBundle` consumption. |

### Other routes (unchanged, non-qualifying)

Noah's Tavern and Troop-training return-home remain on route-local recognition and
direct `NativeRuntimePort` transport without `NavigationSession`, observability,
shared safe-exit binder, or capability firewall consumption. They do not close
readiness.

## Exact missing integrations (blocker)

Before composition can be reconsidered, the two qualifying routes must close:

1. **Fresh pre_dispatch recapture/rebind** on every verified dispatch helper
   (`dispatch_verified_navigate_pan`, Supply Depot building/radial/exit): the
   executor `recapture()` callback must capture a new immutable frame, rebuild
   observation/binding from that frame, and fail closed on drift — not reuse the
   issuance-time observation object.
2. **Safe-exit binder consumption** on Supply Depot exit: the executed exit
   target ROI must come from the shared BlueStacks safe-exit binder candidate
   bound to the current capture (still non-authorizing until capability issuance),
   not a parallel fixed ROI that ignores the binder.
3. **Home Atlas six-state action ledger parity** (requested / authorized /
   dispatched / transport_observed / verified / completed) on the navigate-building
   result path, matching Supply Depot `_execution_payload` semantics.
4. **Same-capture perception bundle** on Supply Depot building and exit steps
   (not only the radial step), or an explicit readiness waiver recorded only if
   composition contracts prove those steps are out of scope — default is require.

Imports, dormant adapters, test mocks, metadata-only probes, and sealed direct
transport helpers do not count as readiness. Live transport success alone does
not waive the gaps above.

## Prerequisites for reconsideration

1. Close the missing integrations above on the real production route paths.
2. Re-run offline focused/adversarial/governance/full-suite gates.
3. Re-run one bounded live reversible validation per touched route when live
   behavior changes.
4. Renew this document with a PASS decision only when two real live-validated
   routes reuse the required architecture without the bypasses listed here.
5. Only then activate `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION`.
6. Leave `M6-DQ-TRANSITION-CORPUS` unactivated until composition completes under
   its own backlog authorization.
