# Issue #24 validation

Implemented: complete offline discovery and coverage enforcement on Windows and
Linux (Python 3.11+). macOS is best-effort; unsupported OCR-worker tests skip with
a reason. This summary records offline proof, not runtime authorization.

## Before and after

Baseline `d4dd8db` has 235 modules / 3,135 methods. At `8062002`, there are
238 modules / 3,171 methods: four mapped renames, 36 added cases, no unmapped
removals. Baseline full discovery fails before collection because `tests` was not
importable; its per-module results below are not full-discovery passes.

| OS | Baseline isolated tests; failures/errors; skips | Candidate full tests; failures/errors; skips | Full without Tesseract tests; failures/errors; skips |
| --- | --- | --- | --- |
| Linux | 3,135; 15/31; 38 | 3,171; 0/0; 41 | 3,171; 0/0; 490 |
| Windows | 3,135; 13/30; 34 | 3,171; 0/0; 36 | 3,171; 0/0; 486 |
| macOS (best-effort) | 3,135; 42/374; 37 | 3,171; 0/0; 68 | 3,171; 0/0; 506 |

These are the source-labelled observations from
[diagnostic run 41821066333](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41821066333).
Its overall result is red because it also runs the failing historical baseline.
The corrected required [CI run 41848027282](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41848027282)
is green on Windows and Linux at `8062002`, including eight five-case Supply
passes per OS. Full discovery uses `python -B -m unittest discover -s tests -t .`;
`scripts/check.py` additionally exercises its controlled environment in both CI jobs.

## Review-fixup proof

`b7f028c` restores the exact Enhancement and Campaign assertions and adds the
owner-approved duplicate-pending guard. `aadb83f` removes raw proof dumps and
restores the controlled CI check. Exactly two Enhancement behavioral tests are
added; no test is removed or renamed. Collection remains 238 modules.

| Environment | Before review methods | After full tests | Failures/errors | Skips | Full seconds |
| --- | ---: | ---: | --- | ---: | ---: |
| Windows, Python 3.12 / Tesseract 5.5.0 | 3,171 | 3,173 | 0/0 | 43 | 1,829.434 |
| Linux, Docker Python 3.11 / Tesseract 5.5.0 | 3,171 | 3,173 | 0/0 | 41 | 1,851.822 |

Both touched modules pass together: 56 tests, zero failures/errors/skips.
The unchanged `scripts/check.py` passes 397 tests with zero failures/errors/skips
on each OS. An actual offline recovery-selector smoke rejects duplicate sources
without changing state bytes or creating reservations.

## Module classification

