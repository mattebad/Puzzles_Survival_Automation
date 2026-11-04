# Issue #24 historical module ledger

## Scope and counts

Keep the three snapshots separate. The original `f6b201f` audit was macOS arm64 / Python 3.11 / Tesseract 5.5.4: 246 modules, 3,319 cases, 48 failures and 39 errors across 23 failing modules. The published issue names 16 of those failing modules, not all 23. Seven names are therefore `evidence_required`; none are inferred here. The issue separately names `test_flow_delivery_token_context_hygiene` in its PowerShell portability findings, without establishing whether it was one of the 23.

The later baseline is `d4dd8db`, not `f6b201f`: 235 modules / 3,135 cases. Its Linux run had 12 failing modules; the macOS comparison had 11 of those (not `test_personal_might_bluestacks`) plus six macOS-only OCR-worker/Supply failures. Those are the handoff's counts, not the original audit's. The latest local actual-loader snapshot records 238 modules / 3,171 cases and three new test modules. Four old IDs have explicit rename mappings; there are no unmapped deletions. [`case-accounting.json`](case-accounting.json) retains the separately source-labelled identifier accounting. Test collection is not platform acceptance.

At the earlier `3dc3d8e` snapshot, the controller's Windows full CLI observation without Tesseract was 3,165 tests, 489 reasoned skips and zero failures/errors. That is local offline evidence, not installed-OCR/native or final-candidate acceptance. Final hosted CI outcomes belong in the controller's separate report.

`f6b201f` hand-entered CI/check lists covered 86 of 246 modules. The seven examples below that are not in the published failing-module list are discovery-gap examples, not newly identified failures. The historical 23-module name inventory is unavailable in the published issue; do not treat this ledger as a reconstructed complete list.

## Published failing-module names

