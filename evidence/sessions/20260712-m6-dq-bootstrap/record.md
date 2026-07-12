# M6-DQ-BOOTSTRAP — Passed bootstrap corpus decision

Recorded: 2026-07-12, America/Chicago

## Decision

**Passed.** The prior Daily-tab navigation was confirmed from retained before/input/immediate-after
and settled evidence. A fresh observe-only reconciliation positively recognized the selected
Daily Quest screen. One bounded list scroll then produced stable overlap evidence with additional
incomplete rows. All executable bootstrap assets passed the RT-019 profile and frame validator.

M6 remains In Progress. `M6-DQ-TRANSITION-CORPUS` remains later work and no M7 or MVP task was
started.

## Captured states

- Safe Bliss launcher baseline.
- Authenticated Cash Mall startup reference and bounded Cash Mall-to-Home evidence.
- Final-runtime Home/Base with Quest entry target.
- Quest main screen with Daily Quest tab target.
- Daily Quest selected-tab screen with points `0`, reset countdown, incomplete objective rows,
  six visible `Go` controls, and a partially visible bottom row.
- Fresh settled post-scroll Daily Quest screen with additional incomplete rows and six visible
  `Go` controls.
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
| Scroll overlap/end-of-list evidence | Passed | `replay/daily-scroll-fingerprint.json`; one bounded upward scroll revealed new rows and retained stable header/tab/progress evidence. |
| Executable asset metadata and profile compatibility | Passed | `assets/asset-manifest.json`; six assets passed `validate-assets`, including the explicit Go-not-Claim negative. |
| Stale, mismatched-profile, corrupt, and black-frame rejection | Passed | Synthetic manifests and frame fixtures rejected with nonzero validation outcomes. |
| Final post-input state and temporary-worker cleanup | Passed | Fresh reconciliation frame positively recognized Daily Quest; all three task-scoped workers were inspected, evidence preserved, removed, and no M6 listener remained. |
| No quest completion, Claim, Go, or spend input | Passed | Only startup normalization, Home-to-Quest, Daily-tab selection, and one bounded list scroll were recorded; no Claim/Go control was actuated. |

## Inputs

OS inputs: none in this task.

The resumed task sent exactly one bounded Daily Quest list scroll after fresh positive recognition
and immediate pre-input recapture: `input swipe 400 1080 400 600 500`. The retained bootstrap run
also contains the authorized Cash Mall back arrow, Home-to-Quest, and one Daily-tab selection.
No quest objective, Claim, Go, purchase, offer, premium, resource, account, or other gameplay
action was sent.

## Evidence and rollback

- Evidence root: `evidence/sessions/20260712-m6-dq-bootstrap/`.
- Earlier orchestration failures and detector defects remain retained; none were filtered.
- The custom helper is `scripts/daily_quest_bootstrap.py`; no third-party framework was installed.
- Promoted executable assets are under `assets/`, with reference-only Cash Mall material retained
  under the startup evidence and not promoted as Daily Quest assets.
- No VM profile, qcow2, XML, network, runtime profile, or unrelated workload was modified.
- The VM was observed running with Android boot complete, `800x1280` logical display, density 160,
  nonblocking keyguard, and the game activity foreground during fresh reconciliation. Cleanup
  force-stopped the game, removed all task-scoped workers, stopped their temporary ADB servers,
  and left only the pre-existing loopback ADB server on `127.0.0.1:5037`.

## Historical blocker records

The initial SSH loss, unresolved worker boundary, and later failed resume attempt remain retained
in `runtime-transport-blocker.md` and `resume-reconciliation-20260712.md`. They were resolved by
the subsequent successful read-only reconciliation and retained worker evidence; no input was
retried.

## Resume attempt

The later successful reconciliation confirmed the prior Daily-tab input and allowed safe cleanup.

## Next boundary

M6-DQ-BOOTSTRAP is closed. M6 remains incomplete until `M6-DQ-TRANSITION-CORPUS` later passes.
`M7-SAFE-ACTION-CORE` is the next ready task; it was not started in this run.
