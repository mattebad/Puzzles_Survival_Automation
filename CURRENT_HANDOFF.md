<!-- CURRENT_HANDOFF_STATE_BEGIN -->
{
  "schema_version": 2,
  "branch": "main",
  "head": "11ee3b3f10cb5aa052a22ffdebf25636856cf7b8",
  "ahead_behind": {
    "ahead": 0,
    "behind": 0
  },
  "attributable_dirty_paths": [
    "tasks/nova_praise_vision.py",
    "scripts/nova_praise_bluestacks.py",
    "tasks/assets/nova_praise/800x1280/**",
    "tests/fixtures/nova_praise_preflight/manifest.json",
    "tests/fixtures/nova_praise_preflight/blocked-canary-radial-48a116d3.png",
    "tests/test_nova_navigation_canary.py",
    "tasks/flow_scenario_attempts.py",
    "tests/test_flow_scenario_attempts.py",
    "tasks/flow_delivery_queue.json",
    "tasks/backlog_task_index.json",
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
  "current_task_state": "in_progress",
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
    "note": "GF-MVP-009 offline correction pending parent validation/commit; flow and named ledgers synchronized at max2/count1; queue remains inactive."
  },
  "latest_focused_validation_result": "160 focused Nova/command/replay/Home/governance tests passed; independent production-call-graph review approved",
  "latest_full_suite_result": "1121 tests passed; 1 expected skip; 0 failures/errors",
  "current_live_attempt_state": "flow live max 2 count 1 with immutable blocked dc8210c attempt; named scenario max 2 count 1 ready; no fabricated future attempt; zero Praise; queue inactive",
  "current_evidence_or_session_reference": ".local-captures/flow-delivery/NOVA-PRAISE-HOME-ATLAS-MIGRATION/nova-navigation-canary-20260721T230841195923Z",
  "last_safe_completed_step": "Offline GF-MVP-009 correction: measured Home context on radial binds, template Nova bind, provenance-gated continuation, synchronized flow/scenario attempt ledgers.",
  "exact_next_permitted_action": "Parent validates/commits the offline correction (correction_ref GF-MVP-009-nova-radial-template-bind), then may authorize exactly one live attempt on the changed candidate. Do not rerun dc8210c; do not start GF-MVP-010.",
  "current_blocker": "correction passed parent offline validation and awaits focused commit before the one authorized second live attempt",
  "prohibited_repeated_action": "Do not rerun candidate dc8210c; do not issue live/runtime input before parent validation/commit; do not tap Praise; do not start GF-MVP-010, Milestone B, queue activation, or production scheduling.",
  "recent_relevant_commits": [
    "dc8210c fix(flow-factory): normalize known Nova canary start",
    "58f7343 feat(flow-factory): migrate Nova navigation canary",
    "188ebd0 feat(flow-factory): add Nova scenario accounting",
    "6b89a20 fix(flow-factory): enforce executable evidence integrity",
    "b142e21 feat(flow-factory): add Nova production replay"
  ],
  "process_deviations": [
    "GF-MVP-009 required a committed known-Nova start correction after a non-consuming pre-input block; the corrected execution then exhausted its one-attempt budget; user later authorized one additional changed-candidate attempt after offline template-radial correction."
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
    "evidence_requirement_reason": "GF-MVP-009 attempt 1 issued two navigation inputs and must retain the terminal blocked evidence sequence; correction adds committed fixture/template provenance without mutating retained session bytes.",
    "active_evidence_manifest": "docs/validation/gf-mvp-009-blocked-canary-manifest.json",
    "do_not_recursively_inspect_parent_evidence_tree": true
  }
}
<!-- CURRENT_HANDOFF_STATE_END -->

# Current handoff

Volatile operational boundary only. History lives in Git, `BACKLOG.md`, and retained evidence.

## Repository
- Branch: `main` @ `11ee3b3` (pre-correction HEAD; validated correction uncommitted)
- `GF-MVP-009-NOVA-NAVIGATION-LIVE-CANARY`: **correction validated; focused commit pending**; flow live max 2 / count 1; scenario max 2 / count 1 / ready
- Flow-delivery queue: **not activated** (`active_flow_id` null)
- Runtime ownership: none
- Push: prohibited

## Exact next action
Parent validates/commits the offline template-radial correction (`GF-MVP-009-nova-radial-template-bind`),
then may authorize exactly one live attempt on the changed candidate. Do not rerun `dc8210c`, start
`GF-MVP-010`, or issue gameplay input before that validation/commit.
