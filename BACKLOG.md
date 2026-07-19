# Canonical execution backlog

Last updated: 2026-07-14 (America/Chicago)

This is the single authoritative task/status record. The service plan controls technical
requirements and measured facts. Evidence records contain observations, not competing status.

## Repository governance migration

### GOV-DURABLE-STATE — Establish durable agent governance and state contracts

- Task ID: `GOV-DURABLE-STATE`
- Title: Establish durable agent governance and state contracts.
- Status: Completed (2026-07-15; durable governance and state contracts validated and committed).
- Milestone: Repository governance and durable-state architecture.
- Dependencies: repository authority files identified; protected untracked evidence preserved;
  no runtime or production dependency.
- Blocked by: none known; stop if protected-work ownership, authoritative journal state, or exact
  evidence identity cannot be determined without prohibited operations.
- Objective: establish compact permanent policy, a deterministic volatile handoff schema, a
  self-contained backlog task contract, an exact current-evidence manifest, Cursor indexing
  controls, and focused structural validation without changing runtime behavior.
- Established facts:
  - `AGENTS.md`, `BACKLOG.md`, `CURRENT_HANDOFF.md`, exact local evidence references, and Git
    state are the governing repository sources.
  - `MVP-QUEST-TO-CLAIM` remains the next product task; its product status, runtime authorization,
    evidence conclusions, and implementation state are not changed by this task.
  - Raw retained evidence and protected untracked paths must not be moved, deleted, compacted, or
    staged.
- Scope:
  - Direct implementation files: `AGENTS.md`, `CURRENT_HANDOFF.md`, this task section,
    `docs/runtime-input-safety-policy.md`, `docs/journal-lease-policy.md`,
    `docs/chat-execution-ownership-policy.md`, `docs/backlog-task-contract.md`,
    `docs/evidence-retention-policy.md`, `docs/pns-operations-runbook.md`,
    `evidence/current-evidence-manifest.json`, `.cursorindexingignore`,
    `scripts/validate_governance.py`, and `tests/test_governance_validation.py`.
  - Shared dependencies: Python standard library, existing unittest conventions, existing
    evidence-retention policy, and exact local canonical summaries.
  - Transitive regression set: governance validator tests, active Daily planning validation,
    evidence-reference/hygiene tests, and documentation consistency checks directly affected by
    the changed policy references.
  - Allowed changes: only the named governance files, exact task section, and direct runbook/policy
    cross-references.
  - Prohibited changes: production modules, `safe_action_core`, task implementations, registration,
    scheduler state, runtime files, journals, evidence content, `.local-reference/`, historical
    backlog entries, plan files, or prompt templates.
- Live authorization:
  - Authorized runtime action: none; repository documentation and offline validation only.
  - Maximum transport inputs: navigation-only `0`; consequential `0`; recovery `0`.
  - Navigation-only recovery: forbidden.
  - Consequential action: forbidden.
  - Registration changes: forbidden.
  - Scheduler changes: forbidden.
  - Actions that must not be repeated: no runtime operation, ADB operation, worker startup, evidence
    collection, journal migration, lease mutation, gameplay input, or production validation.
- Recognition contract:
  - Required source: exact repository files named by this task and exact evidence paths already
    referenced by the handoff, task, transaction result, or journal records.
  - Exact target semantics: deterministic governance fields and exact evidence artifact identity;
    no visual or approximate evidence substitution.
  - Required local association: `GOV-DURABLE-STATE` must be the handoff current task and
    `MVP-QUEST-TO-CLAIM` must be a declared, not-yet-active next task.
  - Negative controls: no recursive `evidence/` search, no transcript loading, no runtime process
    discovery, no production-file edits, and no inferred journal/lease facts.
  - Coordinate space: not applicable; no runtime input is authorized.
- Semantic postcondition:
  - Accepted signals: exact handoff schema parses, current task and backlog contract agree, all
    required policy sections exist, exact manifest statuses/hashes validate, indexing exclusions
    preserve lightweight authorities, and focused tests pass.
  - Rejected weak signals: Markdown prose alone, a transport or command result, approximate path
    matching, a missing hash, or a visually similar artifact.
  - Ambiguous-result behavior: record `UNKNOWN`, `NOT_VERIFIED_THIS_RUN`, `MISSING`, or
    `NOT_LOCATED` as applicable; stop before staging or committing disputed files.
- Product resource policy:
  - Zero-cost requirement: no product action is authorized.
  - Quantity limits: zero runtime inputs.
  - Resource consumption policy: no resources, currency, premium items, or game state may change.
  - Premium or strategic restrictions: all prohibited.
- Evidence contract:
  - Active evidence manifest: `evidence/current-evidence-manifest.json`.
  - Evidence requirement: REQUIRED; this governance task retains the canonical current evidence manifest.
  - Required artifacts: exact governance files, validator output, and only exact Bioenhancer
    summaries/results/journals named by the manifest.
  - Immediate-before/immediate-post/result/journal: preserve existing references; do not collect,
    move, normalize, or replace evidence.
  - Additional task-specific artifacts: validator test output and final Git status/diff review.
- Verification:
  - Focused tests: `tests/test_governance_validation.py`.
  - Integration tests: affected `tests/test_daily_quest_planning.py` and evidence-reference tests.
  - Transitive regression tests: existing evidence-hygiene and planning validators touched by the
    new policy/indexing contract.
  - Full-suite requirement: none; production code is unchanged.
  - Validators: `scripts/validate_governance.py`, `git diff --check`, exact manifest path/hash
    validation, and indexing-rule validation.
  - Known baseline failures: report existing environment or `cv2`/evidence-fixture failures
    separately; any new failure in touched governance code blocks completion.
- Valid blocked outcomes:
  - protected-work ownership cannot be determined;
  - exact journal/lease/unresolved state cannot be represented without runtime access;
  - an evidence hash/path cannot be classified without approximation;
  - a validator requires production behavior changes;
  - a protected file would need to be staged or moved.
- Blocked-result commit policy: evidence/status boundary commit is permitted only for
  noncontroversial governance structure when this task cannot complete; otherwise no commit.
- Commit policy:
  - Expected focused commits: up to three, only when non-empty and dependency boundaries are clear.
  - `docs(agent): define durable execution policy` allowed paths:
    `AGENTS.md`, `BACKLOG.md` (this task section only),
    `docs/runtime-input-safety-policy.md`, `docs/journal-lease-policy.md`,
    `docs/chat-execution-ownership-policy.md`, `docs/backlog-task-contract.md`,
    `docs/evidence-retention-policy.md`, and `docs/pns-operations-runbook.md`.
  - `docs(handoff): standardize current operational state` allowed paths:
    `CURRENT_HANDOFF.md`, `evidence/current-evidence-manifest.json`, and
    `.cursorindexingignore`.
  - `chore(governance): validate durable state contracts` allowed paths:
    `scripts/validate_governance.py`, `tests/test_governance_validation.py`, plus reviewed
    handoff/task-status hunks required for the terminal state transition.
  - Shared files require reviewed hunk-level staging or the affected commits must be collapsed;
    never stage a complete shared file for one unrelated hunk.
  - No unrelated commits and no push.
- Completion criteria:
  - `GOV-DURABLE-STATE` is terminally committed;
  - `AGENTS.md` is compact and invariant-only;
  - the handoff contains deterministic current/next task fields and fixed sections;
  - the exact manifest and indexing policy validate;
  - the active task and validator tests pass;
  - `MVP-QUEST-TO-CLAIM` remains the next task with activation status
    `contract_migration_required` unless separately migrated and validated;
  - no runtime or production behavior changed and no protected evidence was moved or staged.

### TOOLS-BLUESTACKS-FLOW-CAPTURE — Build a practical BlueStacks manual flow collector

- Task ID: `TOOLS-BLUESTACKS-FLOW-CAPTURE`
- Title: Build a practical Windows/BlueStacks flow-capture utility for later Bliss translation.
- Status: Completed (2026-07-16; elevated Windows passive smoke accepted with 11 observed actions and verified ZIP).
- Milestone: Offline tooling and translation corpus preparation.
- Dependencies: Python standard library, tkinter, Windows ctypes hooks, and the repository's
  existing image dependency convention; no runtime or product dependency.
- Blocked by: none. Matching collector/BlueStacks high integrity was confirmed by the accepted Windows
  smoke; the collector now fails early with administrator guidance when process integrity is incompatible.
- Objective: record manual BlueStacks quest walkthroughs as screenshots, coordinates, actions,
  transitions, semantic labels, notes, and an exportable ZIP without executing a quest autonomously.
- Established facts:
  - This task is a user-driven recorder and does not authorize Bliss, Unraid, production automation,
    scheduler, registration, or gameplay during implementation.
  - Local capture output is ignored under `.local-captures/`; it is not canonical evidence.
- Direct implementation files: `scripts/bluestacks_flow_collector.py`,
  `scripts/bluestacks_passive.py`, `docs/bluestacks-flow-capture.md`, `.gitignore`, and
  `.cursorindexingignore`.
- Shared dependencies: Python subprocess/tkinter, Windows ctypes input hooks, JSON/path/hash/ZIP
  standard-library helpers, and the explicit BlueStacks serial/window supplied by the user.
- Transitive regression set: focused governance validation, syntax/help checks, and no production
  automation tests.
- Allowed changes: the named collector, guide, ignore rules, local session schema, and task-local
  offline validation artifacts only.
- Prohibited changes: Bliss or Unraid contact; gameplay; production automation, journals, leases,
  registration, scheduler, historical evidence, `.local-reference/`, or push.
- Authorized runtime action: none during implementation; future capture sessions may use only the
  explicitly selected BlueStacks device after user confirmation.
- Maximum transport inputs: navigation-only `0`; consequential `0` during this
  activation task.
- Navigation-only recovery: forbidden.
- Consequential action: forbidden during implementation; future recorder dispatch remains explicitly
  user-confirmed and exactly once per selected action.
- Registration changes: forbidden.
- Scheduler changes: forbidden.
- Actions that must not be repeated: any prior MVP, Praise, Claim, Bioenhancer, Supply Depot,
  recruitment, ADB, pnsctl, Bliss, or gameplay action.
- Required source: a current clean BlueStacks screenshot or a synthetic mock image selected by the
  user; no vendor or stale evidence.
- Exact target semantics: the user-selected tap/swipe/Back/Wait action and its semantic labels, not
  autonomous target discovery or route inference.
- Required local association: displayed selection, raw 800x1280 coordinates, source frame, before/
  after frames, annotation, labels, and manifest step must belong to the same recorder session.
- Negative controls: unselected devices, known Bliss/Unraid serials, wrong package, wrong orientation
  or resolution, letterboxed/out-of-bounds points, stale frames, and canceled confirmations.
- Coordinate space: raw portrait 800x1280 frame; displayed coordinates must retain scale and padding
  metadata.
- Accepted signals: clean PNG frames, explicit user confirmation, deterministic labels, and verified
  manifest/ZIP hashes.
- Rejected weak signals: transport success alone, approximate coordinates, scaled screenshots treated
  as raw, automatic retries, route discovery, or guessed semantic success.
- Ambiguous-result behavior: preserve the partial session and error; do not retry or delete artifacts.
- Zero-cost requirement: no game resource or state change is authorized during implementation.
- Quantity limits: zero gameplay inputs during this activation.
- Resource consumption policy: none.
- Premium or strategic restrictions: all prohibited.
- Evidence requirement: NOT_APPLICABLE — offline tooling activation creates no canonical runtime evidence.
- Active evidence manifest: null; ignored `.local-captures/` output is not required to exist.
- Required artifacts: collector source, concise operating guide, focused validator coverage, and
  ignored-output rules.
- Immediate-before/immediate-post/result/journal: not applicable to this governance activation.
- Additional task-specific artifacts: none; future sessions retain their own local manifests.
- Focused tests: `tests/test_governance_validation.py`, Python compile/help, and direct
  mock/manifest/ZIP checks when the collector task is implemented.
- Integration tests: none.
- Transitive regression tests: none beyond governance and touched-file validation.
- Full-suite requirement: none.
- Validators: `scripts/validate_governance.py`, JSON parsing, indexing validation,
  `git diff --check`, and touched-file secret scan.
- Known baseline failures: report existing cv2/evidence-fixture or unrelated dirty-worktree failures
  separately; any new governance failure blocks activation.
- Valid blocked outcomes: inability to represent the task contract without weakening validation,
  protected-work overlap that cannot be isolated, or missing required local tooling.
- Blocked-result commit policy: preserve valid governance repair work; do not activate or commit an
  invalid task transition.
- Commit policy: stage only reviewed collector-task paths or hunks; never absorb existing MVP work.
- Expected focused commits: `feat(tools): add BlueStacks flow collector`; allowed paths are
  limited to the named collector, guide, ignore rules, and this exact task/handoff transition.
- Completion criteria: the collector implementation includes passive selected-window tap/swipe/Back
  observation, rolling clean before frames, delayed after frames, optional metadata, guide, mock mode,
  coordinate translation, manifest/ZIP verification, and ignored local storage; Windows manual smoke
  must confirm an observed action with before/after frames; no gameplay or Bliss input occurs.
- Verification: compile, `--help`, pure coordinate checks, synthetic mock session, passive tap/swipe/Back
  harness, manifest parsing, local SHA-256 verification, deterministic ZIP member verification,
  touched-file checks, DPI/integrity/finalization compile, governance, and diff checks passed. Elevated
  Windows smoke `20260716T012457275520Z` captured 11 actions with complete before/after/annotated
  frames; 36 local hashes, 37 sorted ZIP members, archived manifest and hashes, raw-coordinate bounds,
  and pre-action frame timing all verified.
- Collector commands used: mock `python3 scripts/bluestacks_flow_collector.py --mock-image
  /tmp/bluestacks-collector-synthetic.png --flow-id collector-smoke-test --daily-objective
  "Collector smoke test" --post-action-delay 0 --output-directory /tmp/bluestacks-collector-check
  --no-gui`; Windows passive `python scripts\\bluestacks_flow_collector.py --adb
  "C:\\Program Files\\BlueStacks_nxt\\HD-Adb.exe" --serial emulator-5554 --passive --window-title
  "BlueStacks App Player 4" --flow-id passive-smoke --daily-objective "Passive smoke"
  --post-action-delay 1`.
- Temporary verified output: `/tmp/bluestacks-collector-check/bluestacks/collector-smoke-test/20260715T211220540935Z/`;
  it is not canonical evidence and no capture was staged.
- Accepted Windows smoke output: `.local-captures/bluestacks/passive-smoke/20260716T012457275520Z/`;
  11 actions, complete frame triplets, compatible high-integrity processes, 36 verified artifacts, and
  37 sorted verified ZIP members. The ignored local session remains preserved and unstaged.
- Runtime boundary: the collector dispatched zero gameplay or ADB inputs; it passively observed 11
  user-driven BlueStacks inputs. Zero Bliss, Unraid, production runtime, registration, scheduler,
  journal, or lease operations occurred.
- Next permitted action: run the collector locally on Windows against BlueStacks and capture the first
  missing quest flow, beginning with AP through Campaign Auto Complete.
- No push unless explicitly authorized.
- Next: `MVP-QUEST-TO-CLAIM` remains the next inactive product task; its existing successor remains
  `M6-DQ-TRANSITION-CORPUS`.

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

- Task ID: `MVP-QUEST-TO-CLAIM`
- Title: Complete one supervised Daily Quest vertical slice.
- Status: Passed (2026-07-15; one bounded supervised Claim completed and independently reconciled).
- Milestone: M8 claim-only MVP validation.
- Dependencies: `M6-DQ-BOOTSTRAP` Passed, `M7-SAFE-ACTION-CORE` Passed,
  `MVP-STARTUP-NORMALIZATION` Passed, and no active unresolved action.
- Blocked by: none for this bounded trial. The fresh source established the selected Daily Quest
  screen, current game-day binding, and an ordinary completed Bioenhancer Research Claim row.
- Objective: prove one bounded, supervised Daily Quest quest-to-claim transition using the selected
  runtime and the minimum safety core, then stop.
- Established facts:
  - The original scope is exactly: navigate to Daily Quest; determine whether one completed,
    unclaimed row exists; if none exists, complete exactly one approved zero-cost R1 objective;
    verify that row becomes Claim; claim exactly that row; prove the postcondition; stop.
  - This is agent-driven supervised development input, not unattended automatic gameplay. RT-016A
    and M7-AccountGuard remain required before unattended automatic gameplay.
  - The product entry remains Blocked: the typed continuation report had no admissible selected-
    Daily proof for its named objectives; the retained first-four frame was Main Quest, Gather Food
    was synthetic-only, and Headquarters was documentation-only.
  - No ordinary Claim row, admissible Alliance Help objective, or explicitly free fallback objective
    was established in the retained blocker evidence. No Go or Claim input was sent in that state.
  - The retained schema-v1 journal was terminal-only with no unresolved/nonterminal records and a
    released lease at that observation. The prior Help attempt and later retained unresolved
    diagnostic records remain evidence conclusions and must not be repeated.
  - Selected-Daily correction/retest, bounded inventory, local-row handling, startup escape policy,
    and central safety-core behavior were validated in the existing evidence conclusions. Existing
    records cite both a 96-test dependency-complete suite and a later 100-test selected-tab retest;
    this activation does not revalidate either.
  - Alliance Help geometry was corrected: the upper `(556,274)-(727,330)` target is individual
    Help, while the lower `(277,1188)-(523,1268)` target is Help All. The retained
    `alliance-help-1783986842` action was dispatched once and reconciled positively, but no Claim
    or Daily Quest completion was proven.
  - Personal Might Praise and Claim work is a separate completed/validated area and is not part of
    this task. The retained popup and phase-2 route records remain unresolved or diagnostic.
  - Runtime registration remains `NOT_REGISTERED_UNCHANGED` and scheduler state remains
    `DISABLED/INELIGIBLE`; this task does not promote either state.
- Result: the fresh selected-Daily frame positively identified the completed Bioenhancer Research
  row and its local Claim control. No prerequisite was needed. Exactly one Claim tap was sent
  through the central policy/executor path. The toast reported `Daily Achieved: Bioenhancer
  Research x1`, the row disappeared, and Daily Quest Pts increased from 0 to 5. The action first
  persisted `unresolved` on an unexpected successor, then was manually reconciled to `confirmed`
  from the preserved postcondition frames without retry.
- Blocker: none. Historical `alliance-help-1783981635` was not reused or retried; it is outside
  this task cycle. The current Claim journal is terminally confirmed and its lease is released or
  expires by policy before handoff.
- Direct implementation files: `scripts/mvp_quest_to_claim.py`, `scripts/pnsctl.py`,
  `safe_action_core/executor.py`, and `safe_action_core/policy.py`. These are the only product
  files directly changed for this trial.
- Shared dependencies: `M6-DQ-BOOTSTRAP`, `M7-SAFE-ACTION-CORE`,
  `MVP-STARTUP-NORMALIZATION`, RT-019 profile evidence, the central policy/executor path, and the
  persistent action journal/lease contracts.
- Transitive regression set: M6 corpus recognition and six-asset validation, M7 safety-core and
  journal crash-boundary tests, RT-019 profile checks, focused Daily planning tests, and any exact
  task-module tests named by a future implementation allowlist.
- Allowed changes: this contract, its exact task-specific evidence manifest, persisted handoff,
  and the directly allowlisted execution files above. Runtime execution remained limited to the
  seven original bounded scope steps, through the central policy/executor path, with exact
  current-frame binding and retained evidence.
- Prohibited changes: Supply Depot; recruitment; unrelated Daily objectives; generalized framework
  redesign; evidence hygiene; scheduler activation; runtime registration changes; downstream
  backlog work; push; production modules outside the direct allowlist; and any additional runtime,
  worker, ADB, SSH, Docker, emulator, or game operation after this bounded trial.
- Authorized runtime action: one exact Claim after all source, game-day, target, cost, journal,
  lease, and unresolved-action gates passed. No prerequisite was required; Supply Depot remains
  unauthorized.
- Maximum transport inputs: this trial used navigation-only `0`, prerequisite `0`, and Claim `1`.
  The task contract maximum remains `2` consequential inputs (`1` prerequisite if needed and
  `1` Claim), with Claim maximum `1`.
- Navigation-only recovery: forbidden during activation. Future recovery may use only a fresh,
  evidence-supported narrow policy; no identical retry, generic popup cleanup, or recovery after an
  ambiguous consequence.
- Consequential action: Claim is separately journaled, current-frame validated, row-locally bound,
  sent once through the central executor, and independently reconciled. Any unknown or unresolved
  result is terminal for this task; no blind retry.
