IDE-NATIVE EXECUTION ONLY.
Do not invoke Cursor CLI, cursor-agent, agent, SDK, ACP, or a detached parent.
All custom subagents must be launched through the native Subagent/Task tool in this conversation.

Load and follow `.cursor/skills/pns-flow-delivery/SKILL.md` as the canonical detailed lifecycle.

## Bootstrap

1. Verify repository, queue, development lease, runtime ownership, unresolved-action, registration,
   and scheduler state.
2. Run `python scripts/flow_delivery_control.py validate`.
3. Continue an existing active flow or select exactly one ready flow.
4. Before every native subagent invocation:
   - `python scripts/flow_delivery_context.py build --flow-id <flow> --stage <stage> --reuse-if-current`
   - `python scripts/flow_delivery_context.py validate --packet <packet-path>`
   - pass only packet path, active flow ID, active stage, and exact requested deliverable
5. Keep every custom subagent foreground and serial. Set the exact custom agent, request
   `cursor-grok-4.5-high` explicitly, wait for its terminal result, and immediately run
   `record-subagent-invocation` before advancing. Never say "use an exploration/general-purpose
   agent" or "choose the best agent"; use only the checked-in stage-to-agent mapping.
6. Use bounded validation profiles only:
   - `python scripts/run_flow_delivery_validation.py focused --flow-id <flow>`
   - `python scripts/run_flow_delivery_validation.py architecture --flow-id <flow>`
   - `python scripts/run_flow_delivery_validation.py full --flow-id <flow>`
   - `python scripts/run_flow_delivery_validation.py governance --flow-id <flow>`
7. Continue the authoritative queue until a checked-in hard stop condition occurs.

## Parent-conversation rollover hard stop

The controller loop policy in `tasks/flow_delivery_loop_policy.json` is the sole authoritative
maximum for completed gameplay-delivery flows in one parent conversation. Count only verified
completed gameplay-delivery queue flows. Do not begin another flow after that maximum is reached.
Enforce rollover only at a safe terminal boundary. Emit exactly
`PARENT_CONVERSATION_ROLLOVER_REQUIRED` and the compact resume command below. A new parent identity
starts at completed-flow count zero. A valid current full-suite receipt may be reused at rollover
when the controller accepts it.

```text
/loop Load and follow `.cursor/commands/pns-flow-delivery-loop.md` exactly.
Continue the authoritative queue until a checked-in hard stop condition occurs.
IDE-native custom subagents only; no CLI fallback.
```

`preToolUse(Task)` is the fail-closed authorization gate before child creation. `subagentStart` is
audit-only for resolved-identity correlation and is not a reliable deny boundary. When preToolUse
denies a Task: do not fall back to built-in agents, Sol, or Cursor CLI; stop blocked unless one
explicit corrected project-owned mapping exists.

```text
A missing optional subagentStart audit event does not authorize another execution surface.
It only disables the additional resolved-identity cross-check.
```

Stop with `IDE_NATIVE_SUBAGENT_TOOL_UNAVAILABLE` rather than substituting the parent or another
delegation surface.

Do not activate composition, M6, Bliss migration, production registration, or gameplay scheduling.
