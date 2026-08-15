<!-- CURRENT_HANDOFF_STATE_BEGIN -->
{
  "schema_version": 2,
  "branch": "feature/autonomy-remediation",
  "head": "d9f47bb9a8ac0f610d6e2a31bce37a211d8aeb75",
  "ahead_behind": {"ahead": 0, "behind": 0},
  "attributable_dirty_paths": ["CURRENT_HANDOFF.md", "scripts/pnsctl.py", "scripts/flow_delivery_troop_training_bluestacks.py", "tasks/flow_delivery_queue.json", "tasks/flow_delivery_disabled_production_registry.json", "tasks/gameplay_flow_contracts/CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY.json", "tasks/gameplay_flow_contracts/RUINS-CHALLENGE-HOME-ATLAS-MIGRATION.json", "automation_service/**", "compose.automation-service.yml", "docker/automation-service.Dockerfile", "docs/automation-service.md", "docs/portfolio-requirements-inventory.md", "requirements-automation-service.txt", "tests/test_flow_delivery_troop_training.py", "tests/test_automation_service_adapters.py", "tests/test_automation_service_campaign.py", "tests/test_automation_service_cli.py", "tests/test_automation_service_contracts.py", "tests/test_automation_service_handlers.py", "tests/test_automation_service_operations.py", "tests/test_automation_service_scheduler.py", "tests/test_automation_service_temporal.py"],
  "task_start_worktree": {"tracked_dirty_paths": [], "protected_untracked_paths": [".local-transfer/"]},
  "protected_user_owned_paths": [".local-reference/", ".local-captures/", ".local-tools/", "evidence/"],
  "current_task_id": "AUTONOMY-REMEDIATION-ROADMAP-WITHOUT-BLISS",
  "current_task_state": "offline_repair",
  "next_task_id": "SUPPLY-DEPOT-LEGACY-ADAPTER-RETIREMENT",
  "next_task_activation_status": "ready",
  "active_task_or_flow": "AUTONOMY-REMEDIATION-ROADMAP-WITHOUT-BLISS",
  "active_delivery_stage": "offline_repair_validation",
  "queue_counts": {"ready": 3, "active": 0, "blocked": 6, "completed": 14, "needs_product_decision": 1},
  "first_ready_flow": "SUPPLY-DEPOT-LEGACY-ADAPTER-RETIREMENT",
  "next_ready_flow": "SUPPLY-DEPOT-LEGACY-ADAPTER-RETIREMENT",
  "development_lease_state": "released",
  "runtime_ownership_state": "released",
  "writable_agent_state": "absent",
  "unresolved_action_state": "clear",
  "latest_focused_validation_result": "Repair validation passed 29 automation-service tests, 61 pnsctl compatibility tests, 11 gameplay-contract tests, 154 scheduler/action/perception/replay tests, and 47 Troop tests with one retained-evidence skip. The known authority-consistency baseline remains three stale expectation failures; no live validation was run.",
  "latest_full_suite_result": "Manual opt-in only; not run.",
  "current_live_attempt_state": "No runtime, emulator, BlueStacks, ADB, Docker-daemon, Unraid, Bliss, gameplay, or network input occurred for this offline architecture task. Prior Troop session remains complete and ownership released.",
  "current_evidence_or_session_reference": ".local-captures/flow-delivery/TROOP-TRAINING-END-TO-END-CONSOLIDATION/run-20260814T054246158698Z/troop-training-20260814T054246675094Z; development session TROOP-TRAINING-END-TO-END-CONSOLIDATION-20260814T054244780021Z.",
  "last_safe_completed_step": "The terminal run recorded all four exact active queues, confirmed Vehicle T1 x1000 after one normal timed Train dispatch, issued the bounded Home return, and positively recognized canonical FULLY_ZOOMED_OUT Home. Its development-session summary is completed with 10 inputs and ownership_released=true.",
  "exact_next_permitted_action": "Review the focused offline validation and changed allowlist; no runtime or live canary is permitted.",
  "current_blocker": "",
  "prohibited_repeated_action": "Do not repeat any Fighter, Shooter, Rider, or Vehicle Train: exact matching queues are active/proven. Do not use Train Now, premium currency, speedups, Shooter/Rider resource boxes, registration, scheduler, composition, M6, or Bliss changes.",
  "recent_relevant_commits": ["d9f47bb9a8ac0f610d6e2a31bce37a211d8aeb75", "c548a8f299234a1e27132a8c001939dfe8f13a31", "fa9a33b070f83001f0e673f136f6435072c204d3", "9c68cbe86d6001b53c8bb874bada30422774b819", "51483090558206699a9ce3092eab0c182f13ccf1"],
  "process_deviations": ["The first live preflight sampled transient ADB startup state before its own successful screencap; a zero-input pnsctl observation proved device/game/native profile readiness.", "Later bounded development sessions exposed stale OCR source frames, packed queue timers, transient Master Trainer text, and active-queue carousel/queue-tier divergence. Each block retained evidence, released ownership, and was retried only after a materially changed tested repair; no exact active queue was trained twice."],
  "registration_and_scheduler": {"registered_operator_tasks": "NOT_REGISTERED_UNCHANGED", "scheduler_enabled_disabled": "DISABLED/INELIGIBLE", "scheduler_eligible_flows": [], "composition_blocked": true, "m6_unactivated": true, "bliss_unchanged": true},
  "journals_and_lease": {"development_lease_path": ".local-orchestrator/flow-delivery-lease.json", "development_lease_status": "released_after_completed_session", "active_prepared_input_sent_unresolved_action_ids": [], "historical_unresolved_classification": "Clear. Every dispatched normal Train has an exact queue/timer successor, the terminal Home postcondition is proven, and singleton ownership is released."},
  "evidence": {"evidence_requirement": "SATISFIED", "evidence_requirement_reason": "The terminal native session proves exact Fighter, Shooter, Rider, and Vehicle queues with positive timers, queue-bound tier/quantity identity, fresh tab successors, Vehicle current maximum 1000 before normal Train, and canonical Atlas Home. No resource boxes, Train Now, premium, speedup, purchase, registration, or scheduling input occurred.", "active_evidence_manifest": null, "do_not_recursively_inspect_parent_evidence_tree": true}
}
<!-- CURRENT_HANDOFF_STATE_END -->

# Current handoff

`AUTONOMY-REMEDIATION-ROADMAP-WITHOUT-BLISS` is an offline architecture implementation on
`feature/autonomy-remediation` at baseline `d9f47bb9a8ac0f610d6e2a31bce37a211d8aeb75`. The
implementation composes existing action, perception, scheduler-invocation, replay, and
Campaign/Home semantics without runtime input or production registration. Troop Training remains
complete with exact active queues Fighter T8 x1000, Shooter T8 x250, Rider T1 x250, and Vehicle
T1 x1000; its evidence/session remains retained and ownership released. No registration,
scheduler promotion, composition activation, M6, or Bliss change occurred.
