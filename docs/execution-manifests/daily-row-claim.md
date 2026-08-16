# Daily Row Claim execution manifest

## Task ID and objective
- Task ID: `daily-row-claim`
- Flow ID: `DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`
- Manifest state: `FROZEN_RECONNAISSANCE_REPAIR_CONTINUATION`
- Frozen repository candidate: `main@6e497f12b159d5b5e8deb0f3bc73c8c9577f95d9`
- Corrected freeze UTC: `2026-08-16T22:06:31.5258035Z`
- Objective: acquire current local-BlueStacks ordinary Daily row evidence, then deliver one exact free row-local Claim without registering or scheduling the handler.

## Execution routing and timing
- Host: `cursor`
- Parent conversation ID: `4caa8e49-ddb7-46dd-9cd9-d012c79fed47`

| Role | Model | Agent/session ID | Started UTC | Completed UTC |
| --- | --- | --- | --- | --- |
| `architecture_planner` | `GPT-5.6 Sol` | `cursor-parent-4caa8e49-ddb7-46dd-9cd9-d012c79fed47` | `2026-08-16T21:47:52.176Z` | `2026-08-16T22:06:31.5258035Z` |
| `execution_coordinator` | `GPT-5.6 Luna XHigh` | `not assigned` | `not started` | `not completed` |
| `bounded_implementer` | `GPT-5.6 Luna XHigh` | `not assigned` | `not started` | `not completed` |
| `independent_tester` | `Terra High` | `not assigned` | `not started` | `not completed` |
| `escalation_architect` | `GPT-5.6 Sol Medium` | `fbd0edc2-aea7-45af-be8c-d868a8925d6a` | `2026-08-16T21:53:24.2256895Z` | `2026-08-16T21:55:12.2977131Z` |

## Frozen architecture decision
- The current active-development and canary target is the private local BlueStacks instance, package `com.global.ztmslg`, using the checked-in native `800x1280` profile and exact allowlisted local serial.
- Bliss is the later porting and deployment-acceptance target. It is not a prerequisite or substitute for this BlueStacks flow.
- The earlier Bliss-only bootstrap decision and escalation result are superseded by the user's runtime-phase clarification.
- Work remains evidence-first. The first runtime action is one receipt-bound zero-input observation through the existing local BlueStacks development-session command. No implementation change or Claim dispatch is authorized before that observation.
- The exact frozen reconnaissance command is:
  `python scripts/pnsctl.py development-session observe --max-inputs 0 --delegated-receipt <RECEIPT_DB> --agent-identity <LUNA_AGENT_ID> --task-id daily-row-claim --flow-id DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION --scenario selected-daily-row-evidence --variant ordinary-row`
- The command must consume a `reconnaissance` receipt, acquire and release singleton ownership, dispatch zero inputs, capture one current native BlueStacks frame, and retain a bound result and terminal summary.
- Independent review rejected live admission because a post-capture failure can leave success-looking artifacts and success does not revalidate retained artifact contents. One bounded repair is frozen before reconnaissance.
- Legacy `run-task daily-claim` remains unauthorized because it can dispatch Claim and is not delegated-receipt-bound.
- If the observed frame is not the selected Daily screen with one fully visible ordinary ready row, stop `evidence_required`. Do not add navigation or Claim behavior under reconnaissance authority.
- After accepted source evidence exists, the parent must freeze the evidence-bound implementation revision before assigning Claim code. That revision will preserve `AvailableDailyClaimObservation` as the domain contract, require independent current-frame row/target geometry and a same-objective successor, and reject synthetic references as live provenance.
- The eventual free Claim is an `ordinary_development` zero-cost reward claim. Claims do not use a consequential-action lifecycle; combat dispatch and real-money confirmation remain the only consequential classes.