- Registration changes: forbidden; preserve `NOT_REGISTERED_UNCHANGED`.
- Scheduler changes: forbidden; preserve `DISABLED/INELIGIBLE` and no eligible flows.
- Actions that must not be repeated: Bioenhancer research or actions
  `bioenhancer-free-1784069057` and `bioenhancer-free-1784079616`; `daily-claim-1784092554`;
  any prior validated Praise or Daily Claim transaction; `alliance-help-1783986842`;
  `reset-popup-close-1783994269-2`; any additional gameplay input; Supply Depot, recruitment, or
  unrelated Daily work; evidence movement or collection; and any action key from retained sessions.
- Required source: fresh raw full-frame `800x1280` evidence after startup reconciliation with
  selected Daily Quest positively recognized, no forbidden overlay, positively assigned current
  reset/game-day identity, and either an ordinary completed-unclaimed row or a supported zero-cost
  objective.
- Exact target semantics: the exact completed row's local `Claim` control, not `Go`, Main Quest,
  another row, a generic button, or a coordinate-only target. If a prerequisite is needed, its
  exact zero-cost target must be recognized from the same current frame and remain within the
  existing MVP objective.
- Required local association: selected Daily tab, objective row, local control, source frame,
  immediate-before frame, action journal, and game-day identity must all refer to the same current
  task cycle. No stale or cross-session association is valid.
- Negative controls: Main Quest selected as Daily; typed or synthetic objective wording without
  admissible selected-Daily proof; stale/scaled/partial frames; missing game-day identity; unknown
  overlays; purchase, premium, reward, quantity, or offer controls; Supply Depot; recruitment;
  unrelated Daily objectives; Go mistaken for Claim; and any active unresolved action.
- Coordinate space: raw full-frame `800x1280` evidence at the expected `160 dpi` profile
  `pns-blissos-poc-virgl-800x1280-v1`; never scaled previews, stale captures, crops, or vendor
  coordinates.
- Accepted signals: fresh source recognition; selected Daily tab; exact local target recognition;
  reset/game-day binding; immediate-before revalidation; exactly one authorized transport input per
  consequential action; and positive claimed-row/reward/points postcondition.
- Rejected weak signals: transport success alone; a visually similar or stale frame; text without
  selected-Daily provenance; a generic Claim-looking control; row disappearance without the required
  independent postcondition; or a command result without journal/evidence reconciliation.
- Ambiguous-result behavior: stop immediately, preserve all available frames and the journal,
  classify the action unresolved, block further consequential input, release or preserve lease
  state according to policy, and require manual reconciliation. Never retry blindly.
- Game-day requirements: this execution freshly established reset identity and bound all task
  state, evidence, and authorization to that game day. The task-cycle game-day binding is recorded
  in the result evidence; no later action may reuse it without fresh verification.
- Journal and lease requirements: use the central persistent journal and exclusive lease; require no
  active prepared, input-sent, or unresolved consequential action before dispatch; persist
  prepared/input-sent/confirmed-or-unresolved transitions; and leave no action between prepared and
  terminal state at handoff. Activation touched neither journal nor lease.
- Zero-cost requirement: the prerequisite, if needed, must be positively proven zero-cost before
  dispatch; no resource, currency, premium item, or strategic state may be consumed.
- Quantity limits: at most one approved prerequisite if needed and exactly one Claim; no additional
  Daily, quest, reward, or gameplay action.
- Resource consumption policy: no resource-consuming substitute, purchase, reward, quantity, or
  strategic action is permitted.
- Premium or strategic restrictions: premium, paid, strategic, recruitment, Supply Depot, and
  unrelated objective actions are forbidden.
- Active evidence manifest: `evidence/mvp-quest-to-claim-evidence-manifest.json`, sourced from
- Evidence requirement: REQUIRED; this supervised runtime task retains its exact task-scoped evidence manifest.
  `evidence/current-evidence-manifest.json` and exact references named by this task.
- Required artifacts: fresh source, immediate-before, transport/journal record, immediate-post,
  semantic result, unresolved proof when applicable, and exact task-cycle/game-day evidence for a
  future execution. Current activation has no fresh runtime artifacts.
- Immediate-before/immediate-post/result/journal: verified for the 2026-07-15 trial with exact
  hashes in the active manifest; retained evidence was not replaced.
- Additional task-specific artifacts: the exact retained paths in the MVP manifest, including
  `live-continuation-20260713.md`, selected-tab retest, Daily inventory, popup diagnostics, and
  phase-2 route directories; no recursive evidence inspection is permitted.
- Focused tests: `tests/test_governance_validation.py` plus the task-contract, handoff identity,
  manifest path/hash, indexing-boundary, JSON, secret-scan, and `git diff --check` validations
  required for this activation. No product/runtime test is authorized here.
- Integration tests: future supervised trial only, after offline replay and dry-run gates; none in
  this activation.
- Transitive regression tests: existing M6, M7, RT-019, and affected Daily planning validators;
  report prior evidence-hygiene environment failures separately.
- Full-suite requirement: none for this bounded live trial; focused tests had already passed for
  the touched execution and safety paths, and no unrelated suite expansion was performed.
- Validators: `scripts/validate_governance.py`, focused governance unittest, JSON parsing, exact
  manifest path/hash validation, indexing-boundary validation, secret scan of touched files, and
  `git diff --check`.
- Known baseline failures: six accepted evidence-hygiene environment-specific failures and any
  previously recorded cv2/evidence-fixture failures; a new failure in touched governance code
  blocks completion.
- Valid blocked outcomes: unresolved product decision; missing exact source/target/game-day proof;
  active unresolved action; unknown overlay or cost; unavailable exact evidence identity; protected
  work ownership ambiguity; validator failure; or any request for runtime/production mutation.
- Blocked-result commit policy: if migration cannot be completed without an unresolved product
  decision, do not activate; preserve `GOV-DURABLE-STATE` as completed current, retain this task as
  next with `contract_migration_required` or `dependency_blocked`, record the exact missing field,
  and commit only the noncontroversial blocked-state documentation permitted by the existing
  policy. This activation has no such unresolved contract field.
- Commit policy: one focused activation commit; stage only `BACKLOG.md`, `CURRENT_HANDOFF.md`,
  `evidence/mvp-quest-to-claim-evidence-manifest.json`, `scripts/validate_governance.py`, and
  `tests/test_governance_validation.py`. Protected evidence and unrelated paths are never staged.
- Expected focused commits: `docs(tasks): activate MVP quest-to-claim contract` allowed paths:
  `BACKLOG.md` (this task section only), `CURRENT_HANDOFF.md`, the exact MVP evidence manifest,
  and directly affected governance validator/test hunks. No push unless explicitly authorized.
- Completion criteria: the original bounded objective, dependencies, status, safety boundaries,
  Claim separation, evidence conclusions, registration state, and scheduler state remain explicit;
  this contract validates; the handoff records this task as `passed`; the Claim journal is
  terminal; no further consequential action is pending; and one focused documentation commit
  records the result.
- Stop conditions: stop on any validator failure, protected-work ambiguity, evidence identity
  ambiguity, unresolved contract decision, runtime request, unexpected product-file change, active
  prepared/input-sent action, or any need to broaden the original objective.
- Final reporting requirements: report starting/ending HEAD, branch/worktree state, task ID,
  contract fields added or corrected, preserved scope and status, handoff state, manifest, tests and
  validators, changed files, commit hash, zero runtime operations, journal/lease state, registration
  and scheduler state, unresolved actions, exact next permitted action, prohibited repeats, and
  push status.
- Next permitted action: downstream M6 transition-corpus review may begin in a separate task;
  do not repeat this Claim or start unrelated gameplay.
- Historical evidence conclusions retained:
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
- Next: `M6-DQ-TRANSITION-CORPUS` may review the retained positive transition evidence; no further
  MVP gameplay input is authorized.
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
- Status: `BIOENHANCER_SAME_DAY_END_TO_END_CONFIRMED` (2026-07-15 UTC); execution validated;
  Daily reconciliation validated; Claim execution not performed.
- Active parity subtask: `BIOENHANCER-GNBOTS-PARITY` completed offline on 2026-07-15 with
  primary outcome `GNBOTS_REFERENCE_DOES_NOT_IMPLEMENT_BIOENHANCER`. The decoded GnBots reference
  has generic Daily claim/recruit/depot/leaderboard behavior and malformed generic town research,
  but no Bioenhancer routine, Free Research 1x/10x branch, Bioenhancer target, or Daily
  reconciliation. Canonical artifact:
  `docs/research/bioenhancer_gnbots_parity_manifest.json`.
- Covered: `bioenhancer_research`; one free research variant.
- Exclusions: paid/10x research, Nova Praise, premium actions.
- Dependencies/routes: inventory → selected Daily row → direct Bioenhancer Research screen.
- Source/target/policy: selected row `0/1`, current-frame Free Research 1x
  `(94,1133)-(345,1216)`, separate paid 10x rejected, known zero cost and quantity one.
- Offline acceptance/tests: `tasks/daily_bioenhancer.py` binds selected-row ownership, exact
  0/1 Daily progress, same-day result, dispatch cardinality, Main/static negatives, and Claim
  separation; `tests/test_daily_bioenhancer.py` plus `tests/test_bioenhancer.py`.
- Bliss/live boundary: transaction `bioenhancer-free-1784069057` is terminally confirmed in
  `evidence/sessions/20260714-bioenhancer-live-transaction/bioenhancer-free-1784069057-result.json`
  with one transport call, zero cost, quantity one, Free Research 1x binding, positive result/
  cooldown postcondition, and Research 10x untouched.
- Transaction/postcondition/recovery: live research result is confirmed. The later selected-Daily
  inspection occurred after the `daily-2026-07-14` reset and observed the exact Bioenhancer row at
  `0/1`; after the verified `daily-2026-07-15` reset, exactly one new Free Research 1x advanced
  the row to `1/1` with Claim visible. Canonical rerun artifact:
  `docs/research/bioenhancer_e2e_validation_manifest.json`.
- Terminal journal/lease: `bioenhancer-free-1784079616` is terminally `confirmed` with
  `positive_postcondition`; its lease is `EXPIRED_BY_POLICY` and no active consequential action
  remains. The benign reset-popup navigation diagnostic is terminally classified in
  `evidence/sessions/20260714-bioenhancer-e2e-validation/reset-popup-close-diagnostic-classification.json`
  without altering either research transaction.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `LIVE_VALIDATED` under `SUPERVISED_VALIDATION` for research and same-day
  reconciliation; Claim remains independently unperformed. No registration or scheduler
  eligibility. Next atomic backlog task is `DQ-CLAIM-DAILY`; no Claim dispatch is authorized in
  this closure.
- Parity conclusion: no implementation change; GnBots does not implement this objective. The
  verified new reset removed the prior day-boundary ambiguity, and the same-day objective
  progression is now proven. Research 10x and Claim were not dispatched.
- Non-repeatable actions: `bioenhancer-free-1784069057` and `bioenhancer-free-1784079616`.
- Reset-inference disposition: no shared game-day/reset implementation defect was established;
  the earlier discrepancy was corrected by fresh reset verification. No shared reset code changed
  and no separate reset-defect task was opened.

### DQ-FLOW-SUPPLY-DEPOT
- Status: `EVIDENCE_ACQUIRED` (2026-07-14; selected-Daily navigation route and free-target
  observation retained; no collection dispatched).
- Covered: `supply_depot`; free collection variant.
- Exclusions: premium/unknown reward, vendor selector, blind triple tap.
- Dependencies/routes: inventory → selected Daily row → Supply Depot panel → bounded Home/Base
  return → Quest → selected Daily.
- Source/target/policy: selected Daily `0/5`, exact Go `(554,786)-(731,878)`, Supply Depot
  successor, four visible Free controls, annotated first free-single target
  `(35,1170)-(174,1261)`, observed basic reward, no overlay, zero cost/quantity one.
- Offline acceptance/tests: `tasks/daily_supply_depot.py` binds selected-row ownership, exact
  five-count progress, one-pulse collection successors, Main/static negatives, dispatch
  cardinality, and Claim separation; `tests/test_daily_supply_depot.py` plus
  `tests/test_supply_depot.py`.
- Bliss/live boundary: `evidence/sessions/20260714-daily-flow-acquisition/supply-depot-navigation.json`;
  navigation confirmed, no collection input.
- Transaction/postcondition/recovery: one free collect; target disappears/confirmation; stop on unchanged/premium.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `POLICY_GATED`; game-day identity, known-reward approval, positive
  collection/postcondition, and Daily reconciliation remain required. No registration or
  scheduler.

### TOOLS-HOME-BASE-ATLAS-BLUESTACKS
- Task ID: `TOOLS-HOME-BASE-ATLAS-BLUESTACKS`.
- Title: Build a reusable Home atlas, localizer, semantic building navigator, and direct local
  BlueStacks Supply Depot consumer.
- Status: Completed (2026-07-18; local BlueStacks atlas/navigation/Supply Depot live validation
  closed with final canonical Home and no in-flight action).
- Milestone: Local platform-neutral Home/Base navigation foundation.
- Dependencies: TOOLS-BLUESTACKS-FLOW-CAPTURE and the dormant DQ-FLOW-SUPPLY-DEPOT contract.
- Blocked by: None; Bliss-native calibration remains a separate future task.
- Objective: provide a reusable platform-neutral semantic world/coverage/localization/navigation
  contract with a BlueStacks-specific stitched pixel atlas and Supply Depot as the first executable
  direct-building consumer. Future Bank, upgrade, camp, research, and production workflows remain
  out of scope and unauthorized.
- Established facts: native `800x1280`; profile `pns-bluestacks-5-p64-800x1280-v1`; held-left-Ctrl
  plus wheel-down is the measured zoom mechanism; the atlas is `1447x2769` with 30 accepted
  viewports, two duplicate rejections, four measured edge clamps, five overlapping scan rows, zero
  reachable interior coverage gaps, maximum residual `0.213 px`, and maximum loop-closure
  disagreement `1.161 px`; the current registry contains 65 facilities/instances (Forum and Parade
  Grounds are mapped but explicitly non-actionable behind fixed HUD); one food Free tap remains confirmed by
  attempts `9->8`, and the separately authorized hold-to-exhaust follow-up used one `11.1 s` Food
  hold to confirm the remaining eight free collections by attempts `8->0` without retry.
- Direct implementation files: `tasks/home_atlas.py`, `tasks/home_atlas_vision.py`,
  `tasks/supply_depot.py`, `tasks/supply_depot_vision.py`, `scripts/home_atlas_bluestacks.py`,
  `scripts/supply_depot_bluestacks.py`, and `tasks/assets/home_atlas/bluestacks/800x1280/**`.
- Shared dependencies: `scripts/bluestacks_native_runtime.py`, `tasks/contracts.py`, and
  `tasks/profile.py`; no production registration or task row.
- Transitive regression set: Home atlas tests, Supply Depot contract/vision/route tests, existing
  BlueStacks integrated-route tests, governance tests, and the full repository suite when practical.
- Allowed changes: task implementation, tests, BlueStacks-only atlas assets, relevant research
  documentation, this task contract, and CURRENT_HANDOFF; per-commit allowed paths are the direct
  implementation files just listed and no others.
- Prohibited changes: unrelated workflows, protected evidence, Bliss/Unraid/production input,
  workers, task rows, registration, scheduler promotion, credential/manual-only automation, and
  staging/commit/push without a later explicit request.
- Authorized runtime action: local BlueStacks Home panning, held-Ctrl+wheel zoom normalization,
  recognized building open/back navigation, the earlier single Free tap, and the later explicitly
  authorized one-gesture Food hold over the freshly observed remaining Free attempts; no Bliss or
  production action.
- Maximum transport inputs: bounded navigation with fresh capture/relocalization after each input;
  one consequential hold gesture for the observed attempts and no consequential retry.
- Navigation-only recovery: stop on unknown zoom, overlay, insufficient landmarks, ambiguous
  transform, no progress, repeated viewport, map-edge clamp, unexpected successor, or maximum pans;
  use exact recognized Back/radial controls only.
- Consequential action: the earlier zero-cost Food tap
  `supply-depot-free:bluestacks:no-reset:attempts-9:food` confirmed `9->8`; the follow-up bounded hold
  `supply-depot-free-hold:bluestacks:no-reset:attempts-8:food` confirmed `8->0` from a fresh exact
  exhausted successor and read-only reconciliation.
- Registration changes: None; production registration remains `NOT_REGISTERED`.
- Scheduler changes: None; scheduler eligibility remains false.
- Actions that must not be repeated: either confirmed Supply Depot action key, any further Supply
  input in this task, ambiguous consequential transport, or any BlueStacks-to-Bliss coordinate or
  calibration reuse.
- Required source: fresh native local BlueStacks `800x1280` package `com.global.ztmslg` frames with
  exact profile, frame hashes, timestamps, zoom identity, and no manual-only state.
- Exact target semantics: a current-frame Supply Depot label/helicopter-pad binding, then the exact
  radial `Claim Supply` control, then one control whose visible semantic state is Free/zero-cost.
- Required local association: atlas projection narrows the search only; OCR/visual building evidence
  and exact successor are required before a building tap, and the radial must separately show
  Details, Upgrade, and Claim Supply.
- Negative controls: coordinate-only building taps, Daily Quest Go by default, Daily Claim,
  Upgrade, premium/paid/Mall controls, resource items, speedups, tickets, AP, stamina, Bank, research,
  training, healing, production, overlays, stale frames, and wrong profiles.
- Coordinate space: semantic world coordinates are canonical BlueStacks atlas pixels distinct from
  current native screen coordinates; BlueStacks and Bliss calibration are isolated.
- Accepted signals: multi-viewport SIFT landmarks, bounded measured transforms/residuals, exact
  building OCR plus visual signature, exact Supply Depot title, all visible controls classified,
  and attempts decrementing by exactly one or another explicit positive receipt/reward increase.
- Rejected weak signals: native dimensions alone, transport success, prior camera position,
  coordinate projection alone, HUD-only/animation-only matches, button disappearance alone, row
  order, fixed Daily coordinates, and cross-platform scaling.
- Ambiguous-result behavior: reconcile a consequential action unresolved and never retry; retain
  before/post/settled evidence and stop.
- Zero-cost requirement: required; exact Free text, zero premium/purchase visibility, and cost type
  none/amount zero on the immediate-before frame.
- Quantity limits: the primary `collect-free` route permits one bounded Food hold for 1-10 freshly
  recognized free attempts and stops at exhaustion; it never automatically retries. `collect-one`
  remains a one-tap diagnostic fallback.
- Resource consumption policy: no resource item, pack, inventory item, AP, stamina, speedup, ticket,
  or paid currency may be consumed.
- Premium or strategic restrictions: diamonds, purchases, Mall/store, Bank deposit, upgrades,
  research, training, healing, and unrelated consequential building controls are forbidden.
- Active evidence manifest: None; concise local BlueStacks evidence is ignored diagnostic/runtime
  evidence and is not a canonical Bliss production manifest.
- Required artifacts: checked-in atlas manifest/mosaic/tiles, research atlas summary, zoom proof,
  accepted/rejected viewport metadata, loop closure, semantic registry, live localizations,
  navigation binding, Supply Depot screen, collection before/post/result, and final Home.
- Immediate-before/immediate-post/result/journal: retained under
  `.local-captures/supply-depot-direct-building/supply-depot-collect-one-20260718T205259350054Z/`.
- Hold immediate-before/post/result and read-only reconciliation: retained under
  `.local-captures/supply-depot-direct-building/supply-depot-collect-free-hold-20260718T233948312187Z/`
  and `.local-captures/supply-depot-direct-building/supply-depot-reconcile-free-hold-20260718T234250460579Z/`.
- Additional task-specific artifacts: retained paths are enumerated in
  `docs/research/home_ui_atlas.md`; atlas schema and platform separation live in the checked-in
  BlueStacks manifest.
- Focused tests: `tests.test_home_atlas`, `tests.test_supply_depot`,
  `tests.test_supply_depot_vision`, and `tests.test_supply_depot_bluestacks`.
- Integration tests: `tests.test_bluestacks_integrated_routes` plus live executable localizer,
  navigator, Supply Depot continuation, collection, and return-home runs.
- Transitive regression tests: governance validation and existing BlueStacks route regressions.
- Full-suite requirement: run the full repository unittest suite if practical; report established
  baseline failures separately and allow no new touched-component failure.
- Validators: Python compilation, governance validation, handoff JSON parsing, atlas/research JSON
  parsing, touched-file secret scan, and `git diff --check`.
- Known baseline failures: None; the full suite passed 532 tests with one expected skip after the
  hold-to-exhaust follow-up.
