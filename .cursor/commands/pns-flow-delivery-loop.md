Plan-execute-escalate PnS development loop.

1. Read `AGENTS.md`, `CURRENT_HANDOFF.md`, the active queue item, and its direct references.
2. Run:
   `python scripts/flow_delivery_control.py validate`
3. Check `status`, select or resume exactly one queue flow, and acquire/heartbeat the development
   lease. Confirm runtime ownership is clear before any live work.
4. Follow the frozen manifest. Have the execution coordinator implement directly only when the
   selected route permits parent ownership, or delegate one coherent slice to
   `pns-flow-implementer`. Wrap only that invocation with `begin-delegation` / `end-delegation`
   using one ID, so parent and child writes cannot overlap.
5. Run the active flow's focused tests and any route-required independent read-only tester package.
   Permit one consolidated repair in the execution chat. Further substantial repair requires a
   compact handoff and fresh chat; new architecture requires a compact escalation checkpoint.
6. Advance queue history with `record-stage` as needed. Descriptive stages are not agent gates.
7. For live validation, the parent alone runs the supported `scripts/pnsctl.py bluestacks` command.
   Maintain the runtime singleton, current-frame binding, immediate-before checks, attempt budget,
   evidence chain, and unresolved-action gate.
8. Perform one proportional integration decision, record validation receipts required by the task,
   commit only attributable files, complete the queue transition, and record counted completion.
9. Never activate registration, scheduler eligibility, composition, M6, or Bliss migration through
   this loop.

The controller policy in `tasks/flow_delivery_loop_policy.json` defines the parent-conversation
maximum. On a safe terminal boundary emit exactly `PARENT_CONVERSATION_ROLLOVER_REQUIRED` and use
the checked-in resume invocation:

/loop Load and follow `.cursor/commands/pns-flow-delivery-loop.md` exactly.

Do not hardcode a competing maximum.
