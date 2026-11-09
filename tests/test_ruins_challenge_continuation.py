from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tasks.ruins_challenge import KNOWN_CHALLENGE_IDENTITIES
from tasks.ruins_challenge_continuation import (
    CANONICAL_IDENTITIES,
    FLOW_ID,
    PACKAGE_ID,
    RUNTIME_PROFILE_ID,
    RuinsContinuationError,
    build_continuation,
    continuation_schema_digest,
    confirmed_claim_records,
    confirmed_identities,
    load_continuation,
    make_claim_record,
    validate_continuation,
    write_continuation,
)


class RuinsContinuationTests(unittest.TestCase):
    def _claim(self, root: Path, identity: str = "Hero Challenge"):
        frame = root / "session" / "frames" / f"{identity.replace(' ', '-').lower()}.png"
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(identity.encode("utf-8"))
        return make_claim_record(
            identity=identity,
            action_key=f"ruins:chest:{identity}:game-day-2026-07-16",
            post_frame_path=frame,
            post_frame_sha256=hashlib.sha256(frame.read_bytes()).hexdigest(),
            reset_identity="game-day-2026-07-16",
        )

    def test_exact_history_contract_has_twelve_categories(self):
        self.assertEqual(CANONICAL_IDENTITIES, KNOWN_CHALLENGE_IDENTITIES)
        self.assertEqual(len(CANONICAL_IDENTITIES), 12)

    def test_history_round_trip_is_evidence_bound_but_not_action_authority(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            claim = self._claim(root)
            path = write_continuation(
                root / "session" / "ruins-chest-history.json",
                reset_identity="game-day-2026-07-16",
                current_day="Thu",
                claims=[claim],
                evidence_root=root,
            )
            loaded = load_continuation(
                path,
                evidence_root=root,
                expected_reset_identity="game-day-2026-07-16",
                expected_current_day="Thu",
            )
            self.assertEqual(confirmed_identities(loaded), {"Hero Challenge"})
            self.assertEqual(loaded["flow_id"], FLOW_ID)
            self.assertEqual(loaded["runtime_profile_id"], RUNTIME_PROFILE_ID)
            self.assertEqual(loaded["package_id"], PACKAGE_ID)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["claims"][0]["status"], "confirmed")
            self.assertNotIn("medal_delta", loaded["claims"][0])
            # Earlier exports retain genuine reward observations, but those
            # numbers are not required to export a new positive Claim successor.
            claim["medal_delta"] = 100
            old = build_continuation(
                reset_identity="game-day-2026-07-16", current_day="Thu",
                claims=[claim], evidence_root=root,
            )
            self.assertEqual(old["claims"][0]["medal_delta"], 100)

    def test_history_digest_and_identity_mismatch_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload = build_continuation(
                reset_identity="game-day-2026-07-16",
                current_day="Thu",
                claims=[self._claim(root)],
                evidence_root=root,
            )
            for field, value in (
                ("reset_identity", "game-day-2026-07-17"),
                ("current_day", "Fri"),
                ("flow_id", "WRONG"),
            ):
                changed = dict(payload)
                changed[field] = value
                with self.subTest(field=field), self.assertRaises(RuinsContinuationError):
                    validate_continuation(
                        changed,
                        evidence_root=root,
                        expected_reset_identity="game-day-2026-07-16",
                        expected_current_day="Thu",
                    )
            changed = dict(payload, schema_digest="0" * 64)
            with self.assertRaises(RuinsContinuationError):
                validate_continuation(changed, evidence_root=root)

    def test_validated_historical_claim_records_are_read_only_evidence(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            claim = self._claim(root)
            path = write_continuation(
                root / "session" / "ruins-chest-history.json",
                reset_identity="game-day-2026-07-16",
                current_day="Thu",
                claims=[claim],
                evidence_root=root,
            )
            before = path.read_bytes()
            loaded = load_continuation(
                path,
                evidence_root=root,
                expected_reset_identity="game-day-2026-07-16",
                expected_current_day="Thu",
            )
            self.assertEqual(confirmed_claim_records(loaded), (loaded["claims"][0],))
            self.assertEqual(confirmed_identities(loaded), {"Hero Challenge"})
            self.assertEqual(path.read_bytes(), before)




    def test_legacy_new_claim_summary_is_rejected_by_history_schema(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "schema_name": "ruins_chest_continuation",
                "schema_version": 1,
                "flow_id": FLOW_ID,
                "reset_identity": "game-day-2026-07-16",
                "current_day": "Thu",
                "runtime_profile_id": RUNTIME_PROFILE_ID,
                "package_id": PACKAGE_ID,
                "canonical_identities": list(CANONICAL_IDENTITIES),
                "claims": [],
                "newly_claimed_chests": [{"identity": "Hero Challenge", "ruins_medals": 999}],
                "resource_delta": 999,
            }
            payload["schema_digest"] = continuation_schema_digest(payload)
            with self.assertRaises(RuinsContinuationError):
                validate_continuation(payload, evidence_root=root)


if __name__ == "__main__":
    unittest.main()
