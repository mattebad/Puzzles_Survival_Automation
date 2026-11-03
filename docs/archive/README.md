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

The current runtime architecture is documented by [the service guide](../automation-service.md)
and the canonical implementation under [`../../automation_service/`](../../automation_service/).
The [original simplification proposal](governance-simplification-plan.md) is preserved byte-for-byte
from its pre-archival working copy. Its counts, phases and verification list describe that proposal;
they are not current task state or additional runtime gates.

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

## Retired governance and route-status records

- [`retired-governance/`](retired-governance/) preserves the removed staged validator and its tests as non-executable text.
- [`campaign-route-status-before-cleanup-20261030.md`](campaign-route-status-before-cleanup-20261030.md) preserves the former Campaign run-status chronology.
- [`current-handoff-astra-premerge-20261102.md`](current-handoff-astra-premerge-20261102.md) is the former root `CURRENT_HANDOFF.md`, moved byte-for-byte when agent session state moved to [`../agent/`](../agent/). It describes the November 2 pre-merge session (PR #16, since merged); its relative links keep their original root context.

These records do not impose current handoff fields, CI gates, route authorization, or operator state.
