from pathlib import Path
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import tempfile
import time
from types import SimpleNamespace
import unittest
import json
import hashlib
from unittest.mock import patch

import cv2
import numpy as np

from scripts import navigation_development_boundary as boundary
from scripts import personal_might_praise_bluestacks as route
from scripts import flow_delivery_personal_might_bluestacks as delivery
from scripts.bluestacks_native_runtime import captured_native_frame_from_png
from scripts.home_atlas_bluestacks import identity_from_captured
from scripts.navigation_development_boundary import DevelopmentSession
from scripts.startup_normalization import is_clean_home_frame
from tasks import personal_might_vision as vision
from tasks.perception_bundle import PerceptionBundleError
from tasks.runtime_identity import derive_fixed_runtime_binding, derive_resource_runtime_identity
from safe_action_core import SafetyStore
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tests.ocr_memo import install_module_memo
from tests.support.environment import requires_tesseract



def setUpModule():
    # Identical frames are replayed across tests; run real Tesseract once per unique input.
    install_module_memo()

FIXTURE = Path(__file__).parent / "fixtures/personal_might/native-home-more-20261029.png"
MENU_FIXTURE = FIXTURE.with_name("native-more-menu-20261029.png")
CAPTION_HELP_SOURCE = FIXTURE.with_name("native-more-menu-caption-help-source-20261029.png")
LEADERBOARD_FIXTURE = FIXTURE.with_name("native-leaderboard-20261029.png")
PERSONAL_MIGHT_FIXTURE = FIXTURE.with_name("native-personal-might-rank-20261029.png")
PRAISED_FIXTURE = FIXTURE.with_name("native-personal-might-praised-rewards-20261029.png")
DISABLED_FIXTURE = FIXTURE.with_name("native-personal-might-disabled-20261031.png")
FRAGMENTED_RANKINGS_FIXTURE = FIXTURE.with_name("native-more-menu-fragmented-rankings-20261031.png")


def captured(payload, *, path=FIXTURE):
    return captured_native_frame_from_png(payload, path=path, captured_monotonic=time.monotonic())


