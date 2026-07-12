# MVP-QUEST-TO-CLAIM — Blocked by pre-dispatch freshness policy

Recorded: 2026-07-12, America/Chicago

## Decision

MVP-QUEST-TO-CLAIM is **Blocked**. Startup normalization reached positively recognized Home/Base,
but the next Home/Base-to-Quest action was denied by the mandatory immediate-before policy check:
the CPU OCR/classification path took slightly longer than the configured three-second maximum
frame age. The action was cancelled before transport (`transport_calls=0`). The task stopped on
the required policy-denial boundary and did not retry or relax policy.

No Daily Quest screen was reached, no objective was selected or completed, no Go or Claim input
was sent, no prerequisite action occurred, and no resource or currency was spent.

## Offline and live preflight

- Repository HEAD began at `168be82`; MVP-QUEST-TO-CLAIM was Ready.
- All eight pre-existing metadata-only entries hash-matched `HEAD` and remained untouched.
- No retained SQLite task database existed. M7 schema version 1 and all 44 original tests passed.
- The added injected ADB adapter tests passed; final suite total is 47 before documentation checks.
- All six M6 assets, Go-not-Claim negative, clipped/ambiguous abstention, and RT-019 profile/hash
  validation passed. No production fixture could authorize Claim.
- VM was running; Android boot/profile was `800x1280`, 160 dpi, portrait, and nonblocking
  (`showing=false`, `secure=false`, `mInputRestricted=false`). Game was force-stopped.
- No prior worker, task database, tunnel, public listener, or temporary ADB server existed.
  RT-017 remained present.

## Packaging evidence

The first worker used the established unprivileged image but stopped before classification because
OpenCV was absent. No database or input existed. Three unrelated local application images were
probed network-disabled and also lacked OpenCV; none was modified or reused.

A task-scoped image was then built reproducibly from the established worker base with pinned
Numpy, OpenCV-headless, pytesseract, and Tesseract. The first build failed because the base image
declared a non-root build user; the corrected build used root only during image construction.
The live worker still ran as UID/GID 65534, read-only root, all capabilities dropped,
`no-new-privileges`, bounded CPU/memory/PIDs, host networking only for the proven private guest
path, no Docker socket, and no published ports. Build logs and both worker inspections are retained.

The temporary image `sha256:509d29552900cfe106da40439244d633a237ded28be66e909ea02a731497b4b5`
was removed after evidence preservation.

## Inputs and journal

OS inputs: **none**. The known launcher/keyguard state was already safe.

Package lifecycle: one launch of `com.global.ztmslg`; this is not a game-screen input.

Game-screen inputs, in order:

1. `nav-cash-home-001`: recognized Cash Mall back arrow, ROI `[35,0,180,65]`, dispatched one tap
   at `(107,32)` through M7. Lifecycle was `prepared → input_sent → confirmed`; Home/Base passed
   independent scene/navigation/OCR recognition. Cost zero, quantity one, consequence navigation.
2. `nav-home-quest-001`: proposed Home/Base Quest target, ROI `[250,1130,410,1280]`.
   Initial policy authorized and persisted `prepared`; immediate recapture still recognized the
   same source and target, but the second policy returned `STALE_FRAME`. Lifecycle became
   `prepared → cancelled`; input attempt is null and transport calls are zero.

The separate pre-Cash annotation command had a shell-quoting syntax error even though source/ROI
and both policy snapshots were retained. A post-hoc annotation was generated and explicitly named
as such; the confirmed action was never repeated. The Home-to-Quest dry-run annotation was created
successfully before its denied input proposal.

## Daily Quest and claim result

- Pre-existing Claim row: not observed; Daily Quest was not reached.
- Selected prerequisite objective: none.
- Initial objective progress/completion requirement: not observed.
- Prerequisite inputs: zero.
- Objective became claimable: no observation.
- Claim input/lifecycle: none.
- Daily Quest points before/after: not observed.
- Claim postcondition: none.
- Policy denials: one `STALE_FRAME` at immediate-before Home/Base-to-Quest validation.
- Unresolved actions: none.

