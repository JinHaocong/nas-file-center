"""Read-only image/video sorting preview for the existing generic Move Plan.

Default: classify immediate regular files into P/ and V/.
Recursive: classify each directory's own regular files into its own P/ and V/.
Existing P/V names are never reused: choose P_1/V_1, P_2/V_2, ...
Already classified P/V directories (including numbered variants) are not
traversed recursively. Smart skip (default on) leaves folders containing only
one media kind unchanged; the walker still visits their normal descendants.
No preview operation modifies the filesystem.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat

from app.batch.file_rename import _open_directory_nofollow
from app.filters.media_types import get_media_type
from app.path_safety import (
    is_reserved_quarantine_path,
    require_allowed_path,
    require_unreserved_path,
    validate_mutation_destination,
)

MAX_IMMEDIATE_ENTRIES = 50_000
MAX_RECURSIVE_ENTRIES = 50_000
MAX_RECURSIVE_DIRECTORIES = 10_000
MAX_RECURSIVE_DEPTH = 64
MAX_SUFFIX_ATTEMPTS = 10_000
_DESTINATION_DIRS = {"image": "P", "video": "V"}
_SORT_FOLDER_PATTERN = re.compile(r"(?:P|V)(?:_[1-9][0-9]*)?", re.IGNORECASE)
_IGNORED_SYSTEM_FILES = frozenset({".ds_store", "thumbs.db"})


def _choose_folder_name(folder: str, occupied: set[str]) -> str:
    """Return an available P/V folder name (case-insensitive, no replacement)."""
    for number in range(MAX_SUFFIX_ATTEMPTS):
        candidate = folder if number == 0 else f"{folder}_{number}"
        if candidate.casefold() not in occupied:
            return candidate
    raise ValueError(f"No free destination directory name for {folder}")


def _choose_filename(name: str, occupied: set[str], *, parent: Path) -> str:
    """Suffix files with _1, _2 etc. before their extension when necessary."""
    if name.casefold() not in occupied:
        return name

    extension = Path(name).suffix
    original_stem = name[:-len(extension)] if extension else name
    try:
        max_bytes = os.pathconf(parent, "PC_NAME_MAX")
    except (OSError, ValueError, AttributeError):
        max_bytes = 255
    if max_bytes <= 0:
        max_bytes = 255

    for number in range(1, MAX_SUFFIX_ATTEMPTS + 1):
        ending = f"_{number}"
        stem = original_stem
        while stem and len(os.fsencode(stem + ending + extension)) > max_bytes:
            stem = stem[:-1]
        if not stem:
            raise ValueError(f"Cannot append a safe suffix to {name}")
        candidate = stem + ending + extension
        if candidate.casefold() not in occupied:
            return candidate
    raise ValueError(f"No free destination filename for {name}")


def _scan_directory(
    directory: Path,
    *,
    recursive: bool,
    smart_skip: bool,
    allowed_roots: list[str | Path],
    quarantine_root: str | Path | None,
) -> tuple[list[dict], list[Path], int, list[dict]]:
    """Read one directory; only its direct files may be considered for moves."""
    directory_fd = _open_directory_nofollow(directory)
    try:
        occupied: set[str] = set()
        regular_files: list[tuple[str, str, tuple[int, int, int, int]]] = []
        other_regular_files = 0
        children: list[Path] = []
        skipped: list[dict] = []
        with os.scandir(directory_fd) as entries:
            count = 0
            for entry in entries:
                count += 1
                if count > MAX_IMMEDIATE_ENTRIES:
                    raise ValueError(
                        f"Too many immediate entries (limit: {MAX_IMMEDIATE_ENTRIES}) in {directory}"
                    )
                occupied.add(entry.name.casefold())
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    child = directory / entry.name
                    if recursive and not is_reserved_quarantine_path(child, quarantine_root):
                        if _SORT_FOLDER_PATTERN.fullmatch(entry.name):
                            skipped.append({
                                "path": str(child), "reason": "preclassified",
                                "image_count": 0, "video_count": 0,
                            })
                        else:
                            children.append(child)
                    continue
                if not stat.S_ISREG(info.st_mode):
                    # Never follow symlinks (even those pointing to media files).
                    continue
                kind = get_media_type(Path(entry.name).suffix)
                if kind not in _DESTINATION_DIRS:
                    if entry.name.casefold() not in _IGNORED_SYSTEM_FILES:
                        other_regular_files += 1
                    continue
                snapshot = (
                    int(info.st_dev), int(info.st_ino),
                    int(info.st_size), int(info.st_mtime_ns),
                )
                regular_files.append((entry.name, kind, snapshot))

        image_count = sum(kind == "image" for _, kind, _ in regular_files)
        video_count = sum(kind == "video" for _, kind, _ in regular_files)
        reason: str | None = None
        if smart_skip:
            if image_count and not video_count and other_regular_files == 0:
                reason = "pure_images"
            elif video_count and not image_count and other_regular_files == 0:
                reason = "pure_videos"
            elif not image_count and not video_count:
                reason = "no_media"
        if reason is not None:
            # Skipping moves in this directory does NOT prune its descendants.
            skipped.append({
                "path": str(directory), "reason": reason,
                "image_count": image_count, "video_count": video_count,
            })
            return [], sorted(children, key=lambda item: item.name), count, skipped

        # A destination is an *unoccupied* name under this exact directory,
        # never an already existing P/V directory, file or symlink.
        folders = {
            kind: _choose_folder_name(folder, occupied)
            for kind, folder in _DESTINATION_DIRS.items()
        }
        regular_files.sort(key=lambda item: item[0])
        proposed: dict[str, set[str]] = {kind: set() for kind in _DESTINATION_DIRS}
        rows: list[dict] = []

        for name, kind, snapshot in regular_files:
            folder = folders[kind]
            source = directory / name
            target_name = name
            conflict_reason: str | None = None
            try:
                # Include already proposed filenames, avoiding case-insensitive
                # collisions even on case-sensitive source filesystems.
                target_name = _choose_filename(name, proposed[kind], parent=directory)
                target = validate_mutation_destination(
                    directory / folder / target_name, allowed_roots,
                    quarantine_root=quarantine_root,
                )
                if target.parent != directory / folder:
                    raise ValueError("Target must remain in this directory's P/V folder")
                latest = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                identity = (
                    int(latest.st_dev), int(latest.st_ino),
                    int(latest.st_size), int(latest.st_mtime_ns),
                )
                if not stat.S_ISREG(latest.st_mode) or identity != snapshot:
                    raise ValueError("Source changed during preview")
                proposed[kind].add(target_name.casefold())
            except (ValueError, OSError) as exc:
                conflict_reason = str(exc)
            rows.append({
                "source": str(source),
                "target": str(directory / folder / target_name),
                "media_kind": kind,
                "expected_size": snapshot[2],
                "conflict": conflict_reason is not None,
                "conflict_reason": conflict_reason,
            })

        return rows, sorted(children, key=lambda item: item.name), count, skipped
    finally:
        os.close(directory_fd)


def preview_media_sort(
    parent: str | Path, *,
    recursive: bool = False,
    smart_skip: bool = True,
    allowed_roots: list[str | Path],
    quarantine_root: str | Path | None = None,
) -> dict:
    """Preview per-directory classification, optionally traversing descendants.

    Every traversed directory is opened with O_NOFOLLOW. Symlinks, existing
    classification directories and the reserved quarantine subtree are skipped.
    Traversal is bounded by depth, visited entries and directory count.
    """
    if not isinstance(recursive, bool):
        raise ValueError("recursive must be a boolean")
    if not isinstance(smart_skip, bool):
        raise ValueError("smart_skip must be a boolean")
    raw_parent = Path(parent).expanduser()
    if not raw_parent.is_absolute() or raw_parent.is_symlink():
        raise ValueError("Selected parent must be an absolute non-symlink directory")
    safe_parent = require_unreserved_path(
        require_allowed_path(raw_parent, allowed_roots), quarantine_root,
    )
    if not safe_parent.is_dir():
        raise ValueError("Selected parent directory does not exist")

    rows: list[dict] = []
    skipped: list[dict] = []
    pending: list[tuple[Path, int]] = [(safe_parent, 0)]
    scanned_dirs = 0
    scanned_entries = 0

    while pending:
        directory, depth = pending.pop()
        scanned_dirs += 1
        if recursive and scanned_dirs > MAX_RECURSIVE_DIRECTORIES:
            raise ValueError(f"Too many directories (limit: {MAX_RECURSIVE_DIRECTORIES})")
        proposed, children, count, ignored = _scan_directory(
            directory,
            recursive=recursive,
            smart_skip=smart_skip,
            allowed_roots=allowed_roots,
            quarantine_root=quarantine_root,
        )
        rows.extend(proposed)
        skipped.extend(ignored)
        scanned_entries += count
        if recursive and scanned_entries > MAX_RECURSIVE_ENTRIES:
            raise ValueError(f"Too many recursive entries (limit: {MAX_RECURSIVE_ENTRIES})")
        if children and depth >= MAX_RECURSIVE_DEPTH:
            raise ValueError(f"Recursive nesting exceeds depth limit: {MAX_RECURSIVE_DEPTH}")
        pending.extend((child, depth + 1) for child in reversed(children))

    rows.sort(key=lambda item: item["source"])
    skipped.sort(key=lambda item: (item["path"], item["reason"]))
    conflicts = sum(1 for item in rows if item["conflict"])
    return {
        "parent": str(safe_parent),
        "recursive": recursive,
        "smart_skip": smart_skip,
        "scanned_directories": scanned_dirs,
        "skipped_directory_count": len(skipped),
        "skipped_directories": skipped,
        "count": len(rows),
        "image_count": sum(item["media_kind"] == "image" for item in rows),
        "video_count": sum(item["media_kind"] == "video" for item in rows),
        "ready_count": len(rows) - conflicts,
        "conflict_count": conflicts,
        "items": rows,
    }
