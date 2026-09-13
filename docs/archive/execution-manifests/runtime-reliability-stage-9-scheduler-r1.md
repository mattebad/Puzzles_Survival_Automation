# Stage 9 authoritative scheduler manifest

## Task ID and objective
- Task ID: `stage-9-autonomous-service-implementation`
- Objective: Converge offline scheduling onto one UTC scheduler kernel and one SQLite invocation/occurrence authority, then retire every executable legacy scheduler path without enabling production registration or runtime input.

## Frozen stage control
- Host: `omp-codex`
- Parent conversation ID: `current-task`
- `control_plane_owner`: `sol_parent`
- Revision ID: `runtime-reliability-stage-9-scheduler-r1`
- Stage type: `offline_cross_contract_implementation`
- Product precondition: `proven` — Stage 8 parent-accepted exactly `NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE`, typed authority `nova_praise-v1` digest `959fe8201ce0250dcab494dc65f930cf52c753b1ac5833d22bcb3a1abea2b2ae`, with durable same-reset duplicate denial and next-reset eligibility.
- Failure class: `none`; any initial implementation defect is classified by the Sol parent before repair.
- Stage start UTC: `not recorded`
- Continuation checkpoint UTC: `not recorded`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | Stage freeze, architecture, integration acceptance, retirement, Git publication, termination |
| `procedure_coordinator` | `not used` | None |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One consolidated implementation package on assigned paths only |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only defect-first review and, only if used, one recheck |
| `escalation_architect` | `not used` | Reserved for a genuinely new architecture conflict |

## Immutable budgets
- Stage: one implementation, one independent review, at most one consolidated repair, at most one recheck, zero live attempts.
- Managed-turn budget: four (`implementation`, `review`, optional `repair`, optional `recheck`).
- Runtime budget: zero sessions, zero inputs, zero transport calls, zero ownership acquisitions.
- Conversation budget: this is one frozen Stage 9 revision; no second Stage 9 redesign without a defined escalation condition.

## Frozen architecture decision
- The only executable kernel is `automation_service.scheduler.UtcPulseCoordinator`.
- The only persisted scheduler invocation/occurrence authority is `safe_action_core.scheduler_invocation_state.SQLiteSchedulerInvocationRepository`, backed by the existing `safe_action_core.store.SafetyStore` SQLite database. Scheduler claim/projection tables owned by that repository are part of the same authority, not a second store.
- Selection is deterministic and claims at most one account/server/reset/flow occurrence atomically before any handler starts. A claimed occurrence is never silently reopened after crash or unknown dispatch; it remains reconciliation-required until an explicit verified reconciliation result.
- Account, server, reset, accepted-product, registration, scheduler-eligibility, global health, unresolved-action, breaker, singleton-owner availability, UTC clock, and reset-agreement gates fail closed.
- The coordinator selects only. It never binds a gameplay target, creates a DevelopmentSession, acquires runtime ownership, or grants transport authority. A selected handler must re-enter its accepted `pnsctl`/DevelopmentSession/singleton/current-frame/product-revalidation/effect-verification/terminal-postcondition boundary.
- Product state is revalidated after atomic selection and before handler execution. Selection, dispatch, or transport success cannot create semantic completion; only an accepted verified result can complete/defer an occurrence.
- UTC clock rollback or reset disagreement invalidates persisted projections and records observation/defer. Cooldown/timer/AP projections require fresh observed facts; queue and march availability use generation identities; bounded repeats and event windows remain typed and disabled unless an accepted flow supplies product policy.
- `tasks.scheduler.OnePulseScheduler` and `SQLiteBackedOnePulseScheduler` become fail-closed, non-instantiable compatibility artifacts. Historical `task_state` rows remain preserved and cannot be interpreted or dispatched by either scheduler. Ambiguous legacy monotonic state is rejected, not guessed.
- Rollback authority: before any accepted authoritative Stage 9 scheduler state exists, return only to commit `61bfc71a9b032834c464383f2233c099329d606d`. After authoritative state exists, repair forward and preserve invocation, occurrence, unresolved, and audit history.

## Writable paths
### Production
- `automation_service/scheduler.py`
- `automation_service/contracts.py`
- `automation_service/handlers.py`
- `automation_service/service.py`
- `automation_service/registry.py`
- `safe_action_core/scheduler_invocation_state.py`
- `safe_action_core/store.py`
- `tasks/scheduler_task_result.py`
- `tasks/scheduler.py`
- `scripts/pnsctl.py` — one offline scheduler `pulse` entrypoint only

### Tests
- `tests/test_automation_service_scheduler.py`
- `tests/test_automation_service_contracts.py`
- `tests/test_automation_service_operations.py`
- `tests/test_automation_service_cli.py`
- `tests/test_scheduler_invocation_state.py`
- `tests/test_scheduler.py`
- `tests/test_scheduler_sqlite.py`
- `tests/test_scheduler_retirement.py`
- `tests/test_pnsctl_scheduler_pulse.py`

