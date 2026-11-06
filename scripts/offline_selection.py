"""Risk-based offline CI selection; full discovery remains an independent inventory."""
from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

ROUTE_BOUNDARIES = {
    "recruitment": "tests.test_service_recruitment.ServiceRecruitmentTests.test_native_pass_cooldown_restart_and_later_eligibility",
    "nova": "tests.test_service_nova.ServiceNovaTests.test_cooldown_survives_restart_then_one_due_pulse_and_reset",
    "campaign": "tests.test_service_campaign_ap.CampaignServiceRunnerTests.test_composed_vip_chapter_tier_home_ap12_defers_under_one_claim",
    "bioenhancer": "tests.test_service_bioenhancer.ServiceBioenhancerTests.test_native_effect_and_no_work_keep_actual_counts_and_utc_deadline",
    "supply": "tests.test_service_supply.ServiceSupplyTests.test_free_effect_and_zero_work_have_exact_counts_and_actual_reset",
    "ultimate": "tests.test_service_ultimate.UltimateServiceTests.test_prior_completed_day_allows_one_current_flee_home_then_idempotent_repeat",
    "enhancement": "tests.test_service_enhancement.ServiceEnhancementTests.test_full_family_uses_one_wrapper_and_current_proof_with_exact_counts",
    "personal-might": "tests.test_service_personal_might.ServicePersonalMightTests.test_real_boundary_one_praise_then_current_day_gray_repeat_no_praise",
}

# Native Home/Back admission uses different OCR backend builds on the two CI
# hosts. Pair supported-layout positives with denials in the owning layer,
# then verify that Atlas cannot override those denials with confident geometry.
HOME_ADMISSION_BASELINE = (
    "tests.test_home_base_vision.CleanHomeLabelTests.test_latest_native_home_control_ocr_regression_and_native_positives",
    "tests.test_home_base_vision.CleanHomeLabelTests.test_missing_home_control_source_is_not_home",
    "tests.test_home_base_vision.CleanHomeLabelTests.test_missing_navigation_or_base_scene_is_not_home",
    "tests.test_home_control_layouts.HomeControlLayoutTests",
    "tests.test_startup_recovery.StartupRecoveryTests.test_current_and_old_native_scarlett_pages_share_semantic_back_binding",
    "tests.test_startup_recovery.StartupRecoveryTests.test_scarlett_rejects_native_dialog_and_missing_or_unsafe_back",
    "tests.test_atlas_flow_startup.AtlasFlowStartupTests.test_native_zoomed_home_uses_canonical_clean_home_for_one_bounded_zoom",
    "tests.test_atlas_flow_startup.AtlasFlowStartupTests.test_popup_and_radial_home_sources_block_before_zoom_transport",
)

