# Measured CI efficiency pass

Implemented and locally offline-proven; not live acceptance. No device access,
production route behavior, timeout, scheduling or deployment change is included.
This records local measurements; exact-head hosted proof and current-attempt
receipts are linked from [PR #50](https://github.com/mattebad/Puzzles_Survival_Automation/pull/50).
Local timing improvements do not substitute for its complete hosted checks.

PR #50 remains draft and review-required. Its Windows code-regression hold is
resolved by the matched hosted comparison below; the recalibrated weights pass
the predeclared retention rule. This is not a guaranteed end-to-end speedup or
an explanation of the historical host's unretained CPU/resource traces.

## Comparable local measurements

The before source is `51ac935`; the measured candidate code is `175be73`.
Each complete module ran in three sequential fresh processes per revision and
OS, with no overlapping local OCR sweep. All 60 module samples passed. Windows
used Python 3.12.10 and Tesseract 5.5.0.20241111; Linux used Python 3.11.18 and
Tesseract 5.5.0. Both used the existing pinned developer dependencies and
`OMP_THREAD_LIMIT=1`, with bytecode disabled and physical temporary directories.

Instrumented elapsed medians, in seconds:

| Module | Windows before | Windows after | Linux before | Linux after |
| --- | ---: | ---: | ---: | ---: |
| `test_service_campaign_ap` | 87.937 | 61.969 | 85.873 | 60.254 |
| `test_daily_row_claim_bluestacks` | 10.000 | 5.109 | 8.966 | 3.785 |
| `test_bluestacks_ultimate_challenge` | 60.641 | 50.172 | 65.788 | 55.286 |
| `test_daily_resource_item_bluestacks` | 7.953 | 4.578 | 8.464 | 5.215 |
| `test_ultimate_defeat_recovery` | 15.593 | 11.953 | 13.878 | 10.176 |

Every candidate reduced actual work and its module median on both OSes; none
failed the retention rule. These are observed local comparisons, not a promised
hosted speedup or a confidence interval. Raw observations and outcomes are
retained outside the repository; no evidence files were rewritten.

## Work reduced, proof retained

- Selected completed settling sleeps fell to zero: Campaign phase polling,
  unknown Quest successor polling, two bounded Ultimate fake-runtime scenarios,
  and the already-selected Resources route. Logical Campaign/Quest deadlines
  still advance through the existing test clock. Production timeouts are intact.
- Capture/policy freshness stays on the original clock. Time namespaces are
  patched locally, never through shared `time.sleep`. The before/after capture
  labels match exactly on both OSes: Quest 22, Ultimate failure scenarios 11,
  Ultimate lineup 3, Resources 10. Existing dispatch, resource, reconciliation,
  terminal, regeneration and midnight/restart assertions remain.
- A real unknown-state Campaign smoke reaches one logical second after two
  half-second waits, blocks after two captures, and sends zero inputs.
- Ultimate recovery uses a separate existing `OcrMemo` per consumer test. Real
  Tesseract attempts fell from 79 to 57 per full module run on both OSes: 46 to
  24 in receipt/route consumers, with 22 hits. All 33 native-recognition calls
  remain fresh. Running native proof before and after consumer classes confirms
  restoration; exceptions and shorter-timeout fallthrough remain unchanged.
- Other targeted OCR workloads are unchanged: Campaign 239, Ultimate Challenge
  104 and Resources 7 real calls per sample, with zero in daily-row claim.
- Real process-timeout/descendant cleanup tests and OCR worker holds are not
  virtualized. Interrupted worker holds are not counted as completed sleeps.

## CI overhead and correctness

Four whole-module execution shards per OS remain. Scheduling weights and
package/tool versions are unchanged; this is not another parallelism increase.

1. PR-number concurrency cancels superseded PR runs, not different PRs or main
   pushes. Artifacts remain scoped to the current run attempt.
2. Shard zero retains full Git history for immutable-base static checks and the
   three-dot diff. Other execution shards retain all current files/fixtures with
   depth-one history; no test selection changes.
3. Receipt-only aggregators sparse-checkout exactly the cost manifest and the
   two stdlib verifier/discovery modules. A real depth-one three-file checkout
   with Python site packages disabled accepts the baseline 3,169-case receipts
   on each OS and rejects missing, foreign and duplicate coverage.
4. The separate discovery-only invocation is removed; every shard still calls
   the same strengthened discovery validator before selection or execution.
5. Duplicate IDs now fail at both discovery and receipt validation, without
   silently deduplicating them. Only successful execution-job conclusions may
   enter aggregate receipt verification. The actual shell rejects failure,
   cancellation and skipping even when complete valid receipts are present.

The hosted comparison baseline is
[run 41956469267](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41956469267):

| Hosted baseline measurement | Linux | Windows |
| --- | ---: | ---: |
| Longest execution job | 712 s | 754 s |
| Summed execution-job durations | 2,221 s | 2,702 s |
| Aggregator checkout / complete job | 29 / 36 s | 34 / 45 s |

All ten baseline jobs sum to 5,004 runner-seconds. Final hosted step and job
comparisons are reported in PR #50, separately from instrumented local timings;
runner image, package-install and cache variability prevent attributing every
elapsed difference to this change.

## Hosted chronology-fixture follow-up

[Run 41971247527](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41971247527)
exposed a Personal Might recovery chronology error on Windows in a module
identical to the baseline. Both Windows clocks report 15.625 ms resolution;
zero-delay synthetic successors can tie. Equal successor UTC timestamps
deterministically reproduce the production rejection. The failed attempt is
retained, not retried to obtain green.

Only the synthetic original-action fixture now injects one shared advancing
event timeline into captures, UTC events, identity, leases and both policy clocks.
The production ordering checks and every original assertion remain unchanged.
Two additional negative subcases require the exact rejection for tied UTC and
tied monotonic successor timestamps, with zero recovery input and the unresolved
action retained. No test ID is added by these subcases.

The full 30-case module passes on both local OSes. A direct source-action and
recovery-proof smoke under completely flat underlying clocks also succeeds on
both: five strictly ordered native fixture captures, one original dispatch and
zero recovery input. Static ratchets remain unchanged.

## Coverage and scope decisions

Before the subsequent assertion-redundancy cleanup below, actual discovery was
240 modules: 3,169 original cases plus two new duplicate-ID rejection regressions,
for 3,171. That original pass removed or renamed no old ID. Its local Windows
symlink skip was unchanged. Hosted acceptance compares the existing 41 Linux /
36 Windows skip identities, not merely skip totals.

All 397 supported controlled checks and 58 native freshness/process-timeout
safety cases pass independently on both local OSes. The 11 discovery/receipt
regressions pass on both. Existing static ratchets remain unchanged: 440 active
Python files, 257 Ruff / 457 Vulture / 376 mypy findings. These are bounded debt,
not claims of a clean static analysis. Two independent read-only reviews found
no actionable defect in the gate/workflow and timing/OCR deltas.

During the original pass, no test deletion had an equally strong assertion
replacement map, so no tests were retired. The later owner-approved cleanup
below records its explicit maps and inventory delta. The eight fresh-process
Supply probes, sanitized controlled command, compilation, Git hygiene and both
OS gates remain. Native Enhancement proof is
not memoized for its three repeated inputs. Recruitment's expensive cooldown
case has zero measured OCR and completed sleeps. A subsequent single-case
profile attributes 27.8 of 30.0 seconds to nine eager Atlas-localizer constructors:
270 feature extractions, but no `localize` calls. This was a candidate rather
than an implemented optimization in the original pass; its implemented follow-up
is recorded below. Existing pip caching is retained; there is no speculative
installed-environment/Tesseract cache or extra runner.

## Follow-up: Windows critical-path work

Implemented and locally offline-proven; combined exact-head hosted proof is
reported in PR #50. The follow-up baseline is `26267ac`. The slower Windows
critical shard contained none of the five previously optimized modules. Its
runner image also differed from the historical comparison, so a code-caused
regression was not established. Log-derived durations attribute most of the
increase to unchanged integrated-route and Atlas-proposal modules.

The dominant synthetic integrated-route case spent almost all its profiled time
constructing unused native Atlas reference data. Only the unused Home-driver and
Noah localizer factories in that test class now return a test-only tripwire.
Any attribute use raises, and cleanup also rejects attempts swallowed by a
blocked-result handler. Ruins' separate current-frame localizer stays real.
Constructor arguments and the production injected-localizer flag are unchanged.

Three sequential fresh-process complete-module profiles per source and OS,
using unchanged OCR/sleep observers plus call profiling:

| `test_bluestacks_integrated_routes` | Windows before | Windows after | Linux before | Linux after |
| --- | ---: | ---: | ---: | ---: |
| Instrumented elapsed median | 104.890 s | 9.687 s | 97.073 s | 9.475 s |

Every run retains all 31 cases, two real current-frame native localizations and
six real OCR attempts. Localizer constructions fall from 34 to two; feature
extractions and image reads each fall from 1,022 to 62. No existing test body,
assertion, capture, timeout, production code or scheduling weight is changed.
A direct real-route mutation that swallows an accidental localization attempt
still fails at cleanup. Afterward, both constructor aliases are restored and a
fresh real localizer recognizes canonical Home with all 30 reference images on
both OSes. Raw measurements and the negative smoke remain outside the repository.

## Follow-up: Recruitment service fixture

Implemented and locally offline-proven; combined hosted acceptance is reported
in PR #50. The complete five-case module used 13 default Noah localizer
constructions and 390 reference feature extractions despite never localizing a
frame. Its Home driver and binding decisions were already explicitly scripted.
That unused factory now uses the same tripwire, without injecting a localizer
argument or changing the production flag that distinguishes injected localizers.
Native route objects, policy, ownership, accounting and captures still run.

| `test_service_recruitment` | Windows before | Windows after | Linux before | Linux after |
| --- | ---: | ---: | ---: | ---: |
| Instrumented elapsed median | 41.750 s | 3.422 s | 40.826 s | 6.102 s |

These are three sequential fresh-process complete-module samples per source and
OS. All original cases and outcomes remain; constructions, feature extractions
and reference image reads are now zero. Native localization and OCR remain
unused, not replaced by successful canned recognition.

A direct fixture-consumer smoke completes the real service's original action and
four inputs, but deliberately swallows an unexpected native-dependency error.
Both `serve` and cleanup still reject it. This covers consumers that use the
fixture directly without running its TestCase. The native constructor alias is
restored afterward. Both OSes also pass the 21 shared-fixture startup/rollover
cases, 58 true-timeout/freshness safety cases, 397 controlled checks and unchanged
static ratchets. Actual discovery remains 3,171 cases, with no added, removed or
renamed ID. Original integrated test bodies and per-case native OCR pixel/options
key multisets are unchanged.

## Remaining opportunities and rejected work

- Native Campaign reference preparation was subsequently implemented with fresh
  frame proof retained; its measurements and mutation checks are recorded below.
- The existing four-shard costs were subsequently recalibrated from current
  measurements, as recorded below. This balances latency without reducing work,
  changing the scheduler or adding runners.
- Investigate dependency/Tesseract setup only with observed cold/miss behavior
  and pinned compatibility. Existing pip caching is already enabled.
- Do not add the previous per-test OCR memo pattern to Campaign service tests:
  retained profiles show 239 actual calls and 239 per-test distinct input/options
  keys on each OS, leaving no same-test repeated work for that cache to remove.
- The later assertion audit established the explicit replacement maps below.
  No native timeout, stress repetition or runner count is reduced.

## Follow-up: native Campaign reference preparation

Implemented and offline-proven on Windows and Linux from baseline `5bd722f`.
Exact-head combined hosted acceptance is reported in PR #50. The actual-proposal
class already prepares a real Atlas localizer for its planning frames. Its case
context now reuses that real model only after checking full Atlas equality and
resolved manifest-path equality. The production dispatcher still independently
localizes and binds each immediate frame. No frame result, OCR result, policy
decision or transport result is cached or substituted.

Three sequential fresh-process complete-module samples per source and OS, using
the unchanged OCR/sleep observer and the same call profiler:

| Instrumented elapsed median | Before | After |
| --- | ---: | ---: |
| Windows | 25.453 s | 17.765 s |
| Linux | 28.989 s | 22.549 s |

| Actual work per complete module, identical on both OSes | Before | After |
| --- | ---: | ---: |
| Native localizer constructions | 3 | 1 |
| Feature extractions | 94 | 34 |
| Image reads | 126 | 66 |
| Fresh native localizations | 4 | 4 |
| Real OCR attempts | 72 | 72 |

All three original test bodies and assertions remain unchanged. Per-case exact
OCR pixel/options multisets match across all six samples on each OS. Constructor
validation still runs when the class prepares its real model; the dispatch-time
factory guard rejects a changed Atlas or manifest rather than reusing mismatched
reference data. The localizer's reference state is read-only on this call path,
not a new production cache or shared mutable route state.

Actual native-route smokes on both OSes reject stale planning localization and
binding before capability issuance/input, and reject a valid native-sized
featureless immediate frame through real localization. The unchanged native-pair
test fails when a mutation copies the planning ROI but retains the fresh digest.
Reference images, keypoints, descriptors, transforms and nested Atlas data remain
unchanged across normal and failing cases. Constructor aliases restore after
both exit paths, and a subsequent normal native dispatch still succeeds.
Independent source review found no actionable defect. Raw profiles, observer
records and mutation outputs are retained outside Git; no live acceptance is
claimed.

## Follow-up: measured four-shard recalibration

Implemented with actual discovery/partition/selection proof on both local OSes.
Exact-head hosted results and job timings are reported in PR #50. The scheduler,
four-shard count, whole-module ordering, workflow checks and skip allowlists are
unchanged; only the existing cost manifest is recalibrated.

The baseline is successful hosted run
[41984856343](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41984856343)
at `5bd722f`. The parser reconciles every selected/executed ID and completion,
including docstring headers whose completion appears on a later line. Whole-module
intervals include fixture work and reconcile to each authoritative unittest
elapsed total; discovery and other workflow steps are excluded. These are
scheduling estimates, not exact individual-test profiles.

Each shared module weight is the rounded mean of its Windows and Linux estimate.
Only native Campaign is adjusted by its measured local before/after module ratio.
The manifest's source revision is native-only commit `3aaa0e6`; all other module
work is unchanged from the hosted baseline. All 240 modules now have explicit
estimates, including `tests.test_static_checks`, which previously used the
one-second unknown-module fallback. Future modules still use the existing
fallback and remain automatically discovered.

The primary-shard reservation uses the mean per-OS excess of job time outside the
discovery-suite step over the median corresponding nonzero-shard residual:

| Primary-shard reservation measurement | Seconds |
| --- | ---: |
| Linux observed excess | 318 |
| Windows observed excess | 348 |
| New shared reservation | 333 |

Old and new assignments evaluated against the same candidate module estimates
and reservation give these projected peaks. Common job overhead is excluded;
these are not measured post-change CI durations.

| Model peak, seconds | Old assignment | Recalibrated assignment |
| --- | ---: | ---: |
| Linux | 458.733 | 387.706 |
| Windows | 603.182 | 494.187 |

Both OSes' actual runner discovery/partition/selection paths conserve all 3,171
IDs and 240 whole modules exactly once. Case counts per shard are 620/834/727/990;
174 modules move without splitting class/module fixtures. The existing 11
discovery/receipt tests, 58 freshness/timeout cases, 397 controlled cases and
unchanged static ratchets pass on both OSes. Independent review found no
actionable defect in the manifest or native-reference change.

One hosted baseline cannot establish statistical timing guarantees. Predecessor
teardown can be attributed to the next module, the native adjustment transfers
local ratios to hosted estimates, and setup/image variance affects the measured
reserve. Final hosted execution must prove the new co-location preserves actual
coverage and outcomes. Full timing derivation, module migrations, simulations and
raw logs remain outside Git; no assertion, timeout, skip, test ID or safety gate
is weakened.

## Follow-up: approved assertion-redundancy cleanup

Implemented, test-only and locally offline-proven; complete exact-head hosted
Windows/Linux results are reported in PR #50. This is a later owner-approved
change to the original pass's no-retirement scope, not an unexplained inventory
loss. Production code, weights, skip allowlists and workflow gates are unchanged.

| Actual discovered scope | Before cleanup | After cleanup |
| --- | ---: | ---: |
| Test modules | 240 | 240 |
| Complete discovery cases | 3,171 | 3,159 |
| Supported controlled-command cases | 397 | 395 |
| Added or renamed IDs | 0 | 0 |

The only removed IDs are the twelve mapped below. The controlled command keeps
the same 22-module selection; its two retired cases have retained replacements
inside that same selection. The two duplicate-discovery regressions remain.
All native recognition, variant/mutation rows, recovery-count rows and eight
fresh-process Supply repetitions remain.

### Exact retirement map

1. `tests.test_perception_bundle.PerceptionBundleTests.test_checked_navigation_rejects_noncanonical_zoom`
   → `tests.test_perception_bundle.PerceptionBundleTests.test_checked_navigation_rejects_unknown_context`.
   Identical zoomed-in localization, frame validation, navigation consumer and
   accepted denial reasons; the retained case also asserts `UNKNOWN` context.
2. `tests.test_perception_bundle.PerceptionBundleTests.test_serialized_bundle_retains_no_numpy_frame`
   → `tests.test_perception_bundle.PerceptionBundleTests.test_versioned_deterministic_evidence_snapshot_matches_fixture`.
   Same bundle and serializer. The retained case compares the complete fixture,
   pins schema name/version and now explicitly rejects `dtype` as well as
   `numpy`/`ndarray`.
3. `tests.test_flow_delivery_troop_training.TroopTrainingFlowDeliveryTests.test_live_canary_admission_allows_four_total_with_zero_prior_dispatch_evidence`
   → `tests.test_flow_delivery_troop_training.TroopTrainingFlowDeliveryTests.test_live_canary_admission_uses_full_count_boundary`.
   The retained zero-prior row has the same lease, clean artifact root,
   capture-only child result and `dispatch_count == 0` assertion. The configured
   cap remains explicitly one; the old name did not assert four.
4. `tests.test_flow_delivery_troop_training.TroopTrainingFlowDeliveryTests.test_live_canary_admission_rejects_one_prior_dispatch_evidence`
   → `tests.test_flow_delivery_troop_training.TroopTrainingFlowDeliveryTests.test_live_canary_admission_uses_full_count_boundary`.
   The retained one-prior row requires the same `maximum-live-canary` rejection
   before child execution. Dispatch-event counting ignores the differing
   incidental prior-directory and action-key spellings. Both boundary rows stay.
5. `tests.test_nova_praise_centralized_boundary.CentralizedNovaBoundaryTests.test_at_most_one_praise_transport`
   → `tests.test_nova_praise_centralized_boundary.CentralizedNovaBoundaryTests.test_live_boundary_prepares_dispatches_and_confirms_exact_decrement`.
   Same setup and invocation; all confirmed/one-transport/one-tap/one-capture
   assertions remain, plus exact decrement, lifecycle and persisted due state.
6. `tests.test_nova_praise.NovaPraiseContractTests.test_attempt_counting`
   → existing consumer cases, not another fixture echo:
   `tests.test_nova_praise.NovaPraiseContractTests.test_one_attempt_decrement_and_cooldown_postcondition`,
   `tests.test_nova_praise.NovaPraiseContractTests.test_repeat_until_zero`,
   `tests.test_nova_praise.NovaPraiseContractTests.test_next_eligible_scheduling_yields`,
   and the unchanged native counter cases.
   The retired body only constructed/read dataclass values seven and zero; it
   never invoked counting, parsing, persistence or a transition.
7. `tests.test_gameplay_flow_contracts.GameplayFlowContractTests.test_schema_file_exists`
   → `tests.test_gameplay_flow_contracts.GameplayFlowContractTests.test_published_schema_accepts_all_representative_contracts`.
   The retained case reads/parses the same schema and validates all ten
   representative contracts. The module's required dependency is unconditional;
   there is no optional-dependency skip that bypasses this replacement.
8. `tests.test_automation_service_scheduler_canonical.CanonicalSchedulerTests.test_only_reset_scoped_descriptors_roll_reset_state`
   → `tests.test_automation_service_scheduler_canonical.CanonicalSchedulerTests.test_mf1_recurrence_bindings_use_canonical_occurrence_identity`.
   Its timer row already retains the same descriptor, facts, candidate and claim
   kind, with exact occurrence key/basis and a result. It now also changes reset
   identity and requires no second result, no second handler execution and no
   new or altered persisted run. The removed mock wrapper asserted no reset
   behavior; the stronger check exercises the actual coordinator and database.
9. `tests.test_resource_effect_authority_store.ResourceAuthorityStoreTests.test_future_schema_remains_fail_closed`
   → `tests.test_safe_action_core.StoreCase.test_future_schema_rejected`.
   Both create the same separate version-99 SQLite database and require
   `SchemaVersionError` from `SafetyStore`. The retired resource authority setup
   used an unrelated database. Core-store tests own this constructor invariant;
   both modules remain selected by the controlled command.
10. `tests.test_supply_depot_verified_route.SupplyDepotVerifiedRouteTests.test_normal_claim_remains_denied_by_navigation_capability_firewall`
    → `tests.test_supply_depot_verified_route.SupplyDepotVerifiedRouteTests.test_zero_claim_consequential_controls_remain_denied`.
    The same pure guard, radial observation, navigation class, claim semantic and
    exact consequential-denial reason remain in the first loop row. The other
    semantic labels and claim-consequence rejection remain too.
11. `tests.test_home_context.HomeContextTests.test_primitives_digest_is_stable_hex`
    → `tests.test_gameplay_flow_contracts.GameplayFlowContractTests.test_nova_contract_separates_live_proof_from_production_eligibility`.
    The same imported digest retains its exact length-64 assertion alongside its
    dependency declaration. Canonical contract validation now owns this check:
    a HomeContext-only invocation no longer includes it; full discovery does.
    The required developer dependencies include the receiving module's
    `jsonschema` dependency. Neither module is in the controlled selection.
12. `tests.test_home_atlas_verified_route.HomeAtlasVerifiedRouteTests.test_regression_module_imports`
    → the same module's unconditional imports and full discovery's import-error
    gate. All six imports already occur while this test module and
    `scripts.home_atlas_bluestacks` load, even in a focused module invocation.
    The retired body only repeated cached imports and had no assertions.
    `importlib` remains needed by a separate issuance-observation case.

### Stronger proof and remaining limits

All 318 cases in the touched modules plus core-store ownership module pass on
local Windows, with the five existing skips. A separate process-launch-blocked
smoke executes all 13 selected retained cases and conserves the exact full
discovery ID delta, with no skipped smoke case or process-launch attempt.

An in-memory fault that incorrectly rebases a timer slot when reset identity
changes is rejected by the strengthened timer row: it detects the resulting
second execution. No production source is mutated. Full OS execution, exact
skip-ID conservation, static budgets and current-attempt receipts remain
required hosted gates; their exact-head results are recorded in PR #50.

No high-cost native OCR case was established as redundant, and no hosted runtime
saving is claimed for these retirements. The six parameterization-only groups
from the audit are not changed. The separate wall-clock freshness-test weakness
also remains outside this twelve-case cleanup. The existing Windows performance
hold is unchanged.

Removing the unused timer-test mock binding also shrinks its Ruff `F841`
allowance from two to one. Actual Ruff findings fall from 257 to 256; Vulture
remains 457 and mypy 376 over the same 440 active Python files. No allowance is
raised or transferred to another file or code.

## Follow-up: wall-clock freshness proof

Implemented and locally offline-proven; exact-head Windows/Linux hosted results
are recorded in PR #50. No production behavior or test ID changes.

The old wall-clock test compared two identical policy denials. Its OCR capture
timestamp did not match its frame timestamp, so both evaluations returned
`INVALID_PERCEPTION_BINDING` rather than exercising an authorized fresh frame.
The retained method now binds both timestamps to the same capture and varies
wall time forward and backward by a day. At each wall time it checks authorization
for a fresh frame and the exact two-second dispatch-age boundary, plus
`STALE_FRAME` rejection immediately beyond the boundary and for a future capture.

The complete 17-case module passes locally. A throwaway policy mutation that
uses wall time instead of the supplied monotonic time survives the old assertion
but fails all six fresh-frame subcases in the strengthened test. Production code
and shared clock functions are restored after the smoke; no mutation is retained.
The separate Windows code-regression hold was subsequently resolved by the
matched full-assignment comparison recorded below.

## Follow-up: Windows survey fixture chronology

The first matched-assignment diagnostic is retained as failed and is not timing
evidence. Its custom TEMP volume lacked the Windows short aliases available to
the canonical run, and its timing collector included nested fixture executions.
Both are diagnostic-harness defects, not permission to accept new skips.

That attempt also exposed a timing-sensitive synthetic survey case. Under a flat
host monotonic clock, its supposed later capture tied the planning timestamp.
The unchanged executor correctly returned `IMMEDIATE_RECAPTURE_NOT_FRESH` with
zero transport instead of exercising the intended unexpected-successor path.
Only that case now shares the existing test `Clock` between synthetic captures
and the module-local survey clock. All original assertions remain. An additional
tied-capture subcase requires the exact cancellation reason and zero transport.
No real sleeps, production timing checks or permanent test IDs change.

The two complete touched modules pass locally: 64 cases, no skips. A flat-host-clock
smoke now proves one unresolved transport for the distinct-capture scenario and
zero transport for deliberately tied captures. The corrected diagnostic retains
canonical TEMP-volume behavior and selects the outer execution result by its
actual receipt IDs; nested fixture bodies still run but cannot inflate timing
coverage. The frozen-source comparison and final hosted proof remain recorded
separately in PR #50.

## Follow-up: matched hosted Windows performance disposition

The corrected [comparison run 42119774106](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/42119774106)
passed all four jobs using frozen source `5018a92`. Every VM ran both the
pre-recalibration weights from `3aaa0e6` and the current weights, with order
counterbalanced across the four VMs. Each assignment used separate fresh source
worktrees, processes and canonical-volume TEMP directories. Package installation
and initial checkout were shared, not attributed to scheduling.

Both assignments passed the canonical receipt verifier: exactly 3,159 IDs once,
the same 36 Windows skips, no failures/errors/new skips. Actual per-case timings
match only the outer receipt IDs; nested fixture bodies remain real. Shard zero
keeps all eight native Supply repetitions, static ratchets, the supported
395-case command, compilation and whitespace checks for each assignment.

| Matched check/test phase, seconds | Old weights | Recalibrated weights |
| --- | ---: | ---: |
| Longest phase across four shards | 603.174 | 577.768 |
| Sum of four phases | 2,159.034 | 2,070.435 |
| Sum of suite subprocess times | 1,813.725 | 1,726.991 |

The measured phases exclude shared setup and per-mode source checkout. These
are one counterbalanced pair, not two complete independent workflow-duration
samples or a statistical guarantee. Both the longest phase and aggregate measured
time improve, satisfying the rule frozen before the run. Retain the recalibrated
weights; no further tuning, runner addition, timeout reduction or test retirement
is part of this follow-up. The code-regression hold is cleared, not the draft or
required-review gates.

The same Campaign AP module runs on the same VM in both assignments: its 31
case durations, including per-case fixtures, sum to 82.601 and 82.893 seconds. The ordering change does
not reproduce the historical approximately 181.6-second log-derived estimate.
This corroborates the earlier isolated ordering probe without treating log
timestamps as precise per-case clocks.

Actual hosted hardware varies even within this one matrix: AMD EPYC 7763,
Intel Xeon Platinum 8370C and AMD EPYC 9V74, with Windows images
`20261030.294.1` and `20261103.298.1`. Matching each before/after pair to the same
VM controls that variation for this comparison; it does not recover old resource
traces. Historically the longest Windows job increased by 41 seconds while its
suite phase fell by 32, leaving 73 seconds of increase outside the suite. That
is arithmetic across different longest jobs, not proof of a specific host cause.
The original host-level CPU/resource attribution remains `evidence_required`;
no historical receipt or failed experiment is relabeled as successful.

Full canonical Windows/Linux correctness for the frozen source passed
[run 42119600618](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/42119600618),
with all ten jobs green, all 3,159 IDs once per OS, and the unchanged 41 Linux /
36 Windows skip identities. Final-head canonical proof is linked from PR #50.
The temporary diagnostic is retired after preserving its source, logs, hardware,
case timings and receipts outside the working tree and in immutable Git history.

## Final-review native OCR evidence hold

[Run 42167899112](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/42167899112)
failed the unchanged native exhausted-Supply recognition case on Windows. Its
`ocr_invalid_title` result hides the underlying semantic OCR reason; the retained
log cannot distinguish deadline, worker, engine or provenance failure. Independent
source reviews found no attributable regression in the CI optimization delta.
The failed run is non-accepting; its underlying cause remains `evidence_required`.

That case now retains real semantic OCR status, reason and elapsed time in its
failure context. Recognition assertions, source PNG and identity, real OCR engine,
worker ownership, deadline and skip controls are unchanged. The complete 24-case
Supply vision module passes locally; an injected worker deadline still fails
the original positive assertion and exposes `OCR_DEADLINE`. Neither result closes
the hosted evidence hold or authorizes a retry of a consequential live action.
