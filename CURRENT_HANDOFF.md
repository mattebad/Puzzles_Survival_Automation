<!-- CURRENT_HANDOFF_STATE_BEGIN -->
{
  "schema_version": 2,
  "branch": "main",
  "head": "pending containing commit: fix(automation): add preToolUse Task routing gate",
  "ahead_behind": {
    "ahead": 27,
    "behind": 0
  },
  "attributable_dirty_paths": [],
  "protected_user_owned_paths": [
    ".cursorindexingignore (pre-existing user-owned modification outside allowlisted hunks)",
    ".specstory/**",
    ".vscode/**",
    "Puzzle_Survival_Runtime_POC.zip",
    "evidence/**",
    ".local-reference/**",
    ".local-captures/**",
    "scripts/bluestacks_campaign_ap.py (Campaign WIP preserved)",
    "scripts/home_atlas_bluestacks.py (Campaign WIP preserved)",
    "tasks/campaign_auto_battle.py (Campaign WIP preserved)",
    "tasks/campaign_auto_battle_runtime.py (Campaign WIP preserved)",
    "tasks/campaign_auto_battle_vision.py (Campaign WIP preserved)",
    "tests/test_campaign_auto_battle.py (Campaign WIP preserved)",
    "tests/test_campaign_auto_battle_runtime.py (Campaign WIP preserved)",
    "tests/test_campaign_story_destinations.py (Campaign WIP preserved)",
    "tests/test_home_atlas_verified_route.py (Campaign WIP preserved)"
  ],
  "current_task_id": "FLOW-DELIVERY-PRETOOLUSE-TASK-ENFORCEMENT",
  "current_task_state": "blocked",
  "next_task_id": "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
  "next_task_activation_status": "ready",
  "active_task_or_flow": null,
  "active_delivery_stage": null,
  "queue_counts": {
    "ready": 9,
    "active": 0,
    "blocked": 2,
    "completed": 0,
    "needs_product_decision": 4
  },
  "first_ready_flow": "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION",
  "next_ready_flow": "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION",
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
    "note": "Maintenance task completions do not increment gameplay-flow counts; new parent identities start at zero."
  },
  "latest_focused_validation_result": "ide-native + orchestrator focused suites OK (58 tests)",
  "latest_full_suite_result": "not re-run after blocker; prior baseline 993 passed / 1 skipped",
  "current_live_attempt_state": "none",
  "current_evidence_or_session_reference": null,
  "last_safe_completed_step": "Offline preToolUse Task routing gate, shared policy, audit-only subagentStart, and focused tests landed; live enforcement blocked because Cursor 3.12.17 skips preToolUse for Task.",
  "exact_next_permitted_action": "Stop blocked. Do not claim enforcement success. Resume only when installed Cursor emits preToolUse for Task with deny honored before child creation, or a product decision accepts an alternate enforceable boundary that is not subagentStart deny and not CLI. Campaign remains first ready and is not activated here.",
  "current_blocker": "Cursor 3.12.17 does not invoke project preToolUse for Task; Task goes to subagentStart only, and subagentStart deny is not a reliable child-creation boundary.",
  "prohibited_repeated_action": "Claiming preToolUse Task enforcement success on this Cursor build; relying on subagentStart deny; Cursor CLI fallback; activating Campaign inside this blocked maintenance task; BlueStacks/ADB/gameplay input; push.",
  "recent_relevant_commits": [
    "fix(automation): add preToolUse Task routing gate (containing commit)",
    "57d25ba fix(automation): isolate review snapshot secret scanning",
    "8c8e74e feat(automation): limit completed flows per parent conversation",
    "0609eb8 chore(automation): reduce flow delivery context",
    "20811eb fix(automation): keep flow delivery in Cursor IDE"
  ],
  "process_deviations": [
    "Task blocked on installed Cursor preToolUse omission for Task; offline gate retained.",
    "Campaign WIP files preserved unstaged after orphaned Sol-High lease reconciliation."
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
    "evidence_requirement_reason": "Blocked offline routing-enforcement work creates no runtime evidence manifest and must not recursively inspect evidence/**.",
    "active_evidence_manifest": null,
    "do_not_recursively_inspect_parent_evidence_tree": true
  }
}
<!-- CURRENT_HANDOFF_STATE_END -->

# Current handoff

Volatile operational boundary only. History lives in Git, `BACKLOG.md`, and retained evidence.

## Repository
- Branch: `main`
- Task: `FLOW-DELIVERY-PRETOOLUSE-TASK-ENFORCEMENT` — **blocked**
- Blocker: Cursor 3.12.17 skips `preToolUse` for Task; only `subagentStart` runs, and deny there is not reliable
- Campaign remains first ready; Campaign code WIP preserved unstaged
- Push: prohibited

## Exact next action
Stop blocked. Do not claim enforcement success. Resume when Cursor emits enforceable Task `preToolUse` (deny before child creation) or a product decision chooses another enforceable non-CLI boundary.