WINDOWS_BASELINE = (
    "tests.test_safe_action_core.ExecutorCase",
    "tests.test_safe_action_core.CrashBoundaryCase",
    "tests.test_safe_action_core.PolicyCase",
    "tests.test_safe_action_core.LeaseCase",
    "tests.test_automation_service_adapters",
    "tests.test_runtime_identity",
    "tests.test_runtime_profile_unification",
    "tests.test_service_route_contract",
    "tests.test_test_discovery",
    "tests.test_test_environment",
    "tests.test_ocr_memo",
    "tests.test_offline_selection",
    "tests.test_check_entrypoint",
    "tests.test_route_metadata_consistency",
    "tests.test_enhancement_native_material_contract",
    "tests.test_semantic_ocr_crop",
    "tests.test_task_module",
    "tests.test_input_capability_firewall.CapabilityFirewallTests.test_valid_navigation_one_shot_mocked_dispatch",
    "tests.test_input_capability_firewall.CapabilityFirewallTests.test_navigation_capability_cannot_dispatch_consequential",
    "tests.test_input_capability_firewall.CapabilityFirewallTests.test_scope_session_task_action_target_capture_digest_coordinate_mismatches",
    "tests.test_input_capability_firewall.CapabilityFirewallTests.test_moved_target_final_revalidation",
    "tests.test_input_capability_firewall.CapabilityFirewallTests.test_final_consume_rechecks_every_policy_guard",
    "tests.test_input_capability_firewall.CapabilityFirewallTests.test_concurrent_double_consumption_allows_at_most_one",
    "tests.test_input_capability_firewall.CapabilityFirewallTests.test_reuse_after_terminal_fails_closed",
    "tests.test_input_capability_firewall.CapabilityFirewallTests.test_process_global_block_consumes_supplied_capability_without_transport",
    "tests.test_input_capability_firewall.CapabilityFirewallTests.test_train_upgrade_claim_markers_denied_for_navigation_capability",
    "tests.test_automation_service_state.AutomationServiceStateTests.test_fresh_database_and_flow_spec_defaults_are_disabled",
    "tests.test_automation_service_state.AutomationServiceStateTests.test_lease_and_run_fences_reject_every_mismatching_identity",
    "tests.test_automation_service_state.AutomationServiceStateTests.test_post_transport_unknown_crosses_generation_fences_without_refund_or_retry",
    "tests.test_automation_service_state.AutomationServiceStateTests.test_restart_orphan_recovery_reclaims_reservation_but_blocks_unknown_dispatch",
    "tests.test_automation_service_state.AutomationServiceStateTests.test_twenty_managers_yield_one_active_claim",
    "tests.test_automation_service_state.AutomationServiceStateTests.test_emergency_stop_allows_exact_fenced_safe_terminal_and_releases_lease",
    "tests.test_automation_service_state.AutomationServiceStateTests.test_interrupted_write_rolls_back_and_leaves_manager_writable",
    "tests.test_automation_service_state.AutomationServiceStateTests.test_lease_takeover_fences_stale_owner",
    "tests.test_automation_service_canonical_authority.CanonicalAutomationAuthorityTests.test_sqlite_is_sole_enable_authority_registry_environment_and_evidence_cannot_enable",
    "tests.test_automation_service_canonical_authority.CanonicalAutomationAuthorityTests.test_service_and_flow_gates_refuse_manual_live_execution_until_both_sqlite_gates_open",
    "tests.test_automation_service_canonical_authority.CanonicalAutomationAuthorityTests.test_emergency_generation_invalidates_active_pre_dispatch_fence",
    "tests.test_automation_service_canonical_authority.CanonicalAutomationAuthorityTests.test_one_active_claim_is_global_and_releases_after_terminal_transition",
    "tests.test_automation_service_canonical_authority.CanonicalAutomationAuthorityTests.test_static_flow_specs_and_registered_descriptors_initialize_disabled",
    "tests.test_automation_service_handlers.AutomationServiceHandlerTests.test_all_registered_selectors_return_non_consuming_plans",
    "tests.test_automation_service_handlers.AutomationServiceHandlerTests.test_disabled_handler_cannot_become_scheduler_eligible",
    "tests.test_resource_effect_authority_store.ResourceAuthorityStoreTests.test_capability_consume_exception_closes_durable_intent_unknown",
    "tests.test_resource_effect_authority_store.ResourceAuthorityStoreTests.test_terminal_reconciliation_multiple_claims_atomic_release",
    "tests.test_resource_effect_authority_store.ResourceAuthorityStoreTests.test_resource_facts_cannot_be_deleted",
    "tests.test_resource_effect_authority_history.ResourceAuthorityHistoryTests.test_reimport_is_idempotent_and_payload_mismatch_is_integrity_error",
    "tests.test_resource_effect_authority_history.ResourceAuthorityHistoryTests.test_later_reset_clears_only_future_scope_and_conflict_reactivates_block",
    "tests.test_pre_dispatch_freshness.FreshnessPolicyCase.test_capture_age_begins_at_successful_capture_completion",
    "tests.test_pre_dispatch_freshness.FreshnessPolicyCase.test_ocr_duration_advances_frame_age",
    "tests.test_pre_dispatch_freshness.FreshnessPolicyCase.test_wall_clock_adjustment_does_not_change_policy_freshness",
    "tests.test_pre_dispatch_freshness.ExecutorHarness.test_slow_ocr_stale_then_fresh_attempt_uses_one_semantic_action",
    "tests.test_pre_dispatch_freshness.ExecutorHarness.test_no_recapture_loop_occurs_after_transport",
    "tests.test_pre_dispatch_freshness.ExecutorHarness.test_changed_target_cost_quantity_overlay_or_source_denies",
    "tests.test_automation_service_boundaries.RuntimeBoundaryTests.test_transport_exception_is_unknown_and_is_not_automatically_retried",
    "tests.test_automation_service_boundaries.RuntimeBoundaryTests.test_source_changes_between_reservation_and_transport_blocks",
    "tests.test_automation_service_boundaries.RuntimeBoundaryTests.test_new_idempotency_key_cannot_redispatch_same_binding",
    "tests.test_automation_service_boundaries.RuntimeBoundaryTests.test_session_release_cas_rejects_retry_claimed_between_projection_and_release",
    "tests.test_automation_service_boundaries.RuntimeBoundaryTests.test_emergency_after_dispatching_before_transport_aborts_and_releases",
    "tests.test_automation_service_boundaries.RuntimeBoundaryTests.test_inflight_emergency_commit_failure_marks_unknown_and_releases",
    "tests.test_automation_service_boundaries.RuntimeBoundaryTests.test_successful_ocr_drains_descendant_before_return",
    "tests.test_automation_service_boundaries.RuntimeBoundaryTests.test_blocking_ocr_times_out_unknown_and_releases_ownership",
    "tests.test_supply_depot_vision.SupplyDepotVisionTests.test_native_exhausted_capture_keeps_identity_across_scene_animation",
    "tests.test_home_atlas_tap_actual_proposal.HomeAtlasActualTapProposalTests.test_actual_planning_and_issuance_evidence_survive_one_real_core_dispatch",
    "tests.test_home_atlas_tap_actual_proposal.HomeAtlasActualTapProposalTests.test_stale_planning_is_not_replaced_by_fresh_issuance",
    "tests.test_home_atlas_tap_actual_proposal.HomeAtlasActualTapProposalTests.test_invalid_planning_source_or_cost_cannot_be_erased_by_valid_issuance",
    "tests.test_home_atlas_tap_actual_proposal.HomeAtlasActualTapProposalTests.test_unknown_actual_postcondition_never_confirms_or_repeats_transport",
    "tests.test_home_atlas_pan_actual_proposal.HomeAtlasActualPanProposalTests.test_native_pan_preserves_actual_proposal_issuance_and_measured_post_capture",
    "tests.test_home_atlas_pan_actual_proposal.HomeAtlasActualPanProposalTests.test_unknown_actual_post_image_rejects_claimed_progress_after_one_swipe",
    "tests.test_home_atlas_verified_route.HomeAtlasVerifiedRouteTests.test_fresh_overlay_rejected_before_pan_capability_or_transport",
    "tests.test_atlas_startup_normalizer.AtlasStartupNormalizerTests.test_positive_overlay_blocks_canonical_startup_and_building_binding",
    "tests.test_atlas_startup_normalizer.AtlasStartupNormalizerTests.test_unknown_overlay_stale_ambiguous_and_nonfinite_block",
    "tests.test_atlas_startup_normalizer.AtlasStartupNormalizerTests.test_repeated_frame_and_maximum_input_exhaustion_block",
    "tests.test_home_context.HomeContextTests",
    "tests.test_contextual_startup_recovery.ContextualStartupRecoveryTests.test_current_scarlett_artwork_variance_uses_fresh_back_and_route_successor",
    "tests.test_contextual_startup_recovery.ContextualStartupRecoveryTests.test_unknown_commercial_and_modal_cannot_be_overridden_by_route_callback",
    "tests.test_contextual_startup_recovery.ContextualStartupRecoveryTests.test_manual_source_context_stops_known_scarlett_without_input",
    "tests.test_contextual_startup_recovery.ContextualStartupRecoveryTests.test_changed_or_lost_back_on_fresh_capture_never_dispatches",
    "tests.test_contextual_startup_recovery.ContextualStartupRecoveryTests.test_unknown_post_is_unresolved_and_new_key_cannot_repeat_scarlett_back",
    "tests.test_contextual_startup_recovery.ContextualStartupRecoveryTests.test_transport_uncertainty_retains_one_attempt_and_unresolved_ledger",
    "tests.test_noahs_tavern_recruit.NoahContractTests.test_native_advanced_fixture_preserves_complete_header_and_title_glyphs",
    "tests.test_bioenhancer_free_control_native",
    "tests.test_service_supply.ServiceSupplyTests.test_failure_after_hold_keeps_reserved_count_and_denies_retry",
    "tests.test_supply_depot_vision.SupplyDepotVisionTests.test_original_native_capture_recognizes_free_controls_with_explicit_identity",
    "tests.test_ultimate_lineup_native.UltimateLineupNativeTests.test_native_variants_bind_same_enabled_challenge",
    "tests.test_personal_might_bluestacks.PersonalMightNativeTests.test_native_rank_1_thumb_requires_exact_header_medal_and_unique_body",
    "tests.test_building_upgrade_disabled.DisabledBuildingUpgradeContractTests.test_disabled_policy_blocks_valid_generic_upgrade",
    "tests.test_building_upgrade_disabled.DisabledBuildingUpgradeContractTests.test_matrix_keeps_generic_building_upgrade_disabled_and_dormant",
    "tests.test_challenge_disabled.DisabledChallengeContractTests.test_disabled_policy_blocks_dispatch_and_keeps_claim_separate",
    "tests.test_challenge_disabled.DisabledChallengeContractTests.test_matrix_keeps_ruins_challenge_disabled_and_dormant",
    "tests.test_donation_disabled.DisabledDonationContractTests.test_disabled_policy_blocks_dispatch_and_keeps_claim_separate",
    "tests.test_donation_disabled.DisabledDonationContractTests.test_matrix_keeps_donation_disabled_and_dormant",
    "tests.test_resource_boost_disabled.DisabledResourceBoostContractTests.test_disabled_policy_blocks_dispatch_and_keeps_claim_separate",
    "tests.test_resource_boost_disabled.DisabledResourceBoostContractTests.test_matrix_keeps_resource_boost_disabled_and_dormant",
    "tests.test_training_disabled.DisabledTrainingContractTests.test_disabled_policy_blocks_valid_queue_observation",
    "tests.test_training_disabled.DisabledTrainingContractTests.test_matrix_keeps_all_training_rows_disabled_and_dormant",
    "tests.test_hero_duel_disabled.DisabledHeroDuelContractTests.test_disabled_policy_blocks_dispatch_and_keeps_claim_separate",
    "tests.test_hero_duel_disabled.DisabledHeroDuelContractTests.test_matrix_keeps_duel_disabled_and_dormant",
    "tests.test_purchases_disabled.DisabledPurchaseContractTests.test_disabled_policy_blocks_dispatch_and_keeps_claim_separate",
    "tests.test_purchases_disabled.DisabledPurchaseContractTests.test_matrix_keeps_all_purchase_variants_disabled_and_dormant",
    "tests.test_stamina_disabled.DisabledStaminaContractTests.test_disabled_policy_blocks_every_positive_dispatch_request",
    "tests.test_stamina_disabled.DisabledStaminaContractTests.test_matrix_keeps_stamina_unregistered_and_scheduler_dormant",
    "tests.test_hero_upgrade_disabled.DisabledHeroUpgradeContractTests.test_disabled_policy_blocks_dispatch_and_keeps_claim_separate",
    "tests.test_hero_upgrade_disabled.DisabledHeroUpgradeContractTests.test_matrix_keeps_hero_upgrade_disabled_and_dormant",
    "tests.test_speedup_disabled.DisabledSpeedupContractTests.test_disabled_policy_blocks_dispatch_and_keeps_claim_separate",
    "tests.test_speedup_disabled.DisabledSpeedupContractTests.test_matrix_keeps_speedup_disabled_and_dormant",
    "tests.test_tech_upgrade_disabled.DisabledTechUpgradeContractTests.test_disabled_policy_blocks_dispatch_and_keeps_claim_separate",
    "tests.test_tech_upgrade_disabled.DisabledTechUpgradeContractTests.test_matrix_keeps_tech_disabled_and_dormant",
)

