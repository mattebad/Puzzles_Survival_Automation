# M6-DQ-BOOTSTRAP — Blocked bootstrap corpus decision

Recorded: 2026-07-12, America/Chicago

## Decision

**Blocked.** Fresh final-runtime bootstrap observations and offline recognition evidence were
retained, but the task cannot be Passed until the temporary worker and the result of the latest
Daily-tab navigation are reconciled. The private Unraid SSH connection closed during the
post-input command and subsequent TCP 22 checks failed. No input was retried.

M6 remains In Progress. `M6-DQ-TRANSITION-CORPUS` remains later work and no M7 or MVP task was
started.

## Captured states

- Safe Bliss launcher baseline.
- Authenticated Cash Mall startup reference and bounded Cash Mall-to-Home evidence.
- Final-runtime Home/Base with Quest entry target.
- Quest main screen with Daily Quest tab target.
- Daily Quest selected-tab screen with points `0`, reset countdown, incomplete objective rows,
  six visible `Go` controls, and a partially visible bottom row.
- No pre-existing Claim row was observed.
- No candidate prerequisite quest was actuated or observed to a stable destination; this is
  optional for bootstrap acceptance and remains unstarted.

All retained game frames are fresh final-runtime `800x1280` PNGs. The RT-019 profile is
`pns-blissos-poc-virgl-800x1280-v1` with content hash
`195c145e5779b13d1f65708a6b3ef31f6cbdb934b33854f886f1091aa583d742`.

## Criterion review

| Criterion | Decision | Evidence |
|---|---|---|
| Final-runtime Home/Base represented | Passed locally | `remote-cache/20260712-home-quest-nav/home-settled.png`; Home/Base replay passed. |
| Quest entry and Quest screen represented | Passed locally | `remote-cache/20260712-home-quest-nav/`; source/target gates and Quest replay retained. |
| Daily Quest selected tab represented | Passed locally | `remote-cache/20260712-daily-quest-tab/`; selected-tab frame and tab-input record retained. |
| Header, points, and reset evidence | Passed locally | `replay/daily-quest-recognition-immediate.json` and `daily-quest-recognition-patched.json`. |
| Incomplete rows and Go/non-claim controls | Passed locally | Six `Go` detections; visible progress remained `0/1`, `0/3`, or `0/250`. |
| Clipped/partial-row evidence | Passed locally | Bottom `Train Vehicle` row is partial; `clipped_rows_abstain=true`. |
| Confusing/ambiguous negative handling | Passed locally | `claim_input_authorized=false`, `ambiguous_rows_abstain=true`; detector defects retained. |
| Current RT-019/profile validation | Passed locally | `validate-runtime-profile.py` passed; replay used final-profile frames. |
| Final post-input state and temporary-worker cleanup | Blocked | `runtime-transport-blocker.md`; SSH closed and TCP 22 became unavailable. |
| No quest completion, Claim, Go, or spend input | Passed for retained evidence; latest worker reconciliation Blocked | No retained Claim/Go/action command exists; latest worker command result is unresolved but was only scoped to Daily-tab navigation. |

## Inputs

OS inputs: none in this task.

Retained game navigation inputs were limited to the already authorized Cash Mall back arrow,
Home-to-Quest, and Daily-tab selection. No quest objective, Claim, Go, purchase, offer, premium,
resource, account, or other gameplay action was sent. The latest worker's single Daily-tab
invocation cannot be confirmed after the SSH disconnect; no retry was sent.

## Evidence and rollback

- Evidence root: `evidence/sessions/20260712-m6-dq-bootstrap/`.
- Earlier orchestration failures and detector defects remain retained; none were filtered.
- The custom helper is `scripts/daily_quest_bootstrap.py`; no third-party framework was installed.
- No VM profile, qcow2, XML, network, runtime profile, or unrelated workload was modified.
- The VM was previously observed healthy and running; current worker/game/ADB cleanup cannot be
  confirmed while SSH/TCP 22 is unavailable.

## Exact resume condition

Restore the approved private Unraid SSH path. The first resumed operation must be read-only
reconciliation of the VM, device, worker, temporary ADB server, game process, and listeners.
Determine whether the latest Daily-tab input ran and clean up only task-scoped resources. Do not
repeat the Daily-tab input until its prior result is known. Do not begin
`M7-SAFE-ACTION-CORE`, `MVP-QUEST-TO-CLAIM`, or `M6-DQ-TRANSITION-CORPUS`.
