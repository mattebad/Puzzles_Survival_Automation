"""Focused fake-based tests for the canonical runtime/perception boundaries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import os
import hashlib
import subprocess
import sys
import tempfile
import time
import unittest
import cv2
import numpy as np

from tasks.perception_bundle import NativeFrameIdentity
from tasks.semantic_ocr_crop import CropRoiRequest, OcrMode, SemanticOcrObservation
from automation_service.actions import ActionExecutor, ActionOutcome, SuccessorConstraint
from automation_service.contracts import FlowSpec, PerceptionEnvelope, SemanticActionIntent
from automation_service.overlays import OverlayRecoveryManager
from automation_service.screens import (
    CaptureCycle,
    OverlayId,
    ScreenDefinition,
    ScreenId,
    ScreenObservation,
    ScreenRouter,
    TargetBinding,
)
from automation_service.state import ActionState, BotStateManager, DispatchValidation, RunState
from automation_service.session import RuntimeSession
from automation_service.adapters import FrameSample


FLOW_ID = "BOUNDARY-FLOW"
RESET_ID = "boundary-reset"
TARGET = "button:free"

class EncodedFrame(bytes):
    @property
    def shape(self) -> tuple[int, int, int]:
        return (1280, 800, 3)


def ocr_sample() -> FrameSample:
    image = np.zeros((1280, 800, 3), dtype=np.uint8)
    ok, payload = cv2.imencode(".png", image)
    assert ok
    return FrameSample(
        "ocr",
        PerceptionEnvelope("ocr", "home", "native-800x1280", "fresh"),
        EncodedFrame(payload.tobytes()),
    )

def ocr_cycle() -> CaptureCycle:
    sample = ocr_sample()
    digest = hashlib.sha256(bytes(sample.payload)).hexdigest()
    return CaptureCycle(
        "ocr",
        digest,
        payload=sample.payload,
        captured_monotonic=1.0,
        capture_ordinal=1,
        width=800,
        height=1280,
        runtime_session_id="boundary-session",
        transport_sha256=digest,
        semantic_sha256=digest,
    )


def ocr_request_for_cycle(cycle: CaptureCycle, deadline: float) -> CropRoiRequest:
    assert cycle.width is not None and cycle.height is not None
    identity = NativeFrameIdentity(
        "fixture",
        cycle.runtime_session_id,
        cycle.capture_ordinal,
        cycle.captured_monotonic,
        cycle.transport_sha256,
        cycle.semantic_sha256,
        "native-800x1280",
        cycle.width,
        cycle.height,
    )
    return CropRoiRequest(
        identity,
        (10, 10, 30, 30),
        ocr_mode=OcrMode.UNIFORM_BLOCK,
        deadline_monotonic=deadline,
    )


@dataclass(frozen=True)
class BlockingOcrEngine:
    marker: str

    def __call__(self, _pixels: np.ndarray, _psm: int) -> str:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        Path(self.marker).write_text(f"{os.getpid()},{child.pid}", encoding="ascii")
        time.sleep(60.0)
        return ""

@dataclass(frozen=True)
class SuccessWithDescendantOcrEngine:
    marker: str

    def __call__(self, _pixels: np.ndarray, _psm: int) -> str:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        Path(self.marker).write_text(f"{os.getpid()},{child.pid}", encoding="ascii")
        return "HOME"


def positive_ocr_engine(_pixels: np.ndarray, _psm: int) -> str:
    return "HOME"


def match_home(observation: SemanticOcrObservation, _cycle: CaptureCycle) -> bool:
    return observation.text.strip().upper() == "HOME"




def exploding_ocr_matcher(_observation: SemanticOcrObservation, _cycle: CaptureCycle) -> object:
    raise LookupError("matcher")


def process_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return False
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            status = kernel32.WaitForSingleObject(handle, 0)
            if status == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            return status == 258
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, ProcessLookupError):
        return False
    if os.name != "nt":
        try:
            data = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
            fields = data[data.rfind(")") + 2 :].split()
            if fields and fields[0] in {"Z", "X"}:
                return False
        except OSError:
            pass
    return True


@dataclass
class SequenceAdapter:
    frames: list[FrameSample]
    transport_result: object = True
    transport_error: Exception | None = None

    def __post_init__(self) -> None:
        self.index = 0
        self.transports: list[SemanticActionIntent] = []
        self.state_manager: BotStateManager | None = None

    def capture(self) -> FrameSample:
        sample = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        return sample

    def execute(self, intent: SemanticActionIntent) -> object:
        self.transports.append(intent)
        if self.transport_error is not None:
            raise self.transport_error
        return self.transport_result


def frame(name: str, screen: str = "HOME", *, roi: tuple[int, int, int, int] = (10, 10, 30, 30), overlay: str | None = None, digest: str = "stable") -> FrameSample:
    return FrameSample(
        name,
        PerceptionEnvelope(name, screen.lower(), "native-800x1280", "fresh"),
        payload={"screen": screen, "roi": roi, "overlay": overlay, "digest": digest},
    )


def router() -> ScreenRouter:
    def recognize(cycle: CaptureCycle) -> ScreenObservation:
        payload = cycle.payload
        screen = ScreenId(payload["screen"])
        overlays = () if payload.get("overlay") is None else (OverlayId(payload["overlay"]),)
        targets = (
            TargetBinding(TARGET, payload["roi"], semantic_identity="free-button", stable_roi_digest=payload["digest"]),
        )
        if OverlayId.VIP_RESET in overlays:
            targets += (TargetBinding("overlay:vip-reset:close", (100, 100, 140, 140), semantic_identity="close", stable_roi_digest="close"),)
        return ScreenObservation(
            screen,
            overlays,
            cycle.frame_hash,
            0.99,
            targets,
            cycle.capture_id,
            payload["digest"],
            ("fake",),
            "recognized",
            True,
            runtime_session_id=cycle.runtime_session_id,
            capture_ordinal=cycle.capture_ordinal,
            captured_monotonic=cycle.captured_monotonic,
            width=cycle.width,
            height=cycle.height,
            transport_sha256=cycle.transport_sha256,
            semantic_sha256=cycle.semantic_sha256,
            payload_sha256=cycle.payload_sha256,
        )

    return ScreenRouter([recognize])


def manager(path: Path) -> BotStateManager:
    value = BotStateManager(path, owner_instance_id="boundary-owner")
    value.initialize_flows([FlowSpec(FLOW_ID, cadence="manual")])
    value.set_service_enabled(True, now_utc_epoch=1.0)
    value.set_flow_enabled(FLOW_ID, True, now_utc_epoch=1.0)
    return value


def intent() -> SemanticActionIntent:
    return SemanticActionIntent(
        "tap_free",
        FLOW_ID,
        "HOME",
        "HOME successor",
        target_identity=TARGET,
        flow_id=FLOW_ID,
    )

def recognized_mapping(cycle: CaptureCycle, **values: object) -> dict[str, object]:
    result: dict[str, object] = {
        "capture_id": cycle.capture_id,
        "runtime_session_id": cycle.runtime_session_id,
        "capture_ordinal": cycle.capture_ordinal,
        "captured_monotonic": cycle.captured_monotonic,
        "width": cycle.width,
        "height": cycle.height,
        "frame_sha256": cycle.frame_hash,
        "payload_sha256": cycle.payload_sha256,
        "transport_sha256": cycle.transport_sha256,
        "semantic_sha256": cycle.semantic_sha256,
        "stable_roi_digest": "stable",
    }
    result.update(values)
    return result

def complete_cycle() -> CaptureCycle:
    return CaptureCycle(
        "capture",
        "a" * 64,
        payload={"screen": "HOME"},
        captured_monotonic=1.0,
        capture_ordinal=1,
        width=800,
        height=1280,
        runtime_session_id="test-session",
        transport_sha256="b" * 64,
        semantic_sha256="c" * 64,
        stable_roi_digest="stable",
    )
def bound_observation(
    frame_hash: str,
    capture_id: str,
    ordinal: int,
    target: TargetBinding,
    stable_roi_digest: str,
) -> ScreenObservation:
    return ScreenObservation(
        ScreenId.HOME,
        (),
        frame_hash,
        0.99,
        (target,),
        capture_id,
        stable_roi_digest,
        runtime_session_id="test-session",
        capture_ordinal=ordinal,
        captured_monotonic=10.0,
        width=800,
        height=1280,
        transport_sha256=frame_hash,
        semantic_sha256=frame_hash,
        payload_sha256=frame_hash,
        recognized=True,
    )

class ScreenBoundaryTests(unittest.TestCase):
    def test_animation_hash_variance_preserves_stable_target_binding(self) -> None:
        target = TargetBinding(TARGET, (10, 10, 30, 30), "free-button", "stable")
        source = bound_observation("a" * 64, "capture-a", 1, target, "stable")
        fresh = bound_observation("b" * 64, "capture-b", 2, target, "stable")
        self.assertEqual(source.revalidate_target(fresh, TARGET), (True, "OK"))

    def test_changed_target_roi_is_stale_and_fails_closed(self) -> None:
        source_target = TargetBinding(TARGET, (10, 10, 30, 30), "free-button", "stable")
        fresh_target = TargetBinding(TARGET, (11, 10, 31, 30), "free-button", "stable")
        source = bound_observation("a" * 64, "capture-a", 1, source_target, "stable")
        fresh = bound_observation("b" * 64, "capture-b", 2, fresh_target, "stable")
        self.assertEqual(source.revalidate_target(fresh, TARGET), (False, "STALE_OR_CHANGED_TARGET_ROI"))

    def test_changed_source_roi_digest_is_stale_with_same_target_binding(self) -> None:
        target = TargetBinding(TARGET, (10, 10, 30, 30), "free-button", "stable-target")
        source = bound_observation("a" * 64, "capture-a", 1, target, "stable-source-a")
        fresh = bound_observation("b" * 64, "capture-b", 2, target, "stable-source-b")
        self.assertEqual(
            source.revalidate_target(fresh, TARGET),
            (False, "STALE_OR_CHANGED_SOURCE_ROI"),
        )
    def test_mutable_capture_payload_and_metadata_are_snapshotted(self) -> None:
        @dataclass(frozen=True)
        class FrozenEnvelope:
            values: list[int]

        envelope = FrozenEnvelope([1, 2])
        payload = {"nested": {"items": [1, 2]}}
        payload["envelope"] = envelope
        metadata = {"nested": {"value": 1}}
        cycle = CaptureCycle(
            "capture",
            "a" * 64,
            payload=payload,
            capture_ordinal=1,
            runtime_session_id="session",
            width=800,
            height=1280,
            metadata=metadata,
            transport_sha256="b" * 64,
            semantic_sha256="c" * 64,
        )
        payload["nested"]["items"].append(3)
        metadata["nested"]["value"] = 2
        envelope.values.append(3)
        self.assertEqual(cycle.payload["envelope"].values, (1, 2))
        self.assertEqual(cycle.payload["nested"]["items"], (1, 2))
        self.assertEqual(cycle.metadata["nested"]["value"], 1)
        with self.assertRaises(TypeError):
            cycle.payload["nested"]["items"] = ()
        with self.assertRaises(TypeError):
            cycle.metadata["nested"] = {}

    def test_cross_capture_observation_is_typed_unknown(self) -> None:
        def foreign(_cycle: CaptureCycle) -> ScreenObservation:
            return ScreenObservation(
                ScreenId.HOME,
                (),
                "a" * 64,
                0.99,
                (),
                "foreign-capture",
                "stable",
                recognized=True,
            )

        observation = ScreenRouter({ScreenId.HOME: foreign}).observe(
            CaptureCycle("current-capture", "a" * 64)
        )
        self.assertTrue(observation.is_unknown)
        self.assertEqual(observation.reason_code, "CROSS_CAPTURE_OBSERVATION")

    def test_contradictory_screen_matches_fail_closed(self) -> None:
        router = ScreenRouter(
            [
                ScreenDefinition(
                    ScreenId.HOME,
                    recognizer=lambda cycle: recognized_mapping(cycle, screen="HOME"),
                ),
                ScreenDefinition(
                    ScreenId.DAILY,
                    recognizer=lambda cycle: recognized_mapping(cycle, screen="DAILY"),
                ),
            ]
        )
        observation = router.observe(complete_cycle())
        self.assertTrue(observation.is_unknown)
        self.assertEqual(observation.reason_code, "CONTRADICTORY_RECOGNITION")

    def test_revalidate_rejects_digest_only_observations(self) -> None:
        target = TargetBinding(TARGET, (10, 10, 30, 30), "free-button", "stable")
        source = ScreenObservation(ScreenId.HOME, (), "a" * 64, 0.99, (target,), "capture-a", "stable", recognized=True)
        fresh = ScreenObservation(ScreenId.HOME, (), "b" * 64, 0.99, (target,), "capture-b", "stable", recognized=True)
        self.assertEqual(source.revalidate_target(fresh, TARGET), (False, "INCOMPLETE_CAPTURE_PROVENANCE"))

    def test_revalidation_reclassifies_instead_of_using_cached_target(self) -> None:
        target = TargetBinding(TARGET, (10, 10, 30, 30), "free", "stable")
        current_target = [target]
        router = ScreenRouter(
            [lambda cycle: recognized_mapping(cycle, screen="HOME", targets=current_target)],
            clock=lambda: 10.0,
        )
        source = router.observe(complete_cycle())
        fresh_cycle = replace(
            complete_cycle(), capture_id="fresh", capture_ordinal=2, captured_monotonic=2.0
        )
        router.observe(fresh_cycle)
        current_target[0] = replace(target, roi=(20, 10, 40, 30))
        valid, _, reason = router.revalidate(source, fresh_cycle, target_identity=TARGET)
        self.assertFalse(valid)
        self.assertEqual(reason, "STALE_OR_CHANGED_TARGET_ROI")

    def test_recent_ordinal_does_not_authorize_expired_capture(self) -> None:
        target = TargetBinding(TARGET, (10, 10, 30, 30), "free", "stable")
        source = bound_observation("a" * 64, "source", 1, target, "stable")
        fresh = bound_observation("b" * 64, "fresh", 2, target, "stable")
        self.assertEqual(
            source.revalidate_target(fresh, TARGET, now_monotonic=100.0),
            (False, "STALE_CAPTURE_REVALIDATION"),
        )

    def test_mapping_provenance_mismatch_is_unknown(self) -> None:
        router = ScreenRouter(
            {
                ScreenId.HOME: lambda _cycle: {
                    "screen": "HOME",
                    "frame_sha256": "f" * 64,
                }
            }
        )
        observation = router.observe(CaptureCycle("capture", "a" * 64))
        self.assertTrue(observation.is_unknown)
        self.assertEqual(observation.reason_code, "CAPTURE_PROVENANCE_MISMATCH")

    def test_contradictory_target_matches_are_unknown(self) -> None:
        target_a = {"target_identity": TARGET, "roi": (10, 10, 30, 30), "semantic_identity": "free", "stable_roi_digest": "a"}
        target_b = {"target_identity": TARGET, "roi": (11, 10, 31, 30), "semantic_identity": "free", "stable_roi_digest": "a"}
        router = ScreenRouter(
            [
                ScreenDefinition(
                    ScreenId.HOME,
                    recognizer=lambda cycle: recognized_mapping(cycle, screen="HOME", targets=(target_a,)),
                ),
                ScreenDefinition(
                    ScreenId.HOME,
                    recognizer=lambda cycle: recognized_mapping(cycle, screen="HOME", targets=(target_b,)),
                ),
            ]
        )
        observation = router.observe(complete_cycle())
        self.assertTrue(observation.is_unknown)
        self.assertEqual(observation.reason_code, "CONTRADICTORY_RECOGNITION")
    def test_ocr_is_not_called_after_deadline(self) -> None:
        router = ScreenRouter(
            [
                ScreenDefinition(
                    ScreenId.HOME,
                    ocr=positive_ocr_engine,
                    ocr_recognizer=match_home,
                    ocr_request=ocr_request_for_cycle,
                )
            ],
            clock=lambda: 10.0,
        )
        observation = router.observe(ocr_cycle(), deadline_monotonic=9.0)
        self.assertTrue(observation.is_unknown)
        self.assertEqual(observation.targets, ())

    def test_unknown_screen_is_typed_and_cached_by_capture_identity(self) -> None:
        router = ScreenRouter()
        cycle = CaptureCycle("capture", "a" * 64)
        first = router.observe(cycle)
        second = router.observe(cycle)
        self.assertIs(first, second)
        self.assertTrue(first.is_unknown)
        self.assertEqual(first.reason_code, "UNKNOWN_SCREEN")


class RuntimeBoundaryTests(unittest.TestCase):
    def _session(self, manager: BotStateManager, adapter: SequenceAdapter) -> RuntimeSession:
        session = RuntimeSession(manager, adapter, flow_id=FLOW_ID, reset_id=RESET_ID, max_inputs=2, max_actions=2)
        self.assertIsNotNone(session.claim())
        return session
    def test_denied_borrowed_session_preserves_current_owner(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                lease = state.acquire_service_lease(
                    now_utc_epoch=1.0,
                    lease_ttl_seconds=60.0,
                )
                self.assertIsNotNone(lease)
                assert lease is not None
                state.set_flow_enabled(FLOW_ID, False, now_utc_epoch=2.0)
                session = RuntimeSession(
                    state,
                    SequenceAdapter([frame("denied")]),
                    flow_id=FLOW_ID,
                    reset_id=RESET_ID,
                    owner_instance_id=state.owner_instance_id,
                    process_start_token=state.process_start_token,
                    lease_generation=lease.lease_generation,
                    utc_clock=lambda: 2.0,
                )
                self.assertIsNone(session.claim())
                session.close()
                current = state.get_service_lease()
                self.assertEqual(current.owner_instance_id, lease.owner_instance_id)
                self.assertEqual(current.process_start_token, lease.process_start_token)
                self.assertEqual(current.lease_generation, lease.lease_generation)
                self.assertEqual(current.heartbeat_at_utc, lease.heartbeat_at_utc)
                self.assertEqual(current.expires_at_utc, lease.expires_at_utc)
                self.assertEqual(current.row_version, lease.row_version)
            finally:
                state.close()

    def test_denied_acquired_session_releases_exact_lease_once(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                state.set_flow_enabled(FLOW_ID, False, now_utc_epoch=2.0)
                original_release = state.release_service_lease
                release_calls: list[dict[str, object]] = []

                def counted_release(
                    *,
                    owner_instance_id: str | None = None,
                    process_start_token: str | None = None,
                    lease_generation: int | None = None,
                ) -> bool:
                    release_calls.append(
                        {
                            "owner_instance_id": owner_instance_id,
                            "process_start_token": process_start_token,
                            "lease_generation": lease_generation,
                        }
                    )
                    return original_release(
                        owner_instance_id=owner_instance_id,
                        process_start_token=process_start_token,
                        lease_generation=lease_generation,
                    )

                state.release_service_lease = counted_release  # type: ignore[method-assign]
                session = RuntimeSession(
                    state,
                    SequenceAdapter([frame("denied")]),
                    flow_id=FLOW_ID,
                    reset_id=RESET_ID,
                    owner_instance_id=state.owner_instance_id,
                    process_start_token=state.process_start_token,
                    utc_clock=lambda: 2.0,
                )
                self.assertIsNone(session.claim())
                session.close()
                self.assertEqual(len(release_calls), 1)
                self.assertEqual(release_calls[0]["owner_instance_id"], state.owner_instance_id)
                self.assertEqual(release_calls[0]["process_start_token"], state.process_start_token)
                self.assertEqual(release_calls[0]["lease_generation"], 1)
                current = state.get_service_lease()
                self.assertIsNone(current.owner_instance_id)
                self.assertIsNone(current.process_start_token)
                self.assertEqual(current.lease_generation, 2)
            finally:
                state.close()
    def test_close_preserves_lease_when_any_run_fence_drifts(self) -> None:
        for field, value in (
            ("owner_instance_id", "wrong-owner"),
            ("process_start_token", "wrong-process"),
            ("lease_generation", 2),
            ("run_token", "wrong-run-token"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                state = BotStateManager(
                    Path(folder) / "state.sqlite3",
                    owner_instance_id="probe-owner",
                    process_start_token="probe-process",
                )
                try:
                    state.initialize_flows([FlowSpec(FLOW_ID, cadence="daily")])
                    state.set_service_enabled(True, now_utc_epoch=1.0)
                    state.set_flow_enabled(FLOW_ID, True, now_utc_epoch=1.0)
                    session = RuntimeSession(
                        state,
                        SequenceAdapter([frame("fence")]),
                        flow_id=FLOW_ID,
                        reset_id=RESET_ID,
                        owner_instance_id="probe-owner",
                        process_start_token="probe-process",
                        utc_clock=lambda: 2.0,
                    )
                    run = session.claim()
                    self.assertIsNotNone(run)
                    assert run is not None
                    setattr(session, field, value)
                    session.close()
                    current_run = state.get_run(run.run_id)
                    current_lease = state.get_service_lease()
                    self.assertIsNotNone(current_run)
                    assert current_run is not None
                    self.assertEqual(current_run.state, RunState.RUNNING)
                    self.assertEqual(current_lease.owner_instance_id, "probe-owner")
                    self.assertEqual(current_lease.process_start_token, "probe-process")
                finally:
                    state.close()

    def test_session_release_cas_rejects_retry_claimed_between_projection_and_release(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = BotStateManager(
                Path(folder) / "state.sqlite3",
                owner_instance_id="probe-owner",
                process_start_token="probe-process",
            )
            try:
                state.initialize_flows([FlowSpec(FLOW_ID, cadence="daily")])
                state.set_service_enabled(True, now_utc_epoch=1.0)
                state.set_flow_enabled(FLOW_ID, True, now_utc_epoch=1.0)
                session_a = RuntimeSession(
                    state,
                    SequenceAdapter([frame("a")]),
                    flow_id=FLOW_ID,
                    reset_id=RESET_ID,
                    owner_instance_id="probe-owner",
                    process_start_token="probe-process",
                    utc_clock=lambda: 2.0,
                )
                run_a = session_a.claim()
                self.assertIsNotNone(run_a)
                assert run_a is not None
                original_release = state.release_service_lease
                session_b_holder: list[RuntimeSession] = []

                def interleaved_release(
                    *,
                    owner_instance_id: str | None = None,
                    process_start_token: str | None = None,
                    lease_generation: int | None = None,
                    run_id: str | None = None,
                    run_token: str | None = None,
                ) -> bool:
                    if run_id == run_a.run_id and not session_b_holder:
                        session_b = RuntimeSession(
                            state,
                            SequenceAdapter([frame("b")]),
                            flow_id=FLOW_ID,
                            reset_id=RESET_ID,
                            owner_instance_id="probe-owner",
                            process_start_token="probe-process",
                            utc_clock=lambda: 2.0,
                        )
                        run_b = session_b.claim()
                        self.assertIsNotNone(run_b)
                        session_b_holder.append(session_b)
                    return original_release(
                        owner_instance_id=owner_instance_id,
                        process_start_token=process_start_token,
                        lease_generation=lease_generation,
                        run_id=run_id,
                        run_token=run_token,
                    )

                state.release_service_lease = interleaved_release  # type: ignore[method-assign]
                session_a.release(
                    outcome="BLOCKED",
                    reason="retry",
                    retry_not_before_utc=2.0,
                )
                lease_after_a = state.get_service_lease()
                self.assertEqual(lease_after_a.owner_instance_id, "probe-owner")
                self.assertEqual(lease_after_a.process_start_token, "probe-process")
                self.assertEqual(state.get_run(run_a.run_id).state, RunState.RUNNING)
                session_b_holder[0].close()
                self.assertIsNone(state.get_service_lease().owner_instance_id)
            finally:
                state.close()



    def test_adapter_cannot_relabel_an_old_session_capture(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("source")])
                session = self._session(state, adapter)
                original = session.capture()
                adapter.frames = [original]
                with self.assertRaisesRegex(RuntimeError, "requested session event"):
                    session.capture()
                self.assertEqual(adapter.transports, [])
                session.release(outcome="BLOCKED", reason="stale capture")
            finally:
                state.close()

    def test_stale_roi_blocks_without_transport(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("source", roi=(10, 10, 30, 30)), frame("pre", roi=(11, 10, 31, 30))])
                session = self._session(state, adapter)
                source = router().observe(session.capture("source"))
                executor = ActionExecutor(session, router())
                result = executor.execute(intent(), source=source)
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(result.reason, "STALE_OR_CHANGED_TARGET_ROI")
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()

    def test_changed_source_roi_same_target_blocks_without_transport(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter(
                    [
                        frame("source", digest="stable-source"),
                        frame("pre", digest="changed-source"),
                    ]
                )
                session = self._session(state, adapter)
                source = router().observe(session.capture("source"))
                result = ActionExecutor(session, router()).execute(intent(), source=source)
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(result.reason, "STALE_OR_CHANGED_SOURCE_ROI")
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()

    def test_pretransport_denials_terminalize_run_release_lease_and_allow_next_claim(self) -> None:
        """Every post-claim admission denial must leave no active ownership."""

        scenarios = (
            ("service disabled after claim", "service", "SERVICE_DISABLED"),
            ("stale target ROI", "stale-target", "STALE_OR_CHANGED_TARGET_ROI"),
            ("stale source ROI", "stale-source", "STALE_OR_CHANGED_SOURCE_ROI"),
            ("heartbeat exception", "heartbeat-exception", "HEARTBEAT_FAILED:RuntimeError"),
            ("heartbeat false", "heartbeat-false", "HEARTBEAT_FENCE_FAILED"),
            ("fence denial", "fence", "FENCE_DENIED"),
            ("reservation denial", "reservation", "RESERVATION_DENIED"),
            ("dispatch commit denial", "dispatch-commit", "DISPATCH_COMMIT_DENIED"),
        )
        active_states = {RunState.CLAIMED, RunState.RUNNING, RunState.STOP_REQUESTED, RunState.RECOVERING}
        future = 10_000_000_000.0

        for label, scenario, expected_reason in scenarios:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as folder:
                state = manager(Path(folder) / "state.sqlite3")
                try:
                    source: ScreenObservation | None = None
                    if scenario == "service":
                        class DisableOnPreDispatch(SequenceAdapter):
                            def capture(self) -> FrameSample:
                                sample = super().capture()
                                if self.index == 1:
                                    state.set_service_enabled(False, emergency_reason="test denial", now_utc_epoch=2.0)
                                return sample

                        adapter = DisableOnPreDispatch([frame("pre")])
                    elif scenario == "stale-target":
                        adapter = SequenceAdapter(
                            [
                                frame("source", roi=(10, 10, 30, 30)),
                                frame("pre", roi=(11, 10, 31, 30)),
                            ]
                        )
                    elif scenario == "stale-source":
                        adapter = SequenceAdapter(
                            [
                                frame("source", digest="stable-source"),
                                frame("pre", digest="changed-source"),
                            ]
                        )
                    else:
                        adapter = SequenceAdapter([frame("pre")])

                    session = self._session(state, adapter)
                    run_id = session.run_id
                    if scenario in {"stale-target", "stale-source"}:
                        source = router().observe(session.capture("source"))
                    if scenario == "heartbeat-exception":
                        def heartbeat_exception() -> None:
                            raise RuntimeError("heartbeat")

                        session.heartbeat = heartbeat_exception  # type: ignore[method-assign]
                    elif scenario == "heartbeat-false":
                        session.heartbeat = lambda: None  # type: ignore[method-assign]
                    elif scenario == "fence":
                        session.ensure_fence = lambda **_kwargs: DispatchValidation(False, "FENCE_DENIED")  # type: ignore[method-assign]
                    elif scenario == "reservation":
                        state.reserve_action = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
                    elif scenario == "dispatch-commit":
                        original_transition = state.transition_action

                        def deny_dispatch(
                            action_id: str,
                            state_value: object,
                            *args: object,
                            **kwargs: object,
                        ) -> object:
                            if ActionState(state_value) is ActionState.DISPATCHING:
                                return None
                            return original_transition(action_id, state_value, *args, **kwargs)

                        state.transition_action = deny_dispatch  # type: ignore[method-assign]

                    result = ActionExecutor(session, router()).execute(intent(), source=source)
                    self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                    self.assertEqual(result.reason, expected_reason)
                    self.assertFalse(result.transport_attempted)
                    self.assertEqual(adapter.transports, [])
                    if scenario == "dispatch-commit":
                        self.assertIsNotNone(result.action)
                        assert result.action is not None
                        self.assertEqual(result.action.state, ActionState.BLOCKED)
                    self.assertIsNotNone(run_id)
                    assert run_id is not None
                    persisted_run = state.get_run(run_id)
                    self.assertIsNotNone(persisted_run)
                    assert persisted_run is not None
                    self.assertNotIn(persisted_run.state, active_states)
                    self.assertIn(
                        persisted_run.state,
                        {
                            RunState.SUCCEEDED,
                            RunState.DEFERRED,
                            RunState.BLOCKED,
                            RunState.FAILED,
                            RunState.ABANDONED,
                        },
                    )
                    lease = state.get_service_lease()
                    self.assertIsNone(lease.owner_instance_id)
                    self.assertIsNone(lease.process_start_token)

                    state.set_service_enabled(True, now_utc_epoch=future)
                    next_session = RuntimeSession(
                        state,
                        SequenceAdapter([frame("next")]),
                        flow_id=FLOW_ID,
                        reset_id=RESET_ID,
                        utc_clock=lambda: future,
                        max_inputs=2,
                        max_actions=2,
                    )
                    try:
                        self.assertIsNotNone(next_session.claim())
                    finally:
                        next_session.close()
                finally:
                    state.close()

    def test_disable_generation_race_blocks_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                class DisableOnPreDispatch(SequenceAdapter):
                    def capture(self) -> FrameSample:
                        sample = super().capture()
                        if self.index == 2:
                            state.set_service_enabled(False, emergency_reason="test race", now_utc_epoch=2.0)
                        return sample

                adapter = DisableOnPreDispatch([frame("source"), frame("pre")])
                session = self._session(state, adapter)
                source = router().observe(session.capture("source"))
                result = ActionExecutor(session, router()).execute(intent(), source=source)
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()
    def test_emergency_after_dispatching_before_transport_aborts_and_releases(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                class EmergencyOnFinalCapture(SequenceAdapter):
                    session: RuntimeSession | None = None

                    def capture(self) -> FrameSample:
                        sample = super().capture()
                        if self.index == 2:
                            assert self.session is not None
                            self.session.request_emergency_stop("test pre-transport race")
                        return sample

                adapter = EmergencyOnFinalCapture([frame("pre"), frame("final")])
                session = self._session(state, adapter)
                adapter.session = session
                result = ActionExecutor(session, router()).execute(intent())

                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(result.reason, "SERVICE_DISABLED")
                self.assertFalse(result.transport_attempted)
                self.assertEqual(adapter.transports, [])
                self.assertIsNotNone(result.action)
                assert result.action is not None
                self.assertEqual(result.action.state.value, "BLOCKED")
                assert session.run_id is not None
                run = state.get_run(session.run_id)
                assert run is not None
                self.assertEqual(run.consumed_inputs, 0)
                self.assertIsNone(state.get_service_lease().owner_instance_id)

                state.set_service_enabled(True, now_utc_epoch=10_000_000_000.0)
                next_session = RuntimeSession(
                    state,
                    SequenceAdapter([frame("next")]),
                    flow_id=FLOW_ID,
                    reset_id=RESET_ID,
                    utc_clock=lambda: 10_000_000_000.0,
                    max_inputs=2,
                    max_actions=2,
                )
                try:
                    self.assertIsNotNone(next_session.claim())
                finally:
                    next_session.close()
            finally:
                state.close()


    def test_unknown_screen_blocks_without_reservation_or_transport(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("source", screen="UNKNOWN"), frame("pre", screen="UNKNOWN")])
                session = self._session(state, adapter)
                result = ActionExecutor(session, router()).execute(intent())
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()
    def test_invalid_source_releases_runtime_ownership_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("pre")])
                session = self._session(state, adapter)
                invalid_source = ScreenObservation(
                    ScreenId.HOME,
                    (),
                    "a" * 64,
                    0.99,
                    (TargetBinding(TARGET, (10, 10, 30, 30), "free-button", "stable"),),
                    "digest-only",
                    "stable",
                    recognized=True,
                )
                result = ActionExecutor(session, router()).execute(intent(), source=invalid_source)
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(result.reason, "INCOMPLETE_CAPTURE_PROVENANCE")
                self.assertEqual(adapter.transports, [])
                self.assertIsNone(state.get_service_lease().owner_instance_id)
                assert session.run_id is not None
                persisted = state.get_run(session.run_id)
                assert persisted is not None
                self.assertIn(
                    persisted.state,
                    {RunState.SUCCEEDED, RunState.DEFERRED, RunState.BLOCKED, RunState.FAILED, RunState.ABANDONED},
                )
            finally:
                state.close()

    def test_transport_exception_is_unknown_and_is_not_automatically_retried(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("source"), frame("pre"), frame("post")], transport_error=RuntimeError("adb"))
                session = self._session(state, adapter)
                source = router().observe(session.capture("source"))
                executor = ActionExecutor(session, router())
                first = executor.execute(intent(), source=source, idempotency_key="one-shot")
                second = executor.execute(intent(), source=source, idempotency_key="one-shot")
                self.assertEqual(first.outcome, ActionOutcome.UNKNOWN)
                self.assertEqual(second.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(len(adapter.transports), 1)
            finally:
                state.close()

    def test_source_changes_between_reservation_and_transport_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter(
                    [
                        frame("pre", digest="stable-source"),
                        frame("final", digest="changed-source"),
                    ]
                )
                session = self._session(state, adapter)
                result = ActionExecutor(session, router()).execute(intent())
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(result.reason, "STALE_OR_CHANGED_SOURCE_ROI")
                self.assertIsNotNone(result.action)
                self.assertEqual(result.action.state.value, "BLOCKED")
                self.assertEqual(adapter.index, 2)
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()

    def test_new_idempotency_key_cannot_redispatch_same_binding(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("same")], transport_result=False)
                session = self._session(state, adapter)
                executor = ActionExecutor(session, router())
                first = executor.execute(
                    intent(),
                    idempotency_key="binding-first",
                    expected_successor=SuccessorConstraint(ScreenId.HOME),
                )
                self.assertEqual(first.outcome, ActionOutcome.SUCCEEDED)
                self.assertIsNotNone(first.action)
                assert first.action is not None
                self.assertEqual(first.action.source_stable_roi_digest, "stable")
                self.assertTrue(first.action.binding_fingerprint)
                second = executor.execute(
                    intent(),
                    idempotency_key="binding-second",
                    expected_successor=SuccessorConstraint(ScreenId.HOME),
                )
                self.assertEqual(second.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(second.reason, "RESERVATION_DENIED")
                self.assertEqual(len(adapter.transports), 1)
            finally:
                state.close()

    def test_no_effect_rejects_retry_with_unchanged_hypothesis(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("unchanged")], transport_result=False)
                session = self._session(state, adapter)
                executor = ActionExecutor(session, router())
                first = executor.execute(
                    intent(),
                    idempotency_key="no-effect-first",
                    expected_successor=SuccessorConstraint(predicate=lambda _observation: False),
                )
                self.assertEqual(first.outcome, ActionOutcome.NO_EFFECT)
                self.assertIsNotNone(first.action)
                assert first.action is not None
                second = executor.execute(
                    intent(),
                    idempotency_key="no-effect-retry",
                    retry_of_action_id=first.action.action_id,
                    expected_successor=SuccessorConstraint(predicate=lambda _observation: False),
                )
                self.assertEqual(second.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(second.reason, "RESERVATION_DENIED")
                self.assertEqual(len(adapter.transports), 1)
            finally:
                state.close()

    def test_close_terminalizes_run_and_releases_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                session = self._session(state, SequenceAdapter([frame("source")]))
                run_id = session.run_id
                session.close()
                assert run_id is not None
                self.assertIn(state.get_run(run_id).state, {RunState.ABANDONED, RunState.BLOCKED})
                next_session = RuntimeSession(state, SequenceAdapter([frame("next")]), flow_id=FLOW_ID, reset_id=RESET_ID)
                self.assertIsNotNone(next_session.claim())
                next_session.close()
            finally:
                state.close()

    def test_manual_claim_persists_operator_identity_and_enters_running(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                session = RuntimeSession(
                    state,
                    SequenceAdapter([frame("manual")]),
                    flow_id=FLOW_ID,
                    reset_id=RESET_ID,
                    operator_request_id="operator-boundary-42",
                )
                run = session.claim()
                self.assertIsNotNone(run)
                assert run is not None
                self.assertEqual(run.state, RunState.RUNNING)
                self.assertEqual(run.occurrence_kind, "manual")
                self.assertEqual(run.occurrence_basis, "operator-boundary-42")
                self.assertEqual(state.get_flow(FLOW_ID).next_occurrence_key, 0)
                session.close()
            finally:
                state.close()

    def test_inflight_emergency_commit_failure_marks_unknown_and_releases(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                class EmergencyTransport(SequenceAdapter):
                    def execute(self, intent_value: SemanticActionIntent) -> object:
                        state.set_service_enabled(False, emergency_reason="in-flight race", now_utc_epoch=2.0)
                        return super().execute(intent_value)

                original_transition = state.transition_action

                def deny_terminal_commit(action_id: str, state_value: object, *args: object, **kwargs: object) -> object:
                    if ActionState(state_value) in {ActionState.SUCCEEDED, ActionState.NO_EFFECT}:
                        return None
                    return original_transition(action_id, state_value, *args, **kwargs)

                state.transition_action = deny_terminal_commit  # type: ignore[method-assign]
                adapter = EmergencyTransport([frame("pre"), frame("final"), frame("post")], transport_result=False)
                session = self._session(state, adapter)
                executor = ActionExecutor(session, router())
                result = executor.execute(
                    intent(),
                    expected_successor=SuccessorConstraint(ScreenId.HOME),
                )

                self.assertEqual(result.outcome, ActionOutcome.UNKNOWN)
                self.assertEqual(len(adapter.transports), 1)
                self.assertIsNotNone(result.action)
                assert result.action is not None
                persisted_action = state.get_action(result.action.action_id)
                self.assertIsNotNone(persisted_action)
                assert persisted_action is not None
                self.assertEqual(persisted_action.state, ActionState.UNKNOWN)
                assert session.run_id is not None
                persisted_run = state.get_run(session.run_id)
                self.assertIsNotNone(persisted_run)
                assert persisted_run is not None
                self.assertEqual(persisted_run.state, RunState.BLOCKED)
                self.assertIsNone(state.get_service_lease().owner_instance_id)

                second = executor.execute(intent(), expected_successor=SuccessorConstraint(ScreenId.HOME))
                self.assertEqual(second.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(len(adapter.transports), 1)
            finally:
                state.close()

    def test_heartbeat_renews_ttl_before_takeover_then_stale_generation_is_fenced(self) -> None:
        class MutableClock:
            value = 0.0

            def __call__(self) -> float:
                return self.value

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            owner_a = manager(path)
            owner_b = BotStateManager(path, owner_instance_id="boundary-owner-b")
            try:
                clock = MutableClock()
                session = RuntimeSession(
                    owner_a,
                    SequenceAdapter([frame("heartbeat")]),
                    flow_id=FLOW_ID,
                    reset_id=RESET_ID,
                    lease_ttl_seconds=60.0,
                    utc_clock=clock,
                )
                run = session.claim()
                self.assertIsNotNone(run)
                assert run is not None
                clock.value = 30.0
                renewed = session.heartbeat()
                self.assertIsNotNone(renewed)
                assert renewed is not None
                self.assertEqual(renewed.heartbeat_at_utc, 30.0)
                lease = owner_a.get_service_lease()
                self.assertEqual(lease.expires_at_utc, 90.0)

                self.assertIsNone(
                    owner_b.takeover_orphan(
                        run.run_id,
                        owner_instance_id=owner_b.owner_instance_id,
                        process_start_token=owner_b.process_start_token,
                        process_id=owner_b.process_id,
                        now_utc_epoch=61.0,
                        heartbeat_timeout_seconds=60.0,
                    )
                )
                recovered = owner_b.takeover_orphan(
                    run.run_id,
                    owner_instance_id=owner_b.owner_instance_id,
                    process_start_token=owner_b.process_start_token,
                    process_id=owner_b.process_id,
                    now_utc_epoch=91.0,
                    heartbeat_timeout_seconds=60.0,
                )
                self.assertIsNotNone(recovered)
                assert recovered is not None
                self.assertEqual(recovered.state, RunState.RECOVERING)
                clock.value = 91.0
                validation = session.validate_fence()
                self.assertFalse(validation.valid)
                self.assertIn(validation.reason, {"RUN_OWNERSHIP_MISMATCH", "SERVICE_LEASE_MISMATCH"})
                session.close()
            finally:
                owner_b.close()
                owner_a.close()

    def test_screen_ocr_positive_result_is_normalized(self) -> None:
        observation = ScreenRouter(
            [
                ScreenDefinition(
                    ScreenId.HOME,
                    ocr=positive_ocr_engine,
                    ocr_recognizer=match_home,
                    ocr_request=ocr_request_for_cycle,
                )
            ],
            callback_timeout_seconds=3.0,
        ).observe(ocr_cycle())
        self.assertFalse(observation.is_unknown)
        self.assertEqual(observation.screen, ScreenId.HOME)
        self.assertTrue(observation.recognized)

    def test_successful_ocr_drains_descendant_before_return(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / "ocr-success-worker.pid"
            observation = ScreenRouter(
                [
                    ScreenDefinition(
                        ScreenId.HOME,
                        ocr=SuccessWithDescendantOcrEngine(str(marker)),
                        ocr_recognizer=match_home,
                        ocr_request=ocr_request_for_cycle,
                    )
                ],
                callback_timeout_seconds=3.0,
            ).observe(ocr_cycle())
            self.assertFalse(observation.is_unknown)
            self.assertTrue(observation.recognized)
            self.assertTrue(marker.exists())
            worker_pid, child_pid = (int(value) for value in marker.read_text(encoding="ascii").split(","))
            self.assertFalse(process_alive(worker_pid))
            self.assertFalse(process_alive(child_pid))

    def test_blocking_ocr_times_out_unknown_and_releases_ownership(self) -> None:

        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            marker = Path(folder) / "ocr-worker.pid"
            try:
                session = self._session(state, SequenceAdapter([ocr_sample()]))
                deadlines: list[float] = []

                def request_factory(cycle: CaptureCycle, deadline: float) -> CropRoiRequest:
                    deadlines.append(deadline)
                    return ocr_request_for_cycle(cycle, deadline)


                perception = ScreenRouter(
                    [
                        ScreenDefinition(
                            ScreenId.HOME,
                            ocr=BlockingOcrEngine(str(marker)),
                            ocr_recognizer=match_home,
                            ocr_request=request_factory,
                        )
                    ],
                    callback_timeout_seconds=2.0,
                )
                result = ActionExecutor(session, perception).execute(intent())
                self.assertLessEqual(time.monotonic(), deadlines[0])
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(result.reason, "OCR_DEADLINE")
                self.assertTrue(marker.exists())
                worker_pid, child_pid = (int(value) for value in marker.read_text(encoding="ascii").split(","))
                self.assertFalse(process_alive(worker_pid))
                self.assertFalse(process_alive(child_pid))
                self.assertEqual(result.transport_attempted, False)
                self.assertEqual(len(session.adapter.transports), 0)
                self.assertIsNone(state.get_service_lease().owner_instance_id)
                assert session.run_id is not None
                persisted_run = state.get_run(session.run_id)
                self.assertIsNotNone(persisted_run)
                assert persisted_run is not None
                self.assertEqual(persisted_run.state, RunState.BLOCKED)
            finally:
                state.close()


class OverlayBoundaryTests(unittest.TestCase):
    def test_overlay_plan_returns_semantic_intent_and_enforces_successor(self) -> None:
        source = ScreenObservation(
            ScreenId.HOME,
            (OverlayId.VIP_RESET,),
            "a" * 64,
            0.99,
            (TargetBinding("overlay:vip-reset:close", (10, 10, 20, 20), "close", "close"),),
            "overlay-source",
            recognized=True,
        )
        plan = OverlayRecoveryManager().plan(source)
        assert plan is not None
        self.assertEqual(plan.intent.semantic_action, "dismiss_vip_reset")
        still_present = ScreenObservation(ScreenId.HOME, (OverlayId.VIP_RESET,), "b" * 64, 0.99, (), "post", recognized=True)
        gone = ScreenObservation(ScreenId.HOME, (), "c" * 64, 0.99, (), "post-2", recognized=True)
        self.assertFalse(plan.accepts_successor(still_present))
        self.assertTrue(plan.accepts_successor(gone))


    def _session(self, state: BotStateManager, adapter: SequenceAdapter) -> RuntimeSession:
        session = RuntimeSession(state, adapter, flow_id=FLOW_ID, reset_id=RESET_ID, max_inputs=2, max_actions=2)
        self.assertIsNotNone(session.claim())
        return session

    def test_recognizer_callback_exceptions_are_unknown_and_cached(self) -> None:
        cycle = CaptureCycle("callback", "a" * 64)

        def exploding(_cycle: CaptureCycle) -> object:
            raise RuntimeError("recognizer")

        for callback_name in ("template", "geometry", "recognizer"):
            definition = ScreenDefinition(ScreenId.HOME, **{callback_name: exploding})
            observation = ScreenRouter([definition]).observe(cycle)
            self.assertTrue(observation.is_unknown)
            self.assertEqual(observation.reason_code, "RECOGNITION_EXCEPTION:RuntimeError")
        ocr_observation = ScreenRouter(
            [
                ScreenDefinition(
                    ScreenId.HOME,
                    ocr=positive_ocr_engine,
                    ocr_request=ocr_request_for_cycle,
                    ocr_recognizer=exploding_ocr_matcher,
                )
            ]
        ).observe(ocr_cycle())
        self.assertTrue(ocr_observation.is_unknown)
        self.assertEqual(ocr_observation.reason_code, "RECOGNITION_EXCEPTION:LookupError")
        direct = ScreenRouter([exploding]).observe(cycle)
        self.assertTrue(direct.is_unknown)
        self.assertEqual(direct.reason_code, "RECOGNITION_EXCEPTION:RuntimeError")

        class ExplodingRecognizer:
            def recognize(self, _cycle: CaptureCycle, _deadline: float | None = None) -> object:
                raise LookupError("recognizer object")

        object_result = ScreenRouter([ExplodingRecognizer()]).observe(cycle)
        self.assertTrue(object_result.is_unknown)
        self.assertEqual(object_result.reason_code, "RECOGNITION_EXCEPTION:LookupError")

    def test_target_predicate_exception_blocks_without_transport(self) -> None:
        class ExplodingSource(ScreenObservation):
            def revalidate_target(self, _fresh: ScreenObservation, _identity: str) -> tuple[bool, str]:
                raise LookupError("target predicate")

        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("pre")])
                session = self._session(state, adapter)
                source = ExplodingSource(
                    ScreenId.HOME,
                    (),
                    "source" * 11,
                    0.99,
                    (TargetBinding(TARGET, (10, 10, 30, 30), "free-button", "stable"),),
                    "source",
                    recognized=True,
                )
                result = ActionExecutor(session, router()).execute(intent(), source=source)
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()

    def test_successor_predicate_exception_is_unknown_and_not_retried(self) -> None:
        def exploding(_observation: ScreenObservation) -> bool:
            raise LookupError("successor predicate")

        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = SequenceAdapter([frame("pre"), frame("post")])
                session = self._session(state, adapter)
                result = ActionExecutor(session, router()).execute(
                    intent(),
                    expected_successor=SuccessorConstraint(predicate=exploding),
                )
                self.assertEqual(result.outcome, ActionOutcome.UNKNOWN)
                self.assertEqual(len(adapter.transports), 1)
            finally:
                state.close()

    def test_overlay_policy_exception_returns_no_plan(self) -> None:
        class ExplodingPolicy:
            overlay = OverlayId.VIP_RESET
            target_identity = "overlay:vip-reset:close"

            @property
            def allowed_base_screens(self) -> tuple[ScreenId, ...]:
                raise LookupError("overlay policy")

        source = ScreenObservation(
            ScreenId.HOME,
            (OverlayId.VIP_RESET,),
            "a" * 64,
            0.99,
            (TargetBinding("overlay:vip-reset:close", (10, 10, 20, 20), "close", "close"),),
            "overlay-source",
            recognized=True,
        )
        self.assertIsNone(OverlayRecoveryManager([ExplodingPolicy()]).plan(source))

    def test_capture_exception_blocks_before_transport(self) -> None:
        class ExplodingCapture(SequenceAdapter):
            def capture(self) -> FrameSample:
                if self.index >= 0:
                    raise OSError("capture")
                return super().capture()

        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                adapter = ExplodingCapture([frame("pre")])
                session = self._session(state, adapter)
                result = ActionExecutor(session, router()).execute(intent())
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()

    def test_process_owner_token_drift_blocks_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = manager(Path(folder) / "state.sqlite3")
            try:
                lease = state.acquire_service_lease(
                    owner_instance_id="boundary-owner",
                    process_start_token="process-a",
                    process_id=state.process_id,
                    now_utc_epoch=1.0,
                )
                assert lease is not None
                adapter = SequenceAdapter([frame("pre")])
                session = RuntimeSession(
                    state,
                    adapter,
                    flow_id=FLOW_ID,
                    reset_id=RESET_ID,
                    process_start_token="process-a",
                    lease_generation=lease.lease_generation,
                    max_inputs=2,
                    max_actions=2,
                )
                self.assertIsNotNone(session.claim())
                session.process_start_token = "process-b"
                self.assertEqual(session._token_kwargs(include_run=True)["process_start_token"], "process-b")
                validation = session.validate_fence()
                self.assertFalse(validation.valid)
                self.assertEqual(validation.reason, "RUN_OWNERSHIP_MISMATCH")
                result = ActionExecutor(session, router()).execute(intent())
                self.assertEqual(result.outcome, ActionOutcome.BLOCKED)
                self.assertEqual(adapter.transports, [])
            finally:
                state.close()

if __name__ == "__main__":
    unittest.main()
