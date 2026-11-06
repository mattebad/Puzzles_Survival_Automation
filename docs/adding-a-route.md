# Adding (or changing) a route

A *route* is one flow the service can run. This page lists every file you touch, which file owns each
fact, and the check that fails if a copy drifts. Run
`python scripts/check.py` (it includes `tests/test_route_metadata_consistency.py`) after each step;
a missed step names the file and the fact in the failure message.

## Which file owns which fact

| Fact | Owner (edit here) | Derived / checked copies |
| --- | --- | --- |
| Flow id | `automation_service/registry.py` `<ROUTE>_FLOW_ID` (service routes); the route's `scripts/flow_delivery_<route>_bluestacks.py` `FLOW_ID` (development-only routes) | native modules, `pnsctl` aliases and `_DEFAULT_MAX_INPUTS` keys import it; set relations to the operator registry, disabled registry, queue and contracts are checked |
| Family, variant, cadence, reset scope, priority, recurrence | `CANONICAL_FLOW_REGISTRY` entry | every handler and adapter `describe()` returns `canonical_entry(flow_id).descriptor`; the test compares them |
| `serve --flow` name | `cli_name` on the registry entry | `serve --flow` choices, `AutomationService.serve` allowed set, runner lookup (`<cli_name>_runner`), reason-code prefix; README table and example are checked |
| Product id, product revision, handler id, profile, mode | `_FIXED_BINDINGS` in `registry.py` | descriptor, adapter `PRODUCT_ID`/`PRODUCT_REVISION`, scheduler admission facts |
| Total input budget of one run | `max_inputs` on the registry entry, spelled once as `<ROUTE>_MAX_INPUTS` | the adapter's `max_inputs`, the native `flow_delivery_*` `MAX_INPUTS`, the Nova/Recruitment runner arguments, `pnsctl._DEFAULT_MAX_INPUTS`; development-only routes keep their budget in their `flow_delivery_*` module and the queue/contract copies are checked against it |
| Operator runner / validator / recovery ids | `tasks/flow_delivery_bluestacks_registry.json` | `pnsctl.BLUESTACKS_FLOW_IDS` is the set with all three bound in code; the test requires it to equal the registry's flow set |
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
* **Queue**: planning and history. It never authorizes a route, so it must never claim
  `REGISTERED`; its `live_attempts` and receipts are history and are never rewritten or checked for paths.
* **Contracts and product policy**: product semantics and approvals. A contract may exist for a flow that
  is not routed (blocked or contract-only flows).
* **`safe_action_core.policy`**: `CAMPAIGN_AP_FLOW_ID` and `CAMPAIGN_AP_PRODUCT_REVISION` are a second
  copy on purpose (the safety core must not import `automation_service`); the test pins them equal.

Product *revision* has two vocabularies that are intentionally not compared: the registry
`product_revision` is what the scheduler matches against itself (`FlowDescriptor.product_revision` vs
`SchedulerFacts.product_revision`, `automation_service/scheduler.py`), while the policy
`record_revision` versions the policy record and is only matched by contract bindings.

## Checklist for a new service route

1. **Native route** (offline-testable, no ADB at import): semantics and recognition in `tasks/<route>.py`
   (+ `<route>_vision.py`), the native runner in `scripts/<route>_bluestacks.py`.
2. **Operator wrapper** `scripts/flow_delivery_<route>_bluestacks.py`: `RUNNER_ID`, `VALIDATOR_ID`,
   `RECOVERY_ID`, `register()`. Import `FLOW_ID` and `<ROUTE>_MAX_INPUTS` from
   `automation_service.registry`; do not write the literals.
3. **Registry**: in `registry.py` add `<ROUTE>_FLOW_ID`, `_PRODUCT_ID`, `_PRODUCT_REVISION`, `_HANDLER_ID`,
   `_PROFILE_ID`, `_PHASE_MODE`, `_MAX_INPUTS`; a `_FIXED_BINDINGS` entry; a `_canonical_registration(...)`
   call with `cli_name=` and `max_inputs=`; the `__all__` names.
