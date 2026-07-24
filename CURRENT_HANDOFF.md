<!-- CURRENT_HANDOFF_STATE_BEGIN -->
{
  "schema_version": 2,
  "branch": "main",
  "head": "b35f9c981ef2c5751f708afec622437a440284e6",
  "ahead_behind": {
    "ahead": 1,
    "behind": 0
  },
  "attributable_dirty_paths": [],
  "protected_user_owned_paths": [
    ".cursor/plans/**",
    ".specstory/**",
    ".vscode/**",
    "Puzzle_Survival_Runtime_POC.zip",
    "evidence/**",
    ".local-reference/**",
    ".local-captures/**"
  ],
  "current_task_id": "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
  "current_task_state": "blocked",
  "next_task_id": "NOAHS-TAVERN-HOME-ATLAS-MIGRATION",
  "next_task_activation_status": "ready",
  "active_task_or_flow": null,
  "active_delivery_stage": null,
  "queue_counts": {
    "ready": 6,
    "active": 0,
    "blocked": 10,
    "completed": 5,
    "needs_product_decision": 1
  },
  "first_ready_flow": "NOAHS-TAVERN-HOME-ATLAS-MIGRATION",
  "next_ready_flow": "NOAHS-TAVERN-HOME-ATLAS-MIGRATION",
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
    "note": "Campaign AP offline blocked-result commit b35f9c9; lease released; Noah's Tavern is next ready."
  },
  "latest_focused_validation_result": "160 focused Campaign/Home/authority/atlas tests passed; git diff --check clean.",
  "latest_full_suite_result": "Not required for this offline evidence-gated blocked slice.",
  "current_live_attempt_state": "No live attempt; maximum_live_attempts=0; three historical attempts remain terminal.",
  "current_evidence_or_session_reference": "Atlas campaign-atlas-native-800x1280-v4 SHA-256 11214e52a1004cb72c15df0dab5db2b11047b96c0b0f17f078d73208b67b5ac7; Stage-9 Ch.20 ground truth under tasks/assets/campaign_auto_battle/800x1280/ground-truth/stage-9-chapter-20/.",
  "last_safe_completed_step": "Focused commit b35f9c9 and development-lease release for Campaign AP offline evidence_required block.",
  "exact_next_permitted_action": "Stop. A later chat may select NOAHS-TAVERN-HOME-ATLAS-MIGRATION. A Campaign AP retry requires Stage-9 Ch.15/Ch.2 native evidence and, for any canary, an exact user-supplied positive maximum_live_attempts.",
  "current_blocker": "evidence_required: Stage-9 native chapter-map ground truth absent for 1-15-9 and 2-2-9.",
  "prohibited_repeated_action": "Do not issue live Campaign/UC input, invent maximum_live_attempts, fabricate Stage-9 fixtures for Ch.15/Ch.2, rebuild the accepted atlas/survey corpus, consume AP, register a flow, or enable scheduler eligibility.",
  "recent_relevant_commits": [
    "b35f9c9 feat(campaign): add stage9 provenance destination replay",
    "f336ff9 fix(campaign): correct atlas stitch and destination tuple",
    "adb89e5 docs(flow-delivery): finalize atlas integration handoff",
    "dbf79df docs(flow-delivery): close campaign atlas integration",
    "66acbd6 feat(campaign): integrate atlas navigation replay"
  ],
  "process_deviations": [
    "Explicit user-authorized one-task queue-order override selected Campaign AP ahead of ready Noah's Tavern without changing Noah's status."
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
    "development_lease_status": "absent; released after blocked-result commit",
    "active_prepared_input_sent_unresolved_action_ids": [],
    "historical_unresolved_classification": "No active unresolved consequential action."
  },
  "evidence": {
    "evidence_requirement": "NOT_APPLICABLE",
    "evidence_requirement_reason": "Zero-transport offline Stage-9/destination work uses task assets and retained .local-captures rather than the governance evidence manifest; Stage-9 for 1-15-9/2-2-9 and any live canary remain absent blockers.",
    "active_evidence_manifest": null,
    "do_not_recursively_inspect_parent_evidence_tree": true
  }
}
<!-- CURRENT_HANDOFF_STATE_END -->

# Current handoff

Volatile operational boundary only. History lives in Git, BACKLOG.md, retained evidence, and
authoritative journals.

## Atomic task outcome

`CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION` offline slice is blocked `evidence_required`
after focused commit `b35f9c9`. Stage-9 native ground truth and destination zero-transport
verification are proven only for `1-20-9`. `1-15-9` and `2-2-9` remain missing Stage-9 chapter-map
evidence. `maximum_live_attempts=0`. No live input. Lease released. Noah's Tavern is again the
deterministic next ready flow. Registration and scheduler unchanged.

## Exact next action

Stop. A later chat may select `NOAHS-TAVERN-HOME-ATLAS-MIGRATION`. A Campaign AP retry requires
Stage-9 Ch.15/Ch.2 native evidence and, for any canary, an exact user-supplied positive
`maximum_live_attempts`.
