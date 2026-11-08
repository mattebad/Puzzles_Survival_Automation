# Adding (or changing) a route

A *route* is one flow the service can run. This page lists every file you touch, which file owns each
fact, and the check that fails if a copy drifts. Run the focused
`python -m unittest tests.test_route_metadata_consistency` after metadata edits;
a missed step names the file and the fact in the failure message. Run the route's
focused tests as its behavior changes.

## Which file owns which fact

| Fact | Owner (edit here) | Derived / checked copies |
| --- | --- | --- |
| Flow id | `automation_service/registry.py` `<ROUTE>_FLOW_ID` (service routes); the route's `scripts/flow_delivery_<route>_bluestacks.py` `FLOW_ID` (development-only routes) | native modules, `pnsctl` aliases and `_DEFAULT_MAX_INPUTS` keys import it; set relations to the operator registry, disabled registry, queue and contracts are checked |
| Family, variant, cadence, reset scope, priority, recurrence | `CANONICAL_FLOW_REGISTRY` entry | every handler and adapter `describe()` returns `canonical_entry(flow_id).descriptor`; the test compares them |
| `serve --flow` name | `cli_name` on the registry entry | `serve --flow` choices, `AutomationService.serve` allowed set, runner lookup (`<cli_name>_runner`), reason-code prefix; README table and example are checked |
| Product id, product revision, handler id, profile, mode | `_FIXED_BINDINGS` in `registry.py` | descriptor, adapter `PRODUCT_ID`/`PRODUCT_REVISION`, scheduler admission facts |
| Total input budget of one run | `max_inputs` on the registry entry, spelled once as `<ROUTE>_MAX_INPUTS` | adapter and native budget copies import it; `pnsctl._DEFAULT_MAX_INPUTS` covers only retained operator routes. Canonical Troop Training now owns its budget in the service registry; only the separate Campaign Atlas development flow keeps its budget in a `flow_delivery_*` module. |
| Operator runner / validator / recovery ids, when present | `tasks/flow_delivery_bluestacks_registry.json` | `pnsctl.BLUESTACKS_FLOW_IDS` equals this registry's flow set. Canonical-service-only routes have an explicit checked `NO_OPERATOR_RUNNER` reason instead. |
| Gameplay semantics (states, transitions, permitted inputs, evidence gates) | `tasks/gameplay_flow_contracts/<FLOW_ID>.json` | schema-validated; the optional `product_authority_binding` is validated against the product policy |
| Product record (purpose, recurrence, forbidden actions) | `tasks/flow_delivery_product_policy.json` `product_records` | contract bindings check `record_revision` and digest |
| Development queue record | `tasks/flow_delivery_queue.json` | every `implementation_entrypoints`, `implementation_allowlist_seed`, `focused_tests`, `completion_tests` and `reference_docs` path must exist |
| Disabled-production posture | `tasks/flow_delivery_disabled_production_registry.json` | flow set must contain every code-registry and operator-registry flow |
| README route table, route counts | `README.md`, `docs/automation-service.md` | checked against the registry (row per family, `--flow` names, "N fixed flow specs", "N-route command") |

## Authorities that stay separate, and why

Merging these would let one edit change a safety decision, so each keeps its own file and the test only
asserts the *relation* between them:

* **Code registry** (`automation_service/registry.py`): what the service can compose. It never enables
  anything; enablement is persisted in `BotStateManager` and defaults off.
