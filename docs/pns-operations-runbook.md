# Puzzles & Survival operator runbook

Local BlueStacks is the sole active gameplay runtime. Run supported operations
from the project root through `scripts/pnsctl.py`; do not use direct ADB or
remote-host commands for active development.

## Local BlueStacks operations

The active command families are:

```text
python scripts/pnsctl.py bluestacks preflight
python scripts/pnsctl.py development-session run-flow <flow-id> --live --yes
python scripts/pnsctl.py bluestacks run-flow <flow-id>  # offline/dry-run only
python scripts/pnsctl.py bluestacks verify-flow <session-directory>
python scripts/pnsctl.py bluestacks recover-home
python scripts/pnsctl.py development-session observe
python scripts/pnsctl.py development-session daily-row-claim --mode prepare ...
python scripts/pnsctl.py development-session daily-row-claim --mode canary ...
```

These commands are development interfaces, not the gameplay scheduler. They
fix the private serial to `emulator-5554`, require native 800×1280 and package
`com.global.ztmslg`, use checked-in flow IDs and bounded receipt manifests,
and retain structured evidence under `.local-captures/`. No arbitrary ADB,
coordinate, tap, or swipe endpoint is exposed.

`bluestacks run-flow --live` is a retired legacy entry and fails closed before runtime
observation, flow-state loading, artifact creation, or route invocation. Supported live
work uses `development-session run-flow`, whose outer `DevelopmentSession` owns startup
recovery and route execution. The legacy `bluestacks run-flow` command remains available
only for its required offline/dry-run behavior and still fails closed until the active flow
supplies its dedicated checked-in runner.
`verify-flow` validates the session's result, frames, events, ledger, capability audit, journal,
runtime owner, and terminal state. `recover-home` delegates only to the existing
Cultivation-Center-to-Home verified recovery and cannot issue Android Back from an unrecognized
Home screen.

Daily Claim is one selected-Daily aggregate action. The flow reuses the
existing Home → Quest → Daily route, positively recognizes one ordinary,
free, non-milestone Claim control, taps exactly once, and succeeds only when
Daily points increase and no ordinary Claim control remains. Objective flows
may prove completion but never own a Claim tap. There is no per-row loop,
objective binding, fixed point delta, or identical retry.

## Future Bliss porting toolbox

Reusable remote infrastructure is isolated under `scripts/bliss_porting/` and
`docker/bliss-porting-tooling.Dockerfile`. It is manual-only and is not
imported, registered, scheduled, or exposed by `pnsctl`.

Only an explicitly selected future Bliss porting task may invoke:

```text
python -m scripts.bliss_porting.cli --help
```

The toolbox requires explicit host, host key, serial, container, image,
workspace, evidence path, private loopback ADB socket, ADB binary, Plink, and
PSCP arguments. Temporary credentials remain process-only. It contains no
gameplay flow identities or fixed gameplay coordinates, and it publishes no
ADB port.

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

The current task and exact next action are authoritative only in
`CURRENT_HANDOFF.md` and `BACKLOG.md`. Offline contracts do not authorize
registration or scheduler eligibility. Historical Bliss evidence and journals
remain immutable evidence, not active operating instructions.

Stop on an account/session hard stop, public ADB exposure, unresolved
consequential outcome, profile mismatch, or destructive runtime requirement.
