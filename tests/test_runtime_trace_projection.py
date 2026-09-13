from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2

from scripts import bluestacks_popup_recognition as popup_recognition
from scripts.bluestacks_popup_recognition import classify_popup_recovery, recognize_reset_popup
from scripts.runtime_trace_projection import TraceStatus, project_trace
from tasks.list_search import ListObservation, SearchStatus, inspect_list
from tasks.transition_stability import TransitionObservation, TransitionStatus, poll_stable_transition


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "runtime_control_sequences" / "manifest.json"
ENHANCEMENT_FIXTURE = ROOT / "tests" / "fixtures" / "runtime_control_sequences" / "enhancement_transition.json"
PORTABLE_REPLAY_FIXTURE = ROOT / "tests" / "fixtures" / "runtime_trace_projection" / "manifest.json"
VIP_OCR_SNAPSHOT_FIXTURE = ROOT / "tests" / "fixtures" / "runtime_trace_projection" / "vip_popup_ocr_snapshot.json"
IMG_5080 = ROOT / "examples" / "screenshots" / "IMG_5080.PNG"
STARTUP_REFERENCE_MANIFEST = ROOT / "evidence" / "sessions" / "20260711-mvp-startup-normalization" / "reference-manifest.json"
STARTUP_OFFLINE_RESULTS = ROOT / "evidence" / "sessions" / "20260711-mvp-startup-normalization" / "offline-results.json"
IMG_5080_SHA256 = "8c3d7ac932ddf2836bfcfcc05559e7977a3745abeedef2704376e61144e86cdd"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class RuntimeTraceProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
        cls.portable_replay = json.loads(PORTABLE_REPLAY_FIXTURE.read_text(encoding="utf-8"))
        cls.vip_ocr_snapshot = json.loads(VIP_OCR_SNAPSHOT_FIXTURE.read_text(encoding="utf-8"))
    def test_provenance_manifest_hashes_and_native_bindings_are_independent(self):
        for source in self.corpus["source_manifests"]:
            path = ROOT / source["path"]
            self.assertTrue(path.is_file(), source["path"])
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(digest, source["sha256"], source["path"])
        for asset in self.corpus["retained_assets"]:
            path = ROOT / asset["path"]
            self.assertTrue(path.is_file(), asset["path"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), asset["sha256"])
            frame = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            self.assertIsNotNone(frame)
            self.assertEqual((frame.shape[1], frame.shape[0]), tuple(asset["native_dimensions"]))
            self.assertTrue(asset["runtime_profile_id"])
            self.assertTrue(asset["provenance"])
            provenance_manifest = ROOT / asset["provenance"].split(":", 1)[0]
            self.assertTrue(provenance_manifest.is_file(), asset["provenance"])
            self.assertIn(asset["sha256"], provenance_manifest.read_text(encoding="utf-8"))

    def test_img_5080_is_restored_and_retained_evidence_bound(self):
        relative = "examples/screenshots/IMG_5080.PNG"
        self.assertTrue(IMG_5080.is_file(), relative)
        self.assertEqual(hashlib.sha256(IMG_5080.read_bytes()).hexdigest(), IMG_5080_SHA256)

        reference_manifest = json.loads(STARTUP_REFERENCE_MANIFEST.read_text(encoding="utf-8"))
        retained = next(asset for asset in reference_manifest["assets"] if asset["path"] == relative)
        self.assertEqual(retained["path"], relative)
        self.assertEqual(retained["state"], "Home/Base")
        self.assertFalse(retained["production_eligible"])

        offline_results = json.loads(STARTUP_OFFLINE_RESULTS.read_text(encoding="utf-8"))
        reference_check = offline_results["home_base_reference_check"]
        self.assertEqual(reference_check["reference"], relative)
        self.assertEqual(reference_check["reference_sha256"], IMG_5080_SHA256)

    def test_nova_and_ultimate_replay_use_transition_and_list_primitives(self):
        preflight = json.loads((ROOT / "tests/fixtures/nova_praise_preflight/manifest.json").read_text(encoding="utf-8"))
        by_hash = {fixture["file_sha256"]: fixture for fixture in preflight["fixtures"]}
        nova_assets = [asset for asset in self.corpus["retained_assets"] if asset["consumer"] == "Nova"]
        nova_observations = []
        for asset in nova_assets:
            fixture = by_hash[asset["sha256"]]
            state = fixture["semantic_provenance"]["state"]
            nova_observations.append(
                TransitionObservation(
                    {
                        "semantic_state": state,
                        "source_sha256": asset["sha256"],
                        "runtime_profile_id": asset["runtime_profile_id"],
                        "provenance": asset["provenance"],
                    },
                    evidence_ref=asset["path"],
                )
            )
        settled = poll_stable_transition(
            nova_observations,
            stable_polls=2,
            signature=lambda state: state["semantic_state"],
        )
        self.assertEqual(settled.status, TransitionStatus.STABLE)
        self.assertEqual(settled.input_count, 0)
        self.assertEqual(settled.successor["runtime_profile_id"], "native-800x1280")

        ultimate_assets = [asset for asset in self.corpus["retained_assets"] if asset["consumer"] == "Ultimate"]
        ultimate_observations = [
            ListObservation(
                frame_signature=asset["sha256"],
                list_signature=("tier-controls", index),
                target_visible=False,
                displacement=0,
                direction="forward",
                typed_observation={"source": asset["path"], "profile": asset["runtime_profile_id"]},
                evidence_ref=asset["provenance"],
            )
            for index, asset in enumerate(ultimate_assets, 1)
        ]
        searched = inspect_list(ultimate_observations)
        self.assertEqual(searched.status, SearchStatus.NO_MOTION)
        self.assertFalse(searched.dispatch_allowed)
        self.assertEqual(searched.input_count, 0)

    def test_enhancement_replay_is_provenance_bound_and_input_free(self):
        fixture = json.loads(ENHANCEMENT_FIXTURE.read_text(encoding="utf-8"))
        portable = self.portable_replay["fixtures"]["enhancement"]
        self.assertEqual(fixture["consumer"], "Enhancement")
        self.assertEqual(fixture["proof_state"], "replayable")
        self.assertEqual(fixture["dispatch_policy"], "replay_never_dispatches_input")
        self.assertEqual(fixture["native_dimensions"], [800, 1280])

        source_retained = portable["source_record"]["retained_source"]
        event_retained = portable["event_log"]["retained_source"]
        self.assertEqual(source_retained["manifest"], "tests/fixtures/runtime_control_sequences/enhancement_transition.json")
        self.assertEqual(event_retained["manifest"], "tests/fixtures/runtime_control_sequences/enhancement_transition.json")
        self.assertEqual(source_retained["path"], fixture["source_record"]["path"])
        self.assertEqual(source_retained["sha256"], fixture["source_record"]["sha256"])
        self.assertEqual(event_retained["path"], fixture["event_log"]["path"])
        self.assertEqual(event_retained["sha256"], fixture["event_log"]["sha256"])

        source_path = ROOT / portable["source_record"]["portable_copy"]["path"]
        event_path = ROOT / portable["event_log"]["portable_copy"]["path"]
        self.assertTrue(source_path.is_file(), str(source_path))
        self.assertTrue(event_path.is_file(), str(event_path))
        self.assertEqual(source_path.stat().st_size, portable["source_record"]["portable_copy"]["bytes"])
        self.assertEqual(event_path.stat().st_size, portable["event_log"]["portable_copy"]["bytes"])
        self.assertEqual(
            source_retained["sha256"],
            portable["source_record"]["portable_copy"]["sha256"],
        )
        self.assertEqual(
            event_retained["sha256"],
            portable["event_log"]["portable_copy"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(source_path.read_bytes()).hexdigest(),
            portable["source_record"]["portable_copy"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(event_path.read_bytes()).hexdigest(),
            portable["event_log"]["portable_copy"]["sha256"],
        )

        retained = json.loads(source_path.read_text(encoding="utf-8"))
        self.assertEqual(retained["flow_id"], fixture["flow_id"])
        self.assertEqual(
            [retained["native_width"], retained["native_height"]],
            fixture["native_dimensions"],
        )
        module_result = next(
            result
            for result in retained["enhancement_result"]["category_results"]
            if result["variant"] == "module"
        )
        self.assertEqual(
            module_result["successor_observation"]["runtime_profile_id"],
            fixture["runtime_profile_id"],
        )

        events = [
            json.loads(line)
            for line in event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        events_by_label = {event["label"]: event for event in events if "label" in event}
        required_phases = {
            "immediate_post",
            "first_settled",
            "settled_confirmation",
            "terminal_settled",
        }
        phases = [observation["phase"] for observation in fixture["observations"]]
        self.assertEqual(set(phases), required_phases)
        self.assertEqual(len(phases), len(required_phases))
        observations = {observation["phase"]: observation for observation in fixture["observations"]}
        frame_locators = portable["frames"]
        self.assertEqual({locator["phase"] for locator in frame_locators}, required_phases)
        self.assertEqual(len(frame_locators), len(required_phases))
        frame_locators_by_phase = {locator["phase"]: locator for locator in frame_locators}
        expected_hashes = {
            "immediate_post": retained["actions"][0]["immediate_post_sha256"],
            "first_settled": retained["actions"][0]["settled_successor_sha256"],
            "settled_confirmation": retained["actions"][1]["before_sha256"],
            "terminal_settled": retained["actions"][1]["settled_successor_sha256"],
        }
        for phase, observation in observations.items():
            event = events_by_label[observation["event_label"]]
            locator = frame_locators_by_phase[phase]
            retained_frame = locator["retained_source"]
            portable_frame = locator["portable_copy"]
            self.assertEqual(locator["event_label"], observation["event_label"])
            self.assertEqual(locator["evidence_ref"], observation["evidence_ref"])
            self.assertTrue(
                event["path"].replace("\\", "/").endswith(retained_frame["path"]),
                event["path"],
            )
            self.assertEqual(
                retained_frame["path"],
                (Path(source_retained["path"]).parent / observation["evidence_ref"]).as_posix(),
            )
            self.assertEqual(retained_frame["sha256"], event["sha256"])
            self.assertEqual(observation["frame_sha256"], expected_hashes[phase])
            self.assertEqual(observation["frame_sha256"], event["sha256"])
            self.assertEqual(retained_frame["sha256"], observation["frame_sha256"])
            self.assertEqual(portable_frame["sha256"], observation["frame_sha256"])
            portable_path = ROOT / portable_frame["path"]
            self.assertTrue(portable_path.resolve().is_relative_to(ROOT / "tests" / "fixtures"))
            self.assertFalse(Path(portable_frame["path"]).is_absolute())
            self.assertNotIn(".local-captures", Path(portable_frame["path"]).parts)
            self.assertTrue(portable_path.is_file(), str(portable_path))
            frame_bytes = portable_path.read_bytes()
            self.assertEqual(len(frame_bytes), portable_frame["bytes"])
            self.assertEqual(hashlib.sha256(frame_bytes).hexdigest(), portable_frame["sha256"])
            self.assertTrue(frame_bytes.startswith(PNG_SIGNATURE))
            frame = cv2.imread(str(portable_path), cv2.IMREAD_UNCHANGED)
            self.assertIsNotNone(frame)
            self.assertEqual((frame.shape[1], frame.shape[0]), tuple(fixture["native_dimensions"]))
            self.assertEqual(event["type"], "capture")
            self.assertTrue(
                event["path"].replace("\\", "/").endswith(observation["evidence_ref"])
            )
            self.assertEqual(
                observation["typed_observation"]["runtime_profile_id"],
                fixture["runtime_profile_id"],
            )
            self.assertEqual(
                observation["typed_observation"]["native_dimensions"],
                fixture["native_dimensions"],
            )

        def typed(phase):
            observation = observations[phase]
            value = dict(observation["typed_observation"])
            value["semantic_state"] = observation["semantic_state"]
            value["frame_sha256"] = observation["frame_sha256"]
            return TransitionObservation(value, evidence_ref=observation["evidence_ref"])

        transient = poll_stable_transition(
            [typed("immediate_post")],
            stable_polls=2,
            signature=lambda value: value["semantic_state"],
        )
        self.assertEqual(transient.status, TransitionStatus.TRANSIENT)
        self.assertEqual(transient.input_count, 0)

        stable = poll_stable_transition(
            [typed("first_settled"), typed("settled_confirmation")],
            stable_polls=2,
            signature=lambda value: value["semantic_state"],
        )
        self.assertEqual(stable.status, TransitionStatus.STABLE)
        self.assertEqual(stable.input_count, 0)
        self.assertEqual(stable.successor["runtime_profile_id"], fixture["runtime_profile_id"])


    def test_claim_list_and_vip_worldmap_modal_replays_are_bound_or_fail_closed(self):
        claim = next(asset for asset in self.corpus["retained_assets"] if asset["consumer"] == "Claim")
        claim_search = inspect_list(
            [
                ListObservation(
                    frame_signature=claim["sha256"],
                    list_signature=("claim-frame", claim["sha256"]),
                    target_visible=False,
                    displacement=0,
                    typed_observation=claim,
                    evidence_ref=claim["provenance"],
                )
            ]
        )
        self.assertEqual(claim_search.status, SearchStatus.TRANSIENT)
        self.assertEqual(claim_search.input_count, 0)

        popup_asset = next(asset for asset in self.corpus["retained_assets"] if asset["consumer"] == "VIP")
        popup_snapshot = self.vip_ocr_snapshot
        frame_path = ROOT / popup_asset["path"]
        self.assertEqual(popup_snapshot["frame"]["path"], popup_asset["path"])
        self.assertEqual(popup_snapshot["frame"]["sha256"], popup_asset["sha256"])
        self.assertEqual(hashlib.sha256(frame_path.read_bytes()).hexdigest(), popup_snapshot["frame"]["sha256"])
        frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        self.assertEqual(tuple(frame.shape), tuple(popup_snapshot["frame"]["shape"]))

        # Bind recorded OCR to the retained frame/ROIs, not one CPU backend's
        # interpolated bytes. Generate expected crops with this host's OpenCV.
        recorded = {}
        for observation in popup_snapshot["observations"]:
            x0, y0, x1, y1 = observation["roi"]
            scale = observation["resize_scale"]
            expected_crop = cv2.resize(
                frame[y0:y1, x0:x1], None, fx=scale, fy=scale,
                interpolation=cv2.INTER_CUBIC,
            )
            if "binary_threshold" in observation:
                gray = cv2.cvtColor(expected_crop, cv2.COLOR_BGR2GRAY)
                expected_crop = cv2.threshold(
                    gray, observation["binary_threshold"], 255, cv2.THRESH_BINARY,
                )[1]
            key = (hashlib.sha256(expected_crop.tobytes()).hexdigest(), observation["config"])
            recorded[key] = observation

        def replay_ocr(image, *, config):
            key = (hashlib.sha256(image.tobytes()).hexdigest(), config)
            observation = recorded.get(key)
            if observation is None:
                raise AssertionError(f"unbound OCR crop/config request: {key}")
            return observation["text"]

        with patch.object(
            popup_recognition.pytesseract,
            "image_to_string",
            side_effect=replay_ocr,
        ):
            popup = recognize_reset_popup(frame)
        self.assertTrue(popup["recognized"])
        vip = classify_popup_recovery(popup, source_context="vip-source", successor_context="vip-source")
        self.assertTrue(vip.recognized)
        self.assertTrue(vip.allows_dismissal)
        self.assertFalse(vip.confirm_authorized)

        world = json.loads((ROOT / "tests/fixtures/world_map_navigation_observations.json").read_text(encoding="utf-8"))
        unknown = world["observations"]["unknown_popup"]["popup"]
        world_modal = classify_popup_recovery(
            {"recognized": False, "reason": "unknown_popup", **unknown},
            source_context=world["observations"]["unknown_popup"]["state"],
        )
        self.assertFalse(world_modal.recognized)
        self.assertFalse(world_modal.confirm_authorized)

    def test_nova_and_resource_retained_event_replays_stay_action_bound(self):
        replay_manifest = json.loads((ROOT / "tests/fixtures/nova_praise_replay/manifest.json").read_text(encoding="utf-8"))
        nova_case = next(case for case in replay_manifest["cases"] if case["fixture_id"] == "praise_on_cooldown")
        portable_nova = {
            "dispatch_and_initial_reconciliation_journal": self.portable_replay["fixtures"]["nova_live_events"],
            "terminal_reconciliation_journal": self.portable_replay["fixtures"]["nova_reconcile_events"],
        }
        event_refs = [ref for ref in nova_case["evidence_refs"] if ref["kind"].endswith("journal")]
        for ref in event_refs:
            portable = portable_nova[ref["kind"]]
            retained = portable["retained_source"]
            path = ROOT / portable["portable_copy"]["path"]
            self.assertEqual(retained["manifest"], "tests/fixtures/nova_praise_replay/manifest.json")
            self.assertEqual(retained["sha256"], ref["sha256"])
            self.assertEqual(retained["path"], ref["path"])
            self.assertTrue(path.is_file(), str(path))
            self.assertEqual(path.stat().st_size, portable["portable_copy"]["bytes"])
            self.assertEqual(retained["sha256"], portable["portable_copy"]["sha256"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), portable["portable_copy"]["sha256"])
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            projection = project_trace(rows)
            self.assertIn(projection.status, {TraceStatus.UNKNOWN, TraceStatus.CONTRADICTORY, TraceStatus.INCOMPLETE})
            self.assertFalse(projection.is_authorizing)
            self.assertEqual(projection.input_count, sum(row.get("type") == "dispatch" for row in rows))
            self.assertEqual(projection.status, TraceStatus.CONTRADICTORY)
            self.assertIn("mixed_action_keys", projection.contradictions)
            bound_action_keys = {row["action_key"] for row in rows if row.get("action_key")}
            expected_action_key = next(iter(bound_action_keys)) if len(bound_action_keys) == 1 else ""
            self.assertEqual(projection.action_key, expected_action_key)

        resource_manifest = json.loads((ROOT / "tests/fixtures/resource_effect_authority/historical_sessions.json").read_text(encoding="utf-8"))
        resource_session = resource_manifest["sessions"][1]
        portable_resource = self.portable_replay["fixtures"]["resource_events"]
        retained = portable_resource["retained_source"]
        resource_events = ROOT / portable_resource["portable_copy"]["path"]
        self.assertEqual(retained["manifest"], "tests/fixtures/resource_effect_authority/historical_sessions.json")
        self.assertEqual(retained["selector"], "sessions[1].events")
        self.assertEqual(retained["sha256"], resource_session["events"]["sha256"])
        self.assertEqual(retained["sha256"], portable_resource["portable_copy"]["sha256"])
        self.assertTrue(resource_events.is_file(), str(resource_events))
        self.assertEqual(resource_events.stat().st_size, portable_resource["portable_copy"]["bytes"])
        self.assertEqual(
            hashlib.sha256(resource_events.read_bytes()).hexdigest(),
            portable_resource["portable_copy"]["sha256"],
        )
        rows = [json.loads(line) for line in resource_events.read_text(encoding="utf-8").splitlines() if line.strip()]
        projection = project_trace(rows)
        self.assertIn(projection.status, {TraceStatus.UNKNOWN, TraceStatus.CONTRADICTORY, TraceStatus.INCOMPLETE})
        self.assertFalse(projection.is_authorizing)
        self.assertEqual(projection.input_count, sum(row.get("type") == "dispatch" for row in rows))
        self.assertEqual(projection.status, TraceStatus.CONTRADICTORY)
        self.assertIn("mixed_action_keys", projection.contradictions)
        self.assertEqual(projection.action_key, "")

    def test_full_chain_is_complete_only_with_explicit_results(self):
        events = [
            {"stage": "observation", "action_key": "a", "evidence_ref": "source"},
            {"stage": "intent", "action_key": "a"},
            {"stage": "transport", "action_key": "a"},  # dispatch alone is not proof
            {"stage": "settled_successor", "action_key": "a"},
            {"stage": "semantic_result", "action_key": "a", "success": True},
            {"stage": "terminal_result", "action_key": "a", "success": True},
        ]
        unknown = project_trace(events)
        self.assertEqual(unknown.status, TraceStatus.UNKNOWN)
        self.assertFalse(unknown.transport_observed)
        events[2]["transport_observed"] = True
        complete = project_trace(events)
        self.assertEqual(complete.status, TraceStatus.COMPLETE)
        self.assertTrue(complete.transport_observed)
        self.assertTrue(complete.semantic_success_observed)
        self.assertFalse(complete.is_authorizing)

    def test_mixed_action_keys_cannot_form_a_complete_chain(self):
        events = [
            {"stage": "observation", "action_key": "A"},
            {"stage": "intent", "action_key": "A"},
            {"stage": "transport", "action_key": "A", "transport_observed": True},
            {"stage": "settled_successor", "action_key": "A"},
            {"stage": "semantic_result", "action_key": "B", "success": True},
            {"stage": "terminal_result", "action_key": "B", "success": True},
        ]
        result = project_trace(events)
        self.assertEqual(result.status, TraceStatus.CONTRADICTORY)
        self.assertIn("mixed_action_keys", result.contradictions)
        self.assertNotEqual(result.action_key, "A")

    def test_unbound_chain_stays_unknown_even_when_all_stages_are_present(self):
        events = [
            {"stage": "observation"},
            {"stage": "intent"},
            {"stage": "transport", "transport_observed": True},
            {"stage": "settled_successor"},
            {"stage": "semantic_result", "success": True},
            {"stage": "terminal_result", "success": True},
        ]
        result = project_trace(events)
        self.assertEqual(result.status, TraceStatus.UNKNOWN)
        self.assertIn("action_key_unbound", result.unknown_reasons)

    def test_missing_and_contradictory_events_are_preserved(self):
        missing = project_trace([{"stage": "observation"}, {"stage": "intent"}])
        self.assertEqual(missing.status, TraceStatus.INCOMPLETE)
        contradictory = project_trace(
            [
                {"stage": "observation"},
                {"stage": "intent"},
                {"stage": "transport", "transport_observed": True},
                {"stage": "settled_successor"},
                {"stage": "semantic_result", "success": True},
                {"stage": "terminal_result", "success": True, "contradictory": True},
            ]
        )
        self.assertEqual(contradictory.status, TraceStatus.CONTRADICTORY)
        self.assertEqual(contradictory.authority_mutated, False)


if __name__ == "__main__":
    unittest.main()