4. **Adapter** `automation_service/<route>.py`: an `ExecutionHandler` whose `describe()` is
   `canonical_entry(FLOW_ID).descriptor`, `max_inputs = <ROUTE>_MAX_INPUTS`, `PRODUCT_ID` and
   `PRODUCT_REVISION` imported from the registry.
5. **Service wiring**: add the `<cli_name>_runner` argument and attribute to `AutomationService`
   (and its all-`None` check), the runner construction in `automation_service/cli.py`, and the route's
   entry in the three code maps inside `AutomationService.serve` (task id, execution-handler class,
   `<route>_next_due`). Those maps bind adapter *code* to a flow id and have no other owner, so a missing
   key fails at `serve` start (`KeyError`), not silently. The `--flow` choice, allowed set, runner lookup
   and reason-code prefix follow from `cli_name`.
6. **pnsctl**: register in `_register_checked_in_bluestacks_handlers()`; add the flow to
   `_DEFAULT_MAX_INPUTS` using the owner constants. Use constants, never flow-id strings.
7. **JSON authorities**: operator registry entry; disabled-production entry (`disabled`, all `null`); a
   contract in `tasks/gameplay_flow_contracts/`; a product-policy record + contract binding if the route
   is product-approved; a queue record with `registration_state: NOT_REGISTERED` and only existing paths.
8. **Docs**: one README route-table row, the `--flow` in the README example, the counts in
   `docs/automation-service.md`.
9. **Tests**: add the route to `EXECUTION_HANDLERS` (and `MAX_INPUT_COPIES` for native copies) in
   `tests/test_route_metadata_consistency.py`, and add its `RouteSpec` to `ROUTES` in
   `tests/support/service_route_contract.py`. The shared service contract must cover every registered
   flow or explicitly name its navigation-only exclusion. Route modules retain native/route-specific
   behavior. Non-applicable invariants need an `EXCEPTIONS` reason and a resolvable covering test;
   production gaps must be labelled `PRODUCTION GAP`, not silently treated as satisfied.
10. Run `python -m unittest tests.test_service_route_contract` and `python scripts/check.py`.

Renaming a flow id is a migration, not a find-and-replace: keep the old id in a migration constant
(`RENAMED_FLOW_IDS`, `RENAMED_TASK_IDS`), retained evidence and historical queue records, and list each
file in `OLD_CAMPAIGN_ID_FILES`-style allowlists in the consistency test.

## Layer layout and intentional exceptions

A route is `tasks/` (semantics) → `scripts/<route>_bluestacks.py` (native runner) →
`scripts/flow_delivery_<route>_bluestacks.py` (operator wrapper) → `automation_service/<route>.py`
(adapter) → registry entry. Existing exceptions:

* **Nova**: no operator wrapper since #35; the adapter calls `scripts/nova_praise_bluestacks.py` directly.
* **Recruitment**: native runner is `scripts/noahs_tavern_recruit_bluestacks.py`; wrapper keeps the old name.
* **Ultimate, Campaign AP, Enhancement**: adapters import their native runner (`bluestacks_ultimate_challenge`,
  `bluestacks_campaign_ap`, `flow_delivery_enhancement_bluestacks`) rather than a `<route>_route` module.
* **World navigation**: registered selection stub only (no adapter, no `cli_name`).
* **Development-only flows** (Daily Row Claim, Daily Resource Item, Troop Training, Ruins, Campaign Atlas):
  operator wrapper and contract, no service adapter and no registry entry; their budgets live in their
  `flow_delivery_*` module.
* **Campaign budgets**: the service route budget (`CAMPAIGN_MAX_INPUTS`, a whole AP drain) is a different
  fact from the single-battle development-session ceiling in `pnsctl`; the test lists the difference.

## Validation

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
and `tests/test_route_metadata_consistency.py` was broken one copy at a time to prove each fact class fails
with a readable message (see the #34 ticket). The checklist has not yet been exercised by building a
brand-new route; the next route is its real test.

The shared service contract is implemented and offline-proven with transport patched out. It exercises
default controls, restart gating, ownership, partial accounting, generation changes, interruption
signals, execution reset guards and cross-route selection. It is not live acceptance and grants no
runtime authority. Recruitment's existing API default when `flow_ids` is omitted remains an explicit
production-gap exception; the contract still checks explicit `serve --flow` parsing for every route.
