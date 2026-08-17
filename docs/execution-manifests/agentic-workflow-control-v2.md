# Agentic workflow control v2 execution manifest

## Task ID and objective
- Task ID: `agentic-workflow-control-v2`
- Objective: replace the unbounded Heavy-task repair conveyor with Sol-owned stage control, bounded Luna/Terra turns, product-precondition classification, honest handoff state, and deterministic subagent admission.
- Revision ID: `agentic-workflow-control-v2-r1`
- Frozen repository candidate: `main@99c152ded8119f2eaa82058813bb4f7f2aacc813`
- Frozen UTC: `2026-08-17T01:43:42.933Z`

## Execution routing
- `control_plane_owner`: current Sol parent
- `procedure_coordinator`: not used
- `bounded_implementer`: one GPT-5.6 Luna XHigh turn
- `independent_tester`: one Terra High read-only review, plus at most one recheck after one consolidated repair
- Runtime access: prohibited

## Frozen architecture decision
- Sol owns stage definition, product-precondition classification, integration acceptance, live admission, escalation, and termination.
- A Luna procedure coordinator is optional and cannot own stage transitions or architecture.
- Each frozen stage permits one implementation, one review, at most one consolidated repair and recheck, and one live attempt.
- A parent conversation permits at most three stages and eight managed subagent turns. Sixty minutes requires a visible checkpoint; ninety minutes blocks further managed delegation or live admission without an explicit user continuation checkpoint.
- Every live failure is classified as `product_state`, `core_contract`, `local_defect`, or `process_state` before another worker is considered.
- Frozen manifests contain architecture and budgets only. Existing compact runtime records remain the append-only execution history. `CURRENT_HANDOFF.md` contains only current truth, and its latest modifying commit must be the live Git head before managed delegation.
- Deterministic project-level `subagentStart` admission enforces the current Git/handoff binding, Sol control ownership, prompt stage metadata, model assignment, per-stage turn limits, conversation cap, and the ninety-minute checkpoint. Unmanaged general-purpose agents remain unaffected.

## Writable paths
- `AGENTS.md`
- `.cursor/rules/pns-model-routing.mdc`
- `.cursor/commands/pns-flow-delivery-loop.md`
- `.cursor/skills/pns-flow-delivery/SKILL.md`
- `.cursor/hooks.json`
- `.cursor/hooks/pns_agent_workflow_guard.py`
- `tasks/agentic_workflow_policy.json`
- `docs/execution-manifest-template.md`
- `docs/flow-delivery-validation-policy.md`
- `docs/execution-manifests/daily-row-claim-r2.md`
- `CURRENT_HANDOFF.md`
- `tests/test_flow_delivery_orchestrator.py`

## Acceptance checks
- Heavy live work names a Sol `control_plane_owner`; `execution_coordinator` is optional procedural support rather than an unassigned authority gap.
- The stage contract requires revision, stage type, product precondition, failure class, budgets, and immutable-between-freezes behavior.
- Product-precondition failure terminates the stage without Luna/Terra iteration.
- The hook allows a correctly bound first implementation/review, rejects stale handoff Git state, missing/mismatched stage metadata, wrong model, duplicate turn kinds, exceeded stage/conversation budgets, and expired checkpoints.
- The current handoff records `99c152d` as the last product-code candidate, binds itself to the current commit, records the consumed scan receipt, forbids repeating it, and classifies the absence of an accepted ready row as `product_state`.
- The active Daily manifest becomes a compact `r2` contract while preserving the original mixed-format manifest as historical evidence.

## Validation
- `python -m unittest tests.test_flow_delivery_orchestrator`
- `python -m py_compile .cursor/hooks/pns_agent_workflow_guard.py`
- `git diff --check`
- No gameplay, ADB, BlueStacks, Bliss, receipt issuance, queue, registration, scheduler, composition, or M6 action.

## Stop and escalation
- Stop after the first accepted implementation and review.
- Permit at most one parent-classified consolidated repair and one Terra recheck.
- Escalate rather than weakening deterministic admission or runtime safety.
