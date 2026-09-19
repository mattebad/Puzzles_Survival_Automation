# Foundation recovery backlog

Planning-only records for the canonical `automation_service` recovery. These records do not activate a flow, authorize transport, mutate evidence, or replace the historical backlog. `READY` means eligible for a later offline implementation prompt only; every ticket below is inactive.

## Cross-ticket controls

- **Dependency rule:** Dependencies below use only the new `REC-F##` IDs. Historical task IDs are intentionally confined to Related work.
- **Evidence rule:** Full-frame hashes, payload digests, and filenames identify provenance/cache entries. They do not by themselves establish a live screen, target, semantic successor, or effect. Stable semantic ROIs, capture-event identity, and current typed observations are the authority.
- **Shared-wave mutex:** Exact realpath overlap in source *and test* files prevents concurrent assignments, not merely serial merges. `REC-F01`, `REC-F02`, and `REC-F03` overlap on `automation_service/screens.py` and shared boundary tests, so they MUST NOT be assigned concurrently; the integration owner computes exact source/test overlap before dispatch. `REC-F02`/`REC-F17` are likewise serialized around the OCR seam and callers. `REC-F05`/`REC-F07`/`REC-F09`/`REC-F14`/`REC-F15` overlap `automation_service/state.py`, `automation_service/scheduler.py`, `automation_service/service.py`, `automation_service/cli.py`, and shared tests; `REC-F06`/`REC-F09`/`REC-F13` overlap registry/service and World registration hunks. Only path-disjoint assignments may share a wave; semantic dependencies still take precedence.
- **Route safety:** Future coding PRs use fake/replay adapters and zero transport. Native promotion, scheduler enablement, and production registration are separate Operations tickets; old native evidence is historical context, never current acceptance.
- **Runtime authorization:** These records forbid live/production claims, reservations, transport, enablement, and production-state mutation. The orchestrator MAY permit isolated fake/replay adapters and temporary SQLite state for offline behavioral tests only; such state MUST be unreachable from production and MUST NOT be reported as a live or production claim, reservation, or observation. A ticket-local `Runtime authorization: none` line means no live/production authorization and does not prohibit those orchestrator-controlled fake/temp-state tests.
- **Schema/API completeness:** Preserve the existing 19-field ticket structure. Every new or changed runtime API or schema field must name its consumers in the same PR or integration lock; no “wire later” follow-up is complete.

## Governance gate allocation (all 38 plan gates)

1. F09,F16; 2. F04,F09,F16; 3. F01,F10,F11,F17; 4. F01,F09,F10; 5. F07,R01,F16; 6. F03,F10,F11,F16; 7. F03,F04,F09,F16; 8. F07,D02; 9. F09,F16; 10. D03,D04; 11. F04,F09,F14,F16; 12. F09,F15; 13. F09; 14. F09,F15,O08; 15. F04,F09,F15; 16. F09,F10,F16,O08; 17. F02,F03; 18. F01,F08,F09,F15; 19. F09,F16; 20. F04,F09,F16; 21. F04,F09,F16; 22. F09,F16; 23. F01,F10,F11,F17; 24. F01,F11; 25. F03,F09,F11,F16; 26. F02; 27. F07,F16; 28. F07,F09,F16; 29. F07,F14; 30. F07,F14; 31. F14,F16; 32. F07,R01,F16; 33. F01,F08,F09; 34. F09,F14,F16; 35. F14,F15,O11; 36. R01,F16; 37. F05,F09,F15; 38. F06,F13,F17,O12,O13,O14.

## Actual prior audit finding allocation (AF01–AF14)

- **AF01 — legacybypass:** Legacy `pnsctl`/direct runner, lease, receipt, and registration paths could remain an authority or transport bypass -> F13 and Operations O12–O14.
- **AF02 — selectorsuccess:** A static selector/registration snapshot could persist `SUCCEEDED` with `actions=0` and consume an occurrence -> F06.
- **AF03 — contradictoryscreens:** Contradictory recognizers could resolve to a concrete screen instead of typed `UNKNOWN` -> F01.
- **AF04 — OCRlifetime:** An OCR timeout returned while its worker callback remained alive -> F02.
- **AF05 — unknownoverlay:** A VIP/modal successor with `UNKNOWN` overlay state could be accepted -> F03/F11.
- **AF06 — resourceparity:** Resource-effect occurrence, quantity, reserve, `UNKNOWN`, delta, changed-hypothesis, and crash parity remained unproven -> Resources R01 and F16.
- **AF07 — deniedlease:** A denied explicit-owner session retained a lease acquired during its admission attempt -> F04.
- **AF08 — shadowmutates:** Public shadow/observe initialized or mutated flow state while reporting candidates -> F05.
- **AF09 — RESET_BOUNDED:** `RESET_BOUNDED` repeat limit `5` permitted only the first occurrence rather than durable bounded ordinals -> F07.
- **AF10 — realservice/no service-adapters-health:** The canonical real service loop, guarded adapters, and coherent lease health were absent or not authoritative -> F09/F10/F14/F15.
- **AF11 — duplicatedstartup/startupownership:** Duplicate startup/Home/Back/VIP ownership allowed route-local recognizers to compete with the shared composition -> F11.
- **AF12 — duplicatedOCR/fullframe/repeatedOCR:** Direct OCR callers and broad/full-frame or repeated OCR paths bypassed one bounded identity-bound seam -> F02/F17.
- **AF13 — ADSfilenames:** Colon/NTFS alternate-data-stream filename handling could leave misleading zero-byte base files and non-portable evidence names -> F08.
- **AF14 — policy conflict/policyidentityconflicts:** Conflicting product/policy identities and outcomes remained unresolved rather than being attributed to the wrong route -> Daily D01 and Resources P01–P12.

These AF identifiers name the fourteen defects above. Positive historical observations are context-only `EV-*` references and MUST NOT be substituted for an actual finding.

