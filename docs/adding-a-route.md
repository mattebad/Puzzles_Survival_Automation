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
| Operator runner / validator ids, when present | `tasks/flow_delivery_bluestacks_registry.json` | `pnsctl.BLUESTACKS_FLOW_IDS` equals this registry's flow set. Canonical-service-only routes have an explicit checked `NO_OPERATOR_RUNNER` reason instead. |
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

Renaming a flow id is a migration, not a find-and-replace: keep the old id in the
migration tables (`RENAMED_FLOW_IDS`, `RENAMED_TASK_IDS`), retained evidence and
historical queue records. Verify persisted limits migrate and retired ids cannot
select an active canonical handler; do not scan or rewrite historical evidence.

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
  second dispatch path. Both remain runtime-disabled. Daily rewards remain `evidence_required`.
  The supplied Nov 6 DailyQuest image shows one 30-point glowing chest, four closed chests,
  30 points and no aggregate Claim. Policy handles each of five chest categories independently
  when glowing, with no 150-point minimum. Ready chests do not require aggregate Claim
  availability or a complete ordinary-control scan. Any sent aggregate Claim must settle
  before further gameplay. Each affected chest needs its own claimed/opened/removed successor.
  Incomplete chest observations defer without requiring all five chests static merely to
  return Home. These implemented guards are not fresh native completion acceptance.
  Resource Item has source-scoped native acceptance at integrated source `a4811874`
  (2026-11-08): one owned 1K Food, inventory 129810 to 129809, one confirmed authority effect,
  three inputs and verified Home. This is a dated receipt, not an inventory constant or
  execution permission; see issue #66. It does not establish Daily Quest ownership or
  acceptance of other branches/source revisions.
* **Batch B Ruins and Alliance Help**: canonical-service-only routes with registered fixed specs and
  injected native bindings; no legacy operator runner or operator-registry row. Queue `NOT_REGISTERED`
  refers only to disabled legacy production posture; SQLite service/flow controls remain off. Both
  are `evidence_required`, with no current native live acceptance claimed. Ruins advances through
  freshly identified allowed free NPC stages until the first loss or genuine unavailability,
  then collects independent green-ready overview chests. Loss is durable for that reset;
  finite-budget pauses preserve the stage prefix for a later visit. No full-troop, Skip Battle,
  medal arithmetic, weekly wording or twelve-category coverage gate is required.
  Help prefers one independently identified free Help All batch per visit when a ready-request
  context is visible; individual requester/name OCR is not required. The gold footer remains on
  the empty page and cannot establish readiness. Credit only actual proven successful requests
  toward ten; preserve a positively successful unknown-count batch without claiming one or ten
  or marking its effect UNKNOWN.
  A genuinely ambiguous effect remains UNKNOWN with no identical retry. Help recognizes the Alliance menu by its centered title,
  exact bottom-bar labels and clear overlay, and binds the bottom-bar Alliance Help target.
  That opens the distinct Alliance Help hub; only its current recognized Speedup Help row
  may be opened, never Transport Resources or Reinforce Allies. A positively recognized
  Alliance menu, Help hub or Speedup Help starting context first returns to fresh Home
  through at most three distinct rebound Back controls before normal entry; unknown or
  unchanged sources/successors send no repeated input. Native effect acceptance remains separate.
  Verified recovery, entry and terminal navigation use distinct phase/step identities, allowing
  a later return through identical menu pixels without weakening gameplay duplicate protection.
  Ruins completes bounded zoom normalization and calculated Atlas pans with fresh localization,
  mapped building binding and route-owned successor recognition. Session accounting adopts only
  a monotonic cumulative dispatch total from the same retained journal, including startup inputs;
  missing journal rows, interleaved inputs or unchanged/unknown successors fail closed.
  The native overview title and controls use the same isolated regions as Daily Shops.
  Wallet OCR excludes the coin artwork and includes the complete numeric field; missing,
  boundary-clipped or ambiguous text produces an unknown balance, never a guessed maximum
  or concatenated digits. Actual retained overview pixels and counterfactual failure cases
  prove these guards offline, not challenge/chest live acceptance.
