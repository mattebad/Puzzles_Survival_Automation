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
`is_background: false`. Never use generic language such as "use an exploration agent",
"launch an appropriate subagent", "use a general-purpose agent", or "choose the best agent".
The routing decision must be the exact checked-in stage-to-agent mapping plus the approved model.

After every terminal native Task result, immediately record exactly what
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

`preToolUse(Task)` is the fail-closed authorization gate that must allow a Task call before a child
is created. When it denies a request: do not fall back to a built-in agent, Sol, or Cursor CLI;
record the denial; issue one corrected approved request only when an explicit project-owned mapping
exists; otherwise stop blocked.

`subagentStart` is audit-only. It records the resolved child and correlates requested-versus-resolved
identity with the earlier preToolUse authorization event. It is not a reliable mechanism to prevent
child creation.

```text
A missing optional subagentStart audit event does not authorize another execution surface.
It only disables the additional resolved-identity cross-check.
```

## Distinct authorities

- `tasks/flow_delivery_queue.json`: development-work selection only.
- `tasks/flow_delivery_loop_policy.json`: sole authoritative maximum for completed gameplay-delivery
  flows counted per parent conversation; command/skill refer to it semantically and must not
  hardcode a competing numeric maximum.
- `tasks/backlog_task_index.json` and `scripts/flow_delivery_context.py`: compact backlog indexing
  and bounded stage context packets only; packets never grant runtime or product authorization.
- `tasks/scheduler.py` and persisted task state: dormant gameplay execution scheduling; never use
  them to select development work.
- `.local-orchestrator/flow-delivery-lease.json`: one development orchestrator and its current
  runtime-ownership state. Lease mirrors may report the current parent counter but are not the
  progress authority.
- `.local-orchestrator/parent-conversation-progress.json`: local ignored completed-gameplay-flow
  progress scoped to `bound_parent_conversation_id`; grants no gameplay authorization.
- SafetyStore/journal leases: runtime action authority and unresolved-action gate; never mutate
  them through the development controller.
- Git status: working-tree ownership. Preserve unrelated and protected files.

## Context packets before delegation

Use `required_overhead_for(consequence_class, stage)` from
`scripts/flow_delivery_control.py` to decide whether a stage context packet is
required. Navigation-only discovery stages defer context packets, dependency
section digests, strict evidence manifests, and replay-capsule promotion to
stabilization or consequential promotion. Automatic runner evidence
(source/immediate-post frames, intended target/input, events, terminal result,
unresolved proof) remains mandatory on the navigation-development boundary and
is never deferred by this rule.

When overhead includes `context_packet`, before every native subagent invocation:

1. Build or reuse the active stage packet:
   `python scripts/flow_delivery_context.py build --flow-id <flow> --stage <stage> --reuse-if-current`
2. Validate the packet:
   `python scripts/flow_delivery_context.py validate --packet <packet-path>`
3. Pass only packet path, active flow ID, active stage, and exact requested deliverable.
   Do not paste the entire packet into the Task prompt when the subagent can read the packet path.

When overhead omits `context_packet`, pass only active flow ID, active stage, and
exact requested deliverable. Do not invent a substitute packet.

## Bounded validation

Use checked-in profiles only via `scripts/run_flow_delivery_validation.py`
(`focused`, `architecture`, `full`, `governance`). Complete logs remain under
`.local-orchestrator/logs/`; console output stays compact.

## Start or resume

1. Read `AGENTS.md`, compact `CURRENT_HANDOFF.md`, and the active stage context packet when
   `required_overhead_for` includes `context_packet` for that stage.
2. Verify branch/HEAD/divergence, attributable tree ownership, current full-suite baseline,
   registration/scheduler posture, no runtime owner, no nonterminal consequential action, and
   `CONFIRMED_NOT_DISPATCHED`.
3. Run `python scripts/flow_delivery_control.py validate`.
4. Acquire the development lease with a stable parent/session identity, or heartbeat the lease
   already owned by this parent.
5. Run `status`. Continue the existing active flow; otherwise run `select-next` and `activate`.
   Never have two active flows. A blocked flow does not block an independent ready flow.

## Deliver one flow