### REC-F01 — Fail-closed screen ambiguity and immutable capture provenance
- Task ID: `REC-F01`
- Type: Bug
- Priority: P0
- Status: READY
- Objective: Make screen and target admission fail closed when authoritative ROIs, capture-event identity, or immutable payload provenance are missing, contradictory, stale, or cross-capture; permit animation variance without mistaking a full-frame hash for semantic authority. This addresses AF03 and the observed distinction between `CaptureCycle.frame_hash` and stable bindings.
- Dependencies: none
- Related work: `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE` — reuse its same-capture immutable bundle and dual-digest facts; `RUNTIME-RESUMABLE-NAVIGATION-SESSIONS` — retain its fresh-continuation rule; `HOME-ATLAS-LOCALIZATION-RESTORATION` — retain as an inactive Home outcome and do not activate its Campaign/AP path.
- Evidence: `automation_service/screens.py:CaptureCycle,TargetBinding,ScreenObservation,ScreenRouter.revalidate`; `automation_service/temporal.py:CaptureProvenance,TemporalObservation`; `tests/test_automation_service_boundaries.py` already covers distinct animation hashes, changed source/target ROI, deadline, and typed unknown; `tests/test_automation_service_temporal.py` covers duplicate, cross-session, stale, and negative evidence. AF03 found contradictory recognizers returned `HOME` rather than `UNKNOWN`.
- Scope: `automation_service/screens.py`, `automation_service/temporal.py`, `tests/test_automation_service_boundaries.py`, `tests/test_automation_service_temporal.py`
- Changes: Preserve immutable capture ID, session/ordinal, native dimensions, payload/transport digest, semantic digest, and stable-ROI digest as separate fields. Reject mutable or cross-capture observation payloads, contradictory authoritative screen/overlay/target facts, stale source or target ROIs, and incomplete target identity. Permit two frames with different full hashes when authoritative semantic ROIs agree. Keep provenance/hash checks necessary but insufficient for authority; require current typed rebind before dispatch and invalidate caches after input.
- Non-goals: No new recognizer, OCR engine, route migration, evidence rewrite, native capture, or full-frame-hash equality shortcut; no Campaign retry and no change to the inactive Home localization record.
- Acceptance: (1) Cross-capture, mutable-payload, contradictory-screen, stale-source, and changed-target cases return typed `UNKNOWN`/blocked and cannot produce an input-capable target. (2) Two animation-variant frames with distinct full hashes recognize when stable authoritative ROIs match. (3) A digest-only match, filename, timestamp, or cached observation cannot pass `revalidate`. (4) Invalid/ambiguous observations release or never acquire runtime ownership through the caller contract.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_automation_service_boundaries tests.test_automation_service_temporal`; use existing temporary/fake observations only, with no device or protected evidence.
- Native gate: none for this offline contract; any later route use remains fake/replay-only until the separately assigned Operations native gate.
- Integration owner: F11 owns shared screen/overlay composition hunks; F10 owns adapter capture identity. Additional consumer hunks are `scripts/startup_surface_recognition.py:recognize_scarlett_three_day_pack`, `scripts/startup_recovery.py:recover_known_startup_overlay`, `tasks/home_atlas_vision.py:BlueStacksHomeLocalizer.localize`, and `scripts/world_map_navigation_bluestacks.py:recognize_world_frame`; serialize those integrations and do not add a second recognizer.
- PR boundary: one future offline PR titled `fix(runtime): fail closed on ambiguous frame provenance`, branch `recovery/rec-f01`; code/test paths are limited to Scope plus explicitly reviewed integration hunks.
- Rollback: Disable all affected flow rows and the global SQLite gate if a boundary regression appears; retain historical evidence and never restore a legacy bypass.
- Runtime authorization: none; zero transport, zero claims, zero reservations, zero native observations.
- Completion: Offline tests demonstrate immutable same-capture composition, honest animation variance, and fail-closed ambiguity; no eligibility or retry state is derived from hashes/evidence alone, and no runtime/native readiness is implied.

### REC-F02 — Enforce bounded, terminating ROI OCR workers
- Task ID: `REC-F02`
- Type: Bug
- Priority: P0
- Status: READY
- Objective: Ensure every OCR invocation runs in a bounded, enforceable worker process over an explicitly bounded ROI, with the process terminated and reaped by its deadline, and cannot fall back to an abandon-daemon or broad full-frame OCR path. This closes AF04 and AF12 and covers governance gate 26.
- Dependencies: none
- Related work: `VISION-SEMANTIC-OCR-CROP-PIPELINE` — reuse its identity-bound ROI and constrained OCR contract; `VISION-NATIVE-FRAME-REPLAY-HARNESS` — reuse deterministic non-live frames; `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE` — retain same-capture identity.
- Evidence: `automation_service/screens.py:ScreenRouter._call/_recognize_entry` currently starts a daemon thread and `join`s only until a deadline; `scripts/daily_row_claim_bluestacks.py:_default_ocr/_ocr_tokens`; `scripts/world_map_navigation_bluestacks.py:_ocr_hits/_footer_navigation_ocr_hits/_ocr_text_in_roi`; `tests/test_automation_service_boundaries.py:test_ocr_is_not_called_after_deadline` checks admission but AF04 observed the callback still alive. Existing direct `pytesseract` callsites and broad/repeated OCR paths are enumerated under F17 for AF12.
- Scope: `tasks/semantic_ocr_crop.py`, `automation_service/screens.py`, `automation_service/temporal.py`, `tests/test_automation_service_boundaries.py`, `tests/test_automation_service_temporal.py`
- Changes: Extend and reuse the existing `tasks/semantic_ocr_crop.py` identity-bound crop seam; do not create a generic OCR pipeline. Define one bounded contract carrying parent capture identity, exact ROI, mode, and monotonic deadline. Run OCR in a bounded worker process whose actual OS process lifetime is observable; at the deadline terminate the process, escalate termination if needed, and wait/reap it before returning. Returning before worker termination, detaching it, marking it orphaned, or relying on a caller timeout while the process remains alive is not an acceptable substitute, and any late result is rejected. Return `UNKNOWN/OCR_DEADLINE`; reject empty, oversized, or full-frame fallback ROIs; invalidate results after frame/deadline changes. OCR text remains recognition evidence, never dispatch authority.
- Non-goals: No broad OCR accuracy tuning, fuzzy matching, live ADB, platform calibration, evidence capture, or route adoption beyond the shared seam; do not hide a still-running process behind a shorter caller timeout.
- Acceptance: (1) A deliberately blocked OCR worker process is terminated and reaped by the declared deadline; verification checks the actual OS process is no longer live after return, not merely an admission flag, and no late result can mutate state. Returning while the process remains alive or merely marking/ignoring it fails this condition. (2) Timeout returns a typed fail-closed result and prevents target binding/dispatch. (3) ROI, mode, capture identity, and deadline are validated; full-frame fallback is rejected. (4) A new frame cannot consume a late result from an older frame. (5) All tests use deterministic fake/replay data and zero transport.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_automation_service_boundaries tests.test_automation_service_temporal`; add a deterministic worker-lifetime probe to the existing focused module if coverage is insufficient (NEW test code only within that existing path).
- Native gate: none for offline implementation; no OCR native run is authorized. Later route adoption requires O10 per-route evidence, not old OCR output.
- Integration owner: F02 owns only the shared bounded seam (`tasks/semantic_ocr_crop.py`, `automation_service/screens.py`, `automation_service/temporal.py`) and its focused tests. F17 is a separate later adoption ticket that inventories and migrates remaining direct callers only after F02; its explicitly listed consumers are held in this integration lock without claiming they are fixed by F02. F11 owns popup/startup composition; exact F17 consumer paths include `scripts/bluestacks_popup_recognition.py`, `scripts/startup_surface_recognition.py`, `tasks/home_atlas_vision.py`, `tasks/campaign_auto_battle_vision.py`, and `tasks/nova_praise_vision.py`; no caller may introduce a second worker/pipeline.
- PR boundary: one future offline PR titled `fix(vision): enforce bounded OCR lifetime`, branch `recovery/rec-f02`; only Scope paths. Consumer contracts are explicitly held in the F02/F17 integration lock, but no F17 adoption is claimed or merged by this PR.
- Rollback: Disable affected recognition/flow rows and global service gate; do not restore daemon or full-frame fallback behavior.
- Runtime authorization: none; zero transport and zero persistent state mutation.
- Completion: The shared OCR seam has a bounded ROI/deadline/lifetime contract, late results are harmless, timeout is fail closed, and no F02 code PR claims native readiness.

### REC-F03 — Reject unknown or contradictory overlay successors
- Task ID: `REC-F03`
- Type: Bug
- Priority: P0
- Status: READY
- Objective: Make the shared overlay recovery successor contract reject unknown, contradictory, or overlay-bearing post-close observations and accept only an independently classified allowlisted base screen. This addresses AF05 and the VIP ownership failure.
- Dependencies: none
- Related work: `VIP-GET-PTS-POPUP-DISMISSAL` — retain its missing-fresh-evidence disposition; `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE` — reuse same-capture binding; `HOME-ATLAS-RECOVERY-AWARE-VIEWPORT-PLANNING` — retain projection as non-authorizing recovery planning.
- Evidence: `automation_service/overlays.py:OverlayPolicy,OverlayRecoveryPlan.accepts_successor,OverlayRecoveryManager`; `automation_service/screens.py:ScreenObservation`; `scripts/world_map_navigation_bluestacks.py:SafePopupHandler,recognize_allowlisted_popup`; `scripts/startup_recovery.py:recover_known_startup_overlay`; `tests/test_startup_recovery.py` and `tests/test_world_map_navigation_bluestacks.py` exercise VIP/unknown recovery. AF05 found a VIP successor with `UNKNOWN` overlay accepted.
- Scope: `automation_service/overlays.py`, `automation_service/screens.py`, `tests/test_startup_recovery.py`, `tests/test_automation_service_boundaries.py`
- Changes: Require popup presence and exact close target on the bound source, at most one close, explicit overlay absence, and independent successor classification in the same recovery contract. Permit only declared base-screen successors (including Home when popup appeared over Home), reject `UNKNOWN`, contradictory screen/overlay, stale/cross-capture, missing target, and ambiguous close. Return blocked/recovery-required without another blind input.
- Non-goals: No popup transport implementation, route-local popup detector, automatic retry, or requirement that every popup close land on Daily; no native validation.
- Acceptance: (1) VIP/known-modal source without exact current target is blocked. (2) One exact Close maximum is allowed and the post-close frame must be independently recognized with required overlays absent. (3) Unknown/contradictory successor yields blocked and zero follow-up input. (4) Home and Daily are distinguished by the declared policy rather than an assumed selected-Daily successor.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_startup_recovery tests.test_automation_service_boundaries tests.test_vip_points_popup`; fake frame sequences only.
- Native gate: none; future live dismissal is separately assigned to F11/O08/O10 and remains disabled.
- Integration owner: F11 owns `automation_service/screens.py`, `automation_service/context.py`, and `scripts/startup_recovery.py`; World integration must serialize `scripts/world_map_navigation_bluestacks.py:SafePopupHandler` and Daily integration must remove its private successor assumption.
- PR boundary: one future offline PR titled `fix(runtime): reject unknown overlay successors`, branch `recovery/rec-f03`.
- Rollback: Disable overlay-using flows and global gate; preserve popup evidence and never restore blind close/retry.
- Runtime authorization: none; zero transport, reservation, claim, or native observation.
- Completion: Shared recovery is typed, one-close, successor-allowlisted, and fail closed for unknown/contradictory overlays with no native or enablement implication.

### REC-F04 — Release only the exact newly acquired lease on denied claim
- Task ID: `REC-F04`
- Type: Bug
- Priority: P0
- Status: READY
- Objective: Make denied or invalid RuntimeSession admission release only the exact service/run lease acquired by that attempt, while refusing to release another owner’s lease and guaranteeing release on every terminal/error path. This addresses AF07.
- Dependencies: none
- Related work: `RUNTIME-RESUMABLE-NAVIGATION-SESSIONS` — retain crash-safe ownership identity; `RUNTIME-INPUT-CAPABILITY-FIREWALL` — retain one-shot authority boundaries; `RUNTIME-RELIABILITY-MERGE-BOUNDARY` — retain historical merge boundary only, not runtime authority.
- Evidence: `automation_service/state.py:ServiceLease,BotStateManager` and existing lease CAS methods; `automation_service/session.py:RuntimeSession,SessionFence`; `automation_service/actions.py:ActionExecutor._release_after_emergency`; `tests/test_automation_service_state.py` covers owner/run tokens, takeover, emergency stop, and orphan recovery. AF07 found a denied explicit-owner session retained an acquired lease.
- Scope: `automation_service/state.py`, `automation_service/session.py`, `tests/test_automation_service_state.py`, `tests/test_automation_service_boundaries.py`
- Changes: Use the existing owner instance, process-start token, lease generation, and run token fields with the existing compare-and-swap lease cleanup; record whether this denied session acquired or merely borrowed the lease. On failed admission, CAS-release only a matching newly acquired lease; on mismatch or a borrowed lease, leave the current owner intact and return structured denial. Preserve idempotent close, exception, emergency-stop, terminalization, and rejected-dispatch cleanup without introducing a new immutable capability framework, lease policy, force-release, or takeover shortcut.
- Non-goals: No lease policy redesign, scheduler selection, native transport, force-release, stale-owner takeover shortcut, or legacy lease reactivation.
- Acceptance: (1) Negative borrowed-session regression: a denied session that did not acquire the current lease cannot release or alter another owner’s lease. (2) Positive acquired-session regression: a denied attempt that acquired the exact lease releases that row exactly once. (3) Owner/process/lease/run generation mismatch fails closed and preserves the current owner. (4) Existing close, exception, emergency-stop, terminalization, and orphan regressions remain ownership-safe without a new lease abstraction.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_automation_service_state tests.test_automation_service_boundaries`; use temporary SQLite databases and competing fake owners only.
- Native gate: none; no adapter or device action.
- Integration owner: F09 consumes the lease/run token API in `automation_service/scheduler.py` and `automation_service/service.py`; F15 consumes status/health output in `automation_service/operations.py` and `automation_service/cli.py`. Merge shared state changes serially.
- PR boundary: one future offline PR titled `fix(runtime): fence denied lease release`, branch `recovery/rec-f04`.
- Rollback: Disable global service and all rows; preserve the current lease owner and do not fall back to legacy lease control.
- Runtime authorization: none; zero transport and zero persistent production state mutation.
- Completion: Exact ownership release is proven with CAS/fence tests; a denied claim cannot leak or steal a lease and native readiness remains unclaimed.