* **Batch C Alliance Donation, Alliance Shop, and Daily Shops**: canonical-service-only routes with
  fixed native bindings; they add no legacy operator registry entries. `REGISTERED` describes code
  composition only; production posture and SQLite runtime controls remain disabled, and current
  native acceptance remains branch/source-specific. Donation is capped at ten confirmed individual
  HOT-tech actions per reset. Read the ordinary numeric cost and affordable white/red state,
  not a full resource census; attempts establish count, allowing an unchanged count only with
  positively observed thirty-minute regeneration. Ranking points and bonuses are not counts.
  Available attempts may be used consecutively; true UNKNOWN blocks identical retry.
  Alliance Shop buys one affordable exact allowlisted Weekly offer or the exact Other one-star
  Gear fallback, never both. A red preferred-price shortage permits fallback without Owned
  evidence. Exact item x1 purchase acknowledgement proves the effect before terminal Home.
  Timed Tavern Coins match the observed exact UI name `Timed Recruit Coin`; this preferred
  item may use the current Diamonds quote, unlike ordinary Alliance Coins offers. Read its
  current price and affordable balance; a conservative HUD balance is a lower bound, not
  an exact wallet receipt. Product allowlisting is not standing premium-spend authorization:
  any future live scenario must separately record its finite applicable resource budget.
  The current-quote `maximum_cost` alone does not establish that independent approval.
  Daily Shops evaluates both approved three-star tabs in one visit, using min(stock, affordability)
  and fresh numeric quantity/total before inner Buy. Exact item xN acknowledgement plus stock
  decrease confirms a tab; Owned and wallet arithmetic are not effect gates. Confirmed prefixes
  survive a blocked/unavailable sibling tab as deferred progress. Historic recovered Bioenhance
  completion is retained without another Buy; revised/fallback and Daily Shop purchase branches
  remain evidence_required, and the single donation investigation is not quota acceptance.
  Donation entry recognizes the centered Alliance title separately from Back/border art and
  isolates adjacent Alliance Tech words from a shared multi-column OCR line. Known-context
  failure recovery rebinds Back against a fresh surface; an unknown or changed source gets
  no speculative return input. Real-pixel recognition proof is not donation-effect acceptance.
  Donation's tree recognizer reads exact HOT text inside a unique measured red ribbon
  through the bottom of the native viewport. That current widget permits navigation
  to its panel even when the tree label is clipped; no name or technology is guessed,
  and no corrective drag competes with the game's automatic scrolling. The fresh
  panel must independently prove its full identity and current HOT marker before any
  resource/attempt donation guards can authorize an effect. Missing, ambiguous or
  changed-context evidence stops without speculative effects. Fixture provenance
  uses original-workspace-relative paths; native pixels and source hashes are preserved.
  Alliance Shop rebinds the fresh Home footer through the shared recognizer and distinguishes
  the actual Alliance title and red-selected Shop tabs from incidental navigation labels.
  Current offer fields are isolated against measured Buy controls; price OCR excludes the
  matched currency artwork and keeps the original currency-match threshold. Inventory
  scrolling avoids Buy controls, and end-of-list evidence excludes the ticking header.
  Unknown Owned evidence does not block an otherwise exact affordable offer or red-shortage
  fallback evaluation; unknown required price, stock or currency remains incomplete.
  Quantity dialogs bind the exact allowlisted title, measured selected quantity and
  numeric total independently; the Total coin must match the fresh offer-frame coin
  at the existing threshold, never the blurred modal background. A positively identified
  own modal may close through its freshly rebound white X and return via known Alliance
  pages to verified Home, including on restart. Unknown modal structure receives no
  guessed dismissal or Buy. Actual-pixel replay proves these guards, not purchase effects.
  Startup and terminal returns use separate navigation phase identities, including
  source/target duplicate identity. Each Back must reach a different known parent page;
  unchanged or unknown successors stall that phase without another identical input.
  This preserves legitimate revisits without weakening purchase-key protection.
  Daily Shops reuses canonical Atlas startup normalization and its scrcpy simultaneous-pointer
  transport for at most two accounted zoom inputs; the sequential virtual-touch pinch is not
  a substitute for an observed camera transition. It then uses shared bounded calculated pans,
  fresh mapped Mystery Shop binding and route-owned Mystery Shop/shop-tab successors.
  Select the exact Ruins and Rare Earth tabs inside that shop. Unknown or unchanged navigation
  stops; an absent action-store lease dispatches nothing. The walkthrough's Ruins/Exchange
  entry was historical manual navigation, not a production entry binding. Earlier canonical
  Ruins-overview visits proved no purchase or acceptance of this revised entry route.
  On restart, Daily Shops may return from a positively recognized shop context to freshly
  verified Home before a new mapped Mystery Shop entry.
  Unknown contexts receive no speculative Back; recovery inputs remain in canonical totals.
  Shop identity uses the isolated title and uniquely gold-selected current Shop label,
  not incidental item-description OCR. A clipped Rare Earth label permits one bounded
  selector reveal, then a fresh exact-label binding; unknown selection or no progress
  authorizes no guessed tab tap. Current native Shop pixels prove these recognition
  guards offline, not purchase effects; no Owned baseline is required. The Rare Earth selected
  successor and both actual purchase acknowledgement/stock successors remain evidence_required.

