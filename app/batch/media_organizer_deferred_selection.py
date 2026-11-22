"""Bounded API-only path submission for NAS folders unreadable by the API.

This is NOT a filesystem access authorization. In opt-in maintenance-window
mode, the API may queue a read-only preview for a canonical path beneath an
allowed root when a path component actually returns EACCES/EPERM. Every
accessible component is checked for a directory (never a symlink). Only the
Worker can fully validate the inaccessible tail, and it must do so before
freezing evidence or touching media. No worker flag, no deferred selection.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path
import stat


def deferred_api_selection_enabled(settings) -> bool:
    if getattr(settings, "nas_compat_api_deferred_selection_enabled", False) is not True:
        return False
    if getattr(settings, "media_organizer_execution_mode", "strict") != "maintenance_window":
        return False
    # Never defer filesystem verification in a capability-enabled Worker.
    if os.environ.get("NFC_NAS_COMPAT_ROOT_WORKER_ENABLED", "false") == "true":
        return False
    if not hasattr(os, "geteuid") or os.geteuid() == 0:
        return False
    return True


def has_permission_denied_tail(
    path: Path, allowed_roots: list[Path], quarantine_root: Path | None,
) -> bool:
    """Accept *only* EACCES/EPERM after checked, non-symlink prefixes.

    Return False for nonexistent, malformed, accessible-but-rejected and
    otherwise unsafe paths. This function does not grant execute/cleanup
    authorization; it only lets a Worker attempt a read-only preview.
    """
    if not isinstance(path, Path) or not path.is_absolute():
        return False
    literal = str(path)
    if (os.path.abspath(literal) != literal or "\x00" in literal
            or ".." in path.parts or not allowed_roots):
        return False
    try:
        roots = [Path(root) for root in allowed_roots]
        candidates = [root for root in roots if (root.is_absolute()
                      and (path == root or path.is_relative_to(root)))]
        if not candidates:
            return False
        root = max(candidates, key=lambda part: len(part.parts))
        if (quarantine_root is not None and
                (path == quarantine_root or path.is_relative_to(quarantine_root))):
            return False
        prefixes = [root]
        for segment in path.relative_to(root).parts:
            prefixes.append(prefixes[-1] / segment)
        for prefix in prefixes:
            try:
                info = os.lstat(prefix)
            except OSError as exc:
                return exc.errno in (errno.EACCES, errno.EPERM)
            if not stat.S_ISDIR(info.st_mode):
                return False
    except (OSError, ValueError, TypeError):
        return False
    # A path that is already fully accessible is never a deferred exception.
    return False
