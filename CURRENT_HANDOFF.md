<!-- CURRENT_HANDOFF_STATE_BEGIN -->
{
  "schema_version": 2,
  "branch": "main",
  "head": "6d8fdd91cd3400263c82ae479e180f1dbc4bf343",
  "ahead_behind": {
    "ahead": 0,
    "behind": 0
  },
  "attributable_dirty_paths": [
    "BACKLOG.md",
    "CURRENT_HANDOFF.md",
    "tasks/backlog_task_index.json",
    "tasks/flow_delivery_queue.json",
    "tests/test_campaign_story_destinations.py",
    "tests/test_flow_delivery_authority_consistency.py",
    "tests/test_flow_delivery_orchestrator.py"
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
  "current_task_id": "CAMPAIGN-ATLAS-BACKLOG-DEPENDENCY-RECONCILIATION",
  "current_task_state": "completed",
  "next_task_id": "CAMPAIGN-ATLAS-SURVEY-CONTRACT-AND-COLLECTOR-PREP",
  "next_task_activation_status": "ready",
  "active_task_or_flow": "none",
  "active_delivery_stage": null,
  "queue_counts": {
    "ready": 7,
    "active": 0,
    "blocked": 12,
    "completed": 2,
    "needs_product_decision": 1
  },
  "first_ready_flow": "CAMPAIGN-ATLAS-SURVEY-CONTRACT-AND-COLLECTOR-PREP",
  "next_ready_flow": "CAMPAIGN-ATLAS-SURVEY-CONTRACT-AND-COLLECTOR-PREP",
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
    "note": "Campaign Atlas prep-scope correction began from clean 6d8fdd9. This handoff records the pre-commit head; the corrective commit advances Git by one. Do not auto-start collector prep or runtime."
  },
  "latest_focused_validation_result": "Passed 95 focused flow-delivery orchestrator, Campaign separation, authority consistency, token/context hygiene, and governance tests; corrected backlog index generated 22 tasks; git diff --check passed.",
  "latest_full_suite_result": "Not requested; prior handoff recorded 1121 passed, 1 expected skip.",
  "current_live_attempt_state": "No runtime input occurred. All three Campaign Atlas tasks, Campaign AP, and Ultimate Challenge retain maximum_live_attempts=0 and additional_live_attempts_authorized=0.",
  "current_evidence_or_session_reference": "No canonical Campaign Atlas corpus exists. Ignored local Campaign frames remain mechanics/landmark candidates only and were not promoted or modified.",
  "last_safe_completed_step": "Narrowed the first Campaign Atlas task to survey contract and fail-closed zero-input collector preparation; final atlas geometry, anchors, thresholds, localization, navigation, and replay remain after native corpus acquisition.",
  "exact_next_permitted_action": "Start only the offline backlog task CAMPAIGN-ATLAS-SURVEY-CONTRACT-AND-COLLECTOR-PREP in a new atomic turn; define the native evidence schema, HUD masks, generic registration seam, bounded scan contract, and zero-input collector tests without implementing the atlas.",
  "current_blocker": "Native survey and downstream integration remain dependency-blocked; the survey additionally requires separate explicit authorization and a checked-in nonzero navigation-only attempt budget.",
  "prohibited_repeated_action": "Do not issue runtime input, use difficulty switching as recentering, create synthetic atlas evidence, operate BlueStacks/Bliss/ADB/SSH/Docker, start the native survey or either consumer, register a flow, enable scheduler eligibility, or alter unrelated policy.",
  "recent_relevant_commits": [
    "6d8fdd9 sequence Campaign Atlas work (scope corrected by this task)",
    "2d1dc50 gate Ultimate Challenge execution evidence",
    "9c281a7 reconcile approved gameplay policy",
    "8def80d centralize Campaign destinations",
    "72b07a7 separate Campaign and Ultimate Challenge flows"
  ],
  "process_deviations": [
    "The initial Foundation label and scope were broader than the evidence-first sequence required; this correction narrows the first task before any implementation or runtime work began."
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
    "historical_unresolved_classification": "No active unresolved consequential action; retained historical attempts/evidence were not modified."
  },
  "evidence": {
    "evidence_requirement": "NOT_APPLICABLE",
    "evidence_requirement_reason": "This authority-only task creates no evidence. Campaign Atlas native acquisition remains a separate dependency-blocked task with zero attempts.",
    "active_evidence_manifest": null,
    "do_not_recursively_inspect_parent_evidence_tree": true
  }
}
<!-- CURRENT_HANDOFF_STATE_END -->

# Current handoff

Volatile operational boundary only. History lives in Git, `BACKLOG.md`, retained evidence, and
authoritative journals.

## Atomic task outcome

`CAMPAIGN-ATLAS-BACKLOG-DEPENDENCY-RECONCILIATION` now establishes three evidence-ordered atomic
tasks: survey-contract/collector preparation, native survey/validation, and shared navigation integration/replay. Campaign AP and
Ultimate Challenge now depend on the accepted shared navigation layer. The atlas must localize an
arbitrary Campaign viewport; difficulty switching is explicitly not a recenter strategy.

Collector preparation is offline and ready, but it must not build atlas geometry, semantic anchors,
thresholds, a localizer, or a navigator before the native corpus exists. Survey and integration remain
blocked, all attempt budgets remain zero, and retained local Campaign frames remain mechanics/landmark
candidates rather than promoted atlas evidence. No runtime input, evidence fabrication, registration,
or scheduler promotion occurred.

## Exact next action

Do not auto-start runtime or any downstream flow. The exact next permitted atomic task is
`CAMPAIGN-ATLAS-SURVEY-CONTRACT-AND-COLLECTOR-PREP`: native evidence/provenance schema, HUD masks,
generic registration seam API, bounded four-edge/overlap scan contract, and a fail-closed zero-input
collector dry run. It must not implement final atlas geometry, anchors, thresholds, localization,
navigation, or production replay.
