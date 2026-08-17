# Flow-delivery routing and validation policy

This policy is the project-local companion to [`../AGENTS.md`](../AGENTS.md). It applies to
substantive live gameplay-flow development while preserving the runtime safety rules in
[`runtime-input-safety-policy.md`](runtime-input-safety-policy.md), singleton ownership in
[`chat-execution-ownership-policy.md`](chat-execution-ownership-policy.md), and the checked-in
flow queue contract.

## Route and review ownership

The route matrix and review ownership are authoritative in [`../AGENTS.md`](../AGENTS.md). An
explicit user route selection wins and remains active until changed; otherwise use the matrix
before entering this ladder. This document keeps the runnable validation mechanics and the stage
admission contract.

## Stage admission

The Sol parent is the mandatory `control_plane_owner` for Heavy work. Before
implementation, review, or canary, the parent records the frozen revision,
stage type, failure class, budgets, and product precondition. Diagnostic probes
may begin at `evidence_required`; implementation and review require `proven` or
`not_applicable`. A failed product precondition terminates the stage without
Luna/Terra iteration. Any live failure is classified as `product_state`,
`core_contract`, `local_defect`, or `process_state` before continuation is
considered.

Each stage permits one implementation, one initial review, at most one
consolidated repair and one recheck, and one live attempt. A parent conversation
permits at most three stage revisions and eight managed turns. The frozen
manifest is immutable between revision IDs and contains architecture and
budgets only; compact development-session and evidence records remain history.
`CURRENT_HANDOFF.md` is current truth and its latest modifying commit must be
the live Git head before managed delegation. This avoids an impossible
self-referential commit hash inside the tracked handoff while still rejecting a
handoff skipped by a later commit. At 60 minutes record a visible checkpoint;
at 90 minutes require a recorded user continuation later than the stage start.

## Compact validation ladder

Run the smallest rung that proves the current change, then advance once. Do not repeat a passed
rung merely for ceremony.

1. During repair, rerun the exact failing regression after the correction.
2. Run each affected package suite once.
3. Run the checked-in focused flow profile once before canary:
   `python scripts/run_flow_delivery_validation.py focused --flow-id FLOW-ID`.
4. If shared navigation changed, run the boundary profile once:
   `python scripts/run_flow_delivery_validation.py shared-navigation --flow-id FLOW-ID`.
5. Complete the one parent-owned integration gate after the executor self-check and tester package.
6. Perform a zero-input observation through the supported interface:
   `python scripts/pnsctl.py development-session observe`.
7. Execute the authorized live flow through its existing `pnsctl` development-session interface.
8. Verify the semantic result and retained evidence with the flow's checked-in verifier.
9. Full repository discovery is manual-only:
   `python scripts/run_flow_delivery_validation.py full --flow-id FLOW-ID --manual`.

The runner captures full subprocess logs and emits compact success/failure output plus a bound
receipt. Reuse it rather than adding another runner or suppressing test failures. This ladder does
not authorize registration, scheduler promotion, consequential actions, or unsupported payment
confirmation.
