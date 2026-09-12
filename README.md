# Puzzles & Survival Automation

Safety-first computer-vision automation for **Puzzles & Survival**. The repository contains proven BlueStacks gameplay routes and is currently migrating them onto a canonical SQLite-backed scheduler/runtime architecture.

> **Current readiness:** the canonical runtime foundation is implemented, but legacy gameplay routes are still being migrated. Gameplay flows are disabled by default, and no gameplay flow should yet be treated as unattended scheduler-ready.

## Architecture direction

The target execution path is deliberately narrow:

```text
BotStateManager (SQLite authority)
        ↓
Scheduler
        ↓
RuntimeSession
        ↓
ActionExecutor
        ↓
ScreenRouter / OverlayRecoveryManager
        ↓
BlueStacks transport
```

The canonical authority lives in [`automation_service/`](automation_service/). The migration rules and consolidation plan are documented in [`governance-simplification-plan.md`](governance-simplification-plan.md).

## Repository map

- [`automation_service/`](automation_service/) — canonical state, scheduling, runtime ownership, action fencing, screen routing, and overlay recovery.
- [`scripts/`](scripts/) — current BlueStacks gameplay/development implementations while routes are migrated to the canonical runtime.
- [`tasks/`](tasks/) — product semantics, offline controllers, recognition, policy, and legacy task state that will be reduced as canonical migration proceeds.
- [`safe_action_core/`](safe_action_core/) — older safety/action machinery retained where canonical parity has not yet been demonstrated, especially resource-effect safety.
- [`tests/`](tests/) — canonical, route, replay, policy, and safety regression tests.
- [`evidence/`](evidence/) — retained native experiment/evidence records. Historical evidence is diagnostic and must not authorize runtime execution.
- [`tools/`](tools/) — manual or experimental developer tooling that is not part of production runtime authority.
- [`docs/`](docs/) — current operational/reliability documentation; [`docs/archive/`](docs/archive/) contains superseded historical design material.

## Safety model

The project is intentionally fail-closed. Core invariants include:

- flows initialize disabled unless explicitly enabled;
- runtime ownership and action state are durable in SQLite;
- current-frame recognition and target rebinding are required before transport;
- stale or ambiguous targets block rather than guess;
- only one canonical active run may own execution at a time;
- an action is durably marked dispatching before transport;
- uncertain post-transport outcomes become `UNKNOWN` and are not blindly retried;
- premium, resource-affecting, or strategic consequences require explicit route policy and positive reconciliation.

## Current migration state

The canonical bot-state authority and core scheduler/runtime primitives are implemented. Several gameplay routes already have supervised native evidence in the legacy BlueStacks runtime, but they are not yet scheduler-ready through the canonical path.

The next migration sequence is intentionally serial:

1. make the canonical route host fail-honest and executable;
2. migrate ordinary Daily Claim as the first complete canonical gameplay flow;
3. prove restart-safe scheduler recurrence for Daily Claim;
4. migrate low-risk Daily objectives and routine maintenance one flow at a time;
5. retire each legacy live authority as its canonical replacement reaches parity.

## Development and tests

Install the automation-service requirements as needed:

```bash
python -m pip install -r requirements-automation-service.txt
```

Useful offline entry points include:

```bash
python -m automation_service.cli --help
python scripts/pnsctl.py --help
python -m unittest discover -s tests
```

Many tests use retained frames, fake adapters, replay adapters, or temporary SQLite databases. Live BlueStacks/ADB execution is a separate supervised development activity and should not be inferred from a passing offline suite.

## Evidence and historical material

Retained evidence records are immutable development artifacts, not runtime authority. Superseded architecture plans are kept under [`docs/archive/`](docs/archive/) when they remain useful for historical context; Git history is the source for retired binaries, screenshots, and experimental utilities removed from the active tree.