- Evidence requirement: NOT_APPLICABLE because this local BlueStacks validation creates no
  canonical Bliss evidence manifest; concise ignored local evidence and checked-in atlas assets are
  sufficient for this task.
- Valid blocked outcomes: any fail-closed source/zoom/localization/coverage/binding/successor,
  premium/purchase, duplicate, no-progress, stale, overlay, or ambiguous-result stop.
- Blocked-result commit policy: do not stage or commit a blocked live result; retain local evidence
  and update the handoff only when no action remains in flight.
- Commit policy: no staging, commit, or push was requested; no push by default.
- Expected focused commits: None in this task because the user prohibited staging/commit/push unless
  explicitly requested.
- Completion criteria: executable BlueStacks atlas/localizer/navigator and direct Supply Depot route
  run end to end; at most one Free collection is positively reconciled; final canonical Home is
  recognized; tests/validators pass; production stays unregistered and scheduler-disabled; no
  forbidden action occurs.

### TOOLS-HOME-ATLAS-DIRECT-PAN-PLANNER
- Task ID: `TOOLS-HOME-ATLAS-DIRECT-PAN-PLANNER`.
- Title: Reusable platform-neutral minimal-pan planner over the completed Home/Base atlas.
- Status: Completed (2026-07-18; local BlueStacks navigation-only validation closed at canonical Home).
- Milestone: Local platform-neutral semantic Home navigation foundation.
- Dependencies: completed `TOOLS-HOME-BASE-ATLAS-BLUESTACKS` and its passed atlas, registry,
  localization, canonical zoom, camera envelope, and Supply Depot binding.
- Blocked by: None; Bliss calibration remains an independent future task.
- Objective: replace broad/fixed-distance building navigation with calculated target-specific atlas
  viewport plans, adapter-owned gesture conversion, fresh post-pan relocalization, measured progress,
  and current-frame semantic binding for every actionable mapped building.
- Established facts: atlas `1447x2769`; camera origins `x=0.86..646.79`, `y=0.08..1488.01`;
  safe BlueStacks region `(145,180)-(650,1010)`; placement anchor `(400,600)`; measured gesture
  conversion approximately `2.1 atlas px / screen-drag px`; 65 mapped entries, with Forum and Parade
  Grounds non-actionable on the BlueStacks profile.
- Direct implementation files: `tasks/home_atlas_planner.py`, `tasks/home_atlas.py`,
  `tasks/home_atlas_vision.py`, `scripts/home_atlas_bluestacks.py`, semantic atlas metadata, focused
  tests, research docs, `BACKLOG.md`, and `CURRENT_HANDOFF.md`.
- Shared dependencies: `scripts/bluestacks_native_runtime.py`, the completed atlas assets, and the
  existing Supply Depot vision regression surface; no production registration or task row.
- Transitive regression set: Home atlas/planner, Supply Depot, BlueStacks integrated routes,
  governance, and full repository discovery.
- Allowed changes: per-commit allowed paths are the direct implementation files, focused tests,
  semantic metadata/research docs, this task contract, and current handoff only.
- Prohibited changes: unrelated workflows, protected evidence, Bliss/Unraid/production input,
  building opens, workers, task rows, registration, scheduler, staging, commit, or push.
- Authorized runtime action: local BlueStacks native `800x1280` Home panning only through the
  executable project-owned capture/transport route; no building tap was authorized.
- Maximum transport inputs: four calculated pans per target, with fresh capture and relocalization
  after each; observed maximum was two.
- Navigation-only recovery: stop on invalid source, calibration, coverage, localization, progress,
  repeated viewport, edge clamp, semantic binding, or pan-count guard; do not repeat identical input.
- Consequential action: None; all runtime input was navigation-only Home camera panning.
- Registration changes: None; production remains `NOT_REGISTERED`.
- Scheduler changes: None; scheduler remains disabled/ineligible.
- Actions that must not be repeated: the two recorded no-progress canonical short-drag targets, any
  building tap, either prior Supply Depot collection key, or any BlueStacks calibration reuse in Bliss.
- Required source: fresh native local BlueStacks `800x1280` Home frames, exact package/profile,
  canonical zoom, frame identity, no overlay, and positive current localization.
- Exact target semantics: mapped semantic building ID and atlas polygon, followed by current-frame
  renderer-specific label binding inside the safe interaction region.
- Required local association: atlas projection narrows the search only; current-frame OCR and an
  atlas-predicted safe building ROI are required for completion.
- Negative controls: coordinate-only success, building taps, Supply collection, downstream building
  workflows, stale/overlay/wrong-profile frames, and Bliss/Unraid input.
- Coordinate space: canonical BlueStacks atlas pixels are distinct from native screen pixels;
  gesture geometry is injected by a platform adapter and is not portable to Bliss.
- Accepted signals: recognized canonical Home, supported screen-to-atlas transform, verified target
  coverage, reachable desired origin, measured forward displacement, and fresh semantic binding.
- Rejected weak signals: transport success, accumulated swipe count, prior camera state, projection
  alone, native dimensions alone, and current-frame label without local atlas association.
- Ambiguous-result behavior: stop navigation, retain immediate-before/post/settled records, freshly
  localize when safe, and never blindly retry.
- Zero-cost requirement: NOT_APPLICABLE; this task performs no collection or other transaction.
- Quantity limits: zero building/workflow actions; at most four navigation pans per target.
- Resource consumption policy: no resource, item, AP, stamina, speedup, ticket, or currency use.
- Premium or strategic restrictions: no premium, purchase, Mall, Bank deposit, upgrade, research,
  training, healing, production collection, or other consequential control.
- Active evidence manifest: None; local BlueStacks route evidence is ignored task-local diagnostics.
- Required artifacts: each starting localization and plan, pan frame triplets, measured displacement,
  final semantic bindings, a fail-closed case, and final canonical Home recovery.
- Immediate-before/immediate-post/result/journal: retained in the exact ignored local route sessions
  listed in `docs/research/home_ui_atlas.md`; no consequential journal was created.
- Additional task-specific artifacts: planner contracts in `tasks/home_atlas_planner.py` and the
  machine-readable validation summary in `docs/research/home_ui_atlas.json`.
- Focused tests: `tests.test_home_atlas_planner`, `tests.test_home_atlas`, Supply Depot vision/route,
  and BlueStacks integrated-route tests; 57 passed.
- Integration tests: project-owned `navigate-building` dry-run and navigation-only live routes for
  Headquarters, Supply Depot, Bank, and Gear Factory.
- Transitive regression tests: governance validation and full repository discovery.
- Full-suite requirement: run full unittest discovery when practical; 544 passed with one expected skip.
- Validators: Python compilation, governance, CURRENT_HANDOFF JSON, atlas/research JSON, touched-file
  secret scan, and `git diff --check`.
- Known baseline failures: None; one expected full-suite skip.
- Evidence requirement: NOT_APPLICABLE because this local BlueStacks validation creates no canonical
  Bliss evidence manifest; concise ignored sessions and checked-in semantic summaries are sufficient.
- Valid blocked outcomes: all declared source, coverage, calibration, localization, progress,
  repeated viewport, map-edge, maximum-pan, and current-frame semantic-recognition failures.
- Blocked-result commit policy: do not stage or commit a blocked live result; record terminal state
  only after no action remains in flight.
- Commit policy: no staging, commit, or push was requested; no push by default.
- Expected focused commits: None because the user explicitly prohibited staging/commit/push.
- Completion criteria: platform-neutral direct planner and independent BlueStacks adapter implemented;
  required live target matrix bound without building opens; final canonical Home recognized;
  validators pass; production stays unregistered and scheduler-disabled; no forbidden action occurs.

### TOOLS-HOME-ATLAS-TROOP-TRAINING-ENTRY-MIGRATION
- Task ID: `TOOLS-HOME-ATLAS-TROOP-TRAINING-ENTRY-MIGRATION`.
- Title: Migrate local BlueStacks Troop Training facility entry to the completed Home atlas direct-pan planner.
- Status: Completed (2026-07-18; local BlueStacks Fighter/Vehicle entry-only validation closed at canonical Home with zero Train input).
- Milestone: Local platform-neutral semantic Home navigation consumers.
- Dependencies: completed `TOOLS-HOME-ATLAS-DIRECT-PAN-PLANNER`, semantic registry, canonical zoom/localization, and passed Troop Training recognition/downstream controller.
- Blocked by: None; Bliss remains an independent uncalibrated platform.
- Objective: select the first enabled troop type's mapped semantic facility, freshly localize any canonical native Home camera, calculate/relocalize bounded pans, bind the facility from the current frame, open only its exact radial, recognize Train, and support entry-only recovery to canonical Home without tapping Train.
- Established facts: the atlas and direct-pan planner are passed authority; the legacy Troop Training Home recognizer required all four facilities in one frame; Fighter and Vehicle live entry-only validation completed with no Train or consequential input.
- Direct implementation files: `tasks/troop_training_entry.py`, `tasks/troop_training_vision.py`, `scripts/troop_training_bluestacks.py`, the BlueStacks current-frame binder/Vehicle renderer policy, focused tests, research summaries, this task contract, and current handoff.
- Shared dependencies: completed `tasks/home_atlas_planner.py`, atlas/localizer, BlueStacks native runtime, and unchanged downstream `TrainingController`/`TroopTrainingRuntimeController`.
- Transitive regression set: Home atlas/planner, Troop Training, BlueStacks integrated routes, Supply Depot, governance, and full repository discovery.
- Mapped facilities: fighter `home.building.fighter_camp`; shooter `home.building.shooter_camp`; rider `home.building.rider_camp`; vehicle `home.building.vehicle_depot`.
- Allowed changes: per-commit allowed paths are the narrowly scoped Troop Training entry contracts/vision/BlueStacks route and tests, BlueStacks binder/Vehicle renderer policy, this task entry, current handoff, and concise task-local research/evidence references.
- Prohibited changes: atlas rebuild/reacquisition, Bliss geometry/input, Unraid/production, downstream training semantics, Train/quantity/resource/Warehouse/resource-box/premium/consequential input, workers, task rows, registration, scheduler, staging, commit, or push.
- Authorized runtime action: local BlueStacks native 800x1280 Home panning, freshly bound facility tap, positively recognized radial inspection, and positively recognized Back recovery only through the project-owned runtime.
- Maximum transport inputs: four calculated Home pans per facility plus one freshly bound facility tap and one safe Back; zero Train inputs.
- Navigation-only recovery: require the exact fresh facility radial and a BlueStacks-safe exterior scene target outside every projected semantic building polygon; prove the radial gone and canonical Home freshly localized, otherwise stop without retry.
- Consequential action: None; entry-only mode has no Train dispatch path and the passed downstream controller is unchanged.
- Registration changes: None; production stays not registered and scheduler-disabled/ineligible.
- Scheduler changes: None; scheduler stays disabled/ineligible with no worker or task-row changes.
- Actions that must not be repeated: prior Fighter/Vehicle facility taps, the diagnostic Fighter Back that opened the exit dialog, either exterior close, any Train input, or the failed binding/clearance attempts without a new correction.
- Required source: exact local package `com.global.ztmslg`, BlueStacks profile `pns-bluestacks-5-p64-800x1280-v1`, native portrait 800x1280, fresh unambiguous fully-zoomed-out Home localization before planning and after every pan, and no forbidden overlay.
- Exact target semantics: the mapped building ID selected from the first enabled troop type, its current-frame renderer label binding, then that same facility's exact Details/Upgrade/Train radial and Train control.
- Required local association: atlas projection narrows the facility search only; a fresh current-frame label/declared renderer variant is required before the facility tap, and current-frame radial semantics are required before safe close.
- Negative controls: coordinate-only facility success, wrong facility identity, non-Home/wrong-profile/zoom/overlay/stale frames, Train/quantity/Warehouse/resource-box/premium surfaces, and any Bliss geometry reuse.
- Coordinate space: canonical atlas pixels remain platform-neutral; native BlueStacks drag/safe-region/exterior-close geometry is adapter-owned and forbidden for Bliss.
- Accepted signals: current canonical localization, verified target coverage/actionability, measured forward pan progress, exact fresh semantic facility binding, exact facility radial/Train binding, radial disappearance, and final canonical Home localization.
- Rejected weak signals: transport success, projected coordinates alone, prior-frame binding, any background facility label used as radial identity, accumulated pan count, or disappearance without positive Home recovery.
- Ambiguous-result behavior: stop, retain current session frames/events, relocalize read-only when safe, and continue only with a concrete corrected hypothesis; never retry identical input.
- Zero-cost requirement: NOT_APPLICABLE because this is navigation-only and performs no transaction.
- Quantity limits: zero Train inputs, zero quantity edits, at most four planner pans per target, one exact facility entry, and one safe radial close target per validated facility.
- Resource consumption policy: no resource, resource box, Warehouse confirmation, item, AP, stamina, speedup, ticket, or currency use.
- Premium or strategic restrictions: no premium, purchase, Train Now, troop training, upgrade, research, healing, production, collection, recruitment, or unrelated workflow input.
- Active evidence manifest: None; concise ignored local BlueStacks sessions are task diagnostics, not Bliss production evidence.
- Required artifacts: starting/settled localizations, plan and pan frame triplets, requested/measured/residual displacement, current-frame facility/radial bindings, proof Train was not dispatched, safe Home recovery, and one fail-closed case.
- Immediate-before/immediate-post/result/journal: exact ignored sessions are listed in `docs/research/home_ui_atlas.md`/`.json`; runtime `events.jsonl` records only non-consequential local navigation and no consequential journal was created.
- Additional task-specific artifacts: `troop-training-result.json` per primary route, declared Vehicle OCR variants, radial exterior-close binding policy, and final native Home frames.
- Focused tests: Home atlas/planner, `tests.test_troop_training_entry`, and existing Troop Training tests; required mapping, zero/one/corrective pan, relocalization, binding, rejection, radial, dry-run, entry-only, downstream, and platform-separation cases covered.
- Integration tests: project-owned native runtime route with Fighter zero-pan and Vehicle measured-pan entry-only sessions, plus BlueStacks integrated-route and Supply Depot regressions.
- Transitive regression tests: governance validation and full unittest discovery.
- Full-suite requirement: run full repository unittest discovery when practical and allow no new failure beyond the expected skip.
- Validators: Python compilation, focused/full tests, governance, CURRENT_HANDOFF JSON, atlas/research JSON, touched-file secret scan, and `git diff --check`.
- Known baseline failures: None; one expected full-suite skip.
- Evidence requirement: NOT_APPLICABLE because local BlueStacks navigation-only diagnostics create no canonical Bliss evidence manifest; exact ignored sessions and checked-in summaries are sufficient.
- Valid blocked outcomes: every source/profile/zoom/overlay/stale/localization/coverage/actionability/calibration/progress/direction/repetition/edge/pan-count/current-binding/facility/radial/Train/unexpected-surface/safe-close failure.
- Blocked-result commit policy: do not stage or commit a blocked live result; retain local diagnostics only after no action remains in flight.
- Commit policy: preserve all unstaged atlas work; do not stage or commit; no push by default.
- Expected focused commits: None because staging, commit, and push were explicitly prohibited.
- Completion criteria: shared planner entry replaces the all-four-visible gate; entry-only Fighter/Vehicle validation includes zero and measured-pan cases, exact facility/radial bindings, zero Train input, final canonical Home, passing validators, and unchanged registration/scheduler state.

### HOME-ATLAS-RECOVERY-AWARE-VIEWPORT-PLANNING
- Task ID: `HOME-ATLAS-RECOVERY-AWARE-VIEWPORT-PLANNING`.
- Title: Extend the platform-neutral Home atlas direct-pan planner for recovery-aware actionable viewport selection.
- Status: Completed (2026-07-18; offline policy path, BlueStacks inject, and focused tests; no live input).
- Milestone: Local platform-neutral semantic Home navigation foundation.
- Dependencies: completed `TOOLS-HOME-ATLAS-DIRECT-PAN-PLANNER`, completed atlas/localization, and Troop Training entry migration authority.
- Blocked by: None for offline implementation; live BlueStacks validation is outside this authorization.
- Objective: when an optional `ViewportPlanningPolicy` is present, select an actionable destination viewport that supports predicted entry plus predicted recovery search-zone availability—not merely safe-box intersection—while preserving exact legacy behavior when the policy is absent.
- Established facts: direct-pan planner and BlueStacks safe-region/radial-close contracts are authoritative; projection alone never authorizes entry or exit; atlas polygons cannot prove live recovery taps.
- Direct implementation files: `tasks/home_atlas_planner.py`, `scripts/home_atlas_bluestacks.py` policy inject, focused planner tests, research/atlas contract notes, this backlog entry, and `CURRENT_HANDOFF.md`.
- Shared dependencies: completed atlas assets, localization contracts, and existing Supply Depot / Troop Training consumers of dispositions.
- Transitive regression set: Home atlas/planner, Troop Training entry, Supply Depot, BlueStacks integrated routes, governance, and full discovery when practical.
- Allowed changes: per-commit allowed paths are `tasks/home_atlas_planner.py`, `scripts/home_atlas_bluestacks.py` policy inject, focused planner tests, research/atlas planner-contract notes, this task contract, and `CURRENT_HANDOFF.md` only.
- Prohibited changes: atlas rebuild, live BlueStacks/ADB/Bliss/Unraid input, facility entry, radial/consequential input, registration, scheduler, staging, commit, push, or unrelated backlog status changes.
- Authorized runtime action: None; offline only.
- Maximum transport inputs: 0.
- Navigation-only recovery: NOT_APPLICABLE; no runtime input authorized.
- Consequential action: None.
- Registration changes: None; production remains not registered.
- Scheduler changes: None; scheduler remains disabled/ineligible.
- Actions that must not be repeated: prior live facility taps, exterior closes, Supply Depot collections, or any identical no-progress canonical short drag.
- Required source: synthetic offline localizations and checked-in atlas metadata only.
- Exact target semantics: mapped semantic building ID with optional recovery-aware viewport policy; current-frame binding remains required after any future live settle.
- Required local association: affine-correct projection narrows candidates only; live recovery/entry binding stays adapter-owned.
- Negative controls: executable recovery coordinates from the shared planner, viewport-001 recovery bias, symmetric radial annulus as the only model, and policy-absent behavior drift.
- Coordinate space: platform-neutral atlas planning; BlueStacks policy magnitudes adapter-owned and forbidden for Bliss.
- Accepted signals: hard-gated coverage/radial footprint/predicted recovery search zone/registration support, normalized soft scores, deterministic tie-break, and bounded rejection evidence.
- Rejected weak signals: projection alone, map-edge proximity alone, atlas polygons as live tap proof, and canonical_recovery_origin bias.
- Ambiguous-result behavior: fail closed with `no_recoverable_actionable_viewport` when no candidate passes entry and recovery hard gates.
- Zero-cost requirement: NOT_APPLICABLE.
- Quantity limits: at most five additional top rejected alternatives in explanations; navigator destination history rejects before dispatch.
- Resource consumption policy: none.
- Premium or strategic restrictions: no consequential controls.
- Active evidence manifest: None; offline tests only.
- Required artifacts: focused unit tests covering legacy preservation, affine scale, asymmetric radial, recovery honesty, seen-destination reject, tie-break, bounded evidence, and soft map-edge.
- Immediate-before/immediate-post/result/journal: NOT_APPLICABLE.
- Additional task-specific artifacts: `ViewportPlanningPolicy` and honesty fields on `BuildingViewportPlan`.
- Focused tests: `tests.test_home_atlas_planner` plus regressions; Troop Training entry only if residuals drift.
- Integration tests: NOT_APPLICABLE for this offline authorization.
- Transitive regression tests: governance validation and focused discovery of touched modules.
- Full-suite requirement: run focused planner tests; full discovery when practical with no new failures beyond the expected skip.
- Validators: Python compilation, focused tests, CURRENT_HANDOFF JSON, atlas/research JSON, touched-file secret scan, and `git diff --check` when practical.
- Known baseline failures: None; one expected full-suite skip.
- Evidence requirement: NOT_APPLICABLE because this offline planner task creates no runtime evidence manifest.
- Valid blocked outcomes: every declared planner hard-gate and navigator guard.
- Blocked-result commit policy: do not stage or commit; no push.
- Commit policy: no staging, commit, or push; no push by default.
- Expected focused commits: None.
- Completion criteria: optional policy path implemented; legacy path bit-compatible; BlueStacks policy justified from accepted safe-region/radial-close contracts; required offline tests pass; no live input; production stays unregistered and scheduler-disabled.

