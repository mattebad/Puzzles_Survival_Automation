import hashlib
import json
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

    def test_directory_reference_does_not_blanket_protect_descendants(self):
        self.init_git()
        self.write("evidence/sessions/demo/source.png", b"x")
        self.write("README.md", b"Review evidence/sessions/demo/ as the session entry point.\n")
        self.git_add("README.md")
        refs = hygiene.scan_references(self.root, {"evidence/sessions/demo/source.png"})
        self.assertEqual(refs, {})

    def test_protected_consequential_and_unresolved_classes(self):
        decisive, protected = hygiene.classify_retention(
            relative="evidence/sessions/live-claim-success-020/claim-post.png",
            status="untracked", session="live-claim-success-020", reference_entries=[],
            journal_entries=[], journal_meta=None, unresolved_session=False,
        )
        self.assertEqual((decisive, protected), ("DECISIVE_CONSEQUENTIAL_EVIDENCE", True))
        completed_live, protected = hygiene.classify_retention(
            relative="evidence/sessions/20260716-ruins-challenge/chest-postcondition.png",
            status="untracked", session="20260716-ruins-challenge", reference_entries=[],
            journal_entries=[], journal_meta=None, unresolved_session=False,
        )
        self.assertEqual((completed_live, protected), ("DECISIVE_CONSEQUENTIAL_EVIDENCE", True))
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
        sibling = self.root / ".." / ("outside-" + self.root.name)
        result = hygiene.archive_audit({"audit_id": "x", "records": []}, self.root, sibling, execute=False)
        self.assertEqual(result["archive_root"], ".")

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
        digest = result["entries"][0]["sha256"]
        self.assertEqual(result["entries"][0]["blob"], f"blobs/{digest}")
        self.assertFalse(path.exists())
        self.assertTrue(hygiene.verify_archive(archive)["verified"])
        path_index = json.loads((archive / "path-index.json").read_text(encoding="utf-8"))
        indexed = path_index["evidence/session/duplicate.txt"]
        self.assertEqual(indexed["blob"], f"blobs/{digest}")
        self.assertEqual(indexed["manifest"], "manifests/operation-fixture-audit.json")
        restarted = hygiene.archive_audit(audit, self.root, archive, execute=True)
        self.assertEqual(restarted["entries"][0]["status"], "source_removed")

    def test_verify_legacy_absolute_blob_reference_uses_content_addressed_root(self):
        archive = self.root.parent / ("legacy-archive-" + self.root.name)
        payload = b"legacy"
        digest = hashlib.sha256(payload).hexdigest()
        blob = archive / "blobs" / digest
        blob.parent.mkdir(parents=True)
        blob.write_bytes(payload)
        manifest = archive / "manifests" / "operation-legacy.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({
            "schema": "evidence-archive-operation-v1",
            "audit_id": "legacy",
            "entries": [{
                "relative_path": "evidence/legacy.bin",
                "sha256": digest,
                "size": len(payload),
                "blob": "/mnt/c/obsolete/archive/blobs/" + digest,
                "status": "source_removed",
            }],
        }), encoding="utf-8")
        self.assertTrue(hygiene.verify_archive(archive)["verified"])

    def test_archive_failure_leaves_source_in_place(self):
        self.init_git()
        path = self.write("evidence/session/duplicate.txt", b"duplicate")
        archive = self.root.parent / "failed-archive"
        with mock.patch.object(hygiene, "_copy_and_verify", side_effect=hygiene.HygieneError("bad blob")):
            with self.assertRaises(hygiene.HygieneError):
                hygiene.archive_audit(self.simple_audit(path), self.root, archive, execute=True)
        self.assertTrue(path.exists())

    def test_atomic_json_write_retries_transient_windows_lock(self):
        destination = self.root / "manifest.json"
        real_replace = hygiene.os.replace
        attempts = 0

        def transient_replace(source, target):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise PermissionError("transient lock")
            return real_replace(source, target)

        with mock.patch.object(hygiene.os, "replace", side_effect=transient_replace):
            hygiene._write_json(destination, {"ok": True})
        self.assertEqual(attempts, 3)
        self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), {"ok": True})

    def test_reviewed_exact_path_archive_requires_reason_and_rejects_tracked(self):
        self.init_git()
        path = self.write("evidence/session/transfer.zip.001", b"transfer")
        with self.assertRaises(hygiene.HygieneError):
            hygiene.build_reviewed_archive_audit(self.root, ["evidence/session/transfer.zip.001"], "")
        audit = hygiene.build_reviewed_archive_audit(
            self.root, ["evidence/session/transfer.zip.001"], "reviewed transfer package"
        )
        self.assertEqual(audit["records"][0]["proposed_action"], "ARCHIVE_AND_REMOVE_REVIEWED")
        self.git_add("evidence/session/transfer.zip.001")
        with self.assertRaises(hygiene.HygieneError):
            hygiene.build_reviewed_archive_audit(
                self.root, ["evidence/session/transfer.zip.001"], "reviewed transfer package"
            )
        self.assertTrue(path.exists())

    def test_symlink_rejection_and_local_reference_exclusion(self):
        outside = self.root / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        try:
            (self.evidence / "link").symlink_to(outside)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windows symlink privilege is unavailable")
            raise
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
