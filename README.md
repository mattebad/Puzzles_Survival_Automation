# Puzzles & Survival runtime proof

This directory is the durable execution workspace for the runtime proof described by
`.cursor/plans/puzzles-survival-deterministic-service_3c9d7823.plan.md`.

- [`BACKLOG.md`](BACKLOG.md) is the only authoritative execution backlog.
- `evidence/manifest.csv` inventories retained artifacts by hash and dimensions.
- `evidence/sessions/` contains immutable experiment/session records.
- `scripts/collect-runtime-baseline.ps1` performs read-only baseline collection over SSH.

No gameplay automation is enabled or implemented here. Runtime experiments must preserve
the known-working SwiftShader configuration and must not automate login or tutorial flows.

