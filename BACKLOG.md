# Canonical execution backlog

Last updated: 2026-07-12 (America/Chicago)

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

## Milestones

| Milestone | Status | Dependency / blocker |
|---|---|---|
| M1 Repository/environment baseline | Passed | Host/VM baseline and rollback XML captured; authentication hard-stop manually resolved and verified |
| M2 Unraid audit | Passed | Measured in service plan on 2026-07-09 |
| M3 Direct Bliss runtime proof | Passed | RT-001 through RT-013 passed; downstream infrastructure and later account-guard gates remain |
| M4 One-time account provisioning | Passed for current Bliss runtime | Must remain manual on any rebuild |
| M5 Framework bake-off | Passed | Custom Python/direct ADB/OpenCV/local OCR selected; Airtest and MaaFramework rejected early |
| M6 Production corpus | In Progress | M6-DQ-BOOTSTRAP captured bootstrap evidence but is blocked at an unresolved Unraid SSH/worker reconciliation boundary; transition evidence remains later |
| M7 Deterministic service core | Pending | M7-SAFE-ACTION-CORE is the minimum supervised-trial subset; full core, M7-Takeover, and M7-AccountGuard remain later gates |
| M8 Claim-only MVP | Pending | Selected runtime, staged corpus, full core, and promotion gates; one supervised trial does not pass M8 |
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
- Status: Blocked (2026-07-12; SSH closed during post-input verification).
- Blocker: The current worker's Daily-tab input result and cleanup state are unresolved because
  the corrected SSH invocation reported a remote-side connection close and subsequent TCP 22
  checks failed for both `nas.local` and `192.168.50.92`. Do not retry the Daily-tab input until
  read-only reconciliation proves whether it ran and whether the temporary worker remains.
  No Claim, Go, quest-completion, or spend input was recorded. A positive completed-but-unclaimed
  Claim state remains intentionally deferred to `M6-DQ-TRANSITION-CORPUS`.
- Next: Resume M6-DQ-BOOTSTRAP after the approved private Unraid SSH path returns; begin with
  read-only runtime and worker reconciliation.

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
- Evidence: `evidence/sessions/<timestamp>-m7-safe-action-core/`.
- Rollback: disable the new executor/core path and restore the prior repository behavior; retain
  failed test evidence and do not alter runtime state.
- Status: Pending.
- Blocker: M6-DQ-BOOTSTRAP must pass first.
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
- Evidence: `evidence/sessions/<timestamp>-mvp-quest-to-claim/`.
- Rollback: stop at the first unknown or unresolved outcome, preserve the action journal and all
  frames, disable further claim input, and reconcile manually; no blind retry or resource-consuming
  fallback is allowed.
- Status: Pending.
- Blocker: M6-DQ-BOOTSTRAP and M7-SAFE-ACTION-CORE are not yet passed; the positive transition
  state may not exist until a quest is completed.
- Next: M6-DQ-TRANSITION-CORPUS after a successful trial.

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
M6-DQ-BOOTSTRAP is the current M6 task but is Blocked at an unresolved Unraid SSH/worker
reconciliation boundary after retained bootstrap captures. Do not mark M7-SAFE-ACTION-CORE,
MVP-QUEST-TO-CLAIM, or M6-DQ-TRANSITION-CORPUS In Progress. Do not retry the Daily-tab input
until the worker and device state are reconciled. Do not rerun RT-012 or the
completed MVP action; their complete evidence is retained in
`evidence/sessions/20260711-rt-012-observe-soak/` and
`evidence/sessions/20260711-mvp-startup-normalization/`. Do not place credentials in this
repository or command history. Launching `com.global.ztmslg` normally opens the authenticated Cash
Mall screen; startup normalization must positively recognize Cash Mall, recapture immediately,
send at most one authorized no-spend top-left back-arrow input, and positively recognize Home/Base
afterward. Cash Mall is not an authentication hard stop.
