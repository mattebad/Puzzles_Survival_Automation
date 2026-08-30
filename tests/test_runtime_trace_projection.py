from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

import cv2

from scripts.bluestacks_popup_recognition import classify_popup_recovery, recognize_reset_popup
from scripts.runtime_trace_projection import TraceStatus, project_trace
from tasks.list_search import ListObservation, SearchStatus, inspect_list
from tasks.transition_stability import TransitionObservation, TransitionStatus, poll_stable_transition


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "runtime_control_sequences" / "manifest.json"
ENHANCEMENT_FIXTURE = ROOT / "tests" / "fixtures" / "runtime_control_sequences" / "enhancement_transition.json"


class RuntimeTraceProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads(CORPUS.read_text(encoding="utf-8"))

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
        self.assertEqual(fixture["consumer"], "Enhancement")
        self.assertEqual(fixture["proof_state"], "replayable")
        self.assertEqual(fixture["dispatch_policy"], "replay_never_dispatches_input")
        self.assertEqual(fixture["native_dimensions"], [800, 1280])

        source_path = ROOT / fixture["source_record"]["path"]
        event_path = ROOT / fixture["event_log"]["path"]
        self.assertTrue(source_path.is_file(), str(source_path))
        self.assertTrue(event_path.is_file(), str(event_path))
        self.assertEqual(
            hashlib.sha256(source_path.read_bytes()).hexdigest(),
            fixture["source_record"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(event_path.read_bytes()).hexdigest(),
            fixture["event_log"]["sha256"],
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
        expected_hashes = {
            "immediate_post": retained["actions"][0]["immediate_post_sha256"],
            "first_settled": retained["actions"][0]["settled_successor_sha256"],
            "settled_confirmation": retained["actions"][1]["before_sha256"],
            "terminal_settled": retained["actions"][1]["settled_successor_sha256"],
        }
        for phase, observation in observations.items():
            event = events_by_label[observation["event_label"]]
            self.assertEqual(observation["frame_sha256"], expected_hashes[phase])
            self.assertEqual(observation["frame_sha256"], event["sha256"])
            self.assertEqual(
                observation["typed_observation"]["runtime_profile_id"],
                fixture["runtime_profile_id"],
            )
            self.assertEqual(
                observation["typed_observation"]["native_dimensions"],
                fixture["native_dimensions"],
            )
            frame_path = event_path.parent / observation["evidence_ref"]
            self.assertTrue(frame_path.is_file(), str(frame_path))
            self.assertEqual(
                hashlib.sha256(frame_path.read_bytes()).hexdigest(),
                observation["frame_sha256"],
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
        frame = cv2.imread(str(ROOT / popup_asset["path"]), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
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
        event_paths = [ref["path"] for ref in nova_case["evidence_refs"] if ref["kind"].endswith("journal")]
        for relative in event_paths:
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            ref = next(ref for ref in nova_case["evidence_refs"] if ref["path"] == relative)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), ref["sha256"])
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            projection = project_trace(rows)
            self.assertIn(projection.status, {TraceStatus.UNKNOWN, TraceStatus.CONTRADICTORY, TraceStatus.INCOMPLETE})
            self.assertFalse(projection.is_authorizing)

        resource_manifest = json.loads((ROOT / "tests/fixtures/resource_effect_authority/historical_sessions.json").read_text(encoding="utf-8"))
        resource_session = resource_manifest["sessions"][1]
        resource_events = Path(resource_session["events"]["path"])
        self.assertTrue(resource_events.is_file(), str(resource_events))
        self.assertEqual(
            hashlib.sha256(resource_events.read_bytes()).hexdigest(),
            resource_session["events"]["sha256"],
        )
        rows = [json.loads(line) for line in resource_events.read_text(encoding="utf-8").splitlines() if line.strip()]
        projection = project_trace(rows)
        self.assertIn(projection.status, {TraceStatus.UNKNOWN, TraceStatus.CONTRADICTORY, TraceStatus.INCOMPLETE})
        self.assertFalse(projection.is_authorizing)
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
