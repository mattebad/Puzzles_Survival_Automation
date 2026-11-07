from __future__ import annotations

from dataclasses import dataclass
import unittest

from automation_service.commander_talents import (
    CommanderTalentSwitchApproval,
    ensure_commander_talent_preset,
)
from safe_action_core.models import ActionClass, ActionIntent, PolicyDecision, PolicyResult
from tasks.commander_talents import (
    PRESET_NAMES,
    PresetRowState,
    TalentMemoryObservation,
    TalentPresetNativeResult,
    TalentSwitchPermit,
    context_fingerprint,
    observe_preset,
    recognize_talent_memory,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID


@dataclass(frozen=True)
class Hit:
    text: str
    bounds: tuple[int, int, int, int]
    confidence: float = 95.0


def memory_hits(*, applied: str = "Military", cost: str | None = None) -> tuple[Hit, ...]:
    rows = (("Economy", 150), ("Military", 250), ("Training", 350))
    result = [Hit("Talent Memory", (270, 40, 515, 80))]
    for name, y in rows:
        result.append(Hit(name, (58, y, 190, y + 32)))
        state = "Applied" if name == applied else "Apply"
        result.append(Hit(state, (518, y, 674, y + 34)))
        if name == "Economy" and cost is not None:
            result.extend((
                Hit(cost, (380, y, 520, y + 18)),
                Hit("Cooldown: 0 seconds", (370, y + 20, 540, y + 38)),
                Hit("Confirmation: exact Apply", (340, y + 40, 560, y + 58)),
            ))
    return tuple(result)


class CommanderTalentSemanticsTests(unittest.TestCase):
    def test_exact_saved_preset_names_and_applied_row_are_recognized(self) -> None:
        self.assertEqual(set(PRESET_NAMES), {"Military", "Economy", "Training"})
        recognition = recognize_talent_memory(memory_hits())
        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.applied_preset, "Military")

        military = observe_preset(
            recognition,
            "Military",
            source_frame_sha256="a" * 64,
            evidence_ref="frame:memory-applied",
        )
        self.assertTrue(military.recognized)
        self.assertEqual(military.row_state, PresetRowState.APPLIED)
        self.assertIsNone(military.apply_target)

        economy = observe_preset(
            recognition,
            "Economy",
            source_frame_sha256="a" * 64,
            evidence_ref="frame:memory-applied",
        )
        self.assertTrue(economy.recognized)
        self.assertEqual(economy.row_state, PresetRowState.APPLY)
        self.assertEqual(economy.apply_target, (518, 150, 674, 184))
        self.assertFalse(economy.switch_facts_complete)

    def test_cost_cooldown_and_confirmation_must_be_observed_on_target_row(self) -> None:
        recognition = recognize_talent_memory(memory_hits(cost="Cost: 25 Gold"))
        self.assertTrue(recognition.recognized)
        economy = observe_preset(
            recognition,
            "Economy",
            source_frame_sha256="b" * 64,
            evidence_ref="frame:priced-memory",
        )
        self.assertEqual(economy.cost_text, "Cost: 25 Gold")
        self.assertEqual(economy.cooldown_text, "Cooldown: 0 seconds")
        self.assertEqual(economy.confirmation_text, "Confirmation: exact Apply")
        self.assertTrue(economy.switch_facts_complete)

        changed_cost = recognize_talent_memory(memory_hits(cost="Cost: 26 Gold"))
        changed = observe_preset(
            changed_cost,
            "Economy",
            source_frame_sha256="c" * 64,
            evidence_ref="frame:changed-price",
        )
        self.assertNotEqual(economy.cost_text, changed.cost_text)

    def test_ambiguous_rows_or_applied_state_are_unknown(self) -> None:
        hits = list(memory_hits())
        training_apply = next(index for index, hit in enumerate(hits)
                              if hit.text == "Apply" and hit.bounds[1] == 350)
        hits[training_apply] = Hit("Applied", hits[training_apply].bounds)
        recognition = recognize_talent_memory(hits)
        self.assertFalse(recognition.recognized)
        self.assertEqual(recognition.reason, "APPLIED_PRESET_NOT_UNIQUE")

        missing = recognize_talent_memory(memory_hits()[:-1])
        self.assertFalse(missing.recognized)
        self.assertEqual(missing.reason, "PRESET_STATUS_MISSING_OR_AMBIGUOUS")

    def test_context_fingerprint_is_order_independent_and_context_specific(self) -> None:
        first = context_fingerprint({"facility": "Hall of War", "preset": "Military"})
        same = context_fingerprint({"preset": "Military", "facility": "Hall of War"})
        changed = context_fingerprint({"facility": "Troop Camp", "preset": "Training"})
        self.assertEqual(first, same)
        self.assertNotEqual(first, changed)


