<!-- CURRENT_HANDOFF_STATE_BEGIN -->
{
  "schema_version": 2,
  "branch": "main",
  "head": "514b0b20fcba88f94f43860a9c8ee9962c091d99",
  "ahead_behind": {
    "ahead": 0,
    "behind": 0
  },
  "attributable_dirty_paths": [
    "BACKLOG.md",
    "CURRENT_HANDOFF.md",
    "tasks/backlog_task_index.json",
    "tasks/flow_delivery_queue.json",
    "tasks/campaign_atlas.py",
    "tasks/campaign_atlas_vision.py",
    "tasks/gameplay_flow_contracts/CAMPAIGN-ATLAS-SURVEY-CONTRACT-AND-COLLECTOR-PREP.json",
    "tasks/gameplay_flow_contracts/CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION.json",
    "tasks/gameplay_flow_contracts/CAMPAIGN-ATLAS-NAVIGATION-INTEGRATION-AND-REPLAY.json",
    "scripts/campaign_atlas_bluestacks.py",
    "tests/test_campaign_atlas.py",
    "tests/test_campaign_atlas_vision.py",
    "tests/test_campaign_atlas_collector.py",
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
  "current_task_id": "CAMPAIGN-ATLAS-SURVEY-CONTRACT-AND-COLLECTOR-PREP",
  "current_task_state": "completed",
  "next_task_id": "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION",
  "next_task_activation_status": "dependency_blocked",
  "active_task_or_flow": "none",
  "active_delivery_stage": null,
  "queue_counts": {
    "ready": 6,
    "active": 0,
    "blocked": 12,
    "completed": 3,
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
    "note": "Campaign Atlas survey-contract preparation began from clean 514b0b2. This handoff records the pre-commit head; the focused commit advances Git by one. Do not auto-start the native survey or another ready queue flow."
  },
  "latest_focused_validation_result": "Passed 91 required Campaign atlas, authority consistency, gameplay-contract, flow-delivery orchestrator, and governance tests; backlog index generated 22 tasks; git diff --check passed.",
  "latest_full_suite_result": "Not requested; prior handoff recorded 1121 passed, 1 expected skip.",
  "current_live_attempt_state": "No runtime input occurred. All three Campaign Atlas tasks, Campaign AP, and Ultimate Challenge retain maximum_live_attempts=0 and additional_live_attempts_authorized=0.",
  "current_evidence_or_session_reference": "No canonical Campaign Atlas corpus exists. Ignored local Campaign frames remain mechanics/landmark candidates only and were not promoted or modified.",
  "last_safe_completed_step": "Completed the immutable native-frame schema, fixed-HUD mask contract, injected threshold-free registration measurement seam, bounded zero-budget scan topology, and fail-closed offline collector; no corpus or atlas was created.",
  "exact_next_permitted_action": "Prepare a separate atomic activation for CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION only after explicit user authorization and a reviewed checked-in nonzero navigation-only attempt budget; until then issue no runtime input.",
  "current_blocker": "The native survey requires separate explicit authorization and a reviewed checked-in nonzero navigation-only attempt budget; integration, Campaign AP, and Ultimate Challenge remain dependency-blocked behind accepted native evidence.",
  "prohibited_repeated_action": "Do not issue runtime input, use difficulty switching as recentering, create synthetic atlas evidence, operate BlueStacks/Bliss/ADB/SSH/Docker, start the native survey or either consumer, register a flow, enable scheduler eligibility, or alter unrelated policy.",
  "recent_relevant_commits": [
    "514b0b2 narrow Campaign Atlas prep scope",
    "6d8fdd9 sequence Campaign Atlas work (scope corrected by this task)",
    "2d1dc50 gate Ultimate Challenge execution evidence",
    "9c281a7 reconcile approved gameplay policy",
    "8def80d centralize Campaign destinations"
  ],
  "process_deviations": [],
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
    "evidence_requirement_reason": "This prep task creates no evidence. Native hash-bound Campaign survey acquisition remains a separate blocked task with zero authorized attempts.",
    "active_evidence_manifest": null,
    "do_not_recursively_inspect_parent_evidence_tree": true
  }
}
<!-- CURRENT_HANDOFF_STATE_END -->

# Current handoff

Volatile operational boundary only. History lives in Git, `BACKLOG.md`, retained evidence, and
authoritative journals.

## Atomic task outcome

`CAMPAIGN-ATLAS-SURVEY-CONTRACT-AND-COLLECTOR-PREP` is complete offline. It adds immutable native
800x1280 provenance, a profile-bound HUD exclusion contract, an injected measurement-only registration
seam with no acceptance thresholds, the reviewed abstract survey phases with zero current input and
acquisition budgets, and a fail-closed collector dry run.

No Campaign corpus, atlas tiles, geometry, semantic anchors, localizer, navigator, replay, or runtime
evidence was created. The native survey and integration remain blocked, all attempt budgets remain
zero, and retained local Campaign frames remain mechanics/landmark candidates rather than promoted
atlas evidence. Registration and scheduler eligibility remain unchanged.

## Exact next action

Do not auto-start runtime or another ready queue flow. The next Campaign dependency is
`CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION`, but it remains blocked until a separate atomic task has
explicit user authorization and a reviewed checked-in nonzero navigation-only attempt budget. It may
then collect native four-edge and overlapping viewport evidence without using difficulty switching as
recentring and without executing Campaign AP or Ultimate Challenge actions.