### TOOLS-HOME-ATLAS-SEMANTIC-REGISTRY-COMPLETION
- Task ID: `TOOLS-HOME-ATLAS-SEMANTIC-REGISTRY-COMPLETION`.
- Title: Complete the current-account Home atlas semantic building registry.
- Status: Completed (2026-07-18; current-account accepted-atlas inventory reconciled with zero runtime input).
- Milestone: Complete semantic inventory over the passed local BlueStacks Home atlas.
- Dependencies: completed `TOOLS-HOME-BASE-ATLAS-BLUESTACKS` and
  `TOOLS-HOME-ATLAS-DIRECT-PAN-PLANNER`.
- Blocked by: None for current-account visible buildings; account-locked future buildings remain absent.
- Objective: audit every accepted atlas label and physical facility against the semantic registry,
  add each genuinely missing current-account building, and retain individual repeated instances for
  future upgrades while allowing workflow-level representative selection.
- Established facts: the 30-view atlas is complete and must not be reacquired; the audit found Parade
  Grounds labeled in viewports 018/019 but absent from the 64-entry registry; Horizon Hub and AI Hub
  are not present at the current account level; Builder Hall is not a separate current-atlas facility.
- Direct implementation files: BlueStacks atlas JSON, Home atlas research JSON/Markdown, focused
  atlas tests, `BACKLOG.md`, `CURRENT_HANDOFF.md`, and governance identity coverage.
- Shared dependencies: `tasks/home_atlas.py`, accepted atlas tiles, completed coverage/localization,
  and platform-neutral planner rejection of non-actionable facilities.
- Transitive regression set: Home atlas/planner, Supply Depot, BlueStacks routes, governance, and full suite.
- Allowed changes: per-commit allowed paths are the semantic atlas metadata, research documentation,
  focused tests, this task contract, and current handoff only.
- Prohibited changes: atlas reacquisition/rebuild, runtime input, building opens/workflows, protected
  evidence, Bliss/Unraid, workers, task rows, registration, scheduler, staging, commit, or push.
- Authorized runtime action: None required; use accepted native tiles and transforms read-only.
- Maximum transport inputs: Zero.
- Navigation-only recovery: NOT_APPLICABLE because no runtime input is authorized or required.
- Consequential action: None.
- Registration changes: None; production remains `NOT_REGISTERED`.
- Scheduler changes: None; scheduler remains disabled/ineligible.
- Actions that must not be repeated: atlas acquisition, coverage scan, prior planner validation pans,
  Supply Depot actions, or no-progress canonical diagnostics.
- Required source: checked-in accepted native BlueStacks atlas manifest, mosaic, and viewports 018/019.
- Exact target semantics: `home.building.parade_grounds`, OCR label Parade Grounds, right-edge troop
  staging facility, polygon `(1287,845)-(1447,960)`, non-actionable behind fixed right HUD.
- Required local association: two accepted viewport OCR observations plus transform-consistent physical geometry.
- Negative controls: OCR noise, UI text, account-locked absent facilities, coordinate-only inference,
  unsafe actionability, and duplicate renaming of already mapped buildings.
- Coordinate space: canonical BlueStacks atlas pixels only; no Bliss coordinate reuse.
- Accepted signals: repeated accepted-tile label, stable transformed geometry, catalog reconciliation,
  and explicit visibility/actionability policy.
- Rejected weak signals: web catalog name alone, a single noisy OCR token, black atlas margins, HUD icons,
  or a building unavailable on this account.
- Ambiguous-result behavior: leave the candidate unmapped and record the unresolved inventory gap; do not acquire input.
- Zero-cost requirement: NOT_APPLICABLE because no transaction occurs.
- Quantity limits: one registry entry per physical instance; workflow aliases remain separate future policy.
- Resource consumption policy: no resource, item, AP, stamina, speedup, ticket, or currency use.
- Premium or strategic restrictions: no building operation, premium, purchase, Mall, Bank, upgrade,
  research, training, healing, or production action.
- Active evidence manifest: None; accepted checked-in atlas assets are the source authority.
- Required artifacts: updated semantic registry, audit summary, current-account completeness test, and handoff.
- Immediate-before/immediate-post/result/journal: NOT_APPLICABLE; zero runtime input and no journal action.
- Additional task-specific artifacts: accepted `viewport-018.png` and `viewport-019.png` already retained in the atlas.
- Focused tests: `tests.test_home_atlas` and `tests.test_home_atlas_planner`.
- Integration tests: atlas loader plus planner rejection for non-actionable mapped facilities.
- Transitive regression tests: Supply Depot, BlueStacks integrated routes, and governance.
- Full-suite requirement: run full unittest discovery when practical; allow no new failure.
- Validators: compilation, focused/full tests, governance, handoff JSON, atlas/research JSON, secret scan,
  and `git diff --check`.
- Known baseline failures: None; one expected full-suite skip.
- Evidence requirement: NOT_APPLICABLE because this is a checked-in atlas metadata audit with no new runtime evidence.
- Valid blocked outcomes: ambiguous label/geometry, missing accepted support, account-locked building, or permanent HUD occlusion.
- Blocked-result commit policy: do not stage or commit a blocked mapping; preserve the existing atlas.
- Commit policy: no staging, commit, or push was requested; no push by default.
- Expected focused commits: None because staging/commit/push were not requested.
- Completion criteria: every current-account accepted-atlas building label reconciled; Parade Grounds mapped
  with exact non-actionable policy; individual resource/infirmary instances preserved; tests and validators pass.

### RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE
- Task ID: `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE`.
- Title: Shared immutable perception bundle for one captured native frame/capture event.
- Status: Completed (2026-07-18; final review-fix for forged-context, nested-target, and frame-validation consistency).
- Milestone: Platform-neutral same-frame perception composition for Home atlas consumers.
- Dependencies: completed `TOOLS-HOME-BASE-ATLAS-BLUESTACKS`, `TOOLS-HOME-ATLAS-DIRECT-PAN-PLANNER`,
  and `TOOLS-HOME-ATLAS-TROOP-TRAINING-ENTRY-MIGRATION`.
- Blocked by: None for offline implementation; Bliss calibration remains independent.
- Objective: create a shared immutable FramePerceptionBundle that binds localization, classification,
  bindings, OCR, targets, and forbidden-surface observations to one capture event with dual digests,
  reject cross-capture composition, classify context fail-closed without dispatch authority, and
  enforce the bundle in `command_navigate_building` only.
- Established facts: Home atlas, direct-pan planner, and Troop Training entry migration are authoritative;
  `CapturedNativeFrame.sha256` is transport PNG digest; `frame_digest` is semantic digest; planner already
  rejects mismatched semantic binding hashes; live BlueStacks validation is not required for this task.
- Direct implementation files: `tasks/perception_bundle.py`, `tests/test_perception_bundle.py`,
  `tests/fixtures/perception_bundle_evidence.json`, `scripts/home_atlas_bluestacks.py` navigate-building
  adoption, this task contract, `CURRENT_HANDOFF.md`, and governance identity coverage.
- Shared dependencies: `tasks/home_atlas.py`, `tasks/home_atlas_planner.py`, `tasks/home_atlas_vision.py`,
  `scripts/bluestacks_native_runtime.py`, and `safe_action_core.models.snapshot`; no production registration.
- Transitive regression set: Home atlas/planner, Troop Training entry, BlueStacks integrated routes,
  governance, and full repository discovery when practical.
- Allowed changes: per-commit allowed paths are the direct implementation files, focused tests/fixtures,
  this task contract, current handoff, and governance identity coverage only.
- Prohibited changes: atlas rebuild/reacquisition, DirectPanNavigator public API changes, consequential
  Train/Supply input, Bliss/Unraid/production, workers, task rows, registration, scheduler, staging,
  commit, or push.
- Authorized runtime action: None required; offline unit/fixture validation is sufficient. Any later
  runtime path must use `scripts/pnsctl.py` only.
- Maximum transport inputs: Zero for this task.
- Navigation-only recovery: NOT_APPLICABLE because no live transport is authorized.
- Consequential action: None.
- Registration changes: None; production remains `NOT_REGISTERED`.
- Scheduler changes: None; scheduler remains disabled/ineligible.
- Actions that must not be repeated: prior Supply Depot collections, Troop Training Train inputs,
  atlas acquisition, or no-progress canonical short-drag diagnostics.
- Required source: synthetic offline capture-event identities and immutable observation snapshots; live
  frames are not required.
- Exact target semantics: one capture-event identity with transport and semantic digests, same-event
  observation composition, and checked navigation inputs for DirectPanNavigator.
- Required local association: every observation carries the complete NativeFrameIdentity; semantic
  composition uses semantic_sha256 only.
- Negative controls: cross-capture composition, transport/semantic hash interchange, mutable payloads,
  numpy retention in the bundle, classifier-as-dispatch-authority, and silent recapture.
- Coordinate space: platform-neutral contracts; BlueStacks geometry remains adapter-owned.
- Accepted signals: full capture-event identity match, dual digests, immutable typed snapshots, versioned
  evidence snapshot, and bundle-enforced planner inputs.
- Rejected weak signals: pixel-hash-only equality, missing overlay identity treated as clear, and
  evidence-only bundle serialization without checked inputs.
- Ambiguous-result behavior: fail closed to unknown/invalid; never authorize transport from context alone.
- Zero-cost requirement: NOT_APPLICABLE because no transaction occurs.
- Quantity limits: one reference route adoption (`command_navigate_building`); zero consequential inputs.
- Resource consumption policy: no resource, item, AP, stamina, speedup, ticket, or currency use.
- Premium or strategic restrictions: no premium, purchase, Mall, Bank, upgrade, research, training,
  healing, or production action.
- Active evidence manifest: None; offline fixtures and additive navigate-building JSON fields are sufficient.
- Required artifacts: perception bundle module, focused tests, versioned evidence fixture, and enforced
  navigate-building integration.
- Immediate-before/immediate-post/result/journal: NOT_APPLICABLE; zero live transport and no journal action.
- Additional task-specific artifacts: `tests/fixtures/perception_bundle_evidence.json`.
- Focused tests: `tests.test_perception_bundle`, `tests.test_home_atlas`, `tests.test_home_atlas_planner`,
  `tests.test_troop_training`, and `tests.test_troop_training_entry`.
- Integration tests: offline bundle-enforced planner integration; no live BlueStacks validation required.
- Transitive regression tests: governance validation and full unittest discovery when practical.
- Full-suite requirement: run full repository unittest discovery if practical; allow no new touched-component failure.
- Validators: Python compilation, focused/full tests, governance, CURRENT_HANDOFF JSON, fixture JSON,
  touched-file secret scan, and `git diff --check`.
- Known baseline failures: None; one expected full-suite skip may remain.
- Evidence requirement: NOT_APPLICABLE because this offline contract task creates no canonical Bliss
  evidence manifest; fixtures and additive local JSON fields are sufficient.
- Valid blocked outcomes: cross-capture composition, stale transport, semantic invalidity, unknown overlay,
  and missing checked navigation inputs.
- Blocked-result commit policy: do not stage or commit a blocked live result; none is authorized.
- Commit policy: no staging, commit, or push was requested; no push by default.
- Expected focused commits: None because staging, commit, and push are explicitly prohibited.
- Completion criteria: dual-digest capture-event bundle with deep immutability, honest contextual
  classification, enforced navigate-building consumption, required tests/validators passing, and unchanged
  registration/scheduler state.

### RUNTIME-RESUMABLE-NAVIGATION-SESSIONS
- Task ID: `RUNTIME-RESUMABLE-NAVIGATION-SESSIONS`.
- Title: Introduce resumable, evidence-backed navigation sessions with crash-safe checkpoints.
- Status: Completed (2026-07-19; `CONFIRMED_NOT_DISPATCHED` is fail-closed and unavailable until an authenticated runtime-owned transport verifier exists; caller-minted evidence and zero movement are non-authorizing; zero live input).
- Milestone: Platform-neutral navigation-only session continuity after failed or ambiguous observation.
- Dependencies: completed `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE`, completed
  `TOOLS-HOME-ATLAS-DIRECT-PAN-PLANNER`, and completed `HOME-ATLAS-RECOVERY-AWARE-VIEWPORT-PLANNING`.
- Blocked by: None for offline implementation; live resume dispatch remains unauthorized.
- Objective: persist resumable navigation sessions so a route can stop safely after failed or ambiguous
  observation and later continue from a newly captured, positively recognized state without losing prior
  plan and displacement history, without trusting persisted tap coordinates or prior semantic bindings.
- Established facts: perception bundles bind observations to one capture event; direct-pan planner and
  navigate-building loop are authoritative for offline contracts; in-process duplicate guards are not
  crash-safe; no Train or consequential input is authorized by this task.
- Direct implementation files: `tasks/navigation_session.py`, `tests/test_navigation_session.py`, optional
  `tests/fixtures/navigation_session_evidence.json`, thin `scripts/home_atlas_bluestacks.py`
  `command_navigate_building` persistence hooks, this task contract, `CURRENT_HANDOFF.md`, and
  `tests/test_governance_validation.py`.
- Shared dependencies: `tasks/perception_bundle.py`, `tasks/home_atlas_planner.py`, and existing Home atlas
  navigate-building evidence paths; no production registration.
- Transitive regression set: perception bundle, Home atlas planner, governance validation, and focused
  navigate-building persistence coverage; full discovery when practical.
- Allowed changes: per-commit allowed paths are the direct implementation files listed above only.
- Prohibited changes: live resume CLI/dispatch, Train or consequential input, atlas rebuild, Bliss/Unraid
  production operation, workers, task rows, registration, scheduler, staging, commit, or push.
- Authorized runtime action: None; offline unit/fixture validation only.
- Maximum transport inputs: Zero for this task.
- Navigation-only recovery: offline recovery-only continuation mode is modeled; no live transport recovery
  is authorized in this task.
- Consequential action: None.
- Registration changes: None; production remains `NOT_REGISTERED`.
- Scheduler changes: None; scheduler remains disabled/ineligible.
- Actions that must not be repeated: prior Supply Depot collections, Troop Training Train inputs, atlas
  acquisition, or no-progress canonical short-drag diagnostics.
- Required source: synthetic offline capture-event identities and immutable authorization scopes; live
  frames are not required.
- Exact target semantics: versioned navigation session with progress checkpoints, orthogonal session
  outcome, crash-safe action ledger, and one logical `route_id` across corrections and continuations.
- Required local association: distinct `route_id`, `navigation_session_id`, and per-process
  `runtime_capture_session_id`; continuation requires a genuinely new capture event.
- Negative controls: persisted tap ROI dispatch, stale binding reuse, identical unreconciled prepared or
  dispatched replay, authorization partial match, illegal checkpoint regression by enum ordinal alone,
  and cross-process monotonic timestamp requirements.
- Coordinate space: platform-neutral session contracts; BlueStacks geometry remains adapter-owned.
- Accepted signals: flushed prepared-before-transport and dispatched-after-return ledger states, explicit
  cyclic multi-pan transitions gated by event and pan ordinals, complete immutable authorization scope
  match, and perception factory bundles matching `fresh_identity` via `same_capture_event`.
- Rejected weak signals: enum-rank checkpoint ordering, trusting persisted bindings, and treating prior
  frames as current without a new capture event.
- Ambiguous-result behavior: fail closed to `blocked` or `uncertain`; never advance a successful progress
  checkpoint after failed localization or progress validation; suppress identical input after uncertain
  restart.
- Zero-cost requirement: NOT_APPLICABLE because no transaction occurs.
- Quantity limits: bounded multi-pan cycles within the session maximum; unique action keys within a
  session.
- Resource consumption policy: no resource, item, AP, stamina, speedup, ticket, or currency use.
- Premium or strategic restrictions: no premium, purchase, Mall, Bank, upgrade, research, training,
  healing, or production action.
- Active evidence manifest: None; offline fixtures and additive navigate-session JSON fields are sufficient.
- Required artifacts: navigation session module, focused tests, navigate-building persistence hooks, and
  governance/handoff identity updates.
- Immediate-before/immediate-post/result/journal: NOT_APPLICABLE; zero live transport and no journal action.
- Additional task-specific artifacts: optional `tests/fixtures/navigation_session_evidence.json`.
- Focused tests: `tests.test_navigation_session`, `tests.test_perception_bundle`,
  `tests.test_home_atlas_planner`, and `tests.test_governance_validation`.
- Integration tests: offline navigate-building persistence ordering with fakes; no live BlueStacks
  validation required.
- Transitive regression tests: governance validation and focused discovery of touched modules.
- Full-suite requirement: run focused session/perception/planner/governance tests; full discovery when
  practical with no new touched-component failure.
- Validators: Python compilation, focused tests, CURRENT_HANDOFF JSON plus human-readable consistency,
  touched-file secret scan, and `git diff --check` when practical.
- Known baseline failures: None; one expected full-suite skip may remain.
- Evidence requirement: NOT_APPLICABLE because this offline contract task creates no canonical Bliss
  evidence manifest; fixtures and additive local JSON fields are sufficient.
- Valid blocked outcomes: authorization mismatch, invalid checkpoint, stale binding, duplicate unreconciled
  input, corrupt/unsupported session JSON, perception/fresh-identity mismatch, and failed localization or
  progress validation without successful checkpoint advance.
- Blocked-result commit policy: do not stage or commit a blocked live result; none is authorized.
- Commit policy: no staging, commit, or push was requested; no push by default.
- Expected focused commits: None because staging, commit, and push are explicitly prohibited.
- Completion criteria: crash-safe resumable navigation sessions with orthogonal outcomes, cyclic multi-pan
  checkpoints, hardened continuation freshness, navigate-building persistence ordering, required tests
  passing, zero transport, and unchanged registration/scheduler state.

### ARCH-NAVIGATION-AUTOMATION-ROADMAP
- Task ID: `ARCH-NAVIGATION-AUTOMATION-ROADMAP`.
- Title: Register the serial navigation automation architecture roadmap.
- Status: Completed (2026-07-19; nine dormant offline contracts registered and reviewed).
- Milestone: Durable offline navigation architecture roadmap.
- Dependencies: completed `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE`, completed
  `HOME-ATLAS-RECOVERY-AWARE-VIEWPORT-PLANNING`, and completed
  `RUNTIME-RESUMABLE-NAVIGATION-SESSIONS`.
- Blocked by: None for dormant contract registration.
- Objective: add durable dormant backlog contracts, in the authorized order, for the nine-task
  navigation automation architecture sequence while preserving `M6-DQ-TRANSITION-CORPUS` as the
  unrelated post-roadmap successor.
- Established facts: all roadmap work is offline; recognition, actionability, and authorization remain
  distinct; projection never authorizes input; BlueStacks and Bliss ownership remain separate.
- Direct implementation files: `BACKLOG.md`, `CURRENT_HANDOFF.md`, and task-identity governance
  coverage only when required to keep the durable state contract valid.
- Shared dependencies: the three completed architecture tasks named above and existing repository
  governance validation.
- Transitive regression set: governance validation and CURRENT_HANDOFF structured-state parsing.
- Allowed changes: per-commit allowed paths are `BACKLOG.md`, `CURRENT_HANDOFF.md`, and
  `tests/test_governance_validation.py` only; implementation, fixture, runtime, registration,
  scheduler, worker, and task-row files are forbidden.
- Prohibited changes: implementation of any roadmap task, runtime input, evidence acquisition,
  protected evidence or `.local-captures` inspection, production registration, scheduler eligibility,
  worker/task-row changes, push, or unrelated backlog reordering/status changes.
- Authorized runtime action: None; offline documentation and governance only.
- Maximum transport inputs: Zero.
- Navigation-only recovery: NOT_APPLICABLE; no runtime input is authorized.
- Consequential action: None.
- Registration changes: None; production remains `NOT_REGISTERED`.
- Scheduler changes: None; scheduler remains disabled/ineligible.
- Actions that must not be repeated: any prior live runtime action, atlas acquisition, facility input,
  radial input, or consequential input.
- Required source: this authorized roadmap prompt and the completed direct dependency contracts.
- Exact target semantics: nine ordered dormant atomic contracts with explicit dependencies, allowed
  paths, focused tests, blockers, completion criteria, and `M6-DQ-TRANSITION-CORPUS` after the roadmap.
- Required local association: NOT_APPLICABLE; no visual target or frame is used.
- Negative controls: reordered tasks, activated implementation, broad framework creation, registration
  or scheduler promotion, and displacement of the unrelated post-roadmap successor.
- Coordinate space: NOT_APPLICABLE.
- Accepted signals: exact ordered task IDs and explicit durable contract fields.
- Rejected weak signals: prose-only plans, implicit dependencies, unspecified allowed paths, or
  implementation hidden in the setup commit.