class CanonicalTalentLock:
    owner = "automation-service:test"
    invocation_id = "native-generation-1"

    def assert_held(self, owner: str, invocation_id: str) -> None:
        if (owner, invocation_id) != (self.owner, self.invocation_id):
            raise RuntimeError("owner lost")


class CanonicalTalentSession:
    def __init__(self) -> None:
        self.is_active = True
        self.owner = "automation-service:test"
        self.invocation_id = "native-generation-1"
        self.runtime_input_lock = CanonicalTalentLock()


class CanonicalTalentStore:
    def __init__(self) -> None:
        self.actions: dict[str, dict[str, object]] = {}

    def has_action_block(self) -> bool:
        return any(row["status"] in {"prepared", "input_sent", "unresolved"} for row in self.actions.values())

    def lease_valid_for(self, owner: str, now: float) -> bool:
        return owner == "automation-service:test" and now > 0

    def get_action_by_key(self, key: str):
        return self.actions.get(key)

    def prepare_action(self, intent, policy, now: float) -> None:
        if intent.action_key in self.actions:
            raise ValueError("duplicate action")
        self.actions[intent.action_key] = {"action_id": intent.action_id, "status": "prepared"}

    def _row(self, action_id: str) -> dict[str, object]:
        return next(row for row in self.actions.values() if row["action_id"] == action_id)

    def mark_input_sent(self, action_id: str, now: float, result) -> None:
        self._row(action_id)["status"] = "input_sent"

    def mark_confirmed(self, action_id: str, now: float, evidence) -> None:
        self._row(action_id)["status"] = "confirmed"

    def mark_unresolved(self, action_id: str, now: float, reason: str, evidence=None) -> None:
        self._row(action_id)["status"] = "unresolved"


def _switch_facts() -> TalentMemoryObservation:
    return TalentMemoryObservation(
        recognized=True,
        preset_name="Economy",
        row_state=PresetRowState.APPLY,
        applied_preset="Military",
        apply_target=(518, 150, 674, 184),
        cost_text="Cost: 25 Gold",
        cooldown_text="Cooldown: 0 seconds",
        confirmation_text="Confirmation: exact Apply",
        source_frame_sha256="d" * 64,
        evidence_ref="frame:talent-memory-source",
        reason="PRESET_AVAILABLE_TO_APPLY",
    )


