IDE-NATIVE EXECUTION ONLY.
Do not invoke Cursor CLI, cursor-agent, agent, SDK, ACP, or a detached parent.
All custom subagents must be launched through the native Subagent/Task tool in this conversation.

Load and follow `.cursor/skills/pns-flow-delivery/SKILL.md`.

Verify repository, queue, development lease, runtime ownership, unresolved-action, registration,
and scheduler state before selection. Continue an existing active flow or select exactly one ready
flow. Keep every custom subagent foreground and serial. Set the exact custom agent, request
`cursor-grok-4.5-high` explicitly, wait for its terminal result, and immediately run the
lease-bound `record-subagent-invocation` controller command with the returned subagent ID,
`is_background=false`, current parent/session, stage, flow, timestamp, and repository HEAD before
advancing the stage.

The project `subagentStart` hook is an optional additional cross-check when this installed Cursor
execution surface emits it.

A missing optional hook event does not authorize another execution surface.
It only disables the additional hook cross-check.

Stop with
`IDE_NATIVE_SUBAGENT_TOOL_UNAVAILABLE` rather than substituting the parent or another delegation
surface.

Do not activate composition, M6, Bliss migration, production registration, or gameplay scheduling.