| Historical module | Class | Cause, provenance/fix, and current evidence |
| --- | --- | --- |
| `test_flow_delivery_authority_consistency` | d — retire | The reported O7 mismatch was in the development agent-orchestration registry/queue. That tooling, including this check, was retired in `00d2114`. Current canonical service authority has coverage in `test_automation_service_canonical_authority.py` and `test_gameplay_flow_contracts.py`; this is not a claim that the retired queue-parity check still exists. |
| `test_navigation_runner` | d — retire | The old runner test expected the Bliss profile after the active profile had changed; `96aa8d5` unified the active runtime profile, and `4a0453d` removed the verified-dead navigation runner and its test. Current navigation boundaries are exercised by `test_navigation_session.py` and `test_safe_action_core.py`; the removed runner/API is not retained. |
| `test_pnsctl_nova_praise` | d — retire | The failing module exercised the supervised Nova development command/path. `d29972b` retired that path and its dependent tests/code. Current Nova service/pulse coverage is in `test_service_nova.py`, `test_nova_praise.py`, and `test_nova_praise_pulse.py`; none grants live authorization. |
| `test_flow_delivery_enhancement` | a — outdated deliberate contract | Fixtures predated the canonical current-reset, causal action-linkage and successor contracts introduced by `46346f1`. `d2d63d8` migrates the fixtures while retaining fail-closed unbound-exit/unknown-successor checks. Its commit records 48 installed-OCR passes; OCR-dependent methods are explicitly gated rather than blanket-skipped. |
| `test_flow_delivery_bioenhancer_bluestacks` | a — outdated fake | The fake `_PanNavigator` omitted `safe_region` and `calibration`, which `plan_research_lab_pan` reads. `12d3acd` gives the fake the real required fields; it does not change production route behavior. |
| `test_flow_delivery_evidence_integrity` | c — environment | The audit depended on a gitignored `.local-captures/` directory. Current `test_flow_delivery_evidence_integrity.py` uses temporary synthetic sessions to exercise missing/zero-byte evidence and wrapper behavior without inventing evidence. `b616086` introduced reusable fixtures and explicit local-capture opt-ins; its source/history context is the retired development evidence workflow, not private-image acceptance. |
| `test_bluestacks_integrated_routes` | a — outdated deliberate contract | Its fake rejected ordinary reconciliation without an in-flight marker and expected no reconciliations, unlike the current continuation contract. `d2d63d8` updates the fake and asserts exact action/post-frame reconciliation; the commit records 31 installed-OCR passes. Explicit tap/back continuation checks remain. |
| `test_campaign_claimed_startup` | a — outdated fixture | The journal lacked proposal, labelled source and reconcile rows required by `_normalization_ledger` and emitted by runtime. `c8d2693` adds those rows and a negative dismissal-without-retained-proposal case. |
| `test_campaign_home_direct_entry_pan` | a — outdated deliberate contract | `3a79a38` deliberately recognizes the second native Home sidebar layout; the historical `UNKNOWN` premise was stale. `d2d63d8` changes the expected result to bounded `PAN`, preserves zero-tap/unbound-building assertions, and records 19 installed-OCR passes. |
| `test_campaign_stage9_destination_replay` | c — environment | The retained destination/catalog replay reads gitignored native captures. `b616086` makes the module explicitly `@requires_local_captures`; without `PNS_LOCAL_CAPTURES=1` it reports the helper's opt-in reason, and after opt-in missing captures fail. This is replay coverage, not current live acceptance. Its historical source is `b35f9c9`. |
| `test_campaign_victory_native` | b + c — separate defects | Linux OCR read a glow particle as punctuation (`winner.`); `ae4d923` constrains the title field alphabet and retains literal-title/negative checks. Separately, OCR-engine tokenization moved an incidental caption rectangle; `ae4d923` replaces that metadata pin with the consumer contract (measured rectangle within the caption search region and actual integer dispatch center inside the caption). Only real-Tesseract tests are gated by `adf5654`. All six native Campaign tests pass on Windows and on Linux Tesseract 5.3.4/5.5.0; source-labelled receipts and the still-pending final sweep are distinguished in `native-ocr.md`. |
| `test_enhancement_home_ocr_duplicates` | c — environment | Tesseract 5.3.0 and 5.5.4 both read the wide badge as `47S`. `b766195` tests the nested-badge premise while retaining the recognition assertions; it does not relax the OCR acceptance. |
| `test_nova_navigation_canary` | b — real bug; renamed | `d0c4ca0` renames the module to `test_nova_navigation`. `_template_match_in_search_roi` ignored a second strong match at the same scale; `9a4d8f2` changes the matcher and `e57423d` hardens strong same-scale ambiguity rejection with its regression. This is not live acceptance: **NEEDS SUPERVISED LIVE RUN: Nova radial initial bind.** |
| `test_nova_praise_centralized_boundary` | c — environment | Two retained private cooldown-frame tests use `@requires_local_captures` as explicitly directed by the owner (`b616086` added the opt-in support). Pure/mock boundary cases remain available. The skip reason is `opt-in: set PNS_LOCAL_CAPTURES=1 to run tests that read gitignored .local-captures`; private capture availability is not acceptance evidence. See the `runtime_trace_projection` distinction below. |
| `test_personal_might_praise` | a — outdated deliberate contract | The owner deliberately assigned this objective to `REC-D09`, not Nova; current ownership is recorded in `docs/backlog/daily.md` (`REC-D09`). `391b48a` aligns the test owner ID. |
| `test_pnsctl_canonical_serve` | a — outdated invocation | The negative serve test omitted `--adb`, so the fixed-BlueStacks guard exited before the intended facade assertion. `13855ce` supplies the fixed adb and adds a foreign-adb rejection test. No live command was used. |

## Other named historical findings and discovery-gap examples

| Module(s) | Triage and current evidence |
| --- | --- |
| `test_flow_delivery_token_context_hygiene` | The reported macOS error was `FileNotFoundError: 'powershell'`. This test and its agent-orchestration tooling were deliberately retired in `00d2114`; PowerShell is not hidden behind a skip or compatibility shim. |
| `test_personal_might_bluestacks` | b — real bugs | Later Linux OCR read Rank 1 as `a`, not `1`; this was not one of the published original 16 names. Numeric alphabet restriction alone failed. `d4db4c8`'s inner crop passed the native Linux subset, but the expanded negative control exposed clipped ranks 10/11 accepted as 1. The current full-medal highlight-containment guard rejects those before OCR; all 36 local Windows native tests pass, with one symlink-privilege skip. Final cross-platform guard proof is pending; `native-ocr.md` preserves both failed and positive subset observations. |
| `test_scheduler`, `test_scheduler_sqlite`, `test_scheduler_retirement`, `test_task_state_store` | These are named in the #26 retirement follow-up, not in the published original 16. `4a0453d` removes the dead scheduler/task-state implementation and tests. Active canonical scheduler coverage remains in `test_automation_service_scheduler.py`, `test_automation_service_scheduler_canonical.py`, `test_scheduler_invocation_state.py`, and `test_pnsctl_scheduler_pulse.py`; this does not preserve the retired task-state API. |
| `test_runtime_identity` | Named as a discovery-gap example, not as a reported failure. The module remains and exercises current runtime identity; profile unification provenance is `96aa8d5`. |
| `test_troop_training` | Discovery-gap example, not a reported failure. It remains in the candidate; `adf5654` gives real-Tesseract cases precise dependency gates. |
| `test_bluestacks_ultimate_challenge` | Discovery-gap example, not a reported failure. It remains in the candidate; `adf5654` adds precise Tesseract gating for the OCR-dependent cases. |
| `test_daily_row_claim_bluestacks` | Discovery-gap example, not a reported failure. It remains current; later route/ID cleanup is recorded in `d0c4ca0`. |

