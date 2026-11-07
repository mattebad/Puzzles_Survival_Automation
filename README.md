# Puzzles & Survival Automation

Computer-vision automation for the mobile game **Puzzles & Survival**, running against a local
BlueStacks instance. A supervised service checks which daily, cooldown, or timer routes are due, runs one
at a time, verifies each result from the screen, and returns to the game's Home screen before
the next one.

**Status:** Batches A-F add canonical-only Daily Rewards, Resource Item, Ruins, Alliance Help, Alliance Donation, Alliance Shop, Daily Shops, zero-resource Nano Material Production, reset-scoped Normal Craft, Hero Duel, Recommended Research, Food Farm Boost, Hall of War, and Troop Training. Code registration remains separate from runtime enablement: all controls stay off and current live acceptance remains `evidence_required`. Daily Rewards uses the direct canonical Home-to-Daily arrival transition, source/provenance-bound fresh evidence, durable reset/slot identity, individually ready chest claims with same-slot `Claimed` proof, and verified Home closure; a 150-point gate is not required. The bounded #54 canary recognized one glowing 30-point chest and stopped on missing successor proof; the later owner-authorized manual claim supplied actual before/after `Claimed` recognition, not finished-route acceptance. Hero Duel investigation recorded five eligible defense heroes and one free entry/Flee/loss/result cycle, not the required three reset-scoped cycles and lineup/battle acceptance. Research Atlas binding and an idle first recommendation were inspected without a research start or active timer. One owned-item Farm boost and positive timer were observed, with incidental output collection; total inventory and the exact premium-choice branch remain unproven. These are partial observations, not route-level live acceptance. Hall of War's manual #96 investigation observed one dispatch, reconciled
result, and separate Daily Reward row claim; that is not canonical route acceptance, and unexplained
same-reset manual use must not be repeated. Troop Training's current canonical route has offline
contract coverage but no live route acceptance; current numeric maxima are screen-derived. Fighter/
Vehicle box continuations require exact current inventory and effect authority; absent proof, they
remain `evidence_required` and dispatch no boxes or blind warehouse Train. Shooter/Rider never use
boxes. The Commander preset helper
is reused by routes and is not a separate flow. The [November 2 report](docs/bluestacks-route-status-20261102.md) is historical evidence, not authority. Current planning is in [tracker #53](https://github.com/mattebad/Puzzles_Survival_Automation/issues/53).

The owner-authorized #54 observation was exactly one manual chest tap with zero spend; `glowing` to
`Claimed` is its recognition basis. Preserve the raw `UNKNOWN` record unchanged; this one-chest
observation is not combined native route live acceptance (`evidence_required`).

The #66 supervised canaries exposed borrowed-scope and competing-controller-lease failures before Use.
ResourceEffectAuthority now owns its sole Core lease; the existing route session fences its exact
scope through the real canonical input lock. Both failed receipts remain unchanged. Finished-route
live acceptance still requires current proof (`evidence_required`).
The next canary sent one Bag navigation and zero Use calls, then stopped on an unrecognized
successor. Recognition now covers that actual native inset menu and low-contrast item card;
the finished item-decrement/Home scenario remains unaccepted. No identical Bag retry was sent.

Nano building entry reuses the shared Home Atlas pan dispatcher with its native runtime,
fresh capture identities, lease checks and bounded pans. Each confirmed pan is followed
by a fresh mapped binding; an unknown result stops without an identical retry.

Shared exact `[10054]` disconnect recovery (#104) is implemented and offline-proven through the
canonical owner/Core/SQLite boundaries. Explicit opt-in permits at most one Confirm and one
launcher-only start per persistent episode; unknown results stop, and gameplay needs a fresh claim
and route context. Default startup cannot bypass the dialog as “already foreground.”
The first authorized live Confirm exposed a loading successor and stopped safely; actual-capture
replay now covers settling to Home. Explicit zero-input inspection is separate from original-run
acceptance. Native recovery acceptance remains `evidence_required`; controls remain disabled.


## Routes

The service code registers each route in `automation_service/registry.py`. Each row below is one
registration: 23 executable `serve --flow` routes plus one navigation-only flow spec
(24 fixed flow specs total). The `serve --flow` argument takes the name in the first column where present.

| `serve --flow` | Registry family | What it does |
| --- | --- | --- |
| `recruitment` | `recruitment` | Noah's Tavern: uses free recruit attempts as they become available. |
| `nova` | `nova_praise` | One free Nova Praise per cooldown. |
| `campaign` | `campaign_ap` | Spends affordable AP on Auto Battle at `--campaign-stage`, then waits `--campaign-cadence-seconds`. |
| `bioenhancer` | `bioenhancer_research` | One free Bioenhancer Research per cooldown. |
| `supply` | `supply_depot` | Collects free Supply Depot rewards until none remain, once per daily reset. |
| `ultimate` | `ultimate_challenge_daily` | One Ultimate Challenge entry, then Flee, once per daily reset. |
| `enhancement` | `enhancement_family` | Gear, Chip and Module enhancement once each in a single Profile visit, once per daily reset. |
| `personal-might` | `personal_might_praise` | One Personal Might Praise, once per daily reset. |
| `daily-rewards` | `daily_rewards` | At most one current aggregate Claim, then individually ready chests with same-slot Claimed proof; 300-second observation cooldown. Disabled; native acceptance evidence_required. |
| `resource-item` | `resource_item` | One owned 1K Food item use per reset with exact decrement; runtime disabled and current native acceptance remains evidence_required. |
| `ruins` | `ruins_challenge` | Current zero-cost NPC challenge first, then independently claim each green-ready overview chest; unavailable challenge does not suppress ready chests and participation need not win. Runtime disabled; evidence_required; no current live acceptance. |
| `alliance-help` | `alliance_help` | Ten actual successful free Help requests per reset, not ten taps; preserve partial quota and use Help All only when its exact request count is known. Runtime disabled; evidence_required; no current live acceptance. |
| `alliance-donation` | `alliance_donation` | Up to ten confirmed ordinary-resource donations to the automatically selected Alliance Tech per reset; preserve partial progress and defer only on observed attempt/resource unavailability. Unknown effects block identical retry. Runtime disabled; evidence_required; no current live acceptance. |
| `alliance-shop` | `alliance_shop` | One currently affordable allowlisted Weekly Offer, or one exact Other one-star Gear fallback if no preferred offer is affordable; quantity one total. Require paired item/currency effects and canonical Home. Runtime disabled; evidence_required; no current live purchase acceptance. |
| `daily-shops` | `daily_shops` | One visit to Ruins Shop and Rare Earth Shop; one purchase action per exact three-star tab, capped by current stock and affordability. Preserve confirmed tabs and verify numeric quantity/total plus paired effects. Runtime disabled; evidence_required; no current live purchase acceptance. |
| `nano-material-production` | `nano_material_production` | One zero-resource 21600-second production slot: start when idle, claim then restart when complete, and refresh the observed timer without dispatch while active. Its timer persists across game-day boundaries. Runtime disabled; evidence_required; no live acceptance. |
| `nanoweapon` | `nanoweapon` | Same-visit Nano Material maintenance followed by at most one reset-scoped Normal Craft start, exactly 100 Nano Parts and 43200 seconds; claim completed craft when recognized. No Exclusive Craft, Daily/D02 ownership, or points attribution. Runtime disabled; evidence_required; no live acceptance. |
| `hero-duel` | `hero_duel` | Up to three confirmed free entry/Flee/loss cycles per reset after lineup save/verification. One manual investigation cycle is not route acceptance; runtime disabled. |
| `recommended-research` | `recommended_research` | Start only the first displayed recommendation when queue 1 is idle and exact costs/prerequisites are met; freshly bind the mapped Home Atlas Research dome, pan/rebind when HUD-obscured or defer, and never tap through HUD. Runtime disabled; no start/timer live acceptance. |
| `food-farm-boost` | `food_farm_boost` | Reconcile incidental Farm collection, then prefer one exact matching owned-item boost. Consider an exact current diamond option only after exact observed zero inventory, within approved price ceiling and with confirmation/effect proof; unknown inventory is not zero. Verify same-Farm timer. Runtime disabled; no route-level live acceptance. |
| `hall-of-war` | `hall_of_war` | One Zombie Zero dispatch, result reconciliation, then one separate glowing Daily Reward row claim; no win threshold. Manual #96 evidence is not route acceptance; runtime disabled. |
| `troop-training` | `troop_training` | Fighter T8/current numeric maximum and Vehicle T1/current numeric maximum continuously; Shooter T8/250 and Rider T1/250 once per reset. Verify exact costs/effects, queues, timers and saved preset. Fighter/Vehicle boxes remain `evidence_required` absent exact current inventory/effect authority; no blind warehouse Train. Shooter/Rider never use boxes. Runtime disabled. |
| `wali-upgrade` | `wali_upgrade` | Three individual normal upgrades per reset, bounded baseline/final cumulative level and exact debit verification; fresh current quote per tap, no per-tap Back/+1 settlement. Standard evolution never earns or resets normal credit. Durable partial/UNKNOWN handling; no bulk leveling or Reset. Runtime disabled; native acceptance and Campaign/150-diamond Reset remain `evidence_required`. |
| none (navigation-only) | `world_map_navigation` | Registered but never executed by `serve`. |

The `world_map_navigation` registration is navigation-only (registry variant `navigation_only`).
Its handler, `WorldNavigationSelectionHandler` in `automation_service/handlers.py`, is a
selection-only stub with no runtime, target or transport capability: it can be selected by the
scheduler but always reports zero transport, and `serve` has no `--flow` for it. It still has a
persisted flow control, so `status` lists one more flow than there are executable routes.

To add or change a route, follow [docs/adding-a-route.md](docs/adding-a-route.md): it names the
owner of every route fact.

Each registration has a flow id, used by `enable <flow-id>` and `disable <flow-id>`. Run
`automation-service status` to list them. `tests/test_route_metadata_consistency.py` fails if this table
disagrees with the registry or the `serve --flow` choices. Status reports are dated evidence;
a newer filename alone does not establish current acceptance.

## Safety model

- Nothing runs unless both the service control and that route's flow control are on. They are
  stored in SQLite, default to off, and `serve` never turns them on. `emergency-stop` turns the
  service off and stops in-flight runs at their next check.
- Before any tap, the current screen, overlay and target must be recognized in a fresh frame,
  and the run must still hold its claim. A tap that was sent is not success: the expected result
  must be recognized afterwards. Unknown or ambiguous results stop the route and are not retried.
- Only one live controller may own the device at a time. Login, account switching, CAPTCHA and
  similar states stop for a human.
- Documentation, tests and retained evidence never enable a route or authorize live input.

The [service guide](docs/automation-service.md) and the
[operations runbook](docs/pns-operations-runbook.md) give the full control and command reference.

## Setup

Use Python **3.11 or newer** in a virtual environment. On Windows (the BlueStacks host), the Python
Launcher avoids picking up an older `python`:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/check.py
```

On POSIX:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/check.py
```

`scripts/check.py` is the small offline developer smoke check. CI uses the risk-based
selection described below instead of repeating that command after another suite.

## Running

Run everything through `scripts/pnsctl.py`. This is the command shape for all twenty-two executable
routes from the table above; it is not authorization to enable or run them:

```powershell
$runtimeBinding = .\.venv\Scripts\python.exe -c "import json; from tasks.runtime_identity import resource_fixed_runtime_binding; b=resource_fixed_runtime_binding(); print(json.dumps({'account_id': b.account_id, 'server_id': b.server_id}))" | ConvertFrom-Json

.\.venv\Scripts\python.exe scripts/pnsctl.py automation-service `
  --mode supervised --adapter bluestacks `
  --state-path .local-orchestrator/bot-state.sqlite3 serve --live `
  --flow nova --flow recruitment --flow campaign --flow bioenhancer `
  --flow supply --flow ultimate --flow enhancement --flow personal-might `
  --flow daily-rewards --flow resource-item --flow ruins --flow alliance-help `
  --flow alliance-donation --flow alliance-shop --flow daily-shops `
  --flow nano-material-production --flow nanoweapon `
  --flow hero-duel --flow recommended-research --flow food-farm-boost `
  --flow hall-of-war --flow troop-training --flow wali-upgrade `
  --campaign-stage 1-15-9 --campaign-cadence-seconds 300 `
  --adb "C:\Program Files\BlueStacks_nxt\HD-Adb.exe" --serial emulator-5554 `
  --account-id $runtimeBinding.account_id --server-id $runtimeBinding.server_id `
  --output-directory .local-captures/automation-service-live
```

Daily Rewards and Resource Item require these exact fixed-slot scheduler identities, not the
historical `primary-account` / `primary-server` labels. Deriving them is device-free; they identify
the private runtime slot, not an observed game login. Reconcile prior same-reset work before
changing a persisted logical scope; never clear counters or evidence.

This is a launch shape, not current execution authority. The command uses persisted controls
without enabling them. A live scenario needs current explicit authorization, exclusive controller
ownership and finite input/resource budgets. Enable only the authorized controls and restore them
OFF afterward; inspect `automation-service status` before and after.

## Tests

Windows and Linux are the supported full-suite development/CI platforms, with Python
3.11 or newer. From a fresh checkout with `requirements-dev.txt` installed:

```bash
python -B -m unittest discover -v -s tests -t .
```

Routine CI inventories every test module, then executes a declared safety/route-boundary
baseline plus affected coverage. Windows represents the supported bot host; Linux covers
distinct worker, filesystem, SQLite and tooling behavior. Shared Home/OCR/navigation changes
expand their owning tests and representative consumers; bespoke route changes expand that
route and its import-dependent tests. Unknown impact falls back to full execution.

Each job independently verifies actual starts, results, revision, policy and skip identities
against the intended selection. Omitted cases are listed in its receipt, never disguised as
skips or described as full execution. The existing per-OS required-check names remain.

The workflow schedules full Windows/Linux regression daily at 08:23 UTC after merge and on
an explicit full-validation request (workflow dispatch or the `ci:full` PR label). It is not an additional default
pre-merge requirement. The old eight-process Supply repetition is an optional diagnostic
(`supply_stress` input or `ci:supply-stress` label); native Supply canaries still run routinely.
Deferred failures can escape an unrelated PR until the next full run, potentially after merge.
These checks prove offline regressions, not that today's game matches stored screenshots.

See [the CI decision ledger](docs/validation/issue-51/README.md) for exact changes, retained
protection, measured results and accepted coverage loss. Full local execution remains opt-in.

macOS is best-effort, not a full-suite supported platform: tests requiring the
bounded OCR worker skip explicitly because it requires Linux `/proc` or Windows
Job Objects. Pure recognition/preparation tests remain runnable. Missing optional
OCR tooling skips only dependent tests with a reason; CI installs Tesseract.

Run a single module while working on a subsystem:

```bash
python -m unittest tests.test_automation_service_state
```

`tests.test_world_map_navigation_bluestacks` and other fixture-replay modules need a `tesseract`
executable on `PATH` (CI installs it). Tests that need gitignored local captures
(`.local-captures/`) are skipped unless `PNS_LOCAL_CAPTURES=1` is set; with it set, a missing
capture fails the test. Shared fakes and loaders live in `tests/support/`. No offline test run is
a live BlueStacks claim.

## Repository map

- `automation_service/`: the canonical runtime. SQLite state, scheduler, sessions, fencing,
  action execution, screen routing, recovery, and the route registry.
- `safe_action_core/`: action, lease and `ResourceEffectAuthority` safety checks that the
  service reuses.
- `tasks/`: route semantics, recognition, policy data and assets.
- `scripts/`: `pnsctl.py` (the supported command entry point), `check.py`, and BlueStacks
  route and maintenance tooling.
- `tests/`: offline unit, replay, policy, route and safety tests.
- `docs/`: user and maintainer documentation: service guide, runbook, dated status reports,
  route designs, policies, and the planning tickets in `docs/backlog/`.
- `docs/agent/`: volatile agent-workflow state (session handoff, implementation prompts, note
  formats). Not needed to use the bot.
- `docs/archive/`: superseded records kept for history. Not current instructions.
- `evidence/`: retained run evidence. It records what happened and never authorizes a run.