Advance the closed stages with `record-stage`. Build/validate a stage context packet only when
`required_overhead_for` includes `context_packet` for the active consequence class and stage
(navigation-only discovery defers packets; consequential subagent stages still require them):

1. Enter `reconnaissance`, apply the context-packet rule above, use the native `Subagent`/`Task`
   tool with custom subagent type exactly `pns-flow-recon`, wait for its terminal result, and
   record its native invocation receipt before advancing. Do not perform reconnaissance in the
   parent. Parent-review the returned implementation packet; do not create a separate
   readiness-review task.
2. In `implementation`, apply the context-packet rule, then use the same native tool with custom
   subagent type exactly `pns-flow-implementer`. Invoke exactly one foreground writer and wait for
   its terminal result. Record its receipt before advancing. It may touch only the parent-approved
   allowlist. No worktree, live input, queue edit, or commit.
3. In `implementation_review`, parent-review first, apply the context-packet rule, then use the
   native tool with custom subagent type exactly `pns-flow-reviewer`; record its receipt before
   advancing. Pass `--parent-reviewed` only after parent acceptance.
4. In `correction`, give reproduced defects only to the same single-writer lane, record the
   implementer receipt, then repeat review. Do not perform speculative cleanup.
5. `focused_validation`: the parent runs
   `python scripts/run_flow_delivery_validation.py focused --flow-id <flow>` and, for
   consequential flows, `architecture --flow-id <flow>`. Navigation-only flows use the
   proportionate focused profile only.
6. `full_validation`: the parent runs the proportionate profile via
   `python scripts/run_flow_delivery_validation.py` — `shared-navigation --flow-id <flow>` for
   navigation-only flows, or `full --flow-id <flow>` (which produces the required `full_suite`
   receipt) for consequential flows — plus repository validators as required by
   `required_receipts_for`. The `promotion` profile is reserved for promotion and does not satisfy
   the consequential full_validation receipt.
7. If live validation is required, claim runtime ownership in the development lease, recheck the
   authoritative journal/global unresolved gate, and run `live_preflight`. Enter `live_execution`
   only with every controller gate satisfied.
8. The parent alone invokes supported `scripts/pnsctl.py bluestacks ...` commands. Run one
   production flow at a time, obey `maximum_live_attempts`, and never bypass the operator interface.
9. Release runtime ownership after a terminal state. Apply the context-packet rule for
   `evidence_review`, use the native `Subagent`/`Task` tool with custom subagent type exactly
   `pns-evidence-reviewer` for the one generated session, wait for its terminal result, record
   its native invocation receipt, then parent-accept or block the evidence. Keep automatic
   runner evidence; do not require replay-capsule promotion for navigation-only discovery.
10. Reach `commit`, stage only attributable implementation, tests, evidence metadata, and the
    queue's `commit` stage, then create the conventional focused flow commit. Run `complete` with
    that commit SHA and create a narrow queue-transition commit containing only the terminal queue
    record and directly required handoff state. Verify the attributable tree is clean. Do not amend
    either commit and do not push.

## Continue safely

Only after the prior flow has terminal runtime state, reconciled evidence, required tests passing,
a focused commit, clean attributable ownership, and atomic queue completion may the parent select
the next ready flow. After the queue-transition commit, record the counted gameplay completion with
`record-counted-completion` using the current parent conversation identity. Count only completed
gameplay-delivery queue flows. When the controller policy maximum is reached, stop only at a safe
terminal boundary, emit `PARENT_CONVERSATION_ROLLOVER_REQUIRED`, release the development lease, and
print the compact resume command. Do not begin another flow after the maximum is reached. A new
parent identity starts at zero. Reuse a valid current full-suite receipt at rollover when the
controller accepts it; do not rerun the same full suite merely because rollover occurs. Release the
development lease when stopping; otherwise heartbeat and continue immediately. Never advance
composition, Bliss migration, M6, production registration, or gameplay scheduler eligibility
through this loop.

Checked-in hard stop conditions include:

- `IDE_NATIVE_SUBAGENT_TOOL_UNAVAILABLE`
- `PARENT_CONVERSATION_ROLLOVER_REQUIRED`

At a valid rollover boundary, emit that stop reason and print the exact compact resume invocation
from the checked-in flow-delivery loop command. Do not invent a different resume text.

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
