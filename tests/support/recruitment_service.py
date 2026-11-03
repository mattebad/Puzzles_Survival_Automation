"""Offline guarded-recruitment service harness: fake native runtime and service fixture."""
from __future__ import annotations

from contextlib import ExitStack, closing
from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2

from automation_service.recruitment import RecruitmentRunner, recruitment_reset
from automation_service.registry import RECRUITMENT_FLOW_ID
from automation_service.service import AutomationService
from automation_service.state import BotStateManager
from safe_action_core import SafetyStore, SQLiteSchedulerInvocationRepository
from scripts import navigation_development_boundary as boundary
from scripts import noahs_tavern_recruit_bluestacks as native
from tasks.noahs_tavern_recruit import RecruitTier
from tasks.noahs_tavern_recruit_maintenance import MAINTENANCE_TASK_ID, NoahMaintenanceState, PersistedTierState
from tasks.noahs_tavern_recruit_runtime import NoahTavernRecruitRuntimeController
from tasks.scheduler_task_result import SchedulerIdentity
from tests.support.service_stop import VirtualStop
from tests.support.tavern import NoahFixtures, ScriptedTavernRuntime, _observation


class GuardedRecruitmentRuntime(ScriptedTavernRuntime):
    def __init__(self, session, *, unresolved=False):
        super().__init__(["HOME_BASE", "BEFORE", "RESULT", "AFTER", "HOME_BASE"])
        self.session = session
        session.mkdir()
        self.events = session / "events.jsonl"
        self.max_inputs = 12
        self.input_count = 0
        self.checkpoint = None
        self.fixture = NoahFixtures()
        self.unresolved = unresolved

    def capture(self, label):
        if self.checkpoint:
            self.checkpoint()
        captured = super().capture(label)
        ok, encoded = cv2.imencode(".png", captured.frame)
        if not ok:
            raise AssertionError("offline capture could not encode PNG")
        payload = encoded.tobytes()
        path = self.session / f"{self._n:04d}-{label}.png"
        path.write_bytes(payload)
        return replace(captured, png=payload,
                       sha256=hashlib.sha256(payload).hexdigest(), path=path)

    def tap(self, source, **kwargs):
        if self.checkpoint:
            self.checkpoint()
        self.input_count += 1
        super().tap(source, **kwargs)

    def back(self, source, **kwargs):
        if self.checkpoint:
            self.checkpoint()
        self.input_count += 1
        super().back(source, **kwargs)

    def recognizer(self, frame, *, captured_monotonic=None, stale=False):
        screen = self._screen()
        if screen == "HOME_BASE":
            return _observation(screen, captured_monotonic)
        before = self.fixture.tavern()
        if screen == "BEFORE":
            obs = before
        elif screen == "RESULT":
            obs = self.fixture.result()
        else:
            obs = self.fixture.after(before)
            if self.unresolved:
                obs = replace(obs, recognized=False)
            obs = replace(obs, tiers=tuple(
                replace(item, next_eligible_timestamp=captured_monotonic + item.cooldown_duration_seconds)
                if item.cooldown_active and captured_monotonic is not None else item
                for item in obs.tiers
            ))
        # Int/Advanced are cooling independently. Fresh Basic successor is real
        # controller input; the controller, not this fixture, increments its count.
        return replace(obs, captured_monotonic=captured_monotonic)


class RecruitmentServiceCase(unittest.TestCase):
    """setUp/serve fixture shared by recruitment service tests; defines no tests."""
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", self.root / "input-lock.sqlite3"))
        self.stop = VirtualStop(1_800_000_000.0)
        self.state_path = self.root / "service.sqlite3"
        self.state = self.stack.enter_context(BotStateManager(self.state_path))
        self.maintenance_path = self.root / "maintenance.sqlite3"
        self.runner = RecruitmentRunner(adb="FORBIDDEN", serial="offline-guard", output_directory=self.root,
                                        maintenance_path=self.maintenance_path, utc_clock=lambda: self.stop.now)
        self.service = AutomationService(mode="supervised", state=self.state, recruitment_runner=self.runner)
        self.service.set_service_enabled(True)
        self.service.set_flow_enabled(RECRUITMENT_FLOW_ID, True)
        identity = SchedulerIdentity("account", "server", recruitment_reset(self.stop.now), MAINTENANCE_TASK_ID)
        maintenance = NoahMaintenanceState.for_identity(identity)
        maintenance.tiers[RecruitTier.INT] = PersistedTierState(0, self.stop.now + 86400, 86400, "deferred")
        maintenance.tiers[RecruitTier.ADV] = PersistedTierState(0, self.stop.now + 172800, 172800, "deferred")
        with closing(SafetyStore(self.maintenance_path)) as store:
            controller = NoahTavernRecruitRuntimeController(maintenance_state=maintenance,
                scheduler_identity=identity, repository=SQLiteSchedulerInvocationRepository(store))
            controller.persist_maintenance_state(now=self.stop.now)
        self.runtimes = []
        self.unresolved = False

        def connect(**kwargs):
            runtime = GuardedRecruitmentRuntime(self.root / f"session-{len(self.runtimes)}", unresolved=self.unresolved)
            self.runtimes.append(runtime)
            return runtime

        self.stack.enter_context(patch.object(native.LocalBlueStacksRuntime, "connect", side_effect=connect))
        self.stack.enter_context(patch("scripts.bluestacks_native_runtime.ADBRunner", side_effect=AssertionError("live transport forbidden")))
        self.stack.enter_context(patch.object(native, "recognize_home_zoom_source", return_value=(True, {})))
        self.stack.enter_context(patch(
            "scripts.startup_recovery.recognize_reset_popup",
            return_value={"recognized": False, "reason": "not_recognized"},
        ))
        self.stack.enter_context(patch(
            "scripts.startup_recovery.recognize_startup_surface",
            return_value={"recognized": False, "commercial_looking": False},
        ))
        self.stack.enter_context(patch.object(native, "recognize_noahs_tavern_frame",
            side_effect=lambda *a, **k: self.runtimes[-1].recognizer(*a, **k)))
        step = SimpleNamespace(disposition=SimpleNamespace(value="bind"), reason="offline-home",
                               localization=SimpleNamespace(recognized=False, zoom_identity=SimpleNamespace(value="fully_zoomed_out")))
        self.stack.enter_context(patch("scripts.home_atlas_bluestacks.BlueStacksLocalizeFirstHomeDriver",
                                      return_value=SimpleNamespace(observe=lambda frame: step)))
        self.stack.enter_context(patch.object(native.NoahTavernNavigationCanaryRoute, "_atlas_binding",
                                              return_value=(100, 300, 260, 470)))
        route_type = native.NoahTavernIntegratedRoute

        def route(runtime, **kwargs):
            kwargs["recognizer"] = runtime.recognizer
            kwargs["post_input_delay"] = 0
            return route_type(runtime, **kwargs)

        self.stack.enter_context(patch.object(native, "NoahTavernIntegratedRoute", side_effect=route))

    def serve(self, emit):
        self.service.serve(account_id="account", server_id="server", stop=self.stop,
                           emit=emit, clock=lambda: self.stop.now)
