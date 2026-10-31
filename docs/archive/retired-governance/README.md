# Retired governance tooling

These files preserve the former staged execution-contract validator and its tests
as text. They are historical source, are not executable entrypoints, and do not
govern current runtime admission or the compact current handoff.

The old validator required delivery stages, successor tasks, manifests, Git
bindings and operator/agent personas in `CURRENT_HANDOFF.md`. Those requirements
belonged to the retired development workflow. Canonical runtime controls remain
in `automation_service`, `safe_action_core` and the supported `pnsctl` facade.

The active CI callers and handoff-shape assertions were removed with the validator.
Snapshot-export, secret-protection, queue compatibility and runtime safety tests
remain active in their existing modules.

The unused single-battle Campaign production-replay helper and its gate test are
also retained here as text. They asserted one 20-AP battle from 120 to 100 AP;
the current full-drain contract correctly rejects that stopping point. Exact
pre-change and current source produced the same failure. The retirement receipt
is `.local-orchestrator/logs/campaign-obsolete-single-battle-gate-retirement-20261031.json`.
Current native full-drain, resource, cadence, reset, and frame-recognition tests
remain active. These archived sources grant no execution authority.