## Reused foundations and dependency check
- Reuse the accepted selected-Daily inventory and game-day/reset identity from `DQ-FOUNDATION-DAILY-INVENTORY`.
- Reuse the offline authorization and postcondition structure in `tasks/available_daily_claim.py`.
- Preserve the accepted exact Personal Might Claim path; it does not authorize generalized Claim geometry.
- Preserve the delegated receipt controller and zero-input ownership-release contract.
- Current authority remains `EVIDENCE_REQUIRED`, `NOT_REGISTERED`, scheduler-ineligible, composition-blocked, and M6-inactive.
- The queue remains non-active because its Daily Row Claim entry is blocked on fresh source/target/successor evidence.

## Frozen reconnaissance-repair writable paths
- Production: `scripts/pnsctl.py`
- Tests: `tests/test_delegated_runtime_receipts.py`
- The repair must rewrite retained terminal artifacts fail-closed after any post-capture failure and validate the retained frame hash, receipt/result bindings, zero counts, terminal status, and ownership release before recording success.
- Re-review found one remaining defect: fallback artifact-write failure can prevent durable `evidence_required` terminal recording. Live admission remains rejected.
- Repair budget: one of three repair turns used; up to two additional serial repair turns remain, each followed by an independent read-only tester recheck.
- No runtime access is authorized during the repair.
- Queue, catalog, matrix, policy, registry, registration, scheduler, composition, M6, and Bliss state remain unchanged.
- `scripts/flow_delivery_control.py` and all other production/test paths remain excluded.

## Deferred evidence-bound implementation paths
These paths are candidates only and are not writable under `FROZEN_RECONNAISSANCE`:
- `tasks/available_daily_claim.py`
- `scripts/flow_delivery_daily_row_claim_bluestacks.py`
- `scripts/pnsctl.py`
- `tasks/flow_delivery_bluestacks_registry.json`
- `tasks/gameplay_flow_contracts/DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION.json`
- `tests/test_available_daily_claim.py`
- `tests/test_gameplay_flow_contracts.py`
- `tests/test_flow_delivery_daily_row_claim.py`
- `tests/test_daily_row_claim_bluestacks.py`

## Required states and transitions
- Reconnaissance: `FROZEN_RECONNAISSANCE_REPAIR -> OBSERVER_REPAIRED -> TESTER_ACCEPTED -> PARENT_INTEGRATION_ACCEPTED -> RECONNAISSANCE_RECEIPT_ISSUED -> ZERO_INPUT_OBSERVED -> SOURCE_EVIDENCE_ACCEPTED`.
- Evidence negative: any wrong profile, package, dimensions, receipt binding, ownership state, missing frame/result/summary, or non-selected-Daily frame transitions to `EVIDENCE_REQUIRED`.
- Later implementation revision: `SOURCE_EVIDENCE_ACCEPTED -> OFFLINE_IMPLEMENTED -> TESTER_ACCEPTED -> PARENT_INTEGRATION_ACCEPTED -> CANARY_ADMITTED`.
- Later canary: `READY_TO_CLAIM -> CLAIM_DISPATCHED_ONCE -> CLAIMED_OR_POINTS_INCREASED -> TERMINAL_DAILY_SELECTED`.
- Any stale target, Main tab, incomplete or clipped row, `GO`, milestone chest, adjacent control, overlay, reset ambiguity, unknown cost, nonzero cost, wrong quantity, unchanged successor, wrong objective, transport ambiguity, or missing immediate postcondition stops fail-closed without identical retry.

## Persistence and idempotency
- Reconnaissance receipt result identity: `daily-row-claim:reconnaissance:selected-daily-row-evidence`.
- Future Claim reservation key: `daily-row-claim:<game_day_id>:<objective_key>:claim`.
- Establish the game-day identity once per development session and bind all future source and successor evidence to it.
- Reserve any future Claim before dispatch and reconcile only from the immediate semantic successor. An unknown result does not reopen the one-Claim budget.

