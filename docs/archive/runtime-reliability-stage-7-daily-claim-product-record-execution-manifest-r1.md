# Runtime Reliability Stage 7 Daily Claim product-record execution manifest r1

## Task ID and objective

- Task ID: `daily-claim-product-record-migration-r1`
- Flow ID: `DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`
- Objective: migrate only ordinary aggregate Daily Claim to current typed,
  revision-bound product authority without changing selectors, navigation,
  runtime behavior, registration, scheduling, or the continuous-session adapter.

## Frozen stage control

- Host: `codex`
- `control_plane_owner`: `sol_parent`
- Revision ID: `daily-claim-product-record-migration-r1`
- Stage type: `product_authority_shared_binding_extension`
- Product precondition: `missing_typed_daily_claim_product_record`
- Failure class: `core_contract`
- Stage start UTC: `2026-08-21T22:40:21.5694089Z`
- User authorization: explicit Stage 7 Daily Claim selection with Heavy promotion
  permitted when shared authority or multiple product contracts must change.

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` / `architecture_planner` | `gpt-5.6-sol-medium` | Freeze, architecture, integration acceptance, closure, termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One mutable implementation turn within the exact allowlist |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only diff-and-acceptance review |
| `procedure_coordinator` / `escalation_architect` | `not used` | No authority |

## Frozen architecture decision

- Add one typed `aggregate_daily_claim` product record. It alone may declare
  selected-Daily ownership; direct-action records and contracts continue to
  reject selected-Daily coupling.
- Bump the global product-authority revision and digest because the current
  authority is revision-bound and digest-bound.
- Mechanically rebind the three already-migrated Resource, Enhancement, and
  Supply contracts to the new global authority revision/digest without changing
  their product-record revision, record digest, route, inputs, effects, or proof.
- Bind the Daily Claim contract to its own record revision/digest and current
  native BlueStacks platform identifiers. Preserve its existing aggregate,
  ordinary-free, row-local Claim semantics and retained composite proof.
- Add Daily catalog reconciliation ownership only where required to name the
  aggregate Claim record and keep registration/scheduler disabled.
- Do not migrate the Daily adapter to `DevelopmentSession` in this stage.

## Exact writable allowlist

Implementation:

- `tasks/product_authority.py`
- `tasks/flow_delivery_product_policy.json`
- `tasks/gameplay_flow_contracts/DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/SUPPLY-DEPOT-BLUESTACKS-INTEGRATION.json`
- `tasks/daily_quest_catalog.json`
- `tests/test_product_authority.py`
- `tests/test_gameplay_flow_contracts.py`
- `tests/test_catalog_and_pnsctl.py` only if required for the catalog ownership assertion

Parent-only control and closure:

- `docs/runtime-reliability-stage-7-daily-claim-product-record-execution-manifest-r1.md`
- `CURRENT_HANDOFF.md`
- `docs/runtime-reliability-convergence-status.md`
- `.cursor/plans/p&s_runtime_reliability_convergence_program_e62703e1.plan.md`

All selectors, navigation, runtime adapters, `pnsctl`, conductor, session,
registration, scheduler, evidence, and unrelated contracts are read-only.

## Acceptance checks

- Authority contains exactly the prior three records plus `aggregate_daily_claim`.
- Daily recurrence, entry route, row-local ordinary Claim ownership, free/zero
  cost, one-dispatch ceiling, positive points/control successor, reset scope,
  and canonical Home terminal are typed.
- Daily record includes immutable user-direction and native-authority references.
- Direct-action records still require `selected_daily_prerequisite: false` and
  bound direct-action contracts still reject selected-Daily coupling.
- Daily contract binds the exact current authority and Daily record revision/digest.
- Every previously bound contract is rebound only to the new global authority
  revision/digest and retains its prior product record and semantics.
- Old authority revisions/digests and old Daily record revisions/digests fail closed.
- Daily catalog names aggregate Claim as the sole ordinary Claim owner.
- Contract remains registration disabled and production ineligible; scheduler
  eligibility remains false in the catalog/status sources.
- No selector, navigation, runtime, session, conductor, registration, scheduler,
  evidence, or adapter behavior changes.

## Immutable budgets and safety limits

- One implementation, one independent review, at most one consolidated repair,
  and one recheck.
- Zero live attempts, sessions, observations, emulator/ADB actions, and runtime inputs.
- No full repository unittest discovery.
- No commit or push.

## Validation

- Exact new Daily product-authority regressions.
- `python -m unittest tests.test_product_authority tests.test_gameplay_flow_contracts tests.test_catalog_and_pnsctl`
- Existing Daily authority/contract suites as required by the diff.
- Daily Claim focused checked-in validation profile.
- Architecture profile once after parent integration acceptance.
- `git diff --check`.

## Escalation conditions

- Daily ownership cannot be distinguished from direct-action selected-Daily coupling.
- The global digest rebind changes an existing product record or contract semantic.
- Any selector, navigation, runtime, safety, session, registration, scheduler, or
  evidence change becomes necessary.
- Retained native evidence contradicts aggregate ordinary Claim semantics.
- A must-fix review finding cannot be resolved in the single repair budget.
