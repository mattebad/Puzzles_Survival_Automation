<!-- CURRENT_HANDOFF_STATE_BEGIN -->
{
  "schema_version": 2,
  "branch": "main",
  "head": "6b89a209385fde583352fe676dd968bf71420093",
  "ahead_behind": {
    "ahead": 0,
    "behind": 0
  },
  "attributable_dirty_paths": [],
  "protected_user_owned_paths": [
    ".cursor/plans/** (accepted Cursor plan; ignored and not edited during implementation)",
    ".specstory/**",
    ".vscode/**",
    "Puzzle_Survival_Runtime_POC.zip",
    "evidence/**",
    ".local-reference/**",
    ".local-captures/**"
  ],
  "current_task_id": "GF-MVP-007-NAMED-SCENARIO-FAILURE-ACCOUNTING",
  "current_task_state": "completed",
  "next_task_id": "GF-MVP-008-NOVA-NAVIGATION-ROUTE-MIGRATION",
  "next_task_activation_status": "ready",
  "active_task_or_flow": "none",
  "active_delivery_stage": null,
  "queue_counts": {
    "ready": 7,
    "active": 0,
    "blocked": 4,
    "completed": 0,
    "needs_product_decision": 4
  },
  "first_ready_flow": "NOVA-PRAISE-HOME-ATLAS-MIGRATION",
  "next_ready_flow": "NOVA-PRAISE-HOME-ATLAS-MIGRATION",
  "development_lease_state": "absent",
  "runtime_ownership_state": "none",
  "writable_agent_state": "absent",
  "unresolved_action_state": "clear",
  "parent_conversation_loop": {
    "policy_path": "tasks/flow_delivery_loop_policy.json",
    "progress_path": ".local-orchestrator/parent-conversation-progress.json",
    "configured_maximum_source": "controller loop policy",
    "completed_gameplay_flows_this_parent": 0,
    "rollover_required": false,
    "rollover_stop_reason": null,
    "note": "GF-MVP-007 offline named-scenario accounting only; flow-delivery queue not activated."
  },
  "latest_focused_validation_result": "92 tests passed (named scenario, queue/controller, pnsctl/evidence, governance/context)",
  "latest_full_suite_result": "1099 tests passed; 1 expected skip; 0 failures/errors",
  "current_live_attempt_state": "none",
  "current_evidence_or_session_reference": null,
  "last_safe_completed_step": "GF-MVP-007 added one no-Praise scenario: pre-input/replay records are non-consuming and the first navigation input exhausts its single execution budget.",
  "exact_next_permitted_action": "Activate GF-MVP-008-NOVA-NAVIGATION-ROUTE-MIGRATION offline only; do not acquire runtime ownership or activate the flow queue.",
  "current_blocker": null,
  "prohibited_repeated_action": "BlueStacks/ADB/Bliss input before GF-MVP-009; Campaign or Ultimate retries; Nova Praise; queue or production scheduler activation; evidence fabrication or deletion; push.",
  "recent_relevant_commits": [
    "6b89a20 fix(flow-factory): enforce executable evidence integrity",
    "b142e21 feat(flow-factory): add Nova production replay",
    "70df6e3 feat(flow-factory): converge localize-first home",
    "6f95d0a feat(flow-factory): add supervised identity preflight",
    "61e7981 feat(flow-factory): add minimum contract v2"
  ],
  "process_deviations": [
    "Campaign/Ultimate placeholder-evidence behavior is a confirmed latent production defect assigned only to GF-MVP-006."
  ],
  "registration_and_scheduler": {
    "registered_operator_tasks": "NOT_REGISTERED_UNCHANGED",
    "scheduler_enabled_disabled": "DISABLED/INELIGIBLE",
    "scheduler_eligible_flows": [],
    "composition_blocked": true,
    "m6_unactivated": true,
    "bliss_unchanged": true
  },
  "journals_and_lease": {
    "development_lease_path": ".local-orchestrator/flow-delivery-lease.json",
    "development_lease_status": "absent",
    "active_prepared_input_sent_unresolved_action_ids": [],
    "historical_unresolved_classification": "No active unresolved consequential action; historical unresolved snapshots remain retained evidence only."
  },
  "evidence": {
    "evidence_requirement": "NOT_APPLICABLE",
    "evidence_requirement_reason": "GF-MVP-007 is offline named-scenario accounting and creates no gameplay evidence.",
    "active_evidence_manifest": null,
    "do_not_recursively_inspect_parent_evidence_tree": true
  }
}
<!-- CURRENT_HANDOFF_STATE_END -->

# Current handoff

Volatile operational boundary only. History lives in Git, `BACKLOG.md`, and retained evidence.

## Repository
- Branch: `main` @ `6b89a20`
- `GF-MVP-007-NAMED-SCENARIO-FAILURE-ACCOUNTING`: **completed** offline pending its focused commit
- Flow-delivery queue: **not activated**
- Runtime ownership: none
- Push: prohibited

## Exact next action
Activate `GF-MVP-008-NOVA-NAVIGATION-ROUTE-MIGRATION` offline only after the scenario-accounting commit. Do not acquire
runtime ownership, activate the queue, or issue gameplay input.
