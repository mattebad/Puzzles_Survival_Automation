"""Path-component checks shared by evidence and fixed-authority guards."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import sys


class UnsafePathError(ValueError):
    """A path contains a link that is not an explicitly trusted OS alias."""


_DARWIN_ALIASES = {"/var": "private/var", "/tmp": "private/tmp"}


def _darwin_alias_target(path: Path, raw_target: str) -> Path | None:
    """Return the canonical target only for the two exact Darwin OS aliases."""

    if sys.platform != "darwin":
        return None
    target = _DARWIN_ALIASES.get(path.as_posix())
    if target is None or raw_target not in (target, "/" + target):
        return None
    return Path("/") / target


def _inspect(path: Path):
    try:
        return os.lstat(path)
    except OSError as exc:
        raise UnsafePathError(f"cannot safely inspect path component: {path}") from exc


def _require_protected_directory(path: Path, *, sticky_tmp_target: bool = False) -> None:
    metadata = _inspect(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise UnsafePathError(f"Darwin alias ancestry is not a real directory: {path}")
    if metadata.st_uid != 0:
        raise UnsafePathError(f"Darwin alias ancestry is not root-owned: {path}")
    writable_by_others = metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    if writable_by_others:
        if not sticky_tmp_target or not metadata.st_mode & stat.S_ISVTX:
            raise UnsafePathError(f"Darwin alias ancestry is writable by non-root users: {path}")


def _trusted_darwin_alias(path: Path, metadata) -> Path:
    if metadata.st_uid != 0:
        raise UnsafePathError(f"Darwin OS alias is not root-owned: {path}")
    try:
        raw_target = os.readlink(path)
    except OSError as exc:
        raise UnsafePathError(f"cannot inspect Darwin OS alias: {path}") from exc
    target = _darwin_alias_target(path, raw_target)
    if target is None:
        raise UnsafePathError(f"untrusted symlink: {path}")

    # The alias itself lives directly under /; its target is under protected
    # /private. Only /private/tmp has the intentional sticky, user-writable mode.
    _require_protected_directory(Path("/"))
    _require_protected_directory(Path("/private"))
    _require_protected_directory(
        target,
        sticky_tmp_target=target == Path("/private/tmp"),
    )
    return target


def _is_junction(path: Path) -> bool:
    check = getattr(path, "is_junction", None)
    try:
        return bool(check is not None and check())
    except OSError as exc:
        raise UnsafePathError(f"cannot safely inspect path component: {path}") from exc


def require_no_untrusted_symlinks(path: Path, *, reject_junctions: bool = False) -> Path:
    """Validate every existing component and return an alias-canonical lexical path.

    Missing suffixes are permitted for callers that validate a path before
    creating it. Dangling links are not missing suffixes: ``lstat`` sees and
    rejects them. The returned path substitutes only the two verified Darwin
    aliases; it never resolves arbitrary links.
    Parent steps are processed only after the preceding raw components have
    been inspected, including missing prefixes followed by a parent step.
    """

    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = candidate.absolute()
    parts = candidate.parts
    current = Path(candidate.anchor)
    for part in parts[1:]:
        if part == "..":
            current = current.parent
            continue
        probe = current / part
        try:
            metadata = os.lstat(probe)
        except FileNotFoundError:
            current = probe
            continue
        except OSError as exc:
            raise UnsafePathError(f"cannot safely inspect path component: {probe}") from exc

        if stat.S_ISLNK(metadata.st_mode):
            current = _trusted_darwin_alias(probe, metadata)
            continue
        if reject_junctions and _is_junction(probe):
            raise UnsafePathError(f"untrusted junction: {probe}")
        current = probe
    return current


def _git_link(path: Path, prefix: str = "") -> str:
    """Read one exact single-line Git administrative link without following it."""

    path = require_no_untrusted_symlinks(path)
    try:
        metadata = os.lstat(path)
        if not stat.S_ISREG(metadata.st_mode):
            raise UnsafePathError(f"Git link is not a regular file: {path}")
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UnsafePathError(f"cannot read Git link: {path}") from exc
    value = text[:-1] if text.endswith("\n") else text
    if value.endswith("\r"):
        value = value[:-1]
    if not value.startswith(prefix) or "\n" in value or "\r" in value:
        raise UnsafePathError(f"malformed Git link: {path}")
    value = value[len(prefix):]
    if not value.strip() or value != value.strip():
        raise UnsafePathError(f"malformed Git link: {path}")
    return value


def _linked(base: Path, value: str) -> Path:
    target = Path(value)
    return Path(os.path.normpath(target if target.is_absolute() else base / target))


def canonical_state_root(source_root: Path) -> Path:
    """Return the checkout that owns canonical local state for ``source_root``.

    A normal checkout, whose ``.git`` is a directory or absent, owns its state.
    A verified linked Git worktree shares the main checkout's state instead of
    splitting physical runtime history: its ``.git`` file names an admin
    directory ``<main>/.git/worktrees/<name>`` whose ``gitdir`` back-reference
    names this worktree and whose ``commondir`` names ``<main>/.git``. Only
    plain file reads are used, and every administrative path is checked for
    untrusted links before it is read. A ``.git`` file without ``commondir``
    (for example a submodule under ``.git/modules``) is not a linked worktree,
    but an admin directory under ``worktrees`` must have one. Any other
    linked-worktree claim fails closed rather than falling back to the worktree.
    """

    root = Path(os.path.abspath(os.path.normpath(source_root)))
    marker = root / ".git"
    try:
        metadata = os.lstat(marker)
    except FileNotFoundError:
        return root
    except OSError as exc:
        raise UnsafePathError(f"cannot safely inspect checkout marker: {marker}") from exc
    if stat.S_ISDIR(metadata.st_mode):
        return root
    admin = require_no_untrusted_symlinks(_linked(root, _git_link(marker, "gitdir: ")))
    commondir = admin / "commondir"
    try:
        os.lstat(commondir)
    except FileNotFoundError:
        if os.path.normcase(admin.parent.name) == os.path.normcase("worktrees"):
            raise UnsafePathError(f"linked Git worktree has no commondir: {root}") from None
        return root
    except OSError as exc:
        raise UnsafePathError(f"cannot safely inspect Git commondir: {commondir}") from exc
    common = require_no_untrusted_symlinks(_linked(admin, _git_link(commondir)))
    back_reference = _linked(admin, _git_link(admin / "gitdir"))
    try:
        common_metadata = os.lstat(common)
    except OSError as exc:
        raise UnsafePathError(f"cannot safely inspect Git common directory: {common}") from exc
    if (
        back_reference != marker
        or admin.parent != common / "worktrees"
        or common.name != ".git"
        or not stat.S_ISDIR(common_metadata.st_mode)
    ):
        raise UnsafePathError(f"unverified linked Git worktree: {root}")
    return require_no_untrusted_symlinks(common.parent)
