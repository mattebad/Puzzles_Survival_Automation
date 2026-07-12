# MVP-STARTUP-NORMALIZATION — Blocked at Android keyguard boundary

Recorded: 2026-07-11, America/Chicago

## Decision

The startup-normalization MVP is **Blocked**, not Passed or Rejected. Offline Cash Mall
recognition and dry-run target annotation passed. The direct Unraid worker produced fresh valid
`800x1280` observations, but the approved OS-only keyguard reconciliation did not expose the game:
the policy retained `showing=true`, `secure=false`, and `mInputRestricted=true`, while the fresh
after-frame remained the Android unlock/setup surface with `com.farmerbb.taskbar` focused. The
mandatory unresolved-OS/keyguard stop condition therefore prevented game launch, Cash Mall source
authorization, and the supervised back-arrow trial.

No game input, purchase, offer, premium-currency, confirmation, account, credential, profile,
server/state, login, tutorial, or Daily Quest action occurred.

## Criterion-by-criterion review

| Criterion | Decision | Evidence |
|---|---|---|
| Offline/reference Cash Mall recognition with multiple positive features | Passed | `offline-results.json`; retained 800x1280 Cash Mall reference passed title-region, back-arrow, premium header, mall header, mall context, and purchase-context features. |
| Live observe-only classification from fresh 800x1280 frame | Blocked | `remote-cache/20260711-live-observe-2042/frame-before.png` and `frame-after.png` are valid fresh frames, but both classify `UNKNOWN`; the source is Android keyguard/launcher, not Cash Mall. `live-observe-classification.json` retains scores and hashes. |
| Dry-run target annotation | Passed | `dry-run-annotation.png` marks only the recognized top-left back-arrow ROI in green; purchase/offer/premium regions are explicitly denied and marked red. |
| One supervised no-spend back-arrow tap | Blocked | Source Cash Mall and immediate target stability could not be established; no game tap was sent. |
| Positive Home/Base postcondition | Blocked | No game transition occurred and no final locked-runtime Home/Base reference is available. The iOS development/reference Home/Base screenshot was rejected as profile-incompatible. |
| Safe stop, no Daily Quest continuation, and cleanup | Passed | The task stopped at the OS guard; game remained force-stopped; temporary worker was removed; no Daily Quest or gameplay action ran. |

## Fresh worker evidence

- Cache-backed source: `/mnt/cache/puzzle-survival-runtime/mvp-startup-normalization/20260711-live-observe-2042/`.
- Repository copy: `remote-cache/20260711-live-observe-2042/`.
- Container ID: `95041e10aca404577b3051e41912a5881c8ae7fbb62ab86b8fa5574872d9bf86`.
- Worker identity: UID/GID `65534:65534` (`nobody:nogroup`).
- Image: `monarch-gpt-wrapper-api:latest`; container was host-networked only for the private
  guest path, with read-only root, all capabilities dropped, no-new-privileges, 64-PID limit,
  256 MiB memory limit, 0.5 CPU limit, read-only ADB mount, writable task evidence mount, and no
  Docker socket or published port.
- Local ADB server: temporary container port `5040`; guest endpoint `192.168.122.79:5555`.
- ADB log: device connection succeeded; worker exit code `0`; temporary container removed.
- Observation window: `2026-07-12T01:44:44+00:00` to `2026-07-12T01:44:45+00:00`.
- `frame-before.png`: 266239 bytes, `800x1280`, SHA-256
  `5F52D94818EB7ACE6383BF9AE453562E72C6C28AE258BCE918207ADFDEA6567A`.
- `frame-after.png`: 264831 bytes, `800x1280`, SHA-256
  `824345A44C67B17D303F3B47D3BE24AD8E0BB70862F01BA65E819F76F7DE4BFA`.

## Keyguard evidence

- `policy-before.txt` and `policy-after.txt` both report `KeyguardServiceDelegate showing=true`,
  `secure=false`, and `KeyguardStateMonitor mInputRestricted=true`.
- `frame-before.png` shows the Android setup/notification surface; `frame-after.png` shows the
  Android unlock/setup surface with no game UI.
- `activities.txt` reports `com.farmerbb.taskbar/com.farmerbb.taskbar.activity.HomeActivityDelegate`
  as the focused window; `com.global.ztmslg` was not launched.
- The only device input commands were the already-approved OS reconciliation sequence:
  `KEYCODE_WAKEUP`, keyevent `82`, and `cmd window dismiss-keyguard`. No game input occurred.

## Failed attempts and revised hypotheses

1. Evidence bind mount used an invalid Docker `rw` field; failure retained in
   `orchestration-failure-1.md`. Revised to omit the default read-write field.
2. Corrected mount attempt started as UID 65534 but ADB aborted because `HOME=/nonexistent` could
   not create `.android`; complete output and inspect data retained under
   `remote-cache/20260711-live-observe-2039/` and summarized in `orchestration-failure-2.md`.
3. Setting `HOME=/tmp` fixed worker initialization and direct ADB observation. The remaining
   blocker is the external Android keyguard/setup state, not worker transport.

## Reference and rollback

- `reference-manifest.json` labels Cash Mall and supplied Home/Base material as development/reference
  only. The iOS Home/Base frame is not a production recognition asset.
- `scripts/startup_normalization.py` is fail-closed: profile mismatch, missing Home/Base reference,
  stale/unknown source, and feature failure return `UNKNOWN`; no ADB or input transport is embedded.
- Rollback is complete: the game remains force-stopped, temporary workers/ADB servers are removed,
  no VM XML/qcow2/network/display/runtime profile was modified, and all failure evidence remains.

## Exact user action required

Manually clear or confirm the non-secure Android keyguard/setup surface until the approved runtime
startup guard reports a safe, unrestricted game-launch surface. Do not enter credentials, switch
accounts, navigate profiles, or change server/state. Resume this same task only after that manual
OS-state action; the first resumed live operation must be observe-only capture.

## Next step

No later milestone is authorized in this run. Resume `MVP-STARTUP-NORMALIZATION` after the exact
manual OS action above; then recapture the final locked runtime, require positive Cash Mall and
Home/Base recognition, and reconsider one supervised no-spend back-arrow trial from a fresh frame.
