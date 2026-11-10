# Issue 114 review: Training development configuration and input accounting

Offline, code-only plan review for [issue 114](https://github.com/mattebad/Puzzles_Survival_Automation/issues/114) under its [review assignment](https://github.com/mattebad/Puzzles_Survival_Automation/issues/114#issuecomment-6755269645). This is a review of the **plan**, not a native-readiness or acceptance claim. No BlueStacks, ADB, device, runtime command, database connection, test run, or source edit was performed.

## 1. Verdict and provenance

**Verdict: REVISE, then proceed.** The issue's direction is sound (one trusted configuration, preserve original batch facts, no new authority). The source shows three corrections are needed before implementation:

1. **Accounting fix shape.** The mismatch is attempted-vs-admitted, and the native boundary already counts *admitted* inputs. The fix is to record *why* a session attempt was never admitted, not to move or roll back the session increment (section 2, A1–A4).
2. **Drop the proposed `operator_request_id` extension for Training.** Training already has `timer` cadence. Its next-due comes from the positively observed queue timer, and continuous variants already claim and start generation N+1 in the same visit. A development repeat therefore needs no manual-repeat bypass. The existing bypass skips `next_due_at_utc`, which is the opposite of what completion-gated cycles need (B5).
3. **Boundary of `ResourceEffectAuthority` for Training.** Training start and claim *dispatch* is authorized by `CentralPolicy` → `safe_action_core/approved_base_routes.py::_training` and journaled by `SafeActionExecutor`/`SafetyStore`. Neither Training module references REA. REA history is still consulted on the Training **recovery** path: `scripts/pnsctl.py::_troop_training_recovery_history` (:426-461) refuses recovery on ACTIVE/CONFLICT or other-reset CLEARED resource-effect blocks. Preserve that guard unchanged. The development-profile change belongs in `_training`'s closed tables and in history derivation. No REA change is required unless a caller proves otherwise.

| Item | Value |
| --- | --- |
| Inspected source | `fix/live-first-recovery-114` at **`f2346719dbe6985a0d7dd5ada08aef7fa3357d71`** ("Prepare reviewed correction source checkpoint for issue 114"). Parent `7994eedc7fbc15d0211906c2b3863333203a484c` is an ancestor (verified with `git merge-base --is-ancestor`). |
| Checkout | Fresh clean clone of `origin/fix/live-first-recovery-114`; `git status` clean before writing this report. Not a linked worktree (fine for offline reading; linked-worktree rules govern live work only). |
| Carryover | Per [`docs/research/issue-114-source-checkpoint.md`](https://github.com/mattebad/Puzzles_Survival_Automation/blob/f2346719dbe6985a0d7dd5ada08aef7fa3357d71/docs/research/issue-114-source-checkpoint.md): 24 modified and 8 untracked correction files, committed in that one checkpoint commit (33 paths including the brief). Every file cited below is committed at the inspected SHA, so the `path:line` references are stable at that SHA. I did not re-verify the manifest SHA-256 values, because Git line-ending conversion makes raw working-file digests non-comparable. |
| Report commit | A later, report-only commit on the same branch; its SHA is recorded in the issue 114 comment, not here. |
| Evidence gaps | `.local-captures` were not published. The S4 receipt (runtime 7 / session 8, zero Train/Claim, last screen Shooter Camp 250/1510), the rollback archive, the Nov 9 manual walkthrough (261 screenshots) and `training-preset-positive-reconciliation.json` are **HISTORICAL_EVIDENCE, not inspected**. Their numbers come from issue 114, #67, #95 and #53. |

Labels used: **SV** = SOURCE_VERIFIED at the inspected SHA. **HE** = HISTORICAL_EVIDENCE (reported, not inspected). **UI?** = UNVERIFIED_UI_ASSUMPTION. **ER** = evidence_required.

## 2. Execution map and findings

Call path (SV):

`scripts/pnsctl.py` → `automation_service/cli.py` serve → `AutomationService.serve` (`automation_service/service.py`) → scheduler pulse/claim (`automation_service/scheduler.py`, `automation_service/state.py`) → `TroopTrainingRunner.__call__` (`automation_service/troop_training.py`) → `NativeRouteRequest` → `_BoundNativeRoute.run` (`scripts/base_route_native_runtime.py`: `DevelopmentSession` + `LocalBlueStacksRuntime` + canonical `SafetyStore`) → `run_troop_training_native` → `TroopTrainingIntegratedRoute` (`scripts/troop_training_bluestacks.py`) → `TrainingController` (`tasks/troop_training.py`) → `CentralPolicy`/`_training` + `SafeActionExecutor` → `SafetyStore.actions` rows → `derive_training_action_state` on the next visit.

`scripts/base_route_native_runtime.py` is the actual native boundary. The assignment's starting list omitted it, but it owns session/runtime pairing and the accounting snapshot.

### A. Input accounting

- **A1 (SV): the session counts the attempt before the native runtime admits it.** `DevelopmentSession.run_action` (`scripts/navigation_development_boundary.py:1030-1081`) runs `self.input_count += 1` at :1073 and then calls `dispatch(before)`. On exception (:1076-1079) it re-raises without any admission/transport distinction.
  - All Training navigation goes through this path via `_TroopTrainingInputBudgetRuntime.__getattr__` → `session.run_action` (`scripts/troop_training_bluestacks.py:106-192`).
  - Consequential start and claim also go through it, via `_execute_canonical_action` (:1458).
- **A2 (SV): the native runtime counts at admission, and its journal event is pre-transport.** `LocalBlueStacksRuntime._authorize_dispatch` (`scripts/bluestacks_native_runtime.py:390-464`) can raise before its own increment at :459 for several reasons:
  - network/blocking modal (:416-418);
  - stale source frame (:419-421);
  - input limit (:422-423);
  - duplicate or missing action key (:424-425);
  - identical source/target fingerprint (:435-436).

  `tap` writes the `dispatch` event (:557-570) *before* `_dispatch_transport` (:574). `_dispatch_transport` (:507-530) reports the transport result only to a delegated runtime ledger, via `mark_transported` / `mark_reconciled(unresolved=True)`, and only when a delegated context is active. It writes no transport-outcome row to the runtime `events.jsonl`.

  So:
  - `runtime.input_count` = **admitted**;
  - `session.input_count` = **attempted**;
  - the journal `dispatch` row = **admitted intent**, not delivery.

  On the service path, the runtime journal therefore holds no "ADB call returned" record. Even such a record would not prove physical delivery.
- **A3 (SV mechanism; HE instance): a pre-admission rejection produces session = runtime + 1.** `_accounting_snapshot` (`scripts/base_route_native_runtime.py:344-372`) reports `max(session, runtime)` and sets `verified` only on equality. `_BoundNativeRoute.run` (:532-541) turns inequality into failure "native route input accounting is inconsistent".
  - The S4 7/8 receipt is consistent with exactly one pre-admission rejection.
  - Which rejection it was is **ER**: the receipt was not inspected. Stale-frame (OCR inside the `authorize` callbacks at `troop_training_bluestacks.py:1408-1419` and :158-175) and identical-fingerprint rejections are plausible candidates. Treat both as [INFERENCE].
- **A4 (SV): consumer-visible consequence.**
  - `TroopTrainingRunner` marks the result `accounting_verified=False`, reason `NATIVE_TROOP_TRAINING_ACCOUNTING_UNVERIFIED` (`automation_service/troop_training.py:399-410`).
  - The service refuses to record executor consumption: `record_consumption` raises `*_CONSUMPTION_ACCOUNTING_UNVERIFIED` (`automation_service/service.py:989-995`).
  - The run therefore cannot close with verified terminal accounting, and the failure counts against the technical retry window (`automation_service/state.py:2757-2766`).
  - A proven zero-transport rejection is indistinguishable from a lost input, so it lands in the same inspection/rearm path as a genuine uncertainty. This matches #53's "authoritative run/attempt-bound accounting" prerequisite.
- **A5 (SV): the consequential executor is already conservative.** `_execute_canonical_action` (`troop_training_bluestacks.py:1457-1483`) counts `max(runtime_delta, session_delta)` and reports a possibly-sent `TransportResult` on exception, which makes Core mark the action UNRESOLVED. That is correct for uncertainty, but a typed pre-admission rejection would also be classified "possibly sent". Keep this conservatism. Only a typed, proven pre-admission rejection may produce "not sent".

### B. Training configuration: model accepts it, every consumer contradicts it

- **B1 (SV): the model accepts 2 and 10.** `TrainingConfig.validate` (`tasks/troop_training.py:51-67`) allows fixed quantities 1–1000. The issue's in-memory probe (HE) matches.
- **B2 (SV): the native layer installs production defaults and rejects caller settings.**
  - `TroopTrainingRunner` always passes `arguments=MappingProxyType({})` (`automation_service/troop_training.py:379`).
  - `run_troop_training_native` raises on any argument (`scripts/troop_training_bluestacks.py:2721-2722`) and hard-codes `config=default_troop_training_config()` (:2769).
  - `_train` additionally requires fixed mode to be exactly 250 with capacity ≥ 250 (:2123-2126).
  - Defaults live at `tasks/troop_training.py:105-113`.
- **B3 (SV): Core has its own production-only closed table.** `_TRAINING_VARIANTS` (`safe_action_core/approved_base_routes.py:1067-1072`).
  - Start authorization requires the token prefix to equal that table, `qty == 250 and maximum >= 250` for fixed mode, and `count == 0` for once_daily (:1211-1259).
  - Claim authorization rebuilds `tier`, `quantity_mode` and `configured_quantity` from the same table (:1124-1153).
  - Core receives the counts (`per_reset_variant_start_count`) from the route's tokens. It does not read history itself.
- **B4 (SV): history rejects small daily batches.** `derive_training_action_state` raises `"confirmed daily training start is not quantity 250"` for pending Shooter/Rider batches (`automation_service/troop_training.py:214-215`).
  - It derives `prior_daily_initiations` from *all* countable Shooter/Rider starts this reset (:238-242), and `start_counts` includes every countable status (:171-172).
  - Callers:
    - native entry `troop_training_bluestacks.py:2748`;
    - post-claim re-derivation :1742;
    - `pnsctl` Training recovery history `_troop_training_recovery_history` (`scripts/pnsctl.py:349-388`).

    A dev Shooter2 row would therefore also break `bluestacks recover-home`.
  - The test `tests/test_service_troop_training.py::test_pending_daily_batch_rejects_stored_quantity_other_than_250` pins this production assumption as an invariant.
- **B5 (SV): Training is excluded from manual repeat, and doesn't need it.**
  - `serve` allows `operator_request_id` only for Enhancement/Ultimate/Hall (`automation_service/service.py:851-855`).
  - The claim-time `repeat_daily` bypass of `next_due_at_utc` requires a `daily_once_per_reset` or daily occurrence (`automation_service/state.py:2736-2756`).
  - Training is registered with `cadence="timer"` (`automation_service/registry.py:950-957`). Scheduled eligibility applies the once-per-reset skip only to `DAILY_ONCE_PER_RESET` (`automation_service/scheduler.py:656-664`) and the occurrence-limit check only to `RESET_BOUNDED` (:668-679). Every class is gated by `next_due_at_utc`, the retry window and `retry_not_before` (:697-706). A same-reset re-claim of Training is therefore admitted once `next_due_at_utc` has passed, provided the service and flow are enabled and unblocked.
  - Its due time comes from `troop_training_next_due` (`automation_service/troop_training.py:480-538`): the earliest positively observed active-queue completion, `next_due_utc` (+60 s on partial), or the next reset.
  - The tab loop already claims a completed continuous batch and starts the next generation in the same visit (`troop_training_bluestacks.py:2417-2453`, where once_daily `continue`s after the claim at :2421-2423).
  - Conclusion: development repeats need the claim → start path for all four variants, not a manual-repeat exception. It is ER whether the Training flow row's live recurrence projection matches this, since I opened no database. The implementer must check it with the supported read-only status interface before relying on it.
- **B6 (SV): service reporting would label a development visit as production success.**
  - For Training, `status=="completed"` becomes `NormalizedOutcome.COMPLETE_FOR_RESET` with reason `TROOP_TRAINING..._PASS_VERIFIED` (`automation_service/service.py:1402-1423`).
  - The same file's maintenance precedent reports `DEFERRED` with the proven timer instead of completing the occurrence (:1356-1371).

### C. Persisted batch identity and original facts

- **C1 (SV): original batch facts are already persisted. No schema change is needed.**
  - `SafetyStore.actions` stores `quantity` and `policy_request_json` (`safe_action_core/store.py:743-746, 1106-1117`).
  - `policy_request_json` is `snapshot(PolicyRequest)` (`safe_action_core/policy.py:365`; `safe_action_core/models.py:1088-1108`), which includes every `semantic_preconditions` token: tier, `quantity_mode`, `configured_quantity`, `training_policy`, generation and per-reset count.
  - Pending quantity is read from `row["quantity"]` (`automation_service/troop_training.py:211-216`). `derive_training_action_state` never reads `policy_request_json`. Tier, mode, policy and profile are therefore persisted but **not restored or validated today**, so the plan needs an explicit fail-closed decoder (step 4).
- **C2 (SV): identity spans reset and restart.**
  - The start key is `troop-training:<identity>:<reset-digest>:<variant>:g<N>:start` (`automation_service/troop_training.py:85-98`). Generation is a per-variant global maximum over *confirmed* starts across resets (:173-174, :196).
  - The claim key is `<start>:claim` and carries `confirmed_start_reset_id` (`troop_training_bluestacks.py:1640-1672`).
  - Pending batches keep their original reset (`pending_start_reset_ids`).
- **C3 (SV): claim validation mixes the batch's facts with the *current* configuration.**
  - `plan_claim` and `reconcile_active_queue` check `queue_tier` against `config.target_tier` (`tasks/troop_training.py:536-539, 636-641`).
  - Claim tokens take `quantity_mode`/`configured_quantity` from the current config (`troop_training_bluestacks.py:1642-1656`).
  - Quantity itself correctly uses `prior_batch_quantities`.
  - After a mode change, a pending batch would be presented to Core with the wrong profile's tokens.
- **C4 (SV): UNKNOWN cannot be resolved by a new key.**
  - Any consequential `prepared`/`input_sent`/`unresolved` row blocks the next session before input (`base_route_native_runtime.py:475-476`) and every capability request (`troop_training_bluestacks.py:1361`, `safe_action_core/store.py:1365-1368`).
  - Within a reset, an existing row at the candidate generation blocks that variant (`automation_service/troop_training.py:228-229`).
  - Resolution is `pnsctl reconcile`: positive postcondition or proven no-effect (`scripts/pnsctl.py:295-346`).
- **C5 (SV): a non-canonical (manual) queue blocks a fixed-quantity variant.**
  - With no pending canonical key, fixed mode expects `config.quantity` (`tasks/troop_training.py:543-544`); current_max accepts the observed quantity read-only (:545-548).
  - A completed non-canonical queue stops the visit: "completed legacy/unknown queue requires manual reconciliation" (`troop_training_bluestacks.py:1619-1620`).
  - The Nov 9 manual queues (Fighter/Vehicle x1510, Shooter/Rider x250; HE, #67) are therefore likely to block the first development visit. That blocking is the correct fail-closed outcome for an external change; the owner decides what happens next (section 6).
- **C6 (SV): the preset is required on the start path.** Start tokens carry `saved_commander_talent_preset_verified=true` (:2187-2188), and `_ensure_training_preset` runs before each start (:2195). Reuse of same-visit Applied proof without a redundant Apply is #95's contract (HE: native Training Applied reconciled). Nothing here requires a tree edit or Reset.
- **C7 (SV): provenance hash used as scene validity.** The navigation wrapper's `authorize` raises "navigation frame changed before input" whenever the recaptured `before` hash differs from the planning source (:168-170). The only exception is the owned commander-talent Back rebind (:171-175). On animated surfaces this stops navigation by design. HE: the reverted consolidation hit the animated-Home variant of this.

## 3. Minimal ordered implementation plan

Each step lists what changes and why. No new module, registry, DSL, wrapper or DB.

1. **Accounting: classify, don't move counters.** Files: `scripts/bluestacks_native_runtime.py`, `scripts/navigation_development_boundary.py`, `scripts/base_route_native_runtime.py`.
   - **Native runtime.** In `_authorize_dispatch`, raise one typed `RuntimeError` subclass (e.g. `DispatchNotAdmitted`) for every refusal *before* `self.input_count += 1` (:405-436 and the delegated `reserve_input` failure). Subclassing keeps existing `except RuntimeError` callers working. In `_dispatch_transport`, add a `transport_returned` / `transport_raised` event after the runner call. This is a transport *outcome*, not delivery proof.
   - **Session.** `DevelopmentSession.run_action` keeps its pre-dispatch `input_count += 1` (the attempted count; still budget-consuming, never rolled back). On exception it appends the outcome to `actions.jsonl`:
     - `not_admitted` for a typed `DispatchNotAdmitted`;
     - `transport_uncertain` for anything else.

     Then it re-raises. The session exposes `not_admitted_count`. The existing `delegated.mark_transported` / `mark_reconciled(unresolved=True)` calls stay unchanged.
   - **Native boundary.** `_accounting_snapshot` verifies `session.input_count == runtime.input_count + session.not_admitted_count`. `input_count` stays the conservative attempted total. `NativeExecutionAccounting`/`NativeRouteOutcome` gain `not_admitted_count`. Every route using the shared boundary gets this together; no per-route copy.
   - **Why:** this turns the A3/A4 false "inconsistent" into an explained pre-admission refusal while still charging the attempt to budgets. Any unexplained gap stays unverified.
   - **Unchanged:** `TroopTrainingRunner`, service `record_consumption`, the unverified-accounting refusal, and `max(...)` conservatism in `_execute_canonical_action`. A `DispatchNotAdmitted` raised inside a consequential `run_action` must map to `TransportResult(False, ...)` only when the runtime delta is 0 *and* the exception is that type. All other cases keep today's possibly-sent UNRESOLVED path.
2. **One closed development profile, selected by the controller.** Files: `tasks/troop_training.py`, `automation_service/cli.py`, `scripts/pnsctl.py`, `automation_service/service.py`, `automation_service/troop_training.py`, `scripts/troop_training_bluestacks.py`.
   - **Profile constant.** Add `development_troop_training_config()` next to the production defaults:
     - Fighter T8 fixed 2;
     - Shooter T8 fixed 2;
     - Rider T1 fixed 10;
     - Vehicle T1 fixed 10.

     All four `allow_resource_boxes=False`, with a repeat policy that behaves like `continuous` (claim then start next generation). Do not overload Shooter/Rider's production `once_daily`.
   - **Input channel.** Add one enumerated serve option (e.g. `--training-profile {production,development}`, default production) on the existing serve CLI and its `pnsctl` pass-through. `serve` passes it to the runner. `TroopTrainingRunner` passes it as `NativeRouteRequest.arguments={"training_profile": ...}` only for that value set.
   - **Native.** `run_troop_training_native` accepts exactly that key and value set (replacing the blanket rejection at :2721-2722) and builds the config from the closed constant (replacing :2769). The route never receives raw quantities.
   - **Bounds.** Reuse the existing serve session, singleton, lease and `MAX_INPUTS`/`MAX_ACTIONS`.
   - **Why:** this gives a single trusted source with no route self-authorization of arbitrary values.
3. **Core: closed tables, profile-bound tokens.** File: `safe_action_core/approved_base_routes.py`; with `_NATIVE_SEMANTIC_REVISION` and `TROOP_TRAINING_REVISION` bumped together.
   - **Start.** Add a `training_profile=<production|development>` token to start and claim preconditions. Select the variant tuple from a two-entry closed mapping. For development, require `quantity_mode=fixed`, `selected_quantity == configured_quantity` (2/2/10/10), `selected_quantity <= quantity_maximum`, `allow_resource_boxes=false`, and a development cumulative-cap check (step 5).
   - **Claim.** The profile and configured tokens must describe the *batch's original start* (step 4), not the current mode.
   - **Why:** Core currently rejects every dev start (B3). A closed table keeps Core's "no arbitrary caller settings" property. Core still trusts route-supplied counts, exactly as today. The controller choice is enforced at the runner/native boundary and is auditable in `policy_request_json`.
   - **Unchanged:** the production table and its 250/once_daily rules.
4. **History: derive per-batch original facts from persisted tokens.** File: `automation_service/troop_training.py::derive_training_action_state`.
   - **Per-batch facts.** For each confirmed pending start, parse `policy_request_json.semantic_preconditions` into the batch's `training_profile`, tier, mode, configured and selected quantity. Rows without a profile token are production (they could only pass the production table). Rows missing or carrying contradictory tokens raise `TrainingActionHistoryError`, the existing manual-reconciliation path.
   - **Replace the universal 250 with a profile-scoped one.** The check at :214-215 becomes: a *production*-profile Shooter/Rider batch must still have quantity 250, unchanged; a *development*-profile batch must equal its recorded configured quantity (2 or 10). A batch whose decoded profile, quantity and tokens disagree fails closed.
   - **Split counts.** Split `start_counts` and `prior_daily_initiations` by profile: production once_daily uses *production-profile* starts only; development uses its own count.
   - **Extend state.** Add per-pending-batch facts to `TrainingActionState` (replacing the bare `prior_batch_quantities` mapping, so there is one source).
   - **Callers to update together:** native entry (:2748), post-claim re-derivation (:1742), `pnsctl._troop_training_recovery_history`.
   - **Obsolete test.** Remove or replace `test_pending_daily_batch_rejects_stored_quantity_other_than_250` with the consumer-visible invariant "pending batch is reconciled under its own recorded quantity".
   - **Why:** this covers B4, C1 and C3, and makes the production projection explicit: a dev Shooter2 is real spend and a real pending queue, but it never satisfies production once_daily.
5. **Cumulative development bound from history.** Count persisted development-profile starts per variant per reset (all countable statuses) in step 4. Pass the count as a token and have Core deny at the closed cap.
   - **Why:** small batches may complete quickly. Per-visit `MAX_ACTIONS` and the timer cadence are not a cumulative spend bound.
   - **Owner decision:** the cap value (section 6). No new store.
6. **Controller/route uses batch facts for reconcile and claim.** Files: `tasks/troop_training.py` (`reconcile_active_queue`, `plan_claim`, `reconcile_claim`) and `troop_training_bluestacks.py::_claim_completed_tab` / `_train`.
   - **Batch facts, not current config.** Validate active and completed canonical queues against the pending batch's recorded tier and quantity, not `config`, and emit claim tokens from them.
   - **Generalize fixed-mode checks.** Replace the native fixed-250 check (:2123-2126) with "selected equals the active profile's configured quantity within capacity". Under the production profile that is still exactly 250, and Core's production table keeps enforcing it.
   - **Non-canonical queues fail closed in the development profile.** For a non-canonical active or completed queue: no adoption as a canonical batch, no claim identity, and no new start on that camp. Report it as an external/manual change that needs owner reconciliation. Production's existing branches stay unchanged: current_max observes the queue read-only, fixed mode blocks, and a completed unknown queue stops the visit.
   - **Dev tiers.** Keep dev tiers identical to production. The pending-batch tier checks then stay consistent across mode changes, and that equality is an explicit invariant of the profile.
7. **Service projection.** File: `automation_service/service.py` Training branch (:1402-1423).
   - When the result's `training_profile` is development, normalize `completed`/`partial` to `DEFERRED` with the `troop_training_next_due` timer. This follows the existing maintenance precedent (:1356-1371), and the reason code must not be the production `PASS_VERIFIED`.
   - Persist `training_profile` in the result payload so `observed_progress` records it.
   - **Unchanged:** the production branch.
8. **Do not add Training to `operator_request_id`.** Leave `service.py:851-855` and `state.py:2736-2756` as is (B5). Successive same-reset cycles come from the timer-due re-claim under one supervised serve session.
9. **Out of scope for this cut:** Fighter/Vehicle box continuation (stays denied by Core, :1095-1099; the dev profile sets boxes false); warehouse; premium; speedups; queue cancellation; inventory or quest census.

## 4. Safety and transition matrix

| Case | Existing protection (SV) | Required behavior | Gap |
| --- | --- | --- | --- |
| Pre-admission rejection | Runtime refuses before its count (`bluestacks_native_runtime.py:416-436`); the run fails "inconsistent accounting" | Typed `not_admitted`; attempt still charged; accounting verified only if `session == runtime + not_admitted` | No typed reason today; a safe refusal becomes an unverifiable run (A4) |
| Uncertain transport | Possibly-sent → Core UNRESOLVED; global `has_action_block` before the next session; no identical key | Unchanged; `pnsctl reconcile` with evidence only | No post-transport journal event (step 1); no physical-delivery proof exists or is claimed |
| Busy queue | `reconcile_active_queue` read-only for canonical batches; due = projected completion | Same, using decoded batch facts | Non-canonical queue in fixed mode blocks the visit (C5); keep that and surface it as an external change |
| Original-quantity pending work | Quantity from `row.quantity`; key keeps original reset | Profile, tier and mode from `policy_request_json`; claim tokens from the batch | Dev Shooter/Rider rejected by history (B4); claim tokens use the current config (C3) |
| Completed claim | Core exact `<start>:claim`; post-claim re-derivation must show no pending and the same generation (:1742-1755) | Same | Once_daily skips restart after claim (:2421-2423): correct for production; dev needs the continuous-like path |
| Subsequent same-reset generation | Next key = max confirmed + 1; candidate already present → blocked for the reset | Same; plus dev cumulative cap | A cancelled or blocked row at the candidate generation blocks that variant for the rest of the reset (:228-229); keep as is, ER whether it occurs |
| Prod ↔ dev mode change | None profile-aware | Pending batch reconciled and claimed under its original profile; production once_daily counts production starts only | B4/C3/step 4 |
| Reset / restart | Keys and counts are rebuilt from SafetyStore each visit; global UNKNOWN block | Unchanged | none beyond the above |
| Exhausted session / retry window | `max_attempts`/`retry_not_before`, block on exhaustion (`state.py:2757-2766`); audited inspect/rearm (carryover) | Unchanged; no limit increase or history clearing | A4 inflates failures with explainable refusals until step 1 lands |
| External or manual change | Non-canonical active queue in fixed mode → blocked; unknown completed queue → manual reconciliation (:1619-1620); preset re-verified via #95 helper; REA recovery guard in `pnsctl` | Unchanged fail-closed stop, reported as an external change; owner reconciles; no adoption or fabricated rows | Nov 9 manual queues (HE) likely hit this first; owner decision |

## 5. Verification split

**Before any effect: existing focused offline checks only.**
- **Training:** `tests/test_service_troop_training.py`, `tests/test_troop_training.py`, `tests/test_troop_training_entry.py`, `tests/test_training_disabled.py`.
- **Core:** the Training cases of `tests/test_approved_base_route_policy.py`.
- **Native boundary and session:** `tests/test_native_execution.py`, `tests/test_development_session.py`, `tests/test_navigation_development_boundary.py`, `tests/test_bluestacks_native_runtime.py`.
- **Inspection, CLI and contracts:** `tests/test_inspected_retry_admission.py`, `tests/test_pnsctl_canonical_serve.py`, `tests/test_service_route_contract.py`.

Only edit tests whose contract the cutover deliberately changes (B4's 250 test; accounting-equation expectations). Required consumer-visible invariants:
- a pending batch is reconciled under its own recorded facts;
- a dev start never satisfies production once_daily;
- a typed pre-admission refusal verifies while any other mismatch does not;
- UNKNOWN still blocks;
- production tokens are unchanged.

These are the assignment's pre-effect safety gates. They are not native acceptance.

**Live-capable observations (implementer, under current authorization):**
1. Non-consuming prewalk per camp, stopping before Train:
   - Training Applied (no redundant Apply);
   - current queue state of each camp, canonical or manual;
   - tier card selection;
   - the editor accepting `2` and `10` with OCR readback, then OK;
   - exact four-resource cost for each small batch;
   - displayed duration.
2. Canonical run, observed:
   - for each variant, one start with an active-queue label showing tier and quantity (`duration_source=queue_band`);
   - actual cost debit and timer;
   - positive completion seen in-game, not inferred from elapsed time;
   - exact claim and post-claim queue-empty successor;
   - **a subsequent same-reset generation** (g+1) start;
   - terminal Home;
   - accounting verified;
   - controls OFF.
3. Record per-stage timings, including dispatch-frame age (the stale-frame rejection is a candidate cause), actual durations and costs. Mock passes and timer projections are not acceptance. Permanent regressions come only from observed failures and retained captures.

## 6. Live-agent handoff

- **Provisional (UI?), must be observed before relying on them:**
  - single-digit OCR of `2` in the editor and two-digit `10`;
  - queue-band label parsing of small quantities;
  - whether a claim returns the tab to a recognized empty state that permits an immediate next Train in the same visit;
  - small-batch durations (no near-instant assumption);
  - animated-scene tolerance of the hash-equality navigation authorize (C7), which needs route-owned predicate rebinding like the existing talent-page exception, never blind coordinates or whole-screen OCR;
  - the actual cause of the historical 7/8 mismatch (ER).
- **Owner decisions (bounded):**
  1. The development cumulative cap per variant per reset (step 5) and the session's ordinary-resource/time bounds.
  2. How to handle the Nov 9 manual queues. Options: owner-claims manually outside automation with automation paused and records it, or waits for production-mode observation. No fabricated canonical start rows.
  3. Whether to enable the supervised serve session for Training under the development profile. This is required for timer re-claims, because `serve` requires the service to be enabled.
  4. Any expansion to boxes, premium or speedups (currently excluded).
- **Prewalk discipline:** preserve each camp's consuming opportunity. Do not start, claim or cancel during the prewalk. Do not switch routes when blocked; retain the prefix and report.
- **Remaining gaps after scoped dev success:**
  - production-size qualification: Shooter/Rider 250 once_daily, Fighter/Vehicle current-max continuous;
  - box continuation;
  - multi-reset and durability cases;
  - #95 Economy Apply.

  Development success is reported separately and never as production acceptance.
