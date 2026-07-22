<!-- CURRENT_HANDOFF_STATE_BEGIN -->
{
  "schema_version": 2,
  "branch": "main",
  "head": "9efb433f58874b60e9be84d158b05ef0b6fb2ea9",
  "ahead_behind": {
    "ahead": 11,
    "behind": 0
  },
  "attributable_dirty_paths": [
    "tasks/flow_delivery_product_policy.json",
    "tasks/gameplay_flow_contracts/NOVA-PRAISE-HOME-ATLAS-MIGRATION.json",
    "tasks/flow_delivery_queue.json",
    "BACKLOG.md",
    "CURRENT_HANDOFF.md"
  ],
  "protected_user_owned_paths": [
    ".cursor/plans/** (accepted Cursor plan; ignored and not edited during implementation)",
    ".specstory/**",
    ".vscode/**",
    "Puzzle_Survival_Runtime_POC.zip",
    "evidence/**",
    ".local-reference/**",
    ".local-captures/**"
  ],
  "current_task_id": "GF-NOVA-PRAISE-SUPERVISED-20260722",
  "current_task_state": "in_progress",
  "next_task_id": "GF-MVP-010-LIVE-EVIDENCE-TO-REPLAY",
  "next_task_activation_status": "ready_not_active",
  "active_task_or_flow": "none",
  "active_delivery_stage": null,
  "queue_counts": {
    "ready": 6,
    "active": 0,
    "blocked": 5,
    "completed": 0,
    "needs_product_decision": 4
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
    "note": "GF-MVP-009 completed in the accepted 20260722T020656687010Z session. Current work is one separately authorized supervised free Praise pulse after the 2026-07-22 reset."
  },
  "latest_focused_validation_result": "160 focused Nova/command/replay/Home/governance tests passed; independent production-call-graph review approved",
  "latest_full_suite_result": "1121 tests passed; 1 expected skip; 0 failures/errors",
  "current_live_attempt_state": "No supervised Praise attempt started; maximum one invocation and one consequential Praise remain authorized after offline validation and a committed candidate.",
  "current_evidence_or_session_reference": ".local-captures/flow-delivery/NOVA-PRAISE-HOME-ATLAS-MIGRATION/nova-navigation-canary-20260722T020656687010Z",
  "last_safe_completed_step": "Accepted the canonical no-Praise Home-to-Nova-to-Home run with four navigation inputs, zero Praise, and verified terminal Home.",
  "exact_next_permitted_action": "Implement the pnsctl full-route composition, validate attempts/cooldown and fail-closed controls offline, commit the candidate, then run exactly one supervised BlueStacks invocation.",
  "current_blocker": null,
  "prohibited_repeated_action": "Do not rerun the no-Praise canary, loop through restored attempts, dispatch a second Praise, retry an unresolved action, spend currency, register production, enable scheduling, or issue Bliss input.",
  "recent_relevant_commits": [
    "e345db9 fix(flow-factory): bind Nova radial with retained template",
    "dc8210c fix(flow-factory): normalize known Nova canary start",
    "58f7343 feat(flow-factory): migrate Nova navigation canary",
    "188ebd0 feat(flow-factory): add Nova scenario accounting",
    "6b89a20 fix(flow-factory): enforce executable evidence integrity"
  ],
  "process_deviations": [
    "GF-MVP-009 required a committed known-Nova start correction after a non-consuming pre-input block; the corrected execution then exhausted its one-attempt budget.",
    "User authorized one changed-candidate continuation after e345db9 offline proof; it stopped pre-input on stale radial provenance, so blocked-path policy revoked any further attempt."
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
    "historical_unresolved_classification": "No active unresolved consequential action; historical unresolved snapshots remain retained evidence only. The new Praise action must use its centralized durable journal."
  },
  "evidence": {
    "evidence_requirement": "REQUIRED",
    "evidence_requirement_reason": "Retain the completed no-Praise route, current-reset attempts-before frame, immediate-before target, one Praise transport, exact decrement/cooldown successor, journal result, and terminal Home.",
    "active_evidence_manifest": "pending supervised Praise session result",
    "do_not_recursively_inspect_parent_evidence_tree": true
  }
}
<!-- CURRENT_HANDOFF_STATE_END -->

# Current handoff

Volatile operational boundary only. History lives in Git, `BACKLOG.md`, and retained evidence.

## Repository
- Branch: `main` @ `9efb433`
- `GF-MVP-009-NOVA-NAVIGATION-LIVE-CANARY`: **completed** by the accepted full-route session
- Current task: `GF-NOVA-PRAISE-SUPERVISED-20260722` (**in progress**)
- Runtime ownership: none; live attempt not started
- Push: prohibited

## Exact next action
Implement and validate the supported one-Praise pnsctl composition, commit it, then execute at most
one supervised BlueStacks invocation bound to `game-day-2026-07-22`.
