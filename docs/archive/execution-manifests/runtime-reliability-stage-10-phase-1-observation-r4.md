# Stage 10 phase 1 terminal-evidence correction manifest r4

## Control
- Task ID: `stage-10-phase-1-observation-projection`
- Revision: `runtime-reliability-stage-10-phase-1-observation-r4`
- Host: `codex`
- Parent: `gpt-5.6-sol-medium`, sole control-plane owner
- Implementer: `gpt-5.6-luna-xhigh`, one bounded correction
- Tester: `gpt-5.6-terra-high`, one finding-only recheck
- User continuation: explicit at `2026-08-25T17:50:41.000Z`; continue through phase 6, reject only concrete regressions or required fixes.
- Failure class entering r4: `local_defect`

## Frozen correction
Keep the existing direct zero-input observation support, but never leave durable
`observed` success when post-exit ownership-release or checkpoint-immutability
validation fails. The direct session remains fail-closed through those checks.
After session exit:

- success rewrites/persists terminal artifacts as `observed`, `input_count=0`,
  `ownership_released=true`, and `lifecycle_state_created=false`;
- release/checkpoint failure rewrites/persists `summary.json` and `result.json`
  as `evidence_required` with actual ownership state and blocker, then raises;
- negative ceilings still reject before acquisition;
- delegated receipt and every non-observation path remain unchanged.

## Writable paths
- `scripts/pnsctl.py`
- `tests/test_development_session.py`
- Parent closure only: `CURRENT_HANDOFF.md`, `docs/runtime-reliability-convergence-status.md`, this manifest.

## Acceptance
- Prior zero-input success and negative-ceiling regressions remain passing.
- Release failure and checkpoint mutation cannot leave `observed` in either
  terminal artifact and record actual ownership release.
- Success is written only after both post-exit checks pass.
- `tests.test_development_session` and `tests.test_delegated_runtime_receipts`
  pass; no scheduler, registration, or runtime-input path changes.
- Terra recheck considers only this prior concrete finding and repair-caused
  regression; style, speculative hardening, and extra coverage are excluded.

## Budgets and safety
- One Luna correction, one Terra recheck, no further repair in this revision.
- One direct zero-input observation after tests, recheck, and parent acceptance.
- Gameplay input, transport, registration, scheduler eligibility, target
  binding, handlers, combat, purchase, and direct ADB remain prohibited.

## Validation
- Exact release-failure and checkpoint-mutation regressions first.
- `python -m unittest tests.test_development_session tests.test_delegated_runtime_receipts`
- Reuse r2 scheduler replay/status/pulse receipts because this correction does
  not touch scheduler code.
- Then run the exact direct `development-session observe --max-inputs 0` command.
