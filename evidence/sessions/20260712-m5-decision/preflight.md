# M5-DECISION preflight

Recorded: 2026-07-12, America/Chicago

## Task

- Task ID: M5-DECISION
- Objective: select the lowest-complexity deterministic control stack that satisfies the
  representative startup requirements and close M5.
- Satisfied dependencies: M5-CUSTOM-BASELINE Passed (`d7cbca5`); M5-AIRTEST Rejected
  (`d74d345`); M5-MAA Rejected (`efd7aef`); MVP startup-normalization Passed; RT-017, RT-019,
  and RT-021 Passed.
- Acceptance criteria: record the selected framework and exact role; rejected candidates and
  evidence-backed reasons; benchmark methodology and comparative measurements; packaging,
  policy-gate, reconnect/failure, maintainability, limitations, fallback conditions, evidence
  links, and explicit authorization to proceed to M6.

## Intended operations

1. Perform a document-only independent comparison of the three closed candidate records and the
   retained MVP/RT-010/RT-021 evidence.
2. Select the custom Python + direct ADB + OpenCV + local OCR stack if, as indicated by the
   candidate evidence, it is the lowest-complexity reliable option.
3. Update the M5 decision evidence, backlog, canonical plan, and durable handoff. Mark M6 ready
   but do not begin M6 corpus capture, Daily Quest, or any live game work.

## Verification procedure

- Reconcile every M5 acceptance criterion against the three candidate records and benchmark JSON.
- Verify only the selected custom baseline has measured replay/classification/target/OCR/policy
  results; preserve zero-operation early-rejection counts for Airtest and MaaFramework.
- Run JSON parsing, Python compilation, existing offline recognition validation, runtime-profile
  validation, secret scan, whitespace/diff review, and status checks.
- Create exactly one final M5 task-scoped commit, then stop at the M5 terminal decision.

## Evidence and rollback

- Evidence directory: `evidence/sessions/20260712-m5-decision/`.
- Required credentials/manual dependency: none. No SSH, VM, ADB, game, account, or user input is
  required for the final document decision.
- Permissions: repository write for decision evidence/docs and one Git commit only.
- Rollback: preserve all candidate evidence and revert only the M5 decision documentation if an
  independent review later rejects the selection. Do not alter the VM, game, ADB, backup, profile,
  or unrelated worktree paths.
