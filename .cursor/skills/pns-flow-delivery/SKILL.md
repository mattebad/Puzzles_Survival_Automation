---
name: pns-flow-delivery
description: Delivers Puzzles & Survival BlueStacks gameplay flows serially through the canonical development queue. Use when continuing the autonomous flow-delivery loop.
disable-model-invocation: true
---

# PnS serial flow delivery

The parent is the single GPT-5.6 Sol High orchestrator. It owns selection, architecture acceptance,
corrections, full-suite validation, BlueStacks input, evidence acceptance, commits, and queue
transitions.

## IDE-native delegation only

Use only the Cursor IDE native `Subagent`/`Task` tool exposed in this parent Agents Window
conversation. Set the custom subagent type exactly. Every invocation is foreground
(`is_background: false`), serial, visible in this parent conversation, and terminal before the parent continues.
Never use `/multitask`.

Do not invoke Cursor CLI, `cursor-agent`, `agent`, a terminal subprocess, Cursor SDK, ACP, MCP, a
slash command written as prose, or a detached parent as a delegation fallback.
Do not substitute a built-in subagent. Do not perform delegated reconnaissance, implementation,
review, or evidence review directly in the parent. If the native tool is absent, rejected, or
fails to return a terminal result, stop with `IDE_NATIVE_SUBAGENT_TOOL_UNAVAILABLE`.

Set the custom agent explicitly, request `cursor-grok-4.5-high` explicitly, and keep
`is_background: false`. After every terminal native Task result, immediately record exactly what
this parent observed with `record-subagent-invocation`, before advancing the delivery stage:

```text
python scripts/flow_delivery_control.py record-subagent-invocation \
  --owner <lease-owner> \
  --active-flow <active-flow> \
  --active-stage <active-stage> \
  --lease-session-id <current-session-id> \
  --parent-conversation-id <current-parent-conversation-id> \
  --custom-agent <exact-custom-agent> \
  --requested-model cursor-grok-4.5-high \
  --subagent-id <returned-subagent-id> \
  --is-background false \
  --terminal-outcome <completed|blocked|failed> \
  --timestamp <terminal-result-observed-at> \
  --repository-head <current-bound-head>
```

The controller never launches an agent. It atomically binds the receipt to the active lease, stage,
parent, flow, returned ID, requested model, foreground status, timestamp, and HEAD. A completed
receipt is mandatory before leaving any delegated stage.

The installed Cursor execution surface may not emit a project `subagentStart` event. The hook is
an optional additional defense: when a current hook event exists, the controller cross-checks every
reliable field it contains; when none exists, the native Task receipt is sufficient and the
optional mode is reported as `not_emitted`.

```text
A missing optional hook event does not authorize another execution surface.
It only disables the additional hook cross-check.
```

## Distinct authorities

- `tasks/flow_delivery_queue.json`: development-work selection only.
- `tasks/scheduler.py` and persisted task state: dormant gameplay execution scheduling; never use
  them to select development work.
- `.local-orchestrator/flow-delivery-lease.json`: one development orchestrator and its current
  runtime-ownership state.
- SafetyStore/journal leases: runtime action authority and unresolved-action gate; never mutate
  them through the development controller.
- Git status: working-tree ownership. Preserve unrelated and protected files.

## Start or resume

1. Read `AGENTS.md`, `CURRENT_HANDOFF.md`, the active queue entry and direct dependencies only.
2. Verify branch/HEAD/divergence, attributable tree ownership, current full-suite baseline,
   registration/scheduler posture, no runtime owner, no nonterminal consequential action, and
   `CONFIRMED_NOT_DISPATCHED`.
3. Run `python scripts/flow_delivery_control.py validate`.
4. Acquire the development lease with a stable parent/session identity, or heartbeat the lease
   already owned by this parent.
5. Run `status`. Continue the existing active flow; otherwise run `select-next` and `activate`.
   Never have two active flows. A blocked flow does not block an independent ready flow.

## Deliver one flow

Advance the closed stages with `record-stage`:

1. Enter `reconnaissance`, use the native `Subagent`/`Task` tool with custom subagent type exactly
   `pns-flow-recon`, wait for its terminal result, and record its native invocation receipt before
   advancing. Do not perform reconnaissance in the parent. Parent-review the returned
   implementation packet; do not create a separate readiness-review task.
2. In `implementation`, use the same native tool with custom subagent type exactly
   `pns-flow-implementer`. Invoke exactly one foreground writer and wait for its terminal result.
   Record its receipt before advancing. It may touch only the parent-approved allowlist. No
   worktree, live input, queue edit, or commit.
3. In `implementation_review`, parent-review first, then use the native tool with custom subagent
   type exactly `pns-flow-reviewer`; record its receipt before advancing. Pass `--parent-reviewed`
   only after parent acceptance.
4. In `correction`, give reproduced defects only to the same single-writer lane, record the
   implementer receipt, then repeat review. Do not perform speculative cleanup.
5. `focused_validation`: the parent runs focused tests and required architecture regressions.
6. `full_validation`: the parent runs the authoritative full suite and repository validators.
7. If live validation is required, claim runtime ownership in the development lease, recheck the
   authoritative journal/global unresolved gate, and run `live_preflight`. Enter `live_execution`
   only with every controller gate satisfied.
8. The parent alone invokes supported `scripts/pnsctl.py bluestacks ...` commands. Run one
   production flow at a time, obey `maximum_live_attempts`, and never bypass the operator interface.
9. Release runtime ownership after a terminal state. Use the native `Subagent`/`Task` tool with
   custom subagent type exactly `pns-evidence-reviewer` for the one generated session, wait for its
   terminal result, record its native invocation receipt, then parent-accept or block the evidence.
10. Reach `commit`, stage only attributable implementation, tests, evidence metadata, and the
    queue's `commit` stage, then create the conventional focused flow commit. Run `complete` with
    that commit SHA and create a narrow queue-transition commit containing only the terminal queue
    record and directly required handoff state. Verify the attributable tree is clean. Do not amend
    either commit and do not push.

## Continue safely

Only after the prior flow has terminal runtime state, reconciled evidence, required tests passing,
a focused commit, clean attributable ownership, and atomic queue completion may the parent select
the next ready flow. Release the development lease when stopping; otherwise heartbeat and continue
immediately. Never advance composition, Bliss migration, M6, production registration, or gameplay
scheduler eligibility through this loop.

Only these project subagents are permitted:

- `pns-flow-recon`
- `pns-flow-implementer`
- `pns-flow-reviewer`
- `pns-evidence-reviewer`

No subagent may spawn another subagent, no writable invocation may overlap, and only one visible
native subagent tool call may be active. If the native Task receipt does not prove the exact custom
agent, explicit Grok 4.5 High request, returned ID, foreground terminal result, current parent,
lease/stage/flow, and HEAD, stop the loop and fail closed. Never substitute the parent or another
execution surface because an optional hook event is missing.