Classes: **a** stale contract/fake, **b** production defect, **c** environment,
**d** deliberately retired code and tests. The complete original `f6b201f`
23-module list is published in [PR #40's baseline comment](https://github.com/mattebad/Puzzles_Survival_Automation/pull/40#issuecomment-6612004645).
The earlier 16-name summary was incomplete. These rows account for the published
original inventory, not a reconstruction from later baseline failures.

| Published historical module | Class | Resolution |
| --- | --- | --- |
| `test_automation_service_boundaries` | c | Unsupported Darwin OCR worker; only worker-dependent methods use `requires_ocr_worker` (`adf5654`, `5d4ca3e`). |
| `test_flow_delivery_authority_consistency` | d | Retired orchestration registry/queue and its parity check (`00d2114`); canonical authority tests remain. |
| `test_navigation_runner` | d | Active profile unified (`96aa8d5`); dead runner and test removed (`4a0453d`). |
| `test_pnsctl_nova_praise` | d | Retired development command and tests (`d29972b`); current Nova service/pulse coverage remains. |
| `test_flow_delivery_enhancement` | a | Current-reset, causal-linkage and successor fixtures migrated (`46346f1`, `d2d63d8`); review restores exact safety assertions. |
| `test_flow_delivery_bioenhancer_bluestacks` | a | Fake supplies real pan planner's `safe_region` and `calibration` (`12d3acd`). |
| `test_flow_delivery_evidence_integrity` | c | Temporary evidence fixtures replace dependence on private captures (`b616086`). |
| `test_flow_delivery_token_context_hygiene` | d | PowerShell-dependent retired orchestration tooling and its tests removed (`00d2114`); current canonical authority coverage remains. |
| `test_bluestacks_integrated_routes` | a | Fake follows production reconciliation; exact reconciliation assertions retained (`d2d63d8`). |
| `test_campaign_claimed_startup` | a | Fixture includes proposal, source and reconciliation rows plus negative control (`c8d2693`). |
| `test_campaign_home_direct_entry_pan` | a | Inherited Home sidebar recognition (`3a79a38`) requires bounded pan, not UNKNOWN (`d2d63d8`). |
| `test_campaign_stage9_destination_replay` | c | Explicit private-capture opt-in; missing evidence after opt-in fails (`b616086`). |
| `test_campaign_victory_native` | b/c | Title alphabet handles punctuation; three stable boxes stay exact, retained-frame dispatch remains within the caption (`ae4d923`, review fixes). |
| `test_enhancement_home_ocr_duplicates` | c | Fixture models the nested badge without changing acceptance (`b766195`). |
| `test_native_frame_replay` | c | Unsupported Darwin OCR worker; only the same-capture OCR composition method is guarded (`adf5654`, `5d4ca3e`). |
| `test_nova_navigation_canary` | b | Renamed to `test_nova_navigation` (`d0c4ca0`); reject strong same-scale competitors (`9a4d8f2`, `e57423d`). |
| `test_nova_praise_centralized_boundary` | c | Two private cooldown replays require opt-in; portable journal/frame projection remains runnable. |
| `test_personal_might_praise` | a | Align ownership with the owner's REC-D09 decision (`391b48a`). |
| `test_pnsctl_canonical_serve` | a | Supply fixed adb configuration and test foreign-adb rejection (`13855ce`); no live command. |
| `test_semantic_ocr_crop` | c | Unsupported Darwin OCR worker; worker-dependent methods have explicit guards, pure/mock protocol cases remain (`adf5654`, `5d4ca3e`). |
| `test_service_supply` | c | Native surface recognition requires the OCR worker; method-scoped guards retain other route cases (`adf5654`, `5d4ca3e`). |
| `test_supply_claim_button` | c | Native binding methods require the supported worker and Tesseract; pure geometry cases remain (`adf5654`, `5d4ca3e`). |
| `test_supply_depot_vision` | c | Worker-dependent methods explicitly skip only on unsupported platforms; mock/pure recognition cases remain (`adf5654`, `5d4ca3e`). |

Other findings: the PowerShell-dependent token-context tooling was retired
(`00d2114`); dead scheduler/task-state code and tests were removed (`4a0453d`).
`test_personal_might_bluestacks` exposed a real clipped-rank bug: require full
highlight containment before numeric OCR so ranks 10/11 cannot become Rank 1.
Recovery modules now validate raw path components before comparing filesystem
identity. Missing Tesseract and unsupported OCR workers produce method-scoped
skips; pure/mock checks remain runnable. Runtime identity, troop training,
Ultimate Challenge and daily-row discovery-gap examples remain in full discovery.

## Owner decisions

1. Nova strong same-scale ambiguity rejection.
2. Protected Darwin system-alias admission and recovery filesystem-identity
   comparisons. Planted symbolic links are rejected; Windows junctions are not
   detected by the shared guard: [#46](https://github.com/mattebad/Puzzles_Survival_Automation/issues/46).
3. Campaign title normalization accepts `WINNER!`, `WINNER.` and `WIN.NER`;
   Loot and Tap-to-continue gates still apply. Personal Might uses numeric-field
   OCR only after full highlight containment and requires exact Rank 1.
4. Explicit opt-in for the two private Nova cooldown replays, not for committed
   portable `runtime_trace_projection` fixtures.
5. Enhancement's reversal from recovering the original reset to requiring the
   requested current-reset pending category (`46346f1`).

The owner separately authorized the review fix rejecting multiple pending
sources for the same requested category and current reset. Its regression first
failed with `OperatorError not raised`; an older-reset pending entry remains
non-ambiguous. Rejection creates no new state or reservation. No other production
behavior is changed in this review pass.

## Historical observations

[41791057290](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41791057290)
observed protected macOS alias admission but failed its full suite. Later
[41811529483](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41811529483)
also failed; neither is a green acceptance receipt.
[41840024620](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41840024620)
passed both full suites but failed committed-diff whitespace; `8062002` corrected
that gate. Git history preserves these observations without checked-in raw dumps.

The earlier [owner-authorized navigation observation](https://github.com/mattebad/Puzzles_Survival_Automation/issues/24#issuecomment-6635550421)
used the original shared runtime with candidate perception, not a whole-candidate
deployment or separate no-history radial-start round trip. Its private local
captures are not portable acceptance evidence. This review pass is entirely
offline. PR #45 remains draft/unmerged pending owner acceptance. The original
23-module inventory is now accounted for using its published source.
