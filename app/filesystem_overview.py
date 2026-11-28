"""Small, read-only directory overviews for an active file-space inspector."""
from __future__ import annotations

import os
from pathlib import Path
import stat
from threading import BoundedSemaphore
from time import monotonic

from app.batch.file_rename import _DIRECTORY_FLAGS, _open_directory_nofollow
from app.config import Settings
from app.filters.excludes import DEFAULT_EXCLUDE_DIR_NAMES
from app.filters.media_types import get_media_type
from app.path_safety import UnsafePathError, require_allowed_path


MAX_ENTRIES = 4096
MAX_DEPTH = 16
MAX_SECONDS = .3
_SLOTS = BoundedSemaphore(2)
_RESERVED = frozenset(name.casefold() for name in DEFAULT_EXCLUDE_DIR_NAMES)


class _OverviewUnavailable(Exception):
    """The complete result cannot be returned safely within the current budget."""


def _reserved_name(name: str) -> bool:
    folded = name.casefold()
    return folded in _RESERVED or folded.startswith('.nfc-')


def directory_overview(requested: str, settings: Settings) -> dict[str, int] | None:
    """Count actual regular files, staying on the selected filesystem and within a small budget."""
    path = Path(requested)
    if not path.is_absolute() or '\0' in requested or '..' in path.parts or any(map(_reserved_name, path.parts)):
        raise UnsafePathError('Invalid directory overview location')
    canonical = require_allowed_path(path, settings.allowed_roots)
    excluded = (settings.config_dir.resolve(), settings.quarantine_root.resolve())
    if path != canonical or any(path.is_relative_to(root) for root in excluded):
        raise UnsafePathError('Invalid directory overview location')
    if path in settings.allowed_roots or not _SLOTS.acquire(blocking=False):
        return None

    deadline = monotonic() + MAX_SECONDS
    visited = 0
    result = {'images': 0, 'videos': 0, 'files': 0, 'total_bytes': 0}

    def scan(fd: int, folder: Path, before: os.stat_result, depth: int) -> None:
        nonlocal visited
        if depth > MAX_DEPTH or monotonic() > deadline:
            raise _OverviewUnavailable
        with os.scandir(fd) as entries:
            for entry in entries:
                visited += 1
                if visited > MAX_ENTRIES or monotonic() > deadline:
                    raise _OverviewUnavailable
                child = folder / entry.name
                if _reserved_name(entry.name) or child in excluded:
                    continue
                info = entry.stat(follow_symlinks=False)
                if info.st_dev != before.st_dev:
                    continue
                if stat.S_ISDIR(info.st_mode):
                    child_fd = os.open(entry.name, _DIRECTORY_FLAGS, dir_fd=fd)
                    try:
                        opened = os.fstat(child_fd)
                        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                            raise _OverviewUnavailable
                        scan(child_fd, child, opened, depth + 1)
                    finally:
                        os.close(child_fd)
                elif stat.S_ISREG(info.st_mode):
                    suffix = child.suffix or (child.name if child.name.startswith('.') else '')
                    kind = get_media_type(suffix)
                    if kind == 'image':
                        result['images'] += 1
                    elif kind == 'video':
                        result['videos'] += 1
                    result['files'] += 1
                    result['total_bytes'] += info.st_size
        after = os.fstat(fd)
        if (after.st_mtime_ns, after.st_ctime_ns) != (before.st_mtime_ns, before.st_ctime_ns):
            raise _OverviewUnavailable

    try:
        fd = _open_directory_nofollow(canonical)
        try:
            scan(fd, canonical, os.fstat(fd), 0)
        finally:
            os.close(fd)
        return result if monotonic() <= deadline else None
    except (OSError, _OverviewUnavailable):
        return None
    finally:
        _SLOTS.release()