### Documentation
- `docs/execution-manifests/runtime-reliability-stage-9-scheduler-r1.md` — parent-owned and immutable after freeze
- `docs/runtime-reliability-convergence-status.md` — parent updates only after integration acceptance
- `CURRENT_HANDOFF.md` — parent updates only after integration acceptance

No production flow adapter, registry JSON, occurrence/effect implementation, OMP file, launcher, credential, provider, AWS, evidence, or retained runtime artifact is writable.

## Required recurrence capability
- Daily once-per-reset and reset-bounded claim/repeat sets: reset identity plus occurrence/repeat ordinal.
- Cooldown and timer completion: UTC next-eligible projection.
- AP/stamina: UTC regeneration projection combined with a fresh observed balance; projection alone cannot select.
- Queue and march-slot availability: fresh availability generation identity.
- Bounded repeats: persisted count and explicit limit.
- Event windows: typed UTC open/close interval.
- Unresolved occurrence reconciliation: persisted unresolved state blocks identical retry.
- All classes require account/server/reset identity, one runtime-owner availability fact, accepted flow authority, and disabled-by-default per-flow registration. Classes without an admitted Stage 8 flow remain typed/persistable only and cannot become selectable.

## Acceptance checks
- Missing activation, disabled registration, scheduler-ineligible or unaccepted descriptors, missing identity, duplicate descriptors, missing handlers, unhealthy global state, unresolved global action, active breaker, unavailable singleton owner, clock rollback, and reset disagreement all fail closed without handler start.
- Exactly one deterministic eligible candidate is claimed; simultaneous pulses claim at most one occurrence and one pulse starts at most one handler.
- Completed same-reset state, deferred state, unresolved state, evidence, action totals, and claim state survive repository/process restart. Allowed next-reset identity is independently eligible.
- Post-selection product revalidation is mandatory. Unknown/exceptional handler outcomes persist reconciliation-required and block identical retry. Verified semantic completion is distinct from selection and dispatch.
- Cooldown/timer wake calculations are UTC-based. AP/balance, queue generation, march generation, bounded repeat, and event-window contracts are typed and fail closed when fresh product facts are absent.
- Production service construction and the `pnsctl` pulse entrypoint remain disabled by default; production registry remains `NOT_REGISTERED` and scheduler eligibility remains false.
- No scheduler path creates runtime ownership, target binding, DevelopmentSession, transport route, recovery controller, action journal, or second scheduler store.
- Populated legacy state is preserved and either safely classified for compatibility or rejected; it is never scheduled by two authorities. Both legacy scheduler constructors/entrypoints are non-executable, and production code cannot route through them.

## Validation commands
- Exact regressions first for every initially failing changed contract.
- Affected package suites once: `python -m unittest tests.test_automation_service_scheduler tests.test_automation_service_contracts tests.test_automation_service_operations tests.test_automation_service_cli tests.test_scheduler_invocation_state tests.test_scheduler tests.test_scheduler_sqlite tests.test_scheduler_retirement tests.test_pnsctl_scheduler_pulse`.
- Scheduler/identity/restart/duplicate/concurrency profile: focused selectors added under the files above.
- Compatibility and retirement profile: legacy populated-state preservation/rejection plus non-instantiable legacy constructors and no production callsites.
- Architecture/integration profile: existing automation-service, safe-action scheduler persistence, registration-disabled, and governance invariants relevant to touched paths. Full repository discovery remains manual-only and is not run.
- Receipt digests are SHA-256 of captured command output; parent records exact commands, counts, and digests after execution.

## Safety limits
- Allowed: offline source/test/documentation edits; temporary SQLite databases under test-owned temporary directories; fake handlers and fake observations only.
- Disallowed: scheduler service start, production pulse, `pnsctl conduct`, BlueStacks, ADB, runtime ownership, gameplay, Nova repeat, registration, scheduler enablement/eligibility, Stage 10 observation/promotion, combat, real-money surfaces, evidence mutation, external providers, AWS, Bedrock, Qwen, OMP/profile/launcher mutation.
- Runtime/session limits: no runtime session and no input. Offline selection never grants target or transport authority.

## Evidence/history references
- Stage 8 accepted receipt: `.local-captures/development-sessions/NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE-20260824T194955792183Z/result.json`.
- Reset guard: `.local-orchestrator/nova-praise-one-free-pulse-game-day-2026-08-24.guard.json`.
- Confirmed action row: `.local-orchestrator/bluestacks-actions.sqlite3`, action ID `nova-praise-a5145f0c7403b0ac2b3f2e2762b8e9df09369430e9a422342e6e06305c72d177`.
- Canonical Stage 9 plan: `.cursor/plans/p&s_runtime_reliability_convergence_program_e62703e1.plan.md`, lines 587–631.

## Escalation conditions
- Manual-only account state, unsupported product-state precondition, consequential gameplay action, real-money confirmation, required safety-envelope weakening, architecture decision with no dominant safe option, second distinct failed redesign, unavailable required model/profile, or missing external authority/credential.
- Ordinary focused test failures, one localized implementation defect, documentation convergence, compatibility correction, packet completion, and worker completion do not stop the stage.
