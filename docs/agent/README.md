# Agent and session records

This directory holds volatile agent-workflow and session material, kept apart from the
user and maintainer documentation in [`../`](../) and the [README](../../README.md).
Nothing here enables a route, grants live authority, or overrides the runtime controls.

- [`CURRENT_HANDOFF.md`](CURRENT_HANDOFF.md): short session handoff for whoever picks up
  work next. It changes often and is not a status report. `scripts/pnsctl.py` hashes it
  (with `BACKLOG.md` and `tasks/flow_delivery_queue.json`) to detect edits during a live
  development session, so do not edit it while a live session is running.
- [`prompts/daily-quest/`](prompts/daily-quest/): legacy per-task implementation prompts.
  `tasks/daily_quest_execution_matrix.json` and the prompt `index.json` point at these paths,
  and `tests/test_daily_quest_planning.py` checks that every indexed prompt exists.
- [`execution-manifest-template.md`](execution-manifest-template.md) and
  [`flow-attempt-ledger-template.md`](flow-attempt-ledger-template.md): optional note formats.

Agent conventions live in [`AGENTS.md`](../../AGENTS.md). Retired session snapshots live under
[`../archive/`](../archive/).
