# Measured CI efficiency pass

Implemented and locally offline-proven; not live acceptance. No device access,
production route behavior, timeout, scheduling or deployment change is included.
This records local measurements; exact-head hosted proof and current-attempt
receipts are linked from [PR #50](https://github.com/mattebad/Puzzles_Survival_Automation/pull/50).
Local timing improvements do not substitute for its complete hosted checks.

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

Actual discovery remains 240 modules: 3,169 old cases plus two new duplicate-ID
rejection regressions, for 3,171. No old ID is removed or renamed. The local
Windows symlink skip is unchanged in all targeted samples. Hosted acceptance
must preserve the existing 41 Linux / 36 Windows skip identities, not merely
match skip totals.

All 397 supported controlled checks and 58 native freshness/process-timeout
safety cases pass independently on both local OSes. The 11 discovery/receipt
regressions pass on both. Existing static ratchets remain unchanged: 440 active
Python files, 257 Ruff / 457 Vulture / 376 mypy findings. These are bounded debt,
not claims of a clean static analysis. Two independent read-only reviews found
no actionable defect in the gate/workflow and timing/OCR deltas.

No test deletion had an equally strong assertion replacement map, so no tests
were retired. The eight fresh-process Supply probes, sanitized controlled suite,
compilation, Git hygiene and both OS gates remain. Native Enhancement proof is
not memoized for its three repeated inputs. Recruitment's expensive cooldown
case has zero measured OCR and completed sleeps. A subsequent single-case
profile attributes 27.8 of 30.0 seconds to nine eager Atlas-localizer constructors:
270 feature extractions, but no `localize` calls. Avoiding unused construction in
that already-faked fixture is a concrete next candidate, not an implemented or
verified optimization in this pass. Existing pip caching is retained; there is
no speculative installed-environment/Tesseract cache or extra runner.

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
