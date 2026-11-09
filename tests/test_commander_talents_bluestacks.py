from __future__ import annotations

from scripts.enhancement_bluestacks import OcrHit as Hit
import hashlib
import unittest
from unittest.mock import patch

import numpy as np

from tasks.commander_talents import TalentPresetNativeResult, TalentSwitchPermit
from scripts import commander_talents_bluestacks as native




class FakeLock:
    def __init__(self) -> None:
        self.owner = "automation-service:commander-talent-test"
        self.invocation_id = "native-generation-1"
        self.held = True

    def assert_held(self, owner: str, invocation_id: str) -> None:
        if not self.held or (owner, invocation_id) != (self.owner, self.invocation_id):
            raise RuntimeError("owner lost")


class FakeActionStore:
    def __init__(self) -> None:
        self.blocked = False

    def has_action_block(self) -> bool:
        return self.blocked


class FakeRuntime:
    def __init__(self, *, page: str, applied: str = "Military", switch_mode: str = "applied") -> None:
        self.page = page
        self.applied = applied
        self.switch_mode = switch_mode
        self.captures = 0
        self.taps: list[tuple[str, str]] = []
        self.change_preset_on_second_capture = False

    def capture(self, label: str):
        self.captures += 1
        if self.change_preset_on_second_capture and self.captures >= 2:
            self.applied = "Training"
        payload = np.zeros((1280, 800, 3), dtype=np.uint8)
        payload[0, 0, 0] = _PAGE_CODES.get(self.page, _PAGE_CODES["unknown"])
        digest = hashlib.sha256(f"{self.page}:{self.captures}:{label}".encode()).hexdigest()
        return type("Frame", (), {
            "frame": payload,
            "sha256": digest,
            "path": f"frame:{self.captures}:{label}",
            "captured_monotonic": float(self.captures),
        })()

    def tap(self, frame, *, target_identity, target_roi, action_key, action_class="navigation", consequential=False, continuation_of=None):
        self.taps.append((target_identity, action_key))
        if target_identity.startswith("commander-talent-navigation:"):
            _, source, destination = target_identity.split(":", 2)
            self.page = "memory" if destination == "talent_memory" else destination
        elif target_identity.startswith("talent-memory-row:"):
            self.requested = target_identity.split(":")[1]
            if self.switch_mode == "applied":
                self.applied = self.requested
                self.page = "memory"
            elif self.switch_mode in {"confirmation", "paid_confirmation"}:
                self.page = self.switch_mode
            else:
                self.page = "unknown"
        elif target_identity.startswith("talent-memory-confirm:"):
            self.applied = self.requested
            self.page = "memory"


_PAGE_CODES = {"home": 1, "commander_info": 2, "commander_talent": 3, "memory": 4,
               "confirmation": 5, "paid_confirmation": 6, "unknown": 9}


def _memory_hits(applied: str) -> tuple[Hit, ...]:
    result = [Hit("Talent Memory", (265, 42, 515, 84))]
    for name, y in (("Economy", 150), ("Military", 250), ("Training", 350)):
        result.append(Hit(name, (58, y, 188, y + 30)))
        result.append(Hit("Applied" if name == applied else "Apply", (520, y, 675, y + 32)))
    return tuple(result)


def _page_hits(frame: np.ndarray, runtime: FakeRuntime) -> tuple[Hit, ...]:
    page = _PAGE_NAMES.get(int(frame[0, 0, 0]), "unknown")
    if page == "commander_info":
        return tuple(Hit(text, (40 + index * 105, 70, 120 + index * 105, 110))
                     for index, text in enumerate(("Commander Info", "Gear", "Chip", "Module", "Cube", "Bioenhancer"))) + tuple(
            Hit(text, (30 + index * 140, 1120, 110 + index * 140, 1170))
            for index, text in enumerate(("Talent", "Commander", "Boosts", "Alliance", "Achievement"))
        )
    if page == "commander_talent":
        return (
            Hit("Cmdr Talent", (275, 35, 500, 76)),
            Hit("Talent Memory", (410, 120, 530, 170)),
            Hit("Reset", (545, 120, 645, 170)),
            Hit("Economy", (50, 190, 200, 225)),
            Hit("Military", (290, 190, 420, 225)),
            Hit("Balance", (520, 190, 650, 225)),
        )
    if page == "memory":
        return _memory_hits(runtime.applied)
    if page in {"confirmation", "paid_confirmation"}:
        hits = (
            Hit(f"Apply {runtime.requested} talent preset?", (220, 450, 580, 480)),
            Hit("Confirm", (450, 650, 580, 690)), Hit("Cancel", (200, 650, 330, 690)),
        )
        if page == "paid_confirmation":
            hits += (Hit("Cost: 25 diamonds", (220, 500, 580, 530)),)
        return hits
    return ()