* **Batch D Nano Material Production and Nanoweapon**: canonical-service-only routes with fixed
  native bindings and no operator rows. Nano Material Production uses a non-reset-scoped timer
  for exactly one fixed free 21600-second slot: Produce when idle, Claim then restart when
  completed, and observe its timer without dispatch while active. No Info visit or textual
  free/cost/duration quote is required. Nanoweapon v3 accepts verified active production with
  zero effects as same-visit maintenance. Free completed Craft Claim is independent of its
  original automated Start, current quote or affordability; active craft needs no new quote.
  One current-reset Normal Craft Start remains fixed at 100 Nano Parts/43200 seconds, using
  current affordability with no quantity-one caption requirement. Keep production Claim/Start
  and Craft Claim/Start proofs separate; an unsent later action or navigation failure does not
  turn confirmed effects into UNKNOWN. Genuine UNKNOWN still denies identical retry.
  Exclusive Craft, Daily/D02 ownership and points attribution remain prohibited. Controls
  stay disabled and native acceptance remains evidence_required.
  Native factory validators inspect requests, not result mappings; production result/effect
  validation remains separate from request admission. Offline startup exercises the actual
  fixed binding with a held temporary runtime lock and device-free transport.
  Production reuses the canonical scrcpy Atlas normalizer for zoomed Home entry and
  terminal normalization. Each physical zoom belongs to the existing DevelopmentSession
  through run_action; no cumulative external-count adoption is mixed with session-owned
  route inputs. Unknown or unchanged zoom results receive no identical input, and input
  budgets and source fences still apply. Direct-runtime consumers retain their existing
  final cumulative adoption. Real-session replay proves these paths offline, not live
  production acceptance.

* **Batch E Hero Duel, Recommended Research, and Food Farm Boost**: canonical-service-only routes
  with fixed native bindings and no operator rows. E retained the twelve existing legacy operator
  choices; Batch F later retires Training's choice, leaving eleven. Product approval does not enable
  production registration or runtime controls: each route remains disabled and `evidence_required`.
  Offline route contracts and native scenarios model durable attempts separately from confirmed
  resource effects, restart/partial/unknown outcomes, and no identical retry after unresolved effects.
  Hero Duel performs three reset-scoped free Entry/loaded-battle/Exit/Flee/result cycles without
  requiring a win. Save and verify the first five currently eligible defense portraits; fill missing
  attack slots without clearing a valid five. Do not census paid passes or fixed emergency
  exclusions, or force a universal operation-ordinal/free-allowance equation. Actual exhausted
  free allowance defers unfinished quota; true UNKNOWN remains fenced.
  Research uses only the first displayed ordinary-queue recommendation when idle, with actual
  prerequisites, costs and balances satisfied. Bind the mapped Research Center freshly, pan/rebind
  or defer if obscured. Its positive effect is that same technology active with a timer, not four
  post-debits. Do not inspect forbidden Research Now prices or use Queue2, boxes or gathering.
  Farm first-tap settlement is the same bound Home/Farm radial context, not proof that collection
  occurred. Credit collection only on a positive Food HUD tick; it is never a boost prerequisite.
  Prefer a positively usable matching owned item, otherwise a current eligible diamond option
  with sufficient balance and actual price within48. Neither action-cost1 nor an unreadable
  inventory proves total inventory; require no census or invented confirmation dialog.
  Verify the same Farm's positive Boosting timer; global Food Output Boost remains forbidden.
  Historical manual Duel/Farm observations are narrower than revised route acceptance.
  Research uses the bounded OCR caller deadline; missing actual prerequisites/costs blocks Start,
  and current native same-target active-timer acceptance remains evidence_required.

