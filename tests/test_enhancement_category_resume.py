"""Offline original-category replay and truthful composite family accounting."""
from __future__ import annotations

import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import flow_delivery_enhancement_bluestacks as delivery
from scripts import pnsctl
from tests.support.enhancement_replay import CATEGORIES, CategoryResumeSessions


class EnhancementCategoryResumeTests(CategoryResumeSessions, unittest.TestCase):
    def case_for(self, reference):
        parent = Path(reference).parent.parent.resolve()
        return next(case for case in self.cases if case.session.resolve() == parent)

    def parsers(self):
        def selection(current, **kwargs):
            return self.case_for(current.path).selection(current, **kwargs)

        def commander(frame, **kwargs):
            return self.case_for(kwargs["evidence_ref"]).commander(frame, **kwargs)

        def home(frame, *, source_frame_sha256):
            del frame
            hashes = {case.home_hash for case in self.cases}
            hashes.update(case.result["initial_frame_sha256"] for case in self.cases)
            return SimpleNamespace(recognized=source_frame_sha256 in hashes)

        return (
            patch("scripts.enhancement_bluestacks.recognize_selection_context", selection),
            patch("scripts.enhancement_bluestacks.recognize_commander_stage", commander),
            patch("scripts.enhancement_bluestacks.recognize_home_frame", home),
        )

    def inventory(self, completed):
        with self.parsers()[0], self.parsers()[1], self.parsers()[2]:
            return delivery._verify_retained_categories(completed, self.cases[0].reset)

    def verify(self, case, *, checkpoint=None):
        self.persist(case)
        with self.parsers()[0], self.parsers()[1], self.parsers()[2]:
            return delivery.verify_enhancement_family({"result": case.result,
                "session_directory": str(case.session), "frames": case.result["frames"]}, {}, {"checkpoint": checkpoint})

    def test_long_original_and_current_replay_renews_existing_checkpoint(self):
        original = self.make_session(("gear",))
        gear = original.result["enhancement_result"]["category_results"][0]
        current = self.make_session(("chip", "module"), {"gear": gear})
        clock = {"now": 0.0, "expires": 60.0}
        renewals = []

        def checkpoint():
            if clock["now"] > clock["expires"]:
                raise RuntimeError("SERVICE_LEASE_LOST")
            renewals.append(clock["now"])
            clock["expires"] = clock["now"] + 60.0

        for case in self.cases:
            for name in ("selection", "commander"):
                parser = getattr(case, name)

                def slow(*args, parser=parser, **kwargs):
                    verdict = parser(*args, **kwargs)
                    clock["now"] += 31.0
                    return verdict

                setattr(case, name, slow)
        preserved = {path: path.read_bytes() for case in self.cases
                     for path in (case.session / "events.jsonl", case.session / "flow-delivery-result.json")}
        verdict = self.verify(current, checkpoint=checkpoint)
        checkpoint()
        self.assertEqual(verdict["status"], "verified")
        self.assertEqual(verdict["current_resource_affecting_dispatch_count"], 2)
        self.assertGreater(clock["now"], 60.0)
        self.assertGreater(len(renewals), 10)
        self.assertTrue(all(right - left <= 60.0 for left, right in zip(renewals, renewals[1:])))
        self.assertEqual({path: path.read_bytes() for path in preserved}, preserved)

    def test_fence_loss_inside_semantic_replay_is_not_swallowed_as_uncertain_pixels(self):
        current = self.make_session()
        original_parser = current.selection
        fenced = False
        parser_calls = 0

        def checkpoint():
            if fenced:
                raise RuntimeError("SERVICE_OR_FLOW_DISABLED")

        def lose_fence(*args, **kwargs):
            nonlocal fenced, parser_calls
            verdict = original_parser(*args, **kwargs)
            parser_calls += 1
            fenced = True
            return verdict

        current.selection = lose_fence
        preserved = (current.session / "flow-delivery-result.json").read_bytes()
        with self.assertRaisesRegex(RuntimeError, "SERVICE_OR_FLOW_DISABLED"):
            self.verify(current, checkpoint=checkpoint)
        self.assertEqual(parser_calls, 1)
        self.assertEqual((current.session / "flow-delivery-result.json").read_bytes(), preserved)

    def test_retained_gear_plus_current_two_has_real_separate_sources_and_counts(self):
        source = self.make_session(("gear",))
        gear = source.result["enhancement_result"]["category_results"][0]
        retained_bytes = {path: path.read_bytes() for path in source.session.rglob("*") if path.is_file()}
        metadata = self.inventory({"gear": gear})
        self.assertEqual(list(metadata), ["gear"])
        current = self.make_session(("chip", "module"), {"gear": gear})
        verdict = self.verify(current)
        self.assertEqual(verdict["status"], "verified")
        self.assertEqual(verdict["proof_topology"], "composite")
        self.assertEqual(verdict["current_resource_affecting_dispatch_count"], 2)
        self.assertEqual(verdict["retained_category_count"], 1)
        self.assertEqual(list(verdict["category_source_proofs"]), list(CATEGORIES))
        self.assertEqual(verdict["current_categories"], ["chip", "module"])
        self.assertEqual(verdict["category_source_proofs"]["gear"], metadata["gear"])
        self.assertEqual({path: path.read_bytes() for path in retained_bytes}, retained_bytes)
        self.assertTrue(all(str(source.session) not in frame for frame in current.result["frames"]))

    def test_continuous_family_still_requires_three_ordered_current_uses(self):
        current = self.make_session()
        current.session = current.session / "frames" / ".."
        verdict = self.verify(current)
        self.assertEqual(verdict["status"], "verified")
        self.assertEqual(verdict["proof_topology"], "continuous")
        self.assertEqual(verdict["current_categories"], list(CATEGORIES))
        self.assertEqual(verdict["current_resource_affecting_dispatch_count"], 3)
        self.assertEqual(verdict["retained_category_count"], 0)
        proofs = current.result["enhancement_result"]["category_results"]
        current.result["enhancement_result"]["category_results"] = list(reversed(proofs))
        with self.assertRaises(pnsctl.OperatorError):
            self.verify(current)

    def test_normal_wrapper_reports_its_verified_terminal_home_truthfully(self):
        current = self.make_session()
        outer = SimpleNamespace(
            session_directory=current.session, owner="offline-wrapper-test",
            input_count=current.result["input_count"], actions=current.result["actions"],
            set_causal_trace=lambda trace: None, remember_control=lambda key, value: None,
        )
        flow_root = current.session / "isolated-flow-state"
        with (
            patch.object(delivery, "_outer_session", return_value=outer),
            patch.object(delivery, "_initial_observation", return_value=copy.deepcopy(current.result["initial_observation"])),
            patch.object(delivery, "_select_family_state", return_value=(flow_root, current.reset, {})),
            patch.object(delivery, "_ensure_family_reservations", return_value={}),
            # This test wraps an already-built offline journal. Native startup
            # input/replay belongs to the service startup integration tests.
            patch.object(delivery, "_recover_family_startup", return_value=None),
            patch.object(delivery.LocalBlueStacksRuntime, "connect", return_value=SimpleNamespace(session=current.session)),
            patch("scripts.enhancement_bluestacks.EnhancementIntegratedRoute", return_value=SimpleNamespace(
                run=lambda: copy.deepcopy(current.result["enhancement_result"]),
            )) as route,
        ):
            summary = json.loads(delivery.run_enhancement_family({}, {
                "enhancement_reset_identity": current.reset, "max_inputs": 24,
            }, live=True))
        result = json.loads((current.session / "flow-delivery-result.json").read_text(encoding="utf-8"))
        self.assertTrue(result["terminal_home_verified"])
        self.assertTrue(summary["terminal_home_verified"])
        route.assert_called_once()
        self.assertEqual(route.call_args.kwargs["variants"], CATEGORIES)

    def test_all_retained_from_same_or_multiple_sources_needs_only_current_home(self):
        for split in (False, True):
            with self.subTest(split=split):
                originals = [self.make_session((variant,)) for variant in CATEGORIES] if split else [self.make_session()]
                retained = {proof["variant"]: proof for case in originals
                    for proof in case.result["enhancement_result"]["category_results"]}
                current = self.make_session((), retained)
                verdict = self.verify(current)
                self.assertEqual(verdict["status"], "verified")
                self.assertEqual(verdict["current_resource_affecting_dispatch_count"], 0)
                self.assertEqual(verdict["current_categories"], [])
                self.assertEqual(verdict["retained_categories"], list(CATEGORIES))
                self.assertEqual(current.result["input_count"], 0)
                current.result["enhancement_result"]["terminal_frame_sha256"] = "f" * 64
                with self.assertRaises(pnsctl.OperatorError):
                    self.verify(current)

    def test_non_prefix_retention_still_orders_only_current_remaining_inputs(self):
        source = self.make_session(("chip",))
        chip = source.result["enhancement_result"]["category_results"][0]
        current = self.make_session(("gear", "module"), {"chip": chip})
        # Existing Native emits retained records first, then this run's ordered
        # records. Their collection order is not a claim of merged transport.
        proofs = current.result["enhancement_result"]["category_results"]
        current.result["enhancement_result"]["category_results"] = [proofs[1], proofs[0], proofs[2]]
        verdict = self.verify(current)
        self.assertEqual(verdict["current_categories"], ["gear", "module"])
        self.assertEqual(verdict["retained_categories"], ["chip"])

    def test_current_progress_is_replayed_before_it_can_skip_a_category(self):
        source = self.make_session(("gear",))
        gear = source.result["enhancement_result"]["category_results"][0]
        base = source.session / "isolated-state"
        occurrence = base / "occurrences" / source.reset
        occurrence.mkdir(parents=True)
        progress = occurrence / "family-progress.json"
        progress.write_text(json.dumps({"flow_id": delivery.FLOW_ID, "categories": {"gear": gear}}), encoding="utf-8")
        retained = progress.read_bytes()
        with self.parsers()[0], self.parsers()[1], self.parsers()[2]:
            selected, reset, completed = delivery._select_family_state(base, source.reset)
            self.assertEqual((selected, reset, list(completed)), (occurrence, source.reset, ["gear"]))
            self.assertEqual(progress.read_bytes(), retained)
            witness = Path(gear["before_observation"]["evidence_refs"][2])
            witness.write_bytes(Path(gear["before_observation"]["evidence_refs"][1]).read_bytes())
            with self.assertRaises(pnsctl.OperatorError):
                delivery._select_family_state(base, source.reset)
        self.assertEqual(progress.read_bytes(), retained)

    def test_current_ledger_cannot_repeat_retained_gear_or_omit_remaining_use(self):
        source = self.make_session(("gear",))
        gear = source.result["enhancement_result"]["category_results"][0]
        current = self.make_session(("chip", "module"), {"gear": gear})
        row = copy.deepcopy(next(row for row in current.rows if row.get("target_identity") == "enhancement-use"))
        row["action_key"] = gear["resource_affecting_action_key"]
        current.rows.append(row)
        current.result["dispatch_count"] += 1
        current.result["input_count"] += 1
        current.result["resource_affecting_dispatch_count"] += 1
        current.result["causal_trace"]["transport_count"] += 1
        current.result["causal_trace"]["resource_affecting_dispatch_count"] += 1
        with self.assertRaises(pnsctl.OperatorError):
            self.verify(current)
        current = self.make_session(("chip", "module"), {"gear": gear})
        current.rows = [row for row in current.rows if not (
            row.get("target_identity") == "enhancement-use"
            and str(row.get("action_key", "")).startswith("enhancement:module:")
        )]
        current.result["dispatch_count"] -= 1
        current.result["input_count"] -= 1
        current.result["resource_affecting_dispatch_count"] -= 1
        current.result["causal_trace"]["transport_count"] -= 1
        current.result["causal_trace"]["resource_affecting_dispatch_count"] -= 1
        with self.assertRaises(pnsctl.OperatorError):
            self.verify(current)

    def test_retained_scope_key_reset_cross_session_and_png_tamper_fail(self):
        source = self.make_session(("gear",))
        gear = source.result["enhancement_result"]["category_results"][0]
        for changes in (
            {"resource_affecting_action_key": gear["resource_affecting_action_key"] + "-other"},
            {"runtime_session": str(self.make_session(("gear",)).session)},
            {"before_observation": dict(gear["before_observation"], game_day_id="local-2026-10-28-enhancement-family")},
        ):
            with self.subTest(changes=changes), self.assertRaises(pnsctl.OperatorError):
                self.inventory({"gear": {**gear, **changes}})
        path = Path(gear["before_observation"]["evidence_refs"][2])
        path.write_bytes(Path(gear["before_observation"]["evidence_refs"][1]).read_bytes())
        with self.assertRaises(pnsctl.OperatorError):
            self.inventory({"gear": gear})

    def test_original_missing_first_post_or_orphan_resource_is_not_skippable(self):
        source = self.make_session(("gear",))
        gear = source.result["enhancement_result"]["category_results"][0]
        original = copy.deepcopy(source.result["actions"])
        source.result["actions"][0]["immediate_post_sha256"] = gear["before_observation"]["source_frame_sha256"]
        self.persist(source)
        with self.assertRaises(pnsctl.OperatorError):
            self.inventory({"gear": gear})
        source.result["actions"] = original
        orphan = copy.deepcopy(next(row for row in source.rows if row.get("target_identity") == "enhancement-use"))
        orphan["action_key"] = "enhancement:chip:enhancement-use:unaccounted"
        source.rows.append(orphan)
        source.result["dispatch_count"] += 1
        source.result["input_count"] += 1
        source.result["resource_affecting_dispatch_count"] += 1
        self.persist(source)
        with self.assertRaises(pnsctl.OperatorError):
            self.inventory({"gear": gear})

    def test_original_cannot_borrow_another_sessions_event_journal(self):
        source = self.make_session(("gear",))
        other = self.make_session(("gear",))
        gear = source.result["enhancement_result"]["category_results"][0]
        source.result["events_path"] = str(other.session / "events.jsonl")
        self.persist(source)
        with self.assertRaises(pnsctl.OperatorError):
            self.inventory({"gear": gear})

    def test_validated_no_effect_key_is_accounted_without_completion_or_rearming(self):
        source = self.make_session(("gear",))
        gear = source.result["enhancement_result"]["category_results"][0]
        key = "enhancement:chip:enhancement-use:old-zero-selected"
        pending = {"variant": "chip", "status": "dispatch_bearing_unresolved",
            "resource_affecting_dispatch_count": 1, "resource_affecting_action_key": key,
            "runtime_session": str(source.session), "source_frame_sha256": source.before["chip"].source_frame_sha256,
            "before_observation": asdict(source.before["chip"]), "successor_observation": None}
        source.result["enhancement_result"]["category_results"].append(pending)
        source.rows.append({"type": "dispatch", "target_identity": "enhancement-use", "action_key": key})
        source.result["dispatch_count"] += 1
        source.result["input_count"] += 1
        source.result["resource_affecting_dispatch_count"] += 1
        self.persist(source)
        recovery = source.session / "zero-input-recovery"
        recovery.mkdir()
        receipt = {"original_runtime_session": str(source.session), "original_action_key": key,
            "recovery_session_directory": str(recovery), "reset_identity": source.reset}
        receipt_path = recovery / delivery._NO_EFFECT_RECEIPT_NAME
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        no_effect = {"status": "confirmed_no_effect", "reset_identity": source.reset,
            "original_attempt": pending, "no_effect_receipt": receipt, "continuation_claim": None}
        state = source.session / "isolated-progress"
        state.mkdir()
        progress = state / "family-progress.json"
        progress.write_text(json.dumps({"flow_id": delivery.FLOW_ID,
            "categories": {"gear": gear, "chip": no_effect}}), encoding="utf-8")
        retained_bytes = progress.read_bytes()

        # The existing validator owns full four-PNG/immutable-receipt proof and
        # has real-fixture integration tests. This seam test supplies its typed
        # verdict while exercising reference binding and ledger accounting.
        def validated(entry, *, variant, reset_identity, allow_claimed=False):
            self.assertEqual(variant, "chip")
            expected = reset_identity or entry["reset_identity"]
            if entry["continuation_claim"] is not None or entry["no_effect_receipt"]["reset_identity"] != expected:
                raise pnsctl.OperatorError("NoEffect is claimed or crosses reset")
            self.assertEqual(entry["original_attempt"]["resource_affecting_action_key"], key)

        with self.parsers()[0], self.parsers()[1], self.parsers()[2], patch.object(
            delivery, "_validate_confirmed_no_effect_entry", side_effect=validated,
        ) as validate:
            completed = delivery._load_family_progress(state, reset_identity=source.reset)
            self.assertEqual(list(completed), ["gear"])
            self.assertEqual(progress.read_bytes(), retained_bytes)
            inventory = delivery._verify_retained_categories(completed, source.reset)
            self.assertEqual(list(inventory), ["gear"])
            self.assertGreater(validate.call_count, 1)
            references = completed["gear"][delivery._NO_EFFECT_ACCOUNTING_REFS]
            for changes in (
                {"continuation_claim": {"claimed": True}}, {"receipt_sha256": "f" * 64},
                {"recovery_session_directory": str(recovery / "missing")},
            ):
                with self.subTest(changes=changes), self.assertRaises(pnsctl.OperatorError):
                    delivery._verify_retained_categories({"gear": {
                        **completed["gear"], delivery._NO_EFFECT_ACCOUNTING_REFS: [{**references[0], **changes}],
                    }}, source.reset)
            encoded = receipt_path.read_bytes()
            receipt_path.write_text(json.dumps({**receipt, "reset_identity": "local-2026-10-28-enhancement-family"}), encoding="utf-8")
            with self.assertRaises(pnsctl.OperatorError):
                delivery._verify_retained_categories({"gear": {
                    **completed["gear"], delivery._NO_EFFECT_ACCOUNTING_REFS: [{**references[0],
                        "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest()}],
                }}, source.reset)
            receipt_path.write_bytes(encoded)
            delivery._write_family_progress(state, {"category_results": list(completed.values())})
        stored = json.loads(progress.read_text(encoding="utf-8"))["categories"]
        self.assertNotIn(delivery._NO_EFFECT_ACCOUNTING_REFS, stored["gear"])
        self.assertEqual(stored["chip"], json.loads(json.dumps(no_effect)))


if __name__ == "__main__":
    unittest.main()
