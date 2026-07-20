---
name: pns-flow-delivery
description: Delivers Puzzles & Survival BlueStacks gameplay flows serially through the canonical development queue. Use when continuing the autonomous flow-delivery loop.
disable-model-invocation: true
---

# PnS serial flow delivery

The parent is the single GPT-5.6 Sol High orchestrator. It owns selection, architecture acceptance,
corrections, full-suite validation, BlueStacks input, evidence acceptance, commits, and queue
transitions.

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

1. `selected` → `reconnaissance`: invoke only `/pns-flow-recon` and parent-review its bounded
   implementation packet. Do not create a separate readiness-review task.
2. `implementation`: invoke exactly one `/pns-flow-implementer`. It is the only writable subagent
   and may touch only the parent-approved allowlist. No worktree, live input, queue edit, or commit.
3. `implementation_review`: parent-review first, then invoke only `/pns-flow-reviewer`. Pass
   `--parent-reviewed` only after parent acceptance.
4. `correction`: give reproduced defects only to the same single-writer lane, then repeat review.
   Do not perform speculative cleanup.
5. `focused_validation`: the parent runs focused tests and required architecture regressions.
6. `full_validation`: the parent runs the authoritative full suite and repository validators.
7. If live validation is required, claim runtime ownership in the development lease, recheck the
   authoritative journal/global unresolved gate, and run `live_preflight`. Enter `live_execution`
   only with every controller gate satisfied.
8. The parent alone invokes supported `scripts/pnsctl.py bluestacks ...` commands. Run one
   production flow at a time, obey `maximum_live_attempts`, and never bypass the operator interface.
9. Release runtime ownership after a terminal state. Invoke only `/pns-evidence-reviewer` for the
   one generated session, then parent-accept or block the evidence.
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

No subagent may spawn another subagent. If model-routing metadata does not prove Grok 4.5 High,
stop the loop and fail closed.
