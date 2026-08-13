from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tasks.ruins_challenge_continuation import (
    CANONICAL_IDENTITIES,
    FLOW_ID,
    PACKAGE_ID,
    RUNTIME_PROFILE_ID,
    RuinsContinuationError,
    build_continuation,
    continuation_schema_digest,
    confirmed_identities,
    load_continuation,
    make_claim_record,
    validate_continuation,
    write_continuation,
)
from scripts import flow_delivery_ruins_challenge_bluestacks as ruins_delivery
from scripts import ruins_challenge_bluestacks as ruins_operator


EXACT_IDENTITIES = (
    "Hero Challenge", "Weapon Trial", "Tech Challenge", "Gear Challenge",
    "Core Challenge", "Nova Challenge", "Module Challenge", "Glory Challenge",
    "Bioenhancer Challenge", "Ultimate Challenge", "Chip Challenge", "Cube Challenge",
)


class RuinsContinuationTests(unittest.TestCase):
    def _claim(self, root: Path, identity: str = "Hero Challenge", *, status: str = "confirmed"):
        frame = root / "session" / "frames" / f"{identity.replace(' ', '-').lower()}.png"
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(identity.encode("utf-8"))
        digest = hashlib.sha256(frame.read_bytes()).hexdigest()
        claim = make_claim_record(
            identity=identity,
            action_key=f"ruins:chest:reset:{identity}:before",
            medal_delta=100,
            post_frame_path=frame,
            post_frame_sha256=digest,
            reset_identity="reset-1",
        )
        claim["status"] = status
        return claim

    def test_exact_literal_contract_has_twelve_rows(self):
        self.assertEqual(CANONICAL_IDENTITIES, EXACT_IDENTITIES)
        self.assertEqual(len(CANONICAL_IDENTITIES), 12)

    def test_round_trip_persists_only_confirmed_and_binds_identity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            claim = self._claim(root)
            path = write_continuation(
                root / "session" / "ruins-chest-continuation.json",
                reset_identity="reset-1",
                current_day="Wed",
                claims=[claim],
                evidence_root=root,
            )
            loaded = load_continuation(
                path,
                evidence_root=root,
                expected_reset_identity="reset-1",
                expected_current_day="Wed",
            )
            self.assertEqual(confirmed_identities(loaded), {"Hero Challenge"})
            self.assertEqual(loaded["flow_id"], FLOW_ID)
            self.assertEqual(loaded["runtime_profile_id"], RUNTIME_PROFILE_ID)
            self.assertEqual(loaded["package_id"], PACKAGE_ID)

    def test_round_trip_nested_flow_layout_reloads_with_inferred_flow_root(self):
        with TemporaryDirectory() as directory:
            capture_root = Path(directory) / ".local-captures" / "flow-delivery" / FLOW_ID
            session = capture_root / "nav-001" / "session-001"
            claim = self._claim(capture_root)
            # Re-home the fixture evidence under the exact child session layout.
            source = Path(claim["post_frame_path"])
            nested_frame = session / "frames" / "post.png"
            nested_frame.parent.mkdir(parents=True, exist_ok=True)
            nested_frame.write_bytes(source.read_bytes())
            digest = hashlib.sha256(nested_frame.read_bytes()).hexdigest()
            claim = make_claim_record(
                identity="Hero Challenge",
                action_key="ruins:chest:nested",
                medal_delta=1,
                post_frame_path=nested_frame,
                post_frame_sha256=digest,
                reset_identity="reset-1",
            )
            checkpoint = write_continuation(
                session / "ruins-chest-continuation.json",
                reset_identity="reset-1",
                current_day="Wed",
                claims=[claim],
                evidence_root=capture_root,
            )
            loaded = load_continuation(
                checkpoint,
                expected_reset_identity="reset-1",
                expected_current_day="Wed",
            )
            self.assertEqual(confirmed_identities(loaded), {"Hero Challenge"})
            self.assertEqual(loaded["claims"][0]["post_frame_path"], "nav-001/session-001/frames/post.png")

    def test_digest_and_identity_mismatch_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload = build_continuation(
                reset_identity="reset-1", current_day="Wed", claims=[self._claim(root)], evidence_root=root
            )
            for field, value in (("reset_identity", "reset-2"), ("current_day", "Thu"), ("flow_id", "WRONG")):
                changed = dict(payload)
                changed[field] = value
                with self.subTest(field=field), self.assertRaises(RuinsContinuationError):
                    validate_continuation(changed, evidence_root=root, expected_reset_identity="reset-1", expected_current_day="Wed")
            changed = dict(payload)
            changed["schema_digest"] = "0" * 64
            with self.assertRaises(RuinsContinuationError):
                validate_continuation(changed, evidence_root=root)

    def test_missing_required_schema_identity_and_arbitrary_build_contract_fail(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload = build_continuation(
                reset_identity="reset-1", current_day="Wed", claims=[self._claim(root)], evidence_root=root
            )
            for field in ("schema_name", "package_id", "runtime_profile_id", "reset_identity", "current_day"):
                changed = dict(payload)
                changed.pop(field)
                changed["schema_digest"] = continuation_schema_digest(changed)
                with self.subTest(field=field), self.assertRaises(RuinsContinuationError):
                    validate_continuation(changed, evidence_root=root)
            with self.assertRaises(RuinsContinuationError):
                build_continuation(
                    reset_identity="reset-1", current_day="Wed", claims=[], evidence_root=root,
                    runtime_profile_id="wrong-profile",
                )
            with self.assertRaises(RuinsContinuationError):
                build_continuation(
                    reset_identity="reset-1", current_day="Wed", claims=[], evidence_root=root,
                    package_id="wrong.package",
                )

    def test_flow_validator_rejects_skeletal_confirmed_claim(self):
        ids = list(EXACT_IDENTITIES)
        result = {
            "flow_id": FLOW_ID,
            "reset_identity": "reset-1",
            "resource_delta": 0,
            "ruins_result": {
                "status": "completed",
                "reason": "verified_safe_exit_to_home",
                "chests_only": True,
                "chest_coverage": {identity: "already claimed" for identity in ids},
                "newly_claimed_chests": [],
                "confirmed_claim_records": [{"identity": "Hero Challenge", "status": "confirmed", "reset_identity": "reset-1"}],
            },
        }
        structure = {"result": result, "session_directory": ".", "actions": []}
        queue = {"flows": [{"flow_id": FLOW_ID, "live_attempt_count": 0, "maximum_live_attempts": 1}]}
        fake_pnsctl = SimpleNamespace(OperatorError=ValueError)
        with patch.object(ruins_delivery, "_pnsctl", return_value=fake_pnsctl), self.assertRaisesRegex(ValueError, "claim evidence rejected"):
            ruins_delivery.verify_ruins_challenge_home_atlas(structure, queue, {})

    def test_operator_rejects_continuation_without_chests_only(self):
        with patch.object(ruins_operator.LocalBlueStacksRuntime, "connect", side_effect=AssertionError("must reject before runtime connect")):
            with self.assertRaises(SystemExit) as raised:
                ruins_operator.main([
                    "--adb", "adb", "--serial", "emulator-5554",
                    "--reset-identity", "reset-1", "--current-day", "Wed",
                    "--claim-chests", "--chest-continuation", "checkpoint.json",
                ])
            self.assertEqual(raised.exception.code, 2)

    def test_operator_rejects_malformed_continuation_before_runtime_connect(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "bad.json"
            checkpoint.write_text("{}", encoding="utf-8")
            with patch.object(ruins_operator.LocalBlueStacksRuntime, "connect", side_effect=AssertionError("must reject before runtime connect")):
                with self.assertRaises(SystemExit) as raised:
                    ruins_operator.main([
                        "--adb", "adb", "--serial", "emulator-5554",
                        "--reset-identity", "reset-1", "--current-day", "Wed",
                        "--chests-only", "--chest-continuation", str(checkpoint),
                    ])
                self.assertEqual(raised.exception.code, 2)

    def test_resumed_terminal_verifier_reloads_prior_checkpoint_at_prior_root(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            flow_root = root / ".local-captures" / "flow-delivery" / FLOW_ID
            prior = write_continuation(
                flow_root / "nav-old" / "session-old" / "ruins-chest-continuation.json",
                reset_identity="reset-1",
                current_day="Wed",
                claims=[],
                evidence_root=flow_root,
            )
            result = {
                "flow_id": FLOW_ID,
                "reset_identity": "reset-1",
                "current_day": "Wed",
                "prior_continuation_reference": str(prior),
                "resource_delta": 0,
                "terminal_runtime_state": "recognized_home",
                "ruins_result": {
                    "status": "completed",
                    "reason": "verified_safe_exit_to_home",
                    "chests_only": True,
                    "chest_coverage": {identity: "already claimed" for identity in EXACT_IDENTITIES},
                    "newly_claimed_chests": [],
                    "confirmed_claim_records": [],
                },
            }
            structure = {"result": result, "session_directory": str(root / "new-session"), "actions": []}
            queue = {"flows": [{"flow_id": FLOW_ID, "live_attempt_count": 0, "maximum_live_attempts": 1}]}
            verified = ruins_delivery.verify_ruins_challenge_home_atlas(structure, queue, {})
            self.assertEqual(verified["status"], "verified")

    def test_prior_only_resumed_terminal_mints_new_checkpoint_reference(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reset_identity = f"local-{datetime.now(timezone.utc).date().isoformat()}-ruins-home-atlas"
            current_day = datetime.now().strftime("%a")
            prior_flow = root / "prior" / FLOW_ID
            prior_frame = prior_flow / "nav-old" / "session-old" / "frames" / "post.png"
            prior_frame.parent.mkdir(parents=True, exist_ok=True)
            prior_frame.write_bytes(b"prior")
            prior_hash = hashlib.sha256(prior_frame.read_bytes()).hexdigest()
            prior_claim = make_claim_record(
                identity="Hero Challenge", action_key="prior-action", medal_delta=1,
                post_frame_path=prior_frame, post_frame_sha256=prior_hash,
                reset_identity=reset_identity,
            )
            prior_checkpoint = write_continuation(
                prior_flow / "nav-old" / "session-old" / "ruins-chest-continuation.json",
                reset_identity=reset_identity, current_day=current_day, claims=[prior_claim], evidence_root=prior_flow,
            )
            import scripts.pnsctl as pnsctl
            ids = list(EXACT_IDENTITIES)

            def fake_run(command, **_kwargs):
                output = Path(command[command.index("--output-directory") + 1])
                child = output / "child"
                frames = child / "frames"
                frames.mkdir(parents=True, exist_ok=True)
                frame = frames / "0001-home.png"
                frame.write_bytes(b"current")
                digest = hashlib.sha256(frame.read_bytes()).hexdigest()
                (child / "events.jsonl").write_text(
                    json.dumps({"type": "capture", "path": str(frame), "sha256": digest}) + "\n",
                    encoding="utf-8",
                )
                operator = {
                    "status": "completed", "reason": "verified_safe_exit_to_home", "actions_completed": 0,
                    "chests_only": True, "resource_delta": 0,
                    "chest_coverage": {identity: "already claimed" for identity in ids},
                    "newly_claimed_chests": [], "confirmed_claim_records": [],
                }
                return subprocess.CompletedProcess(command, 0, json.dumps(operator), "")

            with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root / "new"), patch.object(
                ruins_delivery.subprocess, "run", side_effect=fake_run
            ):
                output = json.loads(ruins_delivery.run_ruins_challenge_home_atlas(
                    {}, {"owner": "test", "development_session": True, "chests_only": True},
                    live=True, chest_continuation=prior_checkpoint,
                ))
            self.assertIsNotNone(output["continuation_reference"])
            new_checkpoint = Path(output["continuation_reference"])
            loaded = load_continuation(new_checkpoint, expected_reset_identity=reset_identity, expected_current_day=current_day)
            self.assertEqual(confirmed_identities(loaded), {"Hero Challenge"})

    def test_prior_evidence_rebase_is_session_scoped_and_collision_free(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current_flow = root / "current" / FLOW_ID
            current_session = current_flow / "nav-new" / "session-new"
            prior_records = []
            checkpoints = []
            for ordinal, identity, payload in ((1, "Hero Challenge", b"old-a"), (2, "Weapon Trial", b"old-b")):
                prior_flow = root / f"prior-{ordinal}" / FLOW_ID
                frame = prior_flow / "nav-old" / "session-old" / "frames" / "post.png"
                frame.parent.mkdir(parents=True, exist_ok=True)
                frame.write_bytes(payload)
                digest = hashlib.sha256(payload).hexdigest()
                claim = make_claim_record(
                    identity=identity, action_key=f"prior-{ordinal}", medal_delta=1,
                    post_frame_path=frame, post_frame_sha256=digest, reset_identity="reset-1",
                )
                checkpoint = write_continuation(
                    prior_flow / "nav-old" / "session-old" / "ruins-chest-continuation.json",
                    reset_identity="reset-1", current_day="Wed", claims=[claim], evidence_root=prior_flow,
                )
                checkpoints.append(checkpoint)
            rebased = []
            for checkpoint in checkpoints:
                loaded = load_continuation(checkpoint, expected_reset_identity="reset-1", expected_current_day="Wed")
                records = ruins_delivery._rebase_prior_records(
                    list(loaded["claims"]), prior_checkpoint=checkpoint,
                    new_flow_root=current_flow, destination_session=current_session,
                )
                rebased.append(records)
            current_session.mkdir(parents=True, exist_ok=True)
            for ordinal, records in enumerate(rebased, 1):
                output = write_continuation(
                    current_session / f"checkpoint-{ordinal}.json",
                    reset_identity="reset-1", current_day="Wed", claims=records, evidence_root=current_flow,
                )
                loaded = load_continuation(output, expected_reset_identity="reset-1", expected_current_day="Wed")
                self.assertEqual(len(loaded["claims"]), 1)
            self.assertEqual(len(list((current_session / "prior-evidence").iterdir())), 2)

    def test_unresolved_duplicate_typo_and_path_escape_are_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = self._claim(root)
            payload = build_continuation(reset_identity="reset-1", current_day="Wed", claims=[first], evidence_root=root)
            bad_status = dict(payload)
            bad_status["claims"] = [dict(first, status="unresolved")]
            bad_status["schema_digest"] = continuation_schema_digest(bad_status)
            with self.assertRaises(RuinsContinuationError):
                validate_continuation(bad_status, evidence_root=root)
            typo = dict(first, identity="Hero ChallengE")
            with self.assertRaises(RuinsContinuationError):
                build_continuation(reset_identity="reset-1", current_day="Wed", claims=[typo], evidence_root=root)
            duplicate = [first, self._claim(root, "Weapon Trial")]
            duplicate[1]["action_key"] = duplicate[0]["action_key"]
            with self.assertRaises(RuinsContinuationError):
                build_continuation(reset_identity="reset-1", current_day="Wed", claims=duplicate, evidence_root=root)
            escape = dict(first, post_frame_path="../outside.png", post_frame_sha256="0" * 64)
            with self.assertRaises(RuinsContinuationError):
                build_continuation(reset_identity="reset-1", current_day="Wed", claims=[escape], evidence_root=root)

    def test_newly_claimed_resource_delta_is_not_a_checkpoint_record(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "schema_name": "ruins_chest_continuation",
                "schema_version": 1,
                "flow_id": FLOW_ID,
                "reset_identity": "reset-1",
                "current_day": "Wed",
                "runtime_profile_id": RUNTIME_PROFILE_ID,
                "package_id": PACKAGE_ID,
                "canonical_identities": list(EXACT_IDENTITIES),
                "claims": [],
                "newly_claimed_chests": [{"identity": "Hero Challenge", "ruins_medals": 999}],
                "resource_delta": 999,
            }
            payload["schema_digest"] = continuation_schema_digest(payload)
            with self.assertRaises(RuinsContinuationError):
                validate_continuation(payload, evidence_root=root)


if __name__ == "__main__":
    unittest.main()
