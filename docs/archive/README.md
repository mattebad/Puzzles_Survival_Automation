# Historical design archive

Files in this directory are retained for architectural history only. They are not current runtime
authority and may refer to development artifacts that have since been retired from the working tree.
Those artifacts remain recoverable through Git history.

[`backlog-legacy.md`](backlog-legacy.md) is the byte-preserved historical backlog used only by legacy
queue, context, and governance readers that explicitly address this archive path. It is not a mirror
of the current [`../../BACKLOG.md`](../../BACKLOG.md), cannot activate a current ticket, and never
authorizes planning, scheduling, runtime, transport, or evidence changes.

Paths inside byte-preserved records retain their original repository-root context; they were not
rewritten during archival. Use the current backlog and architecture links for active instructions.

The current runtime direction is documented by [`../../governance-simplification-plan.md`](../../governance-simplification-plan.md)
and the canonical implementation under [`../../automation_service/`](../../automation_service/).

## Archived model-specific records

The archived execution manifests, validation manifests, convergence status, flow-specific
manifests, and agent progress notes were moved from `docs/` and `agent_docs/` without rewriting their bodies. They are
historical evidence only, are not current instructions, and cannot select a route, participant,
model, operator, review, runtime action, or retry:

- [`execution-manifests/`](execution-manifests/) — superseded frozen execution records.
- [`validation/`](validation/) — superseded validation records.
- [`agent-latest-session-work.md`](agent-latest-session-work.md) and [`agent-project-progress.md`](agent-project-progress.md) — superseded tracked `agent_docs/` notes.
- Root-level historical manifests and status records — retained for provenance only.

References inside these files retain their original path context to preserve historical meaning.
Use current `AGENTS.md`, the current flow contracts, and the supported runtime controls for active
work.
