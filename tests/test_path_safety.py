from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import stat
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from safe_action_core import path_safety
from safe_action_core.path_safety import UnsafePathError, require_no_untrusted_symlinks


@contextmanager
def _darwin_filesystem(*, platform="darwin"):
    def directory(mode=0o755, owner=0):
        return SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=owner)
    metadata = {
        "/": directory(),
        "/private": directory(),
        "/private/var": directory(),
        "/private/tmp": directory(0o1777),
        "/private/var/folders": directory(0o700, 501),
        "/var": SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=0),
        "/tmp": SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=0),
    }
    targets = {"/var": "private/var", "/tmp": "private/tmp"}
    def lstat(path):
        try:
            return metadata[str(path)]
        except KeyError:
            raise FileNotFoundError(str(path)) from None
    with (
        patch.object(path_safety, "Path", PurePosixPath),
        patch.object(path_safety.os, "lstat", side_effect=lstat),
        patch.object(path_safety.os, "readlink", side_effect=lambda path: targets[str(path)]),
        patch.object(path_safety.sys, "platform", platform),
    ):
        yield metadata, targets


class PathSafetyTests(unittest.TestCase):
    def test_real_test_temp_path_and_missing_suffix_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            safe_root = require_no_untrusted_symlinks(root)
            self.assertTrue(safe_root.is_dir())
            self.assertEqual(
                require_no_untrusted_symlinks(root / "not-created" / "evidence.png"),
                safe_root / "not-created" / "evidence.png",
            )

    def test_verified_system_aliases_accept_user_owned_temp_descendants(self):
        with _darwin_filesystem():
            self.assertEqual(
                require_no_untrusted_symlinks(PurePosixPath("/var/folders/new.sqlite3")),
                PurePosixPath("/private/var/folders/new.sqlite3"),
            )
            self.assertEqual(
                require_no_untrusted_symlinks(PurePosixPath("/tmp/session/evidence.png")),
                PurePosixPath("/private/tmp/session/evidence.png"),
            )

    def test_system_alias_with_changed_target_is_rejected(self):
        with _darwin_filesystem() as (_metadata, targets):
            targets["/var"] = "private/etc"
            with self.assertRaises(UnsafePathError):
                require_no_untrusted_symlinks(PurePosixPath("/var/folders/new.sqlite3"))

    def test_system_alias_not_owned_by_root_is_rejected(self):
        with _darwin_filesystem() as (metadata, _targets):
            metadata["/var"].st_uid = 501
            with self.assertRaises(UnsafePathError):
                require_no_untrusted_symlinks(PurePosixPath("/var/folders/new.sqlite3"))

    def test_system_alias_writable_protected_ancestry_is_rejected(self):
        with _darwin_filesystem() as (metadata, _targets):
            metadata["/private"].st_mode |= stat.S_IWOTH
            with self.assertRaises(UnsafePathError):
                require_no_untrusted_symlinks(PurePosixPath("/var/folders/new.sqlite3"))

    def test_writable_tmp_target_without_sticky_bit_is_rejected(self):
        with _darwin_filesystem() as (metadata, _targets):
            metadata["/private/tmp"].st_mode &= ~stat.S_ISVTX
            with self.assertRaises(UnsafePathError):
                require_no_untrusted_symlinks(PurePosixPath("/tmp/session/evidence.png"))

    def test_root_owned_planted_link_below_system_alias_is_rejected(self):
        with _darwin_filesystem() as (metadata, targets):
            planted = "/private/var/folders/planted"
            metadata[planted] = SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=0)
            targets[planted] = "private/var"
            with self.assertRaises(UnsafePathError):
                require_no_untrusted_symlinks(PurePosixPath("/var/folders/planted/evidence.png"))

    def test_darwin_aliases_are_not_trusted_on_other_platforms(self):
        with _darwin_filesystem(platform="linux"):
            with self.assertRaises(UnsafePathError):
                require_no_untrusted_symlinks(PurePosixPath("/var/folders/new.sqlite3"))


    def test_non_root_owned_protected_ancestry_and_targets_are_rejected(self):
        for protected in ("/", "/private", "/private/var", "/private/tmp"):
            with self.subTest(protected=protected), _darwin_filesystem() as (metadata, _targets):
                metadata[protected].st_uid = 501
                path = "/tmp/session/evidence.png" if protected == "/private/tmp" else "/var/folders/evidence.png"
                with self.assertRaises(UnsafePathError):
                    require_no_untrusted_symlinks(PurePosixPath(path))

    def test_group_writable_root_and_var_target_are_rejected(self):
        for protected in ("/", "/private/var"):
            with self.subTest(protected=protected), _darwin_filesystem() as (metadata, _targets):
                metadata[protected].st_mode |= stat.S_IWGRP
                with self.assertRaises(UnsafePathError):
                    require_no_untrusted_symlinks(PurePosixPath("/var/folders/evidence.png"))

    def test_parent_step_does_not_erase_a_planted_or_dangling_link(self):
        for name, target in (("planted", "/private/var/folders/real"), ("dangling", "/absent")):
            with self.subTest(link=name), _darwin_filesystem() as (metadata, targets):
                metadata["/private/var/folders/real"] = SimpleNamespace(
                    st_mode=stat.S_IFDIR | 0o700, st_uid=501,
                )
                planted = "/private/var/folders/" + name
                metadata[planted] = SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=0)
                targets[planted] = target
                with self.assertRaises(UnsafePathError):
                    require_no_untrusted_symlinks(PurePosixPath("/var/folders") / name / ".." / "evidence.png")
                self.assertEqual(
                    require_no_untrusted_symlinks(PurePosixPath("/var/folders/real/../evidence.png")),
                    PurePosixPath("/private/var/folders/evidence.png"),
                )

    def test_missing_prefix_does_not_hide_a_later_link_after_a_parent_step(self):
        with _darwin_filesystem() as (metadata, targets):
            planted = "/private/var/folders/planted"
            metadata[planted] = SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=0)
            targets[planted] = "/private/var"
            with self.assertRaises(UnsafePathError):
                require_no_untrusted_symlinks(PurePosixPath("/var/folders/missing/../planted/evidence.png"))

    def test_planted_and_dangling_symlinks_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "real"
            target.mkdir()
            (target / "evidence.png").write_bytes(b"evidence")
            link = root / "planted"
            dangling = root / "dangling"
            try:
                link.symlink_to(target, target_is_directory=True)
                dangling.symlink_to(root / "absent")
            except (OSError, NotImplementedError) as exc:
                if getattr(exc, "winerror", None) == 1314 or isinstance(exc, NotImplementedError):
                    self.skipTest("host cannot create symbolic links without elevated privileges")
                if isinstance(exc, PermissionError):
                    self.skipTest("host does not permit symbolic-link creation")
                raise
            with self.assertRaisesRegex(UnsafePathError, "symlink"):
                require_no_untrusted_symlinks(link / "evidence.png")
            with self.assertRaisesRegex(UnsafePathError, "symlink"):
                require_no_untrusted_symlinks(dangling)


if __name__ == "__main__":
    unittest.main()
