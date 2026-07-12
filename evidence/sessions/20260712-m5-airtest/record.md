# M5-AIRTEST — Policy-constrained Airtest evaluation

Recorded: 2026-07-12, America/Chicago

## Decision

**Rejected early.** Airtest was not installed in the current worker environment and no Airtest
CLI or project adapter was present. The official package requires a separate pip installation and
its current requirements add a broad dependency surface, including `numpy<2.0`,
`opencv-contrib-python<=4.6.0.66`, desktop/device packages, and reporting/media dependencies.
Installing or resolving those dependencies was outside this repository-only task boundary and
would have changed the worker packaging before policy integration was proven. The identical
corpus was therefore reviewed for viability, but no meaningless live or repeated game trials
were manufactured.

Supporting availability and source facts are in `availability.json`. Official references:
[Airtest repository](https://github.com/AirtestProject/Airtest) and its
[requirements file](https://github.com/AirtestProject/Airtest/blob/master/requirements.txt).

## Criterion-by-criterion review

| Criterion | Decision | Evidence and reason |
|---|---|---|
| Candidate available in the current worker | Failed for viability | `availability.json`: Python module, CLI, and `pip show airtest` were absent. No installation was attempted. |
| Identical corpus and representative flow | Blocked by early rejection | The same five-fixture corpus and Cash Mall-to-Home flow are identified, but Airtest operations were not run because the candidate could not be packaged or policy-wrapped in scope. |
| Capture/profile enforcement | Rejected early | Airtest would add a device/capture layer before the project’s existing explicit `800x1280` guard; no project adapter exists to prove the required enforcement. |
| Cash Mall, Ending Soon, Home/Base, detector, and OCR | Rejected early | Airtest’s image/assertion surface was not enough to replace the existing multi-feature classifier and ROI-specific local OCR; its listed requirements do not provide the project’s OCR contract. No measurable benefit was established. |
| Stale/unknown/profile rejection | Rejected early | No Airtest adapter maps stale frames, profile mismatch, unknown overlays, or unexpected successors to the project’s `UNKNOWN` state. The custom baseline already passed these cases. |
| Policy gate and one-input/immediate-recapture semantics | Failed for integration | Official APIs expose simulated touch/swipe/keyevent operations, but no central-policy wrapper exists in the candidate. Direct calls would violate the project boundary; generic watchers/retries remain prohibited. |
| ADB reconnect behavior | Rejected early | Airtest-specific reconnect behavior was not measured. RT-021 already proves the direct unprivileged worker path, so no benefit justified adding an untested transport layer. |
| Unprivileged Unraid packaging and resources | Failed for viability | The current worker has no Airtest package. The official dependency list materially expands packaging and includes version constraints that overlap the existing CV stack. A clean unprivileged image was not demonstrated. |
| Logging/replay diagnostics | Rejected early | Airtest reports may be useful, but the custom baseline already retains per-trial JSON, hashes, timing, and annotations. No measured diagnostic gain was available without installing the candidate. |
| Testability and maintainability | Rejected early | Introducing a second capture/input/recognition abstraction plus a required policy wrapper would duplicate the incumbent path before any benefit was proven. |
| SQLite scheduler/controller compatibility | Rejected early | Airtest would need an adapter boundary before it could integrate with the future scheduler/controller; adopting direct `.air` actions would couple task execution to framework behavior. |

## Evidence-based rejection reasons

1. The candidate is absent from the approved worker image and cannot be evaluated without a
   dependency/package mutation that this task did not authorize.
2. The official dependency surface is substantially larger than the incumbent’s already-working
   OpenCV/numpy/pytesseract path, including an older OpenCV upper bound and additional desktop,
   media, and device packages.
3. The candidate’s direct simulated-input API would require a project-owned authorization wrapper;
   no such wrapper was present, so policy-gate integration could not pass.
4. The candidate does not remove the demonstrated need for final-profile multi-feature detection,
   ROI-specific OCR, stale-frame handling, immediate recapture, or SQLite/controller boundaries.
5. The incumbent has retained live ADB capture/reconnect evidence and a passed no-spend startup
   slice; Airtest produced no contrary measurement or benefit.

## Safety, rollback, and next task

- No SSH, ADB, VM, game, account, credential, or input operation occurred.
- No package was installed, no worker image changed, and no runtime/backup/profile state changed.
- Rollback is removal of this task directory only; the custom baseline and all earlier evidence are
  preserved.
- Independent review confirmed the early-rejection boundary and found no unsupported Passed
  claim. The next ready task is M5-MAA.
