# Issue #51: implemented CI/test decisions

Scope: test code, offline tooling and CI only. Production gameplay, recognition thresholds,
runtime authority, bot scheduling and live acceptance are unchanged. No duration, test-count
or savings target governs these decisions.

## Required protection and change impact

The exact selectors live in [offline_selection.py](../../../scripts/offline_selection.py).
The policy is a small baseline plus source/fixture impact rules, not a timing allowlist.

| Required group | Failure protected; plausible change | Marginal value and frequency |
|---|---|---|
| Windows consequential contracts | Duplicate/unknown spending, stale or paid targets, owner/lease loss, stop and generation races, persistence/restart errors | Real executor/authority outcomes plus the shared all-route adapter contract. These invariants affect every route; the native historical variation matrix adds little to unrelated PRs. |
| Supported service consumers | Wrong AP/count/reset/cooldown/no-work/terminal-proof composition | One required service integration per executable registration, with distinctive native recognition samples. A registry check requires a consumer entry for new routes. Full family/import consumers run on route changes. |
| Shared Home/Atlas/OCR/popup/navigation | Broken crop/provenance, unsafe binding, wrong successor, OCR timeout or worker leak | Test thoroughly in owning suites when changed, plus representative consumers. Do not replay each shared variation through every route. |
| Linux portability/tooling | POSIX paths, SQLite locking/rollback, /proc worker cleanup, dependency/selection false greens, static debt | Compact distinct Linux checks plus native Home/Supply OCR samples. Full route logic is not duplicated on Linux for every unrelated PR. |
| Disabled admission | An unsupported feature accidentally permits dispatch or becomes active | Keep the small policy/dormancy checks and registry closure; expand detailed planned-feature semantics when affected or in full validation. |
| CI execution contract | Planned-but-unexecuted, omitted, repeated, newly skipped or foreign-policy/revision/attempt cases appear green | Independently recompute discovery and intended selection. Verify starts/results exactly; disclose omissions. A selected receipt cannot claim full coverage. |

Changed test files execute in full. Bespoke production changes select their route family and
transitive explicit import consumers. Shared surfaces select owners and a consumer matrix,
rather than their entire import blast radius. Fixture/assets and contract data have explicit
owner rules. Dependencies/interpreter/package initialization/global profile changes, mixed or
unknown assets, unreadable impact, or unavailable history use an explicit full fallback.

The static import approximation omits lazy production function imports to avoid expanding
the operator aggregator into every route. Known shared boundaries have explicit owner rules.
A missed dynamic dependency or an unusual consumer interaction can therefore escape a PR;
the next full validation is the backstop, not equivalent immediate coverage.

The workflow schedules full regression on both OSes daily at **08:23 UTC** after merge,
or on workflow dispatch / an explicit
`ci:full` PR label. It is not another automatic pre-merge bottleneck. Deferred failures can
survive a merge until that run, normally within 24 hours plus queue/runtime; failed or missed
schedules extend the delay. Old PNG regressions do not establish compatibility with today's game.

## Removed, consolidated and narrowed

All original captures, research reports and retained receipts remain untouched. The source
history preserves retired tests.

