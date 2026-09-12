# Puzzles & Survival Automation

Safety-first computer-vision automation for **Puzzles & Survival**. The repository contains an
implemented `automation_service` kernel, retained BlueStacks development routes, and offline
planning records for future migration. No route is live-ready or enabled by this documentation.

## Current boundary

- **Development:** BlueStacks, under supervised local development only.
- **Final production target:** NAS/Unraid-hosted runtime with its selected Android-focused VM/profile.
- **Readiness:** The kernel is implemented, but route migration, current native acceptance, scheduler
  acceptance, and explicit enablement remain separate gates. A historical success or passing offline
  check does not claim live readiness.
- Runtime launchers and controls, `ResourceEffectAuthority`, leases/fencing, manual-only states,
  and live gates remain safety authorities. Planning documents cannot enable or authorize them.

The current 74-ticket plan starts at [`BACKLOG.md`](BACKLOG.md). Read the
[`offline execution guide`](docs/backlog/execution-guide.md) and the linked ticket body before any
future assignment. The original 148-record backlog is preserved in the
[`legacy archive`](docs/archive/backlog-legacy.md); it is historical and non-authorizing.

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

Neither the small offline check nor an offline unittest run is a full-suite or live BlueStacks/ADB
claim. Native/device operations are separate, supervised work and are not part of repository checks.
