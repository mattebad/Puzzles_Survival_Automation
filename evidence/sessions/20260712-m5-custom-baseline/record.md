# M5-CUSTOM-BASELINE — Incumbent deterministic control stack

Recorded: 2026-07-12, America/Chicago

## Decision

**Passed as the incumbent baseline.** The existing Python + direct ADB + OpenCV + local OCR
implementation completed the representative startup benchmark using immutable replay fixtures,
mocks, dry-run annotations, and retained RT-010/RT-021/MVP live evidence. No live game or OS
input was sent during this task.

## Corpus

All fixtures are retained development/reference material from the passed MVP and earlier runtime
gates. The benchmark recorded SHA-256 hashes, dimensions, and decode results in
`benchmark.json`.

| Fixture | Expected role | Locked profile result |
|---|---|---|
| `evidence/sessions/20260711-rt-012-observe-soak/cash-mall-startup-reference.png` | Cash Mall positive | `800x1280`, accepted |
| `evidence/sessions/20260711-mvp-startup-normalization/remote-cache/20260711-cash-mall-observe-2120/frame-final.png` | allowlisted Ending Soon positive | `800x1280`, accepted |
| `evidence/sessions/20260711-mvp-startup-normalization/remote-cache/20260711-cash-mall-input-2125/frame-settled-after.png` | Home/Base negative to Cash Mall | `800x1280`, accepted |
| `evidence/sessions/20260711-mvp-startup-normalization/remote-cache/20260711-live-observe-2042/frame-before.png` | keyguard/launcher negative | `800x1280`, accepted |
| `examples/screenshots/IMG_5080.PNG` | incompatible profile negative | rejected by profile check |

## Criterion-by-criterion review

| Criterion | Decision | Retained evidence |
|---|---|---|
| Screenshot replay correctness and profile enforcement | Passed | `benchmark.json`: 100 replay operations; all 100 expected validity outcomes; all expected dimensions; 20 profile-mismatch fixtures rejected. |
| Capture/classification validation set | Passed | `benchmark.json`: 100 classifications, 100/100 expected outcomes; Cash Mall, allowlisted Ending Soon, Home/Base, keyguard/launcher, and profile-mismatch cases each ran 20 times. |
| Cash Mall and Ending Soon recognition | Passed | The clean Cash Mall and explicitly allowlisted Ending Soon fixtures were recognized in all 40 trials; unknown overlays remain fail-closed in the helper. |
| Home/Base recognition and OCR | Passed | `benchmark.json`: 10/10 independent `classify_home_base_live` calls passed using only the demonstrated scene/navigation ROIs; p50/p95/max OCR latency was 948.931/1485.141/1485.141 ms. |
| Target ROI detection and dry-run annotation | Passed | 25/25 trials produced exact ROI `[35, 0, 180, 65]`; 25 PNG annotations are retained under `annotations/`; purchase, offer, premium-currency, and confirmation controls were never authorized. |
| Stale/profile-mismatch/unknown rejection | Passed | Policy mock denied stale, unstable, overlapping, repeated, and unknown-source cases; the incompatible iOS/reference frame was rejected before feature use. |
| Policy-gate and one-input semantics | Passed | `benchmark.json`: fresh-positive was the only authorized policy case; repeated input and stale/immediate-recapture violations were denied; zero benchmark input commands were sent. The prior MVP gate retained exactly one supervised tap and immediate recapture in `20260711-cash-mall-input-2125/`. |
| Safe gesture resolution | Passed | 10 offline keyguard-resolution trials: exactly one authorization, nine repeat-denials, zero inputs. The known keyguard branch requires boot complete, secure=false, positive visual match, game stopped, and swipe_count=0. |
| ADB reconnect behavior | Passed with scope limitation | Five safe mock reconnect cycles passed; retained RT-021 proves the unprivileged direct private worker path and post-restart reconnect, with no external tunnel or public ADB. Additional live cycles are deferred to selected-adapter validation. |
| Packaging and resource boundary | Passed | RT-021 retained UID 65534 worker, dropped capabilities, no-new-privileges, bounded CPU/memory/PIDs, read-only ADB mount, no Docker socket, no published ports, and the documented host-network limitation. The incumbent adds no framework dependency. |
| Logging, replay diagnostics, testability, and maintainability | Passed | Per-trial outcomes, fixture hashes, timing distributions, annotation hashes, policy cases, and limitations are retained in `benchmark.json`; the adapter is a small importable helper with no hidden watcher/retry behavior. |
| SQLite scheduler/controller compatibility | Passed | The helper remains transport/classification/policy-contract scoped and does not own scheduler, persistence, task, or controller state; future SQLite integration can call it behind the central policy gate. |

## Measurements

- Replay decode: 100 operations; p50/p95/max `13.4999 / 51.4715 / 54.5985 ms`. This is local
  immutable PNG replay timing, not live ADB capture latency.
- Classification: 100 operations; p50/p95/max `8.4673 / 10.6073 / 28.5165 ms`; 100/100
  expected outcomes.
- Target resolution: 25/25 exact back-arrow ROI annotations.
- OCR: 10/10 Home/Base recognitions; p50/p95/max `948.9313 / 1485.1412 / 1485.1412 ms`.
- Retained live ADB capture fact: RT-010 p95 `1026.136 ms` for valid `800x1280` frames.
- Reconnect: five safe mocks plus the retained RT-021 passed direct-worker restart/reconnect.

## Packaging, policy, and known limitations

The incumbent uses the existing Python/OpenCV/numpy/pytesseract surface and direct ADB contract;
there is no Airtest or MaaFramework runtime dependency and no framework-owned input or retry
loop. The future worker must preserve the RT-021 unprivileged/container boundary and keep ADB
private. OCR is intentionally ROI-specific and relatively slow; production recognition assets
still require the M6 final-runtime corpus gate. The replay harness does not claim to replace a
future selected-adapter live validation set.

## Review, rollback, and next task

The independent review compared every acceptance criterion with `benchmark.json`, the 25 retained
annotations, RT-010/RT-021 records, the passed MVP gate/input evidence, validation commands, and
the repository diff. No unsupported baseline claim remains. Rollback requires removing only
`scripts/m5_benchmark_custom.py` and this task directory; no VM, game, ADB, backup, profile, or
unrelated worktree file was changed. The next ready task is M5-AIRTEST.