- Ambiguous-result behavior: fail closed and stop before activating the first implementation task.
- Zero-cost requirement: NOT_APPLICABLE because no transaction occurs.
- Quantity limits: exactly nine dormant roadmap contracts plus this setup contract.
- Resource consumption policy: no game resources or runtime input.
- Premium or strategic restrictions: no gameplay or production operation.
- Active evidence manifest: None; offline contracts only.
- Required artifacts: this setup contract, nine dormant roadmap contracts, and synchronized handoff.
- Immediate-before/immediate-post/result/journal: NOT_APPLICABLE.
- Additional task-specific artifacts: None.
- Focused tests: governance validation and CURRENT_HANDOFF structured-state parsing.
- Integration tests: NOT_APPLICABLE.
- Transitive regression tests: `tests.test_governance_validation` when identity coverage changes.
- Full-suite requirement: not required for documentation-only setup if focused governance passes.
- Validators: governance validation, CURRENT_HANDOFF JSON parsing, touched-file secret scan, and
  `git diff --check`.
- Known baseline failures: None; one expected full-suite skip may remain.
- Evidence requirement: NOT_APPLICABLE because this setup task registers dormant offline contracts only.
- Valid blocked outcomes: missing required contract field, ambiguous ownership, unsafe allowed path, or
  successor-order conflict.
- Blocked-result commit policy: record the blocker and do not activate an implementation task.
- Commit policy: one reviewed conventional local commit; no push.
- Expected focused commits: `docs(roadmap): register navigation architecture sequence`; allowed paths
  are the setup task's allowed paths above.
- Completion criteria: all nine contracts are durable, dormant, ordered, dependency-complete, path- and
  test-bounded, explicitly offline, preserve registration/scheduler disablement, and leave
  `VISION-SEMANTIC-OCR-CROP-PIPELINE` as the next eligible task with
  `M6-DQ-TRANSITION-CORPUS` preserved after the roadmap.
- Next: `VISION-SEMANTIC-OCR-CROP-PIPELINE`.


### VISION-SEMANTIC-OCR-CROP-PIPELINE
- Task ID: `VISION-SEMANTIC-OCR-CROP-PIPELINE`.
- Title: Shared frame-identity-bound semantic OCR crop pipeline.
- Status: Completed (2026-07-19; identity-bound crop pipeline and one Supply Depot adoption reviewed; zero runtime input).
- Milestone: Durable offline navigation architecture roadmap.
- Dependencies: `ARCH-NAVIGATION-AUTOMATION-ROADMAP` and completed
  `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE`.
- Blocked by: readiness requires the roadmap setup task completed and perception-bundle contracts
  unchanged; no live frames, runtime, registration, or scheduler work may start this task.
- Objective: add one shared OCR crop pipeline that binds every observation to a single native-frame
  capture identity, with controlled ROI/padding, exclusion masks, bounded normalization, constrained
  OCR modes, immutable observations, negative controls, and opt-in deterministic debug artifacts.
- Established facts: `FramePerceptionBundle` already owns same-capture composition and dual digests;
  adapter-local OCR crops exist but are not a shared identity-bound pipeline; recognition remains
  distinct from authorization and projection never authorizes input.
- Direct implementation files: `tasks/semantic_ocr_crop.py`, `tests/test_semantic_ocr_crop.py`,
  optional exact `tests/fixtures/semantic_ocr_crop_evidence.json`, representative adapter
  `tasks/supply_depot_vision.py`, representative regression `tests/test_supply_depot_vision.py`,
  `BACKLOG.md`, `CURRENT_HANDOFF.md`, and `tests/test_governance_validation.py` only if durable
  identity coverage changes.
- Shared dependencies: `tasks/perception_bundle.py` capture-event identity and immutable observation
  snapshots; no production registration.
- Transitive regression set: perception bundle, the single adopted adapter's focused tests, and
  governance validation.
- Allowed changes: per-commit allowed paths are exactly `tasks/semantic_ocr_crop.py`,
  `tests/test_semantic_ocr_crop.py`, optional `tests/fixtures/semantic_ocr_crop_evidence.json`,
  `tasks/supply_depot_vision.py`, `tests/test_supply_depot_vision.py`, `BACKLOG.md`,
  `CURRENT_HANDOFF.md`, and `tests/test_governance_validation.py` only if identity coverage changes.
- Prohibited changes: screen classifiers, unconstrained fuzzy matching, multi-adapter rewrites, live
  BlueStacks/ADB/Bliss/Unraid input, evidence acquisition, protected evidence or `.local-captures`
  mutation, registration, scheduler, workers, task rows, push, or unrelated backlog reordering.
- Authorized runtime action: None; offline unit/fixture validation only.
- Maximum transport inputs: Zero.
- Navigation-only recovery: NOT_APPLICABLE; no runtime input is authorized.
- Consequential action: None.
- Registration changes: None; production remains `NOT_REGISTERED`.
- Scheduler changes: None; scheduler remains disabled/ineligible.
- Actions that must not be repeated: any prior live facility, radial, collection, Train, Claim, or
  atlas-acquisition input.
- Required source: synthetic offline native-frame identities and immutable parent-frame digests;
  live captures are not required and fixture identities must never masquerade as live captures.
- Exact target semantics: ROI request with explicit padding and exclusion masks; bounded
  normalization only; constrained OCR mode enumeration; immutable OCR observation carrying complete
  `NativeFrameIdentity` / capture-event fields; opt-in deterministic debug crop artifacts.
- Required local association: every crop and OCR observation must share the parent frame's capture
  event, transport digest, and semantic digest; cross-capture composition is rejected.
- Negative controls: unconstrained fuzzy string matching, screen/classifier authority, mutable crop
  buffers retained as observations, padding that escapes declared exclusion masks, and debug artifacts
  enabled by default.
- Coordinate space: parent native full-frame coordinates only; no scaled-preview or vendor coordinates.
- Accepted signals: same-capture identity match, explicit ROI/padding/mask provenance, constrained mode,
  immutable observation snapshot, and deterministic opt-in debug hashes.
- Rejected weak signals: free-text fuzzy match, classifier labels as OCR proof, preview crops, and
  digest-only equality without capture-event identity.
- Ambiguous-result behavior: fail closed to invalid/unknown observation; never invent text or authorize
  transport from OCR alone.
- Zero-cost requirement: NOT_APPLICABLE because no transaction occurs.
- Quantity limits: one shared pipeline module and exactly one representative adapter adoption.
- Resource consumption policy: no game resources or runtime input.
- Premium or strategic restrictions: no gameplay, premium, purchase, or consequential control.
- Active evidence manifest: None; offline fixtures only.
- Required artifacts: shared pipeline module, focused tests, optional exact
  `tests/fixtures/semantic_ocr_crop_evidence.json`, and one Supply Depot vision adapter adoption with
  unchanged registration/scheduler state.
- Immediate-before/immediate-post/result/journal: NOT_APPLICABLE.
- Additional task-specific artifacts: optional deterministic debug crops only as temporary test
  output when explicitly enabled; debug crops are not committed.
- Focused tests: `tests.test_semantic_ocr_crop`, `tests.test_perception_bundle`, and
  `tests.test_supply_depot_vision`.
- Integration tests: offline same-capture composition with the perception bundle; no live validation.
- Transitive regression tests: governance validation and focused discovery of touched modules.
- Full-suite requirement: run focused tests first, then touched-component regressions, then the full
  repository suite when practical; if the full suite cannot run, explicitly record why and the last
  authoritative result rather than silently waiving it.
- Validators: Python compilation, focused tests, governance validation, CURRENT_HANDOFF JSON parsing,
  JSON parsing/hash validation for the optional evidence fixture and deterministic debug artifacts
  when created, touched-file secret scan, and `git diff --check`.
- Known baseline failures: None; one expected full-suite skip may remain.
- Evidence requirement: NOT_APPLICABLE because this dormant offline contract creates no runtime
  evidence manifest.
- Valid blocked outcomes: cross-capture crop, mask/padding escape, unconstrained OCR mode, missing
  frame identity, or adapter scope creep beyond one representative consumer.
- Blocked-result commit policy: record the blocker; do not stage blocked live results; none are
  authorized.
- Commit policy: one reviewed conventional local commit; no push.
- Expected focused commits: `feat(vision): add identity-bound OCR crop pipeline`; allowed paths are
  the direct implementation files above.
- Completion criteria: shared identity-bound OCR crop pipeline landed with immutable observations,
  negative controls, one adapter only, required tests/validators passing, zero runtime input, and
  unchanged registration/scheduler state.
- Next: `VISION-NATIVE-FRAME-REPLAY-HARNESS`.

### VISION-NATIVE-FRAME-REPLAY-HARNESS
- Task ID: `VISION-NATIVE-FRAME-REPLAY-HARNESS`.
- Title: Deterministic offline native-frame replay harness over project-owned fixtures.
- Status: Completed (2026-07-19; deterministic two-source offline replay reviewed; zero runtime input).
- Milestone: Durable offline navigation architecture roadmap.
- Dependencies: `VISION-SEMANTIC-OCR-CROP-PIPELINE` and completed
  `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE`.
- Blocked by: None for offline implementation. The completed OCR crop pipeline is available, and the
  two exact existing project-owned native-frame sources named below are read-only; no frame source may
  be added under this contract, and no bulk evidence copy or live capture acquisition is authorized.
- Objective: provide deterministic offline replay over narrowly selected project-owned native-frame
  fixtures so perception and OCR contracts can be exercised without runtime input.
- Established facts: perception bundles and OCR crops bind to capture identities; live captures and
  protected evidence are not replay fixtures; fixture identities must remain explicitly non-live.
- Direct implementation files: `tasks/native_frame_replay.py`, `tests/test_native_frame_replay.py`,
  exact manifest `tests/fixtures/native_frame_replay_manifest.json`, `BACKLOG.md`,
  `CURRENT_HANDOFF.md`, and `tests/test_governance_validation.py` only if durable identity coverage
  changes. Any selected existing project-owned native-frame source is read-only and must be named
  explicitly during activation before implementation.
- Shared dependencies: `tasks/perception_bundle.py` and `tasks/semantic_ocr_crop.py`; no production
  registration.
- Transitive regression set: perception bundle, semantic OCR crop, and governance validation.
- Allowed changes: per-commit allowed paths are exactly `tasks/native_frame_replay.py`,
  `tests/test_native_frame_replay.py`, `tests/fixtures/native_frame_replay_manifest.json`,
  `BACKLOG.md`, `CURRENT_HANDOFF.md`, and `tests/test_governance_validation.py` only if identity
  coverage changes; no native-frame source path is writable under this task.
- Prohibited changes: mutation testing, bulk evidence or `.local-captures` copy, treating fixtures as
  live captures, runtime input, registration, scheduler, workers, task rows, push, or unrelated
  backlog changes.
- Authorized runtime action: None; offline fixture replay only.
- Maximum transport inputs: Zero.
- Navigation-only recovery: NOT_APPLICABLE; no runtime input is authorized.
- Consequential action: None.
- Registration changes: None; production remains `NOT_REGISTERED`.
- Scheduler changes: None; scheduler remains disabled/ineligible.
- Actions that must not be repeated: any prior live gameplay or atlas-acquisition input.
- Required source: read-only
  `tasks/assets/home_atlas/bluestacks/800x1280/tiles/viewport-001.png` and
  `tasks/assets/navigation/800x1280/daily_praise_claim.png`, each with explicit fixture capture-kind /
  non-live identity; never copy these files or protected evidence trees.
- Exact target semantics: deterministic ordered replay of fixture frames through perception and OCR
  seams; fixture identity fields must refuse live-capture masquerading.
- Required local association: each replayed observation retains fixture identity, digests, and
  ordinal; live-capture labels are forbidden on fixture records.
- Negative controls: bulk evidence import, mutation corpus features, silent live-labeling of fixtures,
  and non-deterministic ordering.
- Coordinate space: native fixture full-frame coordinates only.
- Accepted signals: stable fixture manifest hashes, deterministic observation order, and explicit
  non-live capture-kind.
- Rejected weak signals: path-only identity, evidence-tree traversal, and timestamps treated as live
  freshness.
- Ambiguous-result behavior: fail closed; skip or reject the fixture rather than inventing identity.
- Zero-cost requirement: NOT_APPLICABLE because no transaction occurs.
- Quantity limits: exactly the two named read-only native-frame sources; no bulk corpus expansion.
- Resource consumption policy: no game resources or runtime input.
- Premium or strategic restrictions: no gameplay or consequential control.
- Active evidence manifest: None; offline fixtures only.
- Required artifacts: replay harness module, focused tests, and exact
  `tests/fixtures/native_frame_replay_manifest.json` naming the read-only native-frame sources and
  their non-live identity rules.
- Immediate-before/immediate-post/result/journal: NOT_APPLICABLE.
- Additional task-specific artifacts: no committed frame directory or wildcard fixture tree; selected
  existing project-owned native-frame sources remain read-only and are referenced by the exact
  manifest.
- Focused tests: `tests.test_native_frame_replay`, `tests.test_semantic_ocr_crop`, and
  `tests.test_perception_bundle`.
- Integration tests: offline replay through OCR crop and perception bundle seams; no live validation.
- Transitive regression tests: governance validation and focused discovery of touched modules.
- Full-suite requirement: run focused tests first, then touched-component regressions, then the full
  repository suite when practical; if the full suite cannot run, explicitly record why and the last
  authoritative result rather than silently waiving it.
- Validators: Python compilation, focused tests, governance validation, CURRENT_HANDOFF JSON parsing,
  exact replay-manifest JSON parsing and source hash checks, touched-file secret scan, and
  `git diff --check`.
- Known baseline failures: None; one expected full-suite skip may remain.
- Evidence requirement: NOT_APPLICABLE because this dormant offline harness creates no runtime
  evidence manifest.
- Valid blocked outcomes: missing non-live fixture identity, bulk evidence copy pressure, or any
  request for live capture.
- Blocked-result commit policy: record the blocker; do not import protected evidence.
- Commit policy: one reviewed conventional local commit; no push.
- Expected focused commits: `feat(vision): add native-frame replay harness`; allowed paths are the
  direct implementation files above.
- Completion criteria: deterministic offline replay harness over narrow non-live fixtures passes
  required tests/validators with zero runtime input and unchanged registration/scheduler state.
- Next: `HOME-SHARED-RADIAL-SEMANTIC-CONTRACT`.

### HOME-SHARED-RADIAL-SEMANTIC-CONTRACT
- Task ID: `HOME-SHARED-RADIAL-SEMANTIC-CONTRACT`.
- Title: Platform-neutral shared Home radial semantic contract.
- Status: Completed (2026-07-19; reviewed offline platform-neutral radial semantics; zero transport).
- Milestone: Durable offline navigation architecture roadmap.
- Dependencies: `VISION-NATIVE-FRAME-REPLAY-HARNESS` and completed
  `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE`.
- Blocked by: readiness requires replay harness and perception-bundle radial observation seams;
  BlueStacks coordinates/transport and live radial taps remain unauthorized.
- Objective: define platform-neutral radial semantics for owning-facility identity, same-capture
  association, controls, confidence, actionability, and expected/forbidden successors while keeping
  recognition distinct from authorization.
- Established facts: perception bundles already reserve an immutable radial observation slot;
  adapter-specific radial OCR exists for Supply Depot and related routes; projection and recognition
  do not authorize taps.
- Direct implementation files: `tasks/radial_semantics.py`, `tests/test_radial_semantics.py`,
  optional exact `tests/fixtures/radial_semantics_evidence.json`, narrowly scoped typed adoption in
  `tasks/perception_bundle.py` and `tests/test_perception_bundle.py`, `BACKLOG.md`,
  `CURRENT_HANDOFF.md`, and `tests/test_governance_validation.py` only if durable identity coverage
  changes.
- Shared dependencies: `tasks/perception_bundle.py`, OCR crop pipeline, and native-frame replay;
  no production registration.
- Transitive regression set: perception bundle, semantic OCR crop, native-frame replay, and
  governance validation.
- Allowed changes: per-commit allowed paths are exactly `tasks/radial_semantics.py`,
  `tests/test_radial_semantics.py`, optional `tests/fixtures/radial_semantics_evidence.json`,
  `tasks/perception_bundle.py`, `tests/test_perception_bundle.py`, `BACKLOG.md`,
  `CURRENT_HANDOFF.md`, and `tests/test_governance_validation.py` only if identity coverage changes.
- Prohibited changes: BlueStacks coordinates or transport, live radial taps, consequential control
  authorization, registration, scheduler, workers, task rows, push, or Bliss coordinate reuse.
- Authorized runtime action: None; offline contract/tests only.
- Maximum transport inputs: Zero.
- Navigation-only recovery: NOT_APPLICABLE; no runtime input is authorized.
- Consequential action: None; recognition never authorizes consequential dispatch.
- Registration changes: None; production remains `NOT_REGISTERED`.
- Scheduler changes: None; scheduler remains disabled/ineligible.
- Actions that must not be repeated: any prior live radial Train/Claim Supply/Upgrade or exterior-close
  input.
- Required source: offline same-capture radial observations from fixtures/replay; live frames are not
  required.
- Exact target semantics: owning-facility identity; same-capture association; control inventory with
  confidence and actionability; expected and forbidden successors; explicit recognition-versus-
  authorization separation.
- Required local association: radial observation must share the parent capture event with facility
  binding and OCR evidence; cross-capture radial/facility joins are rejected.
- Negative controls: treating recognition as dispatch authority, BlueStacks pixel hardcoding in the
  shared contract, successor inference from transport success, and missing forbidden-successor sets.
- Coordinate space: platform-neutral semantic contract; adapter geometry remains adapter-owned and
  forbidden for Bliss reuse.
- Accepted signals: same-capture facility+radial association, explicit control confidence/actionability,
  and declared expected/forbidden successors.
- Rejected weak signals: coordinate-only radial proof, transport OK, and classifier-only facility
  labels without same-capture evidence.
- Ambiguous-result behavior: fail closed to non-actionable/unknown radial; never authorize input.
- Zero-cost requirement: NOT_APPLICABLE because no transaction occurs.
- Quantity limits: shared semantic contract only; no multi-route live binding campaign.
- Resource consumption policy: no game resources or runtime input.
- Premium or strategic restrictions: no premium, purchase, Train, Upgrade, or collection authorization.
- Active evidence manifest: None; offline fixtures only.
- Required artifacts: radial semantic module, focused tests, and perception-bundle typed adoption as
  needed without transport hooks.
- Immediate-before/immediate-post/result/journal: NOT_APPLICABLE.
- Additional task-specific artifacts: optional exact
  `tests/fixtures/radial_semantics_evidence.json` demonstrating expected/forbidden successors.
- Focused tests: `tests.test_radial_semantics`, `tests.test_perception_bundle`, and
  `tests.test_native_frame_replay`.
- Integration tests: offline same-capture radial composition; no live BlueStacks validation.
- Transitive regression tests: governance validation and focused discovery of touched modules.
- Full-suite requirement: run focused tests first, then touched-component regressions, then the full
  repository suite when practical; if the full suite cannot run, explicitly record why and the last
  authoritative result rather than silently waiving it.
- Validators: Python compilation, focused tests, governance validation, CURRENT_HANDOFF JSON parsing,
  JSON parsing/hash validation for `tests/fixtures/radial_semantics_evidence.json` when created,
  touched-file secret scan, and `git diff --check`.
- Known baseline failures: None; one expected full-suite skip may remain.
- Evidence requirement: NOT_APPLICABLE because this dormant offline contract creates no runtime
  evidence manifest.
- Valid blocked outcomes: recognition/authorization conflation, BlueStacks transport leakage into the
  shared contract, or cross-capture radial association.
- Blocked-result commit policy: record the blocker; do not authorize live radial input.
- Commit policy: one reviewed conventional local commit; no push.
- Expected focused commits: `feat(home): add shared radial semantic contract`; allowed paths are the
  direct implementation files above.
- Completion criteria: platform-neutral radial semantics with same-capture association,
  actionability, successor rules, recognition/authorization separation, required tests passing, zero
  transport, and unchanged registration/scheduler state.
- Next: `BLUESTACKS-HOME-SAFE-EXIT-BINDING`.

### BLUESTACKS-HOME-SAFE-EXIT-BINDING
- Task ID: `BLUESTACKS-HOME-SAFE-EXIT-BINDING`.
- Title: Reusable BlueStacks-only current-frame Home safe-exit binder.
- Status: Completed (2026-07-19; reviewed offline BlueStacks-only safe-exit binder; zero transport).
- Milestone: Durable offline navigation architecture roadmap.
- Dependencies: `HOME-SHARED-RADIAL-SEMANTIC-CONTRACT` and completed
  `HOME-ATLAS-RECOVERY-AWARE-VIEWPORT-PLANNING`.
