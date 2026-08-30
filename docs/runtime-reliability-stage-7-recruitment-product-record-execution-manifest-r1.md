# Recruitment product-record migration — frozen execution manifest r1

## Task ID and objective

- Task ID: `recruitment-product-record-migration-r1`
- Objective: add one typed, revision-bound product-authority record and exact gameplay-contract bindings for Recruitment without changing or exercising selectors, controllers, navigation, or runtime behavior.

## Frozen stage control

- Host: `codex`
- Parent conversation ID: `current-task`
- `control_plane_owner`: `sol_parent`
- Revision ID: `recruitment-product-record-migration-r1`
- Stage type: `heavy_product_authority_shared_binding_extension`
- Product precondition: `failed_missing_record_and_unbound_reference_contracts`
- Failure class: `core_contract`
- Stage start UTC: `2026-08-22T06:20:17.3912447Z`
- Continuation checkpoint UTC: `2026-08-22T06:20:17.3912447Z`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | stage freeze, architecture, integration acceptance, termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | assigned paths only; self-check, no architecture/live decisions |
| `independent_tester` | `gpt-5.6-terra-high` | read-only diff and acceptance review only |
| `procedure_coordinator` | `not used` | none |
| `escalation_architect` | `not used` | none unless a frozen escalation condition occurs |

## Immutable budgets

- One implementation, one review, at most one consolidated repair and one recheck.
- This is the third and final Heavy Stage 7 revision permitted in this parent conversation; after implementation and review the conversation uses six managed turns total.
- Live attempts: zero. Runtime inputs and Recruitment actions: zero.

## Frozen architecture decision

- Add record `noahs_tavern_recruitment`, type `noahs_tavern_recruitment`, revision `noahs_tavern_recruitment-v1`, and advance global product authority from r7 to r8.
- The direct Noah's Tavern product has two explicitly separated effect contracts: the Daily objective is exactly five Basic zero-cost singles per game-day reset, while maintenance independently inspects Basic, Int., and Advanced and may use at most one currently available zero-cost single per tier/pass.
- Basic cooldown is exactly 600 seconds, Int. 86400 seconds, and Advanced 172800 seconds. Persist each tier independently; cooldown or exhaustion defers without waiting or paid substitution.
- Only Basic recruits own progress toward `recruit_noahs_tavern`; Int. and Advanced never own Daily completion or point credit. Selected Daily is not a prerequisite and ordinary Claim remains independently owned.
- Every dispatch requires the current selected tier, exact enabled free-single control, quantity one, cost zero, and fresh binding. Paid, premium, item-backed, 10x, ambiguous, unknown, contradictory, or stale controls are forbidden.
- Dispatch alone is not success. Require an explicit same-tier recruit-result/free-attempt successor, persist the appropriate progress/cooldown, and deny identical retry after an unknown effect. Terminal canonical Home is separate and mandatory.
- Bind both `RECRUITMENT-BLUESTACKS-INTEGRATION` and `RECRUITMENT-FREE-ATTEMPT-MAINTENANCE` to the same r8 record and current BlueStacks profile. Preserve their truthful `evidence_required`, not-production-eligible, registration-disabled state; existing semantic retained evidence and synthetic fixtures remain diagnostic/non-accepting for current continuous BlueStacks proof.
- Add Recruitment ownership metadata to the Daily catalog only where needed; do not redesign existing catalog semantics.
- Mechanically update only the global authority revision/digest in the eight already-bound contracts. Their record digests and product semantics must remain unchanged.

## Writable paths

- `tasks/product_authority.py`
- `tasks/flow_delivery_product_policy.json`
- `tasks/gameplay_flow_contracts/RECRUITMENT-BLUESTACKS-INTEGRATION.json`
- `tasks/gameplay_flow_contracts/RECRUITMENT-FREE-ATTEMPT-MAINTENANCE.json`
- the eight currently r7-bound gameplay contracts, global revision/digest fields only
- `tasks/daily_quest_catalog.json`
- directly related generated authority-view fixtures only if an existing checked-in generator requires them
- `tests/test_product_authority.py`
- `tests/test_gameplay_flow_contracts.py`
- `tests/test_catalog_and_pnsctl.py`
- existing focused Recruitment authority tests only
- this manifest; parent alone later owns `CURRENT_HANDOFF.md` and `docs/runtime-reliability-convergence-status.md`

## Acceptance checks

- Typed record validates exact Basic-five/reset semantics, independent three-tier cooldown maintenance, free-single quantity/cost, current-tier successor, persistence, retry denial, ownership separation, and canonical Home.
- Both Recruitment contracts are exact r8/record/BlueStacks bound and truthfully remain `evidence_required`, not production eligible, and registration disabled.
- Catalog maps only the Basic-five objective to Recruitment ownership; Int./Advanced maintenance does not claim Daily completion.
- All prior product records and record digests are unchanged; prior bound contracts change only the global revision/digest.
- Focused authority, gameplay-contract, catalog, and Recruitment tests pass; architecture profile and `git diff --check` pass.

## Safety limits

- Allowed actions: offline edits and deterministic tests in the writable allowlist.
- Disallowed actions: selectors, navigation/runtime behavior, adapters, `pnsctl`, queue state, evidence mutation, registration, scheduler, emulator/ADB/BlueStacks access, Recruitment transport, commit, or push.
- Runtime/session/input budget: zero.

## Validation commands

- `python -m unittest tests.test_product_authority tests.test_gameplay_flow_contracts tests.test_catalog_and_pnsctl tests.test_noahs_tavern_recruit tests.test_daily_recruitment tests.test_free_recruitment`
- `python scripts/run_flow_delivery_validation.py architecture --flow-id RECRUITMENT-BLUESTACKS-INTEGRATION`
- `git diff --check`

## Live budget

- Live admission: `not authorized`
- Input budget: `0`
- Iteration budget: `0`

## Evidence/history references

- `evidence/sessions/20260716-noahs-tavern-daily-free/record.md` at retained digest `cc5d306033c559d014947ee48449b794e0e3e8c7175cff2011d2336d6ad896c4` (semantic mechanics evidence only; do not recursively inspect)
- `tests/fixtures/phase_e_daily_recruitment_observations.json` and `tests/fixtures/phase_e_free_recruitment_observations.json` (synthetic policy diagnostics only)
- Current uninterrupted production-controller Basic-five and three-tier maintenance proof remains `evidence_required`.

## Escalation conditions

- Basic Daily ownership cannot be separated from Int./Advanced maintenance.
- Current retained native evidence contradicts the frozen tier, cost, cooldown, or successor semantics.
- Implementation would require selector/runtime behavior, shared primitive, or safety-authority changes.
- Authority binding cannot advance without changing an existing record digest or prior product semantics.
- Tester and implementation evidence conflict, two repair hypotheses fail, or progress stalls (`diminishing_returns`).
