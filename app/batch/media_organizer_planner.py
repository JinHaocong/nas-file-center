"""Read-only discovery and planning for the two media organizer modes."""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Callable, Iterator

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_package_naming import MEDIA_BUCKET_PATTERN
from app.batch.media_package_organizer import (
    MAX_DEPTH, MAX_PACKAGE_DIRECTORIES, MAX_PACKAGE_FILES, MAX_SCOPE_ENTRIES_PER_DIRECTORY,
    _classify, _package_path, _walk_package, iter_media_package_scope_entries, plan_media_layout,
)
from app.path_safety import require_allowed_path, require_unreserved_path

_LEGACY_BUCKET = re.compile(r"(?:p|v)(?:_?[1-9]\d*)?|other", re.I)
_OTHER_BUCKET = re.compile(r"other \[\d+ [^/]+\]", re.I)
_CALENDAR_DIRECTORY = re.compile(
    r"(?:19|20)\d{2}|(?:\d{2}|\d{4})(?:"
    r"[-_.]?(?:0[1-9]|1[0-2])(?:[-_.]?(?:0[1-9]|[12]\d|3[01]))?"
    r"|年(?:0?[1-9]|1[0-2])月(?:(?:0?[1-9]|[12]\d|3[01])日)?)"
)
_CALENDAR_DAY = re.compile(
    r"(?:\d{2}|\d{4})(?:[-_.]?(?:0[1-9]|1[0-2])[-_.]?(?:0[1-9]|[12]\d|3[01])"
    r"|年(?:0?[1-9]|1[0-2])月(?:0?[1-9]|[12]\d|3[01])日)"
)
_AMBIGUOUS = re.compile(r"(?:\d{1,3}|新建文件夹(?:\s*\(\d+\))?)", re.I)
_NUMBERED_LEAF = re.compile(r"[0-9]{1,3}")
_COLLECTION_CONTEXT = re.compile(
    r"合集|全集|图包|作品|\b(?:collection|album)\b|\bno[.\s_-]*\d+\b|\b[a-z]+\d+-\d+\b",
    re.I,
)
_VERSION_NAMES = frozenset({"4k", "pt", "原图无水印", "精华版", "修复版"})
_MIXED_WRAPPER_REASON = "分类包装里的散文件归属待确认"
_AMBIGUOUS_DIRECTORY_REASON = "Ambiguous directory role"
_PHOTO_ALIASES = frozenset({
    "图片", "图", "照片", "photo", "photos", "image", "images", "picture", "pictures", "pic",
})
_ALIASES = _PHOTO_ALIASES | {"视频", "video", "videos"}


def _is_wrapper(parent: Path, name: str) -> bool:
    """Keep explicit bucket labels, but disambiguate aliases at calendar levels."""
    if MEDIA_BUCKET_PATTERN.fullmatch(name) or _OTHER_BUCKET.fullmatch(name):
        return True
    if _CALENDAR_DIRECTORY.fullmatch(parent.name):
        # A date's direct children can be authors named P, V or photos.
        return False
    return bool(_LEGACY_BUCKET.fullmatch(name) or name.casefold() in _ALIASES)


def is_reserved_workspace(path: Path) -> bool:
    """Recognize directories reserved for live or historical organizer stages."""
    return any(part.casefold().startswith(".nfc-") for part in path.parts)


def _checked_scope(unit: Path, allowed_roots: list[Path], quarantine_root: Path | None) -> Path:
    unit = Path(unit)
    if is_reserved_workspace(unit):
        raise ValueError("Reserved organizer workspace cannot be selected")
    if not unit.is_absolute() or unit != require_unreserved_path(
        require_allowed_path(unit, allowed_roots), quarantine_root,
    ):
        raise ValueError("Choose a literal, allowed media directory")
    os.close(_open_directory_nofollow(unit))
    return unit


def _entries(folder: Path, device: int) -> list[tuple[str, os.stat_result]]:
    fd = _open_directory_nofollow(folder)
    try:
        if os.fstat(fd).st_dev != device:
            raise ValueError("Cross-device directory")
        entries = []
        with os.scandir(fd) as stream:
            for entry in stream:
                if len(entries) >= MAX_SCOPE_ENTRIES_PER_DIRECTORY:
                    raise ValueError("Media directory entry limit exceeded")
                entries.append((entry.name, entry.stat(follow_symlinks=False)))
        return sorted(entries, key=lambda entry: (entry[0].casefold(), entry[0]))
    finally:
        os.close(fd)


