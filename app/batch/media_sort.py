"""Read-only, one-level image/video sorting preview for a generic Move Plan.

Images are proposed for P/, videos for V/ under the selected directory.
The preview never creates directories or moves files. The existing Plan
Freeze -> Validate -> Execute lifecycle remains the only mutation path.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path
import stat

from app.batch.file_rename import _open_directory_nofollow
from app.filters.media_types import get_media_type
from app.path_safety import (
    require_allowed_path,
    require_unreserved_path,
    validate_mutation_destination,
)

MAX_IMMEDIATE_ENTRIES = 50_000
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
_DESTINATION_DIRS = {"image": "P", "video": "V"}


def _destination_names(parent_fd: int, folder: str) -> set[str]:
    """Read the existing target basenames without following P/V symlinks."""
    try:
        folder_fd = os.open(folder, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        return set()  # The Move Plan executor creates missing target parents.
    except OSError as exc:
        if exc.errno in {errno.ENOTDIR, errno.ELOOP}:
            raise ValueError(f"Target {folder} must be a real directory, not a file or symlink") from exc
        raise

    try:
        names: set[str] = set()
        with os.scandir(folder_fd) as entries:
            for index, entry in enumerate(entries, start=1):
                if index > MAX_IMMEDIATE_ENTRIES:
                    raise ValueError(f"Too many entries in {folder} (limit: {MAX_IMMEDIATE_ENTRIES})")
                names.add(entry.name.casefold())
        return names
    finally:
        os.close(folder_fd)


def preview_media_sort(
    parent: str | Path, *,
    allowed_roots: list[str | Path],
    quarantine_root: str | Path | None = None,
) -> dict:
    """Classify only immediate real files; never traverse nested dirs/symlinks.

    Existing P/V contents, including case-insensitive collisions, are protected.
    Any conflict stays visible in the preview and must not enter the Move Plan.
    """
    raw_parent = Path(parent).expanduser()
    if not raw_parent.is_absolute() or raw_parent.is_symlink():
        raise ValueError("Selected parent must be an absolute non-symlink directory")
    safe_parent = require_unreserved_path(
        require_allowed_path(raw_parent, allowed_roots), quarantine_root,
    )
    if not safe_parent.is_dir():
        raise ValueError("Selected parent directory does not exist")

    for folder in _DESTINATION_DIRS.values():
        require_unreserved_path(safe_parent / folder, quarantine_root)

    parent_fd = _open_directory_nofollow(safe_parent)
    try:
        existing = {
            folder: _destination_names(parent_fd, folder)
            for folder in _DESTINATION_DIRS.values()
        }
        candidates: list[tuple[str, str, tuple[int, int, int, int]]] = []
        with os.scandir(parent_fd) as entries:
            for count, entry in enumerate(entries, start=1):
                if count > MAX_IMMEDIATE_ENTRIES:
                    raise ValueError(f"Too many immediate entries (limit: {MAX_IMMEDIATE_ENTRIES})")
                info = entry.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    continue
                media_kind = get_media_type(Path(entry.name).suffix)
                if media_kind not in _DESTINATION_DIRS:
                    continue
                snapshot = (
                    int(info.st_dev), int(info.st_ino),
                    int(info.st_size), int(info.st_mtime_ns),
                )
                candidates.append((entry.name, media_kind, snapshot))

        candidates.sort(key=lambda item: item[0])
        proposed: dict[str, set[str]] = {folder: set() for folder in _DESTINATION_DIRS.values()}
        rows: list[dict] = []
        for name, media_kind, snapshot in candidates:
            folder = _DESTINATION_DIRS[media_kind]
            source = safe_parent / name
            target_text = str(safe_parent / folder / name)
            conflict_reason: str | None = None
            try:
                target = validate_mutation_destination(
                    target_text, allowed_roots, quarantine_root=quarantine_root,
                )
                if target.parent != safe_parent / folder:
                    raise ValueError("Target must stay inside P or V under the selected directory")
                folded = name.casefold()
                if folded in existing[folder] or folded in proposed[folder]:
                    raise ValueError("Target already exists or collides (case-insensitive)")
                latest = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                current = (
                    int(latest.st_dev), int(latest.st_ino),
                    int(latest.st_size), int(latest.st_mtime_ns),
                )
                if not stat.S_ISREG(latest.st_mode) or current != snapshot:
                    raise ValueError("Source changed during preview")
                proposed[folder].add(folded)
            except (ValueError, OSError) as exc:
                conflict_reason = str(exc)
            rows.append({
                "source": str(source),
                "target": target_text,
                "media_kind": media_kind,
                "expected_size": snapshot[2],
                "conflict": conflict_reason is not None,
                "conflict_reason": conflict_reason,
            })
    finally:
        os.close(parent_fd)

    conflicts = sum(1 for row in rows if row["conflict"])
    return {
        "parent": str(safe_parent),
        "count": len(rows),
        "image_count": sum(1 for row in rows if row["media_kind"] == "image"),
        "video_count": sum(1 for row in rows if row["media_kind"] == "video"),
        "ready_count": len(rows) - conflicts,
        "conflict_count": conflicts,
        "items": rows,
    }
