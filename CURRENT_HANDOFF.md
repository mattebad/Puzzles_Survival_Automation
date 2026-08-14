<!-- CURRENT_HANDOFF_STATE_BEGIN -->
{
  "schema_version": 2,
  "branch": "main",
  "head": "c548a8f",
  "ahead_behind": {"ahead": 1, "behind": 0},
  "attributable_dirty_paths": ["BACKLOG.md", "CURRENT_HANDOFF.md", "docs/prompts/daily-quest/dq-flow-training.md", "docs/troop-training-bluestacks.md", "scripts/bluestacks_adb_readiness.py", "scripts/flow_delivery_troop_training_bluestacks.py", "scripts/pnsctl.py", "scripts/troop_training_bluestacks.py", "tasks/assets/troop_training/", "tasks/flow_delivery_bluestacks_registry.json", "tasks/flow_delivery_product_policy.json", "tasks/flow_delivery_queue.json", "tasks/flow_delivery_validation_profiles.json", "tasks/gameplay_flow_contracts/TROOP-TRAINING-END-TO-END-CONSOLIDATION.json", "tasks/troop_training.py", "tasks/troop_training_runtime.py", "tasks/troop_training_vision.py", "tests/test_bluestacks_adb_readiness.py", "tests/test_flow_delivery_orchestrator.py", "tests/test_flow_delivery_troop_training.py", "tests/test_troop_training.py", "tests/test_troop_training_entry.py"],
  "protected_user_owned_paths": [".local-reference/", ".local-captures/", ".local-tools/", "evidence/"],
  "current_task_id": "TROOP-TRAINING-END-TO-END-CONSOLIDATION",
  "current_task_state": "completed",
  "next_task_id": "SUPPLY-DEPOT-LEGACY-ADAPTER-RETIREMENT",
  "next_task_activation_status": "ready",
  "active_task_or_flow": "",
  "active_delivery_stage": "completed",
  "queue_counts": {"ready": 3, "active": 0, "blocked": 6, "completed": 14, "needs_product_decision": 1},
  "first_ready_flow": "SUPPLY-DEPOT-LEGACY-ADAPTER-RETIREMENT",
  "next_ready_flow": "SUPPLY-DEPOT-LEGACY-ADAPTER-RETIREMENT",
  "development_lease_state": "released",
  "runtime_ownership_state": "released",
  "writable_agent_state": "absent",
  "unresolved_action_state": "clear",
  "latest_focused_validation_result": "Final affected-package gate passed 112 tests with one expected retained-evidence skip. The checked-in focused profile passed 46 tests (receipt 4f54ca8f1ef0f203148aa0f32393f2349be1df25a2c6c0f813cc4deb5fffc32f) and shared-navigation passed 64 tests (receipt 80e76854a066c91dbddfcf76987fe650b6adab4172457497e3264c410f49d7d4). The broader flow-delivery orchestrator module remains baseline-failing at HEAD because Nova records live_attempt_count 4 for two attempts, the Ruins product-policy status is unknown to the validator, and several historical queue expectations are stale; Troop-specific gates are green.",
  "latest_full_suite_result": "Manual opt-in only; not run.",
  "current_live_attempt_state": "Complete on 2026-08-14. Exact active queues are Fighter T8 x1000, Shooter T8 x250, Rider T1 x250, and Vehicle T1 x1000. The terminal run freshly reconciled the first three queues, dispatched only normal timed Vehicle Train after proving current maximum 1000, verified its exact queue successor, and returned to canonical Home. Runtime ownership is released.",
  "current_evidence_or_session_reference": ".local-captures/flow-delivery/TROOP-TRAINING-END-TO-END-CONSOLIDATION/run-20260814T054246158698Z/troop-training-20260814T054246675094Z; development session TROOP-TRAINING-END-TO-END-CONSOLIDATION-20260814T054244780021Z.",
  "last_safe_completed_step": "The terminal run recorded all four exact active queues, confirmed Vehicle T1 x1000 after one normal timed Train dispatch, issued the bounded Home return, and positively recognized canonical FULLY_ZOOMED_OUT Home. Its development-session summary is completed with 10 inputs and ownership_released=true.",
  "exact_next_permitted_action": "Begin SUPPLY-DEPOT-LEGACY-ADAPTER-RETIREMENT as the next atomic ready flow; Troop Training remains NOT_REGISTERED and scheduler-disabled.",
  "current_blocker": "",
  "prohibited_repeated_action": "Do not repeat any Fighter, Shooter, Rider, or Vehicle Train: exact matching queues are active/proven. Do not use Train Now, premium currency, speedups, Shooter/Rider resource boxes, registration, scheduler, composition, M6, or Bliss changes.",
  "recent_relevant_commits": ["c548a8f", "fa9a33b", "9c68cbe", "5148309"],
  "process_deviations": ["The first live preflight sampled transient ADB startup state before its own successful screencap; a zero-input pnsctl observation proved device/game/native profile readiness.", "Later bounded development sessions exposed stale OCR source frames, packed queue timers, transient Master Trainer text, and active-queue carousel/queue-tier divergence. Each block retained evidence, released ownership, and was retried only after a materially changed tested repair; no exact active queue was trained twice."],
  "registration_and_scheduler": {"registered_operator_tasks": "NOT_REGISTERED_UNCHANGED", "scheduler_enabled_disabled": "DISABLED/INELIGIBLE", "scheduler_eligible_flows": [], "composition_blocked": true, "m6_unactivated": true, "bliss_unchanged": true},
  "journals_and_lease": {"development_lease_path": ".local-orchestrator/flow-delivery-lease.json", "development_lease_status": "released_after_completed_session", "active_prepared_input_sent_unresolved_action_ids": [], "historical_unresolved_classification": "Clear. Every dispatched normal Train has an exact queue/timer successor, the terminal Home postcondition is proven, and singleton ownership is released."},
  "evidence": {"evidence_requirement": "SATISFIED", "evidence_requirement_reason": "The terminal native session proves exact Fighter, Shooter, Rider, and Vehicle queues with positive timers, queue-bound tier/quantity identity, fresh tab successors, Vehicle current maximum 1000 before normal Train, and canonical Atlas Home. No resource boxes, Train Now, premium, speedup, purchase, registration, or scheduling input occurred.", "active_evidence_manifest": null, "do_not_recursively_inspect_parent_evidence_tree": true}
}
<!-- CURRENT_HANDOFF_STATE_END -->

# Current handoff

`TROOP-TRAINING-END-TO-END-CONSOLIDATION` is complete. The authoritative production route enters
one configured camp from canonical Home, then uses freshly bound top tabs for the remaining enabled
types. Exact active queues are Fighter T8 x1000, Shooter T8 x250, Rider T1 x250, and Vehicle T1
x1000. The terminal 2026-08-14 session reconciled Fighter, Shooter, and Rider read-only, proved
Vehicle current maximum 1000 before normal timed Train, verified the exact Vehicle queue successor,
and returned to canonical Home. No resource boxes, Train Now, premium, speedup, registration,
scheduler, composition, M6, or Bliss change occurred. Runtime ownership is released,
`TROOP-TRAINING-VERIFIED-NAVIGATION-CONVERGENCE` is superseded, and
`SUPPLY-DEPOT-LEGACY-ADAPTER-RETIREMENT` is the exact next ready flow.
