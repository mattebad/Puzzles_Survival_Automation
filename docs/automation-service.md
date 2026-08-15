# Automation service

`automation_service/` is a thin local/offline composition package. It reuses the existing
`safe_action_core` policy, executor, store, action lifecycle, and
`SQLiteSchedulerInvocationRepository`; `tasks.scheduler_task_result` supplies normalized
scheduler-aware results, while `tasks.perception_bundle`, native-frame replay, and existing
Campaign/Home semantics remain the source contracts.

## Boundaries

- Context classification is read-only. Flow handlers own action semantics.
- The service scheduler uses UTC epoch `next_eligible_at` values. It never interprets
  `tasks.scheduler.TaskState.next_due_monotonic` and does not compose two schedulers.
- Fake and replay adapters have zero transport.
- The BlueStacks adapter is supervised-only, requires a flow-bound single-use admission token,
  and can dispatch only through `SafeActionExecutor` with a bound core request/capability. The
  service CLI has no arbitrary ADB, coordinate, shell, tap, remote, or automatic endpoint.
- Production registration and scheduler eligibility remain disabled in
  `tasks/flow_delivery_disabled_production_registry.json`.
- Campaign composition delegates destination policy and atlas navigation to existing
  `tasks.campaign_auto_battle` / `tasks.campaign_atlas` contracts. It never authorizes AP,
  Challenge, Auto Battle, Sweep, Blitz, Auto Complete, or AP refill.
- Retention operations classify records only; deletion remains in the dedicated evidence workflow.

## Local checks

Run focused checks from the repository root:

```text
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_automation_service_contracts \
  tests.test_automation_service_adapters \
  tests.test_automation_service_temporal \
  tests.test_automation_service_scheduler \
  tests.test_automation_service_handlers \
  tests.test_automation_service_campaign \
  tests.test_automation_service_operations
```

The CLI is local and non-authorizing:

```text
PYTHONDONTWRITEBYTECODE=1 python -m automation_service --mode disabled status
PYTHONDONTWRITEBYTECODE=1 python -m automation_service --adapter replay observe
```

## Packaging and eventual deployment

`docker/automation-service.Dockerfile` and `compose.automation-service.yml` provide a reproducible
Linux packaging shape with disabled/fake defaults, bounded resources, a read-only code/root
filesystem, and explicit writable state/evidence mounts. The compose file makes no Docker-socket,
libvirt, public-ADB, or runtime-host assumption.

Build and test locally before any future artifact deployment. No deployment is performed by this
roadmap slice; Codex/Cursor is not a NAS production dependency.

## Readiness versus admission

Offline tests establish composition readiness only. They do not promote registry entries, alter
the queue scheduler flag, or admit runtime input. Exactly ten supervised Campaign navigation
cycles remain pending under the roadmap; no family is enabled and no legacy adapter is retired.

