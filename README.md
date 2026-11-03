# Puzzles & Survival Automation

Safety-first computer-vision automation for **Puzzles & Survival**. The repository contains an
implemented `automation_service` kernel, eight explicitly authorized BlueStacks routes, and
offline planning records for future migration. Current route acceptance and remaining coverage
are recorded in the [dated route report](docs/bluestacks-route-status-20261031.md) and
[`BACKLOG.md`](BACKLOG.md); current runtime ownership is in
[`CURRENT_HANDOFF.md`](CURRENT_HANDOFF.md). Documentation never enables a route.

## Current boundary

- **Current runtime:** Local BlueStacks, using explicitly authorized supervised service sessions.
  Selected routes run serially when their persisted daily or cooldown gates permit them.
- **Runtime:** BlueStacks is the runtime; there is no NAS/Unraid production target.
- **Readiness:** All eight routes have retained BlueStacks effect/Home evidence, with dated source
  limits in the backlog. The October 30 source completed a two-hour serial cadence. The latest
  October 31 source passed 20 minutes with 8 reports, 22 inputs, verified Home returns and disabled cleanup. Later cold
  process restart and an actual pre-native UTC-reset deferral are live-accepted. Enhancement's
  Gear, Chip and Module proof covers one physical Profile visit with an interrupted/resumed run;
  a fully uninterrupted native family remains additional coverage. Historical receipts do not
  accept later changed code.
- Runtime launchers and controls, `ResourceEffectAuthority`, leases/fencing, manual-only states,
  and live gates remain safety authorities. Planning documents cannot enable or authorize them.

Current route evidence and the reconciled 74-ticket plan start at [`BACKLOG.md`](BACKLOG.md). Read the
[`offline execution guide`](docs/backlog/execution-guide.md) and the linked ticket body before any
future assignment. The original 148-record backlog is preserved in the
[`legacy archive`](docs/archive/backlog-legacy.md); it is historical and non-authorizing.

## Running the BlueStacks routes

Use the supported `pnsctl` facade and the existing service/flow controls. The service checks due
times, claims one route, verifies its outcome and return Home, then waits for the next eligible
route. Campaign drains every affordable battle before its five-minute completion wait.
Enhancement visits Profile once for Gear, Chip, and Module, then returns Home.

After the Python setup below, this is the service command for all eight routes:

```powershell
.\.venv\Scripts\python.exe scripts/pnsctl.py automation-service `
  --mode supervised --adapter bluestacks `
  --state-path .local-orchestrator/bot-state.sqlite3 serve --live `
  --flow nova --flow recruitment --flow campaign --flow bioenhancer `
  --flow supply --flow ultimate --flow enhancement --flow personal-might `
  --campaign-stage 1-15-9 --campaign-cadence-seconds 300 `
  --adb "C:\Program Files\BlueStacks_nxt\HD-Adb.exe" --serial emulator-5554 `
  --account-id primary-account --server-id primary-server `
  --output-directory .local-captures/automation-service-live
```

Account, server, device, state and output paths must match the intended local instance. This
command preserves persisted service/flow enablement and blocks; it does not turn them on.
Use `automation-service status` to inspect those controls, and the explicit `enable <flow_id>`,
`disable <flow_id>`, `service-enable`, and `service-disable` commands to manage an authorized
session; `emergency-stop` is the global stop. The full command reference and safety notes are in the
[`operations runbook`](docs/pns-operations-runbook.md). Do not start another controller while a live owner exists. Static code registration is separate from enablement; persisted service/flow controls are off
after bounded tests, and permanent deployment remains unchanged. See [`the service guide`](docs/automation-service.md)
for the control and execution boundaries.

## Target architecture and safety contract

Perception must establish a current, typed source and target before any input capability exists.
Every dispatch must be fenced by fresh-frame identity, stable semantic target binding, ownership,
resource/policy checks, and the persisted SQLite gates. A transport return is not success: the
postcondition must be positively recognized. Stale, ambiguous, unknown, contradictory, or
unreconciled outcomes must fail closed and must not be blindly retried.

```text
Current frame
    │
    ▼
Perception: screen + overlay + target + provenance
    │  (no input until this is valid)
    ▼
SQLite state / scheduler → fenced runtime session → ActionExecutor → transport
    ▲                                                        │
    └──────────── fail-closed postcondition/reconciliation ──┘
```

The canonical runtime lives in [`automation_service/`](automation_service/). Legacy route code in
[`scripts/`](scripts/) and [`tasks/`](tasks/) remains under its existing safety boundaries while
migration is evaluated. [`safe_action_core/`](safe_action_core/) and especially
`ResourceEffectAuthority` remain retained authorities until equivalent canonical safeguards are
proved. [`evidence/`](evidence/) records what happened; it never authorizes execution or retry.

## Repository map

- [`automation_service/`](automation_service/) — SQLite state, scheduler, sessions, fencing, action
  execution, screen routing, and recovery.
- [`scripts/`](scripts/) — supervised BlueStacks development and maintenance tooling.
- [`tasks/`](tasks/) — route semantics, recognition, policy, and retained task machinery.
- [`safe_action_core/`](safe_action_core/) — retained action/resource safety authorities.
- [`tools/`](tools/) — manual or experimental developer tooling, not production runtime authority.
- [`tests/`](tests/) — offline, replay, policy, route, and safety checks.
- [`docs/backlog/`](docs/backlog/) — 74 inactive recovery tickets; planning only.
- [`docs/archive/`](docs/archive/) — superseded design/status material and the byte-preserved legacy
  backlog. Archive documents are not current instructions.
- [`evidence/`](evidence/) — immutable development/evidence records, not runtime authority.

## Development setup

Use Python **3.11 or newer** in a virtual environment. On Windows, the Python Launcher avoids
accidentally using an older `python` installation; no activation script is required:

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

With that environment activated, the deterministic offline check is the same command used by CI:

```bash
python scripts/check.py
```

Relevant broader unittest modules may be run separately when working on a subsystem, for example:

```bash
python -m unittest tests.test_automation_service_state
```

The broader `tests.test_world_map_navigation_bluestacks` fixture replay requires a local
`tesseract` executable on `PATH` (CI installs it). Its checked-in World HUD and Search-menu
PNGs are authorized byte-exact copies of retained captures, not fresh native acceptance.

Tests that can only run against gitignored, machine-local captures (`.local-captures/`) are
marked with `tests.support.local_captures.requires_local_captures`. They are reported as explicit
opt-in skips (`opt-in: set PNS_LOCAL_CAPTURES=1 ...`) and are not part of any CI claim. On a
machine that holds the captures, run them with `PNS_LOCAL_CAPTURES=1`; a missing capture then
fails the test instead of skipping it. Shared test fakes and loaders live in `tests/support/`;
test modules do not import each other.

New native-runtime capture files use portable filename components; original semantic labels
remain in structured events. `actions.jsonl` records each canonical action once, including
failed or unresolved attempts. `transport_attempted_count` counts actual dispatch attempts;
`semantic_completed_count` requires a confirmed semantic outcome, not successful transport
or a retained screenshot. Historical evidence paths are not rewritten, and none of these
records enables a flow or authorizes retry.

Neither the small offline check nor an offline unittest run is a full-suite or live BlueStacks/ADB
claim. Native/device operations are separate, supervised work and are not part of repository checks.