### REC-F05 — Keep public shadow scheduling initialization-free and mutation-free
- Task ID: `REC-F05`
- Type: Bug
- Priority: P0
- Status: READY
- Related work: `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION-FINAL-READINESS` — retain its offline review boundary; `ARCH-NAVIGATION-AUTOMATION-ROADMAP` — reuse the dormant-contract principle.
- Objective: Make every public shadow/observe path compute candidates without initializing flow rows, consuming occurrences, inserting runs/actions, advancing due/retry state, acquiring a transport-capable lease, or mutating production SQLite. This addresses AF08 and governance gate 37.
- Dependencies: none
- Evidence: `automation_service/service.py:AutomationService.observe,pulse,shadow`; `automation_service/scheduler.py:_CanonicalPulseCoordinator.shadow`; `automation_service/cli.py:main` shadow command; `tests/test_automation_service_canonical_authority.py:test_shadow_selection_is_mutation_free` and disabled-state tests. AF08 observed public shadow initializing `0` to four flow rows.
- Scope: `automation_service/service.py`, `automation_service/scheduler.py`, `automation_service/cli.py`, `tests/test_automation_service_canonical_authority.py`
- Changes: Separate read-only shadow from initialization and selection mutation. Shadow may read an already-valid canonical database or an isolated temporary database that can never be consumed by production; it must report candidate, due/reset/retry/starvation/health reasoning without `claim`, action reservation, occurrence advance, lease acquisition, or handler start. `observe` remains structurally zero-input.
- Non-goals: No scheduler fairness redesign, route implementation, database migration, queue cleanup, or production enablement; shadow must not use contradictory queue state as authority.
- Acceptance: (1) Empty-path shadow leaves tables and files absent/unchanged rather than seeding rows. (2) Existing-state shadow leaves service/flow/run/action/lease/clock rows byte-for-byte semantically unchanged. (3) Candidate has no claim/run/action side effect and handlers are not started. (4) Observe cannot reserve, claim, enable, or schedule. (5) A shadow database cannot be read by production scheduling.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_automation_service_canonical_authority tests.test_automation_service_cli tests.test_automation_service_scheduler_canonical`; temporary SQLite diff only.
- Native gate: none; fake/replay observation only and zero transport.
- Integration owner: F09 owns shared scheduler/state mutation boundaries; F15 owns CLI command routing; F14 owns service-loop shadow invocation. Shared paths `automation_service/state.py`, `automation_service/registry.py`, and `tests/test_automation_service_state.py` merge by mutex.
- PR boundary: one future offline PR titled `fix(scheduler): make shadow scheduling read-only`, branch `recovery/rec-f05`.
- Rollback: Stop global service and disable rows; discard only an unused isolated shadow database, never restore a second live scheduler.
- Runtime authorization: none; zero transport, claims, reservations, leases, and state mutations.
- Completion: Public shadow/observe is provably mutation-free and initialization-free while preserving candidate diagnostics and all historical evidence.

### REC-F06 — Prevent selection-only handlers from consuming gameplay occurrences
- Task ID: `REC-F06`
- Type: Bug
- Priority: P0
- Status: READY
- Objective: Ensure selector-only and unsupported-route handlers can describe or select an eligible route without terminalizing or consuming a gameplay occurrence, consuming a registration snapshot, or reporting gameplay completion from selector evidence alone. Preserve legitimate verified real-runner zero-input already-completed/observation outcomes where the route contract permits them. This addresses AF02 and separates ordinary versus consequential route semantics.
- Dependencies: none
- Related work: `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION` — retain its blocked composition status; `ARCH-NAVIGATION-AUTOMATION-ROADMAP` — reuse typed handler boundaries; `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE` — retain typed observation facts.
- Evidence: `automation_service/handlers.py:WorldNavigationSelectionHandler,NovaPraiseSelectionHandler,RecruitmentMaintenanceSelectionHandler,CampaignApSelectionHandler`; `automation_service/registry.py:RegisteredDispatchSnapshot,consume_registered_entry`; `automation_service/scheduler.py` selection/terminal paths; `tests/test_automation_service_handlers.py`, `tests/test_automation_service_contracts.py`, and `tests/test_automation_service_canonical_authority.py`. AF02 found static World selection persisted `SUCCEEDED/actions=0/ordinal=1`.
- Scope: `automation_service/handlers.py`, `automation_service/contracts.py`, `automation_service/scheduler.py`, `tests/test_automation_service_handlers.py`, `tests/test_automation_service_contracts.py`
- Changes: Give selector-only handlers an explicit non-consuming result/plan type. Keep eligibility and descriptive projection separate from `runs`/`actions` terminal success; consume a gameplay occurrence only after the canonical real runner reports its corresponding verified action/effect, or a verified already-completed/no-op observation when that FlowSpec explicitly permits observation-only completion. Selector-only and unsupported-route results cannot use zero input as gameplay evidence. Keep ordinary Claim and milestone Claim distinct; registration snapshots cannot be treated as gameplay success.
- Non-goals: No route gameplay implementation, old registry deletion, resource-effect retirement, Campaign/AP retry, or native validation.
- Acceptance: (1) Calling every selector-only handler leaves occurrence/action counts and success state unchanged. (2) **Negative regression:** selector-only or unsupported-route input with zero actions cannot yield `SUCCEEDED`, consume an occurrence, or count gameplay solely from selection/registration evidence. (3) **Positive regression:** a canonical real-runner already-completed/no-op observation with zero input remains an accepted documented observation-only terminal where its FlowSpec permits it (offline tests represent that runner only with fake/replay data); no blanket `actions > 0` success rule is allowed. (4) Ordinary and milestone action identities cannot alias. (5) Unknown or unavailable selection remains fail closed.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_automation_service_handlers tests.test_automation_service_contracts tests.test_automation_service_canonical_authority`; temporary SQLite and fake handlers only.
- Native gate: none; no route input or native evidence.
- Integration owner: F09 owns scheduler result mapping; F13 owns World runner cutover; F06 integration must enumerate `scripts/pnsctl.py` registry consumption and `scripts/flow_delivery_world_map_bluestacks.py:register` without enabling either path.
- PR boundary: one future offline PR titled `fix(scheduler): keep selection separate from gameplay success`, branch `recovery/rec-f06`.
- Rollback: Disable affected rows and global gate; do not restore consume-once selection as success authority.
- Runtime authorization: none; zero transport and zero effect/resource mutation.
- Completion: Selector-only paths are descriptive/non-consuming; selector-only or unsupported routes cannot turn zero input into gameplay success. Where a FlowSpec permits observation-only completion, a verified canonical real-runner already-completed/no-op outcome may legitimately terminalize with zero input; no blanket `actions > 0` rule is allowed, and no route becomes enabled.

