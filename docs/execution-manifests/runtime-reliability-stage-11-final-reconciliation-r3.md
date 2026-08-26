# Stage 11 final reconciliation r3

## Control
- Task: `stage-11-final-reconciliation-r3`.
- Supersedes r2 without altering history. Final refreeze reason: repository governance validation reached the checked-in flow-delivery loop policy and proved that its command and skill omit the required policy-source reference.
- Parent: `gpt-5.6-sol`; Solo implementation/integration route continues.
- Entry HEAD: `a753e3fc3664d45afe7eadc2b592a5270c445c38`; existing r2-scoped work is retained.
- Stage revision budget: 3 of 3; no further refreeze is authorized.

## Additional frozen repair
1. Preserve `tasks/flow_delivery_loop_policy.json` unchanged as the numeric source of truth.
2. Add a non-competing reference to `tasks/flow_delivery_loop_policy.json` in `.cursor/commands/pns-flow-delivery-loop.md` and `.cursor/skills/pns-flow-delivery/SKILL.md`.
3. Preserve `PARENT_CONVERSATION_ROLLOVER_REQUIRED`, the separate agentic policy reference, and all existing safety boundaries.
4. Do not hardcode a numeric maximum.

## Writable paths
- All r2 writable paths.
- `.cursor/commands/pns-flow-delivery-loop.md`.
- `.cursor/skills/pns-flow-delivery/SKILL.md`.
- This r3 manifest.

## Acceptance
- `validate_flow_delivery_loop_policy` passes for command, skill, ignored progress path, and policy schema.
- All r2 acceptance remains unchanged.
- Runtime sessions, gameplay inputs, registrations, scheduler selections, protected-evidence mutations, and identical retries remain zero.
