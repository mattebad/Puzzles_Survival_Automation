"""Guard: tracked mutable files must not identify the owner's machine or network.

Retained historical evidence under ``evidence/`` is immutable and intentionally
out of scope; every other tracked text file is scanned. Allowed values are the
generic loopback/emulator endpoints and the neutral ``owner`` placeholder that
replaced the real account name in retained provenance paths.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
# Immutable retained records; scrubbing them is a separate history decision (#21).
EXCLUDED_ROOTS = ("evidence/",)

PATTERNS = {
    "windows user profile path": re.compile(
        r"(?i)\b[A-Z]:(?:\\\\|\\|/)Users(?:\\\\|\\|/)(?!owner(?:\\|/))[^\\/\s\"'`<>]+"
    ),
    "posix home path": re.compile(r"/(?:Users|home)/(?!owner/)[A-Za-z0-9._-]+/"),
    "private LAN IPv4": re.compile(
        r"(?<![\d.])(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?![\d.])"
    ),
    "MAC address": re.compile(r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f:])"),
    "SSH host-key fingerprint": re.compile(
        r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{2}:){15}[0-9a-f]{2}(?![0-9a-f:])|SHA256:[A-Za-z0-9+/]{43}\b"
    ),
    "NAS hostname": re.compile(r"(?i)\bnas\.local\b"),
    "Unraid storage path": re.compile(r"/mnt/(?:cache|user|disk\d+)/"),
}


def _tracked_mutable_text_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout.decode("utf-8").split("\0")
    files = []
    for name in listed:
        if not name or name.startswith(EXCLUDED_ROOTS):
            continue
        path = ROOT / name
        if not path.is_file():
            continue
        if b"\0" in path.read_bytes()[:8192]:
            continue
        files.append(path)
    return files


def find_host_identifiers(text: str) -> list[tuple[str, str]]:
    return [(label, match.group(0)) for label, rx in PATTERNS.items() for match in rx.finditer(text)]


class HostIdentifierGuardTests(unittest.TestCase):
    def test_patterns_catch_each_category_and_allow_generic_values(self):
        # Assembled from fragments so this file's own source never matches its scan.
        cases = {
            "windows user profile path": "C:\\" + "Users\\" + "alice\\Documents",
            "posix home path": "/" + "home/" + "alice/src",
            "private LAN IPv4": "adb connect " + ".".join(("192", "168", "1", "20")) + ":5555",
            "MAC address": "link/ether " + ":".join(("52", "54", "00", "12", "34", "56")),
            "SSH host-key fingerprint": "SHA256:" + "A" * 43,
            "NAS hostname": "ssh root@" + "nas" + ".local",
            "Unraid storage path": "/" + "mnt/" + "user/appdata",
        }
        for label, sample in cases.items():
            with self.subTest(label=label):
                self.assertIn(label, {found for found, _ in find_host_identifiers(sample)})
        for allowed in (
            "127.0.0.1:5555",
            "emulator-5554",
            "C:\\Users\\owner\\Documents\\capture.png",
            "/Users/owner/src",
            "sha256 0123456789abcdef",
            "version 10.0.19045.1",
        ):
            with self.subTest(allowed=allowed):
                self.assertEqual(find_host_identifiers(allowed), [])

    def test_tracked_mutable_files_contain_no_host_identifiers(self):
        violations = []
        for path in _tracked_mutable_text_files():
            text = path.read_bytes().decode("utf-8", "replace")
            for label, _ in find_host_identifiers(text):
                violations.append(f"{path.relative_to(ROOT).as_posix()}: {label}")
        # Report categories and locations only; never echo the matched values.
        self.assertEqual(sorted(set(violations)), [])


if __name__ == "__main__":
    unittest.main()