_PAGE_NAMES = {value: key for key, value in _PAGE_CODES.items()}


class FakeSession:
    def __init__(self, runtime: FakeRuntime, lock: FakeLock) -> None:
        self.runtime = runtime
        self.runtime_input_lock = lock
        self.owner = lock.owner
        self.invocation_id = lock.invocation_id
        self.is_active = True
        self.input_count = 0
        self.control_memory: dict[str, object] = {}
        self.actions: list[str] = []

    def observe(self, capture, *, label):
        self.runtime_input_lock.assert_held(self.runtime_input_lock.owner, self.runtime_input_lock.invocation_id)
        return capture(label)

    def run_action(self, *, label, capture, dispatch, recognize, authorize, **kwargs):
        before = capture(f"{label}-immediate-before")
        authorize(before)
        self.input_count += 1
        dispatch(before)
        after = capture(f"{label}-immediate-post")
        state = recognize(after)
        self.actions.append(label)
        return type("ActionResult", (), {
            "status": "completed" if state != "unknown" else "unknown",
            "state": state,
        })()


def _patch_home_recognition(runtime: FakeRuntime):
    def recognize(frame, *, source_frame_sha256=None, ocr_engine=None):
        page = _PAGE_NAMES.get(int(frame[0, 0, 0]), "unknown")
        return type("Home", (), {
            "recognized": page == "home",
            "portrait_target": (10, 60, 85, 130) if page == "home" else None,
        })()
    return patch.object(native, "recognize_home_frame", side_effect=recognize)