WINDOWS_BASELINE += tuple(ROUTE_BOUNDARIES.values()) + HOME_ADMISSION_BASELINE

LINUX_BASELINE = (
    "tests.test_test_discovery",
    "tests.test_test_environment",
    "tests.test_ocr_memo",
    "tests.test_offline_selection",
    "tests.test_check_entrypoint",
    "tests.test_static_checks",
    "tests.test_path_safety",
    "tests.test_architecture_imports",
    "tests.test_architecture_source_boundaries",
    "tests.test_bounded_ocr_architecture",
    "tests.test_host_identifier_guard",
    "tests.test_automation_service_boundaries.RuntimeBoundaryTests.test_successful_ocr_drains_descendant_before_return",
    "tests.test_automation_service_boundaries.RuntimeBoundaryTests.test_blocking_ocr_times_out_unknown_and_releases_ownership",
    "tests.test_supply_depot_vision.SupplyDepotVisionTests.test_native_exhausted_capture_keeps_identity_across_scene_animation",
    "tests.test_contextual_startup_recovery.ContextualStartupRecoveryTests.test_unknown_commercial_and_modal_cannot_be_overridden_by_route_callback",
    "tests.test_semantic_ocr_crop.SemanticOcrCropTests.test_original_png_encoding_and_pixels_are_bound_without_relabeling_identity",
    "tests.test_semantic_ocr_crop.SemanticOcrCropTests.test_original_payload_rejects_wrong_bytes_pixels_geometry_and_format",
    "tests.test_semantic_ocr_crop.SemanticOcrCropTests.test_exclusion_masks_block_roi_and_padding_escape",
    "tests.test_semantic_ocr_crop.SemanticOcrCropTests.test_forged_and_cross_capture_identities_rejected",
    "tests.test_semantic_ocr_crop.SemanticOcrCropTests.test_invalid_unknown_fail_closed_and_no_dispatch_authority",
    "tests.test_automation_service_state.AutomationServiceStateTests.test_busy_write_is_bounded_and_typed",
    "tests.test_automation_service_state.AutomationServiceStateTests.test_twenty_managers_yield_one_active_claim",
    "tests.test_automation_service_state.AutomationServiceStateTests.test_interrupted_write_rolls_back_and_leaves_manager_writable",
) + HOME_ADMISSION_BASELINE