def _protected(path: Path, protected_roots: tuple[Path, ...]) -> bool:
    return any(path.is_relative_to(root) for root in protected_roots)


def _author_layer(unit: Path) -> bool:
    """Recognize the author level without mistaking a named work or version for an author."""
    return bool(_CALENDAR_DAY.fullmatch(unit.parent.name)
                and not _COLLECTION_CONTEXT.search(unit.name)
                and unit.name.casefold() not in _VERSION_NAMES)


def _labelled_bucket_kind(name: str) -> str | None:
    match = MEDIA_BUCKET_PATTERN.fullmatch(name)
    if match:
        return match.group("kind").upper()
    return "Other" if _OTHER_BUCKET.fullmatch(name) else None


def _photo_wrapper(unit: Path) -> bool:
    return unit.name.casefold() in _PHOTO_ALIASES and _is_wrapper(unit.parent, unit.name)


def _pure_wrapper(folder: Path, device: int, protected_roots: tuple[Path, ...],
                  check_cancelled: Callable[[], None] | None = None) -> bool:
    """Only merge a classification branch whose descendants have no other directory role."""
    pending = [(folder, 1)]
    visited = 0
    while pending:
        current, depth = pending.pop()
        if check_cancelled is not None:
            check_cancelled()
        visited += 1
        if depth > MAX_DEPTH or visited > MAX_PACKAGE_DIRECTORIES:
            return False
        try:
            fd = _open_directory_nofollow(current)
            try:
                if os.fstat(fd).st_dev != device:
                    return False
                # Shape detection can use entry types; the inventory still reads every file identity.
                with os.scandir(fd) as entries:
                    for index, entry in enumerate(entries):
                        if index >= MAX_SCOPE_ENTRIES_PER_DIRECTORY or entry.name.casefold().startswith(".nfc-"):
                            return False
                        if entry.is_dir(follow_symlinks=False):
                            child = current / entry.name
                            if _protected(child, protected_roots) or not _is_wrapper(current, entry.name):
                                return False
                            pending.append((child, depth + 1))
                        elif not entry.is_file(follow_symlinks=False):
                            return False
            finally:
                os.close(fd)
        except (OSError, ValueError):
            return False
    return True


def _layer_media_kinds(unit: Path, entries: list[tuple[str, os.stat_result]], device: int,
                       protected_roots: tuple[Path, ...]) -> tuple[str, ...]:
    """Identify pure local media beside separate works or dated subgroups."""
    author = _author_layer(unit)
    photos = _photo_wrapper(unit)
    if not author and not photos:
        return ()
    direct = {_classify(name) for name, info in entries if stat.S_ISREG(info.st_mode)}
    if direct and (len(direct) != 1 or "Other" in direct):
        return ()
    children = [unit / name for name, info in entries
                if stat.S_ISDIR(info.st_mode) and info.st_dev == device
                and not _protected(unit / name, protected_roots)]
    kinds = direct
    if not kinds:
        # A later scan sees the published buckets at this level. Keep existing
        # Other buckets with them, and fall back when a bucket needs reclassification.
        labelled = [child for child in children
                    if _labelled_bucket_kind(child.name)]
        kinds = {_verified_bucket_kind(child, device) for child in labelled}
        if None in kinds:
            return ()
    media_kinds = kinds - {"Other"}
    if not media_kinds or (photos and not author and media_kinds != {"P"}):
        return ()
    if any(not _is_wrapper(unit, child.name) or not _pure_wrapper(child, device, protected_roots)
           for child in children):
        return tuple(sorted(kinds))
    return ()


