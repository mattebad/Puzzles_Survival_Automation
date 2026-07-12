# M5-MAA — Policy-constrained MaaFramework evaluation

Recorded: 2026-07-12, America/Chicago

## Decision

**Rejected early.** MaaFramework has a credible feature set for image recognition, OCR/custom
recognition, ADB control, and declarative pipelines. It was not installed in the current worker,
no native SDK/library or CLI was present in the repository, and no project adapter connected its
pipeline/controller actions to the central fail-closed policy. The official project is primarily
native C++ with a larger ecosystem around OpenCV, FastDeploy, ONNX Runtime, Boost, ZeroMQ, and
Android capture/input components. Introducing that runtime would require a new packaging and
policy boundary before any identical-corpus measurement could be trusted.

The candidate was therefore rejected on the permitted early-rejection path. No package was
installed, no native binary was built, no ADB connection was made, and no game or OS input was
sent. Availability and source facts are in `availability.json`. Official reference:
[MaaFramework](https://github.com/MaaXYZ/MaaFramework).

## Criterion-by-criterion review

| Criterion | Decision | Evidence and reason |
|---|---|---|
| Candidate available in the current worker | Failed for viability | `availability.json`: no `maa` Python module, CLI, native SDK/library, or repository integration was present. No installation was attempted. |
| Identical corpus and representative flow | Blocked by early rejection | The same five-fixture corpus and Cash Mall-to-Home flow are identified, but no native runtime was introduced to execute it. This avoids presenting custom-stack results as Maa results. |
| Capture/profile enforcement | Rejected early | Maa has controller/capture capability, but no project adapter was available to enforce the locked `800x1280` profile before recognition and input. |
| Cash Mall, Ending Soon, Home/Base, detector, and OCR | Potentially capable, not demonstrated | Official sources document image recognition/OCR/custom recognition, but no identical-corpus measurement was possible. The incumbent already has the required multi-feature detector and ROI-specific OCR. |
| Stale/unknown/profile rejection | Rejected for integration | No Maa pipeline/resource wrapper maps stale frames, profile mismatch, unknown overlays, or unexpected successors to the project `UNKNOWN` state. |
| Policy gate and one-input/immediate-recapture semantics | Failed for integration | Maa pipeline/controller actions would need a project-owned authorization wrapper. Direct pipeline progression, generic watchers, or framework retries cannot bypass the central gate; no wrapper exists. |
| ADB reconnect behavior | Rejected early | Maa-specific reconnect behavior was not measured. RT-021 already proves the direct unprivileged worker path, so no untested second transport was justified. |
| Unprivileged Unraid packaging and resources | Failed for viability | No native Maa artifact or worker package was present. The official native ecosystem materially expands deployment and resource review beyond the incumbent; a clean unprivileged image was not demonstrated. |
| Logging/replay diagnostics | Potentially capable, not demonstrated | Maa’s pipeline ecosystem includes tooling and logs, but no measured diagnostic gain was available. The custom baseline already retains hashes, timings, annotations, and per-trial outcomes. |
| Testability and maintainability | Rejected early | A native runtime, binding/API layer, pipeline schema, resource bundle, and central-policy adapter would add multiple ownership boundaries before a benefit was shown. |
| SQLite scheduler/controller compatibility | Rejected early | The candidate’s task/pipeline execution model would need a narrow adapter to remain subordinate to the future SQLite scheduler and controller; a rewrite is prohibited and none was present. |

## Evidence-based rejection reasons

1. The candidate is absent from the approved worker image and repository; no native artifact or
   reproducible unprivileged package was available for a safe proof.
2. The official implementation and dependency ecosystem imply materially greater native packaging,
   ABI, and resource complexity than the incumbent already-proven Python/CV/OCR path.
3. Maa’s feature richness does not remove the need for the project’s explicit source recognition,
   stale/profile guards, immediate recapture, one-input limit, unknown-state handling, and
   SQLite/controller boundaries.
4. No policy adapter existed to prevent declarative/controller actions from executing outside the
   central gate. Enabling a generic pipeline runner would violate the task boundary.
5. No contrary measurement or benefit was established, so the candidate was rejected without live
   operations or an arbitrary trial count.

## Fallback, safety, and next task

- Maa may be reconsidered only if a later task supplies a pinned unprivileged worker artifact, a
  narrow central-policy adapter, replay-compatible resource schema, and evidence that its
  detector/OCR value materially exceeds the incumbent. Such reconsideration is not authorized in
  this run.
- No SSH, ADB, VM, game, account, credential, or input operation occurred.
- Rollback is removal of this task directory only; the custom baseline, Airtest rejection, MVP
  corpus, runtime, backup, and profile remain unchanged.
- Independent review confirmed the early-rejection boundary and found no unsupported Passed
  claim. The next ready task is M5-DECISION.
