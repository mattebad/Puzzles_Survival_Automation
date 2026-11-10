# Issue 114 review source checkpoint

This is an **implemented-source snapshot for offline plan review**, not a Training implementation, live acceptance receipt, runtime enablement or gameplay authorization. Begin with [issue 114](https://github.com/mattebad/Puzzles_Survival_Automation/issues/114) and its [code-only review assignment](https://github.com/mattebad/Puzzles_Survival_Automation/issues/114#issuecomment-6755269645).

## Exact source and purpose

- Review branch: `fix/live-first-recovery-114`.
- Local linked worktree: `C:\Users\burni\Documents\Coding_Projects\Puzzle_Survival_live_first_recovery_114`.
- Committed parent: `7994eedc7fbc15d0211906c2b3863333203a484c`.
- Reviewed incoming source: `C:/Users/burni/Documents/Coding_Projects/Puzzle_Survival_walkthrough_corrections_20261109`, branch `fix/manual-walkthrough-corrections-20261109`, at that parent plus the explicit 32-path carryover below.
- Incoming manifest digest: `61fcde1a781b42c0cc3ecd836d4bde147588931b287cc27cb5bf8bb729685963` (SHA-256 of the path/hash dictionary serialized with Python `json.dumps(..., sort_keys=True)`).
- The exact published checkpoint SHA is supplied in issue 114 and is this branch's source-packaging commit. The report author must record the inspected source SHA separately from their later report commit.

The original two dirty worktrees are preserved. All 24 modified tracked files and eight untracked files from the audited correction source were explicitly scoped as existing inspection/rearm, interruption recovery, Research continuity, fixtures and associated documentation/coverage. Nothing was copied from differing Original source. The capture fixtures retain their original bytes and provenance. No database, authorization record, raw capture directory or rolled-back consolidation was transferred as carryover.

All 32 incoming files were verified byte-identical immediately after carryover. The only subsequent differences are explicit historical/current-entry labels in three documents: `docs/agent/CURRENT_HANDOFF.md`, `docs/agent/CONTINUATION_HANDOFF_20261109.md` and `docs/agent/prompts/CONTINUE_20261109.md`. The other 29 incoming paths, including every Python and fixture file, remain byte-identical. This brief is the only additional file. No application, test, policy, configuration or dependency behavior was changed during packaging.

## What to review next

Produce only `docs/research/issue-114-training-development-plan-review.md` under the issue's assignment. Review the accounting correction and a minimal fixed Fighter/Shooter T8x2, Rider/Vehicle T1x10 repeatable Training configuration. Those changes are **not implemented by this checkpoint**; production defaults and the documented conflicting validators remain present for the reviewer to inspect. Do not run routes, create tests merely for green results, prepare another baseline or implement the plan.

The old continuation documents are historical snapshots, not live instructions. In particular, their update-integration/canary statements are stale. Current source includes update recovery integration; later retained evidence records the failed Cash Mall terminal context and separately observed Back. Do not repeat Original worker integration or call the original canary PASS. Do not treat the discarded Codex consolidation as installed.

## Runtime and evidence boundaries

For live implementation only, this worktree is linked to Original. A filesystem-only call to existing `canonical_state_root` resolved it to `C:/Users/burni/Documents/Coding_Projects/Puzzle_Survival_Runtime_POC` and confirmed the three existing `.local-orchestrator` files (`bot-state.sqlite3`, `bluestacks-actions.sqlite3`, `bluestacks-runtime-input-lock.sqlite3`). This verification opened no SQLite connection and sent no device input. Packaging did not enable controls, migrate state, clear UNKNOWN/history or claim a live operator.

A remote code-only reviewer may clone/fetch this published branch. That clone does not need Windows/BlueStacks access and must not initialize runtime state. `--state-path` alone does not relocate all runtime authorities. Any future live work needs its own current authorization, verified canonical bindings and exclusive ownership.

Gitignored `.local-captures` histories were not published. Training's full final receipt/frames and rollback archive remain local to correction at the paths recorded in issue 114. Remote reviewers must label those observations as reported historical evidence unless separately supplied; their absence does not block source-only analysis. The committed recognition fixtures are not current gameplay evidence or authority to repeat effects.

## Preparation verification

- Existing focused inspection/CLI checks: `python -B -m unittest tests.test_inspected_retry_admission tests.test_pnsctl_canonical_serve` — **35 passed** in this new worktree. They use isolated test state, not live runtime state.
- Ruff on all 22 carried Python files: **18 inherited findings** (E402, F401, F601, E702). No suppressions, budget changes or opportunistic fixes were made.
- File-scoped LSP diagnostics for `scripts/pnsctl.py`: **13 errors, 2 warnings, 6 hints**, including existing optional-value/protocol typing issues and Ruff diagnostics. This is not a clean static baseline. The file is byte-identical to incoming correction source.

- Required static ratchet: `python -B scripts/check_static.py --base-ref c6f0e2fba509dacde136226a7519568550f6b066` — **failed**, exit 1; 506 active Python files, Ruff294 findings/97files, Vulture471/143files, Mypy640/40files. Existing budget violations remain. No baseline refresh, budget increase, suppression or unrelated source fix was made.

These checks establish only the stated offline scope. The source is available for review despite inherited static debt; it is not statically clean, feature-complete or live-accepted. No full test discovery or native route was run during preparation. Fresh-worktree creation and path verification do not establish computer-use availability or Training durability.

## Incoming carryover manifest

SHA-256 values below describe incoming correction working-file bytes, before the three explicit documentation labels. The raw file digest is not a claim about a checkout using different Git line-ending conversion. The pushed Git commit is the authoritative review source. All other tracked files are inherited from the named parent; no unrelated Original source is included.

| Path | Incoming SHA-256 |
| --- | --- |
| `automation_service/cli.py` | `\4c821c96eae2ee8ba54a7c09d98e30856724c36f0207b51a45804a36c8be8c6f` |
| `automation_service/recommended_research.py` | `\003a757657daf911bcb3eea9e7a6d6a9bd889f3f34b0a346e65be6f2e7fbfd83` |
| `automation_service/service.py` | `\bc007bee0448d70f81679e133ca4bbf97b711293c9f167e12242424f7ce61518` |
| `automation_service/state.py` | `\5a632e4a5fd7e2e92a51a088f1fc39678ebd871ebceaa9a7ca1b923b7d01f808` |
| `docs/agent/CONTINUATION_HANDOFF_20261109.md` | `\121314a9c4e6c5666ff3cb7961ea0b4a3748d42ff3651741111097fc60db7675` |
| `docs/agent/CURRENT_HANDOFF.md` | `\d9d254ccc98ccf4f33eae33c35aa5e9adc2b8445c2e2cdce2ad73824fd55b815` |
| `docs/agent/prompts/CONTINUE_20261109.md` | `\72a7d6ec49bfa7a06f774c2fce4b460604ffd2f959f6e5aa7b80f72a49e0123e` |
| `docs/pns-operations-runbook.md` | `\e0abd0276fa0635499b0acd2fcac0f9161c31b64b04fe0d8f559a5e1766f1ec7` |
| `scripts/bluestacks_native_runtime.py` | `\12fe97046e321533fab6a0c212075222023c38f7d8ec736ada945bceb57e1e87` |
| `scripts/bluestacks_popup_recognition.py` | `\3bc8bf562f67e1ca3d128dd940288b71e6ca6464e8b82cf53395427c51f8f808` |
| `scripts/pnsctl.py` | `\fc09594c73bd2009362975987997a0205837bf914771106a463ad22115b9dbea` |
| `scripts/recommended_research_bluestacks.py` | `\05984629853511595347fe77677ada2c8c8b97564496f0b0e0ee4e13af265ba5` |
| `scripts/startup_normalization.py` | `\f4c8bcfc00e3f1374ac74aaa97016d68c32e18e4b8e4233097a4e8826a7e05e9` |
| `scripts/startup_recovery.py` | `\448521b7359f77ccf672f74ecbae14b57ca39e93132b4a3e31c0f38175f86925` |
| `scripts/startup_surface_recognition.py` | `\e4f044e15c6ff6506aa92def26a8ff56aa63b6df52d75db4ab954c4fe54aa087` |
| `tests/fixtures/runtime-update-restart/provenance.json` | `\58cedc35ba3a2e647ebadc26cf8b5b0c068c74c4295a88b7ae4e8d92181e757c` |
| `tests/fixtures/runtime-update-restart/update-required.png` | `\41ccef4bf09e3a994e92d3360e7503ac2adc46189e3ecd76ffe0faed00f322a5` |
| `tests/fixtures/startup/cash-mall-current-20261109.png` | `\fe234edc398814c983ff6c452c88b651847e05828acf0dc447e8ede2981a5080` |
| `tests/fixtures/startup/cash-mall-current-20261109.provenance.json` | `\e2425d0f4ccbd9599947d890cf6952ff1326dcfe5a4b9c69d912153f2c0641b4` |
| `tests/fixtures/startup/restart-home-current-20261109.png` | `\4caf05640b4ad8bb6e546c392a239133e08e9b753b4454f73af8feff851c2878` |
| `tests/fixtures/startup/restart-home-current-20261109.provenance.json` | `\17c84d0ab5e1b1bc812e83b3cf2cd65a88ff3ce8ebc08203d979dcdedc59b689` |
| `tests/test_inspected_retry_admission.py` | `\ae57c90bc50e01be216bb9d80cb59954ba11060ee8072ccbb0c2d2e6d6949ce7` |
| `tests/test_network_disconnect_boundaries.py` | `\7544d91e546f5535dd055ed2b47734139239689c7aa7cd9a73b617af984362a2` |
| `tests/test_network_disconnect_occurrence.py` | `\2f081c368219f64ecc492b2b6d4ef00c8cd2f1f16d5a223fecaa3cb9687b9af5` |
| `tests/test_network_disconnect_recognition.py` | `\88534340424eab9f16db20e0ba0732e608c6b21539813dcd9da38e70b50283b6` |
| `tests/test_network_disconnect_recovery.py` | `\0a8f6cf4ff6253cab735dc497b803a2f7d6442ae56b6bfab8ab5551af28c9667` |
| `tests/test_network_recovery_state.py` | `\3a36e4e058cbc3170183e0fc745f1feacd16ff62f52e3118abbfec2c1b760d4a` |
| `tests/test_pnsctl_canonical_serve.py` | `\908688420474b70702383f2a1463d08640f946b2fbe5b4d342a4892b0a7f46d0` |
| `tests/test_scarlett_current_context.py` | `\fbd1b03455db1b932b2c1e847120c360fc7b9161ac5c7360311b218c91f551b0` |
| `tests/test_service_recommended_research.py` | `\724dc0cfaf2a5b8df23f6736240832bb7ec9bda75405112b639b00acfa5d463e` |
| `tests/test_service_route_contract.py` | `\787f324a6c3434f73a72476190a1ac9f48fc9fd3c920ee826b347555734aa14c` |
| `tests/test_startup_recovery.py` | `\71daad2abd5a7db600e3ad0b1cb2a7f723b6dc0e7b0ed7d776dcdbff08b57a30` |