def _semantic_inventory(
    unit: Path, protected_roots: tuple[Path, ...],
    directories: set[Path] | None = None,
    local_media_kinds: tuple[str, ...] = (),
) -> Iterator[dict]:
    """Read only direct files and proven classification wrappers."""
    folders = [(unit, 0)]
    device = os.lstat(unit).st_dev
    files = directory_count = 0
    while folders:
        folder, depth = folders.pop()
        directory_count += 1
        if depth > MAX_DEPTH or directory_count > MAX_PACKAGE_DIRECTORIES:
            raise ValueError("Classification wrapper traversal limit exceeded")
        if directories is not None:
            directories.add(folder)
        children = []
        for name, info in _entries(folder, device):
            path = folder / name
            if name.casefold().startswith(".nfc-"):
                raise ValueError(f"Reserved workspace needs reconciliation: {path}")
            if stat.S_ISDIR(info.st_mode):
                if depth and local_media_kinds:
                    raise ValueError("A local media bucket now contains a nested directory")
                if _protected(path, protected_roots):
                    if depth:
                        raise ValueError("Classification wrapper contains a protected directory")
                elif not depth and local_media_kinds:
                    if _labelled_bucket_kind(name) in local_media_kinds and _verified_bucket_kind(path, device):
                        children.append((path, depth + 1))
                elif _is_wrapper(folder, name):
                    if depth or _pure_wrapper(path, device, protected_roots):
                        children.append((path, depth + 1))
                elif depth:
                    raise ValueError("Classification wrapper may contain independent works")
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_dev != device:
                raise ValueError(f"Unsupported or cross-device entry: {path}")
            kind = _classify(name)
            if depth and local_media_kinds and kind != _labelled_bucket_kind(folder.name):
                raise ValueError("A local media bucket changed its file type")
            files += 1
            if files > MAX_PACKAGE_FILES:
                raise ValueError("Media unit file limit exceeded")
            yield {
                "path": str(path), "name": name, "kind": kind,
                "bytes": int(info.st_size), "dev": int(info.st_dev),
                "ino": int(info.st_ino), "mtime_ns": int(info.st_mtime_ns),
            }
        folders.extend(reversed(children))


def walk_organizing_unit(
    unit: Path, *, mode: str, media_package_root: Path | None = None,
    quarantine_root: Path | None = None, directories: set[Path] | None = None,
    local_media_kinds: tuple[str, ...] = (),
) -> Iterator[dict]:
    """Return the raw inventory required to revalidate a previously checked unit."""
    unit = Path(unit)
    if local_media_kinds and (mode != "semantic" or not {"P", "V"}.intersection(local_media_kinds)
                              or any(kind not in ("P", "V", "Other") for kind in local_media_kinds)):
        raise ValueError("Invalid local media scope")
    if mode == "luolcy" and media_package_root is not None:
        yield from _walk_package(unit, directories=directories)
    elif mode == "semantic":
        protected_roots = tuple(Path(root) for root in (media_package_root, quarantine_root)
                                if root is not None)
        yield from _semantic_inventory(unit, protected_roots, directories, local_media_kinds)
    else:
        raise ValueError("Invalid organizer mode or missing MediaPackage root")


def _blocked(unit: Path, mode: str, reason: str) -> dict:
    return {
        "unit": str(unit), "package": str(unit), "organizer_mode": mode,
        "status": "blocked", "reason": reason, "conflicts": [{"reason": reason}],
        "total_files": 0, "totals": {"P": 0, "V": 0, "Other": 0}, "total_bytes": 0,
        "groups": [], "sample_moves": [], "total_proposals": 0, "actual_moves": 0,
        "needed_moves": 0, "renamed_count": 0, "wrapper_cleanup": [], "read_only": True,
    }


def _held_files(unit: Path, entries: list[tuple[str, os.stat_result]], reason: str) -> dict:
    """Report the local unassigned files while leaving descendants to discovery."""
    record = _blocked(unit, "semantic", reason)
    for name, info in entries:
        if stat.S_ISREG(info.st_mode) and not is_reserved_workspace(unit / name):
            record["totals"][_classify(name)] += 1
            record["total_files"] += 1
            record["total_bytes"] += info.st_size
    return record


def _author_loose_record(unit: Path, items: list[dict], included: set[Path],
                         protected_roots: tuple[Path, ...]) -> dict | None:
    """Recheck ownership of author-level loose files before freezing a changing layout."""
    if not _author_layer(unit) or not any(Path(row["path"]).parent == unit for row in items):
        return None
    device = items[0]["dev"]
    entries = _entries(unit, device)
    for name, info in entries:
        child = unit / name
        if (stat.S_ISDIR(info.st_mode) and info.st_dev == device
                and child not in included and not _protected(child, protected_roots)):
            return _held_files(unit, entries, "作者层散文件待确认")
    return None


def _regular_media_entries(path: Path, device: int) -> list[tuple[str, os.stat_result]]:
    """Read a leaf without admitting symbolic links, mount aliases, or nested directories."""
    try:
        entries = _entries(path, device)
    except (OSError, ValueError):
        return []
    if not all(
        stat.S_ISREG(info.st_mode) and info.st_dev == device and not name.casefold().startswith(".nfc-")
        for name, info in entries
    ):
        return []
    return entries


def _verified_bucket_kind(path: Path, device: int) -> str | None:
    kind = _labelled_bucket_kind(path.name)
    if kind is not None:
        entries = _regular_media_entries(path, device)
        if entries and all(_classify(name) == kind for name, _ in entries):
            return kind
    return None


