"""Identify files to recycle during media organization without reading their contents."""

import os
import stat
from pathlib import Path

from app.batch.file_rename import _open_directory_nofollow


def recycle_file_reason(name: str) -> str | None:
    """Match the literal file-name suffix, including names consisting only of that suffix."""
    name = name.casefold()
    if name.endswith('.txt'):
        return 'text_file'
    if name.endswith('.url'):
        return 'url_shortcut'
    return None


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def check(path: Path, expected_stat: os.stat_result) -> str | None:
    """Classify one unchanged regular file without following a file or directory symlink."""
    reason = recycle_file_reason(path.name)
    if reason is None or not stat.S_ISREG(expected_stat.st_mode) or not path.is_absolute() or '..' in path.parts:
        return None
    try:
        parent = _open_directory_nofollow(path.parent)
        try:
            current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            return reason if _identity(current) == _identity(expected_stat) else None
        finally:
            os.close(parent)
    except OSError:
        return None


def matches_reviewed_candidate(path: Path, info: os.stat_result, reviewed_reason: object) -> bool:
    """Accept a previously reviewed text label for the same still-unchanged file."""
    if reviewed_reason == 'links_only' or reviewed_reason == 'promotion':
        reviewed_reason = 'text_file'
    reason = check(path, info)
    return reason is not None and reason == reviewed_reason