## Environment-wide classification (module names not fully published)

- Missing Tesseract is class c, not an error or a blanket module skip. `adf5654` adds `requires_tesseract` only to real-engine cases. The exact helper reason is: `Tesseract executable {executable!r} is unavailable; install Tesseract or configure pytesseract.pytesseract.tesseract_cmd.` Mocked/geometry/protocol tests remain runnable.
- Unsupported OCR-worker platforms are class c. The exact reasons come from `requires_ocr_worker`: either `OCR worker requires Linux /proc/self/stat; {path!r} is unavailable.` or `OCR worker tests require Linux /proc/self/stat or Windows Job Objects; unsupported environment os.name={...!r}, sys.platform={...!r}.` Windows uses Job Objects; Linux requires `/proc/self/stat` (`adf5654`).
- macOS `/tmp` and `/var` system aliases were falsely rejected by ancestor symlink guards: class b, fixed initially across six consumers in `2467dbf`. The hosted sweep exposed three additional recovery consumers, now using the same raw-component validation before physical canonicalization. Planted/dangling links and untrusted aliases remain rejected; see `docs/runtime-input-safety-policy.md`. Offline path admission is not live acceptance.

## Failures exposed by the native hosted sweep

[Run 41791057290](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41791057290)
is a retained failed observation at `3dc3d8e`, not a final-candidate receipt.

| Affected module(s) | Class | Cause and candidate repair |
| --- | --- | --- |
| `test_bluestacks_ultimate_challenge`, `test_ultimate_challenge_recovery`, `test_enhancement_no_effect_recovery`, `test_enhancement_navigation_recovery`, `test_enhancement_positive_recovery_delivery`, `test_flow_delivery_enhancement`, `test_service_enhancement`, `test_personal_might_bluestacks` | b | Legacy recovery guards rejected the protected macOS alias or compared raw Windows/macOS session names to physical paths. Validate raw references, then compare filesystem identities and enforce containment. Hash/action/reset/input/effect/lease requirements remain. The parent caught and repaired an uninitialized no-effect session binding in the first integration attempt; the 101-case focused recovery run then passed. |
| `test_automation_service_boundaries`, `test_native_frame_replay`, `test_supply_depot_vision`, `test_service_supply` | c | Mocked OCR callbacks still pass through the actual monitored worker on these paths. Gate only those methods for unsupported worker platforms; split the OCR portion from the mixed callback test so pure checks remain runnable. |
| `test_path_safety` | c | Real planted links were rejected with a different human diagnostic under non-root hosted users. Retain all attacks and the typed `UnsafePathError` assertion; remove the incidental wording pin rather than repinning it. |
| `test_ruins_challenge_replay` | c | The fixture expected a raw temporary-directory alias while production deliberately returns physical paths. Canonicalize the fixture root; retain the replay assertions. |
| `test_flow_delivery_enhancement` — raw symlink fixture | a | The old fixture mocked `Path.is_symlink`, not filesystem link metadata. Model `lstat` and `readlink` consistently so resolve-first normalization would lose the forbidden link and fail the test; do not preserve a parallel compatibility guard. |


## `runtime_trace_projection` is portable

`test_runtime_trace_projection` was mentioned in the old Nova handoff only because its manifest also records private source paths. The committed `tests/fixtures/runtime_trace_projection/` journal/frame copies are the replay inputs: the manifest declares retained source metadata plus byte-equal portable copies, and the test reads `PORTABLE_REPLAY_FIXTURE`. The module remains runnable from committed fixtures; it is not evidence of access to, or coverage of, private captures. Do not add a local-capture gate to it.