## Persistence and cleanup

- Retained database: `actions.sqlite3` in this evidence directory and at
  `/mnt/cache/puzzle-survival-runtime/mvp-quest-to-claim/20260712-run/evidence/actions.sqlite3`.
- Final journal query: no nonterminal action, no unresolved action. Lease was explicitly released
  and remains in history with `valid=false`.
- Game force-stopped; task worker removed; task ADB server stopped; temporary task image removed;
  no tunnel or public/published ADB listener exists.
- VM remains running and RT-017 remains present. VM XML, qcow2, network, and runtime profile were
  not changed.
- The pre-existing host loopback ADB daemon at `127.0.0.1:5037` was present at initial preflight
  but absent at final verification. The task did not recreate it. No public listener exists.

## Blocker and next action

The exact blocker is the mismatch between the three-second frame-age policy and measured
CPU OCR/classification latency during immediate recapture. Before resuming this same task, review
and test a fail-closed freshness design that measures capture age without allowing recognition
latency to invalidate an otherwise unchanged immediate frame, or adopt an evidence-justified
threshold. Re-run offline timing/policy tests first. Do not reuse the cancelled action key, do not
retry blindly, and do not begin M6-DQ-TRANSITION-CORPUS.

No user action is currently required.

## Offline freshness correction — 2026-07-12

The retained blocker was reproduced from journal timestamps without reinterpreting or resending
the cancelled action. Its code recorded screenshot-command start as `captured_at`, so the retained
~1.0-second ADB capture latency was incorrectly charged against the three-second frame-age limit.
Home recognition then reached the second policy at 3.031 seconds despite a still-positive source.

`freshness-benchmark.json` retains 90 offline pipeline samples (30 each for Home/Base, Quest, and
Daily Quest) plus eight retained RT-010 live capture-command samples. Results:

- retained screenshot command: p50 1014.7722 ms, p95/max 1027.1039 ms;
- image decode: p50 11.5598 ms, p95 18.5211 ms, max 20.8826 ms;
- profile validation: p50 1.5984 ms, p95 1.8662 ms, max 2.0143 ms;
- full screen classification: p50 1023.0236 ms, p95 1383.6213 ms, max 1417.0655 ms;
- ROI OCR total: p50 305.8572 ms, p95 1352.3459 ms, max 1388.0392 ms;
- target/critical-ROI hashing: p50 14.5579 ms, p95 22.4432 ms, max 23.7521 ms;
- first policy: p50 0.0762 ms, p95 0.1268 ms, max 0.1515 ms;
- capture-completion to first policy: p50 1067.1063 ms, p95 1410.2460 ms, max 1443.6087 ms;
- exact-ROI immediate validation: p50 27.7787 ms, p95 42.1217 ms, max 43.1933 ms;
- second policy: p50 0.0739 ms, p95 0.1293 ms, max 0.2449 ms;
- capture-completion to second policy: p50 27.7803 ms, p95 42.1232 ms, max 43.1937 ms;
- mock transport invocation: p50 0.0002 ms, p95 0.0003 ms, max 0.0005 ms.

The corrected contract retains the 3.0-second proposal limit and introduces a separate 2.0-second
dispatch hard maximum. The dispatch limit exceeds measured full-validation p95 by about 0.59
seconds and the observed maximum by about 0.56 seconds; the exact-ROI fast path remains far below
it. Post-input observation remains separately bounded at ten seconds. Two total immediate-before
attempts are allowed in one prepared semantic action. Only `STALE_FRAME` before transport may use
the second attempt; every attempt and policy result is audited. Exhaustion cancels before dispatch,
never becomes unresolved, and never changes the dedupe key. No loop exists after transport.

