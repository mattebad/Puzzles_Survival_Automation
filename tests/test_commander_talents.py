from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import hashlib
import json
import tempfile
import time
from types import SimpleNamespace
import unittest

import numpy as np

from automation_service.commander_talents import (
    CommanderTalentSwitchApproval, commander_talent_switch_approval,
    ensure_commander_talent_preset, invalidate_commander_talent_preset,
)
from safe_action_core import SafetyStore
from automation_service.registry import TROOP_TRAINING_FLOW_ID
from safe_action_core.models import ActionClass, ActionIntent, PolicyDecision, PolicyResult
from safe_action_core.approved_base_routes import HALL_OF_WAR_TASK
from tasks.commander_talents import (
    APPLY_CONFIRMATION_DIALOG, PRESET_NAMES, PresetRowState, TalentMemoryObservation, TalentPresetNativeResult,
    TalentSwitchPermit, context_fingerprint, observe_preset, recognize_talent_memory,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID


@dataclass(frozen=True)
class Hit:
    text: str
    bounds: tuple[int, int, int, int]
    confidence: float = 95.0


def memory_hits(*, applied="Military"):
    result = [Hit("Talent Memory", (270, 40, 515, 80))]
    for name, y in (("Economy", 150), ("Military", 250), ("Training", 350)):
        result.extend((Hit(name, (58, y, 190, y + 32)),
                       Hit("Applied" if name == applied else "Apply", (518, y, 674, y + 34))))
    return tuple(result)


class CommanderTalentSemanticsTests(unittest.TestCase):
    def test_three_saved_presets_bind_apply_or_applied_without_a_quote(self):
        self.assertEqual(set(PRESET_NAMES), {"Military", "Economy", "Training"})
        for applied in PRESET_NAMES:
            recognition = recognize_talent_memory(memory_hits(applied=applied))
            self.assertTrue(recognition.recognized)
            self.assertEqual(recognition.applied_preset, applied)
            for name in PRESET_NAMES:
                facts = observe_preset(recognition, name, source_frame_sha256="a" * 64, evidence_ref="frame:memory")
                self.assertTrue(facts.recognized)
                self.assertEqual(facts.row_state, PresetRowState.APPLIED if name == applied else PresetRowState.APPLY)
                self.assertEqual(facts.apply_target is None, name == applied)

    def test_ambiguous_missing_or_contradictory_rows_fail_closed(self):
        hits = list(memory_hits())
        hits[-1] = Hit("Applied", hits[-1].bounds)
        self.assertFalse(recognize_talent_memory(hits).recognized)
        self.assertFalse(recognize_talent_memory(memory_hits()[:-1]).recognized)
        self.assertFalse(recognize_talent_memory((*memory_hits(), memory_hits()[1])).recognized)

    def test_context_fingerprint_is_order_independent_and_context_specific(self):
        first = context_fingerprint({"facility": "Hall of War", "preset": "Military"})
        self.assertEqual(first, context_fingerprint({"preset": "Military", "facility": "Hall of War"}))
        self.assertNotEqual(first, context_fingerprint({"facility": "Troop Camp", "preset": "Training"}))


class CanonicalTalentLock:
    owner = "automation-service:test"
    invocation_id = "native-generation-1"

    def assert_held(self, owner, invocation_id):
        if (owner, invocation_id) != (self.owner, self.invocation_id):
            raise RuntimeError("owner lost")


class CanonicalTalentSession:
    def __init__(self):
        self.is_active = True
        self.owner = "automation-service:test"
        self.invocation_id = "native-generation-1"
        self.runtime_input_lock = CanonicalTalentLock()
        self.control_memory = {}
        self.runtime = object()


class CanonicalTalentStore:
    def __init__(self):
        self.actions = {}

    def has_action_block(self):
        return any(row["status"] in {"prepared", "input_sent", "unresolved"} for row in self.actions.values())

    def lease_valid_for(self, owner, now):
        return owner == "automation-service:test" and now > 0

    def get_action_by_key(self, key):
        return self.actions.get(key)

    def prepare_action(self, intent, policy, now):
        if intent.action_key in self.actions:
            raise ValueError("duplicate action")
        self.actions[intent.action_key] = {"action_id": intent.action_id, "status": "prepared"}

    def _row(self, action_id):
        return next(row for row in self.actions.values() if row["action_id"] == action_id)

    def mark_input_sent(self, action_id, now, result):
        self._row(action_id)["status"] = "input_sent"

    def mark_confirmed(self, action_id, now, evidence):
        self._row(action_id)["status"] = "confirmed"

    def mark_unresolved(self, action_id, now, reason, evidence=None):
        self._row(action_id)["status"] = "unresolved"


def _switch_facts():
    return TalentMemoryObservation(True, "Economy", PresetRowState.APPLY, "Military", (518, 150, 674, 184),
                                   "d" * 64, "frame:memory", "PRESET_AVAILABLE_TO_APPLY")


def _approved_switch(facts, generation, context_sha256):
    name = facts.preset_name
    key = f"commander-talent-switch:{name.casefold()}:{generation}"
    post = f"talent-memory-applied:{name}"
    preconditions = (
        f"saved-preset-name:{name}", f"currently-Apply:{name}",
        f"previous-applied-preset:{facts.applied_preset}", "applicable-scenario-switch-authority",
        f"source-generation:{generation}", f"context-sha256:{context_sha256}",
    )
    intent = ActionIntent(
        action_id="commander-talent-switch:" + hashlib.sha256(json.dumps(
            [key, list(preconditions), []], ensure_ascii=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest(), action_key=key, task_id="test_route",
        semantic_action=f"switch_commander_talent_preset:{name.casefold()}", source_state="TALENT_MEMORY",
        target_identity=f"talent-memory-row:{name}:apply", target_roi=facts.apply_target,
        source_frame_sha256=facts.source_frame_sha256, source_frame_captured_at=1.0,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, game_day_id="test-reset",
        expected_postcondition=post, consequence="commander_talent_preset_switch", cost_type="none",
        cost_amount=0, quantity=1, evidence_refs=(facts.evidence_ref,),
        action_class=ActionClass.ZERO_COST_CONSEQUENTIAL, action_kind="commander_talent_preset_switch",
        subject=name, resource_or_currency="none", maximum_cost=0, free_only=True,
        semantic_preconditions=preconditions, semantic_postconditions=(post,),
    )
    snapshot = {key: getattr(intent, key) for key in (
        "action_id", "action_key", "task_id", "semantic_action", "action_kind", "subject",
        "resource_or_currency", "free_only", "maximum_cost", "allowed_confirmation_dialogs")}
    snapshot.update(
        allowed_confirmation_dialogs=[],
        action_class=ActionClass.ZERO_COST_CONSEQUENTIAL.value, semantic_preconditions=list(preconditions),
        semantic_postconditions=[post], expected_runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        observation={"frame_sha256": facts.source_frame_sha256, "source_state": "TALENT_MEMORY",
                     "target_identity": intent.target_identity, "target_roi": list(facts.apply_target),
                     "control_class": "commander_talent_preset_switch", "consequence": intent.consequence,
                     "cost_type": "none", "cost_amount": 0, "quantity": 1, "expected_postcondition": post},
    )
    policy = PolicyResult(PolicyDecision.AUTHORIZE, "APPROVED_FOR_TEST", "test only", 1.0, snapshot)
    return CommanderTalentSwitchApproval(intent, policy, facts.source_frame_sha256, generation, context_sha256)


class CanonicalCommanderTalentTests(unittest.TestCase):
    def _call(self, session, store, native_port, *, context=None, switch_approval=None):
        return ensure_commander_talent_preset(
            session, session.runtime, "Economy", checkpoint=lambda: None,
            runtime_input_lock=session.runtime_input_lock, action_store=store,
            source_generation=session.invocation_id,
            context=context or {"flow_id": "test-route", "required_preset": "Economy"},
            native_port=native_port, switch_approval=switch_approval,
        )

    def test_same_visit_proof_is_reused_without_reopening_from_consuming_screen(self):
        session, store = CanonicalTalentSession(), CanonicalTalentStore()
        calls = []

        def native(*args, **kwargs):
            calls.append(1)
            return TalentPresetNativeResult("already_applied", True, "Economy", "CURRENTLY_APPLIED", ("frame:applied",), 0)

        self.assertTrue(self._call(session, store, native).verified)
        reused = self._call(session, store, native)
        self.assertTrue(reused.verified)
        self.assertEqual(reused.input_count, 0)
        self.assertEqual(calls, [1])

    def test_external_manual_restart_and_context_loss_invalidate_same_visit_proof(self):
        for reason in ("external change", "manual takeover", "restart", "context loss"):
            with self.subTest(reason=reason):
                session, store = CanonicalTalentSession(), CanonicalTalentStore()
                outcomes = iter((
                    TalentPresetNativeResult("already_applied", True, "Economy", "APPLIED", ("frame:applied",), 0),
                    TalentPresetNativeResult("deferred", False, "Economy", "CURRENT_PRESET_CHANGED", ("frame:changed",), 0),
                ))
                def native(*args, **kwargs):
                    return next(outcomes)
                self.assertTrue(self._call(session, store, native).verified)
                invalidate_commander_talent_preset(session, reason)
                self.assertFalse(self._call(session, store, native).verified)

    def test_generation_context_and_runtime_changes_require_new_native_observation(self):
        for change in ("generation", "context", "runtime", "session"):
            with self.subTest(change=change):
                session, store = CanonicalTalentSession(), CanonicalTalentStore()
                outcomes = iter((
                    TalentPresetNativeResult("already_applied", True, "Economy", "APPLIED", ("frame:applied",), 0),
                    TalentPresetNativeResult("deferred", False, "Economy", "NEW_PROOF_REQUIRED", ("frame:changed",), 0),
                ))
                def native(*args, **kwargs):
                    return next(outcomes)
                self.assertTrue(self._call(session, store, native).verified)
                context = None
                if change == "generation":
                    session.invocation_id = session.runtime_input_lock.invocation_id = "native-generation-2"
                elif change == "context":
                    context = {"flow_id": "other-route", "required_preset": "Economy"}
                elif change == "runtime":
                    session.runtime = object()
                else:
                    session = CanonicalTalentSession()
                self.assertFalse(self._call(session, store, native, context=context).verified)

    def test_inactive_session_cannot_reuse_proof(self):
        session, store = CanonicalTalentSession(), CanonicalTalentStore()
        def native(*args, **kwargs):
            return TalentPresetNativeResult("already_applied", True, "Economy", "APPLIED", ("frame:a",), 0)
        self.assertTrue(self._call(session, store, native).verified)
        session.is_active = False
        with self.assertRaisesRegex(RuntimeError, "active DevelopmentSession"):
            self._call(session, store, native)

    def _switch(self, session, store, *, unknown=False, approval_change=None):
        facts = _switch_facts()
        context = {"flow_id": "test-route", "required_preset": "Economy"}
        approval = _approved_switch(facts, session.invocation_id, context_fingerprint(context))
        if approval_change is not None:
            approval = approval_change(approval)

        def native(_session, _runtime, required, **kwargs):
            permit = kwargs["switch_approval"](facts, type("Frame", (), {"sha256": facts.source_frame_sha256})())
            if permit is None:
                return TalentPresetNativeResult("deferred", False, required, "SWITCH_NOT_APPROVED", (), 0)
            self.assertIsInstance(permit, TalentSwitchPermit)
            applied = replace(facts, row_state=PresetRowState.APPLIED, applied_preset="Economy", apply_target=None,
                              source_frame_sha256="e" * 64, evidence_ref="frame:applied")
            kwargs["switch_outcome"](permit.action_key, "unknown" if unknown else "switched", True, None if unknown else applied)
            return TalentPresetNativeResult("unknown" if unknown else "switched", not unknown, required,
                                            "UNKNOWN_NO_RETRY" if unknown else "APPLIED", ("frame:applied",), 1,
                                            permit.action_key, True)

        return self._call(session, store, native, context=context, switch_approval=lambda *_: approval)

    def test_approved_free_switch_is_confirmed_once_and_reused(self):
        session, store = CanonicalTalentSession(), CanonicalTalentStore()
        result = self._switch(session, store)
        self.assertTrue(result.verified)
        self.assertEqual(store.get_action_by_key(result.switch_action_key)["status"], "confirmed")
        reused = self._call(session, store, lambda *args, **kwargs: self.fail("must reuse Applied proof"))
        self.assertTrue(reused.verified)
        self.assertEqual(reused.status, "already_applied")
        self.assertEqual(len(store.actions), 1)

    def test_nonfree_or_changed_source_approval_is_rejected_without_preparing(self):
        for change in (lambda approval: replace(approval, intent=replace(approval.intent, cost_amount=25)),
                       lambda approval: replace(approval, source_frame_sha256="f" * 64)):
            session, store = CanonicalTalentSession(), CanonicalTalentStore()
            result = self._switch(session, store, approval_change=change)
            self.assertFalse(result.verified)
            self.assertEqual(store.actions, {})

    def test_unknown_switch_blocks_durable_identical_retry_and_cache(self):
        session, store = CanonicalTalentSession(), CanonicalTalentStore()
        first = self._switch(session, store, unknown=True)
        self.assertTrue(first.effect_reconciliation_required)
        self.assertTrue(first.identical_retry_denied)
        second = self._call(session, store, lambda *args, **kwargs: self.fail("unknown switch cannot retry"))
        self.assertEqual(second.reason, "CANONICAL_ACTION_REQUIRES_INSPECTION")

    def test_switch_requires_canonical_store_lease(self):
        session, store = CanonicalTalentSession(), CanonicalTalentStore()
        store.lease_valid_for = lambda *_: False
        result = self._switch(session, store)
        self.assertFalse(result.verified)
        self.assertEqual(store.actions, {})


    def test_absent_switch_approval_does_not_prepare_a_canonical_action(self):
        session = CanonicalTalentSession()
        facts = replace(_switch_facts(), preset_name="Training")
        context = {"flow_id": TROOP_TRAINING_FLOW_ID, "required_preset": "Training",
                   "scheduler_reset_id": "game-day-2026-11-08"}

        def native(_session, _runtime, required, **kwargs):
            frame = SimpleNamespace(sha256=facts.source_frame_sha256, captured_monotonic=time.monotonic())
            permit = kwargs["switch_approval"](facts, frame)
            self.assertIsNone(permit)
            return TalentPresetNativeResult("deferred", False, required, "SWITCH_NOT_APPROVED",
                                            ("frame:training-apply",), 0)

        with tempfile.TemporaryDirectory() as directory:
            store = SafetyStore(Path(directory) / "actions.sqlite3")
            try:
                store.acquire_lease(session.owner, time.time(), 60)
                runtime = SimpleNamespace(session=Path(directory), measure_foreground_package=lambda: "com.global.ztmslg")
                result = ensure_commander_talent_preset(
                    session, runtime, "Training", checkpoint=lambda: None,
                    runtime_input_lock=session.runtime_input_lock, action_store=store,
                    source_generation=session.invocation_id, context=context, native_port=native,
                )
                self.assertFalse(result.verified)
                self.assertEqual(store.list_actions_for_task(TROOP_TRAINING_FLOW_ID), [])
            finally:
                store.close()

class CanonicalCommanderTalentApprovalTests(unittest.TestCase):
    def _approval(self, *, preset="Training", task_id=TROOP_TRAINING_FLOW_ID):
        session, store = CanonicalTalentSession(), CanonicalTalentStore()
        facts = replace(_switch_facts(), preset_name=preset,
                        applied_preset="Economy" if preset == "Military" else "Military")
        frame = SimpleNamespace(sha256=facts.source_frame_sha256,
                                captured_monotonic=time.monotonic(),
                                frame=np.ones((1280, 800, 3), dtype=np.uint8))
        runtime = SimpleNamespace(measure_foreground_package=lambda: "com.global.ztmslg")
        context = {"flow_id": task_id, "required_preset": preset}
        approve = commander_talent_switch_approval(
            session, runtime, action_store=store, task_id=task_id, game_day_id="test-reset",
            source_generation=session.invocation_id, context=context,
        )
        return session, store, facts, frame, runtime, context, approve

    def test_real_policy_authorizes_free_saved_apply_for_existing_consumers(self):
        for preset, task_id in (("Training", TROOP_TRAINING_FLOW_ID), ("Military", HALL_OF_WAR_TASK)):
            with self.subTest(preset=preset):
                session, store, facts, frame, runtime, context, approve = self._approval(
                    preset=preset, task_id=task_id)
                approval = approve(facts, frame)
                self.assertIsInstance(approval, CommanderTalentSwitchApproval)
                self.assertTrue(approval.policy_result.authorized)
                self.assertEqual(approval.intent.cost_type, "none")
                self.assertEqual(approval.intent.cost_amount, 0)
                self.assertEqual(approval.intent.allowed_confirmation_dialogs, (APPLY_CONFIRMATION_DIALOG,))
                self.assertEqual(approval.source_frame_sha256, frame.sha256)

                def native(_session, _runtime, required, **kwargs):
                    permit = kwargs["switch_approval"](facts, frame)
                    self.assertIsInstance(permit, TalentSwitchPermit)
                    applied = replace(facts, row_state=PresetRowState.APPLIED, applied_preset=required,
                                      apply_target=None, source_frame_sha256="e" * 64,
                                      evidence_ref="frame:applied")
                    kwargs["switch_outcome"](permit.action_key, "switched", True, applied)
                    return TalentPresetNativeResult(
                        "switched", True, required, "APPLIED", ("frame:applied",), 1, permit.action_key, True)

                result = ensure_commander_talent_preset(
                    session, runtime, preset, checkpoint=lambda: None,
                    runtime_input_lock=session.runtime_input_lock, action_store=store,
                    source_generation=session.invocation_id, context=context,
                    native_port=native, switch_approval=approve,
                )
                self.assertTrue(result.verified)
                self.assertEqual(store.get_action_by_key(result.switch_action_key)["status"], "confirmed")

    def test_fresh_policy_rejects_changed_stale_unleased_blocked_or_duplicate_source(self):
        for change in ("hash", "stale", "lease", "block", "duplicate", "foreground", "applied", "consumer"):
            with self.subTest(change=change):
                _, store, facts, frame, runtime, _, approve = self._approval()
                if change == "hash":
                    frame.sha256 = "f" * 64
                elif change == "stale":
                    frame.captured_monotonic -= 60
                elif change == "lease":
                    store.lease_valid_for = lambda *_: False
                elif change == "block":
                    store.has_action_block = lambda: True
                elif change == "duplicate":
                    store.get_action_by_key = lambda *_: {"status": "confirmed"}
                elif change == "foreground":
                    runtime.measure_foreground_package = lambda: "other.package"
                elif change == "applied":
                    facts = replace(facts, row_state=PresetRowState.APPLIED)
                elif change == "consumer":
                    facts = replace(facts, preset_name="Military", applied_preset="Economy")
                self.assertIsNone(approve(facts, frame))


if __name__ == "__main__":
    unittest.main()
