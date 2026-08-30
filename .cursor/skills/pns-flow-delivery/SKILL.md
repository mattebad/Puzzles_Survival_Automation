---
name: pns-flow-delivery
description: Plan-execute-escalate development of Puzzles & Survival flows with bounded delegation.
disable-model-invocation: true
---

# Plan-execute-escalate PnS flow delivery

The architecture planner freezes the manifest. The Sol parent is the mandatory
`control_plane_owner` for Heavy work and retains stage freeze, product/failure
classification, integration acceptance, runtime ownership, evidence acceptance,
commits, queue transitions, and termination. Optional `procedure_coordinator`
assistance follows the frozen checklist and cannot own stage transitions or
architecture. New architecture, safety ambiguity, or contradictory evidence
goes to the escalation architect through a compact checkpoint packet.

## Development loop

1. Read `AGENTS.md`, the compact `CURRENT_HANDOFF.md`, the active queue item, and only the
   referenced task context.
2. Verify branch, working-tree ownership, queue state, registration posture, runtime ownership,
   unresolved-action state, and the current live-attempt budget.
3. Acquire or heartbeat the development lease with `scripts/flow_delivery_control.py`. The lease
   protects one active flow and one runtime operator; it does not choose a model or agent.
4. Apply the product-precondition gate before implementation or canary: diagnostic probes may
   begin at `evidence_required`, but implementation/review requires `proven` or `not_applicable`.
   Follow the frozen manifest and select its smallest coherent implementation slice. Optional
   procedural assistance may not edit outside its explicit checklist authority; the bounded Luna
   implementer edits only its assigned paths.
5. When delegation is useful, invoke the optional `pns-flow-implementer` once for that slice. Give
   it the parent-approved allowlist and exact deliverable. Immediately before invocation, reserve
   the writer lane with `begin-delegation`; after its terminal result, release the same ID with
   `end-delegation`. Keep it foreground and single-writer. Do not launch reconnaissance, review,
   or evidence agents merely because a correction is needed.
6. If the slice fails, the Sol parent classifies the defect and may authorize at most one
   consolidated repair and one Terra recheck for that stage. A product-precondition failure
   terminates the stage without worker iteration. A further repair requires a compact handoff and
   explicit user continuation under a refrozen stage. It may continue in the same chat while the
   conversation-level stage and turn budgets remain available; a new architecture decision
   requires escalation.
7. Run the focused tests for the active flow. Run architecture/full/governance validation only
   when the changed scope or task contract requires it.
8. Give the independent Terra code-and-acceptance reviewer a bounded read-only package when
   required by the selected route. Require material, actionable findings tied to the manifest or a
   plausible private/local-project impact; reject cosmetic, speculative, or perfection-oriented
   findings.
   Use `record-stage` as a lightweight task ledger; descriptive stages are not agent gates.
9. If live validation is required, the Sol parent alone uses `scripts/pnsctl.py`, one flow at a time,
   with current raw-frame binding, immediate-before revalidation, attempt accounting, and the
   unresolved-action gate.
10. Preserve the required source, transport, semantic-result, journal, and terminal evidence.
    Review evidence proportionally; do not create a separate reviewer invocation by default.
11. The Sol parent creates a focused commit only after tests, runtime state, evidence, and
    attribution are terminal. Complete the queue transition atomically, then record counted
    completion.

## Non-negotiable safety boundaries

- Never automate login, account selection, CAPTCHA, credentials, or other manual-only states.
- Never bypass `scripts/pnsctl.py` for production runtime input.
- Never issue live input from a child agent.
- Never overlap writable agents or runtime operators.
- Transport success is not semantic success.
- Ambiguous consequential results remain unresolved; do not blindly retry.
- Preserve registration-disabled and scheduler-disabled posture unless the active task explicitly
  authorizes promotion.
- Do not recursively inspect or modify protected evidence and reference trees.

## Parent conversation rollover

The checked-in `tasks/agentic_workflow_policy.json` is the source of managed
turn, stage, checkpoint, and parent-conversation limits. At a safe terminal
boundary, stop with `PARENT_CONVERSATION_ROLLOVER_REQUIRED` and use the
checked-in resume invocation. Do not begin another stage after rollover.
The checked-in `tasks/flow_delivery_loop_policy.json` separately defines the
counted-completion limit; do not hardcode a competing numeric maximum.