* **Batch F Hall of War and Troop Training**: canonical-service-only routes with fixed
  bindings; no compatibility runner, validator, operator-registry row, or second input-budget owner
  is retained for Training. The supported manual-only `pnsctl bluestacks recover-home` remains
  distinct. Commander presets are a shared helper, not a standalone flow: exact saved Economy,
  Military and Training rows are resolved and Applied is verified. Do not assume switches are
  free: the manual Training switch displayed no price, and its debit was not inspected.
  An explicit applicable scenario approval must bind cost and any allowed confirmation.
  The observed allocated-points `Reset now?` confirmation is Training-specific and requires
  its exact permit; historical one-time approval does not authorize future resets or edits.
  Unknown-cost future switches defer. Already-Applied presets are not switched again; proof
  reuse requires the same session, generation, context and runtime ownership.
  Hall requires Military, populated saved Troop Set1, one Zombie Zero dispatch/result and one
  glowing daily reward row changing to Claimed. Its fixed zero-resource/zero-loss mechanic needs
  no literal disclosure, full troop capacity, TodayDamage zero or Sets2/3 labels. Its three-effect
  visit budget includes an optional preset switch, dispatch and reward, not extra reset dispatches.
  Training requires Training Applied before starts and reuses valid proof instead of reopening
  the helper mid-training. FighterT8/VehicleT1 use each new batch's current numeric maximum
  continuously; ShooterT8/RiderT1 use250 once/reset. Active/completed batches retain the immutable
  recorded start quantity, not a later carousel maximum; timers use actual capture/tap UTC.
  Fighter/Vehicle boxes remain `evidence_required`: projected totals do not identify boxes or prove
  owned counts. Keep scoped Core denial until real exact authority exists; no invented DTO or blind
  Train. Shooter/Rider never use boxes. All revised native branches remain evidence_required;
  historical manual/legacy evidence does not establish canonical live acceptance or enablement.
  Economy remains a supported saved-memory identity, but there is no existing authorized
  production/helper-inspection consumer for it. Its switch acceptance remains an explicit gap;
  a test-only identity is not gameplay authority and no standalone flow is added.
  Existing recovery ends the native visit on network loss and closes its session; a later visit
  starts with empty session proof. Manual-required contexts deny instead of resuming a cached
  proof. No surviving same-session recovery hook or additional cache subsystem is introduced.

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
  Normal upgrades use one bounded batch intent, baseline/final cumulative level proof and
  exact debit equal to the sum of journaled current quotes. Re-read the normal control and
  quote before every individual tap; never fabricate intermediate settled successors.
  Cap/evolution, shortage or unreadable quote splits the batch and preserves only an exactly
  verified prefix. Normal input limit is at most the remaining reset quota and displayed cap.
  A separate bulk row is never pressed; at most one route-owned non-spending Back after the
  batch may reveal current details or the recognized roster plus named Wali reselection.
  No mandatory per-input Back/+1 settlement. UNKNOWN forbids another Back or Upgrade.
  Navigation counts against the physical budget, not normal quota. Bind fresh current quotes
  to each input and keep stable reset/first-ordinal batch keys. Historical confirmed single
  journals remain progress; new execution writes only the batch contract.


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
