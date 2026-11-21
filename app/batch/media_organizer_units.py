"""Read-only discovery of independent media organization units.

A semantic child is visited as its own potential unit. Old P/V wrappers are
handled by the current unit's planner, never treated as separate works.
Ambiguous numbered folders are held for review instead of guessed away.
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Callable, Iterator

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_planner import (
    MAX_IMMEDIATE_ENTRIES, _check_scope, _is_wrapper, _blocked_result,
    _normalized_excluded_dir_names, preview_semantic_unit,
)

MAX_TRAVERSAL_DIRS = 250_000
MAX_TRAVERSAL_DEPTH = 64
_CLEAR_WORK = re.compile(r"^(?:NO[. _-]?\d+|A\d+-\d+)", re.IGNORECASE)
_AMBIGUOUS = re.compile(r"^(?:\d{1,3}|新建文件夹(?:\s*\(\d+\))?)$", re.IGNORECASE)


def discover_semantic_units(selection: Path, *, allowed_roots: list[Path],
                            quarantine_root: Path | None = None,
                            exclude_roots: list[Path] | None = None,
                            exclude_dir_names: list[str] | None = None,
                            check_cancelled: Callable[[], None] | None = None,
                            ) -> Iterator[dict]:
    """Yield candidate unit previews and isolated blockers in path order.

    This function does not perform or request filesystem mutations. The
    returned source/target mappings are only proposals and cannot be executed
    without a separately frozen, audited manifest.
    """
    root = Path(selection)
    try:
        excluded_names = _normalized_excluded_dir_names(exclude_dir_names)
    except ValueError as exc:
        yield _blocked_result(root, str(exc))
        return
    allowed_roots = [Path(p) for p in allowed_roots]
    quarantine = Path(quarantine_root) if quarantine_root is not None else None
    excluded = [os.path.abspath(p) for p in (exclude_roots or [])]
    if any(not Path(p).is_absolute() for p in (exclude_roots or [])):
        yield _blocked_result(root, "excluded roots must be absolute")
        return

    def is_excluded(path: Path) -> bool:
        raw = os.path.abspath(path)
        return (
            any(piece.casefold() in excluded_names for piece in Path(raw).parts)
            or any(os.path.commonpath((raw, marker)) == marker for marker in excluded)
        )
    try:
        _check_scope(root, allowed_roots, quarantine)
        dev = os.lstat(root).st_dev
    except (ValueError, OSError) as exc:
        yield _blocked_result(root, str(exc))
        return

    stack = [(root, 0)]
    visited = 0
    while stack:
        current, depth = stack.pop()
        if is_excluded(current):
            continue
        if check_cancelled is not None:
            check_cancelled()
        visited += 1
        if visited > MAX_TRAVERSAL_DIRS or depth > MAX_TRAVERSAL_DEPTH:
            yield _blocked_result(current, "scope traversal limit exceeded")
            continue
        entries = []
        try:
            _check_scope(current, allowed_roots, quarantine)
            fd = _open_directory_nofollow(current)
            try:
                if os.fstat(fd).st_dev != dev:
                    raise ValueError("cross-device directory")
                with os.scandir(fd) as scan:
                    for index, entry in enumerate(scan, start=1):
                        if index > MAX_IMMEDIATE_ENTRIES:
                            raise ValueError("too many immediate entries")
                        info = entry.stat(follow_symlinks=False)
                        entries.append((entry.name, info))
            finally:
                os.close(fd)
        except (OSError, ValueError) as exc:
            yield _blocked_result(current, str(exc))
            continue
        entries.sort(key=lambda x: (x[0].casefold(), x[0]))
        has_regular_files = False
        has_wrappers = False
        children = []
        for name, info in entries:
            path = current / name
            if stat.S_ISDIR(info.st_mode) and is_excluded(path):
                continue
            if name.casefold().startswith('.nfc-'):
                yield _blocked_result(path, "reserved workspace requires recovery")
                continue
            if stat.S_ISDIR(info.st_mode):
                if info.st_dev != dev:
                    yield _blocked_result(path, "cross-device child directory")
                elif _is_wrapper(name):
                    has_wrappers = True
                elif _AMBIGUOUS.fullmatch(name):
                    yield _blocked_result(path, "ambiguous folder role requires manual review")
                else:
                    children.append(path)
            elif stat.S_ISREG(info.st_mode):
                has_regular_files = True
            else:
                yield _blocked_result(path, "symlink or special child needs manual review")

        if has_regular_files or has_wrappers:
            record = preview_semantic_unit(current, allowed_roots=allowed_roots,
                                           quarantine_root=quarantine,
                                           exclude_dir_names=list(excluded_names))
            yield record
            if has_wrappers and record['status'] == 'blocked':
                # A historical P/V folder can itself contain numbered works.
                # Do not flatten its parent, but safely discover unambiguous
                # work directories inside it as independent future units.
                for name, info in entries:
                    if (not stat.S_ISDIR(info.st_mode) or
                            is_excluded(current / name) or not _is_wrapper(name)):
                        continue
                    wrapper = current / name
                    try:
                        fd = _open_directory_nofollow(wrapper)
                        try:
                            if os.fstat(fd).st_dev != dev:
                                raise ValueError("cross-device wrapper")
                            with os.scandir(fd) as scan:
                                inside = list(scan)
                                if len(inside) > MAX_IMMEDIATE_ENTRIES:
                                    raise ValueError("wrapper entry limit")
                                for entry in inside:
                                    if _CLEAR_WORK.match(entry.name) and not is_excluded(wrapper / entry.name):
                                        info = entry.stat(follow_symlinks=False)
                                        if stat.S_ISDIR(info.st_mode) and info.st_dev == dev:
                                            children.append(wrapper / entry.name)
                        finally:
                            os.close(fd)
                    except (OSError, ValueError) as exc:
                        yield _blocked_result(wrapper, str(exc))
        children.sort(key=lambda x: (str(x).casefold(), str(x)))
        for child in reversed(children):
            stack.append((child, depth+1))
