# Runtime Reliability Stage 7 Ultimate product-record execution manifest r1

## Task ID and objective

- Task ID: `ultimate-terminal-product-record-migration-r1`
- Flow ID: `ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION`
- Objective: migrate only Ultimate Challenge to current typed, revision-bound
  product authority and truthful retained-proof status without changing its
  controller, selectors, runtime behavior, registration, scheduling, or
  continuous-session terminal-reconciliation adapter.

## Frozen stage control

- Host: `codex`
- `control_plane_owner`: `sol_parent`
- Revision ID: `ultimate-terminal-product-record-migration-r1`
- Stage type: `product_authority_shared_binding_and_retained_proof_correction`
- Product precondition: `missing_typed_ultimate_product_record_and_unbound_stale_contract`
- Failure class: `core_contract`
- Stage start UTC: `2026-08-22T05:05:39.5484810Z`
- User authorization: explicit continuation through remaining Stage 7 flows,
  executed serially as atomic lanes.

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` / `architecture_planner` | `gpt-5.6-sol-medium` | Freeze, architecture, integration acceptance, closure, termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One mutable implementation turn within the exact allowlist |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only diff-and-acceptance review |
| `procedure_coordinator` / `escalation_architect` | `not used` | No authority |

## Frozen architecture decision

- Add one typed direct-action `ultimate_challenge` product record: once per
  verified reset, distinct from Campaign AP and selected Daily, zero resource
  cost, one positively bound Challenge/lineup/Exit/Flee sequence, no Auto
  Battle, no identical/repeated Flee, and canonical Home required separately
  from semantic Flee completion.
- Retained attempt 13 in checked-in queue provenance proves exactly one Flee and
  zero resource delta. Retained attempt 14 proves measured Ultimate-main to
  Campaign to canonical Home navigation with zero new Flee. They are immutable
  composite proof, not one uninterrupted continuous session. Flee must never be
  repeated merely to relabel topology.
- Correct only stale contract proof statements that claim no native Flee
  sequence exists. Preserve the distinction between verified semantic Flee and
  separately assembled terminal Home; uninterrupted terminal reconciliation
  remains `evidence_required` for the later adapter lane.
- Ultimate retains null Daily owner/point trigger and
  `selected_daily_prerequisite: false`; it is a Main/direct flow, not a selected-
  Daily route and not a Campaign AP destination.
- Bump global authority revision/digest and mechanically rebind the five current
  Resource, Enhancement, Supply, Daily Claim, and Nova contracts without
  changing their record revisions, record digests, product semantics, routes,
  evidence, or proof status.
- Bind Ultimate contract to its own record revision/digest and current native
  BlueStacks identifiers.
- Do not modify selectors, navigation, runtime behavior, `pnsctl`, adapters,
  registration, scheduling, evidence files, or execute any runtime input.

## Exact writable allowlist

Implementation:

- `tasks/product_authority.py`
- `tasks/flow_delivery_product_policy.json`
- `tasks/gameplay_flow_contracts/ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/SUPPLY-DEPOT-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE.json`
- `tasks/daily_quest_catalog.json` only if required to preserve explicit Main/
  non-Daily ownership; it must not admit Ultimate as selected Daily
- `tests/test_product_authority.py`
- `tests/test_gameplay_flow_contracts.py`
- `tests/test_catalog_and_pnsctl.py` only if catalog ownership changes

Parent-only control and closure:

- `docs/runtime-reliability-stage-7-ultimate-product-record-execution-manifest-r1.md`
- `CURRENT_HANDOFF.md`
- `docs/runtime-reliability-convergence-status.md`
- `.cursor/plans/p&s_runtime_reliability_convergence_program_e62703e1.plan.md`

All controllers, selectors, adapters, session/conductor code, registration,
scheduler, queues, receipts, evidence, and unrelated contracts are read-only.

## Acceptance checks

- Authority contains exactly the prior five records plus `ultimate_challenge`.
- Ultimate record types direct Main ownership, once/reset identity, zero cost,
  exact Flee ceiling one, semantic Flee/terminal Home separation, no retry, and
  immutable user/native provenance.
- Ultimate is rejected as Campaign AP and selected-Daily ownership.
- Ultimate contract binds exact current authority and record digests plus the
  current BlueStacks profile/package/Home authorities.
- Contract truthfully preserves retained attempt 13 Flee proof and attempt 14
  terminal recovery as `composite`, while uninterrupted continuous terminal
  reconciliation stays `evidence_required`.
- Every previously bound contract changes only global authority revision/digest.
- Freshly re-digested mutations weakening zero cost, one-Flee ceiling, repeat
  denial, semantic/terminal separation, direct ownership, or Home fail closed.
- Registration remains `NOT_REGISTERED`/disabled; scheduler eligibility false.
- No runtime, selector, navigation, adapter, evidence, or session behavior change.

## Immutable budgets and safety limits

- One implementation, one review, at most one consolidated repair and recheck.
- Zero live attempts, observations, emulator/ADB actions, runtime inputs, and
  Flee/Challenge actions.
- No full repository unittest discovery. No push.

## Validation

- Exact new Ultimate authority/contract regressions.
- `python -m unittest tests.test_product_authority tests.test_gameplay_flow_contracts tests.test_catalog_and_pnsctl`
- Ultimate focused checked-in validation profile if offline/non-mutating.
- Architecture profile once after parent integration acceptance.
- `git diff --check`.

## Escalation conditions

- Product semantics require selected-Daily or Campaign AP ownership.
- Retained queue provenance contradicts verified Flee or zero-resource effect.
- Product migration requires controller, selector, runtime, adapter, safety,
  registration, scheduler, or evidence mutation.
- A must-fix review finding cannot close within the one repair budget.