| Exact files / IDs | Decision and actual coverage change |
|---|---|
| tests/test_readme_consistency.py (whole file) | Delete newest-date/link convention. Status-link existence/date selection is no longer checked automatically; registry-backed route documentation remains checked. A newer filename is not acceptance evidence. |
| tests/test_reference_manifest.py; tests/test_coordinate_calibration.py (whole files) | Delete historical vendor manifest declarations/ROI arithmetic and Bliss calibration research checks. No supported bot importer exists. Research arithmetic/completeness/restriction-declaration defects can now go undetected; research code/data are preserved. Exclude the retired calibration directory from active static scanning and remove its old unused-code allowance; supported navigation-session calibration remains active and tested. |
| OperatorCliTests.test_removed_remote_implementation_symbols_are_absent; PersonalMightCompletionAttributionTests.test_completion_contract_has_no_fixed_bliss_profile_import | Delete weak namespace checks in test_catalog_and_pnsctl.py / test_personal_might_praise.py. Exact unused symbol/import-name absence is lost; public CLI refusal and actual active-profile/provider-authority behavior remain. |
| ExecutorCase.test_capability_firewall_preserves_single_executor_and_optional_path | Delete repeated alias/architecture/happy-path check in test_safe_action_core.py. Alias identity is no longer pinned; real optional execution, single-use and duplicate-consume outcomes remain. |
| RecoveryAwareViewportPlannerTests.test_plan_direct_pan_public_signature_excludes_seen_destinations | Delete signature introspection in test_home_atlas_planner.py. Parameter spelling/order lock is lost; destination-history denial remains behavioral coverage. |
| MinimalPanPlannerTests.test_retained_bad_label_frame_binds_tavern_geometry | Merge its explicit_override assertion into the existing attempt3 row of test_native_geometry_binding_handles_two_retained_camera_offsets. Same actual PNG/localizer/binding remains; duplicate preparation is removed. |
| NativeFrameMutationTests: test_all_outputs_are_native_rgba_and_records_have_distinct_mutation_identity; test_stale_substitution_fails_closed_against_parent_identity; test_stale_output_is_rejected_by_semantic_ocr_identity_gate; test_serialization_contains_metadata_only_and_is_repeatable | Consolidate into test_generation_is_deterministic_and_preserves_sources, retaining two independent generations, RGBA/source/identity/OCR rejection and serializer repeatability. JSON metrics are parsed semantically; compact-whitespace and ndarray/dtype word-absence conventions are removed. |
| ContractAndReservationTests.test_completed_ordered_family_verifies_three_uses | Merge verdict assertions into test_completed_family_passes_operational_generic_verification in test_flow_delivery_enhancement.py. The operational verifier calls the same family validator; counts/categories/causal/accounting assertions remain. |
| EnhancementCategoryResumeTests.test_equivalent_session_spelling_preserves_verified_source_and_effects | Merge into positive phase of test_continuous_family_still_requires_three_ordered_current_uses. Keep every assertion and reversed-order negative. Separate canonical/equivalent successful fixture executions are consolidated; canonical paths remain elsewhere. |
| ServicePersonalMightTests.test_gray_replay_after_home_keeps_its_actual_native_capture_identity; test_due_rejects_unknown_identity_counts_home_and_reset_crossing | Merge identity instrumentation and all due mutations into test_real_boundary_one_praise_then_current_day_gray_repeat_no_praise. Repeated successful route setup is removed. |
| UltimateServiceTests.test_result_normalization_requires_current_identity_flee_home_and_next_utc_reset | Merge all result/due mutations into test_prior_completed_day_allows_one_current_flee_home_then_idempotent_repeat. |
| HelpCompletionAttributionTests.test_help_provider_attributes_completion_only | Merge zero-progress, completion/overcompletion and authority-absence assertions into ContractTests.test_alliance_help_is_completion_attribution_only in test_task_module.py. |
| PositiveRecoveryDeliveryTests.test_replay_and_receipt_before_progress_preserve_original | Remove only duplicate initial validation; actual reconciliation and receipt read validate again before progress. Original bytes and failure ordering remain checked. |
| CampaignLineupTests.test_changed_header_gold_or_caption_rejects_dispatch_target; test_duplicate_or_displaced_challenge_controls_fail_closed | Delete older-fixture mutation repetition. CurrentCampaignLineupTests retains the predicates on the current retained fixture. Mutations on the older Ultimate-sourced Campaign frame are genuinely removed; older positive/back/artwork cases remain. |
| CampaignHomeAPFiveNativeTests.test_five_and_retained_hundred_rows_remain_ambiguous | Delete exact5/100 conflict combination. Generic120/100 dual-row denial remains in CampaignNativeAPTests.test_two_individually_valid_ap_rows_are_ambiguous; native five/unreadable-five cases remain. |
| CampaignHomeDirectEntryPanTests.test_existing_current_native_campaign_binding_still_completes_without_pan | Delete isolated canonical completion repetition. Safe-anchor and fresh native HUD-waypoint consumer checks remain; this particular independent entry execution is removed. |
| ChipPanelNativeTests.test_current_panel_back_reaches_commander_with_one_navigation_and_zero_resource; positive half of ModulePanelNativeTests.test_measured_back_reaches_home_without_resource_and_missing_fresh_back_blocks | Remove isolated panel-start positives. Keep actual Chip/Module quantity-to-Home chains and fresh-missing-Back denial (renamed test_fresh_frame_missing_back_cannot_reuse_the_planning_frame_target). Lost: isolated Chip-to-commander_overview termination and Module-panel-to-Home entry. The Home chain is not an identical destination replacement. |
| BioenhancerHomeEntryBindingTests reference preparation | Share an authentic model guarded by exact Atlas/resolved manifest. Every frame still localizes and binds freshly. Repeated construction is removed, not frame recognition. |
| ServiceSupplyTests.test_known_route_surfaces_preserve_no_popup_entry_without_new_input | Keep native facility composition. Exhausted/Arena/radial use separate source-bound vision results while retaining admission and zero-input/accounting/source-forwarding checks. Their raw recognition lives in Supply vision and Arena route tests. Three pixel-to-service compositions are removed: a defect unique to those joint contexts may escape even if separate owner/service tests pass. |