- Blocked by: readiness requires shared radial semantics and recovery-aware planner honesty fields;
  live validation, Bliss binding, and tap authorization from projection remain unauthorized.
- Objective: implement a reusable BlueStacks-only current-frame safe-exit binder that excludes HUD,
  buildings, radial controls, semantic targets, and known interactive regions, requires complete
  target-box clearance, and treats projection as a search envelope never as tap authorization.
- Established facts: recovery-aware planner already exposes predicted recovery search zones as non-
  executable; BlueStacks safe-region/radial-close contracts are adapter-owned; Bliss remains separate.
- Direct implementation files: `tasks/bluestacks_home_safe_exit.py`,
  `scripts/home_atlas_bluestacks.py`, `tests/test_bluestacks_home_safe_exit.py`,
  `tasks/home_atlas_planner.py`, `tests/test_home_atlas_planner.py`, `BACKLOG.md`,
  `CURRENT_HANDOFF.md`, and `tests/test_governance_validation.py` only if durable identity coverage
  changes.
- Shared dependencies: radial semantics, Home atlas planner safe-region contracts, and perception
  bundles; no production registration.
- Transitive regression set: Home atlas planner, radial semantics, perception bundle, and governance.
- Allowed changes: per-commit allowed paths are exactly `tasks/bluestacks_home_safe_exit.py`,
  `scripts/home_atlas_bluestacks.py`, `tests/test_bluestacks_home_safe_exit.py`,
  `tasks/home_atlas_planner.py`, `tests/test_home_atlas_planner.py`, `BACKLOG.md`,
  `CURRENT_HANDOFF.md`, and `tests/test_governance_validation.py` only if identity coverage changes.
- Prohibited changes: live validation/dispatch, Bliss coordinate reuse, authorizing taps from
  projection, treating search envelopes as executable coordinates, registration, scheduler, workers,
  task rows, or push.
- Authorized runtime action: None; offline unit/fixture validation only.
- Maximum transport inputs: Zero.
- Navigation-only recovery: offline binder may model recovery search envelopes only; no live recovery
  transport is authorized.
- Consequential action: None.
- Registration changes: None; production remains `NOT_REGISTERED`.
- Scheduler changes: None; scheduler remains disabled/ineligible.
- Actions that must not be repeated: prior live exterior-close taps, facility taps, or no-progress
  canonical short-drag diagnostics.
- Required source: offline current-frame fixture identities for BlueStacks Home only; Bliss frames are
  out of scope.
- Exact target semantics: candidate safe-exit region with complete clearance from HUD, buildings,
  radial controls, semantic targets, and known interactive regions; projection supplies search
  envelope only.
- Required local association: binder output must cite the current-frame capture identity and excluded
  region set; stale or cross-capture envelopes are rejected.
- Negative controls: executable coordinates from projection alone, incomplete target-box clearance,
  HUD/building/radial overlap acceptance, and Bliss profile reuse.
- Coordinate space: BlueStacks native 800x1280 adapter space only; Bliss remains independent.
- Accepted signals: complete clearance against declared exclusions, current-frame identity match, and
  explicit non-authorizing search-envelope provenance.
- Rejected weak signals: atlas polygon alone, predicted recovery zone as tap proof, and transport
  success.
- Ambiguous-result behavior: fail closed to unavailable safe-exit; never emit an authorizing tap ROI.
- Zero-cost requirement: NOT_APPLICABLE because no transaction occurs.
- Quantity limits: BlueStacks Home binder only; no multi-platform generalization in this task.
- Resource consumption policy: no game resources or runtime input.
- Premium or strategic restrictions: no consequential controls.
- Active evidence manifest: None; offline fixtures only.
- Required artifacts: BlueStacks safe-exit binder, focused tests, and honesty fields proving
  projection is non-authorizing.
- Immediate-before/immediate-post/result/journal: NOT_APPLICABLE.
- Additional task-specific artifacts: exclusion-clearance overlays may be temporary test output only;
  no fixture overlay path is writable or committed.
- Focused tests: `tests.test_bluestacks_home_safe_exit`, `tests.test_home_atlas_planner`, and
  `tests.test_radial_semantics`.
- Integration tests: offline binder-plus-planner honesty checks; no live BlueStacks validation.
- Transitive regression tests: governance validation and focused discovery of touched modules.
- Full-suite requirement: run focused tests first, then touched-component regressions, then the full
  repository suite when practical; if the full suite cannot run, explicitly record why and the last
  authoritative result rather than silently waiving it.
- Validators: Python compilation, focused tests, governance validation, CURRENT_HANDOFF JSON parsing,
  JSON parsing for any touched planner/debug JSON artifact, touched-file secret scan, and
  `git diff --check`.
- Known baseline failures: None; one expected full-suite skip may remain.
- Evidence requirement: NOT_APPLICABLE because this dormant offline binder creates no runtime
  evidence manifest.
- Valid blocked outcomes: incomplete clearance, projection-as-authorization, Bliss leakage, or live
  validation pressure.
- Blocked-result commit policy: record the blocker; do not dispatch safe-exit input.
- Commit policy: one reviewed conventional local commit; no push.
- Expected focused commits: `feat(bluestacks): add home safe-exit binder`; allowed paths are the
  direct implementation files above.
- Completion criteria: reusable BlueStacks current-frame safe-exit binder with complete exclusion
  clearance, non-authorizing projection envelopes, required tests passing, zero transport, Bliss
  separate, and unchanged registration/scheduler state.
- Next: `RUNTIME-INPUT-CAPABILITY-FIREWALL`.

### RUNTIME-INPUT-CAPABILITY-FIREWALL
- Task ID: `RUNTIME-INPUT-CAPABILITY-FIREWALL`.
- Title: Extend safe_action_core with navigation-versus-consequential capability firewall.
- Status: Complete (2026-07-19; parent review and full offline validation passed; zero runtime).
- Milestone: Durable offline navigation architecture roadmap.
- Dependencies: `BLUESTACKS-HOME-SAFE-EXIT-BINDING` and completed `M7-SAFE-ACTION-CORE`.
- Blocked by: readiness requires safe-exit binder semantics and the existing central policy/executor
  boundary; a parallel executor is forbidden; live consequential dispatch remains unauthorized by this
  task alone.
- Objective: extend the existing `safe_action_core` policy/executor boundary so navigation-only
  capabilities cannot dispatch consequential controls, dry-run issues no input, authority is bound to
  task/session/action/target, capabilities are non-serializable/non-reusable, final dispatch
  revalidates semantic identity and coordinates, and allowed/rejected attempts are audited without
  conflating dispatch authorization with conclusive non-dispatch transport verification.
- Established facts: `CentralPolicy` and the exclusive executor already gate supervised input;
  navigation-only and consequential action classes are distinct; `CONFIRMED_NOT_DISPATCHED` remains
  fail-closed until an authenticated runtime-owned transport verifier exists.
- Direct implementation files: `safe_action_core/policy.py`, `safe_action_core/executor.py`,
  `safe_action_core/models.py` only if the capability type is required, `safe_action_core/__init__.py`
  only for export, `tests/test_input_capability_firewall.py`, `tests/test_safe_action_core.py`,
  `tests/test_pre_dispatch_freshness.py`, `tests/test_navigation_runner.py`, `BACKLOG.md`,
  `CURRENT_HANDOFF.md`, and `tests/test_governance_validation.py` only if durable identity coverage
  changes.
- Shared dependencies: existing `safe_action_core` models/store, navigation session authority scopes,
  and safe-exit binder outputs as non-authorizing inputs; no production registration.
- Transitive regression set: safe_action_core policy/executor tests, navigation runner tests, and
  governance validation.
- Allowed changes: per-commit allowed paths are exactly `safe_action_core/policy.py`,
  `safe_action_core/executor.py`, `safe_action_core/models.py` only when the capability type is
  required, `safe_action_core/__init__.py` only for export,
  `tests/test_input_capability_firewall.py`, `tests/test_safe_action_core.py`,
  `tests/test_pre_dispatch_freshness.py`, `tests/test_navigation_runner.py`, `BACKLOG.md`,
  `CURRENT_HANDOFF.md`, and `tests/test_governance_validation.py` only if identity coverage changes.
- Prohibited changes: parallel executor, enabling `CONFIRMED_NOT_DISPATCHED` without authenticated
  verifier, serializable reusable capabilities, live consequential broadening, registration,
  scheduler, workers, task rows, or push.
- Authorized runtime action: None required; offline mocked policy/executor tests only.
- Maximum transport inputs: Zero for this task.
- Navigation-only recovery: navigation-only capabilities may authorize navigation-class intents only;
  consequential controls remain excluded.
- Consequential action: None newly authorized; existing consequential paths stay explicitly gated and
  unchanged in promotion posture.
- Registration changes: None; production remains `NOT_REGISTERED`.
- Scheduler changes: None; scheduler remains disabled/ineligible.
- Actions that must not be repeated: any prior confirmed consequential action keys or unresolved
  identical retries.
- Required source: offline PolicyRequest/Observation fixtures with explicit task/session/action/target
  authority bindings.
- Exact target semantics: capability tokens bound to task, session, action class, and target identity;
  dry-run path guarantees zero input; final dispatch validates semantic identity and coordinates;
  audits record allowed and rejected attempts; dispatch authorization is not treated as conclusive
  non-dispatch transport verification.
- Required local association: capability, target ROI/identity, and observation capture event must
  match at final dispatch; stale or partial authority matches fail closed.
- Negative controls: navigation capability dispatching consequential controls, dry-run transport,
  capability serialization/reuse across sessions, and treating policy allow as proof that transport
  did not occur.
- Coordinate space: existing safe_action_core fixed-profile coordinates; no vendor coordinates.
- Accepted signals: authority-complete capability evaluation, audited allow/reject decisions, dry-run
  zero-input proof, and final semantic+coordinate revalidation.
- Rejected weak signals: transport OK alone, serialized capability replay, and partial authority
  match.
- Ambiguous-result behavior: fail closed to deny/unresolved; never issue identical retries.
- Zero-cost requirement: preserve existing zero-cost supervised gates; this task adds no new paid
  consequences.
- Quantity limits: extend the single executor only; no second execution engine.
- Resource consumption policy: no game resources consumed by this offline task.
- Premium or strategic restrictions: no premium/purchase/strategic broadening.
- Active evidence manifest: None; offline tests only.
- Required artifacts: capability firewall against the existing policy/executor, focused tests, and
  audit coverage for allow/reject paths.
- Immediate-before/immediate-post/result/journal: NOT_APPLICABLE for live journals; offline store
  fakes only.
- Additional task-specific artifacts: none beyond focused tests.
- Focused tests: `tests.test_input_capability_firewall`, `tests.test_safe_action_core`,
  `tests.test_pre_dispatch_freshness`, and `tests.test_navigation_runner`.
- Integration tests: offline policy/executor dry-run and rejection paths; no live runtime.
- Transitive regression tests: governance validation and focused discovery of touched modules.
- Full-suite requirement: run focused tests first, then touched-component regressions, then the full
  repository suite when practical; if the full suite cannot run, explicitly record why and the last
  authoritative result rather than silently waiving it.
- Validators: Python compilation, focused tests, governance validation, CURRENT_HANDOFF JSON parsing,
  JSON parsing for any touched audit fixture/output, touched-file secret scan, and `git diff --check`.
- Known baseline failures: None; one expected full-suite skip may remain.
- Evidence requirement: NOT_APPLICABLE because this dormant offline firewall creates no runtime
  evidence manifest.
- Valid blocked outcomes: parallel executor pressure, capability reuse, navigation/consequential
  conflation, or conflating authorization with non-dispatch transport verification.
- Blocked-result commit policy: record the blocker; do not enable unsafe verification shortcuts.
- Commit policy: one reviewed conventional local commit; no push.
- Expected focused commits: `feat(runtime): add input capability firewall`; allowed paths are the
  direct implementation files above.
- Completion criteria: existing policy/executor enforces navigation-versus-consequential firewall,
  dry-run zero-input, non-reusable authority-bound capabilities, audited decisions, required tests
  passing, zero live input, and unchanged registration/scheduler state.
- Next: `VISION-NATIVE-FRAME-MUTATION-CORPUS`.

### VISION-NATIVE-FRAME-MUTATION-CORPUS
- Task ID: `VISION-NATIVE-FRAME-MUTATION-CORPUS`.
- Title: Controlled native-frame mutation corpus for offline false-accept/false-reject measurement.
- Status: Complete (2026-07-19; parent review and full offline validation passed; zero runtime).
- Milestone: Durable offline navigation architecture roadmap.
- Dependencies: `RUNTIME-INPUT-CAPABILITY-FIREWALL` and `VISION-NATIVE-FRAME-REPLAY-HARNESS`.
- Blocked by: readiness requires the replay harness and capability firewall; mutations must remain
  distinct from retained native evidence; no live capture acquisition is authorized.
- Objective: add realistic controlled replay mutations—brightness, contrast, bounded compression,
  small translation, partial occlusion, distractor text, crop truncation, and stale-frame
  substitution—while measuring false acceptance separately from false rejection.
- Established facts: replay harness consumes non-live fixtures; perception/OCR contracts fail closed
  on identity mismatch; retained evidence must not be overwritten by mutations.
- Direct implementation files: `tasks/native_frame_mutation.py`,
  `tests/test_native_frame_mutation.py`, exact manifest
  `tests/fixtures/native_frame_mutation_manifest.json`, `BACKLOG.md`, `CURRENT_HANDOFF.md`, and
  `tests/test_governance_validation.py` only if durable identity coverage changes. Generated
  mutations are temporary test output and are not committed.
- Shared dependencies: native-frame replay, semantic OCR crop, perception bundle, and capability
  firewall negative-control expectations; no production registration.
- Transitive regression set: native-frame replay, semantic OCR crop, perception bundle, and
  governance validation.
- Allowed changes: per-commit allowed paths are exactly `tasks/native_frame_mutation.py`,
  `tests/test_native_frame_mutation.py`, `tests/fixtures/native_frame_mutation_manifest.json`,
  `BACKLOG.md`, `CURRENT_HANDOFF.md`, and `tests/test_governance_validation.py` only if identity
  coverage changes; generated mutation images may exist only in temporary test output.
- Prohibited changes: mutating retained evidence or `.local-captures`, bulk evidence copy, live
  capture, registration, scheduler, workers, task rows, or push.
- Authorized runtime action: None; offline mutation/replay only.
- Maximum transport inputs: Zero.
- Navigation-only recovery: NOT_APPLICABLE; no runtime input is authorized.
- Consequential action: None.
- Registration changes: None; production remains `NOT_REGISTERED`.
- Scheduler changes: None; scheduler remains disabled/ineligible.
- Actions that must not be repeated: any prior live gameplay input.
- Required source: project-owned replay fixtures only; mutated derivatives must carry distinct
  mutation identity and must not replace retained native evidence.
- Exact target semantics: enumerated mutation operators above; separate false-accept and false-reject
  metrics; stale-frame substitution must fail closed on capture identity.
- Required local association: each mutated frame declares parent fixture identity, operator, and
  non-evidence storage path; parent retained evidence paths are immutable.
- Negative controls: writing mutations into `evidence/**`, treating mutated frames as live, and
  combining false-accept with false-reject into one undifferentiated score.
- Coordinate space: native fixture coordinates with declared translation bounds only.
- Accepted signals: deterministic operator application, distinct mutation identity, and separated
  false-accept/false-reject reporting.
- Rejected weak signals: random unbounded augmentation, evidence overwrites, and single blended error
  rate hiding false accepts.
- Ambiguous-result behavior: fail closed; count unresolved/ambiguous separately from false accept.
- Zero-cost requirement: NOT_APPLICABLE because no transaction occurs.
- Quantity limits: controlled operator set listed in the objective only; no open-ended augmentation
  zoo.
- Resource consumption policy: no game resources or runtime input.
- Premium or strategic restrictions: no gameplay or consequential control.
- Active evidence manifest: None; offline fixtures only.
- Required artifacts: mutation module, focused tests, exact
  `tests/fixtures/native_frame_mutation_manifest.json`, temporary generated mutation output distinct
  from retained evidence, and separated metric reporting.
- Immediate-before/immediate-post/result/journal: NOT_APPLICABLE.
- Additional task-specific artifacts: generated mutations are temporary test output only and must not
  be committed as a wildcard fixture tree.
- Focused tests: `tests.test_native_frame_mutation`, `tests.test_native_frame_replay`, and
  `tests.test_semantic_ocr_crop`.
- Integration tests: offline mutated replay through OCR/perception negative controls; no live
  validation.
- Transitive regression tests: governance validation and focused discovery of touched modules.
- Full-suite requirement: run focused tests first, then touched-component regressions, then the full
  repository suite when practical; if the full suite cannot run, explicitly record why and the last
  authoritative result rather than silently waiving it.
- Validators: Python compilation, focused tests, governance validation, CURRENT_HANDOFF JSON parsing,
  exact mutation-manifest JSON parsing/hash validation, touched-file secret scan, and
  `git diff --check`.
- Known baseline failures: None; one expected full-suite skip may remain.
- Evidence requirement: NOT_APPLICABLE because this dormant offline corpus creates no runtime
  evidence manifest.
- Valid blocked outcomes: evidence mutation pressure, inseparable false-accept/false-reject metrics,
  or live capture requests.
- Blocked-result commit policy: record the blocker; never alter retained evidence.
- Commit policy: one reviewed conventional local commit; no push.
- Expected focused commits: `feat(vision): add native-frame mutation corpus`; allowed paths are the
  direct implementation files above.
- Completion criteria: controlled mutation corpus with distinct storage, separated false-accept and
  false-reject measurement, required tests passing, zero runtime input, and unchanged
  registration/scheduler state.
- Next: `HOME-NAVIGATION-OBSERVABILITY`.

### HOME-NAVIGATION-OBSERVABILITY
- Task ID: `HOME-NAVIGATION-OBSERVABILITY`.
- Title: Deterministic Home navigation observability over the existing NavigationSession ledger.
- Status: Completed (2026-07-19; final cycle-3 availability invariants parent-reviewed; zero runtime).
- Milestone: Durable offline navigation architecture roadmap.
- Dependencies: `VISION-NATIVE-FRAME-MUTATION-CORPUS` and completed
  `RUNTIME-RESUMABLE-NAVIGATION-SESSIONS`.
- Blocked by: readiness requires the navigation session ledger and mutation/replay contracts; a
  second store is forbidden; calibration changes are out of scope.
- Objective: report deterministic observability over the existing NavigationSession ledger covering
  localization, requested/measured displacement, residuals, direction, progress, corrections,
  repeated viewports, clamps, binding confidence, safe-exit availability, timing, and frame counts
  without changing calibration.
- Established facts: `tasks/navigation_session.py` already persists crash-safe checkpoints and
  action ledger fields; observability must not invent a parallel store or alter calibration.
- Direct implementation files: `tasks/navigation_observability.py`,
  `tests/test_navigation_observability.py`, narrowly touchable
  `tasks/navigation_session.py` and `tests/test_navigation_session.py`, `BACKLOG.md`,
  `CURRENT_HANDOFF.md`, and `tests/test_governance_validation.py` only if durable identity coverage
  changes.
- Shared dependencies: `tasks/navigation_session.py` ledger, perception/session identity fields, and
  safe-exit availability signals; no production registration.
- Transitive regression set: navigation session tests, perception bundle, and governance validation.
- Allowed changes: per-commit allowed paths are exactly `tasks/navigation_observability.py`,
  `tests/test_navigation_observability.py`, `tasks/navigation_session.py`,
  `tests/test_navigation_session.py`, `BACKLOG.md`, `CURRENT_HANDOFF.md`, and
  `tests/test_governance_validation.py` only if identity coverage changes.
- Prohibited changes: second session store, calibration changes, live dispatch, registration,
  scheduler, workers, task rows, or push.
- Authorized runtime action: None; offline ledger reporting only.
- Maximum transport inputs: Zero.
- Navigation-only recovery: reporting only; no recovery transport is authorized.
- Consequential action: None.
- Registration changes: None; production remains `NOT_REGISTERED`.
- Scheduler changes: None; scheduler remains disabled/ineligible.
- Actions that must not be repeated: any prior live navigation or consequential input.
- Required source: offline NavigationSession fixtures/ledgers; live frames are not required.
- Exact target semantics: deterministic report fields for localization, requested vs measured
  displacement, residuals, direction, progress, corrections, repeated viewports, clamps, binding
  confidence, safe-exit availability, timing, and frame counts.
- Required local association: every report row must cite `navigation_session_id`, route identity, and
  capture/frame ordinals from the existing ledger.
