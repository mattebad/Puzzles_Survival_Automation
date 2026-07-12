# M6-DQ-BOOTSTRAP — Preflight and blocker

Recorded: 2026-07-12, America/Chicago

## Task preflight

- Task ID: `M6-DQ-BOOTSTRAP`
- Objective: build and validate the final-runtime Daily Quest bootstrap corpus without
  completing a quest, claiming a reward, or sending any gameplay input.
- Dependencies: M5 Passed; RT-019 Passed; MVP-STARTUP-NORMALIZATION Passed.
- Acceptance criteria: fresh final-runtime `800x1280` PNG assets; current RT-019 profile metadata;
  validator rejection for missing/mismatched metadata; Home/Base, Quest, Daily Quest, incomplete,
  Go/non-claim, clipped, stale, unknown, and confusing-negative coverage; abstention on ambiguity;
  zero false Claim authorization; no quest completion, Claim input, spend, or unintended gameplay.
- Intended operations: read-only Unraid/VM/game/ADB reconciliation; then bounded observe-only
  capture and positively recognized no-spend navigation through Home/Base → Quest → Daily Quest;
  capture and label only bootstrap states; run offline replay and metadata/asset validation; clean
  temporary workers and leave the game force-stopped or in the documented safe state.
- Verification procedure: check VM/game/ADB/worker/tunnel/listener/backup state; capture fresh
  profile-bound frames; validate PNG integrity, dimensions, metadata, labels, ROIs, forbidden
  regions, and fail-closed Claim/Go/clipped/ambiguous behavior; replay the corpus; perform a
  criterion-by-criterion review; verify cleanup and repository diff.
- Evidence directory: `evidence/sessions/20260712-m6-dq-bootstrap/`.
- Rollback procedure: retain all captures and failures; remove only temporary observer workers,
  local ADB instances, tunnels, and unpromoted task assets; force-stop the game; do not modify VM
  XML, qcow2, runtime profile, or network configuration.
- Permissions required: repository write access for task evidence, backlog/handoff/plan updates,
  and one task-scoped commit; approved read-only Unraid SSH administration; private worker-to-VM
  ADB observation; bounded no-spend navigation only after fresh source/target authorization.
- Expected credential/manual dependency: the approved Unraid administrative credential must be
  available to the process-only `UNRAID_TEMP_PASSWORD` mechanism. No login, account, profile,
  server/state, tutorial, CAPTCHA, or quest-completion manual action is authorized for this task.

## Initial reconciliation result

- Repository commit `91227c7` is present and `M6-DQ-BOOTSTRAP` was the sole Ready task at
  preflight start; it is now recorded as Blocked below.
- The eight pre-existing unstaged evidence/script entries were hash-compared to `HEAD`; every
  working hash matches its `HEAD` blob. They remain untouched and unstaged.
- The pinned Unraid host was reachable, but the non-interactive shell process had no
  `UNRAID_TEMP_PASSWORD`; Windows Credential Manager contained no stored credential.
- A password-authenticated SSH reconciliation could not be performed without placing the supplied
  password in a recorded command line or durable artifact. No authenticated Unraid command was
  executed. No VM, game, ADB, worker, tunnel, listener, or backup state was changed.

## Decision

`M6-DQ-BOOTSTRAP` is **Blocked** at the approved-credential availability boundary. No corpus
capture, game navigation, quest completion, Claim input, spend, or gameplay action occurred.

## Exact user action required

Make the already-provided Unraid password available to the current process through the transient
`UNRAID_TEMP_PASSWORD` environment mechanism, without placing it in the repository, evidence,
scripts, logs, or command history. Resume this same task; the first resumed live operation must be
read-only Unraid/runtime reconciliation.