@dataclass(frozen=True)
class Selection:
    profile: str
    intended_ids: tuple[str, ...]
    omitted_ids: tuple[str, ...]
    reasons: tuple[str, ...]


# Shared changes use owning modules plus the baseline route-consumer matrix. Walking
# imports for these surfaces would expand almost every historical native fixture.
CORE_OWNERS = (
    "safe_action_core", "input_capability_firewall", "resource_effect_authority",
    "pre_dispatch_freshness", "scheduler_invocation_state", "automation_service_",
    "runtime_identity", "runtime_profile_unification", "recovered_executor_accounting",
    "authorized_daily_repeat", "legacy_reconciliation", "task_module",
    "service_route_contract", "service_cooldown_reset_edge", "gameplay_flow_contracts",
)
HOME_OWNERS = (
    "home_", "atlas_", "navigation_", "contextual_startup_recovery", "home_context",
    "perception_bundle", "radial_semantics", "list_search", "transition_stability",
    "startup_recovery", "bluestacks_home_safe_exit", "research_lab_home_entry_binding",
    "bioenhancer_home_entry_binding", "campaign_home_", "supply_camera_reframe",
)
# These are lazy imports inside is_clean_home_frame(), not merely Nova route
# dependencies. Preserve the ordinary Nova family/import selection as well.
HOME_AUTHORITY_DEPENDENCIES = frozenset({
    "tasks/nova_praise.py", "tasks/nova_praise_vision.py",
})
OCR_OWNERS = (
    "bounded_ocr_architecture", "semantic_ocr_crop", "test_environment", "ocr_memo",
    "enhancement_ocr_deadline", "enhancement_material_label_crop", "enhancement_home_ocr_duplicates",
)
POPUP_OWNERS = (
    "startup_recovery", "contextual_startup_recovery", "vip_points_popup",
    "scarlett_current_context", "atlas_startup_normalizer", "atlas_runtime_startup",
    "atlas_flow_startup", "service_application_startup",
)
RUNTIME_OWNERS = (
    "bluestacks_native_runtime", "native_capture_retry", "development_",
    "navigation_development_boundary", "navigation_session", "runtime_", "pnsctl_",
    "catalog_and_pnsctl", "delegated_runtime_receipts", "host_identifier_guard",
    "automation_service_", "route_metadata_consistency", "flow_id_rename_migration",
)
METADATA_OWNERS = (
    "gameplay_flow_contracts", "product_authority", "route_metadata_consistency",
    "flow_id_rename_migration", "task_module", "catalog_and_pnsctl", "daily_quest_",
)
GATE_OWNERS = ("offline_selection", "test_discovery", "check_entrypoint", "static_checks")
POPUP_REPRESENTATIVES = (
    "tests.test_service_enhancement.ServiceEnhancementTests."
    "test_native_vip_scarlett_stack_reaches_home_with_two_unique_navigation_inputs",
    "tests.test_nova_startup_recovery.NovaStartupRecoveryTests."
    "test_vip_then_scarlett_retains_two_navigation_steps_and_zero_praise",
)
FAMILIES = {
    "campaign": ("campaign",),
    "enhancement": ("enhancement", "enhance_"),
    "nanoweapon": ("nanoweapon",),
    "bioenhancer": ("bioenhancer",),
    "supply": ("supply",),
    "recruitment": ("recruitment", "recruit", "noah"),
    "nova": ("nova",),
    "personal_might": ("personal_might",),
    "resources": ("daily_resource", "resources", "resource_item", "resource_boost"),
    "daily_row_claim": ("daily_row_claim", "available_daily_claim"),
    "ultimate": ("ultimate",),
    "ruins": ("ruins",),
    "troop": ("troop", "training"),
    "world": ("world", "stamina", "zombie_lair"),
    "gathering": ("gathering",),
}


