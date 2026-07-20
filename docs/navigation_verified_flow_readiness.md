# Verified-flow composition readiness review

Review date: 2026-07-19

## Decision

`RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION` is blocked. The repository does
not currently contain two real, production-relevant routes that demonstrably
reuse the complete stable architecture:

- immutable perception bundle;
- resumable `NavigationSession`;
- navigation observability;
- radial semantic contract where applicable;
- BlueStacks safe-exit binder where applicable;
- input capability issuance and final consumption.

No composition engine, DSL, generic autonomous runtime, or new route was
implemented.

## Route evidence

### Home atlas navigation

Implementation: `scripts/home_atlas_bluestacks.py`, the
`command_navigate` route.

- Perception entry: uses `BlueStacksHomeLocalizer`, constructs a
  `FramePerceptionBundle`, and calls `checked_navigation_inputs()`.
- Session ownership: creates and persists a `NavigationSession` while planning,
  preparing, dispatching, and reconciling camera pans.
- Semantic binding: binds the visible atlas building through the current
  perception bundle.
- Radial use: the route has a separate Supply Depot radial navigation path, but
  no demonstrated shared composition seam.
- Safe exit: the module exposes an adapter profile helper, but this route does
  not consume the safe-exit binder as an executed route contract.
- Observability: it records the session ledger but does not consume
  `report_navigation_session`.
- Capability boundary: no `CentralPolicy.issue_capability` or final capability
  consumption is present.
- Transport/verification: dispatches directly through `runtime.swipe`; it
  retains route-local immediate-post and settled checks rather than the input
  capability firewall.
- Remaining bypasses: no capability issuance/consumption, no observability
  integration, and direct transport prevent this route from qualifying.

### Noah's Tavern integrated route

Implementation: `scripts/noahs_tavern_recruit_bluestacks.py`,
`NoahTavernIntegratedRoute`.

- Perception entry: calls the route-local
  `recognize_noahs_tavern_frame` recognizer.
- Session ownership: uses `NativeRuntimePort` session/recovery records, not
  the resumable `NavigationSession` contract.
- Semantic binding: uses route-controller commands and target ROIs.
- Radial use: no shared radial semantic contract.
- Safe exit: no BlueStacks safe-exit binder.
- Observability: no `report_navigation_session` integration.
- Capability boundary: no capability issuance or final consumption; transport
  is direct `NativeRuntimePort.tap/back`.
- Transport/verification: route-local result and cooldown reconciliation.
- Remaining bypasses: perception bundle, resumable navigation session,
  observability, safe-exit, and capability firewall are absent.

### Troop-training return-home route

Implementation: `scripts/troop_training_bluestacks.py`,
`TroopTrainingReturnHomeRoute`.

- Perception entry: route-local Home, training, exit-dialog, and radial
  recognizers.
- Session ownership: `NativeRuntimePort` session only; no
  `NavigationSession`.
- Semantic binding: radial facility identity and an exterior-close target are
  locally checked.
- Radial use: route-local radial recognition and safe exterior-close binding.
- Safe exit: local target binding is not the shared BlueStacks safe-exit
  binder contract.
- Observability: no `report_navigation_session` integration.
- Capability boundary: no capability issuance or final consumption; direct
  `runtime.tap/back` transport.
- Transport/verification: route-local Home recognition after input.
- Remaining bypasses: no shared perception bundle, resumable session,
  observability, safe-exit binder, or capability firewall.

## Missing readiness integrations

Before composition can be reconsidered, at least two real routes must:

1. own a `NavigationSession` for the route lifecycle;
2. build and consume same-capture immutable perception bundles;
3. emit navigation observability from that session;
4. use the shared radial semantics when a radial surface is involved;
5. use the shared BlueStacks safe-exit binder for safe-exit behavior;
6. issue and finally consume one-shot input capabilities through the central
   capability firewall at the transport boundary;
7. retain distinct transport-observed and semantic-verification states.

The existing routes are dormant/unregistered or use route-local and direct
transport paths. Imports, helper functions, and test-only composition do not
establish readiness. Registration and scheduler state remain unchanged.