- Negative controls: parallel store, silent calibration writes, inventing missing measurements, and
  non-deterministic field ordering.
- Coordinate space: platform-neutral session report fields; adapter geometry remains attributed.
- Accepted signals: ledger-backed field completeness and stable serialized report ordering.
- Rejected weak signals: reconstructed guesses without ledger support and timing from wall-clock
  alone when ledger monotonic fields exist.
- Ambiguous-result behavior: fail closed and mark fields unavailable rather than fabricating values.
- Zero-cost requirement: NOT_APPLICABLE because no transaction occurs.
- Quantity limits: one reporting module over the existing ledger only.
- Resource consumption policy: no game resources or runtime input.
- Premium or strategic restrictions: no gameplay or consequential control.
- Active evidence manifest: None; offline fixtures only.
- Required artifacts: observability module, focused tests, and sample deterministic report output in
  tests.
- Immediate-before/immediate-post/result/journal: NOT_APPLICABLE.
- Additional task-specific artifacts: none beyond test fixtures derived from session JSON.
- Focused tests: `tests.test_navigation_observability` and `tests.test_navigation_session`.
- Integration tests: offline ledger-to-report integration; no live BlueStacks validation.
- Transitive regression tests: governance validation and focused discovery of touched modules.
- Full-suite requirement: run focused tests first, then touched-component regressions, then the full
  repository suite when practical; if the full suite cannot run, explicitly record why and the last
  authoritative result rather than silently waiving it.
- Validators: Python compilation, focused tests, governance validation, CURRENT_HANDOFF JSON parsing,
  deterministic report/session JSON parsing when JSON is touched, touched-file secret scan, and
  `git diff --check`.
- Known baseline failures: None; one expected full-suite skip may remain.
- Evidence requirement: NOT_APPLICABLE because this dormant offline reporter creates no runtime
  evidence manifest.
- Valid blocked outcomes: second-store pressure, calibration mutation, or non-deterministic reports.
- Blocked-result commit policy: record the blocker; do not alter calibration.
- Commit policy: one reviewed conventional local commit; no push.
- Expected focused commits: `feat(home): add navigation session observability`; allowed paths are the
  direct implementation files above.
- Completion criteria: deterministic NavigationSession ledger reporting for all required fields,
  no second store, no calibration changes, required tests passing, zero transport, and unchanged
  registration/scheduler state.
- Next: `HOME-NAVIGATION-BOUNDED-SESSION-CALIBRATION`.

### HOME-NAVIGATION-BOUNDED-SESSION-CALIBRATION
- Task ID: `HOME-NAVIGATION-BOUNDED-SESSION-CALIBRATION`.
- Title: Strictly bounded session-local BlueStacks gesture calibration adaptation.
- Status: Pending (dormant; offline contract only; not activated).
- Milestone: Durable offline navigation architecture roadmap.
- Dependencies: `HOME-NAVIGATION-OBSERVABILITY` and completed
  `RUNTIME-RESUMABLE-NAVIGATION-SESSIONS`.
- Blocked by: readiness requires observability fields for requested/measured displacement and
  residuals; auto-persistence of learned calibration is forbidden; Bliss remains separate;
  `CONFIRMED_NOT_DISPATCHED` must not be enabled by this task.
- Objective: allow strictly bounded session-local BlueStacks gesture adaptation that preserves the
  original calibration and every adjustment, rejects wrong-direction/implausible/outlier
  measurements, and never auto-persists learned calibration.
- Established facts: BlueStacks inverse gesture conversion is adapter-owned; navigation sessions
  already track displacement history; production Bliss calibration is independent; transport
  non-dispatch verification remains fail-closed.
- Direct implementation files: `tasks/navigation_session_calibration.py`,
  `scripts/home_atlas_bluestacks.py`, `tests/test_navigation_session_calibration.py`,
  `tests/test_home_atlas_planner.py` if needed for adapter regression, `BACKLOG.md`,
  `CURRENT_HANDOFF.md`, and `tests/test_governance_validation.py` only if durable identity coverage
  changes.
- Shared dependencies: navigation session ledger/observability and BlueStacks gesture conversion;
  no production registration.
- Transitive regression set: navigation session, observability, Home atlas BlueStacks adapter tests,
  and governance validation.
- Allowed changes: per-commit allowed paths are exactly `tasks/navigation_session_calibration.py`,
  `scripts/home_atlas_bluestacks.py`, `tests/test_navigation_session_calibration.py`,
  `tests/test_home_atlas_planner.py` if needed for adapter regression, `BACKLOG.md`,
  `CURRENT_HANDOFF.md`, and `tests/test_governance_validation.py` only if identity coverage changes.
- Prohibited changes: auto-persisting learned calibration, Bliss calibration reuse, enabling
  `CONFIRMED_NOT_DISPATCHED`, unbounded learning, live consequential dispatch, registration,
  scheduler, workers, task rows, or push.
- Authorized runtime action: None required; offline bounded adaptation tests only. Any later live use
  remains separately authorized and BlueStacks-only.
- Maximum transport inputs: Zero for this task.
- Navigation-only recovery: session-local gesture adaptation for navigation-only pans/zooms may be
  modeled offline; no live recovery transport is authorized here.
- Consequential action: None.
- Registration changes: None; production remains `NOT_REGISTERED`.
- Scheduler changes: None; scheduler remains disabled/ineligible.
- Actions that must not be repeated: prior no-progress canonical short drags or any identical
  unreconciled navigation input.
- Required source: offline measured displacement samples from session fixtures; live frames are not
  required.
- Exact target semantics: preserve original calibration baseline; record every session adjustment;
  reject wrong-direction, implausible, and outlier measurements; adaptations remain session-local and
  non-persistent by default.
- Required local association: each adjustment cites session id, sample measurement, acceptance or
  rejection reason, and the unchanged original calibration snapshot.
- Negative controls: auto-persist to disk/profile, Bliss parameter copy, accepting wrong-direction
  samples, and enabling `CONFIRMED_NOT_DISPATCHED`.
- Coordinate space: BlueStacks adapter gesture space only; Bliss remains independent.
- Accepted signals: bounded accepted adjustments with preserved baseline and explicit rejection
  reasons for invalid samples.
- Rejected weak signals: global learning without session bounds, mean-shift from outliers, and
  transport-success-as-calibration-proof.
- Ambiguous-result behavior: fail closed; keep original calibration and reject the sample.
- Zero-cost requirement: NOT_APPLICABLE because no transaction occurs.
- Quantity limits: session-local bounded adjustments only; no cross-session accumulation in this task.
- Resource consumption policy: no game resources or runtime input.
- Premium or strategic restrictions: no consequential controls.
- Active evidence manifest: None; offline fixtures only.
- Required artifacts: session-local calibration adapter, focused rejection tests, and proof that
  original calibration remains preserved.
- Immediate-before/immediate-post/result/journal: NOT_APPLICABLE.
- Additional task-specific artifacts: offline measurements are in-memory test data in
  `tests/test_navigation_session_calibration.py`; no additional fixture path is writable.
- Focused tests: `tests.test_navigation_session_calibration`, `tests.test_navigation_observability`,
  and `tests.test_navigation_session`.
- Integration tests: offline session-local adaptation with observability fields; no live BlueStacks
  validation required.
- Transitive regression tests: governance validation and focused discovery of touched modules.
- Full-suite requirement: run focused tests first, then touched-component regressions, then the full
  repository suite when practical; if the full suite cannot run, explicitly record why and the last
  authoritative result rather than silently waiving it.
- Validators: Python compilation, focused tests, governance validation, CURRENT_HANDOFF JSON parsing,
  calibration/session JSON parsing when JSON is touched, touched-file secret scan, and
  `git diff --check`.
- Known baseline failures: None; one expected full-suite skip may remain.
- Evidence requirement: NOT_APPLICABLE because this dormant offline calibration task creates no
  runtime evidence manifest.
- Valid blocked outcomes: auto-persist pressure, Bliss leakage, outlier acceptance, or attempts to
  enable `CONFIRMED_NOT_DISPATCHED`.
- Blocked-result commit policy: record the blocker; preserve original calibration.
- Commit policy: one reviewed conventional local commit; no push.
- Expected focused commits: `feat(home): add bounded session calibration`; allowed paths are the
  direct implementation files above.
- Completion criteria: bounded session-local BlueStacks gesture adaptation with preserved baseline,
  rejection of invalid samples, no auto-persist, Bliss separate, `CONFIRMED_NOT_DISPATCHED` still
  unavailable, required tests passing, and unchanged registration/scheduler state.
- Next: `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION`.

### RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION
- Task ID: `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION`.
- Title: Narrow declarative verified-flow composition over existing navigation contracts.
- Status: Pending (dormant; offline contract only; not activated).
- Milestone: Durable offline navigation architecture roadmap.
- Dependencies: `HOME-NAVIGATION-BOUNDED-SESSION-CALIBRATION`, completed shared roadmap contracts for
  perception/session/radial/safe-exit/capability reuse, and existing `NavigationStep` /
  `NavigationRunner` contracts.
- Blocked by: readiness review must first demonstrate that multiple routes already reuse stable
  perception, session, radial, safe-exit, and capability contracts; if reuse is not demonstrable,
  stop as a valid blocked outcome without building a second engine. No broad DSL or generic
  autonomous runtime is authorized.
- Objective: after a positive readiness review, extend existing `NavigationStep`, `NavigationRunner`,
  contracts, and semantic planners for declarative verified-flow composition of one reference route
  only, reusing the stable shared contracts rather than inventing a second engine.
- Established facts: `NavigationStep`/`NavigationRunner` and task contracts already compose typed
  navigation; roadmap perception/session/radial/safe-exit/capability tasks are intended shared
  seams; broad autonomous DSLs are out of scope.
- Direct implementation files: exact readiness artifact
  `docs/navigation_verified_flow_readiness.md`, `tasks/contracts.py`,
  `safe_action_core/navigation.py`, exact one reference route `tasks/supply_depot.py`,
  `tests/test_navigation_runner.py`, `tests/test_supply_depot.py`, new exact
  `tests/test_verified_flow_composition.py`, `BACKLOG.md`, `CURRENT_HANDOFF.md`, and
  `tests/test_governance_validation.py` only if durable identity coverage changes.
- Shared dependencies: completed roadmap contracts above, existing NavigationStep/Runner, and
  semantic planners; no production registration.
- Transitive regression set: navigation runner, task contracts, reference route tests, and
  governance validation.
- Allowed changes: per-commit allowed paths are exactly
  `docs/navigation_verified_flow_readiness.md`, `tasks/contracts.py`,
  `safe_action_core/navigation.py`, `tasks/supply_depot.py`,
  `tests/test_navigation_runner.py`, `tests/test_supply_depot.py`,
  `tests/test_verified_flow_composition.py`, `BACKLOG.md`, `CURRENT_HANDOFF.md`, and
  `tests/test_governance_validation.py` only if identity coverage changes.
- Prohibited changes: second navigation engine, broad DSL, generic autonomous runtime, multi-route
  mass migration, live consequential broadening, registration, scheduler, workers, task rows, or push.
- Authorized runtime action: None required for offline composition; any later live reference-route
  run needs separate explicit authorization.
- Maximum transport inputs: Zero for this task.
- Navigation-only recovery: composition may declare navigation-only steps only where existing
  contracts already allow them; no new recovery transport authority.
- Consequential action: None newly authorized by composition alone.
- Registration changes: None; production remains `NOT_REGISTERED`.
- Scheduler changes: None; scheduler remains disabled/ineligible.
- Actions that must not be repeated: any prior live consequential action keys on the reference route.
- Required source: readiness review evidence that multiple existing routes already consume the shared
  contracts; in-memory test doubles in `tests/test_verified_flow_composition.py` and existing
  `tests/test_supply_depot.py` data for the single reference route.
- Exact target semantics: readiness gate first; if positive, declarative composition of one reference
  route using existing NavigationStep/Runner plus shared perception/session/radial/safe-exit/
  capability contracts; verified step preconditions/postconditions remain fail-closed.
- Required local association: each composed step retains source/target semantics, capture freshness
  requirements, and capability class separation from the shared contracts.
- Negative controls: proceeding without readiness proof, second engine/DSL, composing consequential
  steps under navigation-only capabilities, and activating multiple reference routes in this task.
- Coordinate space: existing contract/runner coordinate rules; adapter-owned geometry stays attributed.
- Accepted signals: documented multi-route reuse readiness, one reference route composition, and
  offline verified precondition/postcondition checks.
- Rejected weak signals: aspirational reuse claims, new DSL surface area, and transport success as
  semantic verification.
- Ambiguous-result behavior: fail closed; insufficient multi-route reuse sets and records this task
  as blocked and stops the serial sequence under orchestrator rules without implementing composition.
- Zero-cost requirement: preserve existing zero-cost gates; composition adds no paid consequences.
- Quantity limits: exactly one reference route; no broad migration.
- Resource consumption policy: no game resources or runtime input in this task.
- Premium or strategic restrictions: no premium/purchase/strategic controls.
- Active evidence manifest: None; offline readiness note and tests only.
- Required artifacts: exact `docs/navigation_verified_flow_readiness.md`; after a positive gate,
  narrow composition extensions, exactly one Supply Depot reference route, and focused/integration/
  regression tests. A negative review produces only a recorded blocked state and no implementation.
- Immediate-before/immediate-post/result/journal: NOT_APPLICABLE.
- Additional task-specific artifacts: exact `docs/navigation_verified_flow_readiness.md` only.
- Focused tests: `tests.test_verified_flow_composition`, `tests.test_navigation_runner`, and
  `tests.test_supply_depot`.
- Integration tests: offline composed reference-route dry-run; no live runtime required.
- Transitive regression tests: governance validation and focused discovery of touched modules.
- Full-suite requirement: run focused tests first, then touched-component regressions, then the full
  repository suite when practical; if the full suite cannot run, explicitly record why and the last
  authoritative result rather than silently waiving it.
- Validators: Python compilation, focused tests, governance validation, CURRENT_HANDOFF JSON parsing,
  JSON parsing for any touched route/session output, touched-file secret scan, and `git diff --check`.
- Known baseline failures: None; one expected full-suite skip may remain.
- Evidence requirement: NOT_APPLICABLE because this dormant offline composition task creates no
  runtime evidence manifest.
- Valid blocked outcomes: readiness review showing insufficient multi-route reuse, second-engine/DSL
  pressure, or attempts to compose multiple routes in this task; each must record blocked state and
  stop the serial sequence without satisfying completion.
- Blocked-result commit policy: a failed readiness review must set/record blocked state, stop the
  serial sequence, and must not produce the successful implementation commit.
- Commit policy: one reviewed conventional local commit; no push.
- Expected focused commits: `feat(runtime): compose one verified reference flow`; allowed paths are
  the direct implementation files above.
- Completion criteria: positive readiness review plus exactly one Supply Depot reference-route
  composition over existing contracts, required focused/integration/regression/full-suite gates and
  validators passing or the full-suite inability explicitly recorded, no second engine/DSL, zero
  unauthorized runtime input, unchanged registration/scheduler state, and the unrelated post-roadmap
  successor preserved. A failed readiness review is blocked, not completed.
- Next: `M6-DQ-TRANSITION-CORPUS`.

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
- Status: Passed (2026-07-14; Daily row adapter plus 5 focused tests).
- Covered: `craft_nanoweapon`; Craft Weapon variant.
- Exclusions: Material Production, Inherit Weapon, long/expensive craft, unknown materials.
- Dependencies/routes: inventory → Gear Factory → Nanoweapon.
- Source/target/policy: exact Craft Weapon target and free/allowlisted materials.
- Offline acceptance/tests: `tasks/daily_nanoweapon.py` and
  `tests/test_daily_nanoweapon.py` cover selected-row ownership, one-craft cardinality, successor
  proof, Main/static negatives, and Claim separation; shared recipe/material guards remain covered
  by `tests/test_nanoweapon.py`.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one exact craft; timer/result and Daily 0/1 progress;
  stop on material, cost, timer, stale-frame, or successor ambiguity.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED` only if free policy is proven.

### DQ-FLOW-ENHANCE-GEAR
- Status: Passed (2026-07-14; Daily Gear adapter plus 5 focused tests).
- Covered: `enhance_gear`; Gear variant.
- Exclusions: Auto Select, >1-star materials, Promote/Modify/Replace/Unequip, premium.
- Dependencies/routes: inventory → Commander Info → Gear.
- Source/target/policy: equipped Gear, Enhance, one-star material, quantity one, exact Confirm.
- Offline acceptance/tests: `tasks/daily_enhancement.py` and
  `tests/test_daily_enhancement.py` cover selected-row ownership, Gear family boundaries, cost and
  material guards, one-enhancement cardinality, successor proof, Main/static negatives, and Claim
  separation; shared family coverage remains in `tests/test_enhancement.py`.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one exact enhancement; Gear level/material change and Daily
  0/1 progress; stop on target/material/quantity, stale-frame, or successor ambiguity.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED`; unlocks other enhancement variants through family sharing.

### DQ-FLOW-ENHANCE-CHIP
- Status: Passed (2026-07-14; Daily Chip adapter plus 5 focused tests).
- Covered: `enhance_chip`; Chip variant.
- Exclusions: same enhancement unsafe actions and materials as Gear.
- Dependencies/routes: DQ-FLOW-ENHANCE-GEAR shared engine → Commander Info → Chip.
- Source/target/policy: equipped Chip, one-star material, quantity one.
- Offline acceptance/tests: `tasks/daily_enhancement.py` Chip variant and
  `tests/test_daily_enhancement_chip.py` cover family ownership, Gear/Chip distinction, material
  guards, one-enhancement cardinality, successor proof, Main/static negatives, and Claim
  separation; shared coverage remains in `tests/test_enhance_chip.py`.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one exact enhancement; Chip state/material change and Daily
  0/1 progress; stop on selection, material, stale-frame, or successor ambiguity.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED`; family-shared implementation.

### DQ-FLOW-ENHANCE-MODULE
- Status: Passed (2026-07-14; Daily Module adapter plus 5 focused tests).
- Covered: `enhance_module`; Module variant.
- Exclusions: same enhancement unsafe actions and materials as Gear.
- Dependencies/routes: DQ-FLOW-ENHANCE-GEAR shared engine → Commander Info → Module.
- Source/target/policy: equipped Module, one-star material, quantity one.
- Offline acceptance/tests: `tasks/daily_enhancement.py` Module variant and
  `tests/test_daily_enhancement_module.py` cover family sharing, Module/Gear/Chip distinction,
  material guards, one-enhancement cardinality, successor proof, Main/static negatives, and Claim
  separation; shared coverage remains in `tests/test_enhance_module.py`.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one exact enhancement; Module state/material change and Daily
  0/1 progress; stop on selection, material, stale-frame, or successor ambiguity.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED`; family-shared implementation.

### DQ-FLOW-CAMPAIGN-AP
- Status: Passed (2026-07-14; Daily AP adapter plus 5 focused tests).
- Covered: `consume_ap`; Sweep/Auto Complete variants.
- Exclusions: uncontrolled battle, refill, unknown AP cost, Ultimate Challenge dispatch.
- Dependencies/routes: inventory → Campaign.
- Source/target/policy: readable AP, allowlisted stage, exact Sweep/Auto Complete.
- Offline acceptance/tests: `tasks/daily_campaign_ap.py` and
  `tests/test_daily_campaign_ap.py` cover selected-row ownership, AP budget/cost guards, exact
  progress arithmetic, route/cardinality, Main/static negatives, and Claim separation; shared
  Sweep/Auto Complete coverage remains in `tests/test_campaign_ap.py`.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one bounded known AP transaction; exact AP delta and Daily
  progress; stop on battle, refill, budget, stale-frame, or successor ambiguity.
- Claim/persistence/registration/scheduler: separate Claim; dormant; not registered; false.
- Promotion/unlocks: `EVIDENCE_GATED`; unlocks Challenge policy review.

### DQ-FLOW-CAMPAIGN-AUTO-BATTLE
- Task ID: `DQ-FLOW-CAMPAIGN-AUTO-BATTLE`.
- Title: Add a configurable dormant Campaign Auto Battle route contract.
- Status: Completed (2026-07-16; dormant configurable route contract amended from supervised
  BlueStacks validation and 17 focused Campaign tests passed).
- Milestone: Daily Quest Campaign AP route translation.
- Dependencies: `DQ-FLOW-CAMPAIGN-AP` Passed and `TOOLS-BLUESTACKS-FLOW-CAPTURE` Completed.
- Blocked by: none for offline implementation; live promotion remains blocked by missing exact
  Bliss-native stage navigation and defeat evidence.