class CommanderTalentNativeTests(unittest.TestCase):
    def _run(self, runtime, required, *, switch_approval=None, switch_outcome=None, store=None):
        lock = FakeLock()
        session = FakeSession(runtime, lock)
        store = store or FakeActionStore()
        with _patch_home_recognition(runtime):
            result = native.run_commander_talent_preset(
                session,
                runtime,
                required,
                checkpoint=lambda: None,
                runtime_input_lock=lock,
                action_store=store,
                source_generation=lock.invocation_id,
                context={"flow": "native-test", "requested": required},
                ocr_engine=lambda frame, roi: _page_hits(frame, runtime),
                switch_approval=switch_approval,
                switch_outcome=switch_outcome,
            )
        return result, session, store

    def test_already_applied_does_not_dispatch_any_input(self) -> None:
        runtime = FakeRuntime(page="memory", applied="Military")
        result, session, _store = self._run(runtime, "Military")
        self.assertEqual(result.status, "already_applied")
        self.assertTrue(result.verified)
        self.assertEqual(session.input_count, 0)
        self.assertEqual(runtime.taps, [])

    def test_navigation_uses_observed_profile_and_talent_controls(self) -> None:
        runtime = FakeRuntime(page="home", applied="Military")
        result, session, _store = self._run(runtime, "Military")
        self.assertEqual(result.status, "already_applied")
        self.assertTrue(result.verified)
        self.assertEqual(session.input_count, 3)
        self.assertEqual([entry[0] for entry in runtime.taps], [
            "commander-talent-navigation:home:commander_info",
            "commander-talent-navigation:commander_info:commander_talent",
            "commander-talent-navigation:commander_talent:talent_memory",
        ])

    def test_switch_requires_approval_and_fresh_unchanged_preset(self) -> None:
        runtime = FakeRuntime(page="memory", applied="Military")
        result, session, _store = self._run(runtime, "Economy")
        self.assertEqual(result.status, "deferred")
        self.assertEqual(session.input_count, 0)
        self.assertEqual(runtime.taps, [])

        changed = FakeRuntime(page="memory", applied="Military")
        changed.change_preset_on_second_capture = True
        result, session, _store = self._run(
            changed,
            "Economy",
            switch_approval=lambda observation, frame: TalentSwitchPermit("unused"),
        )
        self.assertEqual(result.status, "deferred")
        self.assertIn("CHANGED", result.reason)
        self.assertEqual(session.input_count, 0)
        self.assertEqual(changed.taps, [])

    def test_switch_requires_canonical_settlement_callback(self) -> None:
        runtime = FakeRuntime(page="memory", applied="Military")
        result, session, _store = self._run(
            runtime,
            "Economy",
            switch_approval=lambda observation, frame: TalentSwitchPermit("unsettled-switch"),
        )
        self.assertEqual(result.status, "deferred")
        self.assertEqual(result.reason, "TALENT_SWITCH_SETTLEMENT_UNAVAILABLE")
        self.assertEqual(session.input_count, 0)
        self.assertEqual(runtime.taps, [])

    def test_approved_switch_dispatches_once_and_exact_applied_successor(self) -> None:
        runtime = FakeRuntime(page="memory", applied="Military")
        outcomes = []
        result, session, _store = self._run(
            runtime,
            "Economy",
            switch_approval=lambda observation, frame: TalentSwitchPermit("approved-switch-economy"),
            switch_outcome=lambda key, status, dispatched, observation: outcomes.append((key, status, dispatched)),
        )
        self.assertEqual(result.status, "switched")
        self.assertTrue(result.verified)
        self.assertEqual(session.input_count, 1)
        self.assertEqual(runtime.taps, [("talent-memory-row:Economy:apply", "approved-switch-economy")])
        self.assertEqual(outcomes, [("approved-switch-economy", "switched", True)])

    def test_optional_real_confirmation_is_one_bounded_continuation_not_a_requirement(self):
        runtime = FakeRuntime(page="memory", applied="Military", switch_mode="confirmation")
        outcomes = []
        result, session, _store = self._run(
            runtime, "Economy", switch_approval=lambda *_: TalentSwitchPermit("switch-economy"),
            switch_outcome=lambda *args: outcomes.append(args),
        )
        self.assertTrue(result.verified)
        self.assertEqual(result.status, "switched")
        self.assertEqual(session.input_count, 2)
        self.assertEqual(runtime.taps, [("talent-memory-row:Economy:apply", "switch-economy"),
                                       ("talent-memory-confirm:Economy", "switch-economy:confirm")])
        self.assertEqual(len(outcomes), 1)

    def test_unexpected_paid_confirmation_is_not_pressed_or_retried(self):
        runtime = FakeRuntime(page="memory", applied="Military", switch_mode="paid_confirmation")
        result, session, _store = self._run(
            runtime, "Economy", switch_approval=lambda *_: TalentSwitchPermit("switch-economy"),
            switch_outcome=lambda *args: None,
        )
        self.assertFalse(result.verified)
        self.assertEqual(result.status, "unknown")
        self.assertEqual(session.input_count, 1)
        self.assertEqual(len(runtime.taps), 1)

    def test_unknown_switch_is_persistently_blocked_from_identical_retry(self) -> None:
        runtime = FakeRuntime(page="memory", applied="Military", switch_mode="unknown")
        store = FakeActionStore()
        outcomes = []

        def record(key, status, dispatched, observation):
            outcomes.append((key, status, dispatched))
            if status == "unknown":
                store.blocked = True

        first, _session, _ = self._run(
            runtime,
            "Economy",
            switch_approval=lambda observation, frame: TalentSwitchPermit("unknown-switch-economy"),
            switch_outcome=record,
            store=store,
        )
        self.assertEqual(first.status, "unknown")
        self.assertTrue(first.switch_transport_attempted)
        self.assertTrue(store.blocked)

        second, session, _ = self._run(runtime, "Economy", store=store)
        self.assertEqual(second.status, "unknown")
        self.assertEqual(second.reason, "CANONICAL_ACTION_REQUIRES_INSPECTION")
        self.assertEqual(session.input_count, 0)
        self.assertEqual(len(runtime.taps), 1)
        self.assertEqual(outcomes, [("unknown-switch-economy", "unknown", True)])


if __name__ == "__main__":
    unittest.main()
