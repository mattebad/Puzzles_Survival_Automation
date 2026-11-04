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
