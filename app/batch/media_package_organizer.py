"""Read-only MediaPackage-specific resource package planner.

This is deliberately separate from generic media sort. No filesystem mutation
is permitted here: a future executor must validate a fresh manifest and use
existing freeze/validate/execute safety mechanisms.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_package_naming import allocate_names, media_source_sort_key
from app.filters.media_types import get_media_type
from app.path_safety import require_allowed_path, require_unreserved_path

MAX_FILES_PER_GROUP = 200
MAX_PACKAGE_FILES = 300_000
MAX_PACKAGE_DIRECTORIES = 100_000
MAX_DEPTH = 64
APPEND_SINGLE_VIDEO = "append_single_video"
APPEND_AUTHOR_VIDEOS = "append_author_videos"
APPEND_VIDEO_OPERATIONS = frozenset({APPEND_SINGLE_VIDEO, APPEND_AUTHOR_VIDEOS})
PROMOTE_NUMBERED_PHOTO_GROUPS = "promote_numbered_photo_groups"
_MONTH = re.compile(r"^\d{2}(?:0[1-9]|1[0-2])$")
_DAY = re.compile(r"^\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01])$")


def _size_label(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    for unit, factor in (("TiB", 1024 ** 4), ("GiB", 1024 ** 3),
                         ("MiB", 1024 ** 2), ("KiB", 1024)):
        if size >= factor:
            # Deterministic names, no floating point precision loss.
            tenths = (size * 10 + factor // 2) // factor
            if tenths % 10 == 0:
                return f"{tenths // 10}{unit}"
            return f"{tenths // 10}.{tenths % 10}{unit}"
    return f"{size}B"


def _package_path(package: str | Path, root: str | Path,
                  allowed_roots: list[Path], quarantine_root: Path | None) -> Path:
    base = Path(root).expanduser()
    raw = Path(package).expanduser()
    if not raw.is_absolute() or not base.is_absolute():
        raise ValueError("MediaPackage paths must be absolute")
    # No symlink traversal even if an attacker points a directory inside the
    # MediaPackage tree to an unrelated storage area.
    safe = require_unreserved_path(
        require_allowed_path(raw, allowed_roots), quarantine_root
    )
    if raw != safe:
        raise ValueError("MediaPackage path must use its literal canonical location")
    try:
        components = raw.relative_to(base).parts
    except ValueError as exc:
        raise ValueError("Package must be below the configured MediaPackage root") from exc
    if (len(components) != 4
            or not _MONTH.fullmatch(components[0])
            or not _DAY.fullmatch(components[1])
            or components[1][:4] != components[0]
            or components[2] in (".", "..")
            or components[3] in (".", "..")):
        raise ValueError("Expected MediaPackage/YYMM/YYMMDD/author/package")
    fd = _open_directory_nofollow(raw)
    os.close(fd)
    return raw



MAX_SCOPE_DISCOVERED_PACKAGES = 60_000
MAX_SCOPE_ENTRIES_PER_DIRECTORY = 100_000


@dataclass(frozen=True)
class MediaPackageScopeEntry:
    path: Path
    reason: str | None = None
    loose_files: list[dict] | None = None
    packages: dict[str, list[int]] | None = None
    author_identity: list[int] | None = None
    all_direct_media: bool = False


def _validate_scope(selection: str | Path, *, media_package_root: str | Path,
                    allowed_roots: list[Path],
                    quarantine_root: Path | None) -> tuple[Path, int]:
    """Restrict a selection to the MediaPackage root or one of its four fixed levels.

    A selected month/day is a *discovery scope*, never a move destination.
    Only the resource package's descendants may be changed by a future runner.
    """
    root = Path(media_package_root).expanduser()
    raw = Path(selection).expanduser()
    if not raw.is_absolute() or not root.is_absolute():
        raise ValueError("MediaPackage selection and root must be absolute paths")
    safe = require_unreserved_path(
        require_allowed_path(raw, allowed_roots), quarantine_root,
    )
    if raw != safe:
        raise ValueError("MediaPackage selection must use a literal canonical path")
    try:
        components = raw.relative_to(root).parts
    except ValueError as exc:
        raise ValueError("Selection must stay below the configured MediaPackage root") from exc
    if (len(components) > 4
            or (len(components) >= 1 and not _MONTH.fullmatch(components[0]))
            or (len(components) >= 2 and
                (not _DAY.fullmatch(components[1]) or
                 components[1][:4] != components[0]))):
        raise ValueError("Select MediaPackage, YYMM, YYMMDD, author or resource package")
    fd = _open_directory_nofollow(raw)
    os.close(fd)
    return raw, len(components)


def _open_luolcy_author(author: Path, root: Path) -> int:
    """Open the exact author level without following links or crossing a device."""
    _, depth = _validate_scope(
        author, media_package_root=root, allowed_roots=[root], quarantine_root=None,
    )
    if depth != 3:
        raise ValueError("Expected MediaPackage/YYMM/YYMMDD/author")
    fd = _open_directory_nofollow(root)
    try:
        device = os.fstat(fd).st_dev
        for part in author.relative_to(root).parts:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            if os.fstat(fd).st_dev != device:
                raise ValueError(f"Cross-device Luolcy author directory: {author}")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _child_directories(
    directory: Path, *, isolate_conflicts: bool, excluded_names: frozenset[str],
    include_loose_files: bool = False, check_cancelled: Callable[[], None] | None = None,
) -> tuple[list[str], list[MediaPackageScopeEntry], MediaPackageScopeEntry | None]:
    """List immediate directories and optionally collect the same-device author files."""
    fd = _open_directory_nofollow(directory)
    names: list[str] = []
    conflicts = []
    files = []
    packages = {}
    count = 0
    try:
        author_stat = os.fstat(fd) if include_loose_files else None
        with os.scandir(fd) as entries:
            for count, entry in enumerate(entries, 1):
                if count > MAX_SCOPE_ENTRIES_PER_DIRECTORY:
                    raise ValueError("Too many MediaPackage discovery entries in one directory")
                if check_cancelled is not None and count % 256 == 0:
                    check_cancelled()
                # Symlinked folders may point outside the protected resource
                # hierarchy. Never silently treat them as resource packages.
                if entry.is_symlink():
                    path = directory / entry.name
                    reason = f"MediaPackage scope contains a symlink: {path}"
                    if not isolate_conflicts:
                        raise ValueError(reason)
                    conflicts.append(MediaPackageScopeEntry(path, reason))
                    continue
                if entry.name.casefold() in excluded_names:
                    continue
                is_directory = entry.is_dir(follow_symlinks=False)
                if is_directory:
                    names.append(entry.name)
                if author_stat is None or entry.name.casefold().startswith(".nfc-"):
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if info.st_dev != author_stat.st_dev:
                    continue
                if is_directory and stat.S_ISDIR(info.st_mode):
                    packages[entry.name] = [info.st_dev, info.st_ino]
                elif stat.S_ISREG(info.st_mode):
                    files.append({
                        "source": str(directory / entry.name), "kind": _classify(entry.name),
                        "bytes": info.st_size, "device": info.st_dev, "inode": info.st_ino,
                        "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
                    })
    finally:
        os.close(fd)
    author = None
    if files and author_stat is not None:
        author = MediaPackageScopeEntry(
            directory, loose_files=sorted(files, key=lambda row: row["source"]),
            packages={name: packages[name] for name in sorted(packages)},
            author_identity=[author_stat.st_dev, author_stat.st_ino],
            all_direct_media=count == len(files) and all(row["kind"] in {"P", "V"} for row in files),
        )
    return sorted(names), sorted(conflicts, key=lambda entry: entry.path), author


def iter_media_package_scope_entries(
    selection: str | Path, *, media_package_root: str | Path,
    allowed_roots: list[Path], quarantine_root: Path | None = None,
    isolate_conflicts: bool = False, excluded_names: frozenset[str] = frozenset(),
    check_cancelled: Callable[[], None] | None = None,
) -> Iterator[tuple[Path, str | None]]:
    """Stream legacy package paths and isolated conflicts from the fixed hierarchy."""
    for entry in iter_media_package_discovery(
        selection, media_package_root=media_package_root, allowed_roots=allowed_roots,
        quarantine_root=quarantine_root, isolate_conflicts=isolate_conflicts,
        excluded_names=excluded_names, check_cancelled=check_cancelled,
    ):
        yield entry.path, entry.reason


def iter_media_package_discovery(
    selection: str | Path, *, media_package_root: str | Path,
    allowed_roots: list[Path], quarantine_root: Path | None = None,
    isolate_conflicts: bool = False, excluded_names: frozenset[str] = frozenset(),
    check_cancelled: Callable[[], None] | None = None, include_author_files: bool = False,
) -> Iterator[MediaPackageScopeEntry]:
    """Stream package paths and optional author inventories from the fixed hierarchy.

    A MediaPackage root selection enumerates all packages; month/day selections
    enumerate only matching descendants. No unrelated directory is modified.
    The iterator is bounded and does not materialize the full library.
    """
    selected, level = _validate_scope(
        selection, media_package_root=media_package_root,
        allowed_roots=allowed_roots, quarantine_root=quarantine_root,
    )
    if any(part.casefold() in excluded_names for part in selected.parts):
        return
    pending = [(selected, level)]
    discovered = 0
    while pending:
        directory, depth = pending.pop()
        if check_cancelled is not None:
            check_cancelled()
        if depth == 4:
            discovered += 1
            if discovered > MAX_SCOPE_DISCOVERED_PACKAGES:
                raise ValueError("Too many MediaPackage resource packages in selected scope")
            yield MediaPackageScopeEntry(directory)
            continue
        try:
            names, conflicts, author = _child_directories(
                directory, isolate_conflicts=isolate_conflicts,
                excluded_names=excluded_names, check_cancelled=check_cancelled,
                include_loose_files=include_author_files and depth == 3,
            )
        except (OSError, ValueError) as exc:
            if not isolate_conflicts:
                raise
            yield MediaPackageScopeEntry(directory, str(exc))
            continue
        if author is not None:
            yield author
        yield from conflicts
        children = []
        for name in names:
            if depth == 0 and not _MONTH.fullmatch(name):
                continue
            if depth == 1 and (not _DAY.fullmatch(name) or
                               name[:4] != directory.name):
                continue
            children.append((directory / name, depth + 1))
        pending.extend(reversed(children))


def iter_media_package_packages(selection: str | Path, *, media_package_root: str | Path,
                                allowed_roots: list[Path],
                                quarantine_root: Path | None = None) -> Iterator[Path]:
    """Yield only package paths; retain the legacy scope rejection policy."""
    for package, _ in iter_media_package_scope_entries(
        selection, media_package_root=media_package_root,
        allowed_roots=allowed_roots, quarantine_root=quarantine_root,
    ):
        yield package


def iter_media_package_previews(selection: str | Path, *,
                         media_package_root: str | Path,
                         allowed_roots: list[Path],
                         quarantine_root: Path | None = None,
                         max_rows: int = 100):
    """Yield read-only previews one resource package at a time (bounded RAM)."""
    for package in iter_media_package_packages(
        selection, media_package_root=media_package_root,
        allowed_roots=allowed_roots, quarantine_root=quarantine_root,
    ):
        yield preview_media_package_package(
            package, media_package_root=media_package_root,
            allowed_roots=allowed_roots, quarantine_root=quarantine_root,
            max_rows=max_rows,
        )


def _classify(filename: str) -> str:
    media_type = get_media_type(Path(filename).suffix)
    return "P" if media_type == "image" else "V" if media_type == "video" else "Other"


def _walk_luolcy_author(
    author: Path, root: Path, *, check_cancelled: Callable[[], None] | None = None,
) -> Iterator[dict]:
    """Inventory a file-only author directory for a new in-place plan."""
    fd = _open_luolcy_author(author, root)
    try:
        device = os.fstat(fd).st_dev
        with os.scandir(fd) as entries:
            for count, entry in enumerate(entries, 1):
                if count > MAX_SCOPE_ENTRIES_PER_DIRECTORY:
                    raise ValueError("Too many Luolcy author entries")
                if check_cancelled is not None and count % 256 == 0:
                    check_cancelled()
                path = author / entry.name
                info = entry.stat(follow_symlinks=False)
                kind = _classify(entry.name)
                if (kind not in {"P", "V"} or info.st_dev != device
                        or not stat.S_ISREG(info.st_mode) or entry.name.casefold().startswith(".nfc-")):
                    raise ValueError(f"Luolcy author contains an unreviewed entry: {path}")
                yield {
                    "path": str(path), "name": entry.name, "kind": kind, "bytes": info.st_size,
                    "dev": info.st_dev, "ino": info.st_ino, "mtime_ns": info.st_mtime_ns,
                }
    finally:
        os.close(fd)


def _walk_package(package: Path, *, directories: set[Path] | None = None):
    """Yield bounded file metadata without opening or reading file contents."""
    stack = [(package, 0)]
    directory_count = file_count = 0
    while stack:
        directory, depth = stack.pop()
        directory_count += 1
        if directory_count > MAX_PACKAGE_DIRECTORIES or depth > MAX_DEPTH:
            raise ValueError("MediaPackage directory/depth safety limit exceeded")
        fd = _open_directory_nofollow(directory)
        children = []
        try:
            if directories is not None:
                directories.add(directory)
            with os.scandir(fd) as it:
                for entry in it:
                    if entry.name.casefold().startswith(".nfc-"):
                        raise ValueError(f"Reserved organizer workspace requires recovery: {directory / entry.name}")
                    if entry.is_symlink():
                        raise ValueError(f"Symlink requires manual review: {directory / entry.name}")
                    if entry.is_dir(follow_symlinks=False):
                        children.append(directory / entry.name)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        raise ValueError(f"Special file requires manual review: {directory / entry.name}")
                    info = entry.stat(follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode):
                        raise ValueError("Source file changed during scan")
                    file_count += 1
                    if file_count > MAX_PACKAGE_FILES:
                        raise ValueError("MediaPackage package file safety limit exceeded")
                    yield {
                        "path": str(directory / entry.name),
                        "name": entry.name,
                        "kind": _classify(entry.name),
                        "bytes": int(info.st_size),
                        "dev": int(info.st_dev),
                        "ino": int(info.st_ino),
                        "mtime_ns": int(info.st_mtime_ns),
                    }
        finally:
            os.close(fd)
        stack.extend((child, depth + 1) for child in reversed(sorted(children)))


def _input_fingerprint(files: list[dict], package: Path) -> str:
    """Stable digest of the entire package file snapshot, not a sampled page."""
    digest = hashlib.sha256(b"media_package-snapshot-v2\\n")
    relative_items = ((os.path.relpath(item["path"], package), item) for item in files)
    for relative, item in sorted(relative_items, key=lambda pair: (pair[0].casefold(), pair[0])):
        record = [
            relative, item["kind"], item["bytes"], item["dev"], item["ino"], item["mtime_ns"],
        ]
        digest.update(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\\n")
    return digest.hexdigest()


def preview_media_package_package(package: str | Path, *, media_package_root: str | Path,
                           allowed_roots: list[Path],
                           quarantine_root: Path | None = None,
                           max_rows: int = 100, include_items: bool = False,
                           include_mapping: bool = False) -> dict:
    """Build a bounded, read-only manifest for one exact resource package.

    Pure image/video packages with up to 200 files are flattened into
    their package root; larger pure packages are grouped in sized P/V buckets.
    An existing group folder containing scanned inputs can be rebuilt by the
    frozen executor; empty/foreign occupants still block unsafe publication.
    """
    if not isinstance(max_rows, int) or not 1 <= max_rows <= 200:
        raise ValueError("max_rows must be between 1 and 200")
    source = _package_path(package, media_package_root, allowed_roots, quarantine_root)
    items = list(_walk_package(source))
    return plan_media_layout(
        source, items, max_rows=max_rows, include_items=include_items,
        include_mapping=include_mapping,
    )


def plan_media_layout(
    source: Path, items: list[dict], *, max_rows: int = 100, include_items: bool = False,
    include_mapping: bool = False, organizer_mode: bool = False,
    legacy_bucket_conflicts: bool = True, append_videos: bool = False,
    numbered_photo_groups: bool = False,
) -> dict:
    """Plan the same final media layout from a mode-specific bounded inventory."""
    input_fingerprint = _input_fingerprint(items, source)
    totals = {kind: sum(x["kind"] == kind for x in items) for kind in ("P", "V", "Other")}
    if not items:
        return {
            "package": str(source), "status": "skipped",
            "input_fingerprint": input_fingerprint,
            "reason": "empty", "total_files": 0, "totals": totals,
            "groups": [], "conflicts": [], "sample_moves": [],
            "total_proposals": 0, "needed_moves": 0,
            "renamed_count": 0, "resolved_collision_count": 0,
            "truncated": False,
            "read_only": True,
            **({"_snapshot_items": items} if include_items else {}),
            **({"_mapping_items": []} if include_mapping else {}),
        }

    # Homogeneous packages <=200 must be flattened *and* renumbered.
    # To avoid a root-level 001/002 rename cycle, the frozen executor stages
    # every file before publishing any numbered basename.
    if (not numbered_photo_groups and len(items) <= MAX_FILES_PER_GROUP and totals["Other"] == 0
            and (totals["P"] == 0 or totals["V"] == 0)):
        relative_items = ((os.path.relpath(row["path"], source), row) for row in items)
        mapping_order = sorted(relative_items, key=lambda pair: (
            append_videos and Path(pair[1]["path"]).parent != source, pair[0].casefold(), pair[0],
        ))
        ordered = [row for _, row in mapping_order]
        new_names, _ = allocate_names(ordered, kind="flat")
        rename_count = sum(row["name"] != name
                           for row, name in zip(ordered, new_names))
        seen_original = set()
        collision_count = 0
        for row in ordered:
            key = row["name"].casefold()
            collision_count += key in seen_original
            seen_original.add(key)
        targets = [str(source / name) for name in new_names]
        actual_moves = sum(row["path"] != target for row, target in zip(ordered, targets))
        source_paths = {row["path"] for row in ordered}
        conflicts = [
            {"reason": "target_path_exists", "target": target}
            for target in targets if target not in source_paths and os.path.lexists(target)
        ] if organizer_mode else []
        # Retain the complete final map for freezing and result verification.
        # The append operation needs only the changed row in its preview.
        mapping = [
            {"source": row["path"], "target": target,
             "source_name": row["name"], "target_name": name,
             "original_relative_path": relative,
             "bytes": row["bytes"], "kind": row["kind"]}
            for (relative, row), target, name in zip(mapping_order, targets, new_names)
        ] if actual_moves or include_mapping else []
        planned = [
            row for row in mapping if not append_videos or row["source"] != row["target"]
        ] if actual_moves else []
        operation = "flatten_pure_media"
        if append_videos:
            operation = APPEND_SINGLE_VIDEO if actual_moves == 1 else APPEND_AUTHOR_VIDEOS
        return {
            "package": str(source),
            "input_fingerprint": input_fingerprint,
            "status": ("blocked" if conflicts else "ready" if actual_moves
                       else "already_organized" if organizer_mode else "skipped"),
            "reason": None if actual_moves or organizer_mode else "already_flat_numbered",
            "total_files": len(items), "totals": totals, "groups": [],
            "conflicts": conflicts, "sample_moves": planned[:max_rows],
            "total_proposals": len(planned), "needed_moves": len(planned),
            "renamed_count": rename_count,
            "resolved_collision_count": collision_count,
            "truncated": len(planned) > max_rows,
            "read_only": True,
            "operation": operation,
            **({"_snapshot_items": items} if include_items else {}),
            **({"_mapping_items": mapping} if include_mapping else {}),
            **({"actual_moves": actual_moves} if organizer_mode else {}),
        }

    # Avoid reordering when readdir() order changes. Only metadata, never
    # data file bytes, are read. Bounded to one package, not the whole library.
    if organizer_mode:
        items.sort(key=lambda row: (row["kind"], media_source_sort_key(row["path"], source)))
    else:
        items.sort(key=lambda x: (x["kind"], os.path.relpath(x["path"], source).casefold(),
                                  os.path.relpath(x["path"], source)))
    groups = []
    conflicts = []
    sample = []
    planned = 0
    needed_moves = 0
    renamed_count = 0
    resolved_collision_count = 0
    observed = {}
    for item in items:
        kind = item["kind"]
        observed.setdefault(kind, []).append(item)

    # Every existing directory containing a scanned file is an input, even
    # when it is named like a former P/V bucket. Only a *non-input* occupant
    # may block a future final name; never decide this from its label alone.
    relative_parts = (Path(item["path"]).relative_to(source).parts for item in items)
    source_directory_names = {parts[0].casefold() for parts in relative_parts if len(parts) > 1}
    with os.scandir(source) as entries:
        occupied = {entry.name.casefold(): entry.name for entry in entries}
    legacy_numbered = sorted(
        original for folded, original in occupied.items()
        if re.fullmatch(r"(?:p|v)_[1-9][0-9]*", folded)
        and folded not in source_directory_names
    ) if legacy_bucket_conflicts else []
    if legacy_numbered:
        conflicts.append({
            "reason": "legacy_numbered_bucket_requires_review",
            "existing": legacy_numbered,
        })
    for kind in ("P", "V", "Other"):
        files = observed.get(kind, [])
        if not files:
            continue
        if numbered_photo_groups:
            by_number: dict[str, list[dict]] = {}
            for row in files:
                by_number.setdefault(Path(row["path"]).parent.name, []).append(row)
            groups_of_kind = sorted(by_number.items(), key=lambda item: (len(item[0].lstrip("0")), item[0].lstrip("0")))
        else:
            chunks = ([files[i:i + MAX_FILES_PER_GROUP] for i in range(0, len(files), MAX_FILES_PER_GROUP)]
                      if kind != "Other" else [files])
            groups_of_kind = [(None, chunk) for chunk in chunks]
        for index, (existing_label, chunk) in enumerate(groups_of_kind):
            stem = kind if index == 0 else f"{kind}_{index}"
            size = sum(row["bytes"] for row in chunk)
            folder = existing_label or f"{stem} [{len(chunk)} {_size_label(size)}]"
            dest = source / folder
            assigned, automatic_other = allocate_names(chunk, kind=kind)
            existing = occupied.get(folder.casefold())
            # A prior P, P_1, V, V_1 bucket with unknown or stale count/size
            # is not silently replaced, merged or renamed.
            stem_folded = stem.casefold()
            competing = [
                value for key, value in occupied.items()
                if (
                    # Legacy unnumbered P/ and V/ folders are ordinary *sources*:
                    # their contents are collected and migrated into sized groups.
                    (key == stem_folded and index > 0)
                    or key.startswith(stem_folded + " [")
                )
                and key != folder.casefold()
                and key not in source_directory_names
            ] if legacy_bucket_conflicts else []
            if competing:
                conflicts.append({"directory": str(dest),
                                  "existing": sorted(competing),
                                  "reason": "existing_bucket_name_requires_review"})
            if (existing is not None
                    and folder.casefold() not in source_directory_names
                    and any(row["path"] != str(dest / name)
                            for row, name in zip(chunk, assigned))):
                # Replacing an existing labelled target folder needs a
                # separate no-clobber migration procedure. Name collisions
                # within a *new* target are automatically numbered, but a
                # pre-existing target directory is not safe to overwrite.
                conflicts.append({"directory": str(dest), "reason": "target_directory_exists"})
            seen_original = set()
            resolved_collision_count += automatic_other
            for row, candidate in zip(chunk, assigned):
                # Numbering makes duplicate original basenames harmless.
                # Report how many collisions were avoided, without merging.
                if kind in ("P", "V"):
                    folded = row["name"].casefold()
                    resolved_collision_count += folded in seen_original
                    seen_original.add(folded)
                renamed_count += row["name"] != candidate
                if include_mapping or len(sample) < max_rows:
                    sample.append({
                        "source": row["path"], "target": str(dest / candidate),
                        "source_name": row["name"], "target_name": candidate,
                        "original_relative_path": os.path.relpath(row["path"], source),
                        "bytes": row["bytes"], "kind": kind,
                    })
                planned += 1
                if row["path"] != str(dest / candidate):
                    needed_moves += 1
            groups.append({"name": folder, "kind": kind, "count": len(chunk),
                           "bytes": size, "destination": str(dest)})
    operation = ("bucket_pure_media" if totals["Other"] == 0 and (totals["P"] == 0 or totals["V"] == 0)
                 else "sort_mixed_media")
    return {
        "package": str(source),
        "input_fingerprint": input_fingerprint,
        "status": "blocked" if conflicts else "ready" if needed_moves else "already_organized",
        "reason": None, "total_files": len(items), "totals": totals,
        "groups": groups, "conflicts": conflicts,
        "sample_moves": sample[:max_rows],
        "total_proposals": planned,
        # Group publishing requires staging each file, even an already-numbered
        # source in one bucket, to guarantee a no-clobber final publication.
        "needed_moves": planned if needed_moves else 0,
        "renamed_count": renamed_count,
        "resolved_collision_count": resolved_collision_count,
        "truncated": planned > max_rows,
        "read_only": True,
        "operation": PROMOTE_NUMBERED_PHOTO_GROUPS if numbered_photo_groups else operation,
        **({"_snapshot_items": items} if include_items else {}),
        **({"_mapping_items": sample} if include_mapping else {}),
        **({"actual_moves": needed_moves} if organizer_mode else {}),
    }
