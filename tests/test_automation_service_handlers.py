from __future__ import annotations

import unittest

from automation_service.contracts import (
    FlowDescriptor,
    NormalizedOutcome,
    RecurrenceClass,
    RecurrenceProjection,
    PerceptionEnvelope,
    SchedulerFacts,
)
from automation_service.handlers import (
    CampaignApSelectionHandler,
    DisabledHandler,
    NovaPraiseSelectionHandler,
    RecruitmentMaintenanceSelectionHandler,
    WorldNavigationSelectionHandler,
)
from automation_service.registry import (
    CAMPAIGN_FLOW_ID,
    CAMPAIGN_HANDLER_ID,
    CAMPAIGN_PHASE_MODE,
    CAMPAIGN_PRODUCT_ID,
    CAMPAIGN_PRODUCT_REVISION,
    CAMPAIGN_PROFILE_ID,
    NOVA_FLOW_ID,
    NOVA_HANDLER_ID,
    NOVA_PHASE_MODE,
    NOVA_PRODUCT_ID,
    NOVA_PRODUCT_REVISION,
    NOVA_PROFILE_ID,
    RECRUITMENT_FLOW_ID,
    RECRUITMENT_HANDLER_ID,
    RECRUITMENT_PHASE_MODE,
    RECRUITMENT_PRODUCT_ID,
    RECRUITMENT_PRODUCT_REVISION,
    RECRUITMENT_PROFILE_ID,
    RegisteredDispatchSnapshot,
    WORLD_FLOW_ID,
    WORLD_HANDLER_ID,
    WORLD_PHASE_MODE,
    WORLD_PRODUCT_ID,
    WORLD_PRODUCT_REVISION,
    WORLD_PROFILE_ID,
)


