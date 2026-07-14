# Canonical execution backlog

Last updated: 2026-07-14 (America/Chicago)

This is the single authoritative task/status record. The service plan controls technical
requirements and measured facts. Evidence records contain observations, not competing status.

## Production boundary

The complete production system runs on the Unraid NAS: Android or BlueStacks runtime, controller,
scheduler, computer vision/OCR, persistent state, logs, monitoring, watchdog/recovery, and
startup behavior. Production continues when every external computer is powered off.

External Windows/macOS computers are development, SSH administration, monitoring, viewing,
maintenance, or manual-takeover tools only. Production must not depend on external hardware,
an externally maintained SSH tunnel, PowerShell on another machine, Cursor, Codex, MCP, an LLM,
APIs/tokens, or a physical Android device. Worker-to-Android communication uses a local/private
Unraid path.
Tutorial, account login, account provisioning, account switching, and credential entry remain
permanently manual-only.

Automated gameplay may carry account-enforcement risk under the current
[Puzzles & Survival Terms](https://gpassport.pnsofficial.com/center/ServicePrivicy/service?gameId=191&language=en-US).
This is a documented project risk, not a separate development approval or acknowledgment task. The
project will not implement stealth, anti-detection, enforcement bypass, humanization intended to
evade enforcement, or other evasion behavior.

## Input authorization boundaries

Manual user input may operate the game for provisioning, debugging, identity exposure, calibration,
recovery, or supervised development. It does not require a project acknowledgment task. Tutorial,
login, credentials, account switching, CAPTCHA handling, and account restoration remain permanently
manual-only.

Agent-driven supervised development input may send a specific game input only when all applicable
technical conditions hold:

- The selected task has reached its supervised-validation stage.
- The input is explicitly within that task's scope.
- Source state and expected successor are defined.
- Target, consequence, cost, quantity, and policy are known.
- No premium or unknown resource use is possible.
- Before/after evidence is retained.
- Timeout or ambiguity becomes unresolved; it never causes a blind retry.

This is technical task-specific authorization and promotion, not a personal risk acknowledgment
gate.

Unattended automatic gameplay input requires all applicable technical gates:

- Selected and locked runtime/profile.
- Secured recovery backup.
- Deterministic controller and policy gate.
- Persistent action journal.
- Fail-closed account/session guard.
- Applicable task replay, observe-only, dry-run, and supervised-validation stages.
- Exact allowlists, limits, reserves, and retry policy.
- No unresolved consequential action.

Fallback order:

1. Bliss OS or another Android-focused VM under Unraid KVM, with deterministic worker in Unraid
   Docker.
2. Another Android runtime isolated inside an Unraid-hosted VM.
3. Windows VM hosted on Unraid running BlueStacks, only after nested virtualization, graphics,
   persistence, and NAS-stability tests pass.

External Windows hardware is out of scope unless the user explicitly changes the NAS-only
requirement.

## Development SSH boundary

Existing SSH credentials are development-only administrative credentials. They must not be
committed, stored in durable plan/evidence files, printed into retained logs, or embedded in
scripts. A process-only `UNRAID_TEMP_PASSWORD` may be used for development execution. The current
RT-012/RT-014A SSH issue is a development execution blocker, not a production architecture
dependency; no dedicated SSH-key task is a production blocker.

## Evidence maintenance

### EVIDENCE-RETENTION-HYGIENE — Audit and safely compact local evidence

- Dependencies: canonical repository state, protected evidence inventory, and the existing Git/
  journal safety boundaries.
- Objective: distinguish tracked canonical evidence from local raw captures, protect fixtures,
  templates, decisive/unresolved evidence, journals, and references, then archive only conclusively
  safe duplicates with verified recoverability.
- Status: Passed (2026-07-14).
- Before: 4,660 evidence files totaling 1,888,103,865 bytes; tracked 1,511/425,828,236 bytes;
  untracked 2,253/1,447,595,565 bytes; ignored 896/14,680,064 bytes. The dry-run identified
  1,761 exact-duplicate or repeated-identical-frame candidates totaling 1,278,502,180 bytes.
- Result: policy, narrowed ignore rules, streaming audit/archive/verify tooling, deterministic
  tests, and a concise report were committed in `fc96e84`. The candidates were copied to the
  external content-addressed archive at `../Puzzles_Survival_Automation_evidence_archive/`, all
  1,761 manifest entries verified, and only then removed locally. The archive has 137 unique blobs and
  1,761 verified path mappings; its measured footprint is 133,173,029 bytes (131,353,624 bytes of
  deduplicated blobs).
- After: local evidence is 609,601,685 bytes across 2,899 files; tracked evidence is unchanged;
  untracked evidence is 169,093,385 bytes and ignored journal sidecars are 14,680,064 bytes.
  Active-checkout recovery is 1,278,502,180 bytes. Git history was not rewritten, garbage-collected,
  repacked, or force-pushed; reachable evidence blobs remain 1,001/291,331,222 bytes and the
  history-only upper bound remains 447,731 bytes.
- Verification: evidence-hygiene and reference tests pass (17/17), the non-OpenCV suite passes
  (131/131), and the authoritative discovery reaches 137 tests with only the six existing local
  `cv2` import errors. `.local-reference/`, protected evidence, journals, and runtime state were
  preserved; no live gameplay input occurred.
- Next: continue Phase E with generalized Daily Claim, milestone, Depot Free, and recruitment Free
  contract/evidence work. Do not authorize Daily Claim, milestone, Depot Free, or recruitment Free
  input without fresh Bliss-native target, free/cost-negative, and positive-postcondition evidence.
  Live evidence acquisition remains the next gate.

## Milestones

| Milestone | Status | Dependency / blocker |
|---|---|---|
| M1 Repository/environment baseline | Passed | Host/VM baseline and rollback XML captured; authentication hard-stop manually resolved and verified |
| M2 Unraid audit | Passed | Measured in service plan on 2026-07-09 |
| M3 Direct Bliss runtime proof | Passed | RT-001 through RT-013 passed; downstream infrastructure and later account-guard gates remain |
| M4 One-time account provisioning | Passed for current Bliss runtime | Must remain manual on any rebuild |
| M5 Framework bake-off | Passed | Custom Python/direct ADB/OpenCV/local OCR selected; Airtest and MaaFramework rejected early |
| M6 Production corpus | In Progress | M6-DQ-BOOTSTRAP Passed; M6-DQ-TRANSITION-CORPUS remains later before the complete M6 corpus can pass |
| M7 Deterministic service core | In Progress | M7-SAFE-ACTION-CORE Passed; full core, M7-Takeover, and M7-AccountGuard remain later gates |
| M8 Claim-only MVP | Blocked | Selected runtime, staged corpus, full core, and promotion gates; one supervised trial does not pass M8 |
| M9 Expanded tasks | Pending | Claim-only MVP evidence |
| Milestone 10 — Production hardening and operational acceptance | Pending | Production task catalog |

Framework bake-off was time-boxed and is now closed with Custom Python + ADB + OpenCV + local OCR
selected. The completed comparison used one representative safe flow: 50–100 captures per
candidate, 20–25 safe
target-resolution trials, 10 safe gesture-resolution trials, 5–10 reconnect cycles, one
detector, one OCR region, one bounded navigation flow, and packaging/policy-gate integration
review. Prefer offline replay, mocks, and dry-run annotations; do not manufacture live game
inputs. Stop evaluating a candidate when its reliability or maintainability benefit clearly does
not justify added complexity. Reserve the selected adapter's larger validation set—500 captures
and 100 supervised inputs—for the chosen adapter.

## M5 candidate evaluation tasks

### M5-CUSTOM-BASELINE — Benchmark incumbent deterministic stack

- Dependencies: MVP-STARTUP-NORMALIZATION, RT-019, and RT-021.
- Objective: measure the existing Python/direct ADB/OpenCV/local-OCR implementation on the
  retained startup corpus and safety contract.
- Scope: offline replay and image decoding, Cash Mall/Ending Soon/Home/Base/negative
  classification, target annotation, OCR, stale/profile/unknown rejection, policy-contract
  mocks, and retained RT-010/RT-021 live facts. No live game input.
- Acceptance: 100 replay capture/classification operations; 25 target annotations; 10 OCR
  operations; 10 safe gesture-resolution trials; 5 reconnect simulations; retained live ADB
  capture/reconnect evidence; packaging/resource/diagnostic/maintainability review; all expected
  outcomes pass and every limitation is recorded.
- Evidence: `evidence/sessions/20260712-m5-custom-baseline/`.
- Rollback: remove only task-scoped benchmark script/evidence; preserve all passed runtime and
  MVP evidence.
- Status: Passed (2026-07-12; offline baseline benchmark complete).
- Blocker: None. The incumbent baseline met the replay, policy, packaging, and diagnostic
  criteria; live ADB capture/reconnect facts remain explicitly attributed to RT-010/RT-021.
- Next: M5-AIRTEST.

### M5-AIRTEST — Evaluate policy-constrained Airtest adapter

- Dependencies: M5-CUSTOM-BASELINE.
- Objective: determine whether Airtest provides a measurable benefit for the representative flow
  without bypassing the central policy gate.
- Scope: minimal offline/mock adapter or packaging review only; no framework auto-watchers,
  coordinate scripts, retries, live game taps, or scheduler/controller rewrite.
- Acceptance: identical corpus and target/policy tests, dependency and unprivileged-worker
  packaging assessment, reconnect and diagnostics assessment, and evidence-backed Passed or
  Rejected decision.
- Evidence: `evidence/sessions/20260712-m5-airtest/`.
- Rollback: remove only task-scoped prototype/evidence; no live runtime changes.
- Status: Rejected (2026-07-12; early packaging/policy rejection).
- Blocker: None. Airtest was absent from the approved worker image; its dependency surface and
  direct simulated-input API could not be introduced without an unproven packaging and policy
  adapter, and no measurable benefit over the passed custom baseline was established.
- Next: M5-MAA.

### M5-MAA — Evaluate policy-constrained MaaFramework adapter

- Dependencies: M5-AIRTEST.
- Objective: determine whether MaaFramework provides a measurable benefit for the representative
  flow without introducing uncontrolled watchers, retries, or policy bypass.
- Scope: minimal offline/mock adapter or packaging review only; no live game input, generic popup
  handlers, coordinate scripts, or scheduler/controller rewrite.
- Acceptance: identical corpus and target/policy tests, dependency and unprivileged-worker
  packaging assessment, reconnect and diagnostics assessment, and evidence-backed Passed or
  Rejected decision.
- Evidence: `evidence/sessions/20260712-m5-maa/`.
- Rollback: remove only task-scoped prototype/evidence; no live runtime changes.
- Status: Rejected (2026-07-12; early packaging/policy rejection).
- Blocker: None. MaaFramework was absent from the approved worker image; its native/pipeline
  packaging and central-policy adapter were not demonstrable within this boundary, and no
  measurable benefit over the passed custom baseline was established.
- Next: M5-DECISION.

### M5-DECISION — Select final deterministic control stack

- Dependencies: M5-CUSTOM-BASELINE, M5-AIRTEST, and M5-MAA.
- Objective: select the lowest-complexity framework that reliably satisfies the project
  requirements and authorize M6.
- Acceptance: comparative measurements, selected role, rejected-candidate reasons, packaging and
  policy implications, reconnect/failure behavior, maintainability, limitations, fallback
  conditions, evidence links, and explicit authorization to proceed to M6 are recorded.
- Evidence: `evidence/sessions/20260712-m5-decision/`.
- Rollback: retain all candidate evidence; revert only the decision documentation if review
  rejects the selection.
- Status: Passed (2026-07-12; custom deterministic control stack selected).
- Blocker: None. M5 authorizes M6 final-runtime corpus capture/replay validation; M6 was not
  started in this run.
- Next: M6-DQ-BOOTSTRAP.

## M6 production corpus gate

Every recognition asset created during M6 must declare its compatible runtime-profile version.
Corpus validation fails when the asset/profile field is missing, malformed, or mismatched. M6
is now Ready because the M5 framework bake-off and final-runtime stack-selection gate passed;
the RT-019 versioned profile schema is complete. M6 is staged because a positive Daily Quest
Claim row may not exist before a quest is completed. M6 passes only after both the bootstrap
corpus and the later transition corpus pass; the bootstrap task may pass without a positive
Claim example.

### M6-DQ-BOOTSTRAP — Capture Daily Quest bootstrap corpus

- Dependencies: M5 Passed, RT-019 Passed, and MVP-STARTUP-NORMALIZATION Passed.
- Objective: capture the final-runtime Daily Quest states that can be observed before completing
  a quest, without creating a Claim row or sending Claim input.
- Scope: final-runtime `800x1280` Home/Base; Quest entry; Quest screen; Daily Quest tab;
  incomplete objective rows; Go or equivalent non-claim state; points, reset, and header regions;
  clipped-row and confusing-negative examples; candidate zero-cost prerequisite quest screens
  where observable; navigation targets; and forbidden regions. Do not complete a quest or claim a
  reward in this task.
- Acceptance: every executable asset is a final-runtime capture and declares the current RT-019
  profile identifier; the corpus validator rejects missing or mismatched profile metadata;
  incomplete, Go, clipped, stale, unknown, and negative examples are represented; and
  recognition abstains when evidence is insufficient.
- Verification: offline replay, observe-only classification, and dry-run target annotations. No
  quest completion or Claim input is authorized.
- Evidence: `evidence/sessions/<timestamp>-m6-dq-bootstrap/`.
- Rollback: disable or remove only unpromoted task-scoped corpus assets and annotations; preserve
  prior runtime, startup-normalization, and M5 evidence. No runtime mutation is part of rollback.
- Status: Passed (2026-07-12; final-runtime bootstrap corpus and bounded scroll evidence closed).
- Blocker: None. The prior Daily-tab input was confirmed by retained immediate/settled evidence;
  fresh reconciliation, profile-compatible asset promotion, Go-not-Claim negatives, clipped-row
  abstention, synthetic fail-closed fixtures, bounded scroll overlap, and cleanup all passed.
  No Claim, Go, quest-completion, or spend input was recorded. A positive completed-but-unclaimed
  Claim state remains intentionally deferred to `M6-DQ-TRANSITION-CORPUS`.
- Next: M7-SAFE-ACTION-CORE Passed; `MVP-QUEST-TO-CLAIM` is now Blocked by its retained
  pre-dispatch freshness-policy denial.

### M6-DQ-TRANSITION-CORPUS — Promote live transition evidence

- Dependencies: MVP-QUEST-TO-CLAIM Passed.
- Objective: promote retained supervised quest-to-claim transition evidence into the M6 corpus.
- Scope: completed-but-unclaimed objective row; positive Claim control; exact Claim versus Go
  negatives; prepared and immediate pre-input frames; reward popup or toast if present;
  claimed/changed row; points before and after; postcondition evidence; and all failure or
  ambiguity examples retained during the trial.
- Acceptance: M6 Production Corpus is Passed only when `M6-DQ-BOOTSTRAP` and
  `M6-DQ-TRANSITION-CORPUS` both pass, with profile-compatible metadata and fail-closed replay
  results for the complete staged corpus.
- Verification: replay the promoted triplets and negatives, validate profile metadata, and
  review the supervised-trial evidence against each transition criterion.
- Evidence: `evidence/sessions/<timestamp>-m6-dq-transition-corpus/`.
- Rollback: remove only unpromoted transition assets; retain the supervised-trial and failure
  evidence and leave claim automation disabled until the corpus is reviewed.
- Status: Pending.
- Blocker: No successful supervised quest-to-claim trial has yet supplied the required positive
  transition state.
- Next: full M6 corpus review and later claim-only promotion gates.

## M7 controller integration tasks

### M7-SAFE-ACTION-CORE — Implement minimum supervised-action safety core

- Dependencies: M6-DQ-BOOTSTRAP Passed.
- Objective: implement only the fail-closed safety machinery required for one supervised Daily
  Quest claim trial.
- Scope: central policy authorization; one exclusive executor path; persistent SQLite action
  journal; `prepared → input_sent → confirmed/unresolved` lifecycle; source-frame hash and
  timestamp; runtime-profile guard; fresh-frame requirement; target and consequence
  authorization; immediate pre-input recapture; exactly-one-input semantics; immediate
  post-input observation; no-blind-retry handling; unresolved-action global block; and
  mocked/offline tests.
- Non-goals: scheduler daemon, continuous automation, full watchdog, VM lifecycle recovery,
  unattended deployment, or the remainder of the full M7 service core.
- Acceptance: every supervised-action safety criterion is covered by mocked/offline tests and a
  retained review; stale/profile-mismatched/unknown frames, policy denial, duplicate input, and
  unresolved outcomes fail closed; and no executor path exists outside the central policy gate.
- Verification: unit and integration tests with mocked device/capture/transport failures and
  action-journal crash-boundary replay. No live game input is authorized by this task alone.
- Evidence: `evidence/sessions/20260712-m7-safe-action-core/`.
- Rollback: disable the new executor/core path and restore the prior repository behavior; retain
  failed test evidence and do not alter runtime state.
- Status: Passed (2026-07-12).
- Result: schema version 1, persistent controller lease and action journal, structured central
  policy decisions, injected exactly-one-input executor, startup reconciliation, append-only
  audits, and M6 fixture guards passed deterministic offline tests. The resumed freshness review
  binds frame age to monotonic successful-capture completion, separates the 3.0-second proposal
  limit from the 2.0-second dispatch hard maximum and post-input timeout, permits prior OCR reuse
  only across exact critical-ROI hashes, and retains at most two audited pre-dispatch attempts in
  one prepared semantic action. Every persisted
  `prepared` or `input_sent` restart boundary becomes unresolved without replay; positive
  evidence is required to reconcile it to confirmed. No Unraid, VM, ADB, container, network, or
  game access occurred. The focused Daily Quest task-module boundary now supplies typed
  `PROGRESS/DONE/RETRY/BLOCKED/FAILED_SAFE` outcomes, fixed-profile anchor specifications, local
  navigation steps, explicit navigation/action popup modes, route dispatch, and transaction
  intent semantics without reopening this passed core. The complete dependency-complete suite is
  96 passing tests. The narrow startup escape-only extension also passed offline: only
  `UNKNOWN_PROMOTIONAL_WITH_VERIFIED_BACK` with an isolated standard game Back arrow can authorize
  `SAFE_PROMOTIONAL_BACK`; explicit forbidden-region separation, bounded successors, and a three-action
  sequence limit are enforced. The current combined suite is 96 passing tests (the prior core boundary was 78).
- Blocker: none; dependency satisfied by M6-DQ-BOOTSTRAP.
- Next: MVP-QUEST-TO-CLAIM.

### M7-Takeover — Integrate safe manual takeover with controller

- Dependencies: RT-014A and M7 deterministic service core.
- Objective: enable manual takeover only after controller safety capabilities exist.
- Scope: pause executor; acquire exclusive device lease; verify no unresolved consequential action;
  enable operator input; release lease; capture fresh state; reverify expected account; reconcile
  task/action state; resume only from a newly classified state.
- Non-goals: replacing RT-014A viewer transport proof, unattended production dependence on a viewer,
  credential entry, tutorial input, or concurrent daemon/operator input.
- Acceptance: executor pause and exclusive lease are enforced; unresolved actions block takeover;
  daemon and operator cannot send input concurrently; release, fresh capture, strong account
  verification, reconciliation, and newly classified resume are all evidenced.
- Verification: controller policy tests, lease tests, injected unresolved-action tests, and
  supervised manual review.
- Status: Pending.
- Blocker: controller implementation; RT-014A remains the independent transport prerequisite.
- Next: production manual takeover enablement.

### M7-AccountGuard — Implement fail-closed account/session guard

- Dependencies: RT-016A and M7 deterministic service core.
- Objective: enforce account/session safety before any consequential controller input.
- Scope: account/session detection; global input lock; expected/unknown/mismatch outcomes; account
  logged in on another device; login required; tutorial/new-account; wrong account; session loss;
  CAPTCHA/authentication challenge; notification; low-frequency backoff; manual restoration; and
  strong re-verification.
- Strong identity verification uses numeric player/account ID, server/state identifier, and
  secondary account evidence. Require it at daemon startup, after game restart, after Android or
  VM restart, after session-related overlays, after manual takeover, after manual account
  restoration, and when cached strong verification exceeds configured TTL.
- Lightweight session guard uses expected account-specific screen markers, absence of
  login/tutorial/session-loss overlays, matching runtime/profile identity, and still-valid cached
  strong verification within configured TTL. Require it before each consequential action and
  periodically during long-lived sessions. Do not navigate to the full account/profile page before
  every action.
- Any lightweight mismatch, uncertainty, or expired strong-verification TTL blocks consequential
  input and triggers strong verification or manual intervention.
- Non-goals: credential entry, login automation, account switching, tutorial automation, stealth,
  anti-detection, enforcement bypass, or evasion.
- Acceptance: every listed hard-stop state saves evidence, notifies once, blocks input, enters
  low-frequency backoff without repeated game restarts, waits for manual restoration, and requires
  strong account/server re-verification before resume. Lightweight checks and strong-verification
  TTL behavior are separately tested.
- Verification: expected/unknown/mismatch tests, overlay/session-loss tests, TTL-expiry tests,
  global input-lock tests, and manual-restoration reconciliation.
- Status: Pending.
- Blocker: controller implementation; RT-016A remains the independent identity-evidence prerequisite.
- Next: task-specific supervised-validation prerequisites for agent-driven supervised gameplay input;
  unattended input additionally requires RT-017 and all applicable M7 and task-promotion gates.

## M8 claim-only MVP validation

### MVP-QUEST-TO-CLAIM — Complete one supervised Daily Quest vertical slice

- Dependencies: M6-DQ-BOOTSTRAP Passed, M7-SAFE-ACTION-CORE Passed,
  MVP-STARTUP-NORMALIZATION Passed, and no unresolved action.
- Objective: prove one bounded, supervised Daily Quest quest-to-claim transition using the
  selected runtime and the minimum safety core.
- Scope:
  1. Navigate to Daily Quest.
  2. Determine whether a completed, unclaimed row already exists.
  3. If none exists, complete exactly one approved zero-cost R1 objective.
  4. Verify that the corresponding row becomes Claim.
  5. Claim exactly that one row.
  6. Prove the postcondition.
  7. Stop.
- Prerequisite policy: prefer Alliance Help only when the exact zero-cost action is positively
  recognized. A proven-free Supply Depot action may be the fallback. No resource-consuming
  substitute is permitted without explicit user authorization.
- Boundary: this is agent-driven supervised development input, not unattended automatic gameplay.
  RT-016A and M7-AccountGuard remain required before unattended automatic gameplay, but do not
  block this one supervised trial when the task-specific source, target, consequence, cost,
  evidence, journal, and unresolved-action requirements are satisfied.
- Acceptance: exactly one approved zero-cost prerequisite, if needed, produces one positively
  identified Claim row; exactly one Claim input is sent through the central policy/executor path;
  the claimed-row/reward/points postcondition is positively verified; all before/action/after and
  failure evidence is retained; and any ambiguity becomes unresolved without retry.
- Verification: offline replay and dry-run coverage from M6-DQ-BOOTSTRAP, then one supervised
  live trial with immediate pre-input recapture, one input, bounded postcondition observation,
  and independent reconciliation. Do not continue into Daily Quest claims or other gameplay after
  this trial.
- Evidence: `evidence/sessions/20260712-mvp-quest-to-claim/`.
- Rollback: stop at the first unknown or unresolved outcome, preserve the action journal and all
  frames, disable further claim input, and reconcile manually; no blind retry or resource-consuming
  fallback is allowed.
- Status: Blocked (2026-07-13; individual Help and actual lower Help All are live-validated, no help request was available, and the full quest-to-claim flow remains incomplete).
- Blocker: the typed continuation report named Vehicle Depot, Ultimate Challenge, Hunt Zombie,
  Own Hero, Gathered Food, and Headquarters wording, but provenance audit found no admissible
  selected-Daily proof for them. The retained raw frame for the first four visibly has Main Quest
  selected; Gather Food is synthetic-only and Headquarters is documentation-only. They remain
  outside this Daily roadmap. No ordinary Claim row, Alliance Help objective, or explicitly free
  Supply Depot objective was observed. No current `game_day_id` was assigned. No Go or Claim input
  was sent.
  The schema-v1 live journal has only terminal actions, zero unresolved/nonterminal records, and a
  released lease. The full combined offline suite remains 96 passing tests; RT-019 and all six M6
  assets pass. Resume only after a fresh Daily observation positively establishes reset/game-day
  identity and a supported zero-cost objective or existing ordinary Claim row. Never reuse prior
  action keys.
- Latest read-only reconciliation at remote time `2026-07-12T20:31:08-05:00` found an already-running
  task-scoped worker and resumed game activity, but the fresh `800x1280` frame was a purchase/top-up
  surface. The Daily Quest recognizer abstained and reset/game-day identity could not be assigned.
  No lease, journal action, transport call, or game input occurred. The worker/image were inspected,
  evidence retained, the game force-stopped, and only those task-scoped resources were removed; no
  task listener/tunnel remained and RT-017 stayed intact. Offline review added a narrow escape-only
  policy for the retained top-up surface; it recognizes only the isolated standard game Back arrow
  and does not authorize purchase, reward, Claim, quantity, or offer controls. The live attempt sent
  exactly one authorized Back tap and reconciled its Home/Base successor; the following Home→Quest
  proposal cancelled before dispatch because the prior recognizer treated harmless Home/Base animation as a source change, with zero transport calls. The corrected navigation contract now uses stable local source/target/overlay ROIs, not full-frame equality; navigation failure is separate from unresolved consequential action. No Quest, Daily
  Quest, prerequisite, Go, Claim, or spend input occurred. Resume only after a fresh startup
  reconciliation positively recognizes a safe canonical screen and the post-reset game day.
- Latest live continuation on 2026-07-13 reached Daily Quest through one verified promotional Back,
  Home→Quest, and Quest→Daily navigation input each, then sent two journaled navigation-only list
  swipes. Home→Quest and Quest→Daily were positively reconciled from fresh local ROI successor
  evidence without retry. The task-scoped worker was removed after evidence preservation; the game
  was force-stopped; no task worker, ADB server, tunnel, or public listener remained; the VM stayed
  running and RT-017 remained intact. Details are in
  `evidence/sessions/20260712-mvp-quest-to-claim/live-continuation-20260713.md`.
- Selected Daily-tab correction and retest on 2026-07-13: `4f26889` now requires selected-tab
  evidence and rejects Main Quest as Daily; `f3373f8` tightened the actual Main Quest Daily-tab
  target from `(260,80,540,300)` to `(300,70,500,140)`, centering the tap at `(400,105)`. The
  old `(400,190)` attempt remained on Main Quest and is retained as navigation-only no-effect
  evidence. A new safe-action record then confirmed Quest→selected Daily with exactly one input.
  No Daily Quest objectives were inspected and no Go, Claim, prerequisite, spend, combat, account,
  or OS input occurred. The 100-test suite, RT-019, and six-asset M6 validation pass. Evidence is
  retained in `evidence/sessions/20260712-mvp-quest-to-claim/live-selected-tab-retest-20260713/`.
- Latest live inventory and handler attempt on 2026-07-13: selected Daily Quest was positively
  recognized and the complete bounded list inventory was retained in
  evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/. No ordinary
  Claim row was present. The exact Help allies row was 0/10; its navigation-only Go action
  was confirmed to the Alliance Help screen, and the narrow AllianceHelpHandler was added in
  c1b32e7. Reset evidence supported game_day_id=daily-2026-07-13 and the action was outside
  the configured reset guard. One zero-cost Help transaction was authorized, prepared, recaptured,
  dispatched exactly once, and persisted as unresolved because the post-dispatch evidence still
  showed Help 0/30. No retry, quest completion, or Claim input occurred. The unresolved action
  blocks all later consequential input until positive manual reconciliation. The task worker and
  task ADB server were removed after evidence preservation; the game remains on Alliance Help to
  preserve the unresolved state, the lease is released, the VM is running, and RT-017 is intact.
- Next: Resume `MVP-QUEST-TO-CLAIM` after reset/game-day and supported-objective evidence;
  `M6-DQ-TRANSITION-CORPUS` remains downstream.
- Alliance Help semantic correction on 2026-07-13: ROI `(556,274)-(727,330)` and tap
  `(641,302)` are the upper individual button labeled Help, not Help All. The immutable historical
  journal remains unchanged; metadata records the action as `ALLIANCE_HELP_ONE` with one request
  processed. The distinct actual `ALLIANCE_HELP_ALL` target is the lower button at
  `(277,1188)-(523,1268)`, center `(400,1228)`. The handler now prefers the lower Help All
  action and permits exactly one individual Help only as fallback. The actual lower action
  `alliance-help-1783986842` passed its literal-label/geometry artifact, dispatched exactly once
  at `(400,1228)`, and was positively reconciled from the first post frame's transient exact
  `No help request currently` message. The immutable source journal is retained; its reconciled
  copy has zero unresolved/nonterminal actions. No Claim or Daily Quest completion is proven;
  M6-DQ-TRANSITION-CORPUS remains downstream.
- Personal Might Praise implementation attempt on 2026-07-13: catalog alias matching,
  `PRAISE_PERSONAL_MIGHT` zero-cost transaction, seven named route steps, selected Daily Quest
  Claim contracts, and reset-time popup route are offline-tested. Fresh evidence recognized the
  `Get Pts` popup. Review found prior ROI `(200,590)-(440,710)` and tap `(320,650)` above the
  actual Close button, over streak text. Correct binding is ROI `(260,750)-(540,870)`, OCR
  `Close` bounds `(363,795)-(436,817)`, center `(400,810)`. The one prior navigation-only tap
  was reconciled as proven no-effect in
  `evidence/sessions/20260713-personal-might-praise/live-popup-unresolved-005/`. No Praise,
  Claim, or unrelated gameplay input occurred. Do not rerun without new authorization. MVP
  remains Blocked.
- Corrected popup validation on 2026-07-13 detected bounds `(277,767)-(523,847)` and dispatched
  exactly one interior tap at `(400,807)` after the full-frame pre-dispatch artifact passed.
  Direct operator observation confirmed the popup disappeared. Executor did not classify the
  resulting startup surface, so retained action `reset-popup-close-1783994269-2` still records
  unresolved pending manual reconciliation. No second popup tap occurred. Evidence is retained
  in `evidence/sessions/20260713-personal-might-praise/live-corrected-popup-006/`.
- Phase 2 then stopped after two equivalent `normalize-alliance-to-home` pnsctl failures from
  the positively identified Speedup Help surface. First failure could not bind the icon-only Back
  control; second attempt bound the fixed ROI but cancelled at immediate revalidation with
  `OVERLAY_STATE_CHANGED` and no transport call. No Praise or Claim input occurred. Evidence:
  `live-phase2-route-007/` and `live-phase2-route-008/`.

## GnBots static-reference bootstrap phases

### GNB-PHASE-A — Complete normalized authorized-trial manifest

- Dependencies: existing M1–M7 work preserved; authorized static reference present locally.
- Scope: static text/image metadata inspection only; no vendor execution, source copying, vendor
  runtime dependency, or vendor image promotion.
- Acceptance: all 12 modules covered by stable IDs; source xywh and normalized xyxy ROIs retained;
  points, thresholds, tries, confirms, waits, swipes, loops, recovery, completion semantics,
  weaknesses, unresolved helpers, and direct/inferred status recorded; production runtime contains
  no `.local-reference` dependency; focused tests pass.
- Evidence: `docs/research/gnbots_trial_reference_manifest.{md,json}` and
  `evidence/sessions/20260713-gnbots-reference-manifest/record.md`.
- Status: Passed (2026-07-13).
- Next: GNB-PHASE-B.

### GNB-PHASE-B — Calibrate reference geometry to Bliss

- Dependencies: GNB-PHASE-A Passed.
- Scope: development-only transform candidates, raw 800×1280 retained correspondences, residuals,
  safe-containment checks, and explicit missing-evidence dependencies. Provisional coordinates
  cannot authorize production input.
- Acceptance: direct 2×, top/bottom 12-logical-pixel inset, independent axis scaling, and affine
  fitting are tested; points and normalized ROIs transform correctly; report cites raw Bliss
  evidence and records unsupported screens without guessing.
- Evidence: `docs/research/gnbots_bliss_coordinate_calibration.{md,json}` and
  `evidence/sessions/20260713-gnbots-coordinate-calibration/record.md`.
- Result: raw Rankings bounds are `(602,1138)-(690,1167)`, center `(646,1152)`; historical broad
  center `(400,1152)` is not a valid Rankings target. All transformed outputs are non-authorizing.
- Status: Passed (2026-07-13).
- Next: GNB-PHASE-C after a focused passing commit.

### GNB-PHASE-C — Prepare Bliss profile, navigation, and required popups

- Dependencies: GNB-PHASE-B Passed.
- Scope: Personal Might route only; test-proven gaps in existing NavigationRunner; VIP/reset and
  Help WebView handling; unknown/cost/resource/premium blocking; narrow route perception.
- Offline result: Rankings target corrected to `(602,1138)-(690,1167)`; declared navigation
  anchors/postconditions and provisional evidence gates are enforced; popup registry is limited to
  VIP Points reset and Help WebView; full suite passes 172 tests.
- Evidence: `docs/research/bliss_profile_provenance.md` and
  `evidence/sessions/20260713-gnbots-profile-navigation-prep/record.md`.
- Live result: exact Rankings tap `(646,1152)` confirmed the Leaderboard successor with one
  transport call and no Help interception. Successor proves Personal Might row and Check coexist;
  separate row tap was removed. Evidence:
  `evidence/sessions/20260713-personal-might-praise/live-rankings-corrected-015/`.
- Live Check result: exact `(590,245)-(775,315)` target, tap `(682,280)`, one transport call,
  confirmed Personal Might Rank leaderboard. Header, icon-only rank-one Praise, and Back are bound
  from raw evidence. Praise and Claim inputs remained zero. Evidence:
  `evidence/sessions/20260713-personal-might-praise/live-personal-might-leaderboard-016/`.
- Status: Passed (2026-07-13).

### GNB-PHASE-D — Complete supervised Praise-to-exact-Claim slice

- Dependencies: GNB-PHASE-C Passed and required Bliss route/Claim evidence.
- Boundary: Praise and Claim are each current-frame-bound, one-dispatch consequential actions.
  Objective execution never implies Claim readiness.
- Status: Passed (2026-07-13).
- Resume correction: first Praise run sent zero inputs because startup omitted the valid already-open
  Personal Might leaderboard state. Startup now recognizes only explicit route states and never
  defaults unknown to Home. Evidence: `live-praise-resume-017-no-input/`.
- Praise confirmed with exactly one transport call and positive postcondition. Fresh Daily evidence
  now proves the exact Personal Might row is complete `(1/1)` and its local control is `Claim`.
  Normal Praise execution stops before reconciliation; `personal-might-claim` is the only explicit
  Claim entrypoint. Evidence: `live-praise-success-018/`, `live-daily-claim-evidence-019/`.
- Exact Claim confirmed separately: tap `(642,466)` inside row-local `(590,438)-(695,495)`, one
  transport call, zero cost, and positive row-disappearance postcondition. Evidence:
  `live-claim-success-020/{claim-pre-dispatch,claim-result,personal-might-claim-task-result}.json`.

### GNB-PHASE-E/F — Free Daily Activities, then persistence/scheduler

- Dependencies: GNB-PHASE-D Passed.
- Scope: Daily claims, milestones, free Depot, free recruitment; then separate task
  persistence and a narrow one-pulse due scheduler. Quiz, resource packs, strategic actions, and
  march families remain excluded from first Daily Activities MVP.
- Status: Evidence-gated.
- Fresh post-Phase-D Daily inventory has 5 points, no visible ordinary Claim row, and no ready
  milestone. Milestone, Depot Free, and recruitment Free controls still lack
  Bliss-native exact target plus positive postcondition pairs. Evidence:
  `evidence/sessions/20260713-phase-e-inventory/live-current-001/phase-e-inventory-001.png`.
- Vendor `GNB-DAILY-*` geometry remains static reference only. No 2x projection, vendor selector,
  blind triple tap, 10x recruitment branch, or broad Claim ROI may authorize input.

### GNB-PHASE-E-DAILY-CLAIMS-OFFLINE — Generalize available Daily Claim contract

- Dependencies: GNB-PHASE-D Passed; fresh generalized Daily Claim evidence is not yet available.
- Scope: ordinary Daily Quest Claim semantics independent of the Personal Might catalog alias,
  exact row-local target containment, explicit free/cost-negative requirements, profile/provenance/
  hash gates, positive row/points postcondition, and synthetic Go/static-reference negatives.
  No image capture, ADB, pnsctl registration, or live input.
- Status: Passed (2026-07-14; offline contract and 5 focused tests).
- Evidence: `tasks/available_daily_claim.py`,
  `tests/fixtures/phase_e_daily_claim_observations.json`, and
  `tests/test_available_daily_claim.py`.
- Result: a non-Personal-Might `Gather Food` semantic case exercises the generalized transaction
  spec; Go, static-reference, wrong-target, non-free, milestone, clipped, overlay, reset, and
  unchanged-postcondition cases fail closed.
- Blocker: no fresh Bliss-native generalized Daily Claim target and positive-postcondition pair
  exists.
- Next: acquire navigation-only evidence when permitted, then promote a real generalized Daily
  Claim target before any handler or dispatch is enabled.

### GNB-PHASE-E-MILESTONES-OFFLINE — Add activity milestone-chest contract

- Dependencies: GNB-PHASE-D Passed; Main and generalized Daily Claim contracts passed; ready
  milestone evidence is not yet available.
- Scope: exact ready activity milestone chest, explicit free/cost-negative semantics, panel-local
  target containment, profile/provenance/hash gates, positive chest-open/points postcondition, and
  synthetic locked/static-reference negatives. No image capture, ADB, pnsctl registration, or live
  input.
- Status: Passed (2026-07-14; offline contract and 5 focused tests).
- Evidence: `tasks/activity_milestones.py`,
  `tests/fixtures/phase_e_activity_milestone_observations.json`, and
  `tests/test_activity_milestones.py`.
- Result: ready synthetic chest exercises the free transaction spec; not-ready, static-reference,
  wrong-target/panel, non-free, overlay, reset, and unchanged-postcondition cases fail closed.
- Blocker: no fresh Bliss-native ready milestone chest and positive-open/points pair exists.
- Next: acquire navigation-only evidence when permitted, then promote a real milestone chest before
  any handler or dispatch is enabled.

### GNB-PHASE-E-DEPOT-OFFLINE — Add free Supply Depot collection contract

- Dependencies: GNB-PHASE-D Passed; generalized Daily Claim and milestone contracts passed; fresh
  free Depot evidence is not yet available.
- Scope: exact free collection target, known non-premium reward, explicit zero-cost semantics,
  panel-local target containment, profile/provenance/hash gates, positive collection postcondition,
  and synthetic premium/static-reference negatives. No image capture, ADB, pnsctl registration, or
  live input.
- Status: Passed (2026-07-14; offline contract and 5 focused tests).
- Evidence: `tasks/supply_depot.py`, `tests/fixtures/phase_e_supply_depot_observations.json`,
  and `tests/test_supply_depot.py`.
- Result: the synthetic known-basic-supplies case exercises the transaction spec; premium reward,
  static-reference, wrong-target/panel, unknown reward, non-free, not-ready, overlay, reset, and
  unchanged-postcondition cases fail closed.
- Blocker: no fresh Bliss-native free Depot target with known non-premium reward and positive
  collection evidence exists.
- Next: acquire navigation-only evidence when permitted, then promote a real free Depot target
  before any handler or dispatch is enabled.

### GNB-PHASE-E-RECRUITMENT-OFFLINE — Add free recruitment contract

- Dependencies: GNB-PHASE-D Passed; generalized Daily Claim, milestone, and free Depot contracts
  passed; fresh free recruitment evidence is not yet available.
- Scope: explicit single free mode, free banner, exact target, no 10x/premium/unknown confirmation,
  panel-local target containment, profile/provenance/hash gates, and positive result/count
  postcondition. No image capture, ADB, pnsctl registration, or live input.
- Status: Passed (2026-07-14; offline contract and 5 focused tests).
- Evidence: `tasks/free_recruitment.py`,
  `tests/fixtures/phase_e_free_recruitment_observations.json`, and
  `tests/test_free_recruitment.py`.
- Result: the synthetic free single case exercises the transaction spec; 10x, static-reference,
  wrong-target/panel, no-free-banner, non-free, unknown-confirmation, and unchanged-result cases
  fail closed.
- Blocker: no fresh Bliss-native free recruitment target and positive result/count evidence exists.
- Next: Phase E live promotion remains evidence-gated; continue with offline Phase F persistence or
  acquire navigation-only evidence when permitted.

### GNB-PHASE-F-OFFLINE — Define serializable task state and one-pulse scheduler

- Dependencies: Phase E offline contracts passed; existing SQLite action journal, lease, and
  unresolved-action semantics remain authoritative.
- Scope: deterministic task-state snapshot serialization, game-day binding, verified completion-key
  handling, bounded backoff, one-candidate selection, lease/unresolved gates, and explicit positive
  reconciliation. No action-journal replacement, ADB, pnsctl registration, or live input.
- Status: Passed (2026-07-14; offline contract and 8 focused tests).
- Evidence: `tasks/scheduler.py` and `tests/test_scheduler.py`.
- Result: state round-trips deterministically; only one due task is selected; wrong day, expired
  lease, unresolved action, failed-safe, mismatched completion, and unverified completion fail closed.
- Blocker: production persistence integration and all Phase E live promotions still require their
  separate evidence/promotion gates.
- Next: review SQLite-backed task-state integration offline, or acquire permitted navigation-only
  Bliss evidence; do not dispatch consequential input from synthetic state.

### GNB-PHASE-F-SQLITE — Persist task state alongside the safety journal

- Dependencies: GNB-PHASE-F-OFFLINE; existing SQLite action journal and lifecycle must remain
  unchanged.
- Scope: forward schema migration v1→v2, task-state table, typed repository adapter, monotonic
  revision/completion-key guards, deterministic audit event, and migration tests. No action-row
  replacement, ADB, pnsctl registration, or live input.
- Status: Passed (2026-07-14; focused persistence/migration tests and full non-OpenCV validation).
- Evidence: `safe_action_core/store.py`, `safe_action_core/task_state.py`, and
  `tests/test_task_state_store.py`.
- Result: v1 databases migrate forward without losing action/journal tables; task snapshots round
  trip through SQLite, preserve revision monotonicity, and reject completion-key changes. The core
  action journal remains authoritative for consequential lifecycle and unresolved blocking.
- Blocker: Phase E live promotions and a future scheduler/worker integration review remain separate;
  no live dispatch is authorized by this persistence task.
- Next: offline integration review of scheduler state with task handlers, or permitted
  navigation-only Bliss evidence.

### GNB-PHASE-F-INTEGRATION — Couple one-pulse scheduler to persisted task state

- Dependencies: GNB-PHASE-F-OFFLINE and GNB-PHASE-F-SQLITE Passed.
- Scope: thin repository-backed scheduler adapter, persisted backoff/completion/unresolved state,
  restart reload, and positive reconciliation tests. No transport, action-journal lifecycle change,
  pnsctl registration, or live input.
- Status: Passed (2026-07-14; focused integration and full non-OpenCV validation).
- Evidence: `tasks/scheduler.py` and `tests/test_scheduler_sqlite.py`.
- Result: scheduler mutations persist through the existing task-state repository; reload preserves
  due times and unresolved blocks; only explicit positive reconciliation reaches `DONE`.
- Blocker: production worker wiring and all Phase E live promotions remain gated. No consequential
  input is authorized by this adapter.
- Next: offline handler/scheduler policy review, or permitted navigation-only Bliss evidence.

Validation duration progression: 4 hours is the Bliss runtime-selection gate; offline replay,
observe-only, dry-run, supervised navigation, one validated supervised action, and one bounded
supervised task precede the 24-hour gate. The 24-hour locked-runtime validation is not required
before the first supervised development action, but is required before repeated or unattended
automatic claim-only execution. The 72-hour gate applies after claim-only continuous scheduling
is enabled; 7 days is expanded-task validation; 21 days is production hardening and operational
acceptance. No later duration is required for initial runtime selection after the 4-hour gate and
other runtime-selection gates pass.

## Runtime-proof tasks

Each task uses the fields required by the implementation directive. `Next` names the task(s)
unlocked when this task passes.

### RT-001 — Preserve working Bliss rollback baseline

- Dependencies: M2 passed; current Bliss disk remains intact.
- Objective: preserve the exact working domain configuration and identify its storage without modifying it.
- Scope: VM XML, domain metadata, block paths, network path, boot behavior, renderer/display/ADB/resource facts, artifact hashes.
- Non-goals: changing VM XML, GRUB, storage, account, or game state.
- Method: run the read-only baseline collector; copy `virsh dumpxml`; record checksums and observations; do not copy the VM disk.
- Acceptance: VM name and UUID recorded; inactive XML saved and hashed; all disk paths recorded; working boot choice documented; renderer, framebuffer, DPI/orientation, ADB path, game persistence, and host resource snapshot recorded; rollback restore command reviewed.
- Verification: inspect XML and command outputs; compare screenshot manifest; verify XML hash twice without intervening changes.
- Evidence: `evidence/manifest.csv`, `evidence/sessions/2026-07-10-initial/`, and next live collection directory.
- Rollback: no mutation; later experiments restore the saved inactive XML with `virsh define` only after explicit comparison.
- Status: Passed.
- Blocker: None. The authentication hard-stop was manually resolved; package relaunch reached the authenticated base screen before graphics work.
- Next: RT-002, RT-003.

### RT-002 — Document current VM XML and GRUB behavior

- Dependencies: RT-001.
- Objective: map video/graphics/firmware devices and the manual no-hardware GRUB selection precisely.
- Scope: inactive/live XML diff, boot screenshots, installed GRUB configuration read-only inspection.
- Non-goals: changing the default boot entry.
- Method: inspect saved XML and guest boot files through existing ADB/shell access where permissions allow.
- Acceptance: active and inactive video/display/render-node settings documented; GRUB menu labels and installed config location recorded; observed default and working entries identified.
- Verification: XML parsing plus one observed boot to menu without selecting a gameplay action.
- Evidence: task-specific session directory.
- Rollback: observation only.
- Status: Passed.
- Blocker: None. Offline read-only inspection recorded EFI `grub.cfg`, sourced `android.cfg`, `grubenv`, menu arguments, five-second timeout, and saved VirGL entry; NBD was disconnected after each inspection.
- Next: RT-003, RT-006.

### RT-003 — Test smallest VirtIO-GPU/VirGL configuration

- Dependencies: RT-001 and RT-002.
- Objective: determine whether one minimal, reversible VirtIO-GPU/VirGL domain configuration boots and renders correctly.
- Scope: one configuration per trial; XML backup; VM-only stop/start; boot, framebuffer, renderer, host GPU/CPU/RAM, screenshot, and game-render checks.
- Non-goals: iGPU passthrough, host reboot, broad networking, gameplay actions, or concurrent configuration changes.
- Method: derive a single XML delta from the captured baseline; define it only after validation; boot; collect timed evidence; restore baseline on reject condition.
- Acceptance: exact delta and timestamps recorded; Android reaches recognizable state unattended for that trial; renderer and GLES strings captured; host GPU use measured; screenshot dimensions/freshness and game rendering verified; no host/NAS error or service impact.
- Verification: inspect console/ADB frames and hashes, Android graphics properties/dumpsys, host metrics, libvirt/QEMU logs, and NAS health; then boot restored baseline once.
- Evidence: a new immutable `evidence/sessions/<timestamp>-rt-003-*` directory.
- Rollback: destroy only the dedicated PoC domain if hung, redefine saved baseline XML, and start it; never delete its disk.
- Status: Passed.
- Blocker: None. QXL rollback boot returned to SwiftShader at 1024×768; the validated VirtIO(3D) candidate was then restored and reverified on Mesa VirGL.
- Next: RT-004 or another bounded RT-003 trial if new evidence justifies it.

### RT-004 — Verify accelerated renderer and host GPU use

- Dependencies: a booting RT-003 configuration.
- Objective: prove rendering is hardware accelerated and usable by the game.
- Scope: renderer/GLES strings, render-node use, host GPU utilization, CPU/RAM, visual correctness.
- Non-goals: performance tuning beyond the candidate profile.
- Method: collect repeatable idle and game-render samples without gameplay input.
- Acceptance: renderer is not SwiftShader; nonzero correlated UHD 770 activity; correct game frames; resource use within PoC limits; no GPU resets.
- Verification: three aligned guest/host samples plus log inspection.
- Evidence: RT-004 session record.
- Rollback: restore RT-001 configuration.
- Status: Passed.
- Blocker: None. Boot, game, and post-rollback aligned samples proved Mesa VirGL, UHD 770 Render/3D activity, correct game frames, lower QEMU CPU than the SwiftShader sample, safe temperatures, and no sampled GPU reset.
- Next: RT-005, RT-006.

### RT-005 — Decide graphics gate

- Dependencies: RT-003 trials and RT-004 where applicable.
- Objective: accept an accelerated graphics profile or apply the documented Bliss rejection criterion.
- Scope: evidence comparison only.
- Non-goals: selecting a framework or fallback without a recorded gate result.
- Method: compare every graphics acceptance/rejection criterion against retained evidence; stop after three materially different failed approaches without meaningful new evidence.
- Acceptance: explicit pass/fail decision with criterion-by-criterion evidence and selected rollback/next candidate.
- Verification: independent review of session records and configuration hashes.
- Evidence: decision record in final graphics session.
- Rollback: retain SwiftShader profile regardless of decision.
- Status: Passed for the graphics gate.
- Blocker: None. The selected profile for remaining Bliss gates is the validated VirtIO(3D)/Mesa VirGL candidate; VNC inactivity after driver load is retained as a remote-view requirement, not hidden.
- Next: RT-006 on pass; ReDroid proof task on justified Bliss rejection.

### RT-006 — Implement unattended boot entry

- Dependencies: RT-002 and selected graphics profile.
- Objective: boot the selected installed Bliss profile without manual GRUB input.
- Scope: guest bootloader default/timeout only, with backup.
- Non-goals: VM autostart or host boot changes.
- Method: back up boot configuration, make the smallest default-entry change, reboot VM, observe without console input.
- Acceptance: three unattended boots reach a recognizable Android/game-safe state; boot config and rollback verified.
- Verification: timestamped console/ADB evidence for all trials.
- Evidence: RT-006 session record.
- Rollback: restore backed-up boot config from recovery/manual menu.
- Status: Passed.
- Blocker: None. Three unattended cold boots used the saved VirGL entry; EFI config, `android.cfg`, and `grubenv` were backed up and hashed; the QXL/no-hardware rollback path was also boot-verified.
- Next: RT-007, RT-011.

### RT-007 — Lock portrait display profile

- Dependencies: RT-006.
- Objective: select and persist final portrait resolution, DPI, orientation, renderer, and viewport/system-bar behavior.
- Scope: display configuration and observation only.
- Non-goals: final CV templates or coordinates.
- Method: test candidate portrait profile, persist it, and compare frames across restarts.
- Acceptance: fixed dimensions/DPI/orientation and recognizable game viewport across three restarts
  with no drift. Startup must verify `sys.boot_completed=1`, inspect input restriction/keyguard,
  verify the approved non-secure keyguard, send only `KEYCODE_WAKEUP`, keyevent `82`, and
  `cmd window dismiss-keyguard`, verify restriction cleared, and stop on a secure credential
  prompt, login state, or unknown OS state.
- Verification: `wm size`, `wm density`, rotation settings, PNG metadata/hashes, and visual inspection.
- Evidence: RT-007 session record and runtime profile draft.
- Rollback: restore recorded 1024×768, 160 dpi baseline settings.
- Status: Passed for effective portrait profile.
- Blocker: None for effective pixels. Global rotation lock is intentionally not part of the profile because the game returns it to `free`; Candidate B's global ignore-orientation mode corrupted rendering. Android post-boot keyguard dismissal is a required non-game startup step.
- Next: RT-008, RT-009, RT-010.

### RT-008 — Secure or strictly isolate ADB

- Dependencies: selected runtime network profile.
- Objective: prove authenticated ADB or a private boundary with no LAN/Internet exposure.
- Scope: existing PoC network and ADB endpoint; firewall/routing observation; narrowly scoped containment if already authorized.
- Non-goals: public exposure, host firewall weakening, or broad network redesign.
- Method: inventory listeners/routes/rules and probe from allowed and disallowed locations; prefer authentication where supported.
- Acceptance: documented trust boundary; endpoint unreachable from LAN/Internet; controller reconnect works after restart; no uncontrolled ADB listener.
- Verification: listener/rule inspection and positive/negative connectivity tests.
- Evidence: RT-008 session record with sensitive identifiers redacted.
- Rollback: restore saved VM network XML/rules only; never broaden exposure.
- Status: Passed via strict isolation.
- Blocker: None. `ro.adb.secure=0` is an explicit limitation; containment is provided by
  libvirt private NAT, rejected LAN ingress, and absent host `:5555` listener. The pinned SSH
  tunnel is development-only evidence access; production uses the local/private Unraid path.
- Next: RT-009.

### RT-009 — Build and run input-fidelity test

- Dependencies: RT-007.
- Objective: measure tap/swipe coordinate mapping without gameplay consequences.
- Scope: Android settings/test surface or other non-game destructive-free target.
- Non-goals: game progression, resource use, tutorial, or credential input.
- Method: deterministic grid targets and bounded swipes; capture before/after frames; calculate error and repeatability.
- Acceptance: all tested taps map within defined target tolerance; swipes have correct direction/distance class; no rotation/scaling mismatch across restarts.
- Verification: repeated trials with captured coordinates and screenshots.
- Evidence: RT-009 session record and machine-readable results.
- Rollback: exit test surface; no durable game change.
- Status: Passed.
- Blocker: None. Android Home pointer overlay measured 9 taps and 4 swipes before and after guest restart; all frames were `800x1280`, zero markers missed, and maximum measured endpoint error was 4.031 px within the 8-pixel tolerance.
- Next: RT-011.

### RT-010 — Build and run capture-fidelity test

- Dependencies: RT-007.
- Objective: verify fresh, lossless, correctly dimensioned screenshots and latency.
- Scope: ADB PNG capture and metadata only.
- Non-goals: choosing the final CV framework.
- Method: capture timed changing/static sequences, validate PNGs, dimensions, timestamps, and hashes.
- Acceptance: initial final-profile acceptance thresholds are 100% valid PNGs, 100% expected
  dimensions, 0 corrupt or black frames, p95 screenshot latency no greater than 2 seconds unless
  later evidence justifies another threshold, coordinate accuracy within the documented RT-009
  tolerance, and no consequential action using a stale or profile-mismatched frame. Any
  runtime-profile mismatch causes a global input lock. Repeated identical hashes are suspicious
  only; staleness requires agreeing freshness indicators or a controlled expected visual change
  that is not observed.
- Verification: automated manifest validation and visual sample inspection.
- Evidence: RT-010 session record and machine-readable results.
- Rollback: none; observation only.
- Status: Passed.
- Blocker: None. Eight valid `800x1280` PNGs, eight unique hashes, zero adjacent duplicates, and approximately 1.0 s capture latency were recorded on the locked effective profile.
- Next: RT-011.

### RT-011 — Execute restart matrix

- Dependencies: RT-006 through RT-010.
- Objective: prove repeatable app, Android, and VM recovery while preserving account/display/renderer/ADB state.
- Scope: approved dedicated PoC app/guest/domain restarts; no host reboot.
- Non-goals: gameplay action recovery testing.
- Method: record every trial independently, including controller reconnect and hard-stop authentication-state checks.
- Acceptance: plan-defined repeated trials all pass; any login/tutorial/wrong-account/CAPTCHA state stops input and is externally blocked.
- Verification: pre/post properties, frames, package state, account guard evidence, and logs per trial.
- Evidence: `evidence/sessions/20260711-rt-011-restart-matrix/record.md` and artifacts.
- Rollback: restore RT-001 XML/boot profile; never automate authentication.
- Status: Passed.
- Blocker: None for tested app, guest, clean VM power-cycle, and controlled cold stop/start paths.
  The initial `virsh shutdown` hang is retained as failure evidence; the approved `adb reboot -p`
  and controlled dedicated-domain stop paths passed.
- Next: RT-012.

### RT-012 — Run 4-hour Unraid-local observe-only runtime-selection soak

- Dependencies: RT-011.
- Objective: complete the bounded 4-hour Bliss runtime-selection observation window and measure
  NAS impact with an observer that runs locally on Unraid.
- Scope: screenshots/health/metrics only; VM and observer observation, independent of future
  controller integration.
- Non-goals: any gameplay tap or production promotion.
- Method: select one NAS-local execution model during implementation: (1) temporary unprivileged
  Docker observer, (2) Python observer running locally on Unraid, or (3) PowerShell Core inside a
  temporary container. Do not select or implement that model in this documentation edit. Run the
  observer locally on Unraid for a 4-hour target (2 hours is diagnostic only) with 300-second
  samples, 512 MiB evidence quota, fresh lossless PNGs, ADB/game health, and read-only
  host/QEMU/NAS metrics. Send no input commands. The observer must continue if the development
  machine disconnects. SSH may be used only to launch, inspect, stop, or retrieve evidence, and
  is not a production dependency.
- Freshness policy: identical full-screen hashes are suspicious evidence only, never proof of
  capture staleness. Evaluate screenshot decode integrity, expected dimensions, file and capture
  timestamps, ADB transport success, capture latency, foreground/process state, SurfaceFlinger
  or window state where useful, known dynamic-region evidence when available, and controlled
  non-game freshness probes where appropriate. Declare staleness only when multiple indicators
  agree or a controlled expected visual change is not observed.
- Acceptance: 4-hour duration completed; observer sent zero input commands; observer remained
  read-only; 100% expected-dimension valid PNGs; zero corrupt or black frames; p95 screenshot
  latency no greater than 2 seconds unless later evidence justifies another threshold; multi-signal
  freshness review passed; runtime and NAS metrics were complete; no account/session hard-stop
  appeared; and no host or runtime rejection condition occurred.
- Verification: time-series completeness, multi-signal freshness review, sampled frames, service
  health, and host/QEMU logs.
- Evidence: `scripts/test-observe-soak.ps1`,
  `evidence/sessions/20260711-rt-012-soak-auth-block/record.md`, and future soak session directory.
- Rollback: stop observer; return VM to safe known state.
- Status: Passed.
- Blocker: None. A temporary unprivileged Docker observer ran locally on Unraid for four hours
  with 48 five-minute samples; the complete cache-backed output and criterion review are retained
  in `evidence/sessions/20260711-rt-012-observe-soak/`. Historical pre-existing NBD warnings in
  host logs are preserved as anomalies and were not generated during this run. Live GPU payload
  was not populated by `intel_gpu_top`; prior RT-004 GPU proof remains authoritative.
- Next: RT-013. RT-014A remains separate optional viewer transport proof. RT-016A remains the
  independent prerequisite for M7-AccountGuard and does not block technical runtime selection.
  viewer transport proof. Later validation is staged as 24-hour locked-runtime, 72-hour
  claim-only, 7-day expanded-task, and 21-day production-hardening runs.

### RT-013 — Final Bliss pass/fail and runtime-profile decision

- Dependencies: RT-012. Earlier graphics, display, ADB, capture, and restart tasks
  remain required evidence inputs.
- Objective: select/lock Bliss or reject it using plan criteria.
- Scope: evidence-based decision and runtime-profile finalization.
- Non-goals: framework selection itself.
- Method: criterion matrix with mandatory evidence links and known limitations.
- Acceptance: every hard gate is pass or explicit reject; selected profile is reproducible and rollback retained; fallback trigger is documented.
- Verification: replay setup from records where safe and review evidence completeness.
- Evidence: `evidence/sessions/20260711-rt-013-runtime-decision/record.md` and selected-profile
  facts; the complete versioned manifest/schema remains RT-019.
- Rollback: preserved RT-001 baseline; fallback begins only after recorded rejection.
- Status: Passed.
- Blocker: None. The criterion-by-criterion decision is recorded in
  `evidence/sessions/20260711-rt-013-runtime-decision/record.md`; the preflight is retained in
  the same directory. Bliss is selected with preserved rollback and explicit limitations.
  RT-016A account/server identity evidence remains a later account-guard prerequisite and does
  not block technical runtime selection. RT-014A viewer transport is optional, and RT-015 is
  deferred deployment documentation.
- Next: RT-017, RT-019, and RT-021 in parallel; M5 framework bake-off requires RT-019 and
  RT-021, while M6 production corpus requires RT-019. ReDroid isolated-in-Linux-VM proof
  remains the rejection path.

### RT-014A — Prove optional private post-VirGL viewer transport

- Dependencies: RT-008 and RT-011.
- Objective: prove that the running Android/game display can be viewed privately after VirtIO-GL
  disables VNC, without requiring the future controller service.
- Scope: private scrcpy or equivalent ADB-backed viewing, correct `800×1280` portrait display,
  reconnect behavior, no LAN/Internet exposure, read-only observation where supported, and
  technical proof that viewer input can be enabled explicitly.
- Non-goals: production executor pause, production exclusive lease, unresolved-action
  reconciliation, task-state reconciliation, gameplay automation, credential input, or tutorial
  input.
- Method: connect through the private development path or transient administrative tunnel as
  needed; start viewer against the private ADB path; verify read-only observation; explicitly
  enable viewer input only for technical transport proof; capture reconnect and listener evidence.
  Do not require a controller, permanent external viewer, or unattended production viewer.
- Acceptance: post-driver Android/game view is usable; portrait dimensions remain correct;
  observation mode sends no input; viewer reconnects; no public listener is created; explicit
  viewer-input enablement is technically demonstrated; viewer remains optional and unattended
  production continues without it.
- Verification: retained viewer screenshots/logs, private listener inspection, reconnect test,
  and explicit input-enable evidence only. No controller lease or task reconciliation is required
  for RT-014A.
- Evidence: existing `evidence/sessions/<timestamp>-rt-014-remote-view/` reference and future
  RT-014A transport evidence.
- Rollback: stop viewer and close transient development tunnel; leave game force-stopped.
- Status: Blocked (development authentication).
- Blocker: existing development SSH authentication probe failed with exit 255; use process-only
  `UNRAID_TEMP_PASSWORD` for this development execution. Do not store credentials. This is not a
  production architecture dependency.
- Next: M7-Takeover and the first supervised live validation that depends on remote observation.

### RT-015 — Document VM autostart and worker ordering

- Dependencies: RT-006 and RT-011.
- Objective: document VM autostart and safe worker-after-VM health ordering for later deployment.
- Scope: read-only current VM autostart/config inspection and an ordered startup runbook.
- Non-goals: Unraid host reboot, changes to existing VM/container ordering, broad host startup
  changes, or gameplay input.
- Method: inspect current domain autostart settings; document required dependency delay and health
  gates for the future worker; leave host reboot validation to separately authorized deployment
  operations.
- Acceptance: selected VM profile, ADB, display, account, storage, and safe-screen startup gates
  are documented in order; no NAS reboot is required or performed; existing Home Assistant/Docker
  workloads remain protected.
- Verification: read-only libvirt/config inspection and review of the ordered startup runbook.
- Evidence: `evidence/sessions/<timestamp>-rt-015-autostart-order/`.
- Rollback: restore saved autostart/order configuration; do not alter existing workloads.
- Status: Pending.
- Blocker: worker implementation does not yet exist. Host reboot validation is explicitly
  deferred to deployment operations and is not a runtime-proof prerequisite.
- Next: Milestone 10 — Production hardening and operational acceptance; does not block RT-013.

### RT-016A — Capture and verify expected account/server identity evidence

- Dependencies: RT-011.
- Objective: capture the strongest stable identity evidence from the already-provisioned account.
- Scope: numeric player/account ID where available, server/state identifier, commander name as
  secondary evidence, alliance as optional supporting evidence, redacted or access-restricted
  evidence, persistence across already-tested restart paths, and expected/unknown/mismatched
  identity definitions.
- Non-goals: login, credential entry, account switching/creation/binding, tutorial automation,
  CAPTCHA handling, account-operation input, or controller enforcement.
- Method: capture the strongest available identity evidence from the existing authenticated
  surface; compare it with retained restart evidence; retain only minimum redacted or hashed
  evidence; document account/session hard-stop states and evidence needed for later enforcement.
- Acceptance: expected account and server identity are recorded; evidence is redacted or
  restricted appropriately; identity remains consistent across restart evidence; expected,
  unknown, and mismatched identity definitions are documented; account/session hard-stop states
  are documented; no credentials, login, account switching, or tutorial behavior is automated.
- Verification: independent review of redacted identity evidence and consistency across RT-011
  restart paths.
- Evidence: existing `evidence/sessions/<timestamp>-rt-016-account-guard/` reference and future
  RT-016A identity-evidence record.
- Rollback: observation only; keep game force-stopped and do not change account state.
- Status: Pending.
- Blocker: retained evidence proves authenticated game surface but does not yet contain stable
  redacted player/server identity evidence.
- Next: M7-AccountGuard. RT-016A is not a prerequisite for RT-013.

### RT-017 — Create secured post-provisioning runtime recovery backup

- Dependencies: RT-013.
- Objective: preserve a restricted, restorable post-provisioning runtime snapshot after the final
  profile is selected.
- Scope: qcow2 disk, VM XML, required EFI and GRUB state, artifact hashes, runtime-profile version,
  restricted access, restoration procedure, and restore-test evidence.
- Non-goals: copying credentials, changing the live runtime, or restoring over a competing account
  session.
- Method: define the backup contents and hashes, document restricted storage, and test restoration
  only under a controlled procedure with no competing live account session.
- Acceptance: backup artifacts and hashes are complete; runtime-profile version is bound to the
  backup; access is restricted; restoration procedure recreates the selected profile; restore
  testing records that no competing live account session was present.
- Verification: independent manifest/hash review and restoration evidence.
- Evidence: `evidence/sessions/20260711-rt-017-runtime-backup/`.
- Rollback: retain original live runtime and do not overwrite it during backup or restore testing.
- Status: Passed.
- Blocker: None. The restricted backup, artifact hashes, EFI/GRUB state, profile binding, and
  offline restore-test review are recorded in `evidence/sessions/20260711-rt-017-runtime-backup/`.
- Next: MVP-STARTUP-NORMALIZATION. RT-017 remains required for unattended automatic gameplay
  input with applicable M7 and task-specific promotion gates; the broad M5 framework bake-off is
  deferred while the first vertical slice is validated with the presumptive Python/direct ADB/
  OpenCV stack.

### RT-018 — Define narrow local VM lifecycle-control boundary

- Dependencies: RT-013.
- Objective: define safe local lifecycle control for the selected Puzzles & Survival VM without
  granting broad host authority.
- Scope: selected VM only; status, start, graceful shutdown, approved restart, unresolved-action
  guard, request logging, and a local socket or narrowly restricted local endpoint.
- Non-goals: arbitrary shell, unrestricted Docker socket, unrestricted libvirt control, Unraid
  reboot authority, broad VM control, or gameplay input.
- Method: specify and review the narrow command schema, authorization boundary, local transport,
  lease/unresolved-action checks, and audit fields.
- Acceptance: only the selected VM can be addressed; allowed lifecycle operations are explicit;
  unresolved consequential actions block shutdown/restart; every request is logged; no arbitrary
  shell, unrestricted Docker/libvirt access, or Unraid reboot path exists.
- Verification: policy tests for allowed/denied requests and unresolved-action guard.
- Evidence: `evidence/sessions/<timestamp>-rt-018-vm-lifecycle-boundary/`.
- Rollback: disable the local endpoint and retain manual VM lifecycle control.
- Status: Pending.
- Blocker: none for initial claim MVP while VM restart remains manual. Required before unattended
  VM recovery.
- Next: unattended VM lifecycle recovery.

### RT-019 — Lock and version final runtime-profile manifest

- Dependencies: RT-013. RT-017 is parallel and is not a prerequisite.
- Objective: make the selected runtime reproducible and define the compatibility contract for
  future recognition assets.
- Scope: manifest version, Bliss and Android versions, VM name and UUID, VM XML hash, qcow2
  identity, GRUB state, renderer and OpenGL ES version, physical/logical dimensions, DPI,
  orientation behavior, viewport/system-bar behavior, game package/version, ADB transport and
  isolation, startup/keyguard sequence, account-guard version, evidence references, and profile
  creation date.
- Non-goals: changing the selected runtime or automating account provisioning/tutorial/login.
- Method: record each manifest field; assign a runtime-profile hash or immutable identifier; define
  an asset compatibility field/schema; document future asset requirements; and define a validator
  that rejects missing or mismatched profile/asset versions before input.
- Acceptance: complete versioned runtime-profile manifest; runtime-profile hash or immutable
  identifier; asset compatibility field/schema; validator capable of rejecting mismatched profile
  or asset versions; documentation requiring future assets to reference a runtime profile; and
  global input lock on profile mismatch. M6 separately validates every asset created in the
  production corpus.
- Verification: independent manifest, XML/qcow2/GRUB/hash review and validator/schema review.
- Evidence: `evidence/sessions/20260711-rt-019-runtime-profile-manifest/`.
- Rollback: retain prior profile manifest and disable assets that lack compatibility evidence.
- Status: Passed.
- Blocker: None. RT-019 manifest, schema, validator, profile hash, and criterion evidence are
  recorded in `evidence/sessions/20260711-rt-019-runtime-profile-manifest/`.
- Next: RT-021; M5 framework bake-off requires RT-019 and RT-021, while M6 production corpus
  requires the RT-019 profile schema and later adapter selection.

### RT-021 — Prove unprivileged Unraid worker-to-VM ADB path

- Dependencies: RT-013 and selected local/private VM networking.
- Objective: prove the production communication path from an unprivileged Unraid container to the
  Bliss VM without an external SSH tunnel.
- Scope: temporary unprivileged test container on Unraid, direct local/private access to the Bliss
  ADB endpoint, screenshot capture, package status/lifecycle observation, reconnect after guest
  restart, negative LAN exposure test, and reproducible network configuration.
- Non-goals: external SSH tunnel, public ADB, host network mode unless explicitly justified,
  unrestricted Docker socket, unrestricted libvirt access, or gameplay input.
- Method: use a temporary least-privilege container on Unraid against the selected local/private
  VM network; validate ADB capture and package observation; restart the guest through the existing
  approved path; verify reconnect and LAN denial; record reproducible network/container
  configuration without changing production runtime.
- Acceptance: test container reaches ADB with no external tunnel active; screenshot capture
  succeeds; reconnect succeeds after guest restart; endpoint remains inaccessible from normal LAN
  clients; container has no unnecessary host privileges; configuration is reproducible and
  documented; production design no longer depends on the development tunnel.
- Verification: container privilege review, positive ADB/capture/reconnect evidence, negative LAN
  test, and configuration replay review.
- Evidence: `evidence/sessions/20260711-rt-021-worker-vm-adb/`.
- Rollback: remove temporary test container/network attachment; retain existing private VM network
  and runtime state.
- Status: Passed.
- Blocker: None. RT-021 passed with an explicit host-network limitation after the retained Docker
  bridge refusal; criterion review and all positive/negative/failure evidence are recorded in
  `evidence/sessions/20260711-rt-021-worker-vm-adb/record.md`.
- Next: M5 framework bake-off; RT-019 and RT-021 now pass, so bake-off work may begin in its own
  task boundary.

### MVP-STARTUP-NORMALIZATION — Validate Cash Mall-to-Home/Base startup slice

- Dependencies: RT-017, RT-019, and RT-021.
- Objective: safely normalize the already-provisioned game from its normal Cash Mall startup
  state to a positively recognized Home/Base screen.
- Scope: Python, direct ADB, OpenCV, local OCR only for a demonstrated ROI; offline recognition,
  live observe-only classification, dry-run annotation, and one supervised no-spend back-arrow
  trial with retained before/target/input/after evidence.
- Non-goals: login, credentials, tutorial, account/server selection, profile navigation, purchases,
  Daily Quest claims, broad framework bake-off, or production unattended gameplay.
- Method: launch/observe the package, capture fresh `800x1280`, recognize Cash Mall using exact
  title/layout/header/back-control/mall context, confirm no unknown overlay, recapture immediately,
  authorize exactly one recognized top-left back-arrow tap, and require positive Home/Base after.
  Coordinate-only, stale, purchase/offer/premium, confirmation, timeout, and unexpected-successor
  actions are denied/UNKNOWN. Never retry blindly.
- Acceptance: offline/reference recognition passes; live observe-only classification passes; dry-run
  ROI annotation passes; one supervised Cash Mall-to-Home/Base transition passes with no spend and
  retained evidence; failure/timeout/overlay stops safely.
- Verification: ordered offline → observe-only → dry-run → one supervised input → positive
  postcondition review. Do not continue to Daily Quest in the same live trial.
- Evidence: `evidence/sessions/<timestamp>-mvp-startup-normalization/`.
- Rollback: force-stop the game after the trial; no state/spend rollback is required for the
  bounded back navigation. Preserve all failure evidence.
- Status: Passed (2026-07-11; resumed guarded startup trial complete).
- Blocker: None. The fresh runtime was already non-blocking at resumed observation, so no additional
  keyguard swipe or HOME input was sent; the fail-closed one-swipe branch is implemented and
  fixture-validated. No credential or profile navigation was automated.
- Next: M5 framework bake-off. Daily Quest and later gameplay workflows were not started in this
  task.

## Dependency graph

- RT-012 → RT-013.
- RT-013 → RT-017 secured backup, RT-019 runtime-profile manifest, and RT-021 worker-to-VM ADB
  proof in parallel.
- RT-019 + RT-021 → M5 framework bake-off.
- RT-017 + RT-019 + RT-021 → MVP-STARTUP-NORMALIZATION supervised trial.
- M5 + RT-019 + MVP-STARTUP-NORMALIZATION → M6-DQ-BOOTSTRAP.
- M6-DQ-BOOTSTRAP → M7-SAFE-ACTION-CORE.
- M6-DQ-BOOTSTRAP + M7-SAFE-ACTION-CORE + MVP-STARTUP-NORMALIZATION → MVP-QUEST-TO-CLAIM.
- MVP-QUEST-TO-CLAIM → M6-DQ-TRANSITION-CORPUS.
- M6-DQ-BOOTSTRAP + M6-DQ-TRANSITION-CORPUS → M6 Production Corpus Passed.
- M7-SAFE-ACTION-CORE is the minimum M7 subset for the supervised trial; the full M7
  deterministic service core remains required before repeated/bounded automatic claim operation,
  continuous scheduling, and production operation.
- MVP-QUEST-TO-CLAIM is evidence for later promotion and does not by itself pass M8 Claim-only
  MVP.
- RT-014A → M7-Takeover manual-takeover integration.
- RT-016A → M7-AccountGuard account-guard implementation → unattended automatic gameplay only
  after all applicable safety and promotion gates.
- Task-specific supervised-validation prerequisites → agent-driven supervised gameplay input.
- 24-hour locked-runtime validation → repeated/bounded automatic claim-only execution.
- 72-hour claim-only continuous scheduling applies only after continuous claim-only scheduling is
  enabled.
- RT-017 + applicable M7 safety gates + task-specific promotion gates → unattended automatic gameplay input.
- RT-018 → unattended VM lifecycle recovery.

## Current ready work

RT-007 through RT-013 passed. RT-009 measured 9 taps and 4 swipes before and after guest restart
on Android Home; all frames were `800x1280`, zero markers missed, and maximum endpoint error was
4.031 px. RT-008 proves strict private ADB isolation but records `ro.adb.secure=0`; production
must use the local/private Unraid worker-to-VM path and must not depend on an external SSH tunnel.
RT-010 measured eight valid `800x1280` PNGs, eight unique hashes, zero adjacent duplicates, and
p50/p95 capture latency of about 1.015/1.026 seconds. These measurements do not replace the
initial final-profile acceptance thresholds recorded in RT-010. RT-011 completed 3 app restarts,
3 corrected Android/guest recoveries, 2 clean VM power-cycles, and 1 controlled cold VM
stop/start; display, Mesa renderer, game surface, and ADB reconnect persisted. Do not place a
password or private key in this repository. RT-012 passed with a temporary unprivileged
Unraid-local Docker observer and a root read-only host-metrics collector; its complete four-hour
evidence and criterion review are retained in `evidence/sessions/20260711-rt-012-observe-soak/`.
The VM is running Mesa VirGL and no gameplay input automation or external tunnel is active. VNC
becomes inactive after VirtIO-GL loads, so ADB remains the observation path until optional private
scrcpy or equivalent passes. RT-014A remains separately blocked by development authentication;
RT-015 is deferred VM/worker-order documentation and does not block RT-013; RT-016A needs redacted
identity evidence for M7-AccountGuard, not technical runtime selection. RT-018 is pending;
RT-017, RT-019, and RT-021 have passed. MVP-STARTUP-NORMALIZATION Passed after the resumed
observe-only keyguard reconciliation, guarded Cash Mall launch, one authorized no-spend back-arrow
tap, and positive final-profile Home/Base postcondition. The M5 framework bake-off Passed on
2026-07-12 with the custom Python/direct ADB/OpenCV/local OCR stack selected; Daily Quest and
later gameplay workflows were not started.
M6-DQ-BOOTSTRAP Passed after the prior Daily-tab input was confirmed, a fresh final-runtime
reconciliation was positively classified, one bounded no-spend list scroll produced overlap
evidence, profile-compatible assets were promoted, fail-closed fixtures passed, and all task-scoped
workers were cleaned up. M7-SAFE-ACTION-CORE Passed with SQLite schema version 1, the persistent
lease/action journal, central policy, injected exactly-one-input executor, startup reconciliation,
and 44 passing offline tests. `MVP-QUEST-TO-CLAIM` is Blocked after one confirmed Cash Mall-to-Home
action and a pre-dispatch `STALE_FRAME` denial on Home-to-Quest; no Daily Quest, prerequisite, or
Claim input occurred. Resume only after offline review of the recognition/freshness timing
contract. Do not begin M6-DQ-TRANSITION-CORPUS before the supervised trial passes. Do not rerun RT-012 or the
completed MVP action; their complete evidence is retained in
`evidence/sessions/20260711-rt-012-observe-soak/` and
`evidence/sessions/20260711-mvp-startup-normalization/`. Do not place credentials in this
repository or command history. Launching `com.global.ztmslg` normally opens the authenticated Cash
Mall screen; startup normalization must positively recognize Cash Mall, recapture immediately,
send at most one authorized no-spend top-left back-arrow input, and positively recognize Home/Base
afterward. Cash Mall is not an authentication hard stop.

## Daily Quest execution backlog — matrix authority

Added 2026-07-14. `tasks/daily_quest_execution_matrix.json` owns current implementation, evidence,
promotion, registration, persistence, and scheduler status. Catalog status fields are legacy
observations only. Every task below is offline-first, preserves Claim separation, and has
`scheduler_eligibility: false`. No task authorizes ADB, worker wiring, live state, or gameplay input
during this planning boundary.

Each record uses this acceptance vocabulary: source/target identities must be current-frame-bound;
transaction means exactly one bounded dispatch; postcondition must be semantic and positive;
recovery stops on ambiguity and reconciles unresolved state; Daily reconciliation never implies
Claim; persistence remains dormant; registration must match checked-in operator state; Bliss evidence
must be native; GnBots geometry is provenance only; tests are deterministic offline tests.

### DQ-CATALOG-RECONCILIATION
- Covered: 31 objective keys from retained selected-Daily inventory evidence.
- Exclusions: Main Quest Claim, Main-only Vehicle Depot/Ultimate/Hunt/Own Hero rows, synthetic-only
  Gather Food/Gathered Food, documentation-only Headquarters wording, and unretained names.
- Dependencies/routes: retained inventories → normalized catalog; no runtime route.
- Source/target/policy: source is only accepted raw/lossless Bliss evidence or inventory records
  derived from it; target is canonical key/alias/variant; consequence and resource policy stay
  observational.
- Offline acceptance/tests: unique keys, aliases, selected-Daily provenance for every admitted key,
  rejected-candidate classifications, dynamic count, no literal count constant;
  `tasks/daily_quest_provenance_audit.json` and `tests/test_daily_quest_planning.py`.
- Bliss/live boundary: read-only files only; no capture, ADB, worker, lease, journal migration, or input.
- Transaction/postcondition/recovery: none; rejected candidates remain non-counted reconciliation
  records with missing-evidence requirements.
- Claim/persistence/registration/scheduler: Claim separate; no state rows; not registered; false.
- Promotion/unlocks: `OFFLINE_ONLY`; unlocks coverage matrix and family tasks.

### DQ-COVERAGE-MATRIX
- Covered: one matrix owner for every proven catalog key plus support flows.
- Variants: reusable family sharing declared; duplicate ownership prohibited unless explicit shared family.
- Exclusions: unproven candidates counted as Daily objectives, support flows counted as objectives,
  objective completion implying Claim, Main Claim.
- Dependencies/routes: catalog reconciliation → matrix; route names must match catalog and handler status.
- Source/target/policy: matrix records recognizers, consequence class, resource policy, transaction, semantic postcondition, and recovery.
- Offline acceptance/tests: key parity, required field completeness, closed promotion/registration enums, all scheduler flags false; planning tests.
- Bliss/live boundary: matrix construction only; no runtime registration or task-state creation.
- Transaction/postcondition/recovery: every consequential entry has all three fields; no dispatch permitted by matrix.
- Claim/persistence/registration/scheduler: separate Claim support; dormant persistence; actual registration snapshot; false.
- Promotion/unlocks: `OFFLINE_ONLY`; unlocks roadmap and prompts.

### DQ-FOUNDATION-DAILY-INVENTORY
- Covered: selected Daily-tab recognition, bounded inventory, overlap reconciliation, current game-day evidence.
- Variants: selected tab, Main-negative, clipped-row abstention, scroll overlap.
- Exclusions: Main Quest Claim, row Claim, Go dispatch, gameplay completion.
- Dependencies/routes: M6 assets; Home → Quest → selected Daily; local ROI source/target/successor.
- Source/target/policy: Bliss Daily header/tab and row identities; zero consequential action policy.
- Offline acceptance/tests: replay selected Daily and negative frames; no duplicate rows; current reset identity required; `tests/test_daily_quest_planning.py` and existing M6 tests.
- Bliss/live boundary: preserve existing evidence only; no fresh runtime interaction.
- Transaction/postcondition/recovery: navigation-only contracts; stop on unknown/ambiguous frame.
- Claim/persistence/registration/scheduler: Claim separate; dormant state; no registration; false.
- Promotion/unlocks: `LIVE_VALIDATED` support; unlocks Claim and objective owners.

### DQ-CLAIM-DAILY
- Covered: generalized ordinary Daily row Claim and exact Personal Might Claim support.
- Variants: generalized row-local Claim; Personal Might exact row.
- Exclusions: Main Quest Claim, milestone chest, Go, objective completion as Claim proof.
- Dependencies/routes: selected Daily inventory → exact row-local control.
- Source/target/policy: selected Daily, complete same objective, exact `CLAIM`, free/zero/one cost, row-local target; no static geometry.
- Offline acceptance/tests: synthetic positive/Go/milestone/clipped/cost/overlay/reset/postcondition cases; existing Claim tests and planning tests.
- Bliss/live boundary: generalized evidence-gated; Personal Might registration preserved; no new registration/input.
- Transaction/postcondition/recovery: `CLAIM_DAILY_QUEST`, one input; same row disappears or points increase; unresolved blocks retry.
- Claim/persistence/registration/scheduler: this is Claim support, never implied by objective; journal authoritative; actual operator registration only for Personal Might; false.
- Promotion/unlocks: generalized `EVIDENCE_GATED`; Personal Might `LIVE_VALIDATED`; unlocks runtime gate.

### DQ-CLAIM-MILESTONE
- Covered: ready activity milestone chest support.
- Variants: each observed point threshold remains a milestone variant, not row Claim.
- Exclusions: ordinary row Claim, Main Claim, locked/static chest, unknown reward.
- Dependencies/routes: Daily inventory → activity milestone panel.
- Source/target/policy: exact ready chest, panel-local target, explicit zero cost, current day/profile.
- Offline acceptance/tests: ready/locked/static/wrong-panel/cost/overlay/reset/unchanged cases; `tests/test_activity_milestones.py`.
- Bliss/live boundary: no fresh ready chest evidence; no registration or input.
- Transaction/postcondition/recovery: `CLAIM_ACTIVITY_MILESTONE`, one input; chest opens or points increase; stop/reconcile otherwise.
- Claim/persistence/registration/scheduler: separate milestone Claim; dormant state; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED`; unlocks runtime gate only after Bliss pair.

### DQ-PERSISTENCE
- Covered: task-state persistence alongside SafetyStore.
- Variants: schema-v1/v2 forward migration, revision/completion-key guards, audit event.
- Exclusions: action-journal replacement, live migration, worker wiring, task row creation.
- Dependencies/routes: DQ-SCHEDULER contract → `safe_action_core/store.py` and `task_state.py`.
- Source/target/policy: serialized task snapshot and repository; no gameplay consequence policy.
- Offline acceptance/tests: round-trip, migration, monotonic revision, completion-key rejection; `tests/test_task_state_store.py`.
- Bliss/live boundary: offline SQLite fixtures only; no authoritative journal touched.
- Transaction/postcondition/recovery: repository mutation is deterministic; crash/restart reload preserves unresolved block.
- Claim/persistence/registration/scheduler: persistence support only; no registry; false.
- Promotion/unlocks: `OFFLINE_ONLY`; unlocks future integration gate.

### DQ-SCHEDULER
- Covered: one-pulse deterministic selector and persisted adapter.
- Variants: due, backoff, blocked, unresolved, positive reconciliation.
- Exclusions: scheduler daemon, eligibility enablement, transport, live task rows.
- Dependencies/routes: DQ-PERSISTENCE; state snapshot → one candidate.
- Source/target/policy: game-day, lease-valid, unresolved-free gates; no action authorization.
- Offline acceptance/tests: deterministic ordering, one candidate, wrong day, lease, unresolved, failed-safe, completion key; `tests/test_scheduler.py`, `tests/test_scheduler_sqlite.py`.
- Bliss/live boundary: dormant offline infrastructure; no worker or lease.
- Transaction/postcondition/recovery: records result only; DONE requires verified matching key; unresolved remains globally blocking.
- Claim/persistence/registration/scheduler: no Claim authority; persisted support; not registered; false.
- Promotion/unlocks: `OFFLINE_ONLY`; unlocks runtime gate review.

### DQ-RUNTIME-INTEGRATION-GATE
- Covered: future explicit registration, fresh game-day, journal compatibility, lease, unresolved blocking, first-live migration/rollback, per-flow promotion.
- Variants: operator registration versus runtime registration.
- Exclusions: all live integration during this run, new registration, task rows, scheduler enablement.
- Dependencies/routes: all promoted flow tasks → worker integration gate.
- Source/target/policy: checked-in registry/pnsctl entry, current game-day, locked profile, central policy.
- Offline acceptance/tests: mocked registration parity, schema-v1/v2, lease and unresolved matrices, rollback; planning tests.
- Bliss/live boundary: future gate only; no ADB/worker/VM interaction.
- Transaction/postcondition/recovery: no transaction now; future dispatch requires exact source/target/successor and rollback on mismatch.
- Claim/persistence/registration/scheduler: Claim independently authorized; no migration now; no current registration; false.
- Promotion/unlocks: `OFFLINE_ONLY`; unlocks only after explicit future authorization.

### DQ-FLOW-ALLIANCE-HELP
- Covered: `help_allies`; individual Help and Help All variants.
- Exclusions: Claim, donation, purchase, generic popup, retry after unresolved.
- Dependencies/routes: inventory → `daily_go_to_speedup_help` → Alliance Help.
- Source/target/policy: literal Help All lower target preferred; individual Help fallback; zero-cost.
- Offline acceptance/tests: exact ROI separation, action kind, one-pulse postcondition, no-effect/unresolved; `tests/test_alliance_help.py`.
- Bliss/live boundary: live validated evidence preserved; no new input in this run.
- Transaction/postcondition/recovery: one `ALLIANCE_HELP_ALL` or `ALLIANCE_HELP_ONE`; request/control/no-request state changes; unresolved stops.
- Claim/persistence/registration/scheduler: completion never implies Claim; existing journal; `REGISTERED_OPERATOR`; false.
- Promotion/unlocks: `LIVE_VALIDATED`; unlocks future Daily progress review.

### DQ-FLOW-PERSONAL-MIGHT-PRAISE
- Covered: `personal_might_praise`, one Praise variant.
- Exclusions: Claim inside Praise handler, static GnBots geometry, repeat/cooldown.
- Dependencies/routes: inventory → `daily_go_to_personal_might`; existing route anchors.
- Source/target/policy: current Personal Might leaderboard and rank-one gold Praise; zero cost/cooldown bound.
- Offline acceptance/tests: route, popup, target, postcondition, selected Daily reconciliation; `tests/test_personal_might_praise.py`.
- Bliss/live boundary: live validated operator flow preserved; no rerun or new input.
- Transaction/postcondition/recovery: one `PRAISE_PERSONAL_MIGHT`; control/count/Daily progress changes; stop on ambiguity.
- Claim/persistence/registration/scheduler: explicit separate Claim; action journal; `REGISTERED_OPERATOR`; false.
- Promotion/unlocks: `LIVE_VALIDATED`; unlocks only future unattended gate.

### DQ-FLOW-BIOENHANCER
- Status: Passed (2026-07-14; offline contract and 5 focused tests).
- Covered: `bioenhancer_research`; one free research variant.
- Exclusions: paid/10x research, Nova Praise, premium actions.
- Dependencies/routes: inventory → Bioenhancer route.
- Source/target/policy: selected row, free Research 1x, known zero cost.
- Offline acceptance/tests: semantic free/cost/overlay/postcondition contract and replay;
  `tests/test_bioenhancer.py`.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one free research; result/cooldown and Daily progress; stop on free disappearance.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED`; unlocks only after native pair.

### DQ-FLOW-SUPPLY-DEPOT
- Status: Passed (2026-07-14; existing offline contract and 5 focused tests).
- Covered: `supply_depot`; free collection variant.
- Exclusions: premium/unknown reward, vendor selector, blind triple tap.
- Dependencies/routes: inventory → Supply Depot panel.
- Source/target/policy: exact free target, known non-premium reward, zero cost.
- Offline acceptance/tests: `tests/test_supply_depot.py` positive/negative contract suite.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one free collect; target disappears/confirmation; stop on unchanged/premium.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED`; unlocks runtime gate after native pair.

### DQ-FLOW-RECRUITMENT
- Status: Passed (2026-07-14; Daily five-count adapter plus 5 focused tests).
- Covered: `recruit_noahs_tavern`; free single variant repeated to target quantity.
- Exclusions: 10x, premium, unknown confirmation, vendor selector.
- Dependencies/routes: inventory → Noah's Tavern.
- Source/target/policy: explicit FREE mode/banner, quantity one, zero cost.
- Offline acceptance/tests: `tasks/daily_recruitment.py` and
  `tests/test_daily_recruitment.py` cover selected-row ownership, exact five one-pulse
  successors, dispatch cardinality, Main/ambiguous negatives, and Claim separation; the shared
  free contract remains covered by `tests/test_free_recruitment.py`.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one `RECRUIT_FREE` per pulse, exactly enough pulses to reach
  5/5; result/count increase required; stop on partial or ambiguous result.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED`; unlocks after native pair.

### DQ-FLOW-NANOWEAPON
- Status: Passed (2026-07-14; offline contract and 5 focused tests).
- Covered: `craft_nanoweapon`; Craft Weapon variant.
- Exclusions: Material Production, Inherit Weapon, long/expensive craft, unknown materials.
- Dependencies/routes: inventory → Gear Factory → Nanoweapon.
- Source/target/policy: exact Craft Weapon target and free/allowlisted materials.
- Offline acceptance/tests: recognizer/transaction/postcondition mocks; static reference rejection;
  `tests/test_nanoweapon.py`.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one craft; timer/result and Daily progress; stop on material/cost ambiguity.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED` only if free policy is proven.

### DQ-FLOW-ENHANCE-GEAR
- Status: Passed (2026-07-14; shared Gear contract and 5 focused tests).
- Covered: `enhance_gear`; Gear variant.
- Exclusions: Auto Select, >1-star materials, Promote/Modify/Replace/Unequip, premium.
- Dependencies/routes: inventory → Commander Info → Gear.
- Source/target/policy: equipped Gear, Enhance, one-star material, quantity one, exact Confirm.
- Offline acceptance/tests: shared enhancement family contract with route-specific fixtures;
  `tests/test_enhancement.py`.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one enhancement; Gear level/material change; stop on target/material/quantity ambiguity.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED`; unlocks other enhancement variants through family sharing.

### DQ-FLOW-ENHANCE-CHIP
- Status: Passed (2026-07-14; shared Chip contract and 5 focused tests).
- Covered: `enhance_chip`; Chip variant.
- Exclusions: same enhancement unsafe actions and materials as Gear.
- Dependencies/routes: DQ-FLOW-ENHANCE-GEAR shared engine → Commander Info → Chip.
- Source/target/policy: equipped Chip, one-star material, quantity one.
- Offline acceptance/tests: shared engine plus Chip recognizer/postcondition fixture;
  `tests/test_enhance_chip.py`.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one enhancement; Chip state changes; stop on ambiguity.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED`; family-shared implementation.

### DQ-FLOW-ENHANCE-MODULE
- Status: Passed (2026-07-14; shared Module contract and 5 focused tests).
- Covered: `enhance_module`; Module variant.
- Exclusions: same enhancement unsafe actions and materials as Gear.
- Dependencies/routes: DQ-FLOW-ENHANCE-GEAR shared engine → Commander Info → Module.
- Source/target/policy: equipped Module, one-star material, quantity one.
- Offline acceptance/tests: shared engine plus Module recognizer/postcondition fixture;
  `tests/test_enhance_module.py`.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one enhancement; Module state changes; stop on ambiguity.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED`; family-shared implementation.

### DQ-FLOW-CAMPAIGN-AP
- Status: Passed (2026-07-14; offline AP contract and 5 focused tests).
- Covered: `consume_ap`; Sweep/Auto Complete variants.
- Exclusions: uncontrolled battle, refill, unknown AP cost, Ultimate Challenge dispatch.
- Dependencies/routes: inventory → Campaign.
- Source/target/policy: readable AP, allowlisted stage, exact Sweep/Auto Complete.
- Offline acceptance/tests: AP budget/cost/result/postcondition fixtures;
  `tests/test_campaign_ap.py`; no live stage use.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one known AP transaction; AP delta/result/Daily progress; unresolved on timeout.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED`; unlocks Challenge policy review.

### DQ-FLOW-WORLD-STAMINA-ENGINE
- Status: Passed (2026-07-14; offline shared primitive and 5 focused tests).
- Covered: shared world, map, march, stamina, and tile primitives.
- Variants: map toggle, search, occupancy, march capacity, level recognition.
- Exclusions: vendor selector, coordinate-only taps, generic popup sweep, unknown level.
- Dependencies/routes: proven inventory → World; proven Zombie Lair and gathering flows depend on it.
- Source/target/policy: Bliss-native map/node/march anchors; world/stamina policy.
- Offline acceptance/tests: World route/resource replay, family ownership, budget bounds, Main/static
  rejection, and stale-state fixtures; `tests/test_world_stamina.py`.
- Bliss/live boundary: no fresh world evidence or live input.
- Transaction/postcondition/recovery: primitives do not complete objectives; each action requires positive successor; stop after bounded failure.
- Claim/persistence/registration/scheduler: no Claim; dormant; not registered; false.
- Promotion/unlocks: `OFFLINE_ONLY`; unlocks Zombie Lair, Stamina, and proven Gathering.

### DQ-FLOW-ZOMBIE-LAIR
- Status: Passed (2026-07-14; offline Lair contract and 5 focused tests).
- Covered: `defeat_zombie_lair`; Lair variant.
- Exclusions: level 60, unknown level, arbitrary combat, Claim.
- Dependencies/routes: DQ-FLOW-WORLD-STAMINA-ENGINE → recognized Lair.
- Source/target/policy: exact row, lair level, stamina, march slot, join.
- Offline acceptance/tests: Lair level/slot/stamina/result fixtures and fail-closed negatives;
  `tests/test_zombie_lair.py`.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one join; positive participation/result; unresolved on unknown combat.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED`; requires explicit level/stamina policy.

### DQ-FLOW-STAMINA
- Status: Passed (2026-07-14; disabled counter-only contract and 5 focused tests).
- Covered: `consume_stamina`; shared stamina-consume variant.
- Exclusions: implicit substitution by Lair, unknown action, resource refill.
- Dependencies/routes: DQ-FLOW-WORLD-STAMINA-ENGINE.
- Source/target/policy: exact Daily row, known stamina cost, approved action.
- Offline acceptance/tests: selected-Daily counter recognition, same-day stamina delta arithmetic,
  disabled dispatch guard, Main/static negatives, and Claim separation; `tests/test_stamina_disabled.py`.
- Bliss/live boundary: disabled until explicit policy; no registration/input.
- Transaction/postcondition/recovery: no transaction path; counter-only replay verifies arithmetic;
  every dispatch request blocks under policy; stop on cost/result ambiguity.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `DISABLED_POLICY`; product decision required.

### DQ-FLOW-GATHERING
- Status: Passed (2026-07-14; parameterized Wood/Steel/Gas offline contract and 6 focused tests).
- Covered: `gather_wood`, `gather_steel`, `gather_gas`.
- Variants: Wood 30000, Steel 6000, Gas 1500; one parameterized engine.
- Exclusions: occupied nodes, existing march override, coordinate-only vendor geometry.
- Dependencies/routes: DQ-FLOW-WORLD-STAMINA-ENGINE → World Search → node → march.
- Source/target/policy: exact resource row, resource node identity, free/known march policy.
- Offline acceptance/tests: exact variant ownership, node identity/level, occupancy and march
  capacity, known formation/duration, outbound queue/result, provenance and Main negatives;
  `tests/test_gathering.py`.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one gather march; outbound/positive gather and Daily progress; stop on weak disappearance.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED`; Food remains excluded pending selected-Daily proof.

### DQ-FLOW-TRAINING
- Status: Passed (2026-07-14; disabled four-variant queue contract and 6 focused tests).
- Covered: `train_fighter`, `train_rider`, `train_shooter`, `train_vehicle`.
- Variants: four troop types, shared queue/quantity engine.
- Exclusions: automatic resource packs, oversized batches, unknown tier.
- Dependencies/routes: inventory → troop building/training screen.
- Source/target/policy: exact troop type, minimum tier, quantity 250, known cost/queue.
- Offline acceptance/tests: exact four-way ownership, selected-Daily/unit/facility binding, exact
  quantity and capacity, cost/queue guards, arithmetic successor, Main/static negatives, and
  unconditional dispatch block; `tests/test_training_disabled.py`.
- Bliss/live boundary: disabled pending resource policy; no registration/input.
- Transaction/postcondition/recovery: no transaction path; queue arithmetic replay only; every
  dispatch request blocks; stop on cost/queue ambiguity.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `DISABLED_POLICY`; product/tier decision required.

### DQ-FLOW-BUILDING-UPGRADE
- Status: Passed (2026-07-14; disabled generic building contract and 5 focused tests).
- Covered: `upgrade_building`; proven generic variant only.
- Exclusions: automatic resource packs, unknown queue, strategic target without allowlist.
- Dependencies/routes: inventory → named building/radial menu → Upgrade.
- Source/target/policy: exact building identity, queue, cost, free/allowlist.
- Offline acceptance/tests: generic identity and level successor, Vehicle Depot Main negative,
  cost/queue/stale-source guards, disabled dispatch, and Claim separation;
  `tests/test_building_upgrade_disabled.py`.
- Bliss/live boundary: disabled; no registration/input.
- Transaction/postcondition/recovery: no transaction path; level arithmetic replay only; every
  dispatch request blocks; stop on unexpected resource dialog.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `DISABLED_POLICY`; policy decision required. Vehicle Depot is Main-only and
  remains outside Daily ownership.

### DQ-FLOW-TECH-UPGRADE
- Status: Passed (2026-07-14; disabled prerequisite/level contract and 5 focused tests).
- Covered: `upgrade_tech`; Research variant.
- Exclusions: automatic resource packs, unknown geometry, strategic research without allowlist.
- Dependencies/routes: inventory → research route.
- Source/target/policy: exact technology, queue, cost, resource policy.
- Offline acceptance/tests: technology/prerequisite identity, level successor, queue/cost/source
  guards, disabled dispatch, Main/static negatives, and Claim separation;
  `tests/test_tech_upgrade_disabled.py`.
- Bliss/live boundary: disabled; no registration/input.
- Transaction/postcondition/recovery: no transaction path; level arithmetic replay only; every
  dispatch request blocks; stop on ambiguity.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `DISABLED_POLICY`; policy decision required.

### DQ-FLOW-HERO-UPGRADE
- Status: Passed (2026-07-14; disabled selected-hero/material/level contract and 5 focused tests).
- Covered: `upgrade_hero`; upgrade variant.
- Exclusions: hero acquisition, premium/material guess, unrelated ownership objective.
- Dependencies/routes: inventory → Hero screen.
- Source/target/policy: exact hero, upgrade control, known materials/cost.
- Offline acceptance/tests: selected hero/material identity, level successor, disabled dispatch,
  Main/ambiguous negatives, and Claim separation; `tests/test_hero_upgrade_disabled.py`.
- Bliss/live boundary: disabled; no registration/input.
- Transaction/postcondition/recovery: no transaction path; level arithmetic replay only; every
  dispatch request blocks; stop on ambiguity.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `DISABLED_POLICY`; product decision required.

### DQ-FLOW-PURCHASES
- Status: Passed (2026-07-14; disabled four-variant shop contract and 6 focused tests).
- Covered: `buy_box`, `ruins_shop_purchase`, `rare_earth_shop_purchase`, `alliance_shop_purchase`.
- Variants: box, Ruins, Rare Earth, Alliance Shop; shared allowlist engine.
- Exclusions: premium/unknown offers, auto purchase, static vendor selectors.
- Dependencies/routes: inventory → shop-specific route.
- Source/target/policy: exact item, currency, quantity one, allowlisted cost.
- Offline acceptance/tests: four-way shop identity, offer/cost/currency guards, offline item/cost
  arithmetic, disabled dispatch, Main/ambiguous negatives, and Claim separation;
  `tests/test_purchases_disabled.py`.
- Bliss/live boundary: disabled; no registration/input.
- Transaction/postcondition/recovery: no transaction path; item/currency arithmetic replay only;
  every dispatch request blocks; stop on any offer change.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `DISABLED_POLICY`; product purchase policy required.

### DQ-FLOW-DONATION
- Status: Passed (2026-07-14; disabled Alliance Technology contract and 5 focused tests).
- Covered: `donate_alliance_tech`.
- Variants: resource/tech target only after allowlist.
- Exclusions: unknown resource, broad donation, uncontrolled repeated donation.
- Dependencies/routes: inventory → Alliance Technology.
- Source/target/policy: exact tech and resource amount; disabled policy.
- Offline acceptance/tests: target/resource identity, count/resource arithmetic, disabled dispatch,
  Main/ambiguous negatives, and Claim separation; `tests/test_donation_disabled.py`.
- Bliss/live boundary: disabled; no registration/input.
- Transaction/postcondition/recovery: no transaction path; count/resource arithmetic replay only;
  every dispatch request blocks; stop on mismatch.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `DISABLED_POLICY`; resource policy decision required.

### DQ-FLOW-SPEEDUP
- Status: Passed (2026-07-14; disabled 180-minute timer/item contract and 5 focused tests).
- Covered: `speedup_using_items`; 180-minute item variant.
- Variants: item type and timer target, both allowlisted.
- Exclusions: premium currency, arbitrary target, item waste.
- Dependencies/routes: inventory → existing timer/Speedup.
- Source/target/policy: exact timer, item, quantity, known cost.
- Offline acceptance/tests: 180-minute timer/item identity, quantity arithmetic, disabled dispatch,
  Main/ambiguous negatives, and Claim separation; `tests/test_speedup_disabled.py`.
- Bliss/live boundary: disabled; no registration/input.
- Transaction/postcondition/recovery: no transaction path; timer/item arithmetic replay only; every
  dispatch request blocks; stop on unknown.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `DISABLED_POLICY`; allowlist decision required.

### DQ-FLOW-CHALLENGES
- Status: Passed (2026-07-14; disabled Ruins Challenge contract and 5 focused tests).
- Covered: `ruins_challenge`; Ultimate wording is Main-only evidence and is excluded.
- Exclusions: treating variants as aliases, uncontrolled combat, AP/premium use.
- Dependencies/routes: inventory → challenge-specific routes.
- Source/target/policy: exact challenge identity, entry control, cost/AP policy.
- Offline acceptance/tests: Ruins identity, entry cost/AP guards, result replay, Ultimate/Main and
  ambiguous negatives, disabled dispatch, and Claim separation; `tests/test_challenge_disabled.py`.
- Bliss/live boundary: disabled; no registration/input.
- Transaction/postcondition/recovery: no transaction path; result/progress replay only; every entry
  request blocks; stop on combat/unknown.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `DISABLED_POLICY`; challenge policy required.

### DQ-FLOW-HERO-DUEL
- Status: Passed (2026-07-14; disabled Hero Duel event contract and 5 focused tests).
- Covered: `join_hero_duel`; three-entry PvP variant.
- Exclusions: lineup changes, opponent selection, premium, autonomous PvP.
- Dependencies/routes: inventory → Hero Duel.
- Source/target/policy: exact entry, opponent/consequence policy.
- Offline acceptance/tests: event/Join identity, active-attempt guards, participation successor,
  Main/static negatives, disabled dispatch, and Claim separation; `tests/test_hero_duel_disabled.py`.
- Bliss/live boundary: disabled; no registration/input.
- Transaction/postcondition/recovery: no transaction path; participation arithmetic replay only;
  every event-entry request blocks; stop on ambiguity.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `DISABLED_POLICY`; explicit PvP decision required.

### DQ-FLOW-RESOURCE-BOOST
- Status: Passed (2026-07-14; disabled resource-building boost contract and 5 focused tests).
- Covered: `boost_resource_building_output`; any-resource-building variant.
- Exclusions: unknown building, premium boost, uncontrolled duration.
- Dependencies/routes: inventory → resource building.
- Source/target/policy: exact building, boost control, duration/cost.
- Offline acceptance/tests: `tests/test_resource_boost_disabled.py` covers building/resource
  identity, duration/cost guards, boost-state postcondition replay, Main/ambiguous negatives,
  disabled dispatch, and Claim separation.
- Bliss/live boundary: disabled; no registration/input.
- Transaction/postcondition/recovery: no transaction path; timer/state replay only; stop on
  building, cost, duration, stale-frame, or successor ambiguity.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `DISABLED_POLICY`; resource-building boost policy required.