### REC-F07 — Persist bounded repeats, occurrence ordinals, retry backoff, and exhaustion blocks
- Task ID: `REC-F07`
- Type: Bug
- Priority: P0
- Status: READY
- Objective: Correct `RESET_BOUNDED` and related recurrence handling so every allowed ordinal is durable, retries reuse the same occurrence identity, exhaustion is an explicit block, and schedule cadence is separate from retry backoff. This addresses AF09 and governance gates 8, 27–30.
- Dependencies: none
- Related work: `HOME-NAVIGATION-OBSERVABILITY` — reuse persisted session timing fields; `HOME-NAVIGATION-BOUNDED-SESSION-CALIBRATION` — retain calibration independence; `RUNTIME-RESUMABLE-NAVIGATION-SESSIONS` — retain occurrence/session continuity.
- Evidence: `automation_service/contracts.py:RecurrenceClass,RecurrenceProjection,FlowSpec`; `automation_service/scheduler.py:_occurrence_binding,_projection_key`; `automation_service/state.py:FlowState,RunRecord`; `tests/test_automation_service_scheduler_canonical.py` covers recurrence keys, reset, retry, timer slots, and bounded repeat; AF09 found repeat limit 5 permitted only the first occurrence.
- Scope: `automation_service/contracts.py`, `automation_service/scheduler.py`, `automation_service/state.py`, `tests/test_automation_service_scheduler_canonical.py`, `tests/test_automation_service_state.py`
- Changes: Persist deterministic reset/timer/bounded-repeat identity and ordinal before claim. For reset-bounded Claim, identity includes the durable canonical `ready_batch_id`, ordinal, and `revision_within_reset` in addition to flow/reset, so distinct later ready batches within one reset receive distinct occurrences; persist that batch identity before claim, keep it immutable on the run, and reuse it on retry/restart. A new capture hash, OCR rescan, or UI revisit cannot mint a batch; only changed UI after reconciled state and a genuinely new ready batch may advance it, and `UNKNOWN` never rolls a batch forward to retry. Permit ordinals `0..limit-1` exactly once, block exhausted projections explicitly, and retain the running run’s original reset/budget across reset crossing. Store `next_due_at_utc` independently from non-zero retry backoff (`> one pulse`), cap attempts, and block repeated failures/unknowns rather than looping. Preserve timer anchor and UTC rollback rules.
- Non-goals: No route-specific resource policy, scheduler service loop, fairness implementation, native action, or legacy queue migration.
- Acceptance: (1) A bounded repeat limit N claims exactly N ordinals across restart and no N+1; reset-bounded Claim accepts two distinct canonical ready batches within the same reset as distinct occurrences, while a duplicate of the first batch after restart is denied. (2) Retry preserves occurrence key, ordinal, ready-batch identity, and `revision_within_reset`, and waits non-zero backoff; adjacent immediate pulses cannot retry. (3) Exhaustion is explicit `BLOCKED`/reason, not silent reset or success. (4) Reset crossing does not mutate a running run’s key/budget. (5) Timer anchor resumes without drift and clock rollback prevents new claims. (6) New capture hashes, OCR rescans, and UI revisits do not mint batches; changed UI advances only after reconciliation establishes a genuinely new ready batch, and `UNKNOWN` never rolls a batch forward to retry.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_automation_service_scheduler_canonical tests.test_automation_service_state tests.test_automation_service_scheduler`; temporary SQLite and deterministic clocks only.
- Native gate: none; offline recurrence/state only.
- Integration owner: F14 owns pulse sleep/heartbeat/fairness consumption; D02/D03/D04 consume reset facts later; R01 must receive occurrence identity for effectful routes. Merge scheduler/state hunks serially with F05/F09.
- PR boundary: one future offline PR titled `fix(scheduler): enforce bounded occurrence identity`, branch `recovery/rec-f07`.
- Rollback: Disable affected rows and global gate; do not reactivate legacy retry or reset authorities.
- Runtime authorization: none; zero transport and zero product/resource effects.
- Completion: Recurrence, retry, reset crossing, exhaustion, and timer-anchor behavior are durable, bounded, and tested offline without enabling a flow.

### REC-F08 — Make evidence filenames portable and action counts truthful
- Task ID: `REC-F08`
- Type: Bug
- Priority: P1
- Status: READY
- Objective: Produce filesystem-portable evidence/session filenames and one truthful compact action/input count without interpreting Windows colon syntax as an alternate data stream or rewriting protected evidence. This addresses AF13.
- Dependencies: none
- Related work: `RUNTIME-RELIABILITY-MERGE-BOUNDARY` — retain its historical merge/evidence boundary; `TOOLS-HOME-BASE-ATLAS-BLUESTACKS` — retain local diagnostics and their non-canonical status; `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION-FINAL-READINESS` — retain evidence correspondence as review-only.
- Evidence: `scripts/bluestacks_native_runtime.py:LocalBlueStacksRuntime.capture/_record_input`; `scripts/pnsctl.py:_retained_transport_count,_retained_action_rows`; `tests/test_bluestacks_native_runtime.py`, `tests/test_pnsctl_scheduler_pulse.py`, and `tests/test_world_map_navigation_bluestacks.py`. AF13 found colon-interpolated filenames and a zero-byte base file with a 399204-byte ADS carrying the verified hash.
- Scope: `scripts/bluestacks_native_runtime.py`, `scripts/pnsctl.py`, `tests/test_bluestacks_native_runtime.py`, `tests/test_pnsctl_scheduler_pulse.py`
- Changes: Sanitize action labels into a portable allowlisted filename component, preserve action identity in structured JSON rather than filename syntax, and detect/reject path/ADS ambiguity. Derive one count from the canonical action/input ledger with explicit transport-attempted versus semantic-completed fields; do not infer count from file size, directory names, or stale receipts. Read-only checks must not rewrite protected `evidence/**`.
- Non-goals: No protected evidence migration, bulk copy, deletion, manifest rewrite, telemetry framework, or route cutover.
- Acceptance: (1) Colons, separators, ADS syntax, traversal, and empty labels cannot create an ambiguous path. (2) Base files remain ordinary files with truthful bytes and no ADS-dependent proof. (3) Duplicate/unknown/failed actions are counted according to the canonical ledger exactly once; transport and semantic outcomes remain distinct. (4) Editing/deleting evidence cannot alter eligibility/retry. (5) Existing historical paths are reported, not rewritten.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_bluestacks_native_runtime tests.test_pnsctl_scheduler_pulse tests.test_world_map_navigation_bluestacks`; use temporary Windows-compatible paths only and never protected evidence.
- Native gate: none; no evidence rewrite or device action. Any later native ledger is an Operations responsibility.
- Integration owner: F09 owns canonical action count fields; F15 owns status/CLI display; O07/O12/O14 own later retention/retirement. Do not stage or mutate `evidence/**` or `.local-captures/**`.
- PR boundary: one future offline PR titled `fix(runtime): make evidence filenames portable`, branch `recovery/rec-f08`.
- Rollback: Disable affected output/reporting path; preserve existing artifacts and never restore colon/ADS ambiguity.
- Runtime authorization: none; zero transport and no protected evidence mutation.
- Completion: New filenames and compact counts are portable, ledger-backed, and semantically honest; historical evidence is preserved unchanged.

### REC-F09 — Establish the canonical static registry, SQLite schema, and attachable run session
- Task ID: `REC-F09`
- Type: Story
- Priority: P0
- Status: WAITING_DEPENDENCIES
- Objective: Make SQLite `service_control`/`service_lease`/`flow_state`/`runs`/`actions` the sole mutable runtime authority, initialize every flow disabled from static `FlowSpec` facts, atomically claim one occurrence, and let a session attach to an already-claimed run with complete generation/lease tokens. No queue, registry, evidence, Git, environment, or `--live` value may substitute. This is the canonical remediation for AF10.
- Dependencies: `REC-F04`, `REC-F06`
- Related work: `ARCH-NAVIGATION-AUTOMATION-ROADMAP` — reuse its typed dormant architecture; `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION` — retain blocked composition and do not activate M6; `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE` — reuse capture identity facts.
- Evidence: `automation_service/state.py:BotStateManager,ServiceControl,ServiceLease,FlowState,RunRecord,ActionRecord`; `automation_service/scheduler.py:_CanonicalPulseCoordinator`; `automation_service/session.py:RuntimeSession,SessionFence`; `automation_service/service.py:_canonical_registry_scheduler_components`; `automation_service/registry.py:FlowSpec,CanonicalFlowRegistration`; existing canonical state/scheduler tests and governance plan phases 0–1 define the tables, transitions, generation fences, and two SQLite gates. AF10 requires these SQLite authority and service-boundary consumers rather than legacy or health-only paths.
- Scope: `automation_service/state.py`, `automation_service/scheduler.py`, `automation_service/session.py`, `automation_service/service.py`, `tests/test_automation_service_canonical_authority.py`
- Changes: Complete the schema/constraints and short `BEGIN IMMEDIATE` CAS mutations; static specs seed missing rows only with `enabled=false`. Claim identity includes deterministic occurrence/reset identity and, for reset-bounded Claim, the durable canonical `ready_batch_id`, ordinal, and `revision_within_reset`, plus owner/process/lease/run/flow/service generations, mode, budgets, and operator key. The producer contract carries that identity into canonical claim evaluation without itself claiming or inserting a second run; only the scheduler transaction may claim. Add explicit attach-to-claimed-run validation and session construction; enforce `RESERVED→DISPATCHING→SUCCEEDED/NO_EFFECT/UNKNOWN`, orphan recovery, emergency fencing, and terminal release. Keep schedule and retry fields orthogonal.
- Non-goals: No route gameplay implementation, legacy state migration, native transport, global enablement, protected evidence, or retirement of `ResourceEffectAuthority`.
- Acceptance: (1) Fresh DB has every static flow row disabled regardless of `default_enabled`. (2) One transaction yields at most one active claim, persists the complete occurrence identity (including canonical ready-batch identity, ordinal, and `revision_within_reset` for reset-bounded Claim), and a session can attach only with exact owner/process/run/lease/flow/service tokens; a producer may carry an existing identity into that transaction but cannot claim or insert a second run. (3) Both persisted gates are required for live/manual dispatch; observe remains zero-input. (4) Disable/emergency/crash fences dispatch; orphan `DISPATCHING` becomes `UNKNOWN` and is never auto-repeated. (5) Terminal/error/CAS paths release exact ownership and preserve immutable occurrence identity.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_automation_service_state tests.test_automation_service_scheduler_canonical tests.test_automation_service_canonical_authority tests.test_automation_service_boundaries`; temporary databases and fake adapters only.
- Native gate: implementation PR is fake/replay-only. Native promotion requires O08/O10 after F13/F15/profile prerequisites; this ticket does not enable SQLite rows or the service gate.
- Integration owner: Shared schema owner is F09. Required serial hunks: `automation_service/registry.py:canonical_flow_specs/load_canonical_registry`, `automation_service/cli.py:_initialize_state_database/_CANONICAL_TABLE_COLUMNS`, `automation_service/actions.py:ActionExecutor`, `automation_service/operations.py`, `scripts/pnsctl.py` adapters/runner maps, and every future route runner. Exact legacy queue/receipt/lease callers remain disabled until F13/O12–O14 cutovers.
- PR boundary: one future PR titled `feat(runtime): establish canonical SQLite authority`, branch `recovery/rec-f09`; fake/replay offline code and scoped tests only.
- Rollback: Global SQLite stop, disable all rows, and discard only an unused new database; never reactivate old automation as a competing authority.
- Runtime authorization: none during implementation; zero native transport, zero live claims, zero persistent enablement.
- Completion: Canonical schema, atomic claim, attachable fenced session, action lifecycle, and two-gate behavior pass offline proof; code merge is not scheduler/native readiness.

### REC-F10 — Retain one guarded canonical native transport adapter
- Task ID: `REC-F10`
- Type: Story
- Priority: P0
- Status: WAITING_DEPENDENCIES
- Objective: Adapt the existing native transport behind the canonical session/action boundary while retaining exact device, package, profile, native `800x1280`, fresh-frame, stable-ROI, budget, and successor guards; do not add a second admission authority or bypass. Fake transport is the only implementation-time adapter. This addresses AF10.
- Dependencies: `REC-F09`
- Related work: `TOOLS-HOME-BASE-ATLAS-BLUESTACKS` — retain its exact BlueStacks profile and platform separation; `HOME-ATLAS-VERIFIED-ROUTE-INTEGRATION` — reuse its SafeActionExecutor/session seams; `SUPPLY-DEPOT-VERIFIED-ROUTE-SEAM-CLOSURE` — retain fresh pre-dispatch and binder evidence as historical route facts.
- Evidence: `scripts/bluestacks_native_runtime.py:CapturedNativeFrame,LocalBlueStacksRuntime.connect,tap,swipe`; `automation_service/adapters.py:DeviceAdapter,FakeDeviceAdapter,ReplayDeviceAdapter,SupervisedBlueStacksAdapter`; `tests/test_bluestacks_native_runtime.py` and `tests/test_automation_service_adapters.py` already assert native dimensions, fake/replay zero transport, and executor-only supervised dispatch. AF10 is the absence of a canonical guarded adapter. Governance plan preserves `LocalBlueStacksRuntime` and its profile/package guards.
- Scope: `automation_service/adapters.py`, `scripts/bluestacks_native_runtime.py`, `tests/test_automation_service_adapters.py`, `tests/test_bluestacks_native_runtime.py`
- Changes: Expose one canonical adapter interface that receives a fenced session/action capability and current semantic intent, not arbitrary coordinates/commands. Preserve package `com.global.ztmslg`, profile `pns-bluestacks-5-p64-800x1280-v1`, native dimensions, capture identity, input budgets, duplicate keys, stable target ROI, and positive successor. Keep fake/replay adapters structurally non-transport; supervised adapter delegates only to the existing executor and cannot claim/enable/register.
- Non-goals: No second executor/admission path, ADB/device connection during coding, coordinate portability to Bliss, registration, route migration, or live native evidence.
- Acceptance: (1) Wrong device/package/profile/dimensions/stale frame/ROI/budget/generation rejects before transport. (2) Fake and replay report zero transport and cannot be promoted to live. (3) Supervised adapter has no shell/ADB/coordinate API and dispatches only through the canonical executor. (4) One action key produces at most one transport attempt and requires semantic successor. (5) Native profile facts remain separate from Bliss.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_automation_service_adapters tests.test_bluestacks_native_runtime tests.test_automation_service_boundaries`; fake/replay and mocked executor only.
- Native gate: implementation PR is fake/replay-only. O08/O10 separately own supervised current native evidence after F13/F15/O03 profile checks; no native action is authorized here.
- Integration owner: F09 owns session/action fence consumption; F13 owns World runner; F11 owns startup/overlay; exact additional shared paths are `automation_service/actions.py`, `automation_service/session.py`, `safe_action_core/executor.py`, `scripts/pnsctl.py`, and `scripts/navigation_development_boundary.py`. No direct route `runtime.tap/swipe` bypass may remain in a migrated path.
- PR boundary: one future PR titled `feat(runtime): bind canonical native adapter`, branch `recovery/rec-f10`; fake/replay-only implementation and focused tests.
- Rollback: Disable the affected row/global gate and leave the adapter non-transport-capable; do not revive a legacy native runner.
- Runtime authorization: none during code PR; zero device/ADB/native inputs and zero registration.
- Completion: One guarded adapter is consumable by the canonical session/action boundary offline, while separate Operations gates remain required for any native promotion.

### REC-F11 — Compose shared Home-ready, Atlas, Back, startup, and VIP ownership
- Task ID: `REC-F11`
- Type: Story
- Priority: P0
- Status: WAITING_DEPENDENCIES
- Objective: Compose one shared typed Home/Atlas/startup/Back/overlay boundary with exact VIP/Get Pts, exit-dialog, Scarlett, Home-ready, and terminal Home ownership; remove route-specific duplicate recognizers and do not infer a successor from transport. This addresses AF03, AF05, and AF11.
- Dependencies: `REC-F01`, `REC-F02`, `REC-F03`
- Related work: `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE` — reuse same-capture typed facts; `HOME-ATLAS-VERIFIED-ROUTE-INTEGRATION` — retain verified Home route seams; `SUPPLY-DEPOT-VERIFIED-ROUTE-SEAM-CLOSURE` — retain binder-selected safe-exit semantics; `VIP-GET-PTS-POPUP-DISMISSAL` — retain its inactive/missing-evidence disposition.
- Evidence: `automation_service/screens.py:ScreenId,OverlayId,ScreenRouter`; `automation_service/overlays.py:OverlayRecoveryManager`; `automation_service/context.py:classify_common_context`; `scripts/startup_recovery.py:classify_startup_frame,recover_known_startup_overlay`; `scripts/startup_surface_recognition.py`; `tests/test_startup_recovery.py`, `tests/test_home_nav_recognition.py`, and `tests/test_automation_service_boundaries.py` establish current typed and exact-ROI seams. AF03/AF05/AF11 cover contradictory screens, unknown-overlay acceptance, and duplicate startup/Home ownership.
- Scope: `automation_service/screens.py`, `automation_service/overlays.py`, `automation_service/context.py`, `scripts/startup_recovery.py`, `tests/test_startup_recovery.py`
- Changes: Register existing canonical Home/Home Atlas/VIP/exit recognizers in one router; keep platform geometry in adapter modules. Define source-screen allowlists for in-game Back/Android Back, exact popup close and Scarlett safe Back ownership, bounded settle/reclassification, and positive terminal Home. Accept Home when VIP appeared over Home, reject unknown/manual login/tutorial/CAPTCHA/commercial variants, and keep recognition distinct from input capability.
- Non-goals: No new recognizer, popup transport, atlas reacquisition, Campaign retry, live input, or generic “tap any close/back” behavior.
- Acceptance: (1) Every retained VIP fixture resolves through one shared recognizer and at most one Close is attempted. (2) Exact Scarlett stable ROIs and purchase exclusions are required; unknown commercial surfaces stop before route. (3) Back is allowed only for source-screen policy; unknown/ambiguous target blocks with zero input. (4) Post-close/Back Home is independently classified, not inferred from transport or stale hash. (5) Daily, World, Ultimate, and startup callers use the shared ownership contract.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_startup_recovery tests.test_home_nav_recognition tests.test_automation_service_boundaries tests.test_vip_points_popup`; fake/replay frames only.
- Native gate: implementation PR is zero-input fake/replay-only; O08/O10 separately gate current native startup/route evidence.
- Integration owner: Shared composition owner is F11. Required caller hunks: `scripts/daily_row_claim_bluestacks.py:_popup_recognizer_call,_daily_selected_successor`, `scripts/world_map_navigation_bluestacks.py:SafePopupHandler`, `scripts/bluestacks_ultimate_challenge.py`, `scripts/flow_delivery_campaign_bluestacks.py`, `tasks/home_context.py`, `tasks/home_atlas_vision.py`, and `scripts/home_atlas_bluestacks.py`; legacy route-local popup/Home/Back loops become replay-only or hard-disabled atomically.
- PR boundary: one future PR titled `feat(runtime): compose shared Home and overlay recovery`, branch `recovery/rec-f11`; no native run.
- Rollback: Disable all affected routes/global gate; preserve canonical recognizer and do not restore duplicate popup/Back authority.
- Runtime authorization: none; zero transport and no registration/scheduler enablement.
- Completion: One shared, typed, bounded Home/overlay/Back/startup composition is consumed by callers offline; code merge does not establish native readiness.

### REC-F12 — Restore Home Atlas localization offline without Campaign retry
- Task ID: `REC-F12`
- Type: Story
- Priority: P1
- Status: WAITING_DEPENDENCIES
- Objective: Repair and validate the existing Home Atlas localizer’s stable semantic/Atlas-target ROI behavior offline, preserving the existing `HOME-ATLAS-LOCALIZATION-RESTORATION` outcome and explicitly refusing to turn this replacement ticket into a Campaign/AP retry or authorization.
- Dependencies: `REC-F01`, `REC-F02`
- Related work: `HOME-ATLAS-LOCALIZATION-RESTORATION` — retain its inactive, evidence-gated outcome and reuse its exact native bounds/negative controls; this ticket supersedes only the need for a new planning record, not its historical outcome or no-Campaign-retry rule; `TOOLS-HOME-ATLAS-DIRECT-PAN-PLANNER` — reuse planner/localizer contracts; `HOME-ATLAS-RECOVERY-AWARE-VIEWPORT-PLANNING` — reuse non-authorizing recovery planning.
- Evidence: `tasks/home_atlas_vision.py:BlueStacksHomeLocalizer,register_home_frame,classify_zoom`; `tasks/home_context.py:localize_home,is_home_canonical`; `scripts/home_atlas_bluestacks.py:BlueStacksLocalizeFirstHomeDriver`; existing `tests/test_home_atlas.py`, `tests/test_home_base_vision.py`, and `tests/test_home_atlas_planner.py` cover localization and stable bindings. Historical task explicitly says Campaign r2 remains `blocked_evidence_required` and does not authorize Campaign/AP.
- Scope: `tasks/home_atlas_vision.py`, `tasks/home_context.py`, `scripts/home_atlas_bluestacks.py`, `tests/test_home_atlas.py`, `tests/test_home_base_vision.py`
- Changes: Keep BlueStacks profile/native bounds and platform separation; use measured stable semantic/Atlas-target ROIs and current capture identity, distinguish canonical Home, localized noncanonical zoom, overlay, unsupported, stale, and contradictory transforms, and reject hash-only/projection-only claims. Validate two animation-variant positives plus stable-ROI negatives offline; preserve existing planner API and no-second-recognizer rule.
- Non-goals: No Campaign/AP navigation or retry, no native proof, no atlas reacquisition, no protected evidence collection, no Bliss geometry, and no replacement of the existing Home task’s historical disposition.
- Acceptance: (1) Distinct full-frame hashes with stable authoritative ROIs both recognize. (2) Changed target/source ROI, stale frame, unsupported zoom, overlay, or conflicting transform fails closed. (3) Canonical Home requires the existing semantic/Atlas contract, not a filename or projection alone. (4) No Campaign/AP caller, registration, scheduler row, or native input changes. (5) The inactive Home localization task remains explicitly no-retry for Campaign.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_home_atlas tests.test_home_base_vision tests.test_home_atlas_planner`; offline fixtures/replay only.
- Native gate: implementation PR is zero-input offline only. Any later one bounded navigation-only Home proof belongs to O08/O10 after explicit activation; it cannot enter Campaign.
- Integration owner: F11 owns shared Home-ready/startup composition; F13 and route consumers must use the repaired localizer without importing a second recognizer. Exact integration paths: `scripts/flow_delivery_campaign_bluestacks.py`, `scripts/flow_delivery_ultimate_challenge_bluestacks.py`, `scripts/noahs_tavern_recruit_bluestacks.py`, and `scripts/troop_training_bluestacks.py`; preserve each route’s separate native gate.
- PR boundary: one future PR titled `fix(home): restore stable Home Atlas localization`, branch `recovery/rec-f12`; offline code/tests only.
- Rollback: Leave Home localization inactive and preserve `HOME-ATLAS-LOCALIZATION-RESTORATION` blocked/no-retry status; disable any dependent row and do not attempt Campaign.
- Runtime authorization: none; zero input, zero Campaign/AP, zero evidence mutation.
- Completion: Stable-ROI Home localization is reviewed offline with honest ambiguity and the historical Home task/no-Campaign-retry outcome preserved.

### REC-F13 — Cut World over exclusively to one canonical runner
- Task ID: `REC-F13`
- Type: Story
- Priority: P0
- Status: WAITING_DEPENDENCIES
- Objective: Perform an atomic exclusive Home→World→Search→Home cutover so exactly one canonical `FlowSpec.runner` can dispatch World; every old pnsctl, direct, registration, lease, popup, and wrapper path is removed or structurally zero-input before enablement. This addresses AF01.
- Dependencies: `REC-F09`, `REC-F10`, `REC-F11`
- Related work: `HOME-ATLAS-VERIFIED-ROUTE-INTEGRATION` — retain its shared navigation/session evidence; `SUPPLY-DEPOT-VERIFIED-ROUTE-INTEGRATION` — retain route-specific cutover lessons; `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION` — retain blocked composition; `TOOLS-HOME-BASE-ATLAS-BLUESTACKS` — retain historical World/BlueStacks profile facts.
- Evidence: `automation_service/registry.py:WORLD_FLOW_ID,CANONICAL_FLOW_REGISTRY,build_canonical_handler`; `automation_service/service.py:registry_scheduler_components`; `scripts/flow_delivery_world_map_bluestacks.py:run_world_map_navigation_foundation,register`; `scripts/world_map_navigation_bluestacks.py:run_world_map_navigation,run_world_map_search_entry_only,recover_world_map_home`; `tests/test_world_map_navigation_bluestacks.py` exercises legacy runner and registration. AF01 requires global stop, drain/recovery, hard-disable old bindings, and one canonical runner; `EV-WORLD-FOUR-INPUT` is historical context only.
- Scope: `automation_service/registry.py`, `automation_service/service.py`, `scripts/flow_delivery_world_map_bluestacks.py`, `scripts/world_map_navigation_bluestacks.py`, `tests/test_world_map_navigation_bluestacks.py`
- Changes: Bind World to one static canonical runner through F09/F10/F11 session/action seams; preserve bounded navigation, exact controls, native package/profile, positive successors, and no resource effect. Under one disabled global gate, drain/reconcile active runs, remove/hard-disable old registration/lease/receipt/runner wrappers, commit binding while row remains disabled, and prove old adapters are replay-only. Revalidate generations before first future dispatch.
- Non-goals: No World live/native validation, Search claim/resource action, new route, new recognizer, Campaign work, or simultaneous old/new binding.
- Acceptance: (1) Repository call-graph audit finds one live World dispatch entry point. (2) The exact old caller set below cannot claim/reserve/call ADB. (3) Canonical route preserves occurrence/reset/input/successor/terminal Home constraints. (4) Manual run is refused with either SQLite gate false. (5) Atomic-cutover test proves no old/new double dispatch; row remains disabled until Operations acceptance.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_world_map_navigation_bluestacks tests.test_automation_service_canonical_authority tests.test_automation_service_adapters`; fake/replay World frames only.
- Native gate: implementation PR is fake/replay-only. O08 owns supervised current native World acceptance; O10 owns route ledger/progression. `EV-WORLD-FOUR-INPUT` is historical context only, not current acceptance.
- Integration owner: F13 owns the shared World cutover. **Exclusive old callers/integration hunks:** `scripts/pnsctl.py:_register_checked_in_bluestacks_handlers` and `_BLUESTACKS_FLOW_RUNNERS/_BLUESTACKS_RECOVERY_HANDLERS` (`register_world_map`); `scripts/flow_delivery_world_map_bluestacks.py:run_world_map_navigation_foundation,register`; `scripts/world_map_navigation_bluestacks.py:run_world_map_navigation,run_world_map_search_entry_only,recover_world_map_home`; `scripts/daily_row_claim_bluestacks.py:_accepted_visual_popup_panel_candidates,_popup_recognizer_call` (private World popup imports); `scripts/bluestacks_ultimate_challenge.py:_visual_popup_panel_candidates` import; and any direct `runtime.tap/swipe`/legacy lease/receipt reference found by the scoped call-graph check. Tests may retain fixture imports only when structurally zero-input.
- PR boundary: one future PR titled `feat(world): perform exclusive canonical cutover`, branch `recovery/rec-f13`; no native enablement.
- Rollback: Disable the World row and global gate, leave old bindings hard-disabled, and retain replay fixtures; never restore old live authority.
- Runtime authorization: none during code PR; zero native transport and zero persistent enablement.
- Completion: World has one canonical offline-dispatch path and an explicit old-caller hard-disable audit; native/scheduler promotion remains separately gated.

### REC-F14 — Run real pulses with due/retry/heartbeat/fairness/shutdown semantics
- Task ID: `REC-F14`
- Type: Story
- Priority: P0
- Status: WAITING_DEPENDENCIES
- Objective: Make the service loop perform real bounded UTC pulses—lease, clock check, atomic due selection/claim, fenced execution, heartbeat, terminalization, retry/backoff, fairness, and shutdown—rather than health-only sleep or zero-transport selector completion. This addresses AF10.
- Dependencies: `REC-F05`, `REC-F07`, `REC-F09`, `REC-F13`
- Related work: `HOME-NAVIGATION-OBSERVABILITY` — reuse deterministic timing/reporting shape; `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION-FINAL-READINESS` — retain review boundary; `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION` — remain blocked until readiness and cutovers.
- Evidence: `automation_service/service.py:AutomationService.pulse,run`; `automation_service/scheduler.py:UtcPulseCoordinator,_CanonicalPulseCoordinator`; `automation_service/operations.py:OperationsService.health`; `automation_service/state.py` persistent schedule/retry/lease fields; `tests/test_automation_service_scheduler_canonical.py`, `tests/test_automation_service_scheduler.py`, `tests/test_automation_service_operations.py` cover pulse, idle, contention, retry, and health. AF10 is the observed absence of one real service/adapters/health boundary.
- Scope: `automation_service/service.py`, `automation_service/scheduler.py`, `automation_service/operations.py`, `tests/test_automation_service_scheduler_canonical.py`, `tests/test_automation_service_operations.py`
- Changes: Implement the one-loop algorithm: verify lease/token and rollback, `BEGIN IMMEDIATE` candidate/claim, commit before work, attach session, heartbeat bounded steps, validate every reservation/dispatch fence, terminalize schedule/retry atomically, and sleep to earliest due/retry/heartbeat/starvation deadline. Add deterministic bounded-starvation selection and safe shutdown/emergency stop without health-only success.
- Non-goals: No 24/7 production soak, native enablement, resource-effect parity, route mass migration, telemetry framework, or second scheduler.
- Acceptance: (1) Healthy pulse claims/executes at most one eligible occurrence and terminalizes it. (2) Due, retry, reset, clock rollback, heartbeat, and starvation deadlines produce deterministic next wake. (3) Contention returns bounded safe idle, never duplicate claim. (4) Stop/shutdown fences next dispatch and releases ownership. (5) Shadow remains mutation-free and a failed pilot leaves rows disabled.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_automation_service_scheduler_canonical tests.test_automation_service_scheduler tests.test_automation_service_operations tests.test_pnsctl_scheduler_pulse`; fakes/temporary SQLite only.
- Native gate: implementation PR is fake/replay-only. O09/O11 separately own navigation pilot/soak; no production service enablement here.
- Integration owner: F09 owns state/scheduler schema; F15 owns CLI/service controls; O08/O09/O10 consume stable scenario IDs later. Shared `automation_service/state.py`, `automation_service/cli.py`, and route runner maps merge serially.
- PR boundary: one future PR titled `feat(runtime): run canonical service pulses`, branch `recovery/rec-f14`; no native or production enablement.
- Rollback: Global stop plus disable all migrated rows; leave old scheduler non-transport-capable and do not fall back to it.
- Runtime authorization: none during implementation; zero transport and zero live scheduling.
- Completion: Offline pulse execution, fairness, retry, heartbeat, shutdown, contention, and mutation-free shadow behavior are proven; pilot/soak readiness remains separate.

### REC-F15 — Expose coherent CLI controls and real lease health
- Task ID: `REC-F15`
- Type: Story
- Priority: P0
- Status: WAITING_DEPENDENCIES
- Related work: `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION` — retain blocked runtime composition; `RUNTIME-RELIABILITY-MERGE-BOUNDARY` — retain historical control-plane boundary; `ARCH-NAVIGATION-AUTOMATION-ROADMAP` — reuse dormant CLI/state contract.
- Objective: Make `bot status`, `bot observe`, `bot run FLOW [--live]`, `bot service`, `bot enable/disable`, and `bot emergency-stop` thin, coherent adapters over the same SQLite state, fenced lease, canonical service, and fake/replay adapters; `--live` cannot bypass gates and observe stays zero-input. This addresses AF10.
- Dependencies: `REC-F05`, `REC-F09`, `REC-F10`
- Evidence: `automation_service/cli.py:build_parser,main,_initialize_state_database,_database_probe`; `automation_service/service.py:AutomationService,status,observe,pulse`; `automation_service/operations.py:OperationsService.health`; `automation_service/adapters.py:FakeDeviceAdapter,ReplayDeviceAdapter,SupervisedBlueStacksAdapter`; `tests/test_automation_service_cli.py`, `tests/test_automation_service_operations.py`, and `tests/test_pnsctl_scheduler_pulse.py` cover command shape, disabled status, manual requests, health, and contention. AF10 requires these controls to consume canonical SQLite state rather than legacy health/CLI paths.
- Scope: `automation_service/cli.py`, `automation_service/service.py`, `automation_service/operations.py`, `automation_service/adapters.py`, `tests/test_automation_service_cli.py`
- Changes: Route all controls through canonical state/service APIs; status reports real service/flow gate, lease owner/generation/health, run/action state, and safe blockers from SQLite. Enable/disable increments flow generation; emergency-stop disables global gate and increments service generation; manual live requires both gates and canonical claim/session; observe cannot mutate. Keep fake/replay explicit and supervised adapter coherent with F10.
- Non-goals: No CLI route logic, queue/receipt/Git/evidence authority, production registration, environment-variable enable override, native action, or broad pnsctl rewrite in this ticket.
- Acceptance: (1) Fresh status reports disabled SQLite defaults and real lease/database/adapter health. (2) Enable/disable/emergency commands perform only the defined fenced SQLite transition. (3) `run --live` is rejected with either gate false and cannot create a bypass claim. (4) `observe` captures/read-only reports with zero reservation/claim/transport. (5) Fake/replay adapters remain zero transport and errors are structured/bounded.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_automation_service_cli tests.test_automation_service_operations tests.test_automation_service_adapters tests.test_pnsctl_scheduler_pulse`; temporary state and fake/replay only.
- Native gate: implementation PR is zero-input fake/replay-only. O08/O10/O11 separately gate native control/health/promotion; no CLI command enables production here.
- Integration owner: F09 owns state/session fields; F14 owns service pulse; `scripts/pnsctl.py:main`, `_register_checked_in_bluestacks_handlers`, and legacy command branches are exact additional shared hunks for hard-disable/translation. O03/O04 own manual-only login/takeover policy.
- PR boundary: one future PR titled `feat(cli): expose canonical runtime controls`, branch `recovery/rec-f15`; no native or production enablement.
- Rollback: Global emergency stop and disable rows; preserve read-only status/observe and do not restore queue/receipt activation.
- Runtime authorization: none during implementation; zero transport, registration, and persistent production enablement.
- Completion: Public controls, manual semantics, observe safety, and lease health all agree on canonical SQLite authority offline; native/scheduler readiness remains separately gated.

### REC-F16 — Provide the canonical concurrency/crash/reset/fairness acceptance package
- Task ID: `REC-F16`
- Type: Validation
- Priority: P0
- Status: WAITING_DEPENDENCIES
- Objective: Deliver one offline acceptance package proving process concurrency, fenced ownership, crash recovery, reset/timer/retry behavior, clock rollback, fairness, contention, and restart budget invariants for the canonical runtime without assuming resources or native success. It includes the AF06 resource-parity regression package.
- Dependencies: `REC-F14`, `REC-F15`
- Related work: `RUNTIME-RELIABILITY-MERGE-BOUNDARY` — retain its historical reliability evidence as non-native context; `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION` — retain blocked status; `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE` — reuse identity fixtures.
- Evidence: Existing temporary/fake suites `tests/test_automation_service_state.py`, `tests/test_automation_service_scheduler_canonical.py`, `tests/test_automation_service_canonical_authority.py`, `tests/test_automation_service_boundaries.py`, and `tests/test_automation_service_operations.py` cover state transitions, canonical gates, shadow, stale frames, contention, and health. AF06 resource parity is consumed through the R01 equivalence package; the prior audit’s 80 fake/temp tests are not native evidence.
- Scope: `tests/test_automation_service_state.py`, `tests/test_automation_service_scheduler_canonical.py`, `tests/test_automation_service_canonical_authority.py`, `tests/test_automation_service_boundaries.py`, `tests/test_automation_service_operations.py`
- Changes: Extend the five existing focused modules with deterministic scenarios: 20 concurrent contenders, two service processes, every reservation/dispatch/crash boundary, orphan `UNKNOWN`, no automatic unknown retry, reset crossing, timer anchor, rollback, retry backoff, fairness maximum wait, SQLite contention, evidence independence, lease release, and restart-preserved budgets. Use fake/replay adapters and temporary databases.
- Non-goals: No production code redesign, resource/gameplay action, native/device/ADB run, protected evidence, soak, registration, scheduler enablement, or assertion that old completed labels are canonical acceptance.
- Acceptance: (1) Twenty contenders produce exactly one active run and no duplicate occurrence. (2) Two processes cannot validate the same generation or retain ownership after takeover. (3) Crashes before/after reservation, during dispatch, and before reconciliation produce defined safe states; orphan dispatch is never auto-repeated. (4) Reset/timer/retry/clock/fairness/SQLite contention invariants pass deterministically. (5) Input/resource/currency/combat budgets remain enforced after restart in route-independent fakes. (6) Evidence edit/delete and shadow observation cannot alter eligibility/retry.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_automation_service_state tests.test_automation_service_scheduler_canonical tests.test_automation_service_canonical_authority tests.test_automation_service_boundaries tests.test_automation_service_operations`; no native command.
- Native gate: none; this is an offline validation record and does not promote any route. O08–O11 remain required for native/service readiness.
- Integration owner: F16 validates F09/F14/F15 outputs and R01 equivalence package; route-specific O10 scenario IDs must be attached independently and no D12/global O10 dependency is implied.
- PR boundary: one future validation record titled `test(runtime): prove canonical recovery invariants`, branch `recovery/rec-f16`; no code PR or native run unless a narrowly needed test seam is reviewed.
- Rollback: Mark validation blocked and leave all rows/global gate disabled; never loosen a failing invariant or revive legacy authority.
- Runtime authorization: none; zero transport, zero resource effects, zero evidence mutation.
- Completion: Offline acceptance package records all required outcomes and boundaries with no false native/scheduler/enablement claim.

### REC-F17 — Adopt remaining direct OCR callers behind the bounded engine
- Task ID: `REC-F17`
- Type: Story
- Priority: P1
- Status: WAITING_DEPENDENCIES
- Objective: After F02, migrate every remaining direct `pytesseract`/OCR callsite to the one bounded, capture-identity-bound ROI engine without creating a second pipeline, broad full-frame fallback, or route-specific timeout authority. This addresses AF12.
- Dependencies: `REC-F02`
- Related work: `VISION-SEMANTIC-OCR-CROP-PIPELINE` — reuse its single identity-bound crop contract; `SUPPLY-DEPOT-LEGACY-ADAPTER-RETIREMENT` — retain its no-supported-caller evidence and do not infer that all legacy OCR callers are retired; `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE` — reuse immutable same-capture observations.
- Evidence: Direct callsites observed in `scripts/bioenhancer_free_research_canary.py:_ocr_tokens`, `scripts/bluestacks_popup_recognition.py`, `scripts/bluestacks_ultimate_challenge.py:_ocr_region_hits/_ocr_ordered_tokens/_ocr_region_text`, `scripts/daily_resource_item_bluestacks.py:_default_ocr/_ocr_tokens`, `scripts/daily_row_claim_bluestacks.py:_default_ocr/_ocr_tokens`, `scripts/enhancement_bluestacks.py:_default_ocr`, `scripts/flow_delivery_campaign_atlas_bluestacks.py:_ocr_hits`, `scripts/home_atlas_bluestacks.py` campaign-title OCR, `scripts/noahs_tavern_recruit_bluestacks.py:_noahs_tavern_binding_ocr`, `scripts/startup_normalization.py`, `scripts/startup_surface_recognition.py`, `scripts/world_map_navigation_bluestacks.py`, `tasks/campaign_atlas_chapter.py`, `tasks/campaign_auto_battle_vision.py`, `tasks/home_atlas_vision.py`, and `tasks/nova_praise_vision.py`; these direct/repeated/full-frame paths are AF12, and all are migrated only after F02.
- Scope: `automation_service/screens.py`, `scripts/daily_row_claim_bluestacks.py`, `scripts/world_map_navigation_bluestacks.py`, `scripts/daily_resource_item_bluestacks.py`, `scripts/bluestacks_popup_recognition.py`
- Changes: Inventory and replace each direct OCR call with the shared F02 API, passing current immutable capture identity, exact ROI, constrained mode, and deadline. Preserve each caller’s semantic association and coordinate space; reject full-frame/empty ROI and late/cross-capture results. Delete obsolete wrappers/aliases after all callers migrate; keep route-specific labels/constraints outside the engine and never use OCR alone as dispatch authority.
- Non-goals: No OCR model/threshold tuning, route behavior changes, native validation, evidence rewrite, second worker/pipeline, or broad fuzzy recognition.
- Acceptance: (1) Scoped repository search shows no remaining production direct OCR invocation outside the bounded engine/adapters explicitly permitted by F02. (2) Every migrated call declares bounded ROI, mode, deadline, and parent capture identity. (3) Timeout, stale, cross-capture, unsupported ROI, and full-frame fallback cases fail closed. (4) Existing semantic associations remain route-owned and no OCR result authorizes transport alone. (5) Fake/replay tests prove no transport and no unbounded worker.
- Verification: Prescribe (do not execute) `python -m unittest tests.test_automation_service_boundaries tests.test_automation_service_temporal tests.test_daily_row_claim_bluestacks tests.test_daily_resource_item_bluestacks tests.test_vip_points_popup tests.test_home_atlas tests.test_campaign_auto_battle_runtime`; use offline fixtures/replay only.
- Native gate: implementation PR is fake/replay-only; O08/O10 separately own any current native route evidence. Historical OCR output is not current acceptance.
- Integration owner: F17 owns the callsite inventory and serial adoption. Additional exact paths are all Evidence-listed callers, especially `tasks/campaign_auto_battle_vision.py`, `tasks/home_atlas_vision.py`, `tasks/nova_praise_vision.py`, `scripts/startup_surface_recognition.py`, `scripts/bluestacks_ultimate_challenge.py`, and `scripts/enhancement_bluestacks.py`; F11 owns shared popup/startup composition. F02 and F17 cannot merge concurrently on `automation_service/screens.py`.
- PR boundary: one future PR titled `refactor(vision): adopt bounded OCR engine`, branch `recovery/rec-f17`; offline code/tests only and no mass route migration beyond the listed callsites.
- Rollback: Disable affected recognizers/flows and global gate; retain fail-closed bounded engine and do not restore abandon-daemon/full-frame fallback.
- Runtime authorization: none; zero transport, device access, claims, resources, and protected evidence mutation.
- Completion: Every direct OCR consumer is behind the single bounded identity-bound engine, no second pipeline remains, and offline verification preserves semantic caller behavior without claiming native readiness.
