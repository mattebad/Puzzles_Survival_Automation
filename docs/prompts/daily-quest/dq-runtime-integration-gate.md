# DQ-RUNTIME-INTEGRATION-GATE

Repository authority: matrix owns promotion, registration, persistence, and scheduler eligibility;
catalog remains observational. `BACKLOG.md` owns this future gate. Main Quest Claim excluded.

Scope: future read-only gate verifying explicit task registration, fresh game-day identity,
schema-v1/v2 journal compatibility, lease behavior, unresolved-action blocking, first-live
migration/rollback, and per-flow promotion. Reusable components: registry, pnsctl, task-state
store, journal, safe action core. Route: offline contract checks → future supervised gate.

Source recognizer: checked-in registry and pnsctl entry; target: matching matrix task; successor:
validated persistence/rollback result. All future consequential handlers must bind source, target,
successor to current frame. Policy: no registration or scheduler eligibility in this run.
Transaction: none now; future gate must be atomic and rollback-safe. Postcondition: registration
matches checked-in state without creating live state. Recovery: fail closed on mismatch.

Daily reconciliation, Claim authorization, and milestone separation remain explicit. Tests:
registry accuracy, fresh-day, schema, lease, unresolved action, migration rollback, and promotion
eligibility. Bliss evidence must be native; GnBots is not authority. Future navigation prohibited
except read-only inspection. Prohibit ADB, worker/VM changes, live rows, journal migration, live
input, new registration, and scheduler enablement. Update gate docs/matrix. Commit:
`docs(tasks): map every Daily objective to an execution task`. Continue offline.
