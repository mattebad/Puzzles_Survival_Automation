> Historical 2026-11-09 snapshot, retained for provenance. Do not execute its
> continuation instructions or treat its integration/canary status as current.
> Start with [the issue 114 source checkpoint](../research/issue-114-source-checkpoint.md)
> and current issue 114 instead. This document grants no live authority.

# Fresh-session continuation handoff — 2026-11-09

This is a volatile session bridge, not a parallel backlog, runtime authorization, or acceptance receipt. GitHub tracker [#53](https://github.com/mattebad/Puzzles_Survival_Automation/issues/53) and current owner direction remain the planning source. Historical receipts remain historical. Read this file before the older sections of CURRENT_HANDOFF.md.

## 1. Immediate truth / stop point

- The owner explicitly paused execution to reload the chat, then requested this handoff. **No resume instruction has been executed.** The paste-ready prompt beside this document is for the owner to send in the new chat.
- **The new update-popup live canary HAS NOT RUN. No game stop/start or update Confirm was issued in this final pass.** The last real operation was a zero-input native capture at 18:15 UTC.
- That capture showed `New version detected. Tap Confirm to update.` over Home. The owner explicitly directed that this exact interruption be detected by the shared guard and recovered with a game restart. Do not revive the superseded requirement that a human must always clear this particular recognized popup.
- Recognition, durable restart state, and standalone lifecycle changes were written. **A handoff inspection found that nested workers wrote the service integration and several tests in the WRONG checkout.** These changes are not lost, but the correction worktree is not yet a coherent complete integration. Consolidate the specific worker changes before live recovery. See section 4.
- Eight focused modules passed **188 tests** on the correction worktree, but **that result does not cover the misplaced new service/recovery tests**. Do not call the complete new update feature offline-proven or live-accepted yet.
- Three changed-line Pyright errors remain; none were fixed before the pause. See section 7.
- Latest supported read-only canonical status, checked at approximately **2026-11-09 18:32 UTC**: service disabled, scheduler ineligible, **all 24 flow controls disabled**. This status output does not expose service-owner/Core-UNKNOWN counts; do not invent fresh values for them.
- All this assistant's workers are complete/parked. No native job from this assistant remains running. The LSP mux is an idle tooling service, not a live game operator.
- GitHub has NOT been updated for the later known-progress correction, its successful inspections, the 18:00 Research attempt, or the new update implementation. The latest tracker comment is still the obsolete 14:45 accounting-blocker account. Publication remains work to do, not completed delivery.

## 2. Workspaces, Git, interpreter, and state

### Active correction checkout — continue here

`C:/Users/burni/Documents/Coding_Projects/Puzzle_Survival_walkthrough_corrections_20261109`

Branch: `fix/manual-walkthrough-corrections-20261109`
HEAD: **`7994eed`** (`docs: distinguish observed replay effects from native acceptance`).
At 18:32 UTC it was **11 commits ahead** of its origin tracking branch. Later fixes remain local/uncommitted; do not assume the remote branch or old draft PRs contain them.

### Original checkout — preserve, do not switch/reset/clean

`C:/Users/burni/Documents/Coding_Projects/Puzzle_Survival_Runtime_POC`

Fresh verification found branch **`canary/owner-route-reacceptance-20261109`**, HEAD **`412c4b7`**, NOT main. This supersedes old statements that Original is currently restored to main. `412c4b7` is **not an ancestor** of correction HEAD `7994eed`; these are not interchangeable source trees. Do not copy whole differing files or merge the Original branch blindly to obtain the worker changes.

Original had these dirty/untracked paths at the handoff check:

```text
 M AGENTS.md
 M README.md
 M Stop-PnS-OMP.ps1
 M automation_service/cli.py
 M automation_service/service.py
 M docs/agent/CURRENT_HANDOFF.md
 M evidence/current-evidence-manifest.json
 D tests/test_daily_nanoweapon.py
 M tests/test_network_disconnect_boundaries.py
 M tests/test_network_disconnect_occurrence.py
 M tests/test_network_disconnect_recovery.py
 M tests/test_pnsctl_canonical_serve.py
?? Puzzle_Survival_Flow_Completion_Plan
?? governance-simplification-plan.pre-merge.md
?? issue-51-test-value-audit.md
```

Preserve all pre-existing/unrelated changes. Some of the service/test hunks above came from the latest misplaced workers; attribution is described below. Original's dirty CURRENT_HANDOFF.md was NOT overwritten by this handoff.

Remote origin: `https://github.com/mattebad/Puzzles_Survival_Automation.git`.
A fresh `git ls-remote origin refs/heads/main` during handoff still returned:
`c6f0e2fba509dacde136226a7519568550f6b066`.
This is a dated verification, not permission to assume main never changes. No merge, deployment, force-push, or permanent execution enablement was performed.

Use **Python 3.12**, not the Eval host's unrelated virtualenv:
`C:/Users/burni/AppData/Local/Programs/Python/Python312/python.exe`.
Supported startup checks use repository `PYTHONPATH` unset, e.g. Git Bash `env -u PYTHONPATH '<python>' -B ...`.

### Canonical data stays in Original

```text
Original/.local-orchestrator/bot-state.sqlite3
Original/.local-orchestrator/bluestacks-actions.sqlite3
Original/.local-orchestrator/bluestacks-runtime-input-lock.sqlite3
```

`BotStateManager.DEFAULT_DB_PATH.resolve()` was freshly checked from corrected source and equals the Original bot-state path. Keep that linked-worktree canonical binding; never create a substitute empty state DB to escape existing history. Inspect current owners, reservations, unresolved effects, reset and generations through supported boundaries before live use.

The latest observed reset was `game-day-2026-11-09`, ending November 10 at 00:00 UTC. **Verify the actual reset in the new session** before treating any action as newly due.

Actual fixed labels, not placeholders:

```text
account: fixed-login-slot:v1:e2b17f4a5d8f53bc156bc29ab4efb6b44534f6e3d15c2847748a59a5f2ade2a5
server:  fixed-server-slot:v1:e2b17f4a5d8f53bc156bc29ab4efb6b44534f6e3d15c2847748a59a5f2ade2a5
```

Obtain them from the existing `resource_fixed_runtime_binding()`/runtime identity API rather than maintaining a second authority. The earlier Help placeholder labels were rejected before input; that failure remains in history.

## 3. Owner intent — do not repeat the workflow failure

The owner repeatedly authorized live input and computer-use walkthroughs and explicitly complained about hours spent adding mocks, inspecting governance and repeatedly running broad checks instead of completing real routes. The latest process direction is:

1. Use real current BlueStacks observation and bounded authorized canonical execution when available. Fix the concrete observed blocker, then verify that path live.
2. Tests are not banned. Use focused safety checks for consequential changes and regression tests for observed bugs or consequential quota/UNKNOWN/restart invariants. **Do not build another mock portfolio, accounting scaffold or global orchestrator before the next safe live attempt.**
3. Ordinary action readiness is established by that route's verified gameplay, not per-route Daily Quest/D02/points attribution.
4. Known no-op/navigation failure and known confirmed partial effects are not automatically financial uncertainty. Do not require a new generic whole-visit accounting journal/receipt as a universal prerequisite. Preserve real input-budget integrity and actual uncertain consequences.
5. Keep honest distinctions: implementation, offline proof, manual gameplay, confirmed individual native effect, and fully native end-to-end acceptance are different claims. A failed original visit remains failed even after positive reconciliation or a later resumed pass.
6. Continue independent eligible routes if one is unavailable. An exhausted technical window, missing current UI state or conditional Wali/Pit gap is not a reason to abandon the rest.
7. The recurring `max_attempts=3` is a persisted **technical failure-window cap**, not a three-gameplay-actions limit supplied by the owner. Do not increase it, erase history, or invent a game rule from it. Use the supported inspection correction described below where genuinely eligible.
8. Explicit per-ticket todos; never hide all outstanding work in 'remaining next steps' or mark the entire queue complete when only an investigation phase ended.

Read current applicable AGENTS guidance and `docs/adding-a-route.md` before code changes. Public docs must distinguish implementation/offline/live facts. No global #22/#65 dependency, extra account polling, unrelated static cleanup, World/gathering/building upgrades/speedups/NAS work.

## 4. CRITICAL: exact uncommitted changes and misplaced worker integration

### Changes in the correction worktree before this handoff's Markdown files

```text
automation_service/cli.py
automation_service/recommended_research.py
automation_service/service.py
automation_service/state.py
scripts/bluestacks_native_runtime.py
scripts/bluestacks_popup_recognition.py
scripts/pnsctl.py
scripts/recommended_research_bluestacks.py
scripts/startup_normalization.py
scripts/startup_recovery.py
tests/test_inspected_retry_admission.py
tests/test_network_disconnect_recognition.py
tests/test_network_recovery_state.py
tests/test_pnsctl_canonical_serve.py
tests/test_service_recommended_research.py
tests/test_service_route_contract.py
tests/fixtures/runtime-update-restart/   # untracked real PNG/provenance
```

They include two cohesive fixes: (a) already exercised known-progress inspection/terminal-marker correction; (b) shared exact update recognition/restart, whose full integration remains incomplete. Preserve the prior hunks when finishing the latter.

### Why source is split

Parent assigned `UpdateRestartHigh` the correction workspace. It delegated children using **relative writable paths without carrying the workspace in their actual task message**. Those children used the Original process cwd. Their histories show relative `read`/`edit` paths, and fresh file/diff inspection confirms the new update hunks in Original, absent from the correction tree. Worker completion claims were therefore too broad.

Known misplaced child work:

| Original path | Actual new worker work |
| --- | --- |
| `automation_service/service.py` | Update interruption identity, stop/launch accounting and actual recovered-episode validation, recovery-only deferral, stop count propagation. |
| `automation_service/cli.py` | Existing `--recover-network-disconnect` help expanded to shared exact10054/update recovery. |
| `tests/test_network_disconnect_occurrence.py` | New update recovery/zero-input resumed occurrence/accounting/UNKNOWN cases. |
| `tests/test_network_disconnect_boundaries.py` | Fake device game-stop/process observation and update opt-in/no-input case. |
| `tests/test_network_disconnect_recovery.py` | Four update restart regressions: fresh success, uncertain restart across reopen, persistent update after one restart, unresolved Core blocks. |
| `tests/test_pnsctl_canonical_serve.py` | Worker-local help/CLI expectation changes; merge carefully with correction tree's prior known-progress tests. |

Approximate Original diffs against its own HEAD were service +33/-7, cli +1/-1, recovery tests +174/-1, occurrence +108, boundaries +31/-6, pnsctl tests +4. These are discovery aids, **not permission to replace whole files or discard other differences**.

First continuation step: inspect/port the attributable hunks into the correction worktree, retaining its prior known-progress fix and its own source baseline. Leave Original and unrelated changes intact. Run the affected checks once after that coherent integration. Do not represent the currently split work as completed canonical integration.

Give all future workers **absolute writable paths and explicit workspace context**, including nested tasks. Verify their actual cwd/paths before edits. Serialize shared service/state/policy integration. Parent remains sole live operator. Worker source/test investigation is not permission for device use.

Relevant current-worker histories, if needed for attribution (not an invitation to reread the entire old chat):
`history://UpdateRestartHigh.UpdateServiceHigh` and
`history://UpdateRestartHigh.UpdateRecoveryTestsHigh`.
Persisted session directory:
`C:/Users/burni/.omp/profiles/codex/agent/sessions/-Documents-Coding_Projects-Puzzle_Survival_Runtime_POC/2026-11-07T01-11-15-350Z_01a1b38f-4c96-7107-b858-cd68fdabb7aa/`.
Read its specific worker records only if tool registration does not survive; do not start an archive-wide investigation.

## 5. Shared update guard: implemented pieces, missing proof, exact scenario

### Exact current interruption

`New version detected. Tap Confirm to update.`
Native 800x1280, foreground `com.global.ztmslg`, Home visible behind the modal. This is **#92 update handling**, not **#104 disconnect10054**. Do not tap its update Confirm/download button.

Retained latest zero-input source:

```text
Correction/.local-captures/development-sessions/observe-20261109T181552560981Z/
  observe.png
  result.json
  summary.json
```

Frame SHA-256:
`41ccef4bf09e3a994e92d3360e7503ac2adc46189e3ecd76ffe0faed00f322a5`.
The supported `development-session observe --max-inputs 0` returned input_count0, dispatch=false, lifecycle_state_created=false, ownership_released=true. The image was actually viewed.

Real retained fixture in correction:
`tests/fixtures/runtime-update-restart/update-required.png` plus `provenance.json`.
Raw captures are immutable. Screenshot coordinates are investigative geometry, not reusable click instructions.

### Implemented API/behavior

- `scripts/bluestacks_popup_recognition.py:recognize_shared_interruption(frame)` retains strict existing10054 recognition and adds exact `UPDATE_RESTART_REQUIRED` detection. Recognized update is blocking and exposes **no click target** (`target`, target identity and center are None). Unknown same-shape dialogs remain blocking.
- `scripts/bluestacks_native_runtime.py`, `startup_normalization.py` and `startup_recovery.py` use the composite guard rather than falsely recognizing Home behind the update as ready.
- `NetworkRecoveryEpisode` in canonical state appends `interruption_identity`, `restart_attempts` and `restart_transport_status`; `NetworkRecoveryStep.RESTART` shares the existing episode, original deadline and durable CAS budget. No parallel recovery journal/controller.
- `recover_network_disconnect(...)` gains an optional keyword-only `restart` callback. Existing10054 behavior is preserved; update performs no Confirm.
- `pnsctl` factors the existing sanctioned game stop transport into `_stop_game_process`, verifies the process stopped and the known BlueStacks launcher, then reuses `owner_bound_application_startup`. No ad-hoc caller device shell and no emulator/VM/router/host restart.
- Persist intent **before** transport; at most one game stop/start, original <=90-second deadline, zero game input/spend. UNKNOWN never renews the restart budget. Persistent update/manual/login state stops rather than loops.
- Core lease/input ownership and outstanding action fences remain. Refresh frames/context and invalidate pre-restart bindings. Recovery creates no gameplay credit and preserves occurrence identity for a fresh invocation.
- The service-side verification/occurrence tests for this behavior are the misplaced hunks above; integrate them before claiming the feature complete.

### Supported command after integration/checks

From the CORRECTION worktree, Python3.12 with repository PYTHONPATH unset:

```text
python -B scripts/pnsctl.py development-session recover-network --live --yes
```

The existing command is intentionally extended; no duplicate launcher is needed. Record the owner's exact update-restart authorization through the existing operator/controller, with one stop, one launch, zero update/game clicks, zero spend, finite deadline. Check present ownership and unresolved consequences first. Do not call `_cold_restart_game` directly: its original clean-idle-Home test precondition is different.

The command's `--help` starts correctly offline. **It has not yet been executed against this update.** If fresh observation is already connected Home, do not force an update or unnecessary restart just to get a receipt. If update persists after its one permitted restart, report that actual missing prerequisite; do not issue another restart/Confirm.

### #104 is separate and still not live-accepted

The historical real10054 canary sent one Confirm, zero launches, then stopped on Daily Quest/loading. Later capture-only Home inspection reconciled that zero-cost navigation but explicitly did not accept the original canary. Source/loading/Home settling was repaired offline. Next proof requires a **naturally occurring exact10054**; do not force an outage or make it a global route prerequisite. Logged-in-elsewhere/account takeover/login/CAPTCHA/tutorial remain manual-only.

## 6. Completed known-progress/marker correction — DO NOT rebuild it

This directly addresses the owner's objection to generic 'durable final-accounting proof' blocking routes with known/no accounting effects. It is uncommitted but already exercised through supported real state inspections.

- `automation_service/service.py`: a normally returned, fully input-accounted known BLOCKED/MANUAL stop clears only its own interrupted/crash marker after fenced terminal projection. Run identity, actual uncertain effects, committed counts, projection failure and existing technical failure history remain guarded.
- `identical_retry_denied=True` alone does not mean the whole visit is uncertain; a confirmed action must remain protected from duplication while a known navigation failure can end normally.
- Research native/adapter now distinguish pre-start no-effect blockage, confirmed start plus failed return navigation, and genuinely uncertain start/accounting. A confirmed partial effect is not relabelled a whole-route PASS.
- Existing supported `inspect-rearm` adds opt-in `--review-known-progress`; default zero-effect-only inspection remains unchanged. RuntimeInputLock/Core transaction and Bot CAS remain authoritative. The correction reads real Core/Bot action/resource truth and exact retained native/run evidence, not a fabricated generic whole-run receipt.
- Evidence fields are `flow_id`, `generation`, `row_version`, `last_attempt_seq`, exact sorted `run_ids`, exact sorted consequential `core_action_ids`, and canonical-root-relative `native_evidence` events.jsonl paths.
- Under the technical cap, review clears the eligible terminal marker without renewing the failure baseline. For an eligible exhausted window, only the audited baseline advances; totals, gameplay counts, generation, UNKNOWN, raw runs and native failed evidence remain intact. An existing flow_inspections constraint migration preserves append-only history rather than replacing it.

Supported form (read the actual help/preview, do not reuse stale CAS values):

```text
python -B scripts/pnsctl.py automation-service --state-path ORIGINAL_DB inspect-rearm FLOW --review-known-progress --evidence FILE --preview
# Mutation additionally requires expected generation, row version, consecutive failures and reason.
```

Five reviews ALREADY succeeded around 17:59 UTC — do not redo them without a new eligible blocker:

| Flow | Preserved failure history / actual review |
| --- | --- |
| Research | generation44,row139→140, failures19, baseline18 retained (one used retry). |
| Farm | generation14,row48→49, failures6, baseline3→6. |
| Material Production | generation26,row97→98, failures12, baseline9→12. |
| Training | generation12,row43→44, failures6, baseline3→6. |
| Donations | generation12,row42→43, failures6, baseline3→6. |

Immutable input manifests:
`Original/.local-captures/canonical-owner-replay-20261109T080850495633Z/known-progress-inspections/`, filenames ending `20261109T175701118947Z.json`.

Audit IDs respectively:
`cc31ab7ceec7443abde22e496cec8d33`, `1160c2d9f32249fe9c3b6783e9864c28`,
`cb6e36c3b28c402cbee21550513c9770`, `72eb05434d604344abc110aacb4f3dd4`,
`14843d836cfa4152ae2db67f9351866e`.

### Latest real Research invocation

After its review, a canonical native Research invocation around 18:00 UTC took ~33.4 seconds. It issued **one harmless mapped Center-entry tap, zero Research starts/debits** and stopped `research_center_radial_successor_unverified`. Actual retained source showed the UPDATE popup **already present before the tap**, so this is the missing shared guard, not missing game cost proof.

The corrected normal-return terminal-marker behavior worked live: afterward Research was disabled, **blocked=false**, blocked_reason=null, generation46,row147, failures20, baseline18, max_attempts3; two technical failures in the retained window, not twenty gameplay starts. These values are historical CAS facts—read fresh values before mutation.

Evidence:

```text
Original/.local-captures/canonical-owner-replay-20261109T080850495633Z/
 research-known-outcome-recovery-and-first-recommendation/
 RECOMMENDED-RESEARCH-BLUESTACKS-INTEGRATION-20261109T175930043003Z-62fac3cb/
 recommended-research-native-20261109T175930137519Z/
```

This native directory has `events.jsonl` and `frames/`, **not a generic summary.json**. Frames0004 immediate-before and0006 settled-successor show the update. Do not invent a missing-summary prerequisite.

## 7. Verification actually performed / remaining diagnostics

### Latest correction-worktree check

Python3.12 / PYTHONPATH unset:

```text
python -B -m unittest tests.test_network_disconnect_recognition tests.test_network_recovery_state tests.test_network_disconnect_recovery tests.test_network_disconnect_boundaries tests.test_network_disconnect_occurrence tests.test_pnsctl_canonical_serve tests.test_route_metadata_consistency tests.test_service_route_contract
```

**188 tests passed in58.688s.** This command ran before the handoff discovered the misplaced worker changes, so the correction versions of recovery/occurrence/boundary tests were the older tests. New retained update recognition and state cases were included; the new Original service/recovery cases were NOT. Re-run the affected selection after coherent port/type fixes, not repeatedly before integration.

Before the update change, required recognition/boundary safety checks passed38. Prior known-progress correction:116 real tests passed in a combined run which also had one loader error from a wrong extra class name; the corrected terminal-projection-failure test separately passed1. **Do not claim that initial combined command exited successfully.** Those checks included inspection admission, pnsctl canonical serve, Research adapter, metadata and service-route contracts.

Supported `recover-network --help` and `inspect-rearm --help` with PYTHONPATH unset started correctly. They are startup proof, not live acceptance.

### Three changed-line Pyright errors still outstanding

1. `scripts/pnsctl.py:705`: cv2.imdecode returns MatLike|None, passed directly to `recognize_shared_interruption`.
2. `scripts/pnsctl.py:853`: restart closure inferred `dict[str,int]`, incompatible with callback `dict[str,object]` because mutable dictionaries are invariant. Explicit appropriate result/return typing is needed; do not weaken the safety callback.
3. `tests/test_network_disconnect_recognition.py:272`: new fixture helper returns cv2.imread MatLike|None as ndarray without narrowing.

No fixes/code actions were applied before pause. LSP quick-fix interface: write JSON to `xd://lsp`, action `code_actions`, file/line/symbol; inspect available actions before manual typing fixes. Do not suppress errors or undertake a repo-wide typing cleanup. Other existing file diagnostics remain, including optional-episode warnings in unchanged recovery code.

Changed-file Ruff reported **16 findings**, not a pass: existing import-layout E402 in service, unused imports, repeated development_session dictionary key in pnsctl, and existing test imports. Do not conflate these with a clean branch or remove unrelated code just to obtain green output.

Full retained latest diagnostics are under the persisted session's `local/`:
`shared-update-ruff.txt`, `shared-update-lsp-diagnostics.txt`,
`update-restart-state-references.txt`, `update-restart-recovery-symbols.txt`,
`update-shared-guard-integration.diff`, `continuation-handoff-facts-20261109.json`.
A fresh `local://` namespace can point elsewhere; use the absolute session directory from section4 if needed. The diff artifact predates the newly discovered Original split and is not a patch to blindly apply.

### Earlier meaningful batch limits

- Latest device-free `scripts/check.py`:413 tests,412 pass, one previously observed host-profile path guard failure in immutable `tests/fixtures/alliance_shop_menu/inventory-repaired-entry/provenance.json`. Do not rewrite raw provenance.
- Immutable-main static ratchet against c6f0e2f failed on integrated-branch findings. No budgets/suppressions raised. No full unittest discovery was run.
- Historical shop groups timed out; older Nano smoke has a stale KEY:BACK expectation; Material negative-output adapter has blocked/unresolved mismatch. Only exercised passing selections are passing evidence.
- Do not re-run broad gates for this documentation-only handoff. At the next real code batch boundary, use documented device-free check/static ratchet proportionally, once, and report retained failures separately.

## 8. Complete route status snapshot and exact remaining scenarios

All listed routes already have native/canonical implementations; this is not a request to rebuild A–F. Status below concerns the latest corrected source/observed scope, not all possible branches.

| Ticket | Concrete implementation and observed native outcome | What remains / do not repeat |
| --- | --- | --- |
| #54 Daily rewards | Canonical PASS: one distinct aggregate35→65, newly glowing60-point chest Claimed, all five slots reobserved, four inputs/two reward actions, native Home. | This bounded scope is accepted. No150 gate. Do not repeat prior batches/30/60 chests; later truly distinct ready batches/newly glowing slots remain eligible. |
| #66 Food | Prior separate canonical exact1KFood acceptance129809→129808. No new Use in walkthrough/replay. | Already accepted scope; no extra same-reset use. Exactly one owned item/decrement when newly due; no Food-balance OCR/Daily ownership. |
| #69 Ruins | `cfb200d` preserves confirmed challenge stages and independent green overview claims; native `RUINS_PASS_VERIFIED`,7inputs,0new effects, Home. Earlier real challenge retained. | Current resumed/no-duplicate path proven; consuming ready-chest branch needs genuinely new ready chests. First allowed challenge, verified wins only until first loss/unavailability; participation need not win. Do not re-dispatch confirmed/lost challenge merely for proof. |
| #56 Help | Corrected ready context admits independently identified enabled free HelpAll without individual names. Native exact empty path verified:6nav,0Help,0credit, Home. | Fresh ready batch/count consuming proof remains. Gold footer can remain after clear; color is insufficient. One HelpAll may serve several requests. Unreadable success count stays uncertain, never invented1/10. |
| #77 Donations | `c3ec958` current HOT/obscured counter/partial results; THREE ordinary native donations confirmed, last15/20→14/20. Original failed whole visit remains failed. | Supported retry review now completed, not still accounting-blocked. Continue only remaining approved quota/budget from3 confirmed, maximum10 total in that explicitly authorized replay (not ten more). Ordinary taps/counter decrement; regeneration does not erase quota. |
| #73 Alliance Shop | `5cf7937` exact Timed Recruit Coin/authorized allowance;1native coin1000Diamonds,owned98→99,stock5→4,Obtained/Home. Outer original failure retained; subsequent canonical confirmed-history PASS0inputs/0buys/Home. | Do not buy again for receipt. Weekly allowlist includes Timed Tavern Coins as exact current UI Timed Recruit Coin; unaffordable preferred must evaluate Other1★Gear fallback, quantityONE total. Current quote/approved finite budget still apply. |
| #72 Daily Shops | `c0e6361` MysteryShop native entry and independent tabs; canonical DEFERRED8nav/0buys/Home:Ruinsstock0;RareEarth4995<13800unitcost,stock5. | Native purchase effects remain evidence_required, not forced while unavailable. Use MysteryShop building, not investigative Ruins entry. Max affordable/stock, numeric quantity/total before Buy; slider endpoint99 was not100. |
| #70 Material | Existing fixed-free21600s one-slot route; prior native production claim Core-confirmed. No new start inferred. | Positive-progress technical review completed. Freshly observe actual idle/active/completed slot; only genuine completed claim/restart. No info/preclaim/resource census. This is NOT Farm resource collection. |
| #71 Normal Craft | Existing same-visit production-first, exact100NanoParts/43200s NormalCraft. Manual radar claim/new craft are historical, not native route acceptance. | At most one new reset start; no extra start to qualify. Preserve100parts cost guard, but do not claim independently observed post-start parts count. Completed claim and new start differ; never ExclusiveCraft. |
| #75 Hero Duel | `dc767bf` actual Survival countdown/free allowance. Native DEFERREDfree0,8inputs,0entries/flees/passes/lineupchanges,Home. | Full3canonical free loadedBattle→Exit→Flee→result→allowance cycles need fresh allowance. Never passes/win requirement. Defense first5CURRENT displayed eligible, save/reopen; retain valid attack lineup/fill missing five slots. |
| #76 Research | `318baef` fresh Home0/1 proof/first ConstructionII/ordered continuity fix. Latest native1nav/0starts stopped on update; marker cleared correctly. | After shared recovery, inspect current queue and first current ordinary recommendation. Detail Research starts; recommendation-row Research navigates. Read prerequisites/all costs/balances; busy/shortage defers. No Queue2/ResearchNow/boxes/substitution. |
| #78 Farm boost | `0169eec` owned same-Farm radial and delayed collection accounting. Prior output collection confirmed;0newBoost. | Positive-progress review completed. Fresh same-Farm Boosting observation/native item/premium paths still need proof. First Farm tap can collect multiple buildings. Item-price1 is not inventory count. Exact authorized premium fallback only; no global FoodOutputBoost/talent prerequisite. |
| #95 Talents | `d7410fd` owner-confirmed FREE exact saved presets. Native Training→Military verified. Later Training Apply/scoped confirmation positively reconciled from assisted fresh Applied readback;0replacementinputs. | Economy native Apply unverified. No redundant switch. Resetnow text is bad saved-Apply translation, not permission for talent-tree Reset/edits. Fresh Applied/context after restart/external change; do not add resource prerequisites to approved free switch. |
| #96 ZombieZero | `d7410fd` mapped Hall/Set1/LOSE reader. Exactly1nativeDispatch, LOSE,damage2166282036; Core positively confirmed. Own reward alreadyClaimed/threechecks,0rewardtaps; Home assisted. | Not fully native end-to-end accepted closure. Do not repeat same-resetDispatch to fix receipt. User confirmed no resource/loss cost. Military→Hall→ZombieZero→QuickSelect savedSet1,5populated heroes/troops; no invented full-cap census. One reward-row tap when actually ready, not three alreadyClaimed icons. |
| #67 Training | `d7410fd` immediate-before Atlas pan and approved configs. Latest native visit6preset inputs/0trainingstarts or claims; Training Applied positively reconciled. | Positive-progress review completed. Observe each current job first; Rider may be completed, do not assume current state. Prove finished corrected path/approved continuation, no duplicate daily Shooter/Rider. Exact F/V boxes remain unexercised; no invented blanket per-SKU census/financial oracle. |
| #74 conditional Wali | Existing guarded implementation/earlier draft; owner changed it to baseline/3ordinary actions/final cumulative-level verification. | Do not require Back/+1 after every input or invent exact final resource-debit oracle. Real cap/evolution/shortage can split; evolution never resets daily count. Bulk-row dismissal path and canonical3-action proof still need observed qualification. Exact Campaign block/150diamondReset unverified and remains blocked. |
| #81 Pit | Investigation only; savedSet1 formation and cancelling preserved5attempts. | No implementation promise. Lighter markers/final battle-fatigue/occupation-collection unverified. Do not execute newPit dispatch as queue work. |

Training configurations are unchanged:

- Fighter T8/current numeric maximum/continuous.
- Vehicle T1/current numeric maximum/continuous.
- Shooter T8/exact250/once daily.
- Rider T1/exact250/once daily.
- Boxes only for exact approved Fighter/Vehicle continuation; Shooter/Rider forbid boxes. No duplicate active jobs.

The normal delivery order remains **#54→#66→#69→#56→#77→#73→#72→#70→#71→#75→#76→#78→#95→#96→#67**, batches A54/66, B69/56, C77/73/72, D70/71, E75/76/78, F95/96/67. Those are review batches, not scheduling directives. The current concrete interruption takes precedence; accepted/unavailable scopes need not be repeatedly executed while independent pending routes can progress.

## 9. Immutable manual effects and later replay authorization

Full report (261screenshots/accounting/authorization/manifest/final status):
`Original/.local-captures/manual-walkthrough-2026-11-09T04-42-35-490Z/walkthrough-report.txt`.
SHA-256 freshly rechecked:
`61bdd23c6740a54b28931ab4ccf3b0d80dd440bb203fdfb8ba1725c18059725b`.

The owner subsequently explicitly authorized selected same-reset supervised replays (Ruins, donations, AllianceShop, shops, production, Duel, research, Farm, talents, ZombieZero, training). This superseded the original no-repeat instruction **only for the actually authorized bounded scenarios**, not blanket duplication or counter resets. Existing recorded authorizations/budgets in replay evidence must be checked. A technical inspection does not create a new replay allowance.

Original November9 manual effects:

- Food inspection only; prior canonical owned129809→129808,0newUse.
- Daily later batch5→35 and30pointchest; earlier0→5 already complete.
- HelpAll served THREE requests, ordered revisit empty.
- Ruins floor61 defeat; eight green chests:Tech324,Gear496,Nova96,Glory408,Module320,Bioenhancer11,Ultimate784,Chip488; total2927medals. NPC challenge casualties are not account losses.
- Ten HOT AllianceSteelPlantCapII ordinary donations, attempts20→10,quoted1000Steel each. One attempt regenerates per30minutes,cap20; no quota renewal from regeneration.
- AllianceShop one1★Gear fallback1000AllianceCoins,owned11052→11053,wallet1395232→1394232. Later explicitly authorized Timed native purchase is separate and already complete; do not buy another.
- RuinsChipx100 for1500,wallet19576→18076,stock100→0. RareEarthModulex15 for207000,wallet211995→4995,stock20→5,owned0→15.
- Free MaterialProduction started06:00:00. Observe actual slot now, not historical timer.
- Completed4★CommonTerrestrialRadar claimed,counter41→42; one newNormalCraft12:00:00,quoted100NanoParts. Post-start balance NOT observed.
- All3freeDuelcycles,free3→2→1→0,points1000→980→960→941,passes125unchanged.
- TroopLoadII ordinary Queue1research started05:56:53; later queue may genuinely finish, inspect current.
- OneFarm-specific itemboost,Boosting23:59:39. Observed48diamond fallback never exercised; itemprice1 was not inventory.
- Military initiallyApplied, specifically approved TrainingApply→Resetnow confirmation once,TrainingApplied re-read. Owner later clarified savedApply is free. No treeReset.
- ZombieZero savedSet1oneDispatch,Today0→2166282036,LOSE; ONEreward-rowtap leftClaimed/threechecks.
- Four newtrainingstarts:FighterT8Veteran1510/20:05:54;VehicleT1Taxi1510/03:08:44;ShooterT8Sharpshooter250/03:19:39;RiderT1Nomad250/00:31:15. Old batches collected at entry are separate claims. No daily Shooter/Riderrestart same reset merely for proof; F/Vmaycontinue only after verifiedcompletion.

Later native acceptance evidence roots:

```text
Original/.local-captures/canonical-corrections-live-20261109T073949341591Z/
Original/.local-captures/canonical-owner-replay-20261109T080850495633Z/
```

Replay root includes `hall-dispatch-positive-reconciliation.json`,
`training-preset-positive-reconciliation.json`, the known-progress inspections, and
`post-replay-disabled-state-20261109T143957577458Z.json`.
The last file is a historical14:39snapshot, not current readiness proof.

Earlier investigative source directories remain under Original `.local-captures/development-sessions/`:
`investigation2-cua-owner-20261106T232501213650Z`,
`investigation2-cua-owner-20261107T001419565481Z`,
`investigation2-cua-owner-20261107T002650251067Z`,
`investigation2-cua-owner-20261107T003344766141Z`,
`investigation2-cua-owner-20261107T005136774123Z`.
Use actual current sources first; those captures are neither current authority nor native acceptance.

## 10. Focused local commit map / reviews / publication gap

Local correction commits, newest first:

| Commit | Scope |
| --- | --- |
| 7994eed | Document actual observed replay versus whole native acceptance. |
| 318baef | Research actual idle proof across ordered transitions. |
| 0169eec | Farm owned radial/delayed collection accounting. |
| dc767bf | Duel current countdown/free allowance. |
| cfb200d | Ruins confirmed-stage resume/no duplicate dispatch. |
| c0e6361 | Independent MysteryShop tab results. |
| d7410fd | Free saved presets/Hall/Training. |
| 3b1b5db | Bounded native accounting/reviewed replay fences. |
| 2829636 | Fresh mapped nighttime Home entries. |
| 5cf7937 | Exact preferred AllianceShop offers/confirmed restart. |
| c3ec958 | Obscured donation attempts/partial results. |
| 92aa95f | Earlier published Daily native acceptance/operational record. |

Historical review stack: A–F draft PRs97–102, conditional Wali103, network105. Later owner-plan drafts106–113/local owner branches are historical separate source boundaries, not automatically integrated/published correction heads. Do not assume a specific draft's current diff without checking it; do not merge any PR or deploy under this task.

Tracker #53 fresh read latest comment at14:45:
https://github.com/mattebad/Puzzles_Survival_Automation/issues/53#issuecomment-6742918394

Its sentence that all five routes require a new durable whole-visit accounting proof is **superseded by the owner correction and the already successful section6 implementation/inspections**. The body latest-status header still points to07:58/published92aa95f. #92 has not yet received the exact update source/implementation progress. #104's body still says manual report pending; report has since been supplied. Preserve historical comments but publish an accurate superseding update when work resumes, with per-route implemented/offline/native states and real next scenarios. Do not claim all tickets already updated for these latest changes.

## 11. Tooling and agents — settled decisions

- The owner asked why workers lacked LSP. Actual configuration was `lsp.enabled=true` but `task.enableLsp=false`. Parent LSP worked; workers received `No such tool: xd://lsp. Mounted devices: ast_edit, debug.` This was an OMP switch, not a missing Pyright installation.
- The owner explicitly requested enabling it overall. **`task.enableLsp=true` was saved to GLOBAL config**, not just this session. No need to ask again or repeat the change. New worker access should be checked normally; older already-spawned tool sets need not be reused.
- Parent real `xd://lsp` status resolved Pyright/Ruff; references/diagnostics were actually obtained. Do not infer missing configured servers from where.exe alone.
- Project requires HIGH-or-higher reasoning for all delegated work, explicit scope, disjoint writable paths, no midflight worker suites. Use task subagents for genuinely independent fixes, not cleanup or every direct question. Current workers `UpdatePopupHigh`, `UpdateRestartHigh` and children are completed/parked; none should be treated as ongoing live operators.
- Last settings inspection showed **`computer.enabled=false`**. Earlier computer-use capability in older chat does not establish present availability. The current process's computer docs lookup was unavailable; no host-desktop computer tool was used in this final pass. The supported native SDK observer still captured the actual game. If CUA is available in the new session, use it as needed under the single-operator boundary; do not pretend a mock is a live walkthrough or spend hours on a substitute without explaining the real limitation.
- Eval/kernel state does not transfer to a new session. Recreate only needed helpers. The previous `start_replay_native` helper was lost on terminal restart and was NOT rebuilt. It is not an existing callable waiting for you. Use documented supported CLI/metadata; do not invent flags or a parallel controller.

## 12. Exact continuation plan / honest outstanding todos

Existing seven execution/publication todos are paused, not complete. A newly discovered consolidation task must precede them:

1. **Consolidate the misplaced update service/test hunks into correction; fix the three changed-line type errors.** Preserve known-progress changes and all Original unrelated work. Use LSP/code actions, explicit absolute paths, one integration owner.
2. **Run proportional focused shared-guard/integration checks on that coherent source**, then the exact currently authorized update recovery through pnsctl if the popup still exists. Retain source/before/transport/after/semantic/terminal proof. One game stop/start, zero game clicks/spend, <=90seconds, no renewed budget after UNKNOWN. Do not force popup if absent.
3. **Research native visit:** after actual recovered Home, fresh queue/list/detail; first recommendation if genuinely idle/affordable; otherwise truthful active/shortage deferral. Never use the remaining technical window for blind repeated navigation.
4. **Farm native visit:** sameFarm current Boosting/owned item branch; no duplicate boost or invented prerequisites. Account actual first collection.
5. **MaterialProduction native visit:** fresh slot state; activeobserve or genuinely completedclaim/restart/freeidleProduce, no duplicate slot. #71 only when actually eligible, afterproduction samevisit; no secondNormalCraft merely for acceptance.
6. **Training native visit:** fresh TrainingApplied without redundant switch, inspect four camps/currentjobs; approved due work only. Daily Shooter/Rider exclusions survive reset-aware reconciliation; no guessed box path.
7. **Donation continuation:** preserve3confirmed in authorized replay; inspect currentHOT/attempts/remaining approved reset quota/resourcebudget; individually verify up to remaining7, not tenmore or cap20hold.
8. **Other per-ticket gaps stay visible:** freshHelpreadybatch; newlyreadyRuinschests; affordablein-stockshop purchases only when actuallydue;3Duelcycles only withfreshallowance; EconomyApply; wholeHallclosure without re-dispatchingconfirmedwork; conditionalWali. Observe/defer available currentstates and continue independentwork; do not stop the queue for one unavailablebranch.
9. **Publish/commit reviewable coherent changes:** update docs and tickets/tracker with actual separate statuses and exact nextscenarios; report baselinechecks honestly; controlsOFF aftereachboundedvisit. No merges/deployment/scheduling. Do not close a ticket whose acceptance is incomplete.

Flow IDs / existing serve aliases for the immediate pending five:

| Flow ID | Alias |
| --- | --- |
| RECOMMENDED-RESEARCH-BLUESTACKS-INTEGRATION | recommended-research |
| FOOD-FARM-OUTPUT-BOOST-DAILY-BLUESTACKS-INTEGRATION | food-farm-boost |
| NANO-MATERIAL-PRODUCTION-MAINTENANCE | nano-material-production |
| TROOP-TRAINING-END-TO-END-CONSOLIDATION | troop-training |
| ALLIANCE-TECH-DONATION-BLUESTACKS-INTEGRATION | alliance-donation |

Use `pnsctl automation-service ... serve --help`/current composition for actual supported options. Prior canonical visits used bounded `--once --max-duration-seconds 180` (longer finite route budgets only when supported/needed), exact selected aliases, explicit fixed bindings, and finally restored OFF controls. Service registration, flow enablement and scheduling remain distinct. Do not leave controls on if an exception interrupts cleanup.

The new session should create explicit per-ticket/phase todos from these actual states, not replay this whole chat or regenerate an implementation plan already approved. It should first report the cross-worktree consolidation and then advance the real routes once resumed.
