# M5-CUSTOM-BASELINE preflight

Recorded: 2026-07-12, America/Chicago

## Task

- Task ID: M5-CUSTOM-BASELINE
- Objective: benchmark the incumbent Python + direct ADB + OpenCV + local OCR stack against
  the retained startup-normalization corpus and the M5 safety contract, without repeating live
  game input.
- Satisfied dependencies: MVP-STARTUP-NORMALIZATION Passed; RT-019 Passed; RT-021 Passed;
  RT-017 recovery backup present.
- Acceptance criteria: 50–100 replay capture/classification operations; 20–25 safe target
  resolution/dry-run trials; 10 safe gesture-resolution trials; 5–10 reconnect simulations
  plus retained RT-021 reconnect evidence; detector and OCR coverage; profile and stale-frame
  rejection; central-policy and one-input/immediate-recapture review; fail-closed unknown
  outcomes; packaging, resource, diagnostics, testability, maintainability, and SQLite-core
  compatibility assessment. All results must be retained with expected outcomes and hashes.

## Intended operations

1. Read the immutable Cash Mall, allowlisted Ending Soon, Home/Base, keyguard/launcher, and
   profile-mismatch fixtures from the passed MVP corpus.
2. Run the incumbent classifier and image decoder in offline replay only. Produce 100 capture
   replays, 100 classification operations, 25 target annotations, and 10 OCR classifications.
3. Exercise the guarded non-secure keyguard authorization contract with fixtures and prove that
   a second swipe is denied; no OS input is sent.
4. Exercise stale/profile-mismatch/unknown/target-overlap policy denials with mocks and review
   the retained RT-021 direct ADB/reconnect and MVP one-input evidence.
5. Record measured local replay timing and retained live ADB timing separately; do not present
   replay decode timing as live ADB capture latency.

## Verification procedure

- Run `scripts/m5_benchmark_custom.py` with output and annotation paths in this directory.
- Check every replay image decodes as PNG-compatible `800x1280` where expected; reject the
  incompatible iOS/reference image.
- Require positive Cash Mall and allowlisted Ending Soon decisions, negative Home/Base,
  keyguard/launcher, and profile-mismatch decisions, exact back-arrow ROI, OCR Home/Base pass,
  one-swipe authorization followed by denial, and all policy denials.
- Review the JSON measurements, hashes, retained RT-010/RT-021 live measurements, package
  constraints, and the complete repository diff before deciding the task.
- Run Python compilation, existing offline startup validation, runtime-profile validation, and
  secret scans before commit.

## Evidence and rollback

- Evidence directory: `evidence/sessions/20260712-m5-custom-baseline/`.
- Planned artifacts: `benchmark.json`, `annotations/`, `record.md`, and `preflight.md`.
- Required credentials/manual dependency: none. No SSH, VM, ADB, game, account, or user input
  is required for this task; the live cleanup state was already verified read-only.
- Permissions: repository write for the benchmark script/evidence and Git task commit only.
- Rollback: remove only the task-scoped benchmark script and evidence directory if the task is
  rejected; leave the passed MVP corpus, runtime, backup, profile, and unrelated worktree files
  untouched. No live rollback operation is permitted or needed.