def _approved_switch(facts: TalentMemoryObservation, generation: str, context_sha256: str):
    action_id = "commander-talent-action-1"
    action_key = f"commander-talent-switch:economy:{generation}"
    semantic_action = "switch_commander_talent_preset:economy"
    target_identity = "talent-memory-row:Economy:apply"
    expected_post = "talent-memory-applied:Economy"
    preconditions = (
        "saved-preset-name:Economy",
        "currently-Apply:Economy",
        f"previous-applied-preset:{facts.applied_preset}",
        f"exact-cost-observed:{facts.cost_text}",
        f"cooldown-observed:{facts.cooldown_text}",
        f"confirmation-observed:{facts.confirmation_text}",
        f"source-generation:{generation}",
        f"context-sha256:{context_sha256}",
    )
    intent = ActionIntent(
        action_id=action_id,
        action_key=action_key,
        task_id="test_route",
        semantic_action=semantic_action,
        source_state="TALENT_MEMORY",
        target_identity=target_identity,
        target_roi=facts.apply_target,
        source_frame_sha256=facts.source_frame_sha256,
        source_frame_captured_at=1.0,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        game_day_id="test-reset",
        expected_postcondition=expected_post,
        consequence="commander_talent_preset_switch",
        cost_type="gold",
        cost_amount=25.0,
        quantity=1,
        evidence_refs=(facts.evidence_ref,),
        action_class=ActionClass.SPEND_OR_STRATEGIC,
        action_kind="commander_talent_preset_switch",
        subject="Economy",
        resource_or_currency="gold",
        maximum_cost=25.0,
        free_only=False,
        semantic_preconditions=preconditions,
        semantic_postconditions=(expected_post,),
    )
    snapshot = {
        "action_id": action_id,
        "action_key": action_key,
        "task_id": intent.task_id,
        "semantic_action": semantic_action,
        "action_kind": "commander_talent_preset_switch",
        "subject": "Economy",
        "resource_or_currency": "gold",
        "free_only": False,
        "maximum_cost": 25.0,
        "action_class": ActionClass.SPEND_OR_STRATEGIC.value,
        "semantic_preconditions": list(preconditions),
        "semantic_postconditions": [expected_post],
        "expected_runtime_profile_id": ACTIVE_RUNTIME_PROFILE_ID,
        "observation": {
            "frame_sha256": facts.source_frame_sha256,
            "source_state": "TALENT_MEMORY",
            "target_identity": target_identity,
            "target_roi": list(facts.apply_target),
            "control_class": "commander_talent_preset_switch",
            "consequence": "commander_talent_preset_switch",
            "cost_type": "gold",
            "cost_amount": 25.0,
            "quantity": 1,
            "expected_postcondition": expected_post,
        },
    }
    policy = PolicyResult(PolicyDecision.AUTHORIZE, "APPROVED_FOR_TEST", "test only", 1.0, snapshot)
    return CommanderTalentSwitchApproval(
        intent,
        policy,
        facts.cost_text,
        facts.cooldown_text,
        facts.confirmation_text,
        facts.source_frame_sha256,
        generation,
        context_sha256,
    )


