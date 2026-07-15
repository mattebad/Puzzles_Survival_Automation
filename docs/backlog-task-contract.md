# Backlog task contract

This is the canonical schema for newly created or activated backlog tasks. It is a contract
specification, not an execution prompt.

## Required contract

Each adopted task must contain these labeled fields in its `BACKLOG.md` section:

### Identity

`Task ID`, `Title`, `Status`, `Milestone`, `Dependencies`, and `Blocked by`.

### Objective and facts

`Objective` must name one atomic outcome. `Established facts` records proven facts that should not
be broadly re-proven.

### Scope

`Direct implementation files`, `Shared dependencies`, `Transitive regression set`, `Allowed
changes`, and `Prohibited changes`.

### Live authorization

`Authorized runtime action`, `Maximum transport inputs`, `Navigation-only recovery`,
`Consequential action`, `Registration changes`, `Scheduler changes`, and `Actions that must not be
repeated`.

Use explicit `none`, `forbidden`, or numeric zero values where a task has no live authority.

### Recognition and semantics

`Required source`, `Exact target semantics`, `Required local association`, `Negative controls`,
`Coordinate space`, `Accepted signals`, `Rejected weak signals`, and `Ambiguous-result behavior`.

### Product resource policy

`Zero-cost requirement`, `Quantity limits`, `Resource consumption policy`, and `Premium or strategic
restrictions`.

### Evidence and verification

`Active evidence manifest`, `Required artifacts`, `Immediate-before/immediate-post/result/journal`,
`Additional task-specific artifacts`, `Focused tests`, `Integration tests`, `Transitive regression
tests`, `Full-suite requirement`, `Validators`, and `Known baseline failures`.

### Outcomes and commits

`Valid blocked outcomes`, `Blocked-result commit policy`, `Expected focused commits`, per-commit
`allowed paths`, `Completion criteria`, and `No push unless explicitly authorized`.

## Activation and migration

The validator hard-fails the task named by `current_task_id` in the structured
`CURRENT_HANDOFF.md`, `GOV-DURABLE-STATE`, newly created tasks, and legacy tasks modified after
governance adoption.

Untouched legacy nonterminal tasks receive warnings only. Completed historical tasks have no
migration requirement. A warning becomes a hard failure when the task is modified or activated.

A legacy task becomes active only after:

1. its backlog section satisfies this contract;
2. its dependencies and authorization are validated;
3. `CURRENT_HANDOFF.md` is updated in a separate persisted transition to move the task from
   `next_task_id` to `current_task_id`.

`next_task_id` is a declared successor, not an active task, and does not trigger immediate contract
migration.

## Commit ownership

Every task names the exact path allowlist for each expected commit. If one file spans concerns,
reviewed hunk-level staging is required. If hunk staging would create an unclear dependency
boundary, collapse the commits. Never duplicate changes, create artificial commits, or stage a
whole shared file merely because one hunk belongs to the active commit.