## Owner gates and acceptance boundary

Production decisions remain owner-gated: Nova ambiguity rejection (`9a4d8f2`, hardened by `e57423d`), protected Darwin alias admission and recovery path identity checks, and native OCR field-alphabet/numeral-crop/highlight-containment changes. The second Home sidebar classification (`3a79a38`) is inherited; this work changes its stale test premise, not production recognition. Offline proof does not sign off the new production decisions. No BlueStacks/device input or live acceptance is claimed. In particular, the Nova initial radial bind still requires the supervised run stated above.

## Runtime change inventory

Compared with `d4dd8db448096ce2268b67bc0a301ce7c540594a`, code candidate
`5d4ca3e6a6c0bf42827fc01a08b2cea9299f1ee6` changes these thirteen runtime files.
They require owner review; passing offline tests do not approve production behavior.

| File | Decision |
| --- | --- |
| `safe_action_core/path_safety.py` | Shared raw-component inspection and narrowly protected Darwin OS-alias admission. |
| `scripts/navigation_development_boundary.py` | Reuse the shared guard for fixed orchestrator paths without hiding links during normalization. |
| `scripts/startup_recovery.py` | Validate contextual recovery references before resolving them. |
| `tasks/campaign_victory_recovery.py` | Reuse raw-path validation while preserving the existing junction-rejection policy. |
| `tasks/ruins_challenge_continuation.py` | Apply the shared guard to continuation source references. |
| `scripts/flow_delivery_ruins_challenge_bluestacks.py` | Apply the shared guard to retained Ruins evidence. |
| `scripts/flow_delivery_bioenhancer_bluestacks.py` | Apply the shared guard to retained Bioenhancer evidence. |
| `scripts/flow_delivery_enhancement_bluestacks.py` | Validate raw recovery/session references, then compare filesystem identities and retain receipt containment. |
| `scripts/flow_delivery_ultimate_challenge_bluestacks.py` | Validate session/frame/event references and use one physical root for Home evidence and relative references. |
| `scripts/flow_delivery_personal_might_bluestacks.py` | Validate raw recovery/verification references and compare the zero-cost request's filesystem session identity physically. |
| `tasks/nova_praise_vision.py` | Reject a second strong same-scale match; retain the separate supervised initial-bind gate. |
| `tasks/campaign_auto_battle_vision.py` | Declare the native title field alphabetic; see the native controls and retained failure history in `native-ocr.md`. |
| `tasks/personal_might_vision.py` | Declare the numeral field numeric and reject clipped numeral highlights before OCR; see `native-ocr.md`. |

`scripts/check_test_discovery.py` is additional test infrastructure, not a runtime
executor. `automation_service/` and `scripts/check.py` are unchanged. No new
execution authority, scheduling/registration enablement, resource-effect bypass,
device input, or live acceptance is part of this inventory.

## Hosted failed candidate: `5d4ca3e`

The retained hosted matrix is [run 41811529483](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41811529483), source `5d4ca3e6a6c0bf42827fc01a08b2cea9299f1ee6`. Its machine-readable summary, raw receipt SHA-256 values, exact failure IDs and tracebacks are in [`hosted-proof-5d4ca3e.json`](../../../evidence/offline-validation/ticket-24/hosted-proof-5d4ca3e.json); original artifacts remain under `../ticket30-proof/t24-hosted-5d4ca3e/`. The immutable hosted snapshot belongs under `evidence/`, not mutable instructions with machine-specific diagnostic paths. The isolated per-module collector ran 238 modules / 3,171 tests with **4 workers**. Each complete discovery run was separate and sequential; the worker count does not describe full-suite concurrency.

| Hosted OS | Isolated collector (wall; summed module time) | Isolated result | Sequential full run (time; result; skips) | Full run without Tesseract (time; result; skips) |
| --- | --- | --- | --- | --- |
| Ubuntu | 676.505 s; 2,644.184 s | 3,171 tests; 1 failure, 0 errors, 41 skips | 1,477.837 s; 3,171 tests, 0 failures/errors, 41 skips; process exit 0 | 496.807 s; 3,171 tests, 0 failures/errors, 490 skips |
| Windows | 663.750 s; 2,587.218 s | 3,171 tests; 0 failures, 1 error, 36 skips | 1,357.688 s; 3,171 tests, 0 failures, 1 error, 36 skips; process exit 1 | 589.750 s; 3,171 tests, 0 failures/errors, 486 skips |
| macOS | 618.511 s; 2,425.913 s | 3,171 tests; 0 failures, 1 error, 68 skips | 1,204.233 s; 3,171 tests, 0 failures, 1 error, 68 skips; process exit 1 | 488.107 s; 3,171 tests, 0 failures/errors, 506 skips |