def _numbered_media_leaf(path: Path, device: int) -> bool:
    """Preserve a numbered leaf role after publishing its own verified media buckets."""
    try:
        entries = _entries(path, device)
    except (OSError, ValueError):
        return False
    has_media = False
    for name, info in entries:
        if info.st_dev != device or name.casefold().startswith(".nfc-"):
            return False
        if stat.S_ISREG(info.st_mode):
            kind = _classify(name)
        elif stat.S_ISDIR(info.st_mode):
            kind = _verified_bucket_kind(path / name, device)
            if kind is None:
                return False
        else:
            return False
        has_media |= kind in ("P", "V")
    return has_media


def _numbered_siblings(unit: Path, entries: list[tuple[str, os.stat_result]],
                       device: int, protected_roots: tuple[Path, ...]) -> set[str]:
    """Confirm independent leaf packages using a collection name or a complete ordinal series."""
    directories = [name for name, info in entries if stat.S_ISDIR(info.st_mode)]
    if sum(bool(_NUMBERED_LEAF.fullmatch(name)) for name in directories) < 2:
        return set()
    names = [name for name in directories
             if _protected(unit / name, protected_roots) or not _verified_bucket_kind(unit / name, device)]
    ordinals = {name.lstrip("0") for name in names}
    if len(names) < 2 or "" in ordinals or len(names) != len(ordinals):
        return set()
    if not all(_NUMBERED_LEAF.fullmatch(name) and not _protected(unit / name, protected_roots) for name in names):
        return set()
    if not _COLLECTION_CONTEXT.search(unit.name) and ordinals != {str(index) for index in range(1, len(names) + 1)}:
        return set()
    return set(names) if all(_numbered_media_leaf(unit / name, device) for name in names) else set()


def preview_organizing_unit(
    unit: Path, *, mode: str, allowed_roots: list[Path],
    quarantine_root: Path | None = None, media_package_root: Path | None = None,
    max_rows: int = 100, include_items: bool = False, include_mapping: bool = False,
    local_media_kinds: tuple[str, ...] | None = None,
) -> dict:
    """Plan a bounded, independently identified organizing unit."""
    unit = _checked_scope(unit, allowed_roots, quarantine_root)
    if mode == "luolcy" and media_package_root is not None:
        unit = _package_path(unit, media_package_root, allowed_roots, quarantine_root)
    elif mode != "semantic" or (media_package_root is not None
                                and unit.is_relative_to(media_package_root)):
        raise ValueError("Invalid unit or mode")
    protected = tuple(Path(root) for root in (media_package_root, quarantine_root) if root is not None)
    if local_media_kinds is None and mode == "semantic" and (_author_layer(unit) or _photo_wrapper(unit)):
        device = os.lstat(unit).st_dev
        local_media_kinds = _layer_media_kinds(unit, _entries(unit, device), device, protected)
    local_media_kinds = local_media_kinds or ()
    directories: set[Path] = set()
    items = list(walk_organizing_unit(
        unit, mode=mode, media_package_root=media_package_root, quarantine_root=quarantine_root,
        directories=directories, local_media_kinds=local_media_kinds,
    ))
    origin_dirs = set()
    for row in items:
        for parent in Path(row["path"]).parents:
            if parent == unit:
                break
            origin_dirs.add(parent)
    plan = plan_media_layout(
        unit, items, max_rows=max_rows,
        include_items=include_items, include_mapping=include_mapping, organizer_mode=True,
        legacy_bucket_conflicts=not (mode == "semantic"
                                     and (local_media_kinds or _CALENDAR_DIRECTORY.fullmatch(unit.name))),
    )
    if mode == "semantic" and plan["status"] == "ready" and not local_media_kinds:
        held = _author_loose_record(unit, items, directories, protected)
        if held is not None:
            return held
    final_dirs = {Path(group["destination"]) for group in plan["groups"]}
    # A pre-existing empty branch is not an input. Retain its ancestors even
    # when another branch in the same wrapper supplied files.
    occupied_ancestors = {
        parent for empty in directories - origin_dirs - {unit}
        for parent in empty.parents if parent in origin_dirs
    }
    occupied_groups = final_dirs & occupied_ancestors
    if occupied_groups:
        return _blocked(unit, mode, "A target media bucket contains a non-input directory")
    cleanup = origin_dirs - final_dirs - occupied_ancestors if plan["status"] == "ready" else set()
    return {
        **plan, "unit": str(unit), "organizer_mode": mode,
        **({"local_media_kinds": list(local_media_kinds)} if local_media_kinds else {}),
        "total_bytes": sum(row["bytes"] for row in items),
        "wrapper_cleanup": sorted((str(path) for path in cleanup), key=lambda path: (-len(Path(path).parts), path)),
    }


