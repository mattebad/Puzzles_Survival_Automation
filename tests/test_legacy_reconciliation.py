"""Focused provenance checks for the retained Nova/Noah legacy boundaries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.noahs_tavern_recruit_bluestacks import (
    _retained_capture_monotonic,
    _validate_retained_recruit_evidence,
    _validate_terminal_home_evidence,
)
from tasks.scheduler_task_result import SchedulerIdentity


def _write_frame(path: Path, content: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _event_capture(
    path: Path, digest: str, timestamp: str, *, captured_monotonic: float | None = None
) -> dict[str, object]:
    event: dict[str, object] = {
        "type": "capture", "path": str(path), "sha256": digest, "timestamp": timestamp
    }
    if captured_monotonic is not None:
        event["captured_monotonic"] = captured_monotonic
    return event


class LegacyReconciliationEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.identity = SchedulerIdentity(
            "account", "server", "reset", "recruitment-free-attempt-maintenance"
        )
        self.evidence = self.root / "evidence"
        self.frames = self.evidence / "frames"
        self.before = self.frames / "0002-step-001-source.png"
        self.result = self.frames / "0003-recruit-immediate-post.png"
        self.after = self.frames / "0005-recruit-after-close.png"
        before_sha = _write_frame(self.before, b"source")
        result_sha = _write_frame(self.result, b"result")
        after_sha = _write_frame(self.after, b"after")
        self.action_key = "ADV:prior-action:1:None"
        events = [
            _event_capture(self.before, before_sha, "2026-10-29T10:00:00+00:00", captured_monotonic=100.0),
            {
                "type": "dispatch",
                "execute": True,
                "action_key": self.action_key,
                "source_sha256": before_sha,
                "timestamp": "2026-10-29T10:00:01+00:00",
            },
            _event_capture(self.result, result_sha, "2026-10-29T10:00:02+00:00", captured_monotonic=102.0),
            {
                "type": "dispatch",
                "execute": True,
                "action_key": f"{self.action_key}:close",
                "source_sha256": result_sha,
                "timestamp": "2026-10-29T10:00:03+00:00",
            },
            _event_capture(self.after, after_sha, "2026-10-29T10:00:04+00:00", captured_monotonic=104.0),
        ]
        self.evidence.mkdir(parents=True, exist_ok=True)
        (self.evidence / "events.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
        )
        (self.evidence / "unified-recruitment-result.json").write_text(
            json.dumps({"status": "unresolved", "identity": self.identity.__dict__}), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_linked_replay_uses_recorded_utc_and_accepts_once(self) -> None:
        result = _validate_retained_recruit_evidence(
            self.evidence,
            before_path=self.before,
            result_path=self.result,
            after_path=self.after,
            identity=self.identity,
        )
        self.assertEqual(result["action_key"], self.action_key)
        self.assertEqual(result["after_at_utc"], "2026-10-29T10:00:04+00:00")
        self.assertIsInstance(result["after_epoch"], float)
        self.assertGreater(result["after_epoch"], result["result_epoch"])
        self.assertEqual(_retained_capture_monotonic(self.evidence, self.before), 100.0)

    def test_unlinked_or_tampered_source_is_rejected(self) -> None:
        self.before.write_bytes(b"tampered")
        with self.assertRaisesRegex(RuntimeError, "evidence_required"):
            _validate_retained_recruit_evidence(
                self.evidence,
                before_path=self.before,
                result_path=self.result,
                after_path=self.after,
                identity=self.identity,
            )

    def test_missing_monotonic_does_not_fall_back_to_wall_clock(self) -> None:
        events = [json.loads(line) for line in (self.evidence / "events.jsonl").read_text().splitlines()]
        for event in events:
            if event.get("type") == "capture":
                event.pop("captured_monotonic", None)
        (self.evidence / "events.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
        )
        self.assertIsNone(_retained_capture_monotonic(self.evidence, self.before))
        with self.assertRaisesRegex(RuntimeError, "evidence_required"):
            _validate_retained_recruit_evidence(
                self.evidence,
                before_path=self.before,
                result_path=self.result,
                after_path=self.after,
                identity=self.identity,
            )

    def test_terminal_successor_requires_linked_safe_exit(self) -> None:
        terminal = self.root / "terminal"
        terminal_frames = terminal / "frames"
        source = terminal_frames / "0002-safe-exit-source.png"
        immediate = terminal_frames / "0003-safe-exit-post.png"
        settled = terminal_frames / "0004-tavern-safe-exit-settled.png"
        source_sha = _write_frame(source, b"terminal-source")
        immediate_sha = _write_frame(immediate, b"terminal-immediate")
        settled_sha = _write_frame(settled, b"terminal-settled")
        terminal.mkdir(parents=True, exist_ok=True)
        events = [
            _event_capture(source, source_sha, "2026-10-29T10:01:00+00:00"),
            {
                "type": "dispatch",
                "execute": True,
                "action_key": f"noah-nav:safe-exit:{source_sha}",
                "source_sha256": source_sha,
                "timestamp": "2026-10-29T10:01:01+00:00",
            },
            _event_capture(immediate, immediate_sha, "2026-10-29T10:01:02+00:00"),
            _event_capture(settled, settled_sha, "2026-10-29T10:01:03+00:00"),
        ]
        (terminal / "events.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
        )
        (terminal / "safe-exit-only-result.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "terminal_home_verified": True,
                    "records": [
                        {
                            "source_sha256": source_sha,
                            "immediate_post_sha256": immediate_sha,
                            "successor_sha256": settled_sha,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(
            _validate_terminal_home_evidence(terminal, terminal_path=settled)["terminal_sha256"],
            settled_sha,
        )
        (terminal / "safe-exit-only-result.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "terminal_home_verified": True,
                    "records": [{"source_sha256": source_sha, "immediate_post_sha256": immediate_sha, "successor_sha256": "0" * 64}],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RuntimeError, "evidence_required"):
            _validate_terminal_home_evidence(terminal, terminal_path=settled)


if __name__ == "__main__":
    unittest.main()