Linux's complete sequential run passed, but the isolated `tests.test_supply_claim_button.SupplyClaimButtonNativeBindingTests.test_actual_before_binds_button_but_label_dismissal_and_changed_png_do_not` failed at `assertIsNotNone(binding)` (`binding` was `None`). The one failing assertion is retained in its module log and JSON. It is an unresolved collector failure; its cause is not established. In particular, four-worker contention is a possible investigation, not a demonstrated cause.

Windows and macOS share the same error: `tests.test_enhancement_no_effect_recovery.EnhancementNoEffectRecoveryTests.test_actual_native_recovery_reaches_independent_wrapper_transition` raised `OperatorError: Enhancement no-effect receipt identity or accounting is invalid` at `_validate_zero_selected_no_effect_receipt`. The retained error does not report individual predicate values.

A portable local regression uses an ordinary existing `alias-anchor/..` path and independently reproduces that validation error at the raw-string `original_runtime_session` comparison. `t24-no-effect-identity-before.json` retains the one-case error. Commit `3b625c2857b974e78e18361967d9e1bc6cee5314` reuses `_same_validated_path_identity` for that filesystem reference; action key, hash, reset and zero-accounting checks remain strict. The existing native integration method keeps all original assertions and now exercises this alias on every platform.

The actual native transition, all no-effect safety cases and unchanged Supply geometry/native-binding cases then pass locally: 24 cases, no failures/errors/skips or forbidden device-executable attempts, 25.593 seconds including driver overhead (`t24-no-effect-identity-after-and-supply-windows.json`). This repair has not received final hosted proof; the `5d4ca3e` hosted failures remain a historical failed candidate, not an overall pass.

All three missing-Tesseract full runs have zero failures and errors. Their skip totals are reasoned: 450 Tesseract-dependent cases per OS, plus 36 local-capture opt-ins on each; Linux additionally has 4 Windows-alias skips (490 total), and macOS has 4 Windows-alias and 16 unsupported OCR-worker skips (506 total). In the Tesseract-present complete runs, the 41 Linux skips are 36 local-capture and 5 Windows-alias; Windows has 36 local-capture skips; macOS has 36 local-capture, 5 Windows-alias, and 27 unsupported OCR-worker skips. Native macOS execution observes these selective worker-platform skips; it does not establish a supported Darwin OCR-worker backend. All hosted full/per-module receipts record zero forbidden process attempts.

The settled `Record OCR build` job logs report Ubuntu Tesseract **5.5.0** (Leptonica 1.86.0), Windows **5.5.3.20260724** (Leptonica 1.87.0), and macOS **5.5.3** (Leptonica 1.87.0). The retained raw job logs and byte hashes are listed in the JSON aggregate. No assertions or thresholds were softened to produce these observations. The separate one-worker collector change is not represented by this four-worker run and is not a verified Supply fix. This failed candidate is not an overall-green or live-acceptance claim; **NEEDS SUPERVISED LIVE RUN: Nova radial initial bind** remains.

## Corrected-source Windows full discovery: `0986aa8`

The runtime/test tree at `0986aa8a5333848e649472d8caa9faad8b065818` passes the
actual `python -B -m unittest discover -v -s tests -t .` command locally:
3,171 tests, no failures/errors, 43 skips, 1,515.672 seconds including driver
overhead. The skips are 36 explicit local-capture opt-ins and 7 unavailable
Windows symlink-creation privileges. The installed engine is Tesseract
5.5.0.20241111 on Python 3.12.10. The device-executable guard records no forbidden
process attempt. This is local Windows proof, not hosted Python 3.11 acceptance.

[`local-proof-index.json`](local-proof-index.json) records the exact receipt-byte
digest and distinguishes this complete run from the static 397-case
`scripts/check.py` run. Pending untracked proof documents were not part of its
tracked-file hygiene scan. Six earlier receipt annotations hashed LF-normalized
text rather than retained Windows file bytes; the index now supplies exact-byte
digests and preserves those earlier values as `legacy_normalized_lf_sha256`.
All original receipt files remain unchanged.