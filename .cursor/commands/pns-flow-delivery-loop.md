Plan-execute-escalate PnS development loop.

1. Read `AGENTS.md`, `CURRENT_HANDOFF.md`, the active queue item, and its direct references.
2. Run:
   `python scripts/flow_delivery_control.py validate`
3. Check `status`, select or resume exactly one queue flow, and acquire/heartbeat the development
   lease. Confirm runtime ownership is clear before any live work.
4. The Sol parent/control-plane owner freezes the stage and product precondition.
   Follow that manifest; optional `procedure_coordinator` assistance is only
   checklist work. Delegate one coherent slice to `pns-flow-implementer` when
   the frozen stage authorizes it, using `begin-delegation` / `end-delegation`
   so parent and child writes cannot overlap.
5. Run the active flow's focused tests and the route-required independent Terra
   read-only review. Per stage allow one implementation, one review, at most
   one consolidated repair and one recheck. A product-precondition failure
   terminates the stage without worker iteration.
6. Advance queue history with `record-stage` as needed. Descriptive stages are not agent gates.
7. For live validation, the parent alone runs the supported `scripts/pnsctl.py bluestacks` command.
   Maintain the runtime singleton, current-frame binding, immediate-before checks, attempt budget,
   evidence chain, and unresolved-action gate.
8. The Sol parent performs one proportional integration decision, records
   validation receipts required by the task, commits only attributable files,
   completes the queue transition, and records counted completion.
9. Never activate registration, scheduler eligibility, composition, M6, or Bliss migration through
   this loop.

The checked-in `tasks/agentic_workflow_policy.json` defines the managed-turn,
stage, checkpoint, and parent-conversation limits. The checked-in
`tasks/flow_delivery_loop_policy.json` defines the counted-completion limit.
On a safe terminal boundary emit exactly `PARENT_CONVERSATION_ROLLOVER_REQUIRED`
and use the checked-in resume invocation:

/loop Load and follow `.cursor/commands/pns-flow-delivery-loop.md` exactly.

Do not hardcode a competing maximum.
