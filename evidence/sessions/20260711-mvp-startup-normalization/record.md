# MVP-STARTUP-NORMALIZATION — Passed after guarded startup reconciliation

Recorded: 2026-07-11, America/Chicago

## Final resumed decision

The startup-normalization MVP is **Passed**. The resumed fresh observation found the known Android
surface already reconciled to a safe launcher (`showing=false`, `secure=false`,
`mInputRestricted=false`), so no additional keyguard swipe or HOME input was sent. The durable
helper now contains a fail-closed classifier for the known non-secure keyguard, one-swipe
authorization, allowlisted-banner handling, and final-profile Home/Base verification.

The verified package launch reached Cash Mall. The specific informational `Ending Soon` sale banner
was positively allowlisted after the user clarified its meaning; it did not overlap the back-arrow
ROI. A fresh precheck and immediate pre-input recapture both passed Cash Mall recognition and ROI
stability. Exactly one bounded tap at `(107,32)` was sent to the recognized top-left arrow. The
settled after-frame passed independent final-profile Home/Base checks for resource header, base
scene/building labels, bottom navigation/OCR anchors, non-Cash-Mall source, and non-blocking OS
policy. No purchase, spend, account, or unintended gameplay action occurred.

## Final criterion-by-criterion review

| Criterion | Decision | Evidence |
|---|---|---|
| Known non-secure keyguard reconciled safely | Passed | `keyguard-live-observe-results.json`; fresh launcher frame and policy proved `showing=false`, `secure=false`, `mInputRestricted=false`; no additional swipe was needed or sent in the resumed run. |
| Guarded keyguard branch implemented fail-closed | Passed | `scripts/startup_normalization.py`; keyguard fixture authorization, Cash Mall/launcher abstention, one-swipe count guard, and immediate launcher policy/focus checks. |
| Launch reached positively recognized Cash Mall | Passed | `remote-cache/20260711-cash-mall-observe-2112/frame-launch-30.png`; settled Cash Mall layout and title. |
| Informational overlay handled safely | Passed | `cash-mall-ending-soon-allowlist-results.json`; only the final-profile `Ending Soon` banner fixture is allowlisted and target non-overlap is enforced. |
| Immediate pre-input source/target verification | Passed | `live-precheck-classification.json`, `live-input-before-classification.json`, `target-annotation-precheck.png`, `target-annotation-input-before.png`; back-arrow similarity 1.0, title 0.995065, offer-header 1.0. |
| Exactly one supervised no-spend back-arrow input | Passed | `remote-cache/20260711-cash-mall-input-2125/input-command-record.txt`; one `input tap 107 32`, no retry. |
| Positive Home/Base postcondition | Passed | `home-base-postcondition.json`; final `800x1280` frame passed resource header, scene, navigation, OCR, and Cash Mall-negative checks. |
| No spend or unintended gameplay consequence | Passed | Before/after frames, activity/policy dumps, single-input record, and cleanup evidence; no purchase/offer/price/premium/confirmation control selected. |
| Evidence, cleanup, and rollback integrity | Passed | Complete cache-backed worker outputs retained; game force-stopped; temporary worker removed; VM/runtime/qcow2/XML unchanged. |

## Prior attempt decision — Blocked at Android keyguard boundary

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

## Resumed live evidence

- Resumed preflight: `preflight-resume.md`.
- Keyguard observe-only worker: `remote-cache/20260711-keyguard-reconcile-observe-2055/`; fresh
  frame SHA-256 `D0CE880D8ED48345D5F3AFBD46A74A3C16E100E88FF8863A2E671F468573FE75`, valid
  `800x1280`, boot complete, safe launcher policy/focus/visual checks passed.
- Launch observations: `remote-cache/20260711-cash-mall-launch-2110/` (loading at 15 seconds),
  `remote-cache/20260711-cash-mall-observe-2112/` (Cash Mall with banner),
  `remote-cache/20260711-cash-mall-observe-2115/` (same banner geometry), and
  `remote-cache/20260711-cash-mall-observe-2120/` (final overlay fixture).
- Gated input worker: `remote-cache/20260711-cash-mall-input-2125/`; precheck, immediate-before,
  immediate-after, settled-after, policy, activity, exact-input, and cleanup artifacts retained.
- The final separate SSH cleanup query was rejected by the session tool-usage limit and was not
  retried. The worker's retained `cleanup-state.txt`, `gate-state.txt`, ADB disconnect/kill log,
  and container-removal evidence are the authoritative last-known cleanup state.
- Settled Home/Base candidate: `home-base-candidate-manifest.json`, bound to
  `pns-blissos-poc-virgl-800x1280-v1`; it is a development candidate, not yet a production corpus
  asset.

## Resumed keyguard input result

- Exact keyguard inputs sent during the resumed run: none. The user/manual reconciliation had
  already cleared the known non-secure surface before the fresh capture; no additional swipe or
  HOME input was necessary or authorized.
- Exact game input sent: one `adb ... shell input tap 107 32`, recorded in the gated worker
  evidence. No other game input was sent.

## Reference and rollback

- `reference-manifest.json` labels Cash Mall and supplied Home/Base material as development/reference
  only. The iOS Home/Base frame is not a production recognition asset.
- `scripts/startup_normalization.py` is fail-closed: profile mismatch, missing Home/Base reference,
  stale/unknown source, and feature failure return `UNKNOWN`; no ADB or input transport is embedded.
- Rollback is complete: the game remains force-stopped, temporary workers/ADB servers are removed,
  no VM XML/qcow2/network/display/runtime profile was modified, and all failure evidence remains.

## Exact user action required

None. The resumed observe-only capture found the keyguard already cleared and the supervised
Cash Mall-to-Home/Base transition passed. No credentials, account switching, profile navigation,
or server/state action was used.

## Next step

MVP-STARTUP-NORMALIZATION is closed Passed. Do not begin Daily Quest in this run. M5 framework
bake-off is the later backlog next task and remains outside this task boundary.