The retired IDs are not relabeled as skips. Full validation means the complete **current**
discovered suite, not conservation of every historical ID.

## Repeated execution

- Remove the duplicate controlled semantic rerun. CI runs under the developer command's
  shared sanitized environment; hash/user-site flags are set before Python starts and runtime
  selectors are removed before discovery. Three entrypoint tests include a real small child
  and failure propagation. The ordinary developer command remains available. Ambient/random
  hash environment variation is reduced; it is not equivalent coverage of arbitrary host setup.
- Remove the eight extra Supply processes from routine validation. The known exhausted
  native canary and a Windows available-control case remain required; full validation runs
  the native corpus once. The old five-case/eight-process sample is available only as an
  explicit `supply_stress` input or `ci:supply-stress` label. Additional startup/load
  variability has no automatic detection bound. Inspected failures in the prior evidence
  occurred in the first iteration; no late-iteration requirement or flake probability is claimed.
- Execute/verify inside the existing two named per-OS required jobs. Remove six duplicate
  execution environments and two receipt-only aggregate environments. Failed steps remain
  failed jobs; receipts cannot rescue an earlier failure. Independent plan verification and
  failed-attempt artifact retention remain.

Routine static ratchets run on Linux; full validation repeats them on Windows. Windows-only
analyzer differences may wait for full validation. Allowances may only shrink.

## Measurements and verification

Existing main baseline f5dcd1ce:
[successful run 42178205198](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/42178205198).
It scheduled 3,159 discovered cases + 395 controlled + 40 extra native invocations per OS:
7,188 scheduled invocations including expected skips. Ten jobs occupied **4,726 runner-seconds**.
Windows execution jobs 606/730/740/533 seconds; Linux 462/611/530/493; aggregates 15/6.
The first job started to final required-gate completion took **1,109s**; creation to
completion took **1,110s**. Some Windows jobs queued for several minutes. This is an
observed hosted run, including setup and queue effects, not a controlled benchmark.

Bounded local comparisons used Python 3.12, Tesseract 5.5.0, OMP_THREAD_LIMIT=1, the same
production source and unchanged captures, serial fresh processes on one Windows host:

| Comparison | Before | After | What was actually retained |
|---|---:|---:|---|
| Complete seven-case Bioenhancer Home-entry module |39.921s;10 models,10 localizations |13.955s;1 model,10 localizations |All 7 pass, no skips; unrelated Atlas and manifest each rejected |
| Four-surface Supply service admission |22.373s |15.238s |Facility native;3 typed branch-specific consumers; both pass without skips |

