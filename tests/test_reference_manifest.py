import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "research" / "gnbots_trial_reference_manifest.json"
EXPECTED_MODULES = {
    "puzzlebot.base.alliancebase",
    "puzzlebot.base.base",
    "puzzlebot.base.dailies",
    "puzzlebot.base.gameconfig",
    "puzzlebot.base.gathervip",
    "puzzlebot.base.launchlib",
    "puzzlebot.base.recruitment",
    "puzzlebot.base.tilebase",
    "puzzlebot.base.townbase",
    "puzzlebot.base.townpaths",
    "puzzlebot.base.wall",
    "puzzlebot.base.worldbase",
}


class ReferenceManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_all_authorized_modules_have_stable_entries(self):
        self.assertEqual(set(self.manifest["modules"]), EXPECTED_MODULES)
        covered = {entry["module"] for entry in self.manifest["entries"]}
        self.assertEqual(covered, EXPECTED_MODULES)
        ids = [entry["id"] for entry in self.manifest["entries"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(item.startswith("GNB-") for item in ids))

    def test_required_flow_fields_are_present(self):
        required = {
            "id",
            "module",
            "flow",
            "basis",
            "points",
            "rois",
            "tries",
            "confirms",
            "waits_ms",
            "loop_bound",
            "source_state",
            "expected_destination",
            "recovery",
            "completion",
        }
        for entry in self.manifest["entries"]:
            with self.subTest(entry=entry["id"]):
                self.assertFalse(required - entry.keys())
                self.assertIn(entry["basis"], {"direct", "inferred", "mixed"})

    def test_xywh_rois_are_normalized_as_endpoints(self):
        checked = 0
        for entry in self.manifest["entries"]:
            for roi in entry["rois"]:
                x, y, width, height = roi["source_xywh"]
                x1, y1, x2, y2 = roi["normalized_xyxy"]
                with self.subTest(entry=entry["id"], template=roi["template"]):
                    self.assertEqual((x1, y1), (x, y))
                    self.assertEqual((x2, y2), (x + width, y + height))
                    if width != x2:
                        self.assertNotEqual(
                            roi["source_xywh"],
                            roi["normalized_xyxy"],
                            "xywh must not be treated as absolute xyxy",
                        )
                checked += 1
        self.assertGreaterEqual(checked, 40)

    def test_reference_tree_is_not_a_runtime_dependency(self):
        forbidden = (".local-reference", "gnbots-trial", "decoded/scripts")
        for folder in ("safe_action_core", "tasks", "scripts"):
            for path in (ROOT / folder).rglob("*.py"):
                text = path.read_text(encoding="utf-8")
                with self.subTest(path=path.relative_to(ROOT)):
                    self.assertFalse(any(marker in text for marker in forbidden))

    def test_restrictions_are_fail_closed(self):
        restrictions = self.manifest["restrictions"]
        self.assertFalse(restrictions["execute_vendor_code"])
        self.assertFalse(restrictions["runtime_dependency_allowed"])
        self.assertFalse(restrictions["copy_vendor_images_to_runtime"])
        self.assertFalse(restrictions["vendor_selector_allowed"])


if __name__ == "__main__":
    unittest.main()
