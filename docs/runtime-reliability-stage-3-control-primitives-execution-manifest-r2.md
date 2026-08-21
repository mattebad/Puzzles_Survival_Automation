# Runtime Reliability Stage 3 control-primitives execution manifest r2

## Task ID and objective

- Task ID: `runtime-reliability-stage-3-control-primitives`
- Objective: Close the sole r1 integration blocker by adding a second provenance-bound transition-stability replay consumer from retained Enhancement evidence, without changing production code or runtime authority.

## Frozen stage control

- Host: `codex`
- Parent conversation ID: `01a02175-5bc3-7033-b401-621bb9041a4c`
- `control_plane_owner`: `sol_parent`
- Revision ID: `runtime-reliability-stage-3-control-primitives-r2`
- Stage type: `evidence_closure`
- Product precondition: `proven` (targeted retained Enhancement result binds native 800×1280 BlueStacks profile, source/successor observations, and exact frame hashes)
- Failure class: `core_contract`
- Stage start UTC: `2026-08-21T02:09:18.483Z`
- Continuation checkpoint UTC: `2026-08-21T02:08:11.674Z` (explicit user continuation in the active parent conversation)

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` / `architecture_planner` | `gpt-5.6-sol-medium` | Stage freeze, evidence acceptance, integration, classification, status, and termination |
| `procedure_coordinator` | `not used` | No authority |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One mutable evidence/test implementation turn within the assigned paths only |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only diff-and-acceptance review; reports findings only |
| `escalation_architect` | `not used unless an escalation condition occurs` | Genuine architecture/evidence conflicts only |

## Immutable budgets

- r2: one implementation, one review, at most one consolidated repair and one recheck, zero live attempts.
- Parent conversation: r2 is the second of at most three frozen revisions; r1 used four managed turns, leaving four under the eight-turn cap.
- Explicit user continuation was recorded after the r1 start and before r2 freeze.

## Frozen architecture decision

- Decision: Preserve the accepted r1 production implementation unchanged. Add only a minimal, independently annotated Enhancement replay excerpt and executable test coverage that verifies its retained source-record digest, BlueStacks profile, native dimensions, observation hashes, and transient-to-stable semantics before passing typed observations to the pure transition primitive.
- Preserved invariants: all r1 architecture and safety invariants; production adapters, primitives, SafetyStore, runtime ownership, Home Atlas, registration, and scheduling remain unchanged. Local retained evidence is read-only and is not copied or relabeled as newly captured proof.

## Writable paths

Bounded implementer:

- `tests/fixtures/runtime_control_sequences/manifest.json`
- `tests/fixtures/runtime_control_sequences/enhancement_transition.json`
- `tests/test_runtime_trace_projection.py`

Parent-only stage control and closure:

- `docs/runtime-reliability-stage-3-control-primitives-execution-manifest-r2.md`
- `docs/runtime-reliability-convergence-status.md`
- `CURRENT_HANDOFF.md`

No production file and no path outside this allowlist may be mutated.

## Acceptance checks

- The Enhancement fixture is a truthful minimal projection of the retained source record at `.local-captures/development-sessions/ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION-20260818T212046050878Z/runtime/enhancement-family-20260818T212046414162Z/flow-delivery-result.json`, SHA-256 `bc36407fb2ede1d202d4b18ced544192c4fcb8125af3943e8364f1fb109dde0b`.
- Fixture annotations independently retain `pns-bluestacks-5-p64-800x1280-v1`, 800×1280 native geometry, provenance paths, and exact immediate-before/immediate-post/settled frame hashes from the retained record.
- An executable replay test validates the fixture and, when the protected retained record is present, validates its digest and relevant values against the fixture without deriving expectations from production constants.
- Enhancement replay passes typed transient and stable observations through `tasks.transition_stability` with zero input, making Enhancement the second distinct provenance-bound transition consumer alongside Nova.
- All r1 primitive/replay and affected-package tests remain passing; the trace mixed-action fix remains intact.
- Production code, production adapters, registration, scheduling, and runtime ownership remain unchanged; zero emulator/ADB/BlueStacks/gameplay input occurs.

## Safety limits

- Allowed actions: targeted read-only access to the named retained Enhancement result/frames; fixture/test edits in the allowlist; offline deterministic validation.
- Disallowed actions: recursive evidence inspection, fabricated/relabelled proof, production edits, runtime observation or input, emulator/ADB/BlueStacks/gameplay, registration, scheduler changes, commit, or push.
- Runtime/session limits: no runtime session; singleton unowned; input and consequential-action budgets are zero.

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

## Evidence/history references

- r1 manifest and candidate: `docs/runtime-reliability-stage-3-control-primitives-execution-manifest-r1.md`
- r1 independent recheck: mixed-action trace resolved; transition consumer minimum unresolved.
- Retained Enhancement result digest: `bc36407fb2ede1d202d4b18ced544192c4fcb8125af3943e8364f1fb109dde0b`.
- Retained Enhancement event digest: `4a78a4a648f15ecd171b0ec2bddc220d9659e982ecdfce0db37ae0648e7fc07b`.
- Settling hashes: immediate post `1bd6a28ba8680f17ac4bfc13c8a32661389fcc92ab51f9357b9a0e3b2389bb92`; first settled `434f4ebb55b8606824247a727229c79accddfb2f243d528328b253726eac6c5b`; terminal settled `f1814d91384522e0f2c67c1796d13a7838f5081ad2e016887b78b9b597bdf2ea`.

## Escalation conditions

- The named retained result or frame hashes contradict the frozen evidence packet.
- A second transition consumer cannot be proven without production changes, flow-specific shared-module semantics, runtime input, or fabricated evidence.
- Safety or evidence authority becomes ambiguous.
- Tester and implementation evidence conflict.
- A repair fails or convergence stalls; no repeated local patch is authorized.
