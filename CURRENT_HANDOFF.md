<!-- CURRENT_HANDOFF_STATE_BEGIN -->
{
  "schema_version": 2,
  "branch": "main",
  "head": "e345db945cf0b4537bc45d0e905dfb818519f7eb",
  "ahead_behind": {
    "ahead": 11,
    "behind": 0
  },
  "attributable_dirty_paths": [
    "tests/test_flow_scenario_attempts.py",
    "tasks/flow_delivery_queue.json",
    "tasks/backlog_task_index.json",
    "docs/validation/gf-mvp-009-template-canary-pre-input-manifest.json",
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
  "current_task_id": "GF-MVP-009-NOVA-NAVIGATION-LIVE-CANARY",
  "current_task_state": "blocked",
  "next_task_id": "GF-MVP-010-LIVE-EVIDENCE-TO-REPLAY",
  "next_task_activation_status": "dependency_blocked",
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
    "note": "GF-MVP-009 changed candidate stopped before input on stale radial provenance; no retry, GF-MVP-010, or Milestone B is authorized."
  },
  "latest_focused_validation_result": "160 focused Nova/command/replay/Home/governance tests passed; independent production-call-graph review approved",
  "latest_full_suite_result": "1121 tests passed; 1 expected skip; 0 failures/errors",
  "current_live_attempt_state": "e345db9 pre-input terminal block; zero navigation, transport, Praise, and consequential inputs; no further attempt authorized",
  "current_evidence_or_session_reference": ".local-captures/flow-delivery/NOVA-PRAISE-HOME-ATLAS-MIGRATION/nova-navigation-canary-20260722T010018285176Z",
  "last_safe_completed_step": "Captured and classified the current Research Lab radial, then stopped before input because fresh current-session Research Lab tap provenance was absent.",
  "exact_next_permitted_action": "Architecture/evidence review only. Do not retry, synthesize provenance, start GF-MVP-010, or begin Milestone B.",
  "current_blocker": "initial_radial_missing_research_lab_provenance on e345db9; changed-candidate authorization terminated",
  "prohibited_repeated_action": "Do not rerun dc8210c or e345db9; do not Back, reopen Research Lab, tap Nova/Praise, issue any gameplay input, start GF-MVP-010, Milestone B, queue activation, or production scheduling.",
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
    "historical_unresolved_classification": "No active unresolved consequential action; historical unresolved snapshots remain retained evidence only."
  },
  "evidence": {
    "evidence_requirement": "REQUIRED",
    "evidence_requirement_reason": "Retain both the prior two-input Hough blocker and the e345db9 source-only stale-provenance terminal block.",
    "active_evidence_manifest": "docs/validation/gf-mvp-009-template-canary-pre-input-manifest.json",
    "do_not_recursively_inspect_parent_evidence_tree": true
  }
}
<!-- CURRENT_HANDOFF_STATE_END -->

# Current handoff

Volatile operational boundary only. History lives in Git, `BACKLOG.md`, and retained evidence.

## Repository
- Branch: `main` @ `e345db9`
- `GF-MVP-009-NOVA-NAVIGATION-LIVE-CANARY`: **blocked**; changed candidate stopped pre-input; no retry
- Flow-delivery queue: **not activated** (`active_flow_id` null)
- Runtime ownership: none
- Push: prohibited

## Exact next action
Architecture/evidence review only. Do not rerun `dc8210c` or `e345db9`, synthesize radial provenance,
start `GF-MVP-010`, begin Milestone B, or issue gameplay input.
