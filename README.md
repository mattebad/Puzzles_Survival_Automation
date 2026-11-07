# Puzzles & Survival Automation

Computer-vision automation for the mobile game **Puzzles & Survival**, running against a local
BlueStacks instance. A supervised service checks which daily or cooldown routes are due, runs one
at a time, verifies each result from the screen, and returns to the game's Home screen before
the next one.

**Status:** Batches A-C add canonical-only Daily Rewards, Resource Item, Ruins, Alliance Help,
Alliance Donation, Alliance Shop, and Daily Shops integration. Code registration is separate
from runtime enablement: these routes remain runtime-disabled with current live acceptance
`evidence_required`. Daily's supplied image proves five-chest readiness. A native pass with zero
ready chests can return to verified Home without aggregate Claim; after a confirmed aggregate Claim,
fresh evidence that all five chests are static is required before Home. A ready chest still needs a same-chest claimed/opened
successor. The [November 2 report](docs/bluestacks-route-status-20261102.md) is historical live
evidence, not current execution authority. Current planning is in
[tracker #53](https://github.com/mattebad/Puzzles_Survival_Automation/issues/53);
[`BACKLOG.md`](BACKLOG.md) retains durable history.

## Routes

The service code registers each route in `automation_service/registry.py`. Each row below is one
registration: fifteen executable `serve --flow` routes plus one navigation-only flow spec
(sixteen fixed flow specs total). The `serve --flow` argument takes the name in the first column where present.

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
| `daily-rewards` | `daily_rewards` | Aggregate Claim plus up to five individually glowing chests; no 150-point minimum. The supplied Nov 6 image shows one 30-point glow, four closed chests, 30 points, and no aggregate Claim. A zero-ready native pass can complete without Claim; a claimed aggregate batch requires fresh five-static proof. Ready-chest successor proof remains `evidence_required`; runtime disabled. |
| `resource-item` | `resource_item` | One owned 1K Food item use per reset with exact decrement; runtime disabled and current native acceptance remains evidence_required. |
| `ruins` | `ruins_challenge` | Current zero-cost NPC challenge first, then independently claim each green-ready overview chest; unavailable challenge does not suppress ready chests and participation need not win. Runtime disabled; evidence_required; no current live acceptance. |
| `alliance-help` | `alliance_help` | Ten actual successful free Help requests per reset, not ten taps; preserve partial quota and use Help All only when its exact request count is known. Runtime disabled; evidence_required; no current live acceptance. |
| `alliance-donation` | `alliance_donation` | Up to ten confirmed ordinary-resource donations to the automatically selected Alliance Tech per reset; preserve partial progress and defer only on observed attempt/resource unavailability. Unknown effects block identical retry. Runtime disabled; evidence_required; no current live acceptance. |
| `alliance-shop` | `alliance_shop` | One currently affordable allowlisted Weekly Offer, or one exact Other one-star Gear fallback if no preferred offer is affordable; quantity one total. Require paired item/currency effects and canonical Home. Runtime disabled; evidence_required; no current live purchase acceptance. |
| `daily-shops` | `daily_shops` | One visit to Ruins Shop and Rare Earth Shop; one purchase action per exact three-star tab, capped by current stock and affordability. Preserve confirmed tabs and verify numeric quantity/total plus paired effects. Runtime disabled; evidence_required; no current live purchase acceptance. |
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

Run everything through `scripts/pnsctl.py`. This serves all routes from the table above:

```powershell
.\.venv\Scripts\python.exe scripts/pnsctl.py automation-service `
  --mode supervised --adapter bluestacks `
  --state-path .local-orchestrator/bot-state.sqlite3 serve --live `
  --flow nova --flow recruitment --flow campaign --flow bioenhancer `
  --flow supply --flow ultimate --flow enhancement --flow personal-might `
  --flow daily-rewards --flow resource-item --flow ruins --flow alliance-help `
  --flow alliance-donation --flow alliance-shop --flow daily-shops `
  --campaign-stage 1-15-9 --campaign-cadence-seconds 300 `
  --adb "C:\Program Files\BlueStacks_nxt\HD-Adb.exe" --serial emulator-5554 `
  --account-id primary-account --server-id primary-server `
  --output-directory .local-captures/automation-service-live
```

Account, server, device, state and output paths must match your local instance. The command
blocks and uses the persisted controls as they are; turn routes on first with `service-enable`
and `enable <flow-id>`, and check `automation-service status` before and after a session.

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
