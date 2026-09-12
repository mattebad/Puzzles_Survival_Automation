# Stage 9 authoritative scheduler repair manifest r3

## Control
- Task ID: `stage-9-refrozen-repair-r3`
- Revision: `runtime-reliability-stage-9-scheduler-r3`
- Type: `offline_consolidated_repair`
- Parent: `gpt-5.6-sol-medium`, `control_plane_owner`
- Implementer: `gpt-5.6-luna-xhigh`, one repair turn
- Tester: `gpt-5.6-terra-high`, one read-only review/recheck
- Product precondition: unchanged accepted Stage 8 Nova authority `nova_praise-v1`, digest `959fe8201ce0250dcab494dc65f930cf52c753b1ac5833d22bcb3a1abea2b2ae`.
- User continuation: explicit; user also pre-authorized one additional r4 revision only if r3 recheck requires it.
- Live budget: zero sessions, inputs, transports, ownership acquisitions, registrations, or scheduler pulses.

## Preserved architecture
- Sole kernel: `automation_service.scheduler.UtcPulseCoordinator`.
- Sole persistence authority: `SQLiteSchedulerInvocationRepository` over existing `SafetyStore` schema version 4.
- Selection creates no target, DevelopmentSession, runtime ownership, or transport authority.
- Production registration remains `NOT_REGISTERED`; scheduler execution and eligibility remain disabled.
- Legacy scheduler constructors remain non-executable; historical state remains preserved.

## Exact r3 repair
1. Explicitly route `NormalizedOutcome.MANUAL_REQUIRED` to a terminal `SchedulerAwareTaskResult.manual_required` result with `unresolved_action=false`; it must not create a reconciliation/global unresolved lock and must not block a distinct eligible flow.
2. Never synthesize `observed_at_utc` for cooldown/timer or any caller projection. A projection without a real finite observation timestamp is ineligible and cannot be persisted as fresh. After rollback/reset invalidation and restart, only a strictly newer, explicitly timestamped observation may restore projection validity; unchanged or undated caller facts remain deferred/observation-required.

## Writable paths
### Production
- `automation_service/contracts.py`
- `automation_service/scheduler.py`
- `safe_action_core/scheduler_invocation_state.py`
- `tasks/scheduler_task_result.py`

### Tests
- `tests/test_automation_service_scheduler.py`
- `tests/test_scheduler_invocation_state.py`

### Parent documentation after decision
- `CURRENT_HANDOFF.md`
- `docs/runtime-reliability-convergence-status.md`
- `docs/execution-manifests/runtime-reliability-stage-9-scheduler-r3.md`

Every other path is read-only. No registry JSON, store schema change, flow adapter, OMP/profile, launcher, provider, credential, AWS, evidence, `.local`, runtime, or Git mutation.

## Required regressions
- Verified `MANUAL_REQUIRED` persists `manual_required`, unresolved false, zero action count unless supplied, and a different eligible descriptor can run next.
- Cooldown/timer projection construction or selection rejects missing `observed_at_utc`.
- Invalidated projection survives repository close/reopen; undated and same/older timestamp writes cannot restore it; strictly newer timestamp can restore it.
- Rollback and reset disagreement still start zero handlers and preserve both-reset invalidation.
- All r1/r2 scheduler, concurrency, migration, recurrence, retirement, and pnsctl regressions remain passing.

## Validation
- Exact new regressions first.
- Targeted scheduler profile: automation-service scheduler, invocation state, retirement, pnsctl pulse.
- Resource authority compatibility suite.
- Frozen affected command from r2 once; unchanged disabled-registry baseline reported separately and never altered.
- One Terra review over the exact r3 diff and all prior accepted invariants.

## Stop
- No runtime/live/registration/Stage 10 action.
- Any must-fix after r3 review may use only the user-pre-authorized r4 through a separately frozen manifest. No unreviewed publication.