Every capture now records screenshot-command start, successful capture completion, and decode
completion separately. Policy age uses `time.monotonic()` at successful capture completion only;
wall time remains audit/journal data and cannot affect freshness. Perception remains bound to the
exact frame SHA-256, RT-019 profile, and critical ROI hashes. OCR may be reused only when source,
target, overlay guard, profile, consequence, cost, quantity, and every required critical ROI are
unchanged and pixel-identical. A changed ROI forces fresh ROI OCR; changed semantics deny input.

Sixty-three deterministic tests pass across the existing core, new freshness/crash/reuse cases,
and injected transport adapter. The retained SQLite database remains schema version 1 with Cash
Mall confirmed, Home-to-Quest cancelled before dispatch, zero Home-to-Quest transport calls, no
nonterminal or unresolved action, and no lease. No Unraid, VM, ADB, game, container, tunnel, or
runtime-network access occurred during this correction.

## Resumed supervised run — reset-boundary stop

Read-only reconciliation confirmed commit `5bf6e54`, the expected eight metadata-only entries,
VM running on the selected VirtIO/VirGL profile with autostart disabled, Android boot complete,
logical `800x1280` at 160 dpi, nonblocking keyguard, game process absent, no prior task worker or
project listener/tunnel, and the restricted RT-017 qcow2/hash/profile-binding artifacts intact.
The fresh screenshot was the known Taskbar launcher. A temporary UID/GID-65534 worker used the
same read-only/capability-dropped/no-published-port boundary as the prior attempt. Its ADB server
was loopback-only at `127.0.0.1:5037` because the bundled ADB ignored the requested alternate
environment port; no pre-existing 5037 daemon was present.

Package launch reached positively recognized Cash Mall. Resumed action results:

1. `nav-cash-home-resume-002`: one tap `(107,32)`, `prepared → input_sent → confirmed`, positive
   Home/Base postcondition. Immediate policy age was 132 ms after fresh OCR.
2. `nav-home-quest-resume-002`: one tap `(330,1205)`, initially unresolved because Linux
   Tesseract missed the Daily tab. Three post frames and the current frame all had SHA-256
   `2ab2039bf71458e771a8927400b441d94467546568ce5363714da5b0f3465bda`, exactly matching promoted
   asset `m6-dq-quest-main-settled-v1`; independent replay recognized Quest and the Daily tab. The
   exact positive evidence reconciled the same action to confirmed without retry or another input.
3. `nav-quest-daily-resume-001`: a new immediate capture was pixel-identical to the static Quest
   frame. The old duplicate-hash guard cancelled before dispatch; transport calls were zero.
4. The binding was corrected and tested: freshness depends on newer monotonic capture completion,
   while OCR reuse binds to the prior frame hash, prior capture timestamp, and pixel-identical
   critical ROIs. An exact promoted Quest-reference hash is accepted before OCR fallback.
5. `nav-quest-daily-resume-002`: one tap `(400,104)`, `prepared → input_sent → confirmed`, positive
   Daily Quest postcondition. The immediate static capture reused bound OCR and reached policy in
   55 ms.

The resulting Daily Quest observation was positive at 800x1280 with six `Go` controls, no Claim,
zero points, incomplete rows, and reset countdown `00:08:33`. The reset-boundary stop fired before
scrolling, selecting Alliance Help/Supply Depot, Go, prerequisite execution, quest completion, or
Claim. No OS input, resource use, spend, account operation, or combat occurred.

Cleanup preserved the updated schema-v1 SQLite database and all frames/results, positively
reconciled the sole temporary unresolved action, released the lease, force-stopped the game,
stopped the task ADB server, removed the task worker and image tag, and verified no 5037/5042/5555
project listener or external tunnel. VM remains running; RT-017 modes/sizes remain intact. Final
journal state is zero unresolved, zero prepared/input_sent, and released lease. The task remains
Blocked only until the reset boundary passes and a new game day is positively reconciled.
