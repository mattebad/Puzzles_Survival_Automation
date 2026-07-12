# M5 final framework decision — Passed

Recorded: 2026-07-12, America/Chicago

## Decision

**M5 Passed. Select the custom Python + direct ADB + OpenCV + local OCR stack.** It is the
lowest-complexity candidate that already meets the project’s representative startup safety
contract and has measured replay, target, OCR, policy, packaging, and retained live transport
evidence. Airtest and MaaFramework were rejected early on evidence-backed packaging and policy
integration grounds; neither was installed or run against the live VM.

The selected stack’s exact role is:

- private Unraid worker-to-VM ADB capture/transport under the RT-021 boundary;
- explicit `800x1280` profile and freshness validation;
- OpenCV multi-feature recognition for Cash Mall, the allowlisted Ending Soon informational
  overlay, Home/Base, and unknown negatives;
- local OCR only for demonstrated Home/Base scene/navigation ROIs;
- project-owned fail-closed policy and one-input/immediate-recapture semantics.

The future SQLite scheduler/controller remains a separate M7 concern. Framework code may not own
task progression, generic watchers, retries, or input authorization.

## Benchmark methodology and comparison

Every candidate was compared against the same retained startup corpus and representative flow:
startup observation, Cash Mall classification, allowlisted Ending Soon handling, back-arrow target
resolution, dry-run annotation, bounded postcondition review, and unknown-state refusal. Offline
replay, mocks, and annotations were preferred; no repeated live Cash Mall taps were manufactured.

| Candidate | Result | Measurements / reason |
|---|---|---|
| Custom Python/direct ADB/OpenCV/local OCR | Selected | 100 replay captures and 100 classifications; 100/100 expected outcomes; 25/25 exact target annotations; 10/10 OCR; 10 gesture mocks; 5 reconnect mocks; retained RT-010 live capture p95 1026.136 ms and RT-021 reconnect proof. |
| Airtest | Rejected early | Module/CLI absent; official install/dependency surface would add a separate Python framework and direct simulated-input API without a project policy adapter. No measurable benefit justified mutation. See `evidence/sessions/20260712-m5-airtest/`. |
| MaaFramework | Rejected early | Native/package adapter absent; official native/pipeline ecosystem would add a new packaging, ABI/resource, and policy boundary. Potential features were not treated as measured results. See `evidence/sessions/20260712-m5-maa/`. |

Custom baseline timing was p50/p95/max `13.4999/51.4715/54.5985 ms` for local replay decode,
`8.4673/10.6073/28.5165 ms` for classification, and `948.9313/1485.1412/1485.1412 ms` for
the ROI-specific OCR calls. Replay values are explicitly not live ADB latency. The full per-trial
hashes, annotations, policy cases, and limitations remain in
`evidence/sessions/20260712-m5-custom-baseline/benchmark.json`.

## Packaging and policy implications

The selected path retains the already-proven unprivileged worker shape: UID 65534, read-only root
and ADB mount, dropped capabilities, no-new-privileges, bounded CPU/memory/PIDs, no Docker socket,
no public ADB, and no external SSH tunnel dependency. Airtest would add package/dependency and
version-resolution risk. MaaFramework would add native binaries/bindings, pipeline resources,
and ABI/resource packaging. Both would still need to call the same project-owned policy gate, so
neither reduces the required safety architecture.

The selected policy behavior is fail-closed: stale or mismatched frames, unknown overlays,
profile mismatch, target overlap, repeated input, timeout, and unexpected successors become
`UNKNOWN` or a blocker. A future authorized input must be preceded by positive source/target
recognition and immediate recapture. No framework default watcher or retry is allowed.

## Reconnect, maintainability, limitations, and fallback

Reconnect behavior uses the RT-021 direct-private worker path and revalidates device/profile/state
before any future action. The M5 baseline added five safe reconnect mocks; it did not repeat live
runtime operations. The custom stack has fewer deployment and ownership boundaries and already
produces deterministic replay artifacts, hashes, timing, annotations, and policy decisions.

Known limitations are retained: replay timing is not live ADB timing; ROI OCR is comparatively
slow; M6 must replace development/reference images with final locked-runtime assets; RT-021’s
host-network fallback remains explicit; and account identity evidence remains a later RT-016A/M7
gate. Reconsider Airtest or MaaFramework only if a future task supplies a pinned unprivileged
package, central-policy adapter, identical-corpus pass, reconnect proof, and a measurable benefit
over the selected stack.

## Authorization and review

M5 authorizes proceeding to M6 final-runtime production corpus capture and replay validation using
the selected custom stack. This authorization does not start M6 in this run and does not authorize
Daily Quest, purchases, unattended gameplay, account/profile navigation, or any new live input.

Independent review matched every M5 acceptance item to the three candidate records, the baseline
JSON, retained RT-010/RT-021/MVP evidence, the final runtime profile, and the repository diff.
No unsupported candidate pass or comparative claim remains. Rollback is intact; all candidate
evidence and rejected attempts are preserved.
