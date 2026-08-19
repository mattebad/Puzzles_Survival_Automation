# Daily Resource Item Heavy r1

## Task ID and objective
- Task ID: `daily-resource-item`
- Canonical flow ID: `DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- Objective: implement and admit one BlueStacks flow that proves the current
  selected-Daily `Use resource item x1` objective by consuming exactly one
  freshly bound `1K Food` item and returning to verified Home.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `not recorded`
- `control_plane_owner`: `sol_parent`
- Revision ID: `daily-resource-item-20260818-r1`
- Stage type: `cross_contract_implementation`
- Product precondition: `not_applicable` for offline implementation; current
  selected-Daily identity remains a fail-closed live admission precondition.
- Failure class: `core_contract`
- Stage start UTC: `2026-08-19T00:15:50.390Z`
- Continuation checkpoint UTC: `2026-08-19T00:17:00.000Z`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | stage freeze, architecture, integration acceptance, live admission, failure classification, termination |
| `procedure_coordinator` | `not used` | none |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | one implementation turn within the exact writable scope |
| `independent_tester` | `gpt-5.6-terra-high` | one read-only diff and acceptance review |
| `escalation_architect` | `not used` | none |

## Immutable budgets
- Per stage: one Luna implementation, one Terra review, at most one
  parent-classified consolidated Luna repair and one Terra recheck, one parent
  integration checkpoint, and one live attempt.
- Per conversation: this is stage revision 1; managed-turn budget is one
  implementation plus one review, with one repair/recheck pair reserved.
- Timing: visible checkpoint at 60 elapsed minutes; further managed delegation
  or live admission after 90 minutes requires a later user continuation.

## Frozen authority reconciliation
- The active plan's `daily-resource-item` todo and its explicit ordering override
  older portfolio prose that placed milestone Claim first. Stop before
  `daily-milestone-claim`.
- The queue's null `use-resource-item` flow ID, staged state, and historical
  catalog blocker are missing executable wiring, classified `core_contract`;
  they are not a user blocker.
- Canonical identity follows the accepted Daily and BlueStacks integration
  convention: `DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`. The stable plan task
  ID remains `daily-resource-item`; `use-resource-item` and
  `use_resource_item` are migrated aliases for queue/catalog identity.
- Current selected-Daily native recognition is mandatory before any Bag item
  use. If the matching objective is absent, stale, already complete, or
  ambiguous, the live flow dispatches no `Use` and returns
  `product_state`/`evidence_required` for parent classification.
- The single freshly bound `Use` control is the only item-consumption dispatch.
  If a second confirmation, quantity chooser, bulk path, premium substitution,
  or unidentified item is presented, fail closed without that additional
  dispatch.
- Scheduler eligibility and unattended production registration remain disabled.
  Only checked-in development-conductor admission is authorized.

## Frozen architecture decision
- Add one cohesive route/recognizer module for current 800x1280 BlueStacks
  frames and one thin flow-delivery adapter registered through the fixed
  `pnsctl conduct` registry.
- Route: current native context -> known-benign VIP `Get Pts` Close if present ->
  verified Home -> selected Daily identity/progress capture -> Home/Bag ->
  Resources -> exact spatially associated `1K Food` item and owned count ->
  exact single `Use` -> item/resource delta -> matching Daily successor ->
  verified Home.
- Actionable controls must be current-frame-bound with full-frame bounds and
  overlay rejection. Narrow associated OCR may corroborate exact labels/counts;
  broad OCR or coordinates alone may not authorize input.
- Reuse existing Home, selected-Daily, runtime-session, popup-normalization, and
  visible in-game return primitives. Android Back is prohibited for unproven
  Bag/Resources/Daily transitions.
- Retain source, immediate-before, transport, immediate-post, semantic, and
  terminal Home evidence. Transport success alone is not completion.

## Writable paths
- `scripts/daily_resource_item_bluestacks.py`
- `scripts/flow_delivery_daily_resource_item_bluestacks.py`
- `scripts/pnsctl.py` — only imports/registration, allowlist/default input
  ceiling, retained-flow verification support, and symbols needed by this flow.
- `tasks/flow_delivery_bluestacks_registry.json`
- `tasks/flow_delivery_queue.json` — only the `use-resource-item` staging alias
  and the new canonical executable flow record.
- `tasks/flow_delivery_validation_profiles.json`
- `tasks/gameplay_flow_contracts/DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION.json`
- `tasks/daily_quest_catalog.json` — only canonical admission for
  `use_resource_item`, preserving provenance and Claim separation.
- `tasks/daily_quest_execution_matrix.json` — only Resource Item ownership and
  executable-contract fields.
- `tests/test_daily_resource_item_bluestacks.py`
- `tests/test_flow_delivery_daily_resource_item_bluestacks.py`
- `tests/test_gameplay_flow_contracts.py` — only assertions required for the new
  checked-in contract.
- `tests/test_flow_delivery_validation_profiles.py` — only profile registration
  assertions if required.

All other paths are read-only. The implementer must not edit this manifest, the
active plan, `BACKLOG.md`, `CURRENT_HANDOFF.md`, scheduler code, unrelated
flows, retained evidence, or local runtime state.

## Acceptance checks
- Contract, queue, fixed registry, `pnsctl`, and validation-profile identities
  agree on `DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`.
- Dry-run is zero transport and reports scheduler disabled.
- Source admission requires a current selected-Daily matching objective with
  incomplete progress and captures the same reset identity for successor proof.
- The route authorizes only exact `1K Food`, owned quantity at least one,
  quantity exactly one, and one current-frame-bound `Use`.
- `In bulk`, AP/Stamina recovery items, premium substitutions, unidentified
  items, stale frames, unsafe overlays, and ambiguous selectors fail closed.
- At most one executed `daily-resource-item:use-1k-food` event can exist.
- Completion requires both a positive inventory or Food-resource change and
  matching Daily objective progression, followed by positively verified Home.
- Objective completion never authorizes ordinary or milestone Claim.
- Focused route, adapter, contract, registry, conductor, and safety tests pass.

## Safety limits
- Allowed actions: bounded known-benign VIP Close; current-frame-bound
  navigation through visible controls; exactly one `1K Food` `Use`; visible
  in-game return controls needed to regain verified Home.
- Disallowed actions: `In bulk`; any second Use; quantity other than one;
  AP/Stamina recovery items; premium/paid/diamond/real-money substitutions;
  unidentified or non-Food items; ordinary or milestone Claim; Android Back
  from an unproven source; identical retry; direct ADB or Bliss input.
- Runtime/session limits: one `pnsctl` singleton session; native 800x1280
  BlueStacks package `com.global.ztmslg`; total input ceiling 10; one
  item-consumption dispatch; fail closed on unknown state or successor.

## Validation commands
- `python -m unittest tests.test_daily_resource_item_bluestacks tests.test_flow_delivery_daily_resource_item_bluestacks tests.test_gameplay_flow_contracts tests.test_flow_delivery_validation_profiles`
- `python scripts/run_flow_delivery_validation.py focused --flow-id DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`
- `python -m py_compile scripts/daily_resource_item_bluestacks.py scripts/flow_delivery_daily_resource_item_bluestacks.py scripts/pnsctl.py`
- Parent dry-run after integration:
  `python scripts/pnsctl.py conduct DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION`

## Live budget
- Live admission: parent-only after Luna self-check, Terra review, and explicit
  parent integration acceptance.
- Input budget: 10 total; exactly one item-consumption dispatch.
- Iteration budget: one supervised conduct attempt; no identical retry.

## Evidence/history references
- Active policy/plan:
  `.cursor/plans/daily_scheduler_promotion_1572d57c.plan.md`
- Current zero-input observation:
  `.local-captures/development-sessions/observe-20260819T001810812238Z`
  (native 800x1280, package correct, known-benign VIP `Get Pts` popup present).
- Independent visual reference named by the active plan:
  `image-a8207b17-56e3-45e4-8c70-0e1fb853064e.png`; it is design ground truth,
  not live-input authority.
- Knowledge fingerprints consulted before navigation:
  `AGENTS.md` `ba014f78b1638ed8a6e4146797cc3fddafd6eb66`;
  `docs/android-back-state-matrix.md`
  `229c8e4072b69408ae57d20fb5f912e25b1f641d`;
  `docs/runtime-input-safety-policy.md`
  `f34a8057248def3b8e6e06307de95815e09683b1`;
  `tasks/flow_delivery_queue.json`
  `bc92fa7a0e329317e83816fef76f86befe9c87d5`.

## Escalation conditions
- The frozen contract proves contradictory or incomplete.
- Current evidence requires a genuinely new architecture or safety decision
  with no dominant safe answer.
- Tester and implementation evidence materially conflict.
- A manual-only account state, unsupported product state, real-money
  confirmation, or required safety weakening is encountered.
- Two materially different repair hypotheses fail, or one STEP_BACK redesign
  has already failed.
- Ordinary syntax/test defects remain parent-classified repair work and are not
  user blockers.