* **Operator registry** (`tasks/flow_delivery_bluestacks_registry.json`): which routes have a
  development-session runner. A route may be a service route without one (Nova since #35).
* **Disabled-production registry**: legacy posture that every flow is `NOT_REGISTERED`/`disabled`. The
  canonical scheduler does not read it; it must still list every routed flow.
* **Queue**: planning and history. It never authorizes a route or claims canonical `REGISTERED`; its
  existing `production_registration`/`scheduler_enabled` fields describe disabled legacy production posture only.
  Its `live_attempts` and receipts are history and are never rewritten or checked for paths.
* **Contracts and product policy**: product semantics and approvals. A contract may exist for a flow that
  is not routed (blocked or contract-only flows).
* **`safe_action_core.policy`**: `CAMPAIGN_AP_FLOW_ID` and `CAMPAIGN_AP_PRODUCT_REVISION` are a second
  copy on purpose (the safety core must not import `automation_service`); the test pins them equal.

Product *revision* has two vocabularies that are intentionally not compared: the registry
`product_revision` is what the scheduler matches against itself (`FlowDescriptor.product_revision` vs
`SchedulerFacts.product_revision`, `automation_service/scheduler.py`), while the policy
`record_revision` versions the policy record and is only matched by contract bindings.

Tracker #53 is the current planning authority. `BACKLOG.md` retains durable history and is not
the active route sequence.

## Checklist for a new service route

1. **Native route** (offline-testable, no ADB at import): semantics and recognition in `tasks/<route>.py`
   (+ `<route>_vision.py`), the native runner in `scripts/<route>_bluestacks.py`.
2. **Execution boundary**: new routes use the canonical service and their fixed native factory.
   Do not create a second development runtime or a forwarding `flow_delivery_*` wrapper.
   Retained development-only routes may have an operator wrapper and its existing controls.
3. **Registry**: in `registry.py` add `<ROUTE>_FLOW_ID`, `_PRODUCT_ID`, `_PRODUCT_REVISION`, `_HANDLER_ID`,
   `_PROFILE_ID`, `_PHASE_MODE`, `_MAX_INPUTS`; a `_FIXED_BINDINGS` entry; a `_canonical_registration(...)`
   call with `cli_name=` and `max_inputs=`; the `__all__` names.
4. **Adapter** `automation_service/<route>.py`: an `ExecutionHandler` whose `describe()` is
   `canonical_entry(FLOW_ID).descriptor`, `max_inputs = <ROUTE>_MAX_INPUTS`, `PRODUCT_ID` and
   `PRODUCT_REVISION` imported from the registry. New runners receive a
   `NativeRouteBoundary` from `automation_service/native_execution.py`; do not import
   `scripts` or the operator wrapper into the adapter.
5. **Service wiring**: add the `<cli_name>_runner` argument and attribute to `AutomationService`
   (and its all-`None` check), the runner construction in `automation_service/cli.py`, and the route's
   entries inside `AutomationService.serve` for task id, execution-handler class,
   `<route>_next_due`, consequential-dispatch accounting, and outcome/recurrence projection.
   Pass the actual claimed run's `occurrence_key` to the new runner; do not derive it
   from a frame, balance, timestamp or a native quota counter. Missing code bindings
   fail at `serve` start rather than silently. The `--flow` choice, allowed set,
   runner lookup and reason-code prefix follow from `cli_name`.
6. **pnsctl**: install the native module's fixed
   `create_service_binding(make_native_route_binding)` in the operator composition,
   and pass the flow-id-keyed `native_route_bindings` mapping through the canonical
   CLI to the runner. The factory is device-free: no store, ownership or device access.
   Use owner constants. Only retained operator routes belong in
   `_register_checked_in_bluestacks_handlers()` and `_DEFAULT_MAX_INPUTS`.
7. **JSON authorities**: disabled-production entry (`disabled`, all `null`); a
   contract in `tasks/gameplay_flow_contracts/`; a product-policy record + contract binding if
   approved; a queue record with existing paths and the A-schema `production_registration:
   NOT_REGISTERED` (legacy disabled-production posture) and `scheduler_enabled: false` fields.
   Add an operator registry entry only for a retained development runner. Service-only routes
   require the explicit metadata-test exception, not a no-op operator triple.
8. **Docs**: one README route-table row, the `--flow` in the README example, the counts in
   `docs/automation-service.md`.
9. **Tests**: add the route to `EXECUTION_HANDLERS` (and `MAX_INPUT_COPIES` for native copies) in
   `tests/test_route_metadata_consistency.py`, and add its `RouteSpec` to `ROUTES` in
   `tests/support/service_route_contract.py`. The shared service contract must cover every registered
   flow or explicitly name its navigation-only exclusion. Route modules retain native/route-specific
   behavior. Non-applicable invariants need an `EXCEPTIONS` reason and a resolvable covering test;
   production gaps must be labelled `PRODUCTION GAP`, not silently treated as satisfied.
10. Run the route's focused tests and `python -m unittest tests.test_service_route_contract`.
    The broader developer smoke command `python scripts/check.py` remains available;
    it need not be repeated after every checklist step.

Choose scheduler cadence independently from the gameplay quota. A normal
`daily_once_per_reset` route result consumes its occurrence even when `DEFERRED`;
partial gameplay quotas therefore use cooldown/timer recurrence and stable
per-reset action keys. The canonical network-recovery-only prelude is a narrow
exception: after verified recovery and zero route actions, its typed
`preserve_for_fresh_context` disposition retains the original run/occurrence/reset
history and actual recovery input charges while permitting a fresh run/token for
the same gameplay occurrence. Route results cannot use it to refund gameplay.
Unknown effects still block; a later occurrence never authorizes repeating them.

Renaming a flow id is a migration, not a find-and-replace: keep the old id in a migration constant
(`RENAMED_FLOW_IDS`, `RENAMED_TASK_IDS`), retained evidence and historical queue records, and list each
file in `OLD_CAMPAIGN_ID_FILES`-style allowlists in the consistency test.

## Layer layout and intentional exceptions

Route semantics live in `tasks/`, native recognition/input in
`scripts/<route>_bluestacks.py`. Retained development routes keep operator
validation/recovery in `scripts/flow_delivery_<route>_bluestacks.py`.
New canonical adapters consume the pure `NativeRouteBoundary` protocol, injected
by `pnsctl`. Their fixed native
drivers share `scripts/base_route_native_runtime.py` for the borrowed owner,
canonical action-store lease, checkpoints, capture/replay, startup recovery,
input accounting and teardown. Drivers retain route-specific recognition,
consequential policy and semantic acceptance. The shared boundary does not
authorize gameplay or convert transport success into a committed effect.
Resource Item selects `driver_manages_action_lease=True`: its existing
`ResourceEffectAuthority` owns and releases the sole Core controller lease, rather than
competing with a second bridge lease. Its `DevelopmentSession.assert_held` fences the exact
route scope through the actual canonical input lock and checkpoint; it does not acquire
another operator or bypass lost ownership.

Existing layout exceptions:

* **Nova**: no operator wrapper since #35; the adapter calls `scripts/nova_praise_bluestacks.py` directly.
* **Recruitment**: native runner is `scripts/noahs_tavern_recruit_bluestacks.py`; wrapper keeps the old name.
* **Ultimate, Campaign AP, Enhancement**: adapters import their native runner (`bluestacks_ultimate_challenge`,
  `bluestacks_campaign_ap`, `flow_delivery_enhancement_bluestacks`) rather than a `<route>_route` module.
* **World navigation**: registered selection stub only (no adapter, no `cli_name`).
* **Development-only Campaign Atlas**: its separate retained wrapper and contract have no service
  adapter or code-registry entry; its budget remains in its `flow_delivery_*` module. Troop Training
  is no longer in this exception after the Batch F canonical service cutover.
* **Batch A Daily Rewards and Resource Item**: canonical service routes with fixed native bindings;
  their former development wrappers/operator rows are retired and must not be reintroduced as a
  second dispatch path. Both remain runtime-disabled and `evidence_required`. The supplied Nov 6
  DailyQuest image shows one 30-point glowing chest, four closed chests, 30 points, and no aggregate
  Claim. Policy handles each of five chest categories independently when glowing, with no 150-point
  minimum. A native pass with zero ready chests can complete without an aggregate Claim; after a
  confirmed aggregate Claim, it requires fresh proof that all five chests are static. A ready chest
  still requires its same-chest claimed/opened successor; current native readiness is not live
  completion acceptance.
* **Batch B Ruins and Alliance Help**: canonical-service-only routes with registered fixed specs and
  injected native bindings; no legacy operator runner or operator-registry row. Queue `NOT_REGISTERED`
  refers only to disabled legacy production posture; SQLite service/flow controls remain off. Both
  are `evidence_required`, with no current native live acceptance claimed. Ruins attempts the current
  zero-cost challenge first, then independent green-ready overview chests even if it is unavailable;
  Help counts actual successful free requests, preserves partial quota, and uses Help All only when
  the exact request count is known.
* **Batch C Alliance Donation, Alliance Shop, and Daily Shops**: canonical-service-only routes with
  fixed native bindings; they add no legacy operator registry entries. `REGISTERED` describes code
  composition only; production posture and SQLite runtime controls remain disabled, and current
  native acceptance remains `evidence_required`. Donation is capped at ten semantically confirmed
  actions per reset; attempted transport calls remain separate from confirmed actions, and an
  unknown effect blocks an identical retry. Alliance Shop selects one affordable allowlisted Weekly
  offer or the exact one-star Other fallback, never both. Daily Shops handles the exact three-star
  Ruins Chip and Rare Earth Module tabs independently, at most one purchase action per tab, capped
  by current stock and affordability. Preserve one tab's confirmed purchase across a later pulse.
  No current donation quota or purchase-effect live acceptance is claimed; the single donation information probe is not route
  acceptance.
  Donation entry recognizes the centered Alliance title separately from Back/border art and
  isolates adjacent Alliance Tech words from a shared multi-column OCR line. Known-context
  failure recovery rebinds Back against a fresh surface; an unknown or changed source gets
  no speculative return input. Real-pixel recognition proof is not donation-effect acceptance.

* **Batch D Nano Material Production and Nanoweapon**: canonical-service-only routes with fixed
  native bindings and no operator rows. Nano Material Production uses a non-reset-scoped timer
  for exactly one zero-resource 21600-second slot: start when idle, claim then restart when
  complete, and refresh its observed timer without dispatch while active. Nanoweapon's v2 product
  policy requires that separately authorized maintenance result earlier in the same visit, then
  permits at most one reset-scoped Normal Craft start costing exactly 100 Nano Parts for 43200
  seconds; Exclusive Craft, Daily/D02 ownership, and points attribution are prohibited. Code
  registration remains separate from production posture and SQLite controls: both routes stay
  runtime-disabled with live acceptance `evidence_required`; no live acceptance is claimed.

* **Batch E Hero Duel, Recommended Research, and Food Farm Boost**: canonical-service-only routes
  with fixed native bindings and no operator rows. E retained the twelve existing legacy operator
  choices; Batch F later retires Training's choice, leaving eleven. Product approval does not enable
  production registration or runtime controls: each route remains disabled and `evidence_required`.
  Offline route contracts and native scenarios model durable attempts separately from confirmed
  resource effects, restart/partial/unknown outcomes, and no identical retry after unresolved effects.
  Hero Duel requires three reset-scoped free entry/Flee cycles, a saved and verified first-five defense lineup, and all-five
  eligible attack lineup with battle/Exit/Flee/result evidence; a win is not
  required. Research considers only the first displayed ordinary-queue recommendation when idle and
  affordable; it freshly binds the mapped Home Atlas Research dome. If HUD obscures the target, safely
  pan/rebind or defer, never punch through the HUD. Research Now diamonds, Queue 2, substitutes, boxes
  and gathering remain prohibited. Food Farm reconciles incidental multi-building collection, then
  prefers an exact matching owned item. Consider a diamond option only after inventory is observed
  exactly zero and the exact current price is within the approved ceiling, with confirmation/effect
  proof; unknown inventory is not zero. Item action cost 1 is not a total-inventory claim and global
  Food Output Boost is prohibited. Current manual evidence is narrower than acceptance: Hero Duel has
  one free loss cycle and five eligible defense heroes observed; Research had no start/timer proof;
  Food Farm had one owned-item boost with a positive timer and incidental multi-building collection,
  while total inventory and the premium branch remain unproven. These are not route-level acceptance.

* **Batch F Hall of War and Troop Training**: canonical-service-only routes with fixed
  bindings; no compatibility runner, validator, operator-registry row, or second input-budget owner
  is retained for Training. The supported manual-only `pnsctl bluestacks recover-home` remains
  distinct. The Commander preset helper is shared, not a standalone flow: every use requires fresh
  exact `Applied` recognition; cached readiness is not proof, and no redundant switch occurs when
  the required preset is already Applied. Both routes are product-approved but remain unregistered
  for production, scheduler-disabled, and runtime-disabled with live acceptance `evidence_required`.
  Hall requires current reset/preset/lineup evidence, one Zombie Zero dispatch and reconciled result,
  then one separate glowing Daily Reward row claim; no win threshold applies. The manual #96
  dispatch/result/row-claim investigation is raw evidence, not canonical route acceptance, and
  unexplained same-reset manual use must defer without retry. Training preserves Fighter T8 and
  Vehicle T1 at the current displayed numeric maximum with continuous policy, Shooter T8 and Rider
  T1 at 250 once per reset, exact resource before/after reconciliation, recognized queue state and
  positive timer. The maximum is dynamic, never a pinned historical quantity. Fighter/Vehicle box
  continuations require exact current inventory and effect authority; absent proof they remain
  `evidence_required`, with no box dispatch, expected-warehouse assumption, or blind Train.
  Shooter/Rider never open boxes. No Train Now, premium, speedup, Daily/D02/points prerequisite, or
  separate Commander route. Historical legacy Training evidence does not establish canonical
  live acceptance.

* **Conditional Wali Upgrade (#74)**: canonical-service-only `wali-upgrade`, using the existing
  `tasks/hero_upgrade_disabled.py` semantic owner despite its historical filename. The fixed
  native binding, adapter and Core admission allow only exact selected-Wali single normal
  upgrades and current affordable standard evolution behind canonical authorization and
  freshness fences. Normal ordinals 1–3 are reset-scoped; evolution-cap keys are separate,
  and its automatic level never resets or increments that quota. Preserve transient named
  manual-use receipts and the settled successor as distinct frames; do not manufacture numeric
  spend receipts from quoted costs. Bulk leveling, Enhance, boxes and premium materials are
  prohibited. The unverified Campaign/150-diamond Reset path has no admitted input. The legacy
  operator `bluestacks verify-flow` is not this service-only route's validation entrypoint;
  the canonical native boundary validates its semantic result and action journal. Keep
  current live authorization, route acceptance and disabled deployment posture distinct.
  A normal Upgrade opens a separate bulk row. One route-owned, non-spending Back per pending
  single action may reveal the current detail screen or the recognized roster, followed only
  by current named Wali reselection. Unknown dismissal stops without another Back or Upgrade.
  These navigation inputs count against the physical budget, not the three-action quota.
  The complete current quote is hashed into the capability-bound action ID while the action
  key retains its stable reset/ordinal identity; changing a quoted balance or cost invalidates admission.


* **Campaign budgets**: the service route budget (`CAMPAIGN_MAX_INPUTS`, a whole AP drain) is a different
  fact from the single-battle development-session ceiling in `pnsctl`; the test lists the difference.

## Validation

Reuse the shared service contract for ownership, stop/generation, unknown-effect
and accounting rules. Add native cases for the route's distinctive semantics and
recognition, plus a representative integration in the Windows baseline in
`ROUTE_BOUNDARIES` in `scripts/offline_selection.py`. The registered-route check
requires a baseline consumer for every executable service registration. Add or verify
its affected-family/import mapping.
Shared Home/OCR/popup variants belong in their owning suite and a representative
consumer matrix, not copied through every route. Expanded native/recovery cases
run on relevant changes and the periodic full validation; document any new risk
that the common contract does not cover. A new route does not justify multiplying
the entire shared suite on every unrelated PR.

Retained executable adapters must bootstrap the repository root before importing project packages.
Check direct file entry with the repository `PYTHONPATH` unset, for example
`python -B scripts/bluestacks_campaign_ap.py --help`; importing the module from the test runner does
not verify that entry path. This is an offline startup check only: do not pass `--execute` or use a
device, and do not treat successful help output as live acceptance.

Zero-delay offline fixtures must give their synthetic captures, event timestamps and policy clocks
one fixture-local clock with explicit event ordering. Keep tests that reject tied UTC or monotonic
successors. Real OCR must retain its real bounded worker clock; do not patch global time or relax
production ordering, freshness or OCR deadlines to make a fixture pass.
Native OCR fixture failures should retain the semantic observation status and reason, not just a
screen-level ambiguity that can collapse provenance, worker and deadline failures.

The owners above were established by migrating the existing routes onto them (descriptors, input
budgets, `--flow` names, pnsctl flow ids, the missing Personal Might queue record, 74 dead queue paths),
and `tests/test_route_metadata_consistency.py` was previously broken one copy at a time to prove each
fact class fails with a readable message (see the #34 ticket).

The shared service contract covers default controls, restart gating, ownership, partial accounting,
generation changes, interruption signals, execution reset guards and cross-route selection. B and
C add cases for the real service manager that preserve opaque occurrence keys and actual counts,
exercise borrowed-owner/generation/lease fences, and deny identical retries after unknown effects.
C baselines distinguish attempted purchase/donation transports from semantically confirmed actions,
preserve donation progress across an availability defer, and resume a confirmed Daily Shops tab
without repurchasing it. The documentation does not claim focused checks or live acceptance ran.
Recruitment's existing API default when `flow_ids` is omitted remains an explicit
production-gap exception; the contract still checks explicit `serve --flow` parsing for every route.
