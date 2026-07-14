import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import evidence_hygiene as hygiene


class EvidenceHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()

    def tearDown(self):
        self.tempdir.cleanup()

    def write(self, relative, payload=b"payload"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def init_git(self):
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)

    def git_add(self, *paths):
        subprocess.run(["git", "add", *paths], cwd=self.root, check=True)

    def test_streaming_sha256_uses_bounded_chunks(self):
        path = self.write("evidence/large.bin", b"abc" * 4097)
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        digest, size = hygiene.sha256_stream(path, chunk_size=7)
        self.assertEqual((digest, size), (expected, path.stat().st_size))

    def test_duplicate_grouping_is_deterministic(self):
        records = [
            {"relative_path": "evidence/z", "sha256": "a"},
            {"relative_path": "evidence/a", "sha256": "a"},
            {"relative_path": "evidence/one", "sha256": "b"},
        ]
        groups = hygiene.group_duplicates(records)
        self.assertEqual(list(groups), ["a"])
        self.assertEqual([item["relative_path"] for item in groups["a"]], ["evidence/a", "evidence/z"])

    def test_tracked_untracked_and_ignored_classification(self):
        self.init_git()
        self.write("evidence/tracked.txt")
        self.write("evidence/untracked.txt")
        self.write("evidence/ignored.txt")
        self.write(".gitignore", b"/evidence/ignored.txt\n")
        self.git_add("evidence/tracked.txt", ".gitignore")
        states = hygiene.git_path_sets(self.root, self.evidence)
        self.assertIn("evidence/tracked.txt", states["tracked"])
        self.assertIn("evidence/untracked.txt", states["untracked"])
        self.assertIn("evidence/ignored.txt", states["ignored"])

    def test_reference_scanning_records_source_kind(self):
        self.init_git()
        self.write("evidence/sessions/demo/source.png", b"x")
        self.write("README.md", b"See evidence/sessions/demo/source.png for the fixture.\n")
        self.git_add("README.md")
        refs = hygiene.scan_references(self.root, {"evidence/sessions/demo/source.png"})
        self.assertEqual(refs["evidence/sessions/demo/source.png"], [{"path": "README.md", "kind": "repository-text"}])

    def test_protected_consequential_and_unresolved_classes(self):
        decisive, protected = hygiene.classify_retention(
            relative="evidence/sessions/live-claim-success-020/claim-post.png",
            status="untracked", session="live-claim-success-020", reference_entries=[],
            journal_entries=[], journal_meta=None, unresolved_session=False,
        )
        self.assertEqual((decisive, protected), ("DECISIVE_CONSEQUENTIAL_EVIDENCE", True))
        unresolved, protected = hygiene.classify_retention(
            relative="evidence/sessions/live-session/frame.png", status="untracked",
            session="live-session", reference_entries=[], journal_entries=[], journal_meta=None,
            unresolved_session=True,
        )
        self.assertEqual((unresolved, protected), ("UNRESOLVED_ACTION_EVIDENCE", True))
        journal, protected = hygiene.classify_retention(
            relative="evidence/sessions/live/actions.sqlite3", status="untracked",
            session="live", reference_entries=[], journal_entries=[],
            journal_meta={"kind": "JOURNAL_SOURCE"}, unresolved_session=False,
        )
        self.assertEqual((journal, protected), ("JOURNAL_SOURCE", True))

    def test_archive_path_is_content_addressed_and_external_only(self):
        digest = "a" * 64
        archive = self.root.parent / "external-archive"
        self.assertEqual(hygiene.archive_blob_path(archive, digest), archive / "blobs" / digest)
        with self.assertRaises(hygiene.HygieneError):
            hygiene.archive_audit({"audit_id": "x", "records": []}, self.root, self.root / "inside", execute=True)

    def simple_audit(self, path):
        digest, size = hygiene.sha256_stream(path)
        return {
            "schema": hygiene.AUDIT_SCHEMA,
            "audit_id": "fixture-audit",
            "records": [{
                "relative_path": path.relative_to(self.root).as_posix(), "sha256": digest, "size": size,
                "git_status": "untracked", "file_type": "text/plain",
                "proposed_action": "ARCHIVE_AND_REMOVE_DUPLICATE",
            }],
        }

    def test_dry_run_never_removes_or_creates_archive(self):
        self.init_git()
        path = self.write("evidence/session/duplicate.txt", b"duplicate")
        archive = self.root.parent / "dry-run-archive"
        result = hygiene.archive_audit(self.simple_audit(path), self.root, archive, execute=False)
        self.assertTrue(result["dry_run"])
        self.assertTrue(path.exists())
        self.assertFalse(archive.exists())

    def test_archive_verifies_before_removal_and_is_restartable(self):
        self.init_git()
        path = self.write("evidence/session/duplicate.txt", b"duplicate")
        archive = self.root.parent / ("verified-archive-" + self.root.name)
        audit = self.simple_audit(path)
        result = hygiene.archive_audit(audit, self.root, archive, execute=True)
        self.assertEqual(result["entries"][0]["status"], "source_removed")
        self.assertFalse(path.exists())
        self.assertTrue(hygiene.verify_archive(archive)["verified"])
        restarted = hygiene.archive_audit(audit, self.root, archive, execute=True)
        self.assertEqual(restarted["entries"][0]["status"], "source_removed")

    def test_archive_failure_leaves_source_in_place(self):
        self.init_git()
        path = self.write("evidence/session/duplicate.txt", b"duplicate")
        archive = self.root.parent / "failed-archive"
        with mock.patch.object(hygiene, "_copy_and_verify", side_effect=hygiene.HygieneError("bad blob")):
            with self.assertRaises(hygiene.HygieneError):
                hygiene.archive_audit(self.simple_audit(path), self.root, archive, execute=True)
        self.assertTrue(path.exists())

    def test_symlink_rejection_and_local_reference_exclusion(self):
        outside = self.root / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        (self.evidence / "link").symlink_to(outside)
        with self.assertRaises(hygiene.SymlinkSafetyError):
            list(hygiene.iter_regular_files(self.evidence))
        safe = self.root / "safe-evidence"
        safe.mkdir()
        (safe / ".local-reference").mkdir()
        (safe / ".local-reference" / "vendor.js").write_text("vendor", encoding="utf-8")
        self.assertEqual(list(hygiene.iter_regular_files(safe)), [])
        with self.assertRaises(hygiene.HygieneError):
            list(hygiene.iter_regular_files(self.root / ".local-reference"))

    def test_audit_manifest_is_deterministic_for_fixed_input(self):
        self.init_git()
        self.write("evidence/sessions/demo/source.png", b"same")
        self.write("evidence/sessions/demo/copy.png", b"same")
        self.git_add("evidence/sessions/demo/source.png")
        first = hygiene.build_audit(self.root, self.evidence, include_history=False, generated_at="fixed")
        second = hygiene.build_audit(self.root, self.evidence, include_history=False, generated_at="fixed")
        self.assertEqual(first["audit_id"], second["audit_id"])
        self.assertEqual(first["records"], second["records"])

    def test_tool_does_not_contain_history_rewrite_commands(self):
        source = Path(hygiene.__file__).read_text(encoding="utf-8")
        for forbidden in ("filter-repo", "BFG", "reflog expire", "gc --prune", "reset --hard", "push --force"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
