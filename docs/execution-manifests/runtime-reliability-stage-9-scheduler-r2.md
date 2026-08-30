# Stage 9 authoritative scheduler repair manifest r2

## Task ID and objective
- Task ID: `stage-9-refrozen-repair-r2`
- Objective: Repair only the five must-fix findings retained by the r1 Terra recheck, add permanent regressions, and complete Stage 9 integration without changing live, registration, or product authority.

## Frozen stage control
- Host: `omp-codex`
- Parent conversation ID: `current-task`
- `control_plane_owner`: `sol_parent`
- Revision ID: `runtime-reliability-stage-9-scheduler-r2`
- Stage type: `offline_consolidated_repair`
- Product precondition: `proven` — unchanged Stage 8 acceptance of `NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE`, `nova_praise-v1`, digest `959fe8201ce0250dcab494dc65f930cf52c753b1ac5833d22bcb3a1abea2b2ae`.
- Prior failure class: `diminishing_returns`; explicit user continuation authorizes this refrozen r2 only.
- Stage start UTC: `not recorded`
- Continuation checkpoint UTC: `not recorded`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | Freeze, classification, integration, publication, termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One r2 repair turn on assigned paths only |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only r2 review/recheck |

## Immutable budgets
- One Luna repair and one Terra review/recheck; no further repair under r2.
- Zero live attempts, zero runtime sessions, zero inputs, zero transports, zero ownership acquisitions.

## Preserved architecture
- Sole executable kernel: `automation_service.scheduler.UtcPulseCoordinator`.
- Sole persisted invocation/occurrence authority: `SQLiteSchedulerInvocationRepository` over the existing `SafetyStore` database.
- Selection grants no target, DevelopmentSession, runtime ownership, or transport authority.
- Registration remains `NOT_REGISTERED`; production scheduler execution and eligibility remain disabled.
- Legacy scheduler constructors remain non-executable and historical state remains preserved.
- Rollback remains commit `61bfc71a9b032834c464383f2233c099329d606d` until accepted authoritative scheduler state is published; afterward repair forward.

## Exact repair findings
1. Map `NormalizedOutcome.BLOCKED` to a terminal blocked scheduler result without unresolved/global-lock state.
2. Add a durable same-pulse occurrence fence so a deferred result with absent/equal deadline cannot be reclaimed during the same UTC pulse; simultaneous pulses start at most one handler for an occurrence.
3. Persist accepted recurrence projections and make selection consult repository validity; invalidated rollback/reset projections cannot be replaced by stale caller facts without a strictly fresh persisted observation.
4. On reset disagreement, invalidate projections for both declared and conflicting observed reset identities and persist observation/defer truth.
5. Reconcile orphan `ACTIVE`/`CLAIMED` occurrences only from a verified positive `COMPLETE_FOR_RESET` or `ALREADY_COMPLETE` result; all other reconciliation attempts remain reconciliation-required and preserve evidence/history.

## Writable paths
### Production
- `automation_service/contracts.py`
- `automation_service/scheduler.py`
- `safe_action_core/scheduler_invocation_state.py`
- `safe_action_core/store.py`
- `tasks/scheduler_task_result.py`

### Tests
- `tests/test_automation_service_scheduler.py`
- `tests/test_scheduler_invocation_state.py`
- `tests/test_scheduler_retirement.py`
- `tests/test_pnsctl_scheduler_pulse.py`

### Parent-owned documentation after acceptance decision
- `CURRENT_HANDOFF.md`
- `docs/runtime-reliability-convergence-status.md`
- `docs/execution-manifests/runtime-reliability-stage-9-scheduler-r2.md`

Every other path is read-only. In particular: no registry JSON, production flow adapter, `.omp/**`, launcher, profile, provider, credential, AWS, evidence, or `.local` artifact mutation.

## Required permanent regressions
- Explicit blocked result persists `blocked`, `unresolved_action=false`, and does not prevent a distinct eligible flow.
- Two SQLite connections/threads using the same UTC pulse and occurrence produce exactly one handler start, including a zero/absent/equal deferral deadline case.
- A saved projection can select only while valid and fresh; rollback invalidation survives restart and stale caller facts cannot restore it.
- Reset disagreement invalidates both reset identities across restart and starts no handler.
- Orphan claim after simulated process exit blocks retry; unverified/deferred/action-performed reconciliation is rejected; verified positive reconciliation atomically completes invocation, occurrence, and claim with evidence.
- Existing r1 resolved regressions remain passing: v4→v5 migration, bounded repeat, AP/stamina freshness, terminal factories, revalidation exceptions, retirement, offline pnsctl disabled behavior.

## Validation hierarchy
- Exact new regressions first.
- Frozen affected command once: `python -m unittest tests.test_automation_service_scheduler tests.test_automation_service_contracts tests.test_automation_service_operations tests.test_automation_service_cli tests.test_scheduler_invocation_state tests.test_scheduler tests.test_scheduler_sqlite tests.test_scheduler_retirement tests.test_pnsctl_scheduler_pulse`.
- Separately report the unchanged disabled-registry baseline; never alter it under r2.
- Focused schema-3 handoff parser after parent durable update.
- One Terra recheck over r2 diff and prior five findings.

## Safety and escalation
- No runtime, service start, production pulse, `pnsctl conduct`, BlueStacks, ADB, gameplay, Nova repeat, registration, scheduler enablement, Stage 10 activity, combat, real-money interaction, evidence mutation, external provider, or Git publication before parent acceptance.
- A new or unresolved must-fix finding after the r2 review terminates r2; it does not authorize another repair.