class CanonicalCommanderTalentTests(unittest.TestCase):
    def _call(self, session, store, native_port, *, context=None, switch_approval=None):
        selected_context = context or {"flow_id": "test-route", "required_preset": "Economy"}
        return ensure_commander_talent_preset(
            session,
            object(),
            "Economy",
            checkpoint=lambda: None,
            runtime_input_lock=session.runtime_input_lock,
            action_store=store,
            source_generation=session.runtime_input_lock.invocation_id,
            context=selected_context,
            native_port=native_port,
            switch_approval=switch_approval,
        )

    def test_same_generation_observes_external_applied_state_change(self) -> None:
        session = CanonicalTalentSession()
        store = CanonicalTalentStore()
        results = iter((
            TalentPresetNativeResult("already_applied", True, "Economy", "CURRENTLY_APPLIED", ("frame:applied",), 0),
            TalentPresetNativeResult("deferred", False, "Economy", "EXTERNAL_PRESET_CHANGE_OBSERVED", ("frame:external-change",), 0),
        ))

        def native_port(*args, **kwargs):
            return next(results)

        first = self._call(session, store, native_port)
        after_external_change = self._call(session, store, native_port)
        self.assertTrue(first.verified)
        self.assertEqual(first.status, "already_applied")
        self.assertFalse(after_external_change.verified)
        self.assertEqual(after_external_change.status, "deferred")
        self.assertEqual(after_external_change.reason, "EXTERNAL_PRESET_CHANGE_OBSERVED")
        self.assertEqual(after_external_change.evidence_refs, ("frame:external-change",))

    def test_changed_context_requires_fresh_native_state(self) -> None:
        session = CanonicalTalentSession()
        store = CanonicalTalentStore()
        results = iter((
            TalentPresetNativeResult("already_applied", True, "Economy", "CURRENTLY_APPLIED", ("frame:applied",), 0),
            TalentPresetNativeResult("deferred", False, "Economy", "CURRENT_PRESET_CHANGED", ("frame:changed",), 0),
        ))

        def native_port(*args, **kwargs):
            return next(results)

        first = self._call(session, store, native_port)
        changed = self._call(
            session,
            store,
            native_port,
            context={"flow_id": "test-route", "required_preset": "Economy", "context": "changed"},
        )
        self.assertTrue(first.verified)
        self.assertFalse(changed.verified)
        self.assertEqual(changed.reason, "CURRENT_PRESET_CHANGED")
        self.assertEqual(changed.evidence_refs, ("frame:changed",))

    def test_changed_generation_requires_fresh_native_state(self) -> None:
        session = CanonicalTalentSession()
        store = CanonicalTalentStore()
        results = iter((
            TalentPresetNativeResult("already_applied", True, "Economy", "CURRENTLY_APPLIED", ("frame:applied",), 0),
            TalentPresetNativeResult("deferred", False, "Economy", "NEW_GENERATION_OBSERVATION_REQUIRED", ("frame:new-generation",), 0),
        ))

        def native_port(*args, **kwargs):
            return next(results)

        first = self._call(session, store, native_port)
        session.runtime_input_lock.invocation_id = "native-generation-2"
        session.invocation_id = "native-generation-2"
        changed_generation = self._call(session, store, native_port)
        self.assertTrue(first.verified)
        self.assertFalse(changed_generation.verified)
        self.assertEqual(changed_generation.reason, "NEW_GENERATION_OBSERVATION_REQUIRED")
        self.assertEqual(changed_generation.evidence_refs, ("frame:new-generation",))

    def test_restarted_session_requires_fresh_native_state(self) -> None:
        store = CanonicalTalentStore()
        results = iter((
            TalentPresetNativeResult("already_applied", True, "Economy", "CURRENTLY_APPLIED", ("frame:prior-session",), 0),
            TalentPresetNativeResult("deferred", False, "Economy", "PRESET_CHANGED_AFTER_RESTART", ("frame:restarted-session",), 0),
        ))

        def native_port(*args, **kwargs):
            return next(results)

        first = self._call(CanonicalTalentSession(), store, native_port)
        after_restart = self._call(CanonicalTalentSession(), store, native_port)
        self.assertTrue(first.verified)
        self.assertFalse(after_restart.verified)
        self.assertEqual(after_restart.reason, "PRESET_CHANGED_AFTER_RESTART")
        self.assertEqual(after_restart.evidence_refs, ("frame:restarted-session",))

    def test_inactive_session_rejects_without_using_prior_native_proof(self) -> None:
        session = CanonicalTalentSession()
        store = CanonicalTalentStore()
        calls = []

        def native_port(*args, **kwargs):
            calls.append(1)
            return TalentPresetNativeResult("already_applied", True, "Economy", "CURRENTLY_APPLIED", ("frame:applied",), 0)

        first = self._call(session, store, native_port)
        session.is_active = False
        with self.assertRaisesRegex(RuntimeError, "active DevelopmentSession"):
            self._call(session, store, native_port)
        self.assertTrue(first.verified)
        self.assertEqual(calls, [1])

    def test_canonical_approval_records_one_successful_switch(self) -> None:
        session = CanonicalTalentSession()
        store = CanonicalTalentStore()
        facts = _switch_facts()
        context = {"flow_id": "test-route", "required_preset": "Economy"}
        context_sha256 = context_fingerprint(context)
        approval = _approved_switch(facts, session.runtime_input_lock.invocation_id, context_sha256)
        native_calls = []

        def native_port(_session, _runtime, required_preset, **kwargs):
            native_calls.append(required_preset)
            if len(native_calls) == 1:
                permit = kwargs["switch_approval"](facts, type("Frame", (), {"sha256": facts.source_frame_sha256})())
                self.assertIsInstance(permit, TalentSwitchPermit)
                applied = TalentMemoryObservation(
                    True, "Economy", PresetRowState.APPLIED, "Economy", None, None, None, None,
                    "e" * 64, "frame:applied", "PRESET_APPLIED",
                )
                kwargs["switch_outcome"](permit.action_key, "switched", True, applied)
                return TalentPresetNativeResult("switched", True, "Economy", "APPLIED", ("frame:applied",), 1,
                                                permit.action_key, True)
            return TalentPresetNativeResult(
                "already_applied", True, required_preset, "FRESH_APPLIED_OBSERVATION", ("frame:fresh-applied",), 0
            )

        result = self._call(session, store, native_port, context=context, switch_approval=lambda *_: approval)
        self.assertEqual(result.status, "switched")
        self.assertTrue(result.verified)
        row = store.get_action_by_key(approval.intent.action_key)
        self.assertEqual(row["status"], "confirmed")

        reobserved = self._call(session, store, native_port, context=context)
        self.assertTrue(reobserved.verified)
        self.assertEqual(reobserved.status, "already_applied")
        self.assertEqual(reobserved.evidence_refs, ("frame:fresh-applied",))
        self.assertEqual(native_calls, ["Economy", "Economy"])

    def test_switch_approval_requires_canonical_store_lease_proof(self) -> None:
        session = CanonicalTalentSession()
        backing = CanonicalTalentStore()

        class LeaseUnknownStore:
            def has_action_block(self):
                return backing.has_action_block()

            def get_action_by_key(self, key):
                return backing.get_action_by_key(key)

            def prepare_action(self, intent, policy, now):
                backing.prepare_action(intent, policy, now)

        facts = _switch_facts()
        context = {"flow_id": "test-route", "required_preset": "Economy"}
        approval = _approved_switch(facts, session.runtime_input_lock.invocation_id, context_fingerprint(context))

        def native_port(_session, _runtime, required_preset, **kwargs):
            permit = kwargs["switch_approval"](facts, type("Frame", (), {"sha256": facts.source_frame_sha256})())
            self.assertIsNone(permit)
            return TalentPresetNativeResult("deferred", False, required_preset, "SWITCH_NOT_APPROVED", (), 0)

        result = self._call(
            session,
            LeaseUnknownStore(),
            native_port,
            context=context,
            switch_approval=lambda *_: approval,
        )
        self.assertEqual(result.status, "deferred")
        self.assertEqual(backing.actions, {})

    def test_unknown_switch_blocks_durable_identical_retry(self) -> None:
        session = CanonicalTalentSession()
        store = CanonicalTalentStore()
        facts = _switch_facts()
        context = {"flow_id": "test-route", "required_preset": "Economy"}
        approval = _approved_switch(facts, session.runtime_input_lock.invocation_id, context_fingerprint(context))
        calls = []

        def native_port(_session, _runtime, required_preset, **kwargs):
            calls.append(required_preset)
            permit = kwargs["switch_approval"](facts, type("Frame", (), {"sha256": facts.source_frame_sha256})())
            kwargs["switch_outcome"](permit.action_key, "unknown", True, None)
            return TalentPresetNativeResult("unknown", False, "Economy", "UNKNOWN_NO_RETRY", (), 1,
                                            permit.action_key, True)

        first = self._call(session, store, native_port, context=context, switch_approval=lambda *_: approval)
        second = self._call(session, store, native_port, context=context, switch_approval=lambda *_: approval)
        self.assertEqual(first.status, "unknown")
        self.assertTrue(first.effect_reconciliation_required)
        self.assertTrue(first.identical_retry_denied)
        self.assertEqual(second.reason, "CANONICAL_ACTION_REQUIRES_INSPECTION")
        self.assertEqual(calls, ["Economy"])


if __name__ == "__main__":
    unittest.main()