Supply real screen-recognizer calls fell from 3 to 1 and real Home calls from 8 to 2.
The first Supply comparison lacked the Windows spawn guard and failed; the corrected
scratch harness produced the pair above without changing the test or production code.
These are observed pairs, not statistical guarantees or hosted savings. Raw local logs and
scratch comparisons remain under .local-validation/issue51; original evidence was not changed.
An in-memory fault removing radial admission was detected specifically by the retained
radial consumer row (resume_ready became false); the other three rows passed.

Focused validation so far:
- Accounting/consolidation batch: 186 cases; two Windows 8.3 alias cases failed only in the
  restricted filesystem view, then both passed with normal Windows file access.
- Native/replacement batch: 117 cases; four mutation-output cases correctly rejected a temp
  directory inside the repository. The 9-case mutation module passed using an external temp
  directory; the remaining native/replacement cases passed without skips.
- Selection/receipt/entrypoint plus architecture/metadata checks: 84 passed at the recorded
  stage. The final focused selection/receipt/entrypoint/task/mutation batch passed 58 cases.
- Windows no-diff routine baseline: **284 executed, 0 skips; 75.270s suite + 2.680s
  selection = 77.950s**. Independent verification matched the exact plan and disclosed
  2,872 omitted IDs from the 3,156-case inventory. This is local Python 3.12, not hosted 3.11.
- Pinned static tools: 438 active Python files; no new findings and no stale allowances.
  The calibration exclusion shrank one old allowance; no budget increased.

Retained failures include the two environmental attempts above and historical
[42167899112](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/42167899112).
That exhausted-Supply failure's hidden inner OCR cause remains evidence_required; an older
or later green run does not establish its cause.

Hosted Python 3.11 no-diff baseline on a758612:
[run 42194866117](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/42194866117),
both jobs passed on their first attempt. This deliberately compares HEAD with itself to
measure the baseline; the separate PR run validates the complete implementation impact.

| Observed required path | Previous main | New no-diff baseline |
|---|---:|---:|
| First job start to both required gates complete |1,109s |227s |
| Workflow creation to both required gates complete |1,110s |230s |
| Summed runner occupancy, including setup/verification |4,726s / 10 jobs |340s / 2 jobs |
| Scheduled test invocations, including skips |7,188 |386 |
| Actual new baseline executions / skips |not a baseline-only run |284 Windows + 102 Linux / 0 skips |

The new Windows suite took 125.408s and selection 2.703s; Linux 23.191s and 2.467s.
Windows/Linux job occupancy was 227s/113s; each job queued 2s after creation.
Checkout/Python/dependency/OCR setup occupied 75s/60s, plus Linux static 9s; independent
execution verification occupied 2s/3s. Remaining job time includes compilation, line-ending
checks, artifacts and runner bookkeeping. Step timestamps are rounded to seconds.
Most of this reduction changes the required scope/frequency; it is not equivalent immediate
coverage or a pure speedup of the same workload. Runner/queue variation makes these observed
runs, not guarantees. Route/shared/dependency changes select broader work.
Using the actual current inventory (selection only, not extra test executions), a Supply
route or fixture change selects 392 Windows / 213 Linux cases; Home Atlas vision selects 720/543;
the shared executor selects 622/575; dependency changes select all 3,156 per OS.

Complete implementation-impact verification is separate from the baseline measurement.
The final source revision, full-run verdict and measurements are recorded in
[draft PR #52](https://github.com/mattebad/Puzzles_Survival_Automation/pull/52) and its checks.
The preliminary full run42194844610 was superseded by this documentation/evidence commit;
its incomplete execution is not pass proof. No release/live-acceptance claim.

## Future routes

Add distinctive semantics/recognition cases, one required consumer entry in ROUTE_BOUNDARIES,
and reuse the all-route service contract. Add/verify the real affected import/family mapping.
Put shared visual variations in their owning layer; add another consumer only for a materially
different integration contract. Do not copy the full shared safety/vision suite into a new
route. Full/manual validation remains available for release-risk or uncertain changes.
