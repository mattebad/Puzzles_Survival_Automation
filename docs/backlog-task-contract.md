# Backlog planning conventions

This document describes the compact format for the 74 current recovery tickets. It is a planning
convention, not an execution prompt, queue, registry, scheduler, evidence authority, or runtime
control plane. Offline work does not require a runtime state change, delivery receipt, or queue
activation. Live runtime changes still require explicit authorization and existing safety checks.

## Required planning information

Every linked ticket should make these facts easy to find:

- **Identity:** stable `Task ID`, title, type, priority, and status.
- **Outcome:** one atomic objective, established facts, dependencies, and related historical work.
- **Scope:** exact implementation and test paths, shared dependencies, intended changes, and clear
  non-goals. A proposed new path is marked `NEW`.
- **Acceptance:** observable success and fail-closed boundaries, including unknown/stale,
  crash/restart, disable, duplicate/no-retry, cost/resource, and ownership behavior where relevant.
- **Verification:** real repository commands or a precise offline decision/operations proof. A
  prescribed command is not a claim that it has run.
- **Native gate:** whether later supervised current evidence is required. Development BlueStacks
  evidence and replay fixtures do not become NAS/Unraid production acceptance by reference.
- **Integration owner:** the callers, registry/schema/service/CLI seams that must change in the same
  PR. A mention is not permission to leave wiring for later.
- **PR boundary:** one focused change set with exact allowed paths, rollback/disable behavior, and
  no push unless separately authorized.
- **Runtime authorization:** normally `none` for these records. State explicitly when a later gate
  is required; a planning record never grants transport, host/device/ADB/VM access, scheduler
  enablement, registration, evidence mutation, or production state mutation.
- **Completion:** distinguish offline code merge, current native evidence, scheduler acceptance, and
  explicit enablement. Do not call the latter three complete because code or tests pass.

The recommended ticket labels are `Task ID`, `Type`, `Priority`, `Status`, `Objective`,
`Dependencies`, `Related work`, `Evidence`, `Scope`, `Changes`, `Non-goals`, `Acceptance`,
`Verification`, `Native gate`, `Integration owner`, `PR boundary`, `Rollback`, `Runtime
authorization`, and `Completion`. Their order is for readability, not positional parsing.

## Status and authority boundaries

`READY` means that a later offline assignment may be considered after dependencies, decisions, path
locks, and an approved base are checked. `WAITING_DEPENDENCIES`, `BLOCKED_POLICY`, and
`BLOCKED_NATIVE` remain explicit blockers. None of these labels starts work or changes runtime
eligibility. Keep `code_merged`, `native_pending`, `scheduler_accepted`, and `enabled` distinct.

The canonical mutable runtime authorities remain the existing SQLite state manager, service lease,
flow/run generations, action reservations, `ResourceEffectAuthority` where parity is not yet proven,
and the current runtime gates. Do not create a queue, second registry, conductor, receipt, evidence-
based enablement, or legacy fallback. Unknown or unresolved consequential outcomes are retained for
reconciliation or blocked and are never automatically retried.

The root [`BACKLOG.md`](../BACKLOG.md) is only an index to the linked records. The historical
148-record backlog is preserved byte-for-byte at
[`docs/archive/backlog-legacy.md`](archive/backlog-legacy.md). Existing legacy tooling may read that
explicit archive path; the archive is historical and cannot activate a current ticket. The derived
`tasks/backlog_task_index.json` remains a compatibility subset for legacy flow-delivery context, not
discovery for the 74 records.

## Future assignment boundary

A later, separately authorized assignment may use one ticket, one worktree, and one focused PR (or a
documentary/operational record where the ticket says so). Workers edit only the ticket's allowed
paths and use fake/replay adapters or isolated temporary state for offline proof. No assignment from
this document creates a branch, worktree, commit, PR, native run, or persistent state transition.

Shared source, test, and integration hunks are serialized by their actual overlap. The integration
owner completes required caller and cutover changes in the same PR; “wire later” is not completion.
No workflow persona, exact stage count, or conversational ceremony is part of this contract.
