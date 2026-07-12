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
