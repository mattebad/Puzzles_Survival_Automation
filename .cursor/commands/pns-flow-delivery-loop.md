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
   `record-subagent-invocation` before advancing.
6. Use bounded validation profiles only:
   - `python scripts/run_flow_delivery_validation.py focused --flow-id <flow>`
   - `python scripts/run_flow_delivery_validation.py architecture --flow-id <flow>`
   - `python scripts/run_flow_delivery_validation.py full --flow-id <flow>`
   - `python scripts/run_flow_delivery_validation.py governance --flow-id <flow>`
7. Continue the authoritative queue until a checked-in hard stop condition occurs.

The project `subagentStart` hook is an optional additional cross-check when this installed Cursor
execution surface emits it.

A missing optional hook event does not authorize another execution surface.
It only disables the additional hook cross-check.

Stop with `IDE_NATIVE_SUBAGENT_TOOL_UNAVAILABLE` rather than substituting the parent or another
delegation surface.

Do not activate composition, M6, Bliss migration, production registration, or gameplay scheduling.