def _semantic_previews(
    selection: Path, protected_roots: tuple[Path, ...], preview: Callable[[Path, str], dict],
    check_cancelled: Callable[[], None] | None,
) -> Iterator[dict]:
    device = os.lstat(selection).st_dev
    pending: list[tuple[Path, int, str | None]] = [(selection, 0, None)]
    visited = 0
    while pending:
        unit, depth, hold_reason = pending.pop()
        if check_cancelled is not None:
            check_cancelled()
        visited += 1
        if depth > MAX_DEPTH or visited > MAX_PACKAGE_DIRECTORIES:
            yield _blocked(unit, "semantic", "Media scope directory limit exceeded")
            continue
        try:
            entries = _entries(unit, device)
        except (OSError, ValueError) as exc:
            yield _blocked(unit, "semantic", str(exc))
            continue
        children: list[tuple[Path, int, str | None]] = []
        numbered = _numbered_siblings(unit, entries, device, protected_roots)
        has_pure_wrappers = False
        has_input = False
        for name, info in entries:
            child = unit / name
            if _protected(child, protected_roots):
                continue
            if name.casefold().startswith(".nfc-") or info.st_dev != device:
                yield _blocked(child, "semantic", "Reserved or cross-device entry")
            elif stat.S_ISDIR(info.st_mode):
                if _is_wrapper(unit, name):
                    if _pure_wrapper(child, device, protected_roots, check_cancelled):
                        has_pure_wrappers = True
                    else:
                        children.append((child, depth + 1, _MIXED_WRAPPER_REASON))
                elif _AMBIGUOUS.fullmatch(name) and name not in numbered:
                    children.append((child, depth + 1, _AMBIGUOUS_DIRECTORY_REASON))
                else:
                    children.append((child, depth + 1, None))
            elif stat.S_ISREG(info.st_mode):
                has_input = True
            else:
                yield _blocked(child, "semantic", "Symlink or special entry")
        if (hold_reason == _MIXED_WRAPPER_REASON and _photo_wrapper(unit)
                and _layer_media_kinds(unit, entries, device, protected_roots)):
            yield preview(unit, "semantic")
        elif hold_reason is not None:
            if hold_reason != _MIXED_WRAPPER_REASON or has_input or has_pure_wrappers:
                yield _held_files(unit, entries, hold_reason)
        elif has_input or has_pure_wrappers:
            yield preview(unit, "semantic")
        children.sort(key=lambda entry: (str(entry[0]).casefold(), str(entry[0])), reverse=True)
        pending.extend(children)


def iter_organizing_previews(
    selection: Path, *, allowed_roots: list[Path], quarantine_root: Path | None = None,
    media_package_root: Path | None = None,
    check_cancelled: Callable[[], None] | None = None,
    max_rows: int = 10, include_mapping: bool = False,
) -> Iterator[dict]:
    """Yield read-only previews from the selected scope."""
    selection = _checked_scope(selection, allowed_roots, quarantine_root)
    protected = tuple(Path(root) for root in (media_package_root, quarantine_root) if root is not None)
    package_root = Path(media_package_root) if media_package_root is not None else None

    def preview(path: Path, mode: str) -> dict:
        try:
            return preview_organizing_unit(
                path, mode=mode, allowed_roots=allowed_roots,
                quarantine_root=quarantine_root, media_package_root=package_root,
                max_rows=max_rows, include_mapping=include_mapping,
            )
        except (OSError, ValueError) as exc:
            return _blocked(path, mode, str(exc))

    if package_root is None or not selection.is_relative_to(package_root):
        yield from _semantic_previews(selection, protected, preview, check_cancelled)
    if package_root is not None and (
        selection.is_relative_to(package_root) or package_root.is_relative_to(selection)
    ):
        package_selection = selection if selection.is_relative_to(package_root) else package_root
        try:
            for unit, reason in iter_media_package_scope_entries(
                package_selection, media_package_root=package_root,
                allowed_roots=allowed_roots, quarantine_root=quarantine_root,
                isolate_conflicts=True, check_cancelled=check_cancelled,
            ):
                yield _blocked(unit, "luolcy", reason) if reason else preview(unit, "luolcy")
        except (OSError, ValueError) as exc:
            yield _blocked(package_selection, "luolcy", str(exc))
