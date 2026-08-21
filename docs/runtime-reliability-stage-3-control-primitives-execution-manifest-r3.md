# Runtime Reliability Stage 3 control-primitives execution manifest r3

## Task ID and objective

- Task ID: `runtime-reliability-stage-3-control-primitives`
- Objective: Close the r1 transition-consumer evidence gap with a provenance-bound Enhancement replay, correcting only the r2 parent transcription error.

## Frozen stage control

- Host: `codex`
- Parent conversation ID: `01a02175-5bc3-7033-b401-621bb9041a4c`
- `control_plane_owner`: `sol_parent`
- Revision ID: `runtime-reliability-stage-3-control-primitives-r3`
- Stage type: `evidence_closure`
- Product precondition: `proven`
- Failure class: `core_contract` (r1 blocker); r2 terminated as `process_state` before mutation
- Stage start UTC: `2026-08-21T02:11:47.529Z`
- Continuation checkpoint UTC: `2026-08-21T02:08:11.674Z`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` / `architecture_planner` | `gpt-5.6-sol-medium` | Freeze, evidence acceptance, integration, classification, status, termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One mutable evidence/test turn within the exact allowlist |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only diff-and-acceptance review |
| `procedure_coordinator` / `escalation_architect` | `not used` | No authority |

## Immutable budgets

- This is the third and final frozen revision in the conversation.
- r1 used implementation, review, repair, and recheck; r2 used one fail-closed implementation turn with zero mutation; r3 permits one implementation and one review, reaching seven managed turns.
- No r3 repair is pre-authorized. Any must-fix finding terminates this conversation stage for user escalation rather than exceeding the managed-turn/convergence envelope.
- Zero live attempts and zero runtime inputs.

## Frozen architecture decision

- Preserve all r1 production code unchanged. Add only a minimal Enhancement evidence projection and executable replay test.
- The authoritative retained result is `.local-captures/development-sessions/ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION-20260818T212046050878Z/runtime/enhancement-family-20260818T212046414162Z/flow-delivery-result.json`, SHA-256 `bc36407fb2ede1d202d4b18ced544192c4fcb8125af3943e8364f1fb109dde0b`.
- The corrected authoritative retained event digest is `4a78a4a648f15ecd171b0ec2bbdc220d9659e982ecdfce0db37ae0648e7fc07b`.
- Preserve profile `pns-bluestacks-5-p64-800x1280-v1`, native 800×1280 geometry, immediate-post hash `1bd6a28ba8680f17ac4bfc13c8a32661389fcc92ab51f9357b9a0e3b2389bb92`, first-settled hash `434f4ebb55b8606824247a727229c79accddfb2f243d528328b253726eac6c5b`, and terminal-settled hash `f1814d91384522e0f2c67c1796d13a7838f5081ad2e016887b78b9b597bdf2ea`.
- SafetyStore, primitives, production adapters, runtime ownership, native-frame authority, Home Atlas, registration, and scheduling remain unchanged.

## Writable paths

Bounded implementer only:

- `tests/fixtures/runtime_control_sequences/manifest.json`
- `tests/fixtures/runtime_control_sequences/enhancement_transition.json`
- `tests/test_runtime_trace_projection.py`

Parent-only closure:

- `docs/runtime-reliability-stage-3-control-primitives-execution-manifest-r3.md`
- `docs/runtime-reliability-convergence-status.md`
- `CURRENT_HANDOFF.md`

No production path or other file is writable.

## Acceptance checks

- The new fixture is a truthful minimal projection of the named retained record and preserves its digest, profile, dimensions, provenance, and exact observation/frame hashes.
- The replay test independently validates fixture provenance and the protected source digest/relevant values when available, without production constants.
- Typed Enhancement immediate-post and settled observations pass through `tasks.transition_stability`, distinguish transient from stable, and report zero input.
- Enhancement becomes the second provenance-bound transition consumer alongside Nova; all other r1 cross-consumer coverage remains intact.
- All primitive/replay, affected-package, shared-navigation, and architecture checks pass. Production paths remain byte-for-byte unchanged from r1.

## Safety limits

- Allowed: targeted read-only access to the named retained files; edits only to the three implementer paths; offline tests.
- Disallowed: recursive evidence inspection, evidence fabrication/relabeling, production changes, runtime observation/input, emulator/ADB/BlueStacks/gameplay, registration/scheduling changes, commit, or push.

## Validation commands

- `python -m unittest tests.test_runtime_trace_projection`
- `python -m unittest tests.test_transition_stability tests.test_list_search tests.test_runtime_trace_projection`
- `python -m unittest tests.test_perception_bundle tests.test_navigation_development_boundary tests.test_vip_points_popup`
- `python scripts/run_flow_delivery_validation.py shared-navigation --flow-id DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- `python scripts/run_flow_delivery_validation.py architecture --flow-id DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- `git diff --check`

## Live budget

- Live admission: `not authorized`
- Input budget: `0`
- Iteration budget: `0`

## Escalation conditions

- Retained source/result/frame values contradict this corrected packet.
- Evidence closure requires production changes, runtime input, or fabricated proof.
- The independent tester finds a concrete must-fix defect.
- Any additional revision or repair is requested after this final conversation revision.
