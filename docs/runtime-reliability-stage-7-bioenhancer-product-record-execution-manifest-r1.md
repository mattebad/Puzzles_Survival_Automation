# Runtime Reliability Stage 7 Bioenhancer product-record execution manifest r1

## Task ID and objective

- Task ID: `bioenhancer-product-record-migration-r1`
- Flow ID: `BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION`
- Objective: migrate only Bioenhancer Free Research to current typed,
  revision-bound product authority while preserving its direct Home route,
  one-free-only safety, historical platform-scoped evidence, disabled
  registration/scheduling, and unchanged adapter/runtime behavior.

## Frozen stage control

- Host: `codex`
- `control_plane_owner`: `sol_parent`
- Revision ID: `bioenhancer-product-record-migration-r1`
- Stage type: `product_authority_shared_binding_extension`
- Product precondition: `missing_typed_bioenhancer_record_and_schema1_unbound_contract`
- Failure class: `core_contract`
- Stage start UTC: `2026-08-22T05:32:58.264Z`
- User authorization: explicit continuation through remaining Stage 7 flows,
  executed serially as atomic lanes.

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` / `architecture_planner` | `gpt-5.6-sol-medium` | Freeze, architecture, integration acceptance, closure, termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One mutable implementation turn within the exact allowlist |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only diff-and-acceptance review |
| `procedure_coordinator` / `escalation_architect` | `not used` | No authority |

## Frozen architecture decision

- Add one typed direct-action `bioenhancer_research` record. It owns exactly one
  currently eligible zero-cost `Free Research 1x` action per visible cooldown
  window. Paid, premium/material-cost, `10x`, unknown-cost, stale-bound, and
  contradictory controls are prohibited.
- The route is direct canonical/localized Home → Research Lab → Bioenhancer; it
  does not require selected Daily. Bioenhancer may provide completion
  attribution for the catalog objective, but aggregate Daily Claim remains the
  sole Claim/point owner. Set null Daily owner/point trigger and
  `selected_daily_prerequisite: false`.
- Dispatch/transport is not semantic success. Success requires a positively
  recognized post-dispatch Free cooldown timer; count text alone is
  insufficient. A dispatch-bearing unknown successor requires reconciliation
  and denies an identical research retry. Canonical Home remains a separate
  terminal requirement.
- Preserve historical July research/Daily reconciliation provenance only as
  immutable platform-scoped evidence. It does not promote current BlueStacks
  uninterrupted proof. Contract proof and current native replay remain
  `evidence_required`; do not inspect or relabel retained evidence.
- Convert the Bioenhancer contract to current schema 2, bind the new record and
  current BlueStacks profile/package/Home authorities, and preserve
  `registration_state: disabled` and `production_eligible: false`.
- Bump global authority to r6 and mechanically rebind the six current Resource,
  Enhancement, Supply, Daily Claim, Nova, and Ultimate contracts. Their record
  revisions/digests, semantics, evidence, routes, and proof states must not
  change.
- Add Bioenhancer catalog product ownership and explicit
  `selected_daily_prerequisite: false` only; do not change the existing route
  controller or selected-Daily legacy behavior in this product-only lane.
- Do not modify selectors, navigation, adapters, `pnsctl`, runtime behavior,
  queues, registration, scheduling, or evidence.

## Exact writable allowlist

Implementation:

- `tasks/product_authority.py`
- `tasks/flow_delivery_product_policy.json`
- `tasks/gameplay_flow_contracts/BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/SUPPLY-DEPOT-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE.json`
- `tasks/gameplay_flow_contracts/ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION.json`
- `tasks/daily_quest_catalog.json`
- `tests/test_product_authority.py`
- `tests/test_gameplay_flow_contracts.py`
- `tests/test_catalog_and_pnsctl.py`

Parent-only control and closure:

- `docs/runtime-reliability-stage-7-bioenhancer-product-record-execution-manifest-r1.md`
- `CURRENT_HANDOFF.md`
- `docs/runtime-reliability-convergence-status.md`
- `.cursor/plans/p&s_runtime_reliability_convergence_program_e62703e1.plan.md`

All controllers, selectors, adapters, session/conductor code, registration,
scheduler, queues, receipts, evidence, and unrelated contracts are read-only.

## Acceptance checks

- Authority contains exactly the prior six records plus
  `bioenhancer_research`; existing records change only through the global
  revision/digest rebind.
- Bioenhancer types direct Home ownership, visible free eligibility, quantity
  one, cost zero, no `10x`/paid fallback, cooldown successor, dispatch/success
  separation, reconciliation/identical-retry denial, and canonical Home.
- Bioenhancer is rejected as a selected-Daily prerequisite or Claim/point owner.
- Catalog references the Bioenhancer product record without selected-Daily
  prerequisite and leaves aggregate Claim sole ownership unchanged.
- Bioenhancer contract is schema 2 and binds exact current authority/record
  digests and current BlueStacks identifiers.
- Historical evidence remains platform-scoped/non-accepting; current native
  uninterrupted proof remains `evidence_required`.
- Freshly re-digested mutations weakening free-only, one-action ceiling,
  cooldown successor, dispatch separation, retry denial, direct ownership, or
  Home fail closed.
- Registration remains `NOT_REGISTERED`/disabled; scheduler eligibility false.
- No adapter, runtime, navigation, selector, evidence, queue, or conduct change.

## Immutable budgets and safety limits

- One implementation, one review, at most one consolidated repair and recheck.
- Zero live attempts, observations, emulator/ADB actions, runtime inputs, and
  Bioenhancer research actions.
- No full repository unittest discovery. No push.

## Validation

- Exact new Bioenhancer authority/contract/catalog regressions.
- `python -m unittest tests.test_product_authority tests.test_gameplay_flow_contracts tests.test_catalog_and_pnsctl`
- Bioenhancer focused checked-in validation profile if offline/non-mutating.
- Architecture profile once after parent integration acceptance.
- `git diff --check`.

## Evidence/history references

- `tasks/daily_quest_execution_matrix.json#bioenhancer_research` contains the
  retained July platform-scoped research and Daily-reconciliation provenance.
- `tasks/flow_delivery_queue.json#BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION`
  contains current disabled delivery disposition.

## Escalation conditions

- Product semantics require selected-Daily/Claim ownership or a paid/10x action.
- Historical platform evidence is needed to claim current BlueStacks acceptance.
- Migration requires controller, selector, runtime, adapter, safety,
  registration, scheduler, queue, or evidence mutation.
- A must-fix review finding cannot close within the one repair budget.