class Runtime:
    def __init__(self, root, *, changed_before=False, source_png=None, successor_png=None, immediate_png=None, capture_pngs=None, wall_clock=None):
        self.session = root
        root.mkdir(parents=True, exist_ok=True)
        self.ordinal = 0
        self.taps = []
        self.changed_before = changed_before
        self.source_png = FIXTURE.read_bytes() if source_png is None else source_png
        self.successor_png = successor_png
        self.immediate_png = immediate_png
        self.capture_pngs = capture_pngs
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))

    def event(self, kind, **values):
        with (self.session / "events.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps({"type": kind, "timestamp": self.wall_clock().isoformat(), **values}) + "\n")

    def capture(self, label):
        self.ordinal += 1
        payload = self.source_png
        if self.capture_pngs is not None:
            payload = self.capture_pngs[self.ordinal - 1]
        elif self.ordinal > 2 and self.successor_png is not None:
            payload = self.successor_png
        elif self.ordinal == 2 and self.immediate_png is not None:
            payload = self.immediate_png
        elif self.ordinal > 2 or (self.changed_before and self.ordinal == 2):
            payload = cv2.imencode(".png", np.zeros((1280, 800, 3), dtype=np.uint8))[1].tobytes()
        path = self.session / f"{self.ordinal}-{label}.png"
        path.write_bytes(payload)
        frame = captured(payload, path=path)
        self.event("capture", label=label, path=str(path), sha256=frame.sha256, captured_monotonic=frame.captured_monotonic)
        return frame

    def tap(self, before, **kwargs):
        self.taps.append(dict(kwargs))
        box = kwargs["target_roi"]
        self.event("dispatch", source_sha256=before.sha256, execute=True, action_class=kwargs.pop("action_class", "navigation"), consequential=kwargs.pop("consequential", False), point=[(box[0] + box[2]) // 2, (box[1] + box[3]) // 2], **kwargs)

    def reconcile(self, action_key, status, post, reason):
        self.event("reconcile", action_key=action_key, status=status, post_sha256=post.sha256, post_path=str(post.path), reason=reason)

    def measure_foreground_package(self):
        return "com.global.ztmslg"


def original_unresolved(root, store, *, successor_png=None, canonical=False):
    binding = derive_fixed_runtime_binding("emulator-5554", ACTIVE_RUNTIME_PROFILE_ID, "com.global.ztmslg", "primary-login-slot-v1")
    identity = derive_resource_runtime_identity(binding, datetime.now(timezone.utc))
    runtime = Runtime(root / "original", source_png=PERSONAL_MIGHT_FIXTURE.read_bytes(), successor_png=PRAISED_FIXTURE.read_bytes() if successor_png is None else successor_png)
    with DevelopmentSession(owner="personal-original", invocation_id="original", session_directory=root / "original-session", max_inputs=8) as session:
        store.acquire_lease(session.owner, time.time(), 60)
        with patch.object(route.PersonalMightPraiseBoundary, "_praised", return_value=False):
            result = route.PersonalMightPraiseBoundary(session=session, runtime=runtime, store=store, identity=identity, validate_identity=lambda: None, settle_seconds=0).execute()
        store.release_lease(session.owner, time.time())
    record = {**result, "flow_id": delivery.FLOW_ID, "session_directory": str(runtime.session), "runtime_identity": asdict(identity), "events_path": "events.jsonl"}
    if canonical:
        backend = record.pop("runtime_identity")
        record.update(backend_identity=backend, task_id="personal_might_praise", runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, time_basis="utc", reset_id="game-day-" + identity.reset_start_utc[:10])
    (runtime.session / ("personal-might-result.json" if canonical else "flow-delivery-result.json")).write_text(json.dumps(record), encoding="utf-8")
    return binding, identity, record, runtime.session


def save_delivery(runtime, result, identity, *, initial_png, topology):
    initial = runtime.session / "0000-initial.png"
    initial.write_bytes(initial_png)
    initial_sha = hashlib.sha256(initial_png).hexdigest()
    trace = {"trace_count": 1, "read_only": True, "input_authority": False, "flow_id": delivery.FLOW_ID, "proof_topology": topology, "initial_frame_sha256": initial_sha, "invocation_id": "retained-test", "transport_count": len(runtime.taps), "praise_transport_calls": result.get("praise_transport_calls", 0)}
    if topology == "composite":
        trace.update(source_session=result["source_session"], recovery_session=str(runtime.session), source_praise_transport_calls=1, source_proof=result["source_proof"])
    record = {**result, "flow_id": delivery.FLOW_ID, "session_directory": str(runtime.session), "input_count": len(runtime.taps), "max_inputs": 8, "runtime_identity": asdict(identity), "proof_topology": topology, "causal_trace_count": 1, "causal_trace": trace, "causal_trace_path": "causal-trace.json", "events_path": "events.jsonl", "initial_frame_sha256": initial_sha, "initial_observation": {"frame_path": initial.name, "frame_sha256": initial_sha, "invocation_id": "retained-test", "device_state": "device", "foreground_package": "com.global.ztmslg", "native_width": 800, "native_height": 1280}}
    (runtime.session / "causal-trace.json").write_text(json.dumps(trace), encoding="utf-8")
    (runtime.session / "flow-delivery-result.json").write_text(json.dumps(record), encoding="utf-8")
    return record


def no_work_delivery(root):
    """Synthetic retained events replay real native fixtures; never live evidence."""
    runtime = Runtime(root)
    binding = derive_fixed_runtime_binding("emulator-5554", ACTIVE_RUNTIME_PROFILE_ID, "com.global.ztmslg", "primary-login-slot-v1")
    identity = derive_resource_runtime_identity(binding, datetime.now(timezone.utc))
    from tasks.personal_might_praise import personal_might_daily_key
    key = personal_might_daily_key(runtime_scope=identity.runtime_scope, account_id=identity.account_id, server_id=identity.server_id, reset_id=identity.reset_id)
    rows = [(FIXTURE, MENU_FIXTURE, vision.MORE_TARGET, (712, 1240, 765, 1263)), (MENU_FIXTURE, LEADERBOARD_FIXTURE, vision.RANKINGS_TARGET, (624, 1098, 668, 1117)), (LEADERBOARD_FIXTURE, PRAISED_FIXTURE, vision.CHECK_TARGET, (612, 267, 687, 288)), (PRAISED_FIXTURE, LEADERBOARD_FIXTURE, "personal-might-back", (47, 2, 128, 61)), (LEADERBOARD_FIXTURE, FIXTURE, "leaderboard-back", (47, 2, 128, 61))]
    for ordinal, (before, after, target, roi) in enumerate(rows):
        runtime.source_png = before.read_bytes()
        runtime.capture_pngs = None
        runtime.ordinal = len([row for row in delivery._events(root) if row["type"] == "capture"])
        def frame(label, fixture):
            runtime.ordinal += 1
            file = root / f"{runtime.ordinal}-{label}.png"
            file.write_bytes(fixture.read_bytes())
            native = captured(file.read_bytes(), path=file)
            runtime.event("capture", label=label, path=str(file), sha256=native.sha256, captured_monotonic=native.captured_monotonic)
            return native
        source = frame("immediate-before", before)
        action = f"navigation-{ordinal}"
        runtime.tap(source, target_identity=target, target_roi=roi, action_key=action)
        post = frame("immediate-post", after)
        runtime.reconcile(action, "confirmed", post, "recognized native fixture successor")
        if target == vision.CHECK_TARGET:
            frame("personal-might-already-praised", PRAISED_FIXTURE)
    result = {"status": "completed", "terminal_home_verified": True, "journal_status": "confirmed", "effect_reconciliation_required": False, "praise_transport_calls": 0, "no_work": True, "action_id": "previous-confirmed-action", "action_key": key, "successor_frame": str(post.path), "successor_sha256": post.sha256}
    return runtime, save_delivery(runtime, result, identity, initial_png=FIXTURE.read_bytes(), topology="continuous")


class PersonalMightNativeTests(unittest.TestCase):
    @requires_tesseract
    def test_native_fragmented_rankings_caption_still_binds_current_trophy_body(self):
        original = cv2.imread(str(FRAGMENTED_RANKINGS_FIXTURE))
        for defect in (None, "caption", "trophy"):
            with self.subTest(defect=defect):
                pixels = original.copy()
                if defect == "caption":
                    pixels[1140:1175, 595:700] = 0
                elif defect == "trophy":
                    pixels[1080:1137, 600:700] = 0
                frame = captured(cv2.imencode(".png", pixels)[1].tobytes())
                source = {"source_frame": identity_from_captured(frame, session_id="native-fragmented-rankings", ordinal=1), "source_png": frame.png}
                target = vision.bind_more_rankings(frame.frame, **source, home_is_clean=is_clean_home_frame)
                if defect is None:
                    self.assertIsNotNone(target)
                    self.assertEqual(target.target_identity, vision.RANKINGS_TARGET)
                    self.assertLess(target.target_roi[3], 1140)
                else:
                    self.assertIsNone(target)

    @requires_tesseract
    def test_public_no_work_validator_reads_only_and_claims_zero_new_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _runtime, _record = no_work_delivery(root)
            before = {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in root.iterdir() if file.is_file()}
            with patch.object(delivery.LocalBlueStacksRuntime, "connect", side_effect=AssertionError("validator cannot connect")), patch.object(boundary, "open_canonical_action_store", side_effect=AssertionError("validator cannot open a store")):
                result = delivery.verify_personal_might({"session_directory": str(root)}, {}, {})
            self.assertEqual(result["status"], "verified", result.get("reason"))
            self.assertEqual(result["praise_transport_calls"], 0)
            self.assertFalse(result["current_effect_verified"])
            self.assertFalse(result["source_effect_verified"])
            self.assertFalse(result["input_authority"])
            self.assertEqual(before, {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in root.iterdir() if file.is_file()})

    @requires_tesseract
    def test_public_validator_rejects_false_count_gold_no_work_and_wrong_input(self):
        for defect in ("praise_count", "gold_no_work", "unresolved_nav", "wrong_point", "stale_source", "malformed_initial"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _runtime, record = no_work_delivery(root)
                events = delivery._events(root)
                if defect == "praise_count":
                    record["praise_transport_calls"] = 1
                    (root / "flow-delivery-result.json").write_text(json.dumps(record), encoding="utf-8")
                elif defect == "gold_no_work":
                    gray = next(row for row in events if row.get("label") == "personal-might-already-praised")
                    Path(gray["path"]).write_bytes(PERSONAL_MIGHT_FIXTURE.read_bytes())
                    gray["sha256"] = hashlib.sha256(PERSONAL_MIGHT_FIXTURE.read_bytes()).hexdigest()
                elif defect == "unresolved_nav":
                    next(row for row in events if row["type"] == "reconcile")["status"] = "unresolved"
                elif defect == "stale_source":
                    source = next(row for row in events if row["type"] == "capture")
                    next(row for row in events if row["type"] == "dispatch")["timestamp"] = (delivery._utc(source["timestamp"]) + timedelta(seconds=31)).isoformat()
                elif defect == "malformed_initial":
                    (root / "0000-initial.png").write_bytes(b"")
                else:
                    next(row for row in events if row["type"] == "dispatch")["point"] = [10, 10]
                (root / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")
                result = delivery.verify_personal_might({"session_directory": str(root)}, {}, {})
                self.assertEqual(result["status"], "evidence_required")
                self.assertFalse(result["input_authority"])

    def test_native_disabled_state_and_rewards_require_current_rank_1_identity(self):
        frame = captured(PRAISED_FIXTURE.read_bytes(), path=PRAISED_FIXTURE)
        source = {"source_frame": identity_from_captured(frame, session_id="native-praise-result", ordinal=5), "source_png": frame.png}
        self.assertTrue(vision.personal_might_praised(frame.frame, **source))
        self.assertEqual(set(vision.praise_reward_toasts(frame.frame, **source)), {10, 30})
        self.assertIsNone(vision.bind_personal_might_praise(frame.frame, **source))
        no_toast = frame.frame.copy()
        no_toast[250:420] = cv2.imread(str(PERSONAL_MIGHT_FIXTURE))[250:420]
        pixels = captured(cv2.imencode(".png", no_toast)[1].tobytes())
        independent = {"source_frame": identity_from_captured(pixels, session_id="persistent-gray", ordinal=1), "source_png": pixels.png}
        self.assertTrue(vision.personal_might_praised(pixels.frame, **independent))
        self.assertEqual(vision.praise_reward_toasts(pixels.frame, **independent), ())
        negative = cv2.cvtColor(cv2.cvtColor(frame.frame, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        gray = captured(cv2.imencode(".png", negative)[1].tobytes())
        self.assertFalse(vision.personal_might_praised(gray.frame, source_frame=identity_from_captured(gray, session_id="global-desaturation", ordinal=1), source_png=gray.png))

    @requires_tesseract
    def test_gold_to_disabled_post_confirms_one_praise_after_two_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding = derive_fixed_runtime_binding("emulator-5554", ACTIVE_RUNTIME_PROFILE_ID, "com.global.ztmslg", "primary-login-slot-v1")
            identity = derive_resource_runtime_identity(binding, datetime.now(timezone.utc))
            store = SafetyStore(root / "actions.sqlite3")
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                runtime = Runtime(root / "runtime", source_png=PERSONAL_MIGHT_FIXTURE.read_bytes(), successor_png=PRAISED_FIXTURE.read_bytes())
                with DevelopmentSession(owner="personal-praise", invocation_id="positive", session_directory=root / "session", max_inputs=8) as session:
                    store.acquire_lease(session.owner, time.time(), 60)
                    result = route.PersonalMightPraiseBoundary(session=session, runtime=runtime, store=store, identity=identity, validate_identity=lambda: None, settle_seconds=0).execute()
                    self.assertEqual(result["status"], "confirmed")
                    self.assertEqual(result["journal_status"], "confirmed")
                    self.assertEqual(result["praise_transport_calls"], 1)
                    self.assertEqual(len(result["praise_result_frames"]), 2)
                    self.assertEqual(result["successor_sha256"], hashlib.sha256(Path(result["successor_frame"]).read_bytes()).hexdigest())
                    self.assertEqual(len(runtime.taps), 1)
                    self.assertFalse(store.has_action_block())
                    store.release_lease(session.owner, time.time())
            store.close()

    @requires_tesseract
    def test_linked_recovery_confirms_only_original_action_then_two_back_home(self):
        self._assert_linked_recovery()

    @requires_tesseract
    def test_canonical_source_recovery_uses_original_gray_pair_without_reward_toasts(self):
        self._assert_linked_recovery(canonical=True, successor_png=DISABLED_FIXTURE.read_bytes())

    def _assert_linked_recovery(self, *, canonical=False, successor_png=None):
        disabled_png = PRAISED_FIXTURE.read_bytes() if successor_png is None else successor_png
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SafetyStore(root / "actions.sqlite3")
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                binding, old_identity, record, original = original_unresolved(root, store, canonical=canonical, successor_png=disabled_png)
                original_result = original / ("personal-might-result.json" if canonical else "flow-delivery-result.json")
                original_bytes = original_result.read_bytes()
                future = datetime.now(timezone.utc) + timedelta(seconds=601)
                identity = derive_resource_runtime_identity(binding, future)
                payloads = [disabled_png] * 3 + [LEADERBOARD_FIXTURE.read_bytes()] * 2 + [FIXTURE.read_bytes()]
                runtime = Runtime(root / "recovery", capture_pngs=payloads, wall_clock=lambda: future + timedelta(seconds=runtime.ordinal))
                with DevelopmentSession(owner="personal-recovery", invocation_id="recovery", session_directory=root / "recovery-session", max_inputs=8) as session:
                    result = delivery.reconcile_personal_might(session=session, runtime=runtime, store=store, identity=identity, binding=binding, validate_identity=lambda: delivery._validate_identity(identity, binding, future), source_session=original)
                    self.assertEqual(result["journal_status"], "confirmed")
                    self.assertEqual(result["praise_transport_calls"], 0)
                    self.assertEqual(session.input_count, 0)
                    store.acquire_lease(session.owner, time.time(), 60)
                    home = route.return_home(session=session, runtime=runtime, settle_seconds=0)
                    self.assertTrue(home["terminal_home_verified"])
                    self.assertEqual(session.input_count, 2)
                    self.assertEqual([tap["target_identity"] for tap in runtime.taps], ["personal-might-back", "leaderboard-back"])
                    self.assertEqual(store.get_action(record["action_id"])["final_status"], "confirmed")
                    store.release_lease(session.owner, time.time())
                composite = {**result, **home}
                save_delivery(runtime, composite, identity, initial_png=disabled_png, topology="composite")
                verification = delivery.verify_personal_might({"session_directory": str(runtime.session)}, {}, {})
                self.assertEqual(verification["status"], "verified", verification.get("reason"))
                self.assertFalse(verification["current_effect_verified"])
                self.assertTrue(verification["source_effect_verified"])
                self.assertEqual(original_result.read_bytes(), original_bytes)
                reconciled = [event for event in delivery._events(runtime.session) if event["type"] == "reconcile"]
                self.assertEqual(len(reconciled), 2)
                self.assertTrue(all(event["action_key"] != record["action_key"] for event in reconciled))
                repeat_payloads = [disabled_png] * 4 + [LEADERBOARD_FIXTURE.read_bytes()] * 2 + [FIXTURE.read_bytes()]
                repeat = Runtime(root / "repeat", capture_pngs=repeat_payloads)
                with DevelopmentSession(owner="personal-repeat", invocation_id="confirmed-day", session_directory=root / "repeat-session", max_inputs=8) as session:
                    store.acquire_lease(session.owner, time.time(), 60)
                    executor = route.PersonalMightPraiseBoundary(session=session, runtime=repeat, store=store, identity=identity, validate_identity=lambda: delivery._validate_identity(identity, binding, future), settle_seconds=0)
                    no_work = route.run(session=session, runtime=repeat, settle_seconds=0, praise_boundary=executor)
                    self.assertEqual(no_work["status"], "completed")
                    self.assertTrue(no_work["terminal_home_verified"])
                    self.assertTrue(no_work["no_work"])
                    self.assertEqual(no_work["praise_transport_calls"], 0)
                    self.assertEqual(session.terminal_status, "completed")
                    self.assertEqual(session.input_count, 2)
                    self.assertTrue(all(tap["target_identity"] != "personal-might-praise" for tap in repeat.taps))
                    store.release_lease(session.owner, time.time())
            store.close()

    @requires_tesseract
    def test_recovery_bad_source_or_canonical_epoch_leaves_fence_and_zero_inputs(self):
        for defect in ("source_sha", "duplicate_dispatch", "canonical_epoch", "current_gold", "one_gray", "duplicate_gray", "current_only_gray", "ambiguous_result"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                store = SafetyStore(root / "actions.sqlite3")
                with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                    binding, identity, record, original = original_unresolved(root, store)
                    if defect == "source_sha":
                        record["immediate_sha256"] = "f" * 64
                        (original / "flow-delivery-result.json").write_text(json.dumps(record), encoding="utf-8")
                    elif defect == "duplicate_dispatch":
                        events = delivery._events(original)
                        dispatch = next(event for event in events if event["type"] == "dispatch")
                        with (original / "events.jsonl").open("a", encoding="utf-8") as output:
                            output.write(json.dumps(dispatch) + "\n")
                    elif defect == "canonical_epoch":
                        store.connection.execute("UPDATE actions SET input_attempt_at=? WHERE action_id=?", (time.time() + 86400, record["action_id"]))
                    elif defect in {"one_gray", "duplicate_gray", "current_only_gray"}:
                        frames = record["praise_result_frames"]
                        record["praise_result_frames"] = frames[:1] if defect == "one_gray" else [frames[0], frames[0]] if defect == "duplicate_gray" else []
                        (original / "flow-delivery-result.json").write_text(json.dumps(record), encoding="utf-8")
                    elif defect == "ambiguous_result":
                        (original / "personal-might-result.json").write_text(json.dumps(record), encoding="utf-8")
                    runtime = Runtime(root / "recovery", source_png=PERSONAL_MIGHT_FIXTURE.read_bytes() if defect == "current_gold" else PRAISED_FIXTURE.read_bytes())
                    with DevelopmentSession(owner="personal-recovery", invocation_id="negative", session_directory=root / "recovery-session", max_inputs=8) as session:
                        with self.assertRaises((ValueError, RuntimeError)):
                            delivery.reconcile_personal_might(session=session, runtime=runtime, store=store, identity=identity, binding=binding, validate_identity=lambda: None, source_session=original)
                        self.assertEqual(session.input_count, 0)
                        self.assertEqual(runtime.taps, [])
                        self.assertEqual(store.get_action(record["action_id"])["final_status"], "unresolved")
                store.close()

    @requires_tesseract
    def test_native_disabled_antialias_requires_rank_identity_finger_and_cuff(self):
        pixels = cv2.imread(str(DISABLED_FIXTURE))
        for defect in (None, "cuff", "finger", "rank", "desaturation"):
            with self.subTest(defect=defect):
                modified = pixels.copy()
                if defect == "cuff":
                    modified[183:201, 707:713] = 140
                elif defect == "finger":
                    modified[172:203, 715:738] = 140
                elif defect == "rank":
                    modified[160:200, 80:115] = 0
                elif defect == "desaturation":
                    modified = cv2.cvtColor(cv2.cvtColor(modified, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
                frame = captured(cv2.imencode(".png", modified)[1].tobytes())
                source = {"source_frame": identity_from_captured(frame, session_id="native-disabled-antialias", ordinal=1), "source_png": frame.png}
                self.assertEqual(vision.personal_might_praised(frame.frame, **source), defect is None)
                self.assertIsNone(vision.bind_personal_might_praise(frame.frame, **source))
                if defect is None:
                    self.assertEqual(vision.praise_reward_toasts(frame.frame, **source), ())

    def test_personal_recovery_without_original_session_stops_before_runtime(self):
        from scripts import pnsctl
        with patch.object(delivery.LocalBlueStacksRuntime, "connect", side_effect=AssertionError("runtime must not connect")) as connect:
            with self.assertRaises(pnsctl.OperatorError):
                pnsctl.development_session_run_flow(delivery.FLOW_ID, live=True, yes=True, max_inputs=8, recovery_only=True)
            connect.assert_not_called()

    def test_native_rank_1_thumb_requires_exact_header_medal_and_unique_body(self):
        frame = captured(PERSONAL_MIGHT_FIXTURE.read_bytes(), path=PERSONAL_MIGHT_FIXTURE)
        identity = identity_from_captured(frame, session_id="native-rank-1-thumb", ordinal=1)
        source = {"source_frame": identity, "source_png": frame.png}
        self.assertTrue(vision.is_personal_might(frame.frame, **source))
        target = vision.bind_personal_might_praise(frame.frame, **source)
        self.assertIsNotNone(target)
        self.assertEqual(target.target_roi, (701, 167, 741, 207))
        self.assertIs(target.source_frame, identity)
        negatives = []
        for missing in ((180, 0, 650, 80), (89, 168, 119, 206), (695, 155, 750, 218)):
            changed = frame.frame.copy()
            x0, y0, x1, y1 = missing
            changed[y0:y1, x0:x1] = 0
            negatives.append(changed)
        blank_circle = frame.frame.copy()
        cv2.circle(blank_circle, (721, 187), 20, (0, 190, 255), -1)
        negatives.append(blank_circle)
        duplicate = frame.frame.copy()
        duplicate[274:324, 696:746] = frame.frame[162:212, 696:746]
        negatives.append(duplicate)
        wrong_row = duplicate.copy()
        wrong_row[155:218, 695:750] = 0
        negatives.append(wrong_row)
        for index, pixels in enumerate(negatives):
            with self.subTest(index=index):
                changed = captured(cv2.imencode(".png", pixels)[1].tobytes())
                self.assertIsNone(vision.bind_personal_might_praise(changed.frame, source_frame=identity_from_captured(changed, session_id="native-thumb-negative", ordinal=1), source_png=changed.png))

    def test_current_visible_back_arrow_is_bound_on_both_native_pages(self):
        for fixture, personal_page in ((PERSONAL_MIGHT_FIXTURE, True), (LEADERBOARD_FIXTURE, False)):
            frame = captured(fixture.read_bytes(), path=fixture)
            source = {"source_frame": identity_from_captured(frame, session_id="current-page-back", ordinal=1), "source_png": frame.png}
            target = vision.bind_back(frame.frame, **source, personal_page=personal_page)
            self.assertIsNotNone(target)
            self.assertEqual(target.target_roi, (47, 2, 128, 61))
            self.assertIsNone(vision.bind_back(frame.frame, **source, personal_page=not personal_page))
            missing = frame.frame.copy()
            missing[0:90, 0:180] = 0
            erased = captured(cv2.imencode(".png", missing)[1].tobytes())
            self.assertIsNone(vision.bind_back(erased.frame, source_frame=identity_from_captured(erased, session_id="missing-back", ordinal=1), source_png=erased.png, personal_page=personal_page))

    @requires_tesseract
    def test_one_fenced_praise_unknown_persists_and_blocks_next_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding = derive_fixed_runtime_binding("emulator-5554", ACTIVE_RUNTIME_PROFILE_ID, "com.global.ztmslg", "primary-login-slot-v1")
            identity = derive_resource_runtime_identity(binding, datetime.now(timezone.utc))
            validate = lambda: delivery._validate_identity(identity, binding, datetime.now(timezone.utc))
            store = SafetyStore(root / "actions.sqlite3")
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                runtime = Runtime(root, source_png=PERSONAL_MIGHT_FIXTURE.read_bytes())
                with DevelopmentSession(owner="personal-praise", invocation_id="first", session_directory=root / "session-one", max_inputs=8) as session:
                    store.acquire_lease(session.owner, time.time(), 60)
                    result = route.PersonalMightPraiseBoundary(session=session, runtime=runtime, store=store, identity=identity, validate_identity=validate, settle_seconds=0).execute()
                    self.assertEqual(result["status"], "unresolved")
                    self.assertEqual(result["journal_status"], "unresolved")
                    self.assertTrue(result["effect_reconciliation_required"])
                    self.assertEqual(result["praise_transport_calls"], 1)
                    self.assertEqual(session.input_count, 1)
                    self.assertEqual(len(runtime.taps), 1)
                    self.assertEqual(runtime.taps[0]["target_roi"], (701, 167, 741, 207))
                    self.assertTrue(all(Path(path).is_file() for path in result["praise_result_frames"]))
                    store.release_lease(session.owner, time.time())
                store.close()
                store = SafetyStore(root / "actions.sqlite3")
                second = Runtime(root, source_png=PERSONAL_MIGHT_FIXTURE.read_bytes())
                with DevelopmentSession(owner="personal-praise", invocation_id="second", session_directory=root / "session-two", max_inputs=8) as session:
                    self.assertTrue(store.has_action_block())
                    retry = route.PersonalMightPraiseBoundary(session=session, runtime=second, store=store, identity=identity, validate_identity=validate, settle_seconds=0).execute()
                    self.assertEqual(retry["action_key"], result["action_key"])
                    self.assertEqual(retry["journal_status"], "unresolved")
                    self.assertEqual(retry["praise_transport_calls"], 0)
                    self.assertEqual(session.input_count, 0)
                    self.assertEqual(second.ordinal, 0)
                    self.assertEqual(second.taps, [])
            store.close()

    @requires_tesseract
    def test_changed_immediate_thumb_never_reaches_praise_input_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding = derive_fixed_runtime_binding("emulator-5554", ACTIVE_RUNTIME_PROFILE_ID, "com.global.ztmslg", "primary-login-slot-v1")
            identity = derive_resource_runtime_identity(binding, datetime.now(timezone.utc))
            store = SafetyStore(root / "actions.sqlite3")
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                runtime = Runtime(root, source_png=PERSONAL_MIGHT_FIXTURE.read_bytes(), changed_before=True)
                with DevelopmentSession(owner="personal-praise", invocation_id="changed", session_directory=root / "session", max_inputs=8) as session:
                    store.acquire_lease(session.owner, time.time(), 60)
                    result = route.PersonalMightPraiseBoundary(session=session, runtime=runtime, store=store, identity=identity, validate_identity=lambda: None, settle_seconds=0).execute()
                    self.assertEqual(result["praise_transport_calls"], 0)
                    self.assertEqual(session.input_count, 0)
                    self.assertEqual(runtime.taps, [])
                    self.assertIsNone(store.get_action_by_key(result["action_key"]))
                    store.release_lease(session.owner, time.time())
            store.close()

    @requires_tesseract
    def test_valid_moved_immediate_thumb_fails_canonical_p_to_i_guard(self):
        source = cv2.imread(str(PERSONAL_MIGHT_FIXTURE))
        shifted = source.copy()
        shifted[155:218, 695:750] = 0
        shifted[162:212, 698:748] = source[162:212, 696:746]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding = derive_fixed_runtime_binding("emulator-5554", ACTIVE_RUNTIME_PROFILE_ID, "com.global.ztmslg", "primary-login-slot-v1")
            identity = derive_resource_runtime_identity(binding, datetime.now(timezone.utc))
            store = SafetyStore(root / "actions.sqlite3")
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                runtime = Runtime(root, source_png=PERSONAL_MIGHT_FIXTURE.read_bytes(), immediate_png=cv2.imencode(".png", shifted)[1].tobytes())
                with DevelopmentSession(owner="personal-praise", invocation_id="moved", session_directory=root / "session", max_inputs=8) as session:
                    store.acquire_lease(session.owner, time.time(), 60)
                    result = route.PersonalMightPraiseBoundary(session=session, runtime=runtime, store=store, identity=identity, validate_identity=lambda: None, settle_seconds=0).execute()
                    self.assertEqual(result["reason"], "TARGET_ROI_CHANGED")
                    self.assertEqual(result["journal_status"], "cancelled")
                    self.assertEqual(result["praise_transport_calls"], 0)
                    self.assertEqual(session.input_count, 0)
                    self.assertEqual(runtime.taps, [])
                    store.release_lease(session.owner, time.time())
            store.close()

    @requires_tesseract
    def test_immediate_capture_with_proposal_timestamp_stops_before_policy_issue(self):
        class SameTimestampRuntime(Runtime):
            def capture(self, label):
                result = super().capture(label)
                if self.ordinal == 1:
                    self.proposal_timestamp = result.captured_monotonic
                elif self.ordinal == 2:
                    return captured_native_frame_from_png(result.png, path=result.path, captured_monotonic=self.proposal_timestamp)
                return result

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding = derive_fixed_runtime_binding("emulator-5554", ACTIVE_RUNTIME_PROFILE_ID, "com.global.ztmslg", "primary-login-slot-v1")
            identity = derive_resource_runtime_identity(binding, datetime.now(timezone.utc))
            store = SafetyStore(root / "actions.sqlite3")
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                runtime = SameTimestampRuntime(root, source_png=PERSONAL_MIGHT_FIXTURE.read_bytes())
                with DevelopmentSession(owner="personal-praise", invocation_id="same-time", session_directory=root / "session", max_inputs=8) as session:
                    store.acquire_lease(session.owner, time.time(), 60)
                    result = route.PersonalMightPraiseBoundary(session=session, runtime=runtime, store=store, identity=identity, validate_identity=lambda: None, settle_seconds=0).execute()
                    self.assertEqual(result["reason"], "personal_might_praise_immediate_not_newer")
                    self.assertEqual(result["praise_transport_calls"], 0)
                    self.assertEqual(session.input_count, 0)
                    self.assertEqual(runtime.taps, [])
                    self.assertIsNone(store.get_action_by_key(result["action_key"]))
                    store.release_lease(session.owner, time.time())
            store.close()

    def test_identity_reset_and_expiry_remain_bound_to_fixed_slot(self):
        binding = derive_fixed_runtime_binding("emulator-5554", ACTIVE_RUNTIME_PROFILE_ID, "com.global.ztmslg", "primary-login-slot-v1")
        now = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
        identity = derive_resource_runtime_identity(binding, now)
        delivery._validate_identity(identity, binding, now)
        for later in (now - timedelta(seconds=1), now + timedelta(seconds=600), now + timedelta(days=1)):
            with self.assertRaises(RuntimeError):
                delivery._validate_identity(identity, binding, later)
        other = derive_fixed_runtime_binding("emulator-5556", ACTIVE_RUNTIME_PROFILE_ID, "com.global.ztmslg", "primary-login-slot-v1")
        with self.assertRaises(RuntimeError):
            delivery._validate_identity(identity, other, now)

    @requires_tesseract
    def test_native_more_menu_rankings_is_bound_without_more_toggle(self):
        frame = captured(MENU_FIXTURE.read_bytes(), path=MENU_FIXTURE)
        identity = identity_from_captured(frame, session_id="native-more-menu", ordinal=1)
        source = {"source_frame": identity, "source_png": frame.png, "home_is_clean": is_clean_home_frame}
        self.assertTrue(vision.recognize_more_menu(frame.frame, **source))
        target = vision.bind_more_rankings(frame.frame, **source)
        self.assertIsNotNone(target)
        self.assertEqual(target.target_roi, (624, 1098, 668, 1117))
        self.assertLess(target.target_roi[3], vision.MENU_CELLS["rankings"][1])
        self.assertIsNone(vision.bind_home_more(frame.frame, **source))
        for field in ("friend", "rankings", "settings"):
            with self.subTest(missing=field):
                changed = frame.frame.copy()
                x0, y0, x1, y1 = vision.MENU_CELLS[field]
                changed[y0:y1, x0:x1] = 0
                erased = captured(cv2.imencode(".png", changed)[1].tobytes())
                changed_source = {"source_frame": identity_from_captured(erased, session_id="native-more-menu-negative", ordinal=1), "source_png": erased.png, "home_is_clean": is_clean_home_frame}
                self.assertIsNone(vision.bind_more_rankings(erased.frame, **changed_source))
                self.assertIsNone(vision.bind_home_more(erased.frame, **changed_source))

    @requires_tesseract
    def test_native_caption_help_source_uses_trophy_and_missing_body_blocks(self):
        frame = captured(CAPTION_HELP_SOURCE.read_bytes(), path=CAPTION_HELP_SOURCE)
        identity = identity_from_captured(frame, session_id="caption-help-source", ordinal=1)
        source = {"source_frame": identity, "source_png": frame.png, "home_is_clean": is_clean_home_frame}
        target = vision.bind_more_rankings(frame.frame, **source)
        self.assertIsNotNone(target)
        self.assertEqual(target.target_roi, (624, 1098, 668, 1117))
        self.assertIs(target.source_frame, identity)
        for missing in ((600, 1080, 675, 1137), (624, 1098, 668, 1128)):
            changed = frame.frame.copy()
            x0, y0, x1, y1 = missing
            changed[y0:y1, x0:x1] = 0
            erased = captured(cv2.imencode(".png", changed)[1].tobytes())
            changed_source = {"source_frame": identity_from_captured(erased, session_id="missing-trophy", ordinal=1), "source_png": erased.png, "home_is_clean": is_clean_home_frame}
            self.assertTrue(vision.recognize_more_menu(erased.frame, **changed_source))
            self.assertIsNone(vision.bind_more_rankings(erased.frame, **changed_source))

    def test_already_open_more_goes_to_rankings_once_then_unknown_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = Runtime(root, source_png=CAPTION_HELP_SOURCE.read_bytes(), successor_png=MENU_FIXTURE.read_bytes())
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(owner="personal-might-menu", invocation_id="menu", session_directory=root / "session", max_inputs=8) as session:
                    result = route.run(session=session, runtime=runtime, settle_seconds=0)
                    self.assertEqual(session.input_count, 1)
            self.assertEqual(len(runtime.taps), 1)
            self.assertEqual(runtime.taps[0]["target_identity"], vision.RANKINGS_TARGET)
            self.assertEqual(runtime.taps[0]["target_roi"], (624, 1098, 668, 1117))
            self.assertEqual(result["reason"], "personal_might_rankings_page_successor_unknown")
            self.assertEqual(result["verified_navigation"], [])
            self.assertEqual(result["navigation_outcome"], "unknown")
            self.assertEqual(result["praise_transport_calls"], 0)

    def test_personal_might_check_requires_one_exact_row_and_same_row_control(self):
        label = (("personal", (100, 240, 190, 265)), ("might", (200, 240, 270, 265)), ("rank", (280, 240, 340, 265)))
        check = ("check", (600, 268, 680, 290))
        self.assertEqual(vision._personal_row_check((*label, check)), (600, 268, 680, 290))
        self.assertIsNone(vision._personal_row_check((*label[:2], check)))
        self.assertIsNone(vision._personal_row_check((*label, ("check", (600, 340, 680, 365)))))
        self.assertIsNone(vision._personal_row_check((*label, ("check", (150, 240, 210, 265)))))
        self.assertIsNone(vision._personal_row_check((*label, check, ("check", (700, 240, 780, 265)))))
        self.assertIsNone(vision._personal_row_check((*label, check, ("personal might rank", (100, 340, 340, 365)))))

    def test_native_leaderboard_binds_own_exact_personal_might_row(self):
        frame = captured(LEADERBOARD_FIXTURE.read_bytes(), path=LEADERBOARD_FIXTURE)
        identity = identity_from_captured(frame, session_id="native-leaderboard", ordinal=1)
        source = {"source_frame": identity, "source_png": frame.png}
        self.assertTrue(vision.is_rankings(frame.frame, **source))
        target = vision.bind_personal_might_check(frame.frame, **source)
        self.assertIsNotNone(target)
        self.assertEqual(target.target_roi, (612, 267, 687, 288))
        self.assertIs(target.source_frame, identity)
        for missing in ((180, 0, 650, 80), (385, 235, 450, 268), (575, 260, 720, 301)):
            with self.subTest(missing=missing):
                changed = frame.frame.copy()
                x0, y0, x1, y1 = missing
                changed[y0:y1, x0:x1] = 0
                erased = captured(cv2.imencode(".png", changed)[1].tobytes())
                changed_source = {"source_frame": identity_from_captured(erased, session_id="native-row-negative", ordinal=1), "source_png": erased.png}
                self.assertIsNone(vision.bind_personal_might_check(erased.frame, **changed_source))
        duplicate = frame.frame.copy()
        duplicate[365:398, 190:450] = frame.frame[235:268, 190:450]
        ambiguous = captured(cv2.imencode(".png", duplicate)[1].tobytes())
        self.assertIsNone(vision.bind_personal_might_check(ambiguous.frame, source_frame=identity_from_captured(ambiguous, session_id="duplicate-native-row", ordinal=1), source_png=ambiguous.png))

    def test_already_open_leaderboard_uses_one_check_then_unknown_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = Runtime(root, source_png=LEADERBOARD_FIXTURE.read_bytes())
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(owner="personal-might-leaderboard", invocation_id="row", session_directory=root / "session", max_inputs=8) as session:
                    result = route.run(session=session, runtime=runtime, settle_seconds=0)
                    self.assertEqual(session.input_count, 1)
            self.assertEqual(len(runtime.taps), 1)
            self.assertEqual(runtime.taps[0]["target_identity"], vision.CHECK_TARGET)
            self.assertEqual(runtime.taps[0]["target_roi"], (612, 267, 687, 288))
            self.assertEqual(result["reason"], "personal_might_personal_might_page_successor_unknown")
            self.assertEqual(result["verified_navigation"], [])
            self.assertEqual(result["praise_transport_calls"], 0)

    @requires_tesseract
    def test_native_more_binding_is_current_and_popup_free(self):
        frame = captured(FIXTURE.read_bytes())
        identity = identity_from_captured(frame, session_id="native-more", ordinal=1)
        target = vision.bind_home_more(frame.frame, source_frame=identity, source_png=frame.png, home_is_clean=is_clean_home_frame)
        self.assertIsNotNone(target)
        self.assertEqual(target.target_identity, vision.MORE_TARGET)
        self.assertEqual(target.target_roi, (712, 1240, 765, 1263))
        self.assertIs(target.source_frame, identity)
        missing = frame.frame.copy()
        missing[1240:1278, 690:795] = 0
        erased = captured(cv2.imencode(".png", missing)[1].tobytes())
        erased_identity = identity_from_captured(erased, session_id="native-more-erased", ordinal=1)
        self.assertIsNone(vision.bind_home_more(erased.frame, source_frame=erased_identity, source_png=erased.png, home_is_clean=is_clean_home_frame))
        self.assertIsNone(vision.bind_home_more(frame.frame, source_frame=identity, source_png=frame.png, home_is_clean=lambda _: False))
        self.assertIsNone(vision.bind_home_more(frame.frame, source_frame=identity, source_png=frame.png + b"changed", home_is_clean=lambda _: True))

    def test_missing_duplicate_and_timeout_targets_are_non_actionable(self):
        frame = captured(FIXTURE.read_bytes())
        identity = identity_from_captured(frame, session_id="native-more", ordinal=1)
        for text in ([], ["More", "More"], ["Mail"]):
            data = {"text": text, "left": [20] * len(text), "top": [2] * len(text), "width": [100] * len(text), "height": [40] * len(text)}
            with self.subTest(text=text), patch.object(vision, "tesseract_data", return_value=data):
                self.assertIsNone(vision.bind_home_more(frame.frame, source_frame=identity, source_png=frame.png, home_is_clean=lambda _: True))
        with patch.object(vision, "tesseract_data", side_effect=RuntimeError("timeout")):
            self.assertIsNone(vision.bind_home_more(frame.frame, source_frame=identity, source_png=frame.png, home_is_clean=lambda _: True))

    def test_discovery_dispatches_one_more_and_stops_without_praise(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = Runtime(root)
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(owner="personal-might-test", invocation_id="discovery", session_directory=root / "session", max_inputs=8) as session:
                    result = route.run(session=session, runtime=runtime, settle_seconds=0)
                    self.assertEqual(session.input_count, 1)
            self.assertEqual(len(runtime.taps), 1)
            self.assertEqual(runtime.taps[0]["target_identity"], vision.MORE_TARGET)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["praise_transport_calls"], 0)
            self.assertFalse(result["praise_dispatch_supported"])
            self.assertIn("more_menu_successor_unknown", result["reason"])
            self.assertIn("settled", result["successor_frame"])

    def test_changed_before_source_dispatches_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = Runtime(root, changed_before=True)
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(owner="personal-might-test", invocation_id="changed", session_directory=root / "session", max_inputs=8) as session:
                    with self.assertRaises(PerceptionBundleError):
                        route.run(session=session, runtime=runtime, settle_seconds=0)
                    self.assertEqual(session.input_count, 0)
            self.assertEqual(runtime.taps, [])

    def test_discovery_does_not_claim_full_route_acceptance(self):
        result = delivery.verify_personal_might({"session_directory": "fixture"}, {}, {})
        self.assertEqual(result["status"], "evidence_required")
        self.assertFalse(result["scheduler_enabled"])
        with patch.object(delivery.LocalBlueStacksRuntime, "connect", side_effect=AssertionError("dry run must not connect")):
            import json
            result = json.loads(delivery.run_personal_might({}, {"max_inputs": 8}, live=False))
            self.assertEqual(result["input_count"], 0)
            self.assertEqual(result["praise_transport_calls"], 0)


if __name__ == "__main__":
    unittest.main()
