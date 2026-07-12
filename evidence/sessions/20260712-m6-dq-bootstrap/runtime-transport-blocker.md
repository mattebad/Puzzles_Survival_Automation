# M6-DQ-BOOTSTRAP — Live transport blocker

Recorded: 2026-07-12, America/Chicago

## Decision

M6-DQ-BOOTSTRAP is **Blocked**, not Passed. The final-runtime bootstrap work produced fresh
`800x1280` launcher, Home/Base, Quest, and Daily Quest observations and the Daily Quest
classifier passed the retained settled frame after the ROI correction. The task cannot be
closed because the fresh worker's post-input result and cleanup could not be verified after the
SSH connection closed unexpectedly.

No Claim, Go, quest-completion, spend, resource, account, credential, profile, server/state,
login, tutorial, CAPTCHA, or gameplay-action input was authorized or recorded. The only
task-scoped game navigation target was the Daily Quest tab.

## Retained live evidence

- `remote-cache/20260712-resume-observe/` — fresh safe launcher baseline and force-stop cleanup.
- `remote-cache/20260712-cash-mall-launch/` — authenticated Cash Mall startup observations.
- `remote-cache/20260712-cash-mall-input/` — one bounded Cash Mall-to-Home normalization tap and
  positive Home/Base result.
- `remote-cache/20260712-home-quest-nav/` — one bounded Home-to-Quest navigation and Quest
  observation.
- `remote-cache/20260712-daily-quest-tab/` — one retained Daily-tab tap at `400,105`, immediate
  and settled Daily Quest frames, incomplete rows, Go controls, and a clipped bottom row.

The retained Daily-tab worker evidence contains no Claim or Go input. The visible rows were
incomplete (`0/1`, `0/3`, or `0/250`) and showed `Go`; no pre-existing Claim row was observed.

## Unresolved boundary

A fresh worker was staged from a positively recognized Quest frame and a pre-input gate for the
Daily Quest tab was recorded. The first remote invocation attempt was rejected locally by
PowerShell quoting before reaching Unraid. The corrected single invocation connected, then
reported `FATAL ERROR: Remote side unexpectedly closed network connection` before returning a
normal completion status. A subsequent read-only SSH probe failed the TCP 22 check for both
`nas.local` and `192.168.50.92`.

It is therefore unknown whether the fresh worker sent its one Daily-tab tap, captured its
immediate/settled after-frames, or completed force-stop and worker cleanup. No retry was sent.
The live result and temporary-worker state must be reconciled by a future read-only SSH check
before this task can be Passed.

## Offline detector result

`replay/daily-quest-recognition-patched.json` passed with `DAILY_QUEST`, positive title and
points/reset evidence, six `Go` controls, a clipped/partial bottom row, and
`claim_input_authorized=false`. The earlier detector failures remain retained in
`detector-defect-1.md` and `detector-defect-2.md`.

## Required resume action

Restore the approved private Unraid SSH path, then begin with read-only host/container/device
reconciliation. Do not repeat the Daily-tab input until the fresh worker's command and cleanup
state are positively reconciled. Do not begin M7-SAFE-ACTION-CORE, MVP-QUEST-TO-CLAIM, or
M6-DQ-TRANSITION-CORPUS.