- Objective: model configurable `tier-chapter-stage` selection, bounded repeated AP use, Auto
  Battle enablement, screenshot-polled terminal recognition, and return-home behavior.
- Established facts: the ignored BlueStacks session
  `.local-captures/bluestacks/consume-ap-campaign/20260716T014118395232Z/` and seven supplied
  screenshots establish tier controls, `Ch.3`, `[3-1]`, AP `100/120`, cost `20`, Hero Lineup,
  Auto, active battle, and `WINNER`/Loot/`Tap to continue`; they do not authorize Bliss input.
- Post-completion supervised BlueStacks validation on 2026-07-16 was explicitly user-authorized:
  tier 1 was selected, the tier map was panned directly to `Ch.20 Westwinds`, `[20-9] Westwinds`
  was selected, its fresh cost was 16 AP, six Auto battles succeeded, 96 AP was spent, three AP
  regenerated during the loop, the insufficient state showed 6/120 with the 16 cost red without
  opening refill, and the highlighted Campaign exit returned to Home/Base. One observation request
  timed out while run 6 remained active; read-only reconciliation found Auto still active and the
  battle later reached the normal victory terminal. No Bliss, Unraid, ADB, registration, scheduler,
  journal, lease, premium, refill, or Claim operation occurred.
- Direct implementation files: `tasks/campaign_auto_battle.py`, `tasks/__init__.py`,
  `tests/test_campaign_auto_battle.py`, and `docs/campaign-auto-battle.md`.
- Shared dependencies: `tasks/campaign_ap.py`, task contracts, fixed 800x1280 profile semantics,
  and fresh OCR binding policy.
- Transitive regression set: existing Campaign AP and Daily Campaign AP focused tests.
- Allowed changes: direct implementation files plus this exact backlog section and isolated
  `CURRENT_HANDOFF.md` hunks; per-commit allowed paths are those same task-owned files/hunks.
- Prohibited changes: production adapters, pnsctl, journals, leases, registration, scheduler,
  protected evidence, unrelated MVP work, and any runtime or gameplay operation.
- Authorized runtime action: None.
- Maximum transport inputs: Bliss 0, BlueStacks 0, ADB 0, gameplay 0.
- Navigation-only recovery: offline semantic planning only; no transport recovery is authorized.
- Consequential action: none; the module returns coordinate-free decisions with dispatch disabled.
- Registration changes: forbidden; preserve not registered.
- Scheduler changes: forbidden; preserve disabled/ineligible.
- Actions that must not be repeated: no prior Claim, Bioenhancer, Praise, Alliance Help, AP,
  Campaign, or collector input may be replayed by this task.
- Required source: the exact accepted local capture and supplied screenshots for translation only;
  future live work requires fresh Bliss-native full-frame evidence.
- Exact target semantics: configured tier, chapter, stage, AP Challenge, Hero Lineup Challenge,
  Auto, explicit victory continue, explicit defeat return, and Home/Base.
- Required local association: tier/chapter/stage identity, AP value/cost/budget, battle state, and
  result must belong to one current route ledger.
- Negative controls: wrong tier/chapter/stage, unknown AP/cost, refill, overlay, missing target,
  fixed-time completion, ambiguous result, timeout, ledger mismatch, and repeat after loss.
- Coordinate space: semantic and coordinate-free offline contract; future targets require fresh raw
  800x1280 binding and may not reuse BlueStacks display coordinates.
- Accepted signals: exact stage identity; exact AP arithmetic; recognized lineup; explicit Auto;
  active-battle polling; complete WINNER/Loot/continue signature; explicit defeat; exact AP delta.
- Rejected weak signals: elapsed time, animation cessation, transport success, partial result text,
  stale OCR, coordinate-only targets, or BlueStacks screenshots as production authorization.
- Ambiguous-result behavior: block terminally, preserve state, dispatch nothing, and never retry.
- Zero-cost requirement: not applicable to AP; every planned run requires explicit positive AP cost
  within an explicit budget, with refills forbidden.
- Quantity limits: whole runs only, bounded by available AP, explicit AP budget, and maximum runs.
- Resource consumption policy: offline arithmetic only; no AP is consumed by this task.
- Premium or strategic restrictions: all purchases, refills, premium controls, and strategic
  substitutions are forbidden.
- Active evidence manifest: none; local captures remain ignored and unstaged.
- Required artifacts: task source, focused tests, concise documentation, and verification output.
- Immediate-before/immediate-post/result/journal: NOT_APPLICABLE because no input or runtime action
  is authorized.
- Additional task-specific artifacts: no canonical gameplay evidence is created or staged.
- Focused tests: compile plus `tests.test_campaign_auto_battle`, `tests.test_campaign_ap`, and
  `tests.test_daily_campaign_ap`.
- Integration tests: none; live integration is outside this task.
- Transitive regression tests: existing Campaign AP and Daily Campaign AP focused modules only.
- Full-suite requirement: none; do not run the full project suite.
- Validators: governance validation, handoff JSON parsing, `git diff --check`, and touched-file
  secret scan.
- Known baseline failures: report unrelated existing failures separately; none may be introduced in
  touched Campaign files.
- Evidence requirement: NOT_APPLICABLE because this is a dormant offline contract and the local
  BlueStacks capture remains an ignored translation source.
- Valid blocked outcomes: missing exact semantic contract, focused test failure, governance failure,
  protected-work overlap, or any need for runtime input.
- Blocked-result commit policy: preserve valid task-owned work and commit only isolated coherent
  offline changes when allowed; otherwise report the exact overlap and do not broaden scope.
- Commit policy: one focused commit, stage only reviewed task-owned paths/hunks, preserve all
  pre-existing MVP and protected evidence work, do not amend, and no push.
- Expected focused commits: `feat(tasks): model Campaign Auto Battle route`; allowed paths are the
  direct implementation files and isolated task-state hunks only.
- Completion criteria: met: configurable stage parsing, fresh-AP bounded repeat arithmetic with
  separately reconciled regeneration, semantic pan/chapter/stage decisions, screenshot-polled
  success/loss/timeout handling, insufficient-AP unwind to Home/Base, focused tests, documentation,
  and validators pass. The route remains dormant and unregistered.

### DQ-FLOW-CAMPAIGN-AUTO-BATTLE-BLUESTACKS
- Task ID: `DQ-FLOW-CAMPAIGN-AUTO-BATTLE-BLUESTACKS`.
- Title: Bind and validate the executable local BlueStacks Campaign AP route.
- Status: Completed (2026-07-16; executable local BlueStacks route and supervised validation).
- Milestone: Daily Quest Campaign AP executable BlueStacks validation.
- Dependencies: `DQ-FLOW-CAMPAIGN-AUTO-BATTLE` Completed.
- Blocked by: none for the local BlueStacks adapter; Bliss promotion remains blocked by
  Bliss-native source/target/successor evidence.
- Objective: recognize native 800x1280 Campaign frames, select a configurable stage, pan maps
  without clicking intermediate chapters, press only the lineup Challenge control, enable Auto,
  poll victory/defeat, repeat within AP budget, and return Home without refill.
- Established facts: stage `1-20-9` costs 16 AP; native BlueStacks frames expose tier controls,
  OCR-readable chapter/stage/AP/cost, a fixed lineup Challenge control, distinct Auto states, and
  the joint WINNER/Loot/Tap-to-continue terminal. The executable validation completed one victory.
  The supplied defeat frame establishes a joint LOSE/Improve Might/bottom-Tap-to-continue
  signature; the Buy Now panel is excluded from target binding.
- Scope: local BlueStacks `emulator-5554` only; Bliss, Unraid, production registration, scheduler,
  Daily Claim, premium currency, AP refill, and unrelated gameplay remain prohibited.
- Authorized runtime action: one supervised bounded local BlueStacks validation for stage `1-20-9`;
  consume only naturally available AP at the observed 16-AP stage cost and stop when unaffordable.
- Maximum transport inputs: Bliss 0; local BlueStacks navigation/consequential inputs 240 total;
  maximum completed stage runs 10; AP budget 120; no identical blind retries.
- Navigation-only recovery: pan with a different bounded gesture when the configured chapter/stage
  is absent; one base request may reveal one recognized lower-right Campaign exit; otherwise stop.
- Consequential action: stage Challenge may spend only the recognized configured AP cost; lineup
  Challenge and Auto are permitted only after their fresh recognized predecessors.
- Runtime interface: checked-in `scripts/bluestacks_campaign_ap.py` or Computer Use against the exact
  selected BlueStacks window; no production adapter or public ADB connection.
- Negative controls: unknown/stale frame, wrong stage/cost, refill, insufficient AP, ambiguous
  result, timeout, missing target, AP ledger mismatch, and repeat after defeat all fail closed.
- Direct implementation files: `tasks/campaign_auto_battle_vision.py`,
  `tasks/campaign_auto_battle_runtime.py`, project-owned template assets,
  `scripts/bluestacks_campaign_ap.py`, focused tests, Campaign documentation, and exact task/handoff
  state hunks.
- Shared dependencies: the completed semantic Campaign contract, OpenCV, Tesseract, the existing
  BlueStacks collector transport, and native 800x1280 profile semantics.
- Transitive regression set: existing Campaign Auto Battle, Campaign AP, and Daily Campaign AP tests.
- Allowed changes: direct implementation files, project-owned Campaign templates, focused tests,
  Campaign documentation, and exact task/handoff state hunks.
- Prohibited changes: Bliss/Unraid production adapters, public ADB, journals, leases, Daily Claim,
  premium/refill behavior, unrelated gameplay, registration, and scheduler state.
- Registration changes: forbidden; preserved not registered.
- Scheduler changes: forbidden; preserved disabled/ineligible.
- Actions that must not be repeated: the obsolete bottom-left `campaign-exit-base` binding, any
  identical input after unchanged semantic state, any completed stage transaction after defeat,
  and any refill/premium control.
- Required source: fresh native 800x1280 local BlueStacks frames plus project-owned templates
  derived from the exact user-supplied and retained frames.
- Exact target semantics: configured tier/chapter/stage, stage Challenge, fixed bottom lineup
  Challenge, disabled Auto, strict victory continuation, safe defeat return, and highlighted exit.
- Required local association: OCR stage/AP/cost, template state, target ROI, route progress, and AP
  ledger all derive from the same fresh frame sequence and configured stage.
- Coordinate space: raw native 800x1280 BlueStacks frames only; window previews and vendor
  coordinates cannot authorize adapter dispatch.
- Accepted signals: exact stage header, numeric AP/cost, button color/text, chapter header, red stage
  node glyph, wave fraction, enabled/disabled Auto comparison, and joint victory signature.
- Rejected weak signals: elapsed time alone, transport success, hero portrait/identity, partial
  victory text, stale OCR, unrecognized map digits, and coordinate-only targets.
- Ambiguous-result behavior: stop terminally, retain local frames/events, send no retry, refill, or
  substitute action.
- Zero-cost requirement: not applicable; Campaign runs require a positive known AP cost.
- Quantity limits: whole runs only, bounded by available AP, AP budget 120, run cap 10, and the
  180-second per-battle timeout ceiling.
- Resource consumption policy: consume only naturally available AP at the configured stage cost;
  never refill and stop when another complete run is unaffordable.
- Premium or strategic restrictions: all AP refills, premium currency, paid Blitz, Ultimate
  Challenge, and strategic substitutions are forbidden.
- Active evidence manifest: none canonical; local ignored session frames and `events.jsonl` retain
  the BlueStacks validation trace.
- Required artifacts: checked-in recognizer/controller/runner, project-owned templates and manifest,
  focused tests, documentation, and local session result records.
- Immediate-before/immediate-post/result/journal: local frames and `events.jsonl` provide the
  BlueStacks validation sequence; no production operational journal or lease was created.
- Additional task-specific artifacts: local sessions under
  `.local-captures/campaign-ap-live/1-20-9-*` including the verified victory and final Home terminal.
- Focused tests: compile plus `tests.test_campaign_auto_battle_runtime`,
  `tests.test_campaign_auto_battle`, `tests.test_campaign_ap`, and
  `tests.test_daily_campaign_ap`.
- Integration tests: retained local BlueStacks frame replay plus one explicitly authorized live
  local BlueStacks validation; no Bliss integration.
- Transitive regression tests: existing Campaign AP and Daily Campaign AP focused modules.
- Full-suite requirement: none; do not run the unrelated full suite.
- Validators: governance validation, handoff-state JSON parsing, asset-manifest JSON parsing,
  `git diff --check`, and touched-file secret scan.
- Known baseline failures: unrelated dirty-worktree changes remain outside this task; no new focused
  Campaign failures are accepted.
- Evidence requirement: NOT_APPLICABLE: ignored local BlueStacks frames/events are validation
  diagnostics, not canonical production evidence, and must not be staged as Bliss authorization.
- Valid blocked outcomes: unknown screen, missing target, OCR/cost mismatch, timeout, defeat without
  a safe return, absent highlighted exit, duplicate input, or protected-work overlap.
- Blocked-result commit policy: preserve coherent task-owned implementation and local diagnostics;
  never broaden scope or absorb unrelated dirty changes.
- Commit policy: one focused commit only if task-owned hunks can be isolated from the existing dirty
  worktree; per-commit allowed paths are the listed direct files and exact task/handoff hunks; no push.
- Expected focused commits: `feat(tasks): execute Campaign AP on BlueStacks`; no push.
- Completion criteria: met. Twenty-five focused Campaign tests pass; retained replay recognizes
  the route; the live adapter panned directly to chapter 20, selected stage 9, verified 21 AP and
  cost 16, used only the lineup Challenge control, enabled Auto, recognized victory, verified
  6 AP after one regenerated AP, and returned Home. The original return binding repeated a
  navigation-only base request; it was stopped, replaced with the exact highlighted lower-right
  exit plus an identical-input retry guard, and the final Home frame terminated at 9 AP without
  refill or further input. The supplied defeat frame is recognized only by its three-part
  signature, binds only the bottom continuation, excludes Buy Now, and forces a no-repeat unwind
  through chapter and tier to Home.
- Next: define the exact requested Nova objective before activating a separate atomic workflow;
  `M6-DQ-TRANSITION-CORPUS` remains the existing product successor until that happens.

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
- Status: Passed (2026-07-14; Daily Lair adapter plus 5 focused tests).
- Covered: `defeat_zombie_lair`; Lair variant.
- Exclusions: level 60, unknown level, arbitrary combat, Claim.
- Dependencies/routes: DQ-FLOW-WORLD-STAMINA-ENGINE → recognized Lair.
- Source/target/policy: exact row, lair level, stamina, march slot, join.
- Offline acceptance/tests: `tasks/daily_zombie_lair.py` and
  `tests/test_daily_zombie_lair.py` cover selected-row ownership, Lair level/march/stamina guards,
  exact result/cardinality, Main/static/combat negatives, and Claim separation; shared route
  coverage remains in `tests/test_zombie_lair.py`.
- Bliss/live boundary: evidence-gated; no registration/input.
- Transaction/postcondition/recovery: one exact join; positive participation/result and Daily 0/1
  progress; stop on wrong Lair, budget, combat, stale-frame, or successor ambiguity.
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

### DQ-FLOW-RUINS-CHALLENGE-BLUESTACKS
- Task ID: `DQ-FLOW-RUINS-CHALLENGE-BLUESTACKS`
- Title: Separate Ruins Challenge Daily workflow — local BlueStacks validation
- Status: Passed (2026-07-16; dormant implementation and supervised local validation)
- Milestone: Ruins Challenge recognition, bounded challenge state machine, chest separation
- Dependencies: native 800x1280 frame contract, current reset identity, Computer Use local BlueStacks access
- Blocked by: none for local validation; production promotion remains separately gated
- Objective: recognize Home/Base and Ruins, identify current-day stages, challenge authorized zero-cost stages, reconcile results, claim Ruins chests, and return Home/Base
- Established facts: live flow was row Challenge → detail Attack → NPC Dispatch → explicit result → Tap to continue; current validation exposed Nova and Module timer-bound stages
- Direct implementation files: `tasks/ruins_challenge.py`, `tasks/ruins_challenge_runtime.py`, `tasks/ruins_challenge_vision.py`, `tests/test_ruins_challenge.py`, `scripts/ruins_challenge_inspect.py`
- Shared dependencies: `tasks/contracts.py`, `tasks/profile.py`, existing scheduler and governance validators are read-only dependencies
- Transitive regression set: Noah’s Tavern recruits, Nova Praise, Bioenhancer, Personal Might Praise, and existing recruit flows
- Allowed changes: only the Ruins files, focused tests, local evidence record/manifest, documentation, and allowed paths directly attributable to this task
- Prohibited changes: Bliss/Unraid production input, ADB bypass, login/manual-only states, Exchange, Mall, purchase, premium, ticket, points spending, Daily Claim, registration, scheduler promotion, and unrelated workflows
- Authorized runtime action: Computer Use inspection and local BlueStacks input only; one fresh-bound consequential input per challenge or chest
- Maximum transport inputs: one row initiation per distinct authorized stage and one Claim per distinct available Ruins chest; no identical retries
- Navigation-only recovery: fresh source recognition, safe close/back, return to Ruins list, and final Home/Base only
- Consequential action: challenge initiation, Dispatch, and Ruins chest Claim are independently journaled/reconciled actions
- Registration changes: none; `ruins_challenge` matrix row remains `NOT_REGISTERED`
- Scheduler changes: none; scheduler eligibility remains `false`
- Actions that must not be repeated: Nova or Module after explicit failure; any ambiguous result; any claimed chest; Exchange/Mall/purchase/ticket control
- Required source: fresh native BlueStacks Home/Base and Ruins Challenge frames, with supplied screenshots reference-only
- Exact target semantics: positively recognized challenge identity, current reset/day state, enabled Challenge/Attack/Dispatch or available chest Claim control
- Required local association: reset identity `local-2026-07-16-ruins`, frame hash, action key, challenge/chest identity, immediate-before and immediate-post evidence
- Negative controls: locked Core/Cube, wrong-day rows, unknown rows/results, overlays, clipped/stale targets, premium/paid/ticketed/currency controls, Exchange, Mall
- Coordinate space: raw native 800x1280 only
- Accepted signals: explicit title, identity, row day/progress, enabled zero-cost control, NPC troop provision, explicit WIN/LOSE result, positive progress/chest postcondition
- Rejected weak signals: transport success, stale/reference geometry, generic green/gold pixels, unknown/partial OCR, inferred stage/day, missing close control
- Ambiguous-result behavior: mark unresolved, stop, preserve evidence, and never retry identically
- Zero-cost requirement: challenge detail must show NPC troops and no AP, ticket, premium, or currency cost
- Quantity limits: required Daily challenge count is 1; optional second only when independently recognized and configured; each chest at most once
- Resource consumption policy: no resource consumption except Ruins medals received by chest claim; no Ruins points spending
- Premium or strategic restrictions: reject premium, paid, ticketed, Mall, Exchange, and currency-spending controls
- Active evidence manifest: `evidence/sessions/20260716-ruins-challenge/manifest.json`
- Required artifacts: Home/Base, Ruins screen, both available rows, locked rows, detail, immediate-before/post, result, progress/Daily row, chest before/post, final Home/Base
- Immediate-before/immediate-post/result/journal: retained under `evidence/sessions/20260716-ruins-challenge/`; `record.md` reconciles all live actions
- Additional task-specific artifacts: `scripts/ruins_challenge_inspect.py`; challenge and chest ledgers in the runtime controller
- Focused tests: `tests/test_ruins_challenge.py`; 12 identities, day filtering, authorization, result/chest/controller guards
- Integration tests: `tests/test_challenge_disabled.py`; execution matrix remains disabled and dormant
- Transitive regression tests: Noah’s Tavern, Nova Praise, Bioenhancer, Personal Might Praise, and existing recruitment tests
- Full-suite requirement: run focused tests first, then requested regressions and governance validators; report baseline failures separately
- Validators: compilation, focused Ruins tests, regression tests, governance validation, handoff JSON, `git diff --check`, touched-file secret scan
- Known baseline failures: report only pre-existing fixture/environment failures; no new touched-component failure is acceptable
- Evidence requirement: TASK_LOCAL retained evidence is required for this supervised local validation; it is not Bliss production evidence
- Valid blocked outcomes: unknown screen/row/result, locked/unavailable/premium stage, overlay, stale frame, unresolved postcondition, duplicate action key
- Blocked-result commit policy: no commit required or permitted for this task; preserve local work and evidence
- Commit policy: do not stage, commit, push, or register; no push
- Expected focused commits: none
- Completion criteria: implementation compiled, focused/regression/governance validation passed or baseline-separated, evidence retained, final Home/Base recognized, no unresolved action, production registration/scheduler unchanged

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
