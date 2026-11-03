# Puzzles & Survival operator runbook

Local BlueStacks is the sole active gameplay runtime. Run supported operations
from the project root through `scripts/pnsctl.py`; do not use direct ADB or
remote-host commands for active development.

## Local BlueStacks operations

The canonical controls and operator bootstrap commands are:

```text
python scripts/pnsctl.py automation-service status
python scripts/pnsctl.py automation-service health
python scripts/pnsctl.py automation-service enable <flow-id>
python scripts/pnsctl.py automation-service disable <flow-id>
python scripts/pnsctl.py automation-service service-enable
python scripts/pnsctl.py automation-service service-disable
python scripts/pnsctl.py development-session launch-game --live --yes
```

Normal `launch-game` preserves an already running game. For an explicitly authorized cold-process
restart test, add `--cold-restart`. This requires clean Home, the existing canonical database,
disabled service/flow controls, no active service owner/run, a held runtime input lock and clear
Core actions. It attempts one stop, verifies process exit and the known launcher, then reuses
owner-bound startup. It never retries an uncertain stop/start and issues no gameplay inputs.
Its fresh captures and terminal result are retained in the development session directory.

The canonical automation-service live boundary is the existing `pnsctl` facade:

```text
python scripts/pnsctl.py automation-service --mode supervised --adapter bluestacks --state-path .local-orchestrator/bot-state.sqlite3 serve --live --flow campaign --campaign-stage 1-15-9 --campaign-cadence-seconds 300 --adb "C:\\Program Files\\BlueStacks_nxt\\HD-Adb.exe" --serial emulator-5554 --account-id primary-account --server-id primary-server --output-directory .local-captures/automation-service-live
```

Repeat `--flow` for other named routes when a bounded run needs them. Due eligibility determines
execution order; selected argument order does not. The facade validates the standard mode, adapter,
and state path before forwarding to the canonical service CLI and respects existing disabled gates.
It does not auto-enable registration, scheduling, or deployment. The public disabled-gates proof
produced zero captures and zero new runs, so it is control evidence only.

The supervised service is the gameplay scheduler. Bootstrap and older diagnostic commands are
separate operator interfaces with their existing guards. Local execution uses the fixed approved
serial, native800×1280 profile and exact game package, and retains structured evidence under
`.local-captures/`. No arbitrary coordinate/tap/ADB endpoint is added by these commands.

`bluestacks run-flow --live` is a retired legacy entry and fails closed before runtime
observation, flow-state loading, artifact creation, or route invocation. Supported live
work uses the canonical `automation-service ... serve --live` boundary for registered execution;
older `development-session run-flow` records are historical/diagnostic interfaces and remain
available only where their checked-in recovery contract requires them. The legacy `bluestacks
run-flow` command remains available only for its required offline/dry-run behavior and still fails
closed before live invocation.
`verify-flow` validates the session's result, frames, events, ledger, capability audit, journal,
runtime owner, and terminal state. `recover-home` delegates only to the existing
Cultivation-Center-to-Home verified recovery and cannot issue Android Back from an unrecognized
Home screen.

The implemented Daily Claim contract is one selected-Daily aggregate action. Current eight-route
acceptance does not establish aggregate Daily or milestone acceptance. The flow reuses the
existing Home → Quest → Daily route, positively recognizes one ordinary,
free, non-milestone Claim control, taps exactly once, and succeeds only when
Daily points increase and no ordinary Claim control remains. Objective flows
may prove completion but never own a Claim tap. There is no per-row loop,
objective binding, fixed point delta, or identical retry.

## Canonical governance references

This runbook is an operational entry point, not a duplicate authority. Permanent invariants are in
[`../AGENTS.md`](../AGENTS.md); detailed procedures are in:

- [`runtime-input-safety-policy.md`](runtime-input-safety-policy.md) for raw-frame recognition,
  coordinate translation, rebinding, input limits, and semantic postconditions;
- [`journal-lease-policy.md`](journal-lease-policy.md) for operational versus historical journals,
  lifecycle, leases, unresolved gates, and reconciliation;
- [`chat-execution-ownership-policy.md`](chat-execution-ownership-policy.md) for singleton
  ownership and safe handoffs;
- [`evidence-retention-policy.md`](evidence-retention-policy.md) for exact manifests, hashes,
  indexing exclusion, and archive-before-removal.

Current task status and the next planned action are recorded in `CURRENT_HANDOFF.md` and
`BACKLOG.md`. These documents and offline contracts do not grant runtime authority or enable
service/flow controls. Historical Bliss evidence and journals
remain immutable evidence, not active operating instructions.

Stop on an account/session hard stop, public ADB exposure, unresolved
consequential outcome, profile mismatch, or destructive runtime requirement.