class AutomationServiceHandlerTests(unittest.TestCase):
    @staticmethod
    def _snapshot(
        flow_id: str,
        product_id: str,
        product_revision: str,
        handler_id: str,
        profile_id: str,
        phase_mode: str,
    ) -> RegisteredDispatchSnapshot:
        return RegisteredDispatchSnapshot(
            flow_id,
            product_id,
            product_revision,
            handler_id,
            profile_id,
            phase_mode,
            "REGISTERED",
            True,
        )

    def _nova_snapshot(self) -> RegisteredDispatchSnapshot:
        return self._snapshot(
            NOVA_FLOW_ID,
            NOVA_PRODUCT_ID,
            NOVA_PRODUCT_REVISION,
            NOVA_HANDLER_ID,
            NOVA_PROFILE_ID,
            NOVA_PHASE_MODE,
        )

    def _recruitment_snapshot(self) -> RegisteredDispatchSnapshot:
        return self._snapshot(
            RECRUITMENT_FLOW_ID,
            RECRUITMENT_PRODUCT_ID,
            RECRUITMENT_PRODUCT_REVISION,
            RECRUITMENT_HANDLER_ID,
            RECRUITMENT_PROFILE_ID,
            RECRUITMENT_PHASE_MODE,
        )

    def _campaign_snapshot(self) -> RegisteredDispatchSnapshot:
        return self._snapshot(
            CAMPAIGN_FLOW_ID,
            CAMPAIGN_PRODUCT_ID,
            CAMPAIGN_PRODUCT_REVISION,
            CAMPAIGN_HANDLER_ID,
            CAMPAIGN_PROFILE_ID,
            CAMPAIGN_PHASE_MODE,
        )

    def _nova_facts(self, **overrides) -> SchedulerFacts:
        values = {
            "health_ok": True,
            "accepted_product": NOVA_PRODUCT_ID,
            "product_revision": NOVA_PRODUCT_REVISION,
            "registration_status": "REGISTERED",
            "scheduler_eligible": True,
            "owner_available": True,
            "clock_ok": True,
            "reset_agreement": True,
        }
        values.update(overrides)
        return SchedulerFacts("account", "server", "reset", 100.0, **values)

    def _recruitment_facts(self, **overrides) -> SchedulerFacts:
        values = {
            "health_ok": True,
            "accepted_product": RECRUITMENT_PRODUCT_ID,
            "product_revision": RECRUITMENT_PRODUCT_REVISION,
            "registration_status": "REGISTERED",
            "scheduler_eligible": True,
            "owner_available": True,
            "clock_ok": True,
            "reset_agreement": True,
            "projections": {
                RECRUITMENT_FLOW_ID: RecurrenceProjection(
                    RecurrenceClass.COOLDOWN,
                    next_eligible_at=90.0,
                    observed_at_utc=95.0,
                )
            },
        }
        values.update(overrides)
        return SchedulerFacts("account", "server", "reset", 100.0, **values)

    def _campaign_facts(self, **overrides) -> SchedulerFacts:
        values = {
            "health_ok": True,
            "accepted_product": CAMPAIGN_PRODUCT_ID,
            "product_revision": CAMPAIGN_PRODUCT_REVISION,
            "registration_status": "REGISTERED",
            "scheduler_eligible": True,
            "owner_available": True,
            "clock_ok": True,
            "reset_agreement": True,
            "projections": {
                CAMPAIGN_FLOW_ID: RecurrenceProjection(
                    RecurrenceClass.AP_REGENERATION,
                    next_eligible_at=90.0,
                    observed_at_utc=95.0,
                    observed_balance=14.0,
                )
            },
        }
        values.update(overrides)
        return SchedulerFacts("account", "server", "reset", 100.0, **values)

    def test_handler_protocol_surface_is_semantic_and_capability_specific(self) -> None:
        descriptor = FlowDescriptor("flow", "owner", "family", "variant", "daily_once")
        handler = DisabledHandler(descriptor)
        self.assertEqual(handler.describe(), descriptor)
        self.assertFalse(handler.eligibility(SchedulerFacts("a", "s", "r", 1.0)))
        self.assertEqual(handler.plan(SchedulerFacts("a", "s", "r", 1.0)), None)
        self.assertEqual(handler.reconcile(None).outcome, NormalizedOutcome.BLOCKED)
        self.assertEqual(handler.recover("UNKNOWN").outcome, NormalizedOutcome.BLOCKED)
        self.assertEqual(handler.summarize()["mode"], "disabled")

    def test_disabled_handler_cannot_become_scheduler_eligible(self) -> None:
        descriptor = FlowDescriptor(
            "flow",
            "owner",
            "family",
            "variant",
            "daily_once",
            scheduler_eligible=False,
        )
        handler = DisabledHandler(descriptor)
        self.assertFalse(handler.describe().scheduler_eligible)
        self.assertFalse(handler.eligibility(SchedulerFacts("a", "s", "r", 1.0)))

    def test_nova_handler_is_zero_transport_and_requires_parent_canary(self) -> None:
        handler = NovaPraiseSelectionHandler(self._nova_snapshot())
        descriptor = handler.describe()
        self.assertEqual(descriptor.flow_id, NOVA_FLOW_ID)
        self.assertEqual(descriptor.cadence, "daily_once_per_reset")
        self.assertEqual(descriptor.accepted_product, NOVA_PRODUCT_ID)
        self.assertEqual(descriptor.product_revision, NOVA_PRODUCT_REVISION)
        self.assertEqual(descriptor.registration_status, "REGISTERED")
        result = handler.plan(self._nova_facts())
        self.assertEqual(result.outcome, NormalizedOutcome.COMPLETE_FOR_RESET)
        self.assertEqual(result.reason_code, "NOVA_PRAISE_PARENT_CANARY_REQUIRED")
        self.assertEqual(result.action_count, 0)
        self.assertEqual(result.observed_progress["transport_count"], 0)
        self.assertEqual(
            result.observed_progress["registration_snapshot"],
            handler.snapshot.to_mapping(),
        )

    def test_nova_handler_fail_closes_product_owner_clock_reset_and_profile_mismatches(
        self,
    ) -> None:
        handler = NovaPraiseSelectionHandler(self._nova_snapshot())
        mismatches = (
            {"accepted_product": "world_map_navigation"},
            {"product_revision": "wrong-revision"},
            {"owner_available": False},
            {"clock_ok": False},
            {"clock_rollback": True},
            {"reset_agreement": False},
        )
        for overrides in mismatches:
            with self.subTest(overrides=overrides):
                self.assertFalse(handler.eligibility(self._nova_facts(**overrides)))
                self.assertEqual(
                    handler.plan(self._nova_facts(**overrides)).outcome,
                    NormalizedOutcome.BLOCKED,
                )
        perception = PerceptionEnvelope(
            "capture",
            "home",
            "wrong-profile",
            "fresh",
        )
        self.assertFalse(handler.eligibility(self._nova_facts(), perception))

    def test_nova_handler_rejects_non_nova_snapshot(self) -> None:
        with self.assertRaises(ValueError):
            RegisteredDispatchSnapshot(
                NOVA_FLOW_ID,
                NOVA_PRODUCT_ID,
                NOVA_PRODUCT_REVISION,
                "wrong-handler",
                NOVA_PROFILE_ID,
                NOVA_PHASE_MODE,
                "REGISTERED",
                True,
            )
        with self.assertRaises(TypeError):
            NovaPraiseSelectionHandler(object())

    def test_recruitment_handler_requires_fresh_due_cooldown_projection(self) -> None:
        handler = RecruitmentMaintenanceSelectionHandler(self._recruitment_snapshot())
        descriptor = handler.describe()
        self.assertEqual(descriptor.flow_id, RECRUITMENT_FLOW_ID)
        self.assertEqual(descriptor.cadence, "cooldown_pulse")
        self.assertFalse(descriptor.reset_scoped)
        result = handler.plan(self._recruitment_facts())
        self.assertEqual(result.outcome, NormalizedOutcome.COMPLETE_FOR_RESET)
        self.assertEqual(
            result.reason_code,
            "RECRUITMENT_MAINTENANCE_PARENT_CANARY_REQUIRED",
        )
        self.assertEqual(result.action_count, 0)
        self.assertEqual(result.observed_progress["transport_count"], 0)

        ineligible = (
            {},
            {
                RECRUITMENT_FLOW_ID: RecurrenceProjection(
                    RecurrenceClass.COOLDOWN,
                    next_eligible_at=101.0,
                    observed_at_utc=95.0,
                )
            },
            {
                RECRUITMENT_FLOW_ID: RecurrenceProjection(
                    RecurrenceClass.TIMER,
                    next_eligible_at=90.0,
                    observed_at_utc=95.0,
                )
            },
        )
        for projections in ineligible:
            with self.subTest(projections=projections):
                self.assertFalse(
                    handler.eligibility(
                        self._recruitment_facts(projections=projections)
                    )
                )

        wrong_profile = PerceptionEnvelope("capture", "home", "wrong-profile", "fresh")
        self.assertFalse(handler.eligibility(self._recruitment_facts(), wrong_profile))
        self.assertEqual(handler.snapshot.profile, RECRUITMENT_PROFILE_ID)

    def test_campaign_handler_requires_fresh_funded_ap_projection(self) -> None:
        handler = CampaignApSelectionHandler(self._campaign_snapshot())
        descriptor = handler.describe()
        self.assertEqual(descriptor.flow_id, CAMPAIGN_FLOW_ID)
        self.assertEqual(
            descriptor.recurrence.recurrence_class,
            RecurrenceClass.AP_REGENERATION,
        )
        self.assertFalse(descriptor.reset_scoped)
        result = handler.plan(self._campaign_facts())
        self.assertEqual(result.outcome, NormalizedOutcome.COMPLETE_FOR_RESET)
        self.assertEqual(result.reason_code, "CAMPAIGN_AP_PARENT_CANARY_REQUIRED")
        self.assertEqual(result.action_count, 0)
        self.assertEqual(result.observed_progress["projection_observed_balance"], 14.0)

        ineligible = (
            {},
            {
                CAMPAIGN_FLOW_ID: RecurrenceProjection(
                    RecurrenceClass.AP_REGENERATION,
                    next_eligible_at=90.0,
                    observed_at_utc=95.0,
                    observed_balance=13.0,
                )
            },
            {
                CAMPAIGN_FLOW_ID: RecurrenceProjection(
                    RecurrenceClass.STAMINA_REGENERATION,
                    next_eligible_at=90.0,
                    observed_at_utc=95.0,
                    observed_balance=14.0,
                )
            },
        )
        for projections in ineligible:
            with self.subTest(projections=projections):
                self.assertFalse(
                    handler.eligibility(self._campaign_facts(projections=projections))
                )

        wrong_profile = PerceptionEnvelope("capture", "home", "wrong-profile", "fresh")
        self.assertFalse(handler.eligibility(self._campaign_facts(), wrong_profile))
        self.assertEqual(handler.snapshot.profile, CAMPAIGN_PROFILE_ID)

    def test_selection_handlers_require_exact_explicit_snapshots(self) -> None:
        handlers = (
            WorldNavigationSelectionHandler,
            NovaPraiseSelectionHandler,
            RecruitmentMaintenanceSelectionHandler,
            CampaignApSelectionHandler,
        )
        for handler_type in handlers:
            with self.subTest(handler=handler_type.__name__):
                with self.assertRaises(TypeError):
                    handler_type()

        nova_snapshot = self._nova_snapshot()
        with self.assertRaises(ValueError):
            WorldNavigationSelectionHandler(nova_snapshot)
        with self.assertRaises(ValueError):
            RecruitmentMaintenanceSelectionHandler(nova_snapshot)
        with self.assertRaises(ValueError):
            CampaignApSelectionHandler(nova_snapshot)


if __name__ == "__main__":
    unittest.main()
