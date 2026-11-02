"""Interrupted mutable progress writes preserve the last complete document."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import flow_delivery_enhancement_bluestacks as delivery


class EnhancementAtomicProgressTests(unittest.TestCase):
    def initial(self, root):
        path = root / "family-progress.json"
        categories = {"gear": {"status": "completed", "resource_affecting_action_key": "retained-gear"},
                      "chip": {"status": "dispatch_bearing_unresolved", "continuation_claim": {"invocation_id": "claimed"}}}
        delivery._atomic_family_progress(path, categories)
        return path, categories, path.read_bytes()

    def test_complete_replacement_preserves_unresolved_and_claimed_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path, categories, _old = self.initial(Path(folder))
            delivery._atomic_family_progress(path, {**categories, "module": {"status": "completed"}})
            result = json.loads(path.read_bytes())
            self.assertEqual(result["categories"]["gear"], categories["gear"])
            self.assertEqual(result["categories"]["chip"], categories["chip"])
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_flush_or_replace_failure_keeps_previous_valid_bytes(self):
        for operation in ("fsync", "replace"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as folder:
                path, categories, old = self.initial(Path(folder))
                with patch.object(delivery.os, operation, side_effect=OSError("injected write failure")):
                    with self.assertRaises(OSError):
                        delivery._atomic_family_progress(path, {"gear": {"status": "new"}})
                self.assertEqual(path.read_bytes(), old)
                self.assertEqual(json.loads(path.read_bytes())["categories"], categories)
                self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_first_write_failure_does_not_publish_partial_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "family-progress.json"
            with patch.object(delivery.os, "fsync", side_effect=OSError("injected flush failure")):
                with self.assertRaises(OSError):
                    delivery._atomic_family_progress(path, {"gear": {"status": "pending"}})
            self.assertFalse(path.exists())
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_process_termination_before_replace_preserves_durable_claims(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path, _categories, old = self.initial(root)
            marker = root / "ready"
            code = """import sys,time
from pathlib import Path
from scripts import flow_delivery_enhancement_bluestacks as d
def pause(source,destination):
    Path(sys.argv[2]).write_text('ready')
    time.sleep(60)
d.os.replace=pause
d._atomic_family_progress(Path(sys.argv[1]), {'gear': {'status': 'replacement'}})
"""
            env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
            child = subprocess.Popen([sys.executable, "-B", "-c", code, str(path), str(marker)],
                cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                deadline = time.monotonic() + 20
                while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(marker.exists(), "writer did not reach flushed temporary state")
                child.terminate()
                child.communicate(timeout=5)
                self.assertEqual(path.read_bytes(), old)
                self.assertEqual(json.loads(path.read_bytes())["categories"]["chip"]["continuation_claim"]["invocation_id"], "claimed")
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
