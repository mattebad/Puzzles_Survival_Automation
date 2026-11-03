# Puzzles & Survival operator runbook

Local BlueStacks is the sole active gameplay runtime. Run supported operations
from the project root through `scripts/pnsctl.py`; do not use direct ADB or
remote-host commands for active development.

## Safety controls

These commands change or report only the canonical SQLite service state (default
`.local-orchestrator/bot-state.sqlite3`; override with `--state-path`). They are offline: through
`pnsctl` they pass no `--adapter`, so the canonical CLI default (`AUTOMATION_SERVICE_ADAPTER`, else
`fake`) applies and no device input is issued. Persisted service and flow gates
default off and `serve` never turns them on.

- **`emergency-stop`** is the global stop. It disables the service gate, records the reason
  (`--reason`, default `emergency stop`) and time, increments the service generation, and marks
  every `CLAIMED`/`RUNNING`/`RECOVERING` run `STOP_REQUESTED`. A running `serve` re-checks the gate and
  its claimed generations at its fence checkpoints, so it stops at the next fence. It does
  not kill the process, touch the device, or clear per-flow gates. Use it when the live run must stop
  now; recovery after it is explicit `service-enable` plus `enable <flow-id>` by the operator.
- **`service-disable`** is the same gate change with `--reason` (default `service disabled`);
  **`service-enable`** re-opens the global gate. **`disable <flow-id>`** / **`enable <flow-id>`**
  gate one flow. Each increments a generation counter, which fences in-flight runs.
- **`status`** prints the service and per-flow gates and generations; **`health`** prints the health
  report and exits non-zero when it is unhealthy. Check `status` before and after any live session.
- Both gates must be on for any claim. Do not start a second controller while a live owner exists.

```text
python scripts/pnsctl.py automation-service status
python scripts/pnsctl.py automation-service health
python scripts/pnsctl.py automation-service emergency-stop --reason "<why>"
python scripts/pnsctl.py automation-service service-disable --reason "<why>"
python scripts/pnsctl.py automation-service service-enable
python scripts/pnsctl.py automation-service enable <flow-id>
python scripts/pnsctl.py automation-service disable <flow-id>
```

## Live service boundary

The only supported route executor is the canonical `serve` facade. Every route, including Nova and Recruitment, runs as `serve --flow <route>`; `pnsctl` has no per-route runner commands.

```text
python scripts/pnsctl.py automation-service --mode supervised --adapter bluestacks --state-path .local-orchestrator/bot-state.sqlite3 serve --live --flow campaign --campaign-stage 1-15-9 --campaign-cadence-seconds 300 --adb "C:\\Program Files\\BlueStacks_nxt\\HD-Adb.exe" --serial emulator-5554 --account-id primary-account --server-id primary-server --output-directory .local-captures/automation-service-live
```

Repeat `--flow` for other named routes when a bounded run needs them. Due eligibility determines
execution order; selected argument order does not. The facade validates the standard mode, adapter,
and state path before forwarding to the canonical service CLI and respects existing disabled gates.
It does not auto-enable registration, scheduling, or deployment. The public disabled-gates proof
produced zero captures and zero new runs, so it is control evidence only. Local execution uses the
fixed approved serial, native 800×1280 profile and exact game package, and retains structured
evidence under `.local-captures/`. No arbitrary coordinate/tap/ADB endpoint is added by these
commands.

## Command reference

"Operator" commands are part of the supported workflow. "Dev-only" commands remain for development,
retained-evidence work and recovery; they are not an operating path and need explicit current
authorization when they touch the device. Run `python scripts/pnsctl.py <group> --help` for the
exact set; `tests/test_catalog_and_pnsctl.py` fails if the parser and this table drift apart.

| Command | Purpose | Safety notes | Use |
| --- | --- | --- | --- |
| `automation-service serve` | Run the supervised scheduler for the selected `--flow` routes | Requires `--mode supervised --adapter bluestacks --live`, `--serial`, `--account-id`, `--server-id`; both persisted gates must be on; `--mode`, `--adapter`, `--state-path` go before `serve` | Operator (live) |
| `automation-service status`, `health` | Report gates/generations and health | Read-only for gates; no device | Operator |
| `automation-service enable`, `disable <flow-id>` | Gate one flow | Fenced SQLite transition; no device | Operator |
| `automation-service service-enable`, `service-disable` | Gate the whole service | Fenced; `service-disable` also stops in-flight runs | Operator |
| `automation-service emergency-stop` | Global stop (see Safety controls) | Fenced; does not clear flow gates | Operator |
| `automation-service run <flow-id>` | Claim one flow occurrence | Through `pnsctl` the mode is `disabled`/`observe_only`/`dry_run` and the adapter is the non-device CLI default (`fake`): without `--live` it only reports the candidate; `--live` needs both gates and still has zero transport | Operator (rehearsal) |
| `automation-service pulse` | One offline UTC scheduler pulse | `dry_run`, no runtime or transport; initializes flow rows in the state DB | Operator (rehearsal) |
| `development-session launch-game` | Start the game from the BlueStacks launcher | Requires `--live --yes` and the runtime input lock; `--cold-restart` is described below; issues no gameplay input | Operator (live) |
| `development-session observe` | Capture and recognize the current screen | Zero gameplay input; owns the runtime lock while running | Operator |
| `bluestacks preflight` | Check ADB state, 800×1280 frame and foreground package | Read-only (`dispatch: false`); needs a valid flow-delivery queue and lease with runtime ownership held (`_load_flow_delivery_state`), otherwise it fails closed | Operator |
| `bluestacks verify-flow <session-dir>` | Verify a retained session's result, frames, events, ledger, capability audit, journal, runtime owner and terminal state | Offline, reads retained files only | Operator |
| `bluestacks recover-home` | Verified Cultivation-Center-to-Home recovery | Issues input (Back/Home) only through the existing recovery handler; cannot Back from an unrecognized Home screen; needs a live-stage queue/lease or the retained Troop Training recovery candidate | Operator (live) |
| `reconcile` | Offline reconciliation of one unresolved action | Edits a **copy** (`--output`) of a retained SafetyStore database (`--source` is never modified), only if the action is `unresolved`; records `--outcome` (`proven_no_effect` or `positive_postcondition`) with `--evidence` and an audit row. It does not touch the live state DB and cannot clear a blocked running service | Operator (offline) |
| `development-session run-flow <flow-id>` | Run one registered flow in a development session | Development and recovery only; `--live` needs `--yes`; ordinary Campaign execution is refused (use `serve --flow campaign`); several routes need a consumed registration or a delegated receipt | Dev-only |
| `development-session daily-row-reconnaissance`, `daily-row-claim`, `delegated-dry-run` | Daily row reconnaissance/claim and receipt validation | Require a delegated receipt bound to agent, task, flow, scenario, variant and `--max-inputs`; `delegated-dry-run` has no runtime access | Dev-only |
| `bluestacks reconcile-campaign-atlas-survey-action` | Reconcile one unresolved Campaign atlas survey action | Offline, zero input, retained frames only; session must be under the Campaign atlas artifact root | Dev-only |

Normal `launch-game` preserves an already running game. For an explicitly authorized cold-process
restart test, add `--cold-restart`. This requires clean Home, the existing canonical database,
disabled service/flow controls, no active service owner/run, a held runtime input lock and clear
Core actions. It attempts one stop, verifies process exit and the known launcher, then reuses
owner-bound startup. It never retries an uncertain stop/start and issues no gameplay inputs.
Its fresh captures and terminal result are retained in the development session directory.

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