## Acceptance checks
- The existing observation command is present only under `development-session` and requires all delegated receipt bindings.
- It consumes only a `reconnaissance` receipt with `max_total_inputs=0`, zero resource-affecting inputs, and zero combat confirmations.
- It may use only the checked-in local BlueStacks ADB executable and exact allowlisted private serial through `pnsctl`; it cannot dispatch tap, swipe, key, text, shell-input, Claim, purchase, resource, march, or combat actions.
- It validates `com.global.ztmslg` and native `800x1280` on local BlueStacks before retaining `observe.png`.
- It retains source SHA-256, result identity, `result.json`, `summary.json`, zero input count, terminal status, and proven singleton release.
- It rereads and validates retained evidence before terminal success and leaves fail-closed artifacts after any post-capture, checkpoint, or ownership-release failure.
- It does not mutate `BACKLOG.md`, `CURRENT_HANDOFF.md`, `tasks/flow_delivery_queue.json`, registration, scheduling, composition, M6, BlueStacks configuration, Bliss configuration, or unrelated Git state.
- Existing delegated-receipt and zero-input observation tests are the acceptance basis for this unchanged command.

## Safety limits
- Allowed now: up to two additional serial offline bounded repairs in the frozen reconnaissance-repair allowlist, with an independent read-only tester recheck after each.
- Allowed after tester acceptance and parent integration acceptance: one delegated zero-input local BlueStacks observation using the exact frozen command.
- Disallowed now: navigation, Claim binding or dispatch, queue activation, registration, scheduling, direct ADB outside `pnsctl`, ad hoc remote shell, Bliss access, and evidence fabrication.
- Reconnaissance live budget: one observation, zero inputs, zero resource-affecting inputs, zero combat confirmations.
- Future Claim budget: not authorized by this revision.
- Real-money Cash Mall confirmation is unsupported.

## Validation commands
- `python -m unittest tests.test_delegated_runtime_receipts tests.test_catalog_and_pnsctl`
- `python scripts/run_flow_delivery_validation.py focused --flow-id DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`
- Shared-navigation validation is required only if a later evidence-bound revision changes navigation.
- Full repository discovery remains manual-only.

## Evidence references
- Reused offline contract: `tasks/available_daily_claim.py`
- Reused selected-Daily authority: `tasks/daily_quest_execution_matrix.json`
- Reused exact Personal Might proof references are listed in the execution matrix and are not generalized target proof.
- Required new reconnaissance evidence: one current local BlueStacks `observe.png`, its SHA-256, delegated receipt/result binding, terminal `result.json`, terminal `summary.json`, and ownership release.
- Required later source ground truth: native source frame, source hash, row bounds, Claim ROI, annotated full-frame source, nearby objective/progress semantics, runtime profile, and game-day identity.
- Required later successor proof: immediate post frame showing the same objective row no longer ready/visible or a positive Daily points delta.

## Milestones
- Architecture frozen: `yes`
- Offline implemented: `no`
- Tester accepted: `no`
- Live proven: `no`
- Merged: `no`
- Registration state: `NOT_REGISTERED`
- Scheduler eligibility: `false`

## Escalation conditions
- The approved plan is contradictory or incomplete.
- A genuinely new architecture decision is required.
- Safety authority is ambiguous.
- Tester and implementation evidence conflict.
- Two materially different repair hypotheses fail.
- Live evidence disproves the accepted design.
- Ordinary test failures, syntax errors, and known repairs do not escalate.

## Stop conditions
- Stop repairs after tester acceptance or after the third total repair turn. A fourth repair requires explicit user authorization, a refrozen manifest, a compact handoff, and a fresh execution chat.
- Stop after one zero-input observation with `EVIDENCE_REQUIRED` if the selected Daily ready row is absent or ambiguous.
- Stop before any Claim implementation until the parent freezes the evidence-bound revision.
- Stop after any unknown runtime, ownership, transport, evidence, or semantic result; do not retry identically.

## Next authorized action
- Assign one offline bounded `GPT-5.6 Luna XHigh` repair turn limited to making terminal failure recording independent of fallback artifact writes and adding the exact regression test, then run an independent read-only tester recheck. No runtime access, navigation, or Claim input is authorized.
