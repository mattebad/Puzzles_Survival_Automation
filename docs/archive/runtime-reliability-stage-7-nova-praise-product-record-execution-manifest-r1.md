# Runtime Reliability Stage 7 Nova Praise product-record execution manifest r1

## Task ID and objective

- Task ID: `nova-praise-product-record-migration-r1`
- Flow ID: `NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE`
- Objective: migrate only Nova Praise to current typed, revision-bound product
  authority without changing selectors, navigation, runtime behavior,
  registration, scheduling, or its continuous-session adapter.

## Frozen stage control

- Host: `codex`
- `control_plane_owner`: `sol_parent`
- Revision ID: `nova-praise-product-record-migration-r1`
- Stage type: `product_authority_shared_binding_extension`
- Product precondition: `missing_typed_nova_praise_product_record`
- Failure class: `core_contract`
- Stage start UTC: `2026-08-22T04:27:50.6173610Z`
- User authorization: explicit continuation through the remaining Stage 7
  portfolio, executed serially as atomic lanes.

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` / `architecture_planner` | `gpt-5.6-sol-medium` | Freeze, architecture, integration acceptance, closure, termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One mutable implementation turn within the exact allowlist |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only diff-and-acceptance review |
| `procedure_coordinator` / `escalation_architect` | `not used` | No authority |

## Frozen architecture decision

- Add one typed `nova_praise` direct-action product record for one eligible,
  zero-cost Praise pulse. It must type current free-attempt eligibility, exact
  attempts `X -> X-1`, fixed 300-second cooldown semantics, zero premium/currency
  cost, no identical retry, and safe canonical Home return.
- Nova does not own or route through the selected Daily surface. Its catalog
  objective may reference the Nova product record, while `daily_owner` and
  `point_credit_trigger` remain null and `selected_daily_prerequisite` remains
  false.
- Bump the global authority revision and digest because the authority is
  revision-bound and digest-bound.
- Mechanically rebind the four accepted Resource, Enhancement, Supply, and
  aggregate Daily Claim contracts to the new global authority revision/digest
  without changing their record revisions, record digests, routes, effects, or
  proof.
- Bind the existing Nova contract to its own record revision/digest and current
  native BlueStacks platform identifiers. Preserve its existing Home Atlas,
  current-frame free-attempt, one-Praise, cooldown, no-paid-fallback, and Home
  semantics.
- Use the retained completed Nova pulse only through its checked-in provenance:
  session `nova-praise-one-free-pulse-20260722T223535494658Z`, candidate
  `0ca611c5d42998b3d5c260c24c9604586d2aa831`, attempts `7 -> 6`, visible
  cooldown `299s`, one Praise transport, and terminal Home. Do not recursively
  reopen, copy, relabel, or fabricate evidence.
- Do not migrate the Nova adapter to `DevelopmentSession` in this stage.

## Exact writable allowlist

Implementation:

- `tasks/product_authority.py`
- `tasks/flow_delivery_product_policy.json`
- `tasks/gameplay_flow_contracts/NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE.json`
- `tasks/gameplay_flow_contracts/DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/SUPPLY-DEPOT-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION.json`
- `tasks/daily_quest_catalog.json`
- `tests/test_product_authority.py`
- `tests/test_gameplay_flow_contracts.py`
- `tests/test_catalog_and_pnsctl.py` only if required for catalog ownership

Parent-only control and closure:

- `docs/runtime-reliability-stage-7-nova-praise-product-record-execution-manifest-r1.md`
- `CURRENT_HANDOFF.md`
- `docs/runtime-reliability-convergence-status.md`
- `.cursor/plans/p&s_runtime_reliability_convergence_program_e62703e1.plan.md`

All selectors, navigation, Nova controllers/adapters, `pnsctl`, conductor,
session, registration, scheduler, evidence, and unrelated contracts are read-only.

## Acceptance checks

- Authority contains exactly the prior four records plus `nova_praise`.
- Nova recurrence/eligibility, Home Atlas semantic entry, free-attempt target,
  zero cost, quantity one, attempts decrement, cooldown, no-paid fallback,
  reconciliation/no-identical-retry constraint, and Home terminal are typed.
- Nova record includes immutable user-direction and native-authority references.
- Nova retains null Daily owner/point trigger and rejects selected-Daily coupling.
- The catalog `personal_might_praise` objective references only `nova_praise`
  without making selected Daily an input prerequisite.
- Nova contract binds the exact current authority and Nova record revision/digest.
- Every previously bound contract changes only its global authority
  revision/digest binding.
- Old authority or Nova record revisions/digests fail closed.
- Production registration remains `NOT_REGISTERED`/disabled and scheduler
  eligibility remains false.
- No selector, navigation, runtime, session, conductor, registration, scheduler,
  evidence, or adapter behavior changes.

## Immutable budgets and safety limits

- One implementation, one independent review, at most one consolidated repair,
  and one recheck.
- Zero live attempts, sessions, observations, emulator/ADB actions, and runtime inputs.
- No full repository unittest discovery.
- No commit or push.

## Validation

- Exact new Nova product-authority regressions.
- `python -m unittest tests.test_product_authority tests.test_gameplay_flow_contracts tests.test_catalog_and_pnsctl`
- Nova focused checked-in validation profile only if it remains offline/non-mutating.
- Architecture profile once after parent integration acceptance.
- `git diff --check`.

## Escalation conditions

- Nova product semantics require selected-Daily ownership or attribution routing.
- The global digest rebind changes an existing record or contract semantic.
- Any selector, navigation, runtime, safety, session, registration, scheduler, or
  evidence change becomes necessary.
- Retained native evidence contradicts the one-free-Praise/cooldown design.
- A must-fix review finding cannot be resolved in the single repair budget.
