<!-- CURRENT_HANDOFF_STATE_BEGIN -->
{
  "schema_version": 2,
  "branch": "main",
  "head": "e6ecb381dfb8f3ebeb4b8d2135632eefe977f52c",
  "ahead_behind": {
    "ahead": 2,
    "behind": 0
  },
  "attributable_dirty_paths": [
    "BACKLOG.md",
    "CURRENT_HANDOFF.md",
    "scripts/bluestacks_campaign_ap.py",
    "scripts/flow_delivery_campaign_bluestacks.py",
    "tasks/backlog_task_index.json",
    "tasks/campaign_atlas_chapter_nav.py",
    "tasks/campaign_auto_battle_runtime.py",
    "tasks/campaign_auto_battle_vision.py",
    "tasks/flow_delivery_queue.json",
    "tests/test_campaign_atlas_chapter_nav.py",
    "tests/test_campaign_auto_battle_runtime.py"
  ],
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
  "current_task_state": "completing",
  "next_task_id": "NOAHS-TAVERN-HOME-ATLAS-MIGRATION",
  "next_task_activation_status": "ready",
  "active_task_or_flow": "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
  "active_delivery_stage": "selected",
  "queue_counts": {
    "ready": 6,
    "active": 1,
    "blocked": 9,
    "completed": 5,
    "needs_product_decision": 1
  },
  "first_ready_flow": "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
  "next_ready_flow": "NOAHS-TAVERN-HOME-ATLAS-MIGRATION",
  "development_lease_state": "held",
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
    "note": "Campaign AP finish wrapping: Stage-9 complete; commit+complete pending."
  },
  "latest_focused_validation_result": "test_campaign_stage9_destination_replay OK (all three STAGE9_VERIFIED / DESTINATION_REPLAY_VERIFIED).",
  "latest_full_suite_result": "Not yet required; navigation-only shared_navigation profile gates live_preflight.",
  "current_live_attempt_state": "All three destinations completed (attempts 9/13/14). Stage-9 Ch.15/Ch.2 packaged.",
  "current_evidence_or_session_reference": "nav-1-20-9-20260724T213721049798Z; nav-1-15-9-20260724T220450188105Z; nav-2-2-9-20260724T221131230091Z; campaign-ap-live Stage-9 GT copies",
  "last_safe_completed_step": "Packaged Stage-9 Ch.15/Ch.2 GT from live frames; zero-transport replay verified for 1-20-9/1-15-9/2-2-9.",
  "exact_next_permitted_action": "Focused commit then flow_delivery_control complete; do not consume AP; no push.",
  "current_blocker": null,
  "prohibited_repeated_action": "Do not consume AP, register/scheduler-enable, rebuild atlas, or use OCR residual chapter pans.",
  "recent_relevant_commits": [
    "e6ecb38 docs(flow-delivery): close campaign ap offline block",
    "b35f9c9 feat(campaign): add stage9 provenance destination replay",
    "f336ff9 fix(campaign): correct atlas stitch and destination tuple",
    "adb89e5 docs(flow-delivery): finalize atlas integration handoff",
    "dbf79df docs(flow-delivery): close campaign atlas integration"
  ],
  "process_deviations": [
    "Explicit user-authorized finish of Campaign AP with maximum_live_attempts=6 ahead of ready Noah's Tavern without changing Noah's status."
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
    "development_lease_status": "held by cursor-grok-4.5-parent; session pns-flow-delivery-80eb3dd0-3256-4604-afd9-916fe8923af8",
    "active_prepared_input_sent_unresolved_action_ids": [],
    "historical_unresolved_classification": "No active unresolved consequential action."
  },
  "evidence": {
    "evidence_requirement": "REQUIRED_FOR_LIVE",
    "evidence_requirement_reason": "Navigation-only live canaries must retain source/immediate-before/transport/immediate-post/semantic result under the flow artifact root.",
    "active_evidence_manifest": null,
    "do_not_recursively_inspect_parent_evidence_tree": true
  }
}
<!-- CURRENT_HANDOFF_STATE_END -->

# Current handoff

Volatile operational boundary only. History lives in Git, BACKLOG.md, retained evidence, and
authoritative journals.

## Atomic task outcome

CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION live canaries and Stage-9 provenance for
1-20-9, 1-15-9, and 2-2-9 are complete. Zero-transport destination replay verifies all three.
AP execution never authorized. Registration/scheduler unchanged. Noah's Tavern remains next ready.

## Exact next action

Create the focused local commit, then 
ecord-commit + complete under the held lease. No push.

