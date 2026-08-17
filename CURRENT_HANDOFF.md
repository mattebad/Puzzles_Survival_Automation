<!-- CURRENT_HANDOFF_STATE_BEGIN -->
{
  "schema_version": 3,
  "branch": "main",
  "head_binding": "latest_commit_touches_handoff",
  "last_product_candidate_head": "1a3de21a5e6bdeba070e649a454f1609d9013cd2",
  "ahead_behind": {"source": "compute_from_git"},
  "attributable_dirty_paths": "compute_from_git_for_retire_legacy_bliss_runtime",
  "task_start_worktree": {"tracked_dirty_paths": [], "protected_untracked_paths": [".local-captures/", ".local-orchestrator/"]},
  "protected_user_owned_paths": [".local-reference/", ".local-captures/", ".local-tools/", "evidence/"],
  "current_task_id": "retire-legacy-bliss-runtime",
  "current_task_state": "completed",
  "next_task_id": null,
  "next_task_activation_status": "not_applicable",
  "active_task_or_flow": "legacy Bliss retirement and aggregate Daily Claim cutover",
  "active_delivery_stage": "completed_cutover",
  "active_execution_manifest_path": "docs/retire-legacy-bliss-runtime-repair-manifest-3.md",
  "queue_counts": {"ready": 0, "active": 0, "blocked": 8, "completed": 17, "needs_product_decision": 0},
  "first_ready_flow": "none",
  "next_ready_flow": "none",
  "development_lease_state": "absent",
  "runtime_ownership_state": "none",
  "writable_agent_state": "none",
  "unresolved_action_state": "clear",
  "latest_focused_validation_result": "Cutover complete. Consolidated parent suite passed 208 tests; final provider/authority suites passed 147 and 97 tests; post-review navigation/Campaign/Supply suites passed 138 tests; Daily planning passed 11 tests; checked-in focused profile passed 9 and shared-navigation passed 18. Changed-file Ruff checks pass except the repository's pre-existing executable-script E402 import-order pattern. Final Terra High read-only review reported no material findings.",
  "latest_full_suite_result": "Manual opt-in only; not run.",
  "current_live_attempt_state": "not admitted; receipt issuance failed closed before runtime ownership because the implementation candidate is uncommitted, so no gameplay input was issued",
  "current_evidence_or_session_reference": ".local-captures/development-sessions/observe-20260817T043426964464Z",
  "last_safe_completed_step": "Final Terra High read-only closure review reported no material findings after all retired-provider code, policy, matrix, roadmap, and prompt inconsistencies were repaired; no gameplay input was issued.",
  "exact_next_permitted_action": "Review and commit the completed cutover. A future aggregate Daily Claim live acceptance requires a clean committed candidate and fresh selected-Daily preconditions.",
  "current_blocker": null,
  "prohibited_repeated_action": "Do not invoke retired Bliss gameplay paths, direct ADB, remote pnsctl commands, a second Claim tap, another gameplay flow, registration, scheduling, composition, or M6.",
  "control_owner": "sol_parent",
  "control_parent_conversation_id": "6f7e9bb4-7ecf-4dfe-ac13-98cf0ba2b2fa",
  "stage_revision": "retire-legacy-bliss-runtime-repair-3",
  "stage_type": "repair",
  "product_precondition": "proven",
  "failure_class": null,
  "budgets": {"per_stage": {"implementation": 1, "repair": 1, "review": 1, "recheck": 1, "live_attempt": 1}, "per_parent_conversation": {"managed_turns": 8, "stage_revisions": 3}},
  "recent_relevant_commits": ["1a3de21a5e6bdeba070e649a454f1609d9013cd2", "99c152ded8119f2eaa82058813bb4f7f2aacc813", "da4aa1d", "d883a42", "5e61591"],
  "registration_and_scheduler": {"retired_bliss_operator_tasks": ["alliance-help", "praise", "personal-might-claim"], "scheduler_enabled_disabled": "DISABLED/INELIGIBLE", "scheduler_eligible_flows": [], "composition_blocked": true, "m6_unactivated": true, "active_runtime": "local BlueStacks only"},
  "journals_and_lease": {"development_lease_path": ".local-orchestrator/flow-delivery-lease.json", "development_lease_status": "absent", "active_prepared_input_sent_unresolved_action_ids": [], "historical_journals": "immutable and non-authorizing"},
  "evidence": {"evidence_requirement": "REQUIRED_FOR_LIVE_CANARY_ONLY", "evidence_requirement_reason": "A live canary requires a clean committed candidate plus fresh selected-Daily aggregate Claim preconditions and semantic successor proof. Receipt issuance rejected the dirty candidate before any runtime input.", "active_evidence_manifest": null, "do_not_recursively_inspect_parent_evidence_tree": true}
}
<!-- CURRENT_HANDOFF_STATE_END -->

# Current handoff

Legacy Bliss gameplay execution is retired. Local BlueStacks is the sole active
runtime; reusable Plink/PSCP, Unraid, private ADB, worker, capture, and Docker
build primitives are isolated in the manual-only `scripts/bliss_porting/`
toolbox.

Daily Claim is one aggregate selected-Daily action. Objective handlers only
attribute completion. One ordinary free non-milestone Claim control may be
tapped once; success requires increased Daily points and no remaining ordinary
Claim controls. No per-row loop, objective binding, fixed point delta, or
second Claim tap is permitted.
