# Daily Milestone Claim product-record migration — frozen execution manifest r1

## Task ID and objective

- Task ID: `daily-milestone-claim-product-record-migration-r1`
- Objective: add one typed, revision-bound product-authority record and gameplay contract for the Daily Activity Milestone reward surface without implementing or exercising the route.

## Frozen stage control

- Host: `codex`
- Parent conversation ID: `current-task`
- `control_plane_owner`: `sol_parent`
- Revision ID: `daily-milestone-claim-product-record-migration-r1`
- Stage type: `heavy_product_authority_shared_binding_extension`
- Product precondition: `failed_missing_record_and_schema1_unbound_contract`
- Failure class: `core_contract`
- Stage start UTC: `2026-08-22T05:57:19.062Z`
- Continuation checkpoint UTC: `2026-08-22T05:57:19.062Z`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | stage freeze, architecture, integration acceptance, termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | assigned paths only; self-check, no architecture/live decisions |
| `independent_tester` | `gpt-5.6-terra-high` | read-only diff and acceptance review only |
| `procedure_coordinator` | `not used` | none |
| `escalation_architect` | `not used` | none unless a frozen escalation condition occurs |

## Immutable budgets

- One implementation, one review, at most one consolidated repair and one recheck.
- This is the second Heavy Stage 7 revision in the parent conversation; after this implementation and review the conversation uses four managed turns total.
- Live attempts: zero. Runtime inputs and Milestone Claim actions: zero.

## Frozen architecture decision

- Add record `activity_milestone_claim`, type `activity_milestone_claim`, revision `activity_milestone_claim-v1`, and advance global authority from r6 to r7.
- The product is a daily-reset-scoped reward surface reached `HOME → QUEST → ACTIVITY_MILESTONES`, separate from ordinary selected-Daily row Claim ownership.
- It owns only one exact, currently ready, fully visible, zero-cost milestone chest per milestone/reset occurrence. It does not own ordinary Claim controls or Daily objective point credit.
- Success requires the same milestone's opened/claimed control successor or an explicitly positive bound points successor; dispatch alone is never success. A dispatch-bearing unknown requires effect reconciliation and denies an identical retry.
- Not-ready, already-claimed, clipped, cost-bearing, unknown, contradictory, stale, ordinary-Claim, or real-money controls are forbidden. Terminal requires the same milestone panel successor followed by canonical Home.
- Existing Phase E Bliss/synthetic fixture authority remains platform-scoped diagnostic proof and cannot satisfy current BlueStacks route acceptance. Current ready/claimed BlueStacks evidence remains `evidence_required`.
- Upgrade the Milestone gameplay contract to schema 2 with exact r7/record/BlueStacks binding, `contract_only`, `production_eligible:false`, and disabled registration. Do not claim a runner, selector, navigation implementation, or accepted native proof.
- Add separate milestone claim ownership in the Daily catalog; preserve aggregate ordinary Claim as its existing sole ordinary-row owner.
- Mechanically update only the global authority revision/digest in the seven already-bound contracts. Their record digests and product semantics must remain unchanged.

## Writable paths

- `tasks/product_authority.py`
- `tasks/flow_delivery_product_policy.json`
- `tasks/gameplay_flow_contracts/DAILY-MILESTONE-CLAIM-BLUESTACKS-INTEGRATION.json`
- the seven currently r6-bound gameplay contracts, global revision/digest fields only
- `tasks/daily_quest_catalog.json`
- `tests/test_product_authority.py`
- `tests/test_gameplay_flow_contracts.py`
- `tests/test_catalog_and_pnsctl.py`
- this manifest; parent alone later owns `CURRENT_HANDOFF.md` and `docs/runtime-reliability-convergence-status.md`

## Acceptance checks

- Typed record validates exact recurrence, entry route, target, zero cost/quantity, successor, retry denial, ownership separation, and canonical Home.
- Contract is exact r7/record/BlueStacks bound and truthfully remains `contract_only` / `evidence_required` / not production eligible.
- Catalog separates milestone claim ownership from ordinary row Claim ownership.
- All prior product records and record digests are unchanged; prior bound contracts change only the global revision/digest.
- Focused authority, gameplay-contract, catalog, and Activity Milestone tests pass; `git diff --check` passes.

## Safety limits

- Allowed actions: offline edits and deterministic tests in the writable allowlist.
- Disallowed actions: selectors, navigation/runtime behavior, adapters, `pnsctl`, queue state, evidence mutation, registration, scheduler, emulator/ADB/BlueStacks access, Milestone Claim transport, commit, or push.
- Runtime/session/input budget: zero.

## Validation commands

- `python -m unittest tests.test_product_authority tests.test_gameplay_flow_contracts tests.test_catalog_and_pnsctl tests.test_activity_milestones`
- `python scripts/run_flow_delivery_validation.py architecture --flow-id DAILY-MILESTONE-CLAIM-BLUESTACKS-INTEGRATION`
- `git diff --check`

## Live budget

- Live admission: `not authorized`
- Input budget: `0`
- Iteration budget: `0`

## Evidence/history references

- `tasks/activity_milestones.py`
- `tests/fixtures/phase_e_activity_milestone_observations.json` (synthetic/Bliss-scoped diagnostic fixture; non-accepting for BlueStacks)
- `tasks/flow_delivery_queue.json#DAILY-MILESTONE-CLAIM-BLUESTACKS-INTEGRATION` (missing fresh ready/claimed BlueStacks proof)

## Escalation conditions

- The product meaning cannot be separated from ordinary row Claim ownership.
- Current retained native evidence contradicts the frozen target, cost, or successor semantics.
- Implementation would require selector/runtime behavior or broader Daily ownership changes.
- Authority binding cannot be advanced without changing an existing record digest or prior product semantics.
- Tester and implementation evidence conflict, two repair hypotheses fail, or progress stalls (`diminishing_returns`).
