# Issue #47: offline suite cost and coverage

Implemented scope: test execution, fixture OCR reuse and CI scheduling only. This
is offline proof, not live acceptance. Runtime input authority, registration,
scheduling, production recognition and timeout values are unchanged.

## Baseline and measurement

Source: `93cab54836b2f88947aab4712e169a4a9abc1dca`, the combined #24/#30
integration. Both profiles execute all 239 modules / 3,160 cases without failures
or errors. The existing per-module sweep is reused with a temporary observer;
no profiling framework or production instrumentation is added.

| Profile environment | Module seconds summed | Tesseract attempts | Unique exact OCR inputs | Completed sleep seconds | Interrupted sleeps | Skips |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Windows, Python 3.12, Tesseract 5.5.0 | 1,626.071 | 4,151 | 2,106 | 49.831 | 80 | 43 |
| Docker Linux, Python 3.11, Tesseract 5.5.0 | 1,660.136 | 4,130 | 2,097 | 50.094 | 2 | 41 |

[Every case's measurements](per-test-profile.csv) include elapsed test time,
Tesseract attempts, exact-input cardinality, completed sleep count/elapsed time,
and interrupted sleep count on each OS. Module timing also includes fixture and
loading costs outside individual test bodies. Calls are observed at the real
`pytesseract.engine.run_tesseract` boundary, after existing mock/memo boundaries;
attempts include calls that hit a deadline. Exact OCR identity includes encoded
input bytes, output extension, language, config and nice value. No OCR result is
substituted by the observer. Sleeping workers killed after returning a result
have a durable start but no end: their requested 60 seconds are not reported as
60 seconds of suite cost. Interrupted sleep duration is unmeasured.

Hosted skip baselines come from the actual verbose logs, not the local profile:
41 Linux IDs and 36 Windows IDs in
[run 41937776289](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41937776289).
Both full suites and controlled checks pass there; the overall run fails only
on retained CRLF receipt whitespace. `7eca65b` fixes that with path-specific
attributes while retaining proof bytes and real trailing-space checks.

## Every module at or above ten seconds on either OS

`recognition` retains native pixel/recognizer proof. `accounting` retains route,
control, causal-evidence or consumption/transition assertions, including mixed
integration tests. No remaining module is retired or classified as a redundant
replacement: no equally strong per-assertion replacement map was established.

| Module (`tests.test_` prefix) | Windows s | Windows OCR / unique | Linux s | Linux OCR / unique | Sleep s W / L | Class | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `bluestacks_integrated_routes` | 124.56 | 6 / 6 | 112.45 | 6 / 6 | 0.00 / 0.00 | accounting | Keep distinct safety/transition assertions; shard. |
| `service_campaign_ap` | 83.97 | 239 / 239 | 90.19 | 239 / 239 | 21.01 / 21.06 | accounting | Keep distinct safety/transition assertions; shard. |
| `bluestacks_ultimate_challenge` | 64.11 | 104 / 104 | 64.46 | 104 / 104 | 7.21 / 7.22 | accounting | Keep distinct safety/transition assertions; shard. |
| `bioenhancer_home_entry_binding` | 44.34 | 32 / 32 | 57.48 | 32 / 32 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `personal_might_bluestacks` | 49.95 | 107 / 107 | 46.39 | 107 / 107 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `supply_depot_vision` | 47.44 | 88 / 78 | 49.12 | 84 / 74 | 0.00 / 0.00 | recognition | Keep fresh OCR and the repeated CI probe. |
| `campaign_ap_hud_native` | 38.58 | 156 / 156 | 47.21 | 156 / 156 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `service_recruitment` | 45.02 | 0 / 0 | 45.61 | 0 / 0 | 0.00 / 0.00 | accounting | Keep distinct safety/transition assertions; shard. |
| `campaign_tier_controls` | 39.95 | 176 / 176 | 44.46 | 176 / 176 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `nova_startup_recovery` | 37.47 | 70 / 70 | 41.69 | 70 / 70 | 0.00 / 0.00 | accounting | Keep distinct safety/transition assertions; shard. |
| `home_base_vision` | 32.22 | 180 / 120 | 37.53 | 178 / 119 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `service_enhancement` | 32.27 | 54 / 54 | 31.35 | 54 / 54 | 8.01 / 8.02 | accounting | Keep distinct safety/transition assertions; shard. |
| `service_supply` | 28.09 | 100 / 100 | 31.73 | 100 / 100 | 0.00 / 0.00 | accounting | Keep distinct safety/transition assertions; shard. |
| `enhancement_semantic_stage_mapping` | 28.92 | 104 / 30 | 23.56 | 104 / 30 | 0.00 / 0.00 | accounting | Existing exact-input memo; no cases removed. |
| `enhancement_item_modal_native` | 27.56 | 127 / 127 | 28.44 | 126 / 126 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `enhancement_category_resume` | 27.08 | 0 / 0 | 19.23 | 0 / 0 | 0.00 / 0.00 | accounting | Keep distinct safety/transition assertions; shard. |
| `enhancement_selection_context_native` | 25.09 | 142 / 142 | 26.50 | 137 / 137 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `home_atlas_campaign_actual_proposal` | 26.33 | 72 / 44 | 25.49 | 72 / 44 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `home_atlas_pan_actual_proposal` | 25.16 | 27 / 27 | 24.70 | 27 / 27 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `nova_navigation` | 21.81 | 56 / 56 | 24.88 | 56 / 56 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `campaign_exit_binding` | 19.34 | 98 / 55 | 23.33 | 98 / 55 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `supply_claim_button` | 19.22 | 59 / 40 | 22.75 | 61 / 42 | 0.00 / 0.00 | recognition | Keep fresh OCR and the repeated CI probe. |
| `flow_delivery_daily_resource_item_bluestacks` | 16.59 | 25 / 4 | 21.92 | 25 / 4 | 0.00 / 0.00 | accounting | Existing exact-input memo; no cases removed. |
| `enhancement_chip_quantity_native` | 20.09 | 101 / 101 | 21.61 | 100 / 100 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `campaign_home_ap_five_native` | 16.25 | 65 / 44 | 20.32 | 65 / 44 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `enhancement_chip_modal_native` | 17.20 | 109 / 64 | 18.56 | 109 / 64 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `enhancement_module_quantity_native` | 17.56 | 82 / 82 | 18.46 | 81 / 81 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `campaign_home_direct_entry_pan` | 18.05 | 46 / 46 | 17.74 | 46 / 46 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `enhancement_chip_panel_native` | 16.58 | 103 / 53 | 17.70 | 103 / 53 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `research_lab_home_entry_binding` | 15.03 | 48 / 16 | 16.79 | 48 / 16 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `home_atlas_planner` | 15.22 | 0 / 0 | 16.09 | 0 / 0 | 0.00 / 0.00 | accounting | Keep distinct safety/transition assertions; shard. |
| `startup_recovery` | 15.38 | 53 / 53 | 15.62 | 53 / 53 | 2.30 / 2.45 | accounting | Keep distinct safety/transition assertions; shard. |
| `enhancement_module_modal_native` | 14.70 | 73 / 73 | 15.39 | 73 / 73 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `ultimate_defeat_recovery` | 15.14 | 79 / 21 | 12.63 | 79 / 21 | 0.00 / 0.00 | accounting | Keep distinct safety/transition assertions; shard. |
| `flow_delivery_enhancement` | 15.09 | 11 / 8 | 10.28 | 11 / 8 | 0.00 / 0.00 | accounting | Keep distinct safety/transition assertions; shard. |
| `enhancement_module_panel_native` | 14.56 | 62 / 62 | 14.76 | 61 / 61 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `noahs_tavern_recruit` | 14.02 | 30 / 15 | 13.10 | 30 / 15 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `native_frame_mutation` | 12.84 | 0 / 0 | 13.99 | 0 / 0 | 0.00 / 0.00 | accounting | Keep distinct safety/transition assertions; shard. |
| `campaign_home_hud_waypoint` | 12.19 | 36 / 18 | 13.24 | 34 / 17 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `campaign_stage_dialog_native` | 12.95 | 80 / 80 | 12.40 | 80 / 80 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `service_application_startup` | 12.72 | 0 / 0 | 10.79 | 0 / 0 | 0.00 / 0.00 | accounting | Keep distinct safety/transition assertions; shard. |
| `campaign_victory_native` | 12.67 | 57 / 57 | 12.36 | 57 / 57 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `enhancement_home_native` | 11.09 | 68 / 37 | 12.43 | 64 / 36 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `campaign_lineup_current` | 12.34 | 55 / 55 | 12.10 | 55 / 55 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `service_ultimate` | 12.16 | 0 / 0 | 9.16 | 0 / 0 | 0.00 / 0.00 | accounting | Keep distinct safety/transition assertions; shard. |
| `enhancement_positive_recovery_delivery` | 12.14 | 0 / 0 | 6.47 | 0 / 0 | 0.00 / 0.00 | accounting | Keep distinct safety/transition assertions; shard. |
| `atlas_flow_startup` | 9.02 | 53 / 43 | 11.40 | 51 / 42 | 0.00 / 0.00 | accounting | Keep distinct safety/transition assertions; shard. |
| `enhancement_module_selection_native` | 11.23 | 83 / 26 | 9.89 | 83 / 26 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `enhancement_quantity_modal_native` | 10.98 | 80 / 22 | 10.04 | 80 / 22 | 0.00 / 0.00 | recognition | Keep real recognition; whole-module shard. |
| `campaign_lineup` | 10.16 | 44 / 44 | 9.73 | 44 / 44 | 0.00 / 0.01 | recognition | Keep real recognition; whole-module shard. |

## Changes and conservation

- Reuse the existing `tests.ocr_memo.install_module_memo` in daily-resource-item
  delivery and Enhancement causal-stage replay. Every distinct input still runs
  real Tesseract; cache lifetime is one module, misses remain Tesseract-gated,
  exceptions are not cached, and the existing timeout compatibility rule stays.
  No recognizer, result assertion or case is removed.
- Do not add an OCR memo to Recruitment: its measured service module makes no
  Tesseract calls. Do not mock recognition to make the other modules fast.
- Strengthen the development-session budget fixture with fresh final-frame pixels
  and an unchanged-transport-count assertion. Otherwise the duplicate-frame fence
  masks a budget off-by-one. All original budget and cash-confirmation pins remain.
- Add six execution-coverage tests to the existing discovery module: new modules,
  missing/repeated/unexecuted cases, reservation balancing, real module/class
  fixture lifecycle, new skips even at unchanged totals, and foreign revisions.
  Case inventory changes from 3,160 to 3,166; no old ID is removed or renamed.

## Measured memo changes

All cases in each complete module pass without skips before and after. Unique
inputs remain real OCR, not mocked outputs.

| Module (`tests.test_` prefix) | OS | Cases | Before OCR | After OCR | Unique inputs | Before s | After s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `flow_delivery_daily_resource_item_bluestacks` | Windows | 19 | 25 | 4 | 4 | 16.59 | 4.56 |
| `flow_delivery_daily_resource_item_bluestacks` | Linux | 19 | 25 | 4 | 4 | 21.92 | 5.00 |
| `enhancement_semantic_stage_mapping` | Windows | 14 | 104 | 30 | 30 | 28.92 | 20.00 |
| `enhancement_semantic_stage_mapping` | Linux | 14 | 104 | 30 | 30 | 23.56 | 12.70 |

## CI layout and gates

Four whole-module shards run on **each** OS for every PR. Scheduling uses the
slower measured OS cost per module, with 400 seconds reserved on shard zero for
the repeat probe, controlled check and hygiene checks. New modules are discovered
and assigned automatically with a default cost; the timing JSON is not an allowlist.
The normal full-discovery developer command is unchanged:

```sh
python -B -m unittest discover -v -s tests -t .
python scripts/check.py
```

Each receipt records the discovered, selected and actually started case IDs,
run count, result, skips, platform and `GITHUB_SHA`. The existing per-OS
`Offline checks` status names are retained as aggregators. They require all four
successful receipts, exact execution-multiset equality with complete discovery,
matching revision/platform and no skip IDs outside that OS's hosted baseline.
A missing artifact, empty/partial run, duplicated case, failed fixture or new skip
cannot produce a green aggregate. Discovery validation runs inside every shard.
The controlled check, compilation, line-ending and whitespace checks remain on
both OSes, on shard zero. No test selection is removed.

Artifacts are scoped to `github.run_attempt`; **rerun all jobs**, not only failed
shards, to produce a complete new attempt. Old receipts cannot fill missing shards.
Sharding reduces wall-clock latency, not total billed CPU; the two exact-input
memo additions reduce repeated OCR work. Target: under 15 minutes per execution
job. Hosted after-change timing remains `evidence_required` until actual CI runs.

## Supply repeat decision

Keep the existing five-case, eight-fresh-process probe on both OSes. Retained
failures demonstrate a real deadline mode, but do not establish that eight is a
statistically necessary count. Conservatively preserve the accepted stress
coverage and balance its measured cost instead of weakening it:

- [CI 48](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41256325360)
  and [CI 54](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41261090984):
  Linux fails in the first repetition on real Supply binding deadlines.
- [CI 82](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41402574839):
  Windows fails in the first repetition; Linux completes all eight.
- [CI 83](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41403793774)
  succeeds after parent `OMP_THREAD_LIMIT=1` is set before OCR startup.
- No late-iteration Supply failure was observed in the inspected retained logs;
  no flake probability or deadline root cause is inferred from that absence.

## Fault sensitivity

Scratch mutations are isolated from the implementation and restored afterward.

| Fault | Observed rejection |
| --- | --- |
| Remove only flow/service generation predicates, retaining other fences | Pure flow-generation and pure service-generation checks each fail all eight routes; the disable/reenable-only check still passes |
| Unblock a partial result instead of retaining the block | All eight partial-result subtests fail the blocked-flow assertion |
| Remove only the exact WINNER title gate, retaining Loot/Continue gates | Both real WINER and LOSER frame subtests fail |
| Change input budget `>=` to `>` | Fresh-frame case dispatches two fake Back inputs after one tap with budget two; expected rejection is absent |

All six affected methods pass on restored production code. The generation,
partial-result and budget checks run with all process-launch paths forbidden;
the title probe uses real offline fixture OCR. No device or live operator is used.

## Verification state

- All 67 cases in the four changed test modules pass on Windows and Linux,
  without skips.
- Actual CLI execution discovers all 239 modules / 3,166 cases. Comparison to
  the complete baseline IDs shows no removed or renamed case, exactly the six
  new discovery-helper cases.

| Actual shard-zero smoke | Executed cases | Skips | Receipt elapsed s |
| --- | ---: | ---: | ---: |
| Windows | 541 | 9 | 100.538 |
| Linux | 541 | 10 | 102.958 |

- Both real shard receipts have identical selected/executed ID multisets.
  Synthetic real TestCases also execute across two shards exactly once; an
  incomplete receipt set is rejected.
- Hosted complete execution, no-new-skip comparison and after-change job timing
  remain `evidence_required` until CI completes. Local shard proof is not a claim
  that all 3,166 cases have already passed on the new tree.