def _expand(selectors: Sequence[str], ids: Sequence[str]) -> set[str]:
    selected: set[str] = set()
    for selector in selectors:
        matches = {name for name in ids if name == selector or name.startswith(selector + ".")}
        if not matches:
            raise ValueError(f"Selection selector has no discovered tests: {selector}")
        selected.update(matches)
    return selected


def _normalize_path(value: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError("Changed paths must be nonempty Git-relative paths")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (path.is_absolute() or PureWindowsPath(value).drive or ".." in path.parts
            or "\x00" in value or normalized in (".", "") or ":" in normalized):
        raise ValueError(f"Unsafe changed path: {value!r}")
    return path.as_posix()


def _module(path: str) -> str:
    parts = PurePosixPath(path).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _family(value: str) -> set[str]:
    value = value.lower().replace("-", "_")
    return {
        name for name, tokens in FAMILIES.items()
        if any(token in value for token in tokens)
        and not (name == "enhancement" and "bioenhancer" in value)
    }


def _imports(path: Path, module: str, *, test: bool) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    package = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
    imports: set[str] = set()

    def visit(node: ast.AST) -> None:
        if not test and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level > len(package):
                    raise ValueError(f"Unresolvable relative import in {path}")
                base = package[:len(package) - node.level + 1]
                target = ".".join([*base, *([node.module] if node.module else [])])
            else:
                target = node.module or ""
            imports.add(target)
            imports.update(f"{target}.{alias.name}" for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.Call) and node.args:
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if name in ("__import__", "import_module") and isinstance(node.args[0], ast.Constant):
                target = node.args[0].value
                if isinstance(target, str) and not target.startswith("."):
                    imports.add(target)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return imports


def _dependent_tests(root: Path, changed: set[str], modules: set[str]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for directory in ("scripts", "tasks", "automation_service", "safe_action_core", "tests"):
        for path in sorted((root / directory).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            name = _module(relative)
            graph[name] = _imports(path, name, test=directory == "tests")
    result: dict[str, set[str]] = {}
    for source in changed:
        impacted = {source}
        while True:
            additions = {name for name, imports in graph.items() if imports & impacted} - impacted
            if not additions:
                result[source] = modules & impacted
                break
            impacted.update(additions)
    return result


def _owners(modules: set[str], prefixes: Sequence[str]) -> set[str]:
    return {module for module in modules if module.removeprefix("tests.test_").startswith(tuple(prefixes))}


def _dispatch_owners(modules: set[str]) -> set[str]:
    return {module for module in modules if module.startswith("tests.test_service_") and module.endswith("_dispatch")}


def _shared(path: str) -> str | None:
    stem = PurePosixPath(path).stem
    if path.startswith("tests/fixtures/resource_effect_authority/"):
        return "core"
    if path.startswith(("tests/fixtures/runtime_control_sequences/", "tests/fixtures/runtime_trace_projection/")):
        return "runtime"
    if (path.startswith(("docker/", ".omp/")) or stem.startswith(("Start-PnS", "Stop-PnS"))):
        return "runtime"
    if not path.endswith(".py") or not path.startswith(("scripts/", "tasks/", "safe_action_core/", "automation_service/")):
        return None
    if path.startswith("safe_action_core/") or path in {
        f"automation_service/{name}.py" for name in (
            "state", "service", "session", "scheduler", "contracts", "adapters", "actions",
            "registry", "handlers", "operations", "temporal", "context", "screens", "overlays",
        )
    } or path in {"tasks/contracts.py", "tasks/scheduler_task_result.py", "tasks/runtime_identity.py"}:
        return "core"
    if stem in {"bluestacks_popup_recognition", "startup_recovery", "startup_surface_recognition"}:
        return "popup"
    if stem in {"bounded_tesseract", "semantic_ocr_crop"}:
        return "ocr"
    if (stem in {"pnsctl", "bluestacks_native_runtime", "bluestacks_adb_readiness", "bluestacks_passive",
                 "navigation_development_boundary", "runtime_trace_projection", "delegated_runtime_receipts"}
            or path == "automation_service/cli.py"):
        return "runtime"
    if (stem.startswith(("home_", "atlas_", "startup_normalization", "navigation_"))
            or stem in {"perception_bundle", "radial_semantics", "list_search", "transition_stability", "bluestacks_home_safe_exit"}):
        return "home"
    return None


def build_selection(
    discovered_ids: Sequence[str], changed_paths: Sequence[str] | None,
    platform_name: str, root: Path,
) -> Selection:
    """Select current test IDs; omissions are intentional scope, never test skips.

    ``None`` means the caller could not obtain reliable change information. Missing
    baseline selectors and duplicate discovery IDs are inventory errors, not scope.
    """
    ids = tuple(discovered_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate discovered test IDs")
    if not ids or any(not isinstance(name, str) or len(name.split(".")) < 4 for name in ids):
        raise ValueError("Discovery must contain fully qualified test IDs")
    baseline = WINDOWS_BASELINE if platform_name.lower() == "windows" else LINUX_BASELINE
    selected = _expand(baseline, ids)
    reasons = [f"{platform_name.lower()} baseline safety and route-consumer matrix"]

    def full(reason: str) -> Selection:
        return Selection("full-fallback", ids, (), tuple([*reasons, reason]))

    if platform_name.lower() not in {"windows", "linux"}:
        return full(f"Unsupported platform: {platform_name}")
    if changed_paths is None:
        return full("Reliable changed paths unavailable")
    if isinstance(changed_paths, (str, bytes)):
        raise ValueError("Changed paths must be a sequence of paths, not a string")
    paths = tuple(dict.fromkeys(_normalize_path(path) for path in changed_paths))
    modules = {".".join(name.split(".")[:-2]) for name in ids}
    selected_modules: set[str] = set()
    production: set[str] = set()
    for path in paths:
        pure = PurePosixPath(path)
        if path.startswith("calibration/"):
            reasons.append(f"{path}: retired calibration research has no runtime caller coverage")
            continue
        if path.startswith("tests/support/") or path in {"tests/ocr_memo.py", "tests/__init__.py"}:
            return full(f"{path}: shared test semantics changed")
        if path == "tasks/profile.py":
            return full(f"{path}: global runtime profile and geometry changed")
        if pure.name == "__init__.py" or pure.name.startswith("requirements") or path in {
            "pyproject.toml", "uv.lock", "poetry.lock", ".python-version", "Pipfile", "Pipfile.lock",
        }:
            return full(f"{path}: package, dependency or interpreter boundary changed")
        if path.startswith("tests/") and pure.name.startswith("test_") and pure.suffix == ".py":
            selected_modules.add(_module(path))
            reasons.append(f"{path}: changed test module (deleted undiscovered modules add no IDs)")
            continue
        if path.startswith("docs/") or pure.suffix.lower() in {".md", ".rst"} or path in {
            ".gitattributes", ".gitignore", ".editorconfig", "LICENSE", "LICENSE.txt",
        }:
            reasons.append(f"{path}: documentation or repository presentation; baseline applies")
            continue
        if path.startswith(".github/") or path in {
            "scripts/check.py", "scripts/check_static.py", "scripts/check_test_discovery.py",
            "scripts/offline_suite.py", "scripts/offline_selection.py",
        }:
            selected_modules.update(_owners(modules, GATE_OWNERS))
            reasons.append(f"{path}: offline policy and check owners")
            continue
        if path.startswith("tests/fixtures/nova_praise_preflight/"):
            return full(f"{path}: mixed-route fixture has no bounded owner mapping")
        if path in HOME_AUTHORITY_DEPENDENCIES or path.startswith("tasks/assets/nova_praise/"):
            selected_modules.update(_owners(modules, HOME_OWNERS))
            reasons.append(f"{path}: lazy clean-Home authority requires Home/Atlas owners")
        shared = _shared(path)
        if shared is not None:
            owners = {"core": CORE_OWNERS, "home": HOME_OWNERS, "ocr": OCR_OWNERS,
                      "popup": POPUP_OWNERS, "runtime": RUNTIME_OWNERS}[shared]
            selected_modules.update(_owners(modules, owners))
            if shared in {"ocr", "popup"}:
                selected_modules.update(_owners(modules, HOME_OWNERS))
            if shared == "ocr":
                selected_modules.update(_owners(modules, POPUP_OWNERS))
                selected_modules.update(module for module in modules if "nova" in _family(module))
                selected.update(_expand(POPUP_REPRESENTATIVES, ids))
            if shared == "core":
                selected_modules.update(_owners(modules, OCR_OWNERS))
            if shared in {"core", "runtime"}:
                selected_modules.update(_dispatch_owners(modules))
                selected_modules.update(_owners(modules, ("service_route_contract",)))
            if shared == "popup":
                selected.update(_expand(POPUP_REPRESENTATIVES, ids))
            reasons.append(f"{path}: shared {shared} owners and baseline route consumers")
            continue
        if path.startswith(("tasks/gameplay_flow_contracts/",)) or (
            path.startswith("tasks/") and pure.suffix == ".json" and pure.name.startswith(("flow_delivery_", "daily_quest_"))
        ):
            selected_modules.update(_owners(modules, METADATA_OWNERS))
            families = _family(path)
            selected_modules.update(module for module in modules if _family(module) & families)
            reasons.append(f"{path}: contract/product/route metadata owners and route family")
            continue
        families = _family(path)
        if path.startswith(("tests/fixtures/", "tasks/assets/")):
            # Shared Home/startup fixture directory names are not Python stems.
            if any(part in {"home_base", "home_nav", "home_atlas", "startup", "navigation", "research_lab_home_entry"} for part in pure.parts):
                selected_modules.update(_owners(modules, HOME_OWNERS))
                if "startup" in pure.parts or "navigation" in pure.parts:
                    selected_modules.update(_owners(modules, POPUP_OWNERS))
                    selected.update(_expand(POPUP_REPRESENTATIVES, ids))
                reasons.append(f"{path}: shared Home/startup fixture owners and baseline consumers")
                continue
            if not families:
                return full(f"{path}: unknown fixture or asset owner")
        elif pure.suffix == ".py" and path.startswith(("tasks/", "scripts/", "automation_service/")):
            production.add(_module(path))
        else:
            return full(f"{path}: unknown production, data or configuration impact")
        selected_modules.update(module for module in modules if _family(module) & families)
        if families:
            reasons.append(f"{path}: route families {', '.join(sorted(families))}")
    if production:
        try:
            dependents = _dependent_tests(root, production, modules)
        except (OSError, SyntaxError, UnicodeError, ValueError) as error:
            return full(f"Import impact unavailable: {type(error).__name__}: {error}")
        for changed in sorted(production):
            if not _family(changed) and not dependents[changed]:
                return full(f"{changed}: production module has no known test owner")
            selected_modules.update(dependents[changed])
        reasons.append("Production top-level/conditional imports and all test imports select transitive consumers")
    selected.update(name for name in ids if ".".join(name.split(".")[:-2]) in selected_modules)
    intended = tuple(name for name in ids if name in selected)
    omitted = tuple(name for name in ids if name not in selected)
    return Selection("risk-based", intended, omitted, tuple(reasons))
