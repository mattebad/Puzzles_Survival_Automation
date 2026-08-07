<!-- CURRENT_HANDOFF_STATE_BEGIN -->
{
  "schema_version": 2,
  "branch": "main",
  "head": "7934bb781563edd362890c1ed0c56dbab429ed7e",
  "ahead_behind": {"ahead": 0, "behind": 0},
  "attributable_dirty_paths": ["CURRENT_HANDOFF.md", "scripts/flow_delivery_control.py", "scripts/flow_delivery_ruins_challenge_bluestacks.py", "scripts/pnsctl.py", "scripts/ruins_challenge_bluestacks.py", "tasks/flow_delivery_queue.json"],
  "protected_user_owned_paths": [".local-reference/", ".local-captures/", "evidence/"],
  "current_task_id": "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION",
  "current_task_state": "blocked_external_runtime_binding",
  "next_task_id": "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION",
  "next_task_activation_status": "blocked_until_supported_desktop_binding",
  "active_task_or_flow": "",
  "active_delivery_stage": "blocked",
  "queue_counts": {"ready": 5, "active": 0, "blocked": 9, "completed": 8, "needs_product_decision": 1},
  "first_ready_flow": "NOAHS-TAVERN-DYNAMIC-UI-MIGRATION",
  "next_ready_flow": "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION after supported desktop binding",
  "development_lease_state": "released",
  "runtime_ownership_state": "released",
  "writable_agent_state": "absent",
  "unresolved_action_state": "clear",
  "latest_focused_validation_result": "Ruins, Home Atlas, and accepted zoom-recovery focused tests passed 90/90 after automatic recovery integration and host-failure diagnostics.",
  "latest_full_suite_result": "Manual opt-in only; not run.",
  "current_live_attempt_state": "Zero of six authorized Ruins navigation attempts used. Three retained native-frame-gated runs were reconciled as zero-input blocks; resource delta 0.",
  "current_evidence_or_session_reference": ".local-captures/flow-delivery/RUINS-CHALLENGE-HOME-ATLAS-MIGRATION/nav-20260807T051232931405Z/ruins-challenge-20260807T051233457119Z",
  "last_safe_completed_step": "The Ruins runner automatically selected RECOVER_ZOOM from the accepted Home localizer, then stopped before wheel dispatch because the current process could not see a supported host window.",
  "exact_next_permitted_action": "Restore a supported interactive desktop binding for the active HD-Player window, then reacquire the sole Ruins lease, rerun the zero-transport production replay and preflight, and make one bounded navigation-only Home-to-Ruins-to-Home attempt.",
  "current_blocker": "BlueStacksHostZoomTransport correctly found zero exact host windows in this task process although HD-Player.exe runs in the active desktop session; no pnsctl operation may bridge that session boundary.",
  "prohibited_repeated_action": "Do not dispatch challenge, combat, chest, Exchange, purchase, reward, or resource actions; do not issue an identical navigation retry after a failed postcondition.",
  "recent_relevant_commits": ["ebb5e71", "c1c76d1", "d104291"],
  "process_deviations": [],
  "registration_and_scheduler": {"registered_operator_tasks": "NOT_REGISTERED_UNCHANGED", "scheduler_enabled_disabled": "DISABLED/INELIGIBLE", "scheduler_eligible_flows": [], "composition_blocked": true, "m6_unactivated": true, "bliss_unchanged": true},
  "journals_and_lease": {"development_lease_path": ".local-orchestrator/flow-delivery-lease.json", "development_lease_status": "released_after_safe_zero_input_block", "active_prepared_input_sent_unresolved_action_ids": [], "historical_unresolved_classification": "No Ruins consequential input was prepared or sent. The bounded auxiliary zoom guard stopped before wheel dispatch in the unavailable desktop session."},
  "evidence": {"evidence_requirement": "EVIDENCE_REQUIRED", "evidence_requirement_reason": "The retained zero-input observations prove the block; live navigation-only Home-to-Ruins-to-Home evidence remains required after the desktop binding is restored.", "active_evidence_manifest": null, "do_not_recursively_inspect_parent_evidence_tree": true}
}
<!-- CURRENT_HANDOFF_STATE_END -->

# Current handoff

`CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY` is complete end to end. The production controller proved
Home Atlas entry, exact destination navigation, Challenge, lineup confirmation, Auto Battle,
verified victory, exact AP reconciliation including natural regeneration, and recognized Home for
`1-20-9`, `2-2-9`, and `1-15-9`. No refill, paid action, Sweep, Blitz, Auto Complete, Ultimate
Challenge action, registration, scheduler, composition, M6, or Bliss mutation occurred.

Ultimate Challenge is complete. Attempt 13 proved the exact gold Flee action and zero resource
delta; attempt 14 used two verified navigation inputs to return through Campaign to canonical Home.
The retained production evidence validates as `complete_for_reset` and `recognized_home`.

`RUINS-CHALLENGE-HOME-ATLAS-MIGRATION` is authorized ahead of Noah's Tavern with a six-attempt
navigation-only budget. Its existing Ruins Atlas binding and revalidated safe exit now use the
accepted automatic Home preparation path immediately before binding: `BlueStacksLocalizeFirstHomeDriver`,
`RECOVER_ZOOM`, `NavigationGuardedRuntime.dispatch_zoom_out`, and `BlueStacksHostZoomTransport`.
The recovery is bounded to four auxiliary zoom inputs, retains native immediate-before and
immediate-post frames, and reclassifies after each zoom input. No challenge, combat, chest,
Exchange, purchase, reward, or resource action is authorized.

Focused Ruins/Home Atlas/zoom-recovery validation passes 90/90. The production-path zero-transport
replay and live preflight passed. Three subsequent native-frame-gated runs produced zero dispatched
inputs and zero resource delta: the first exposed an over-strict Ruins OCR gate (repaired to use the
accepted Home localizer), and the latter two established that `BlueStacksHostZoomTransport` cannot
see the active HD-Player window from this task process. The transport stopped before a wheel input;
the controller reconciled all three as zero-input observations, retained their evidence, blocked the
flow, and released the lease. Resume only after a supported interactive desktop/window binding is
available; do not issue an identical retry.
