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
from pathlib import Path

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_package_naming import allocate_names
from app.filters.media_types import get_media_type
from app.path_safety import require_allowed_path, require_unreserved_path

MAX_FILES_PER_GROUP = 200
MAX_PACKAGE_FILES = 300_000
MAX_PACKAGE_DIRECTORIES = 100_000
MAX_DEPTH = 64
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


def _child_directories(directory: Path) -> list[str]:
    """List immediate directories without symlink traversal or file content I/O."""
    fd = _open_directory_nofollow(directory)
    names: list[str] = []
    try:
        with os.scandir(fd) as entries:
            for count, entry in enumerate(entries, 1):
                if count > MAX_SCOPE_ENTRIES_PER_DIRECTORY:
                    raise ValueError("Too many MediaPackage discovery entries in one directory")
                # Symlinked folders may point outside the protected resource
                # hierarchy. Never silently treat them as resource packages.
                if entry.is_symlink():
                    raise ValueError(f"MediaPackage scope contains a symlink: {directory / entry.name}")
                if entry.is_dir(follow_symlinks=False):
                    names.append(entry.name)
    finally:
        os.close(fd)
    return sorted(names)


def iter_media_package_packages(selection: str | Path, *,
                         media_package_root: str | Path,
                         allowed_roots: list[Path],
                         quarantine_root: Path | None = None):
    """Stream package paths from MediaPackage/YYMM/YYMMDD/author/package.

    A MediaPackage root selection enumerates all packages; month/day selections
    enumerate only matching descendants. No unrelated directory is modified.
    The iterator is bounded and does not materialize the full library.
    """
    selected, level = _validate_scope(
        selection, media_package_root=media_package_root,
        allowed_roots=allowed_roots, quarantine_root=quarantine_root,
    )
    pending = [(selected, level)]
    discovered = 0
    while pending:
        directory, depth = pending.pop()
        if depth == 4:
            discovered += 1
            if discovered > MAX_SCOPE_DISCOVERED_PACKAGES:
                raise ValueError("Too many MediaPackage resource packages in selected scope")
            yield directory
            continue
        children = []
        for name in _child_directories(directory):
            if depth == 0 and not _MONTH.fullmatch(name):
                continue
            if depth == 1 and (not _DAY.fullmatch(name) or
                               name[:4] != directory.name):
                continue
            children.append((directory / name, depth + 1))
        pending.extend(reversed(children))


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


def _walk_package(package: Path):
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
    for item in sorted(files, key=lambda row: (
        os.path.relpath(row["path"], package).casefold(),
        os.path.relpath(row["path"], package),
    )):
        record = [
            os.path.relpath(item["path"], package), item["kind"],
            item["bytes"], item["dev"], item["ino"], item["mtime_ns"],
        ]
        digest.update(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\\n")
    return digest.hexdigest()


def preview_media_package_package(package: str | Path, *, media_package_root: str | Path,
                           allowed_roots: list[Path],
                           quarantine_root: Path | None = None,
                           max_rows: int = 100, include_items: bool = False) -> dict:
    """Build a bounded, read-only manifest for one exact resource package.

    Pure image/video packages with up to 200 files are flattened into
    their package root; larger pure packages are grouped in sized P/V buckets.
    Existing targets are never assumed safe to overwrite; unresolved target
    occupancy is reported as a blocking conflict for manual review.
    """
    if not isinstance(max_rows, int) or not 1 <= max_rows <= 200:
        raise ValueError("max_rows must be between 1 and 200")
    source = _package_path(package, media_package_root, allowed_roots, quarantine_root)
    items = list(_walk_package(source))
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
        }

    # Homogeneous packages <=200 must be flattened *and* renumbered.
    # To avoid a root-level 001/002 rename cycle, the frozen executor stages
    # every file before publishing any numbered basename.
    if (len(items) <= MAX_FILES_PER_GROUP and totals["Other"] == 0
            and (totals["P"] == 0 or totals["V"] == 0)):
        ordered = sorted(items, key=lambda row: (
            os.path.relpath(row["path"], source).casefold(),
            os.path.relpath(row["path"], source),
        ))
        new_names, _ = allocate_names(ordered, kind="flat")
        rename_count = sum(row["name"] != name
                           for row, name in zip(ordered, new_names))
        seen_original = set()
        collision_count = 0
        for row in ordered:
            key = row["name"].casefold()
            collision_count += key in seen_original
            seen_original.add(key)
        needs_work = any(
            row["path"] != str(source / name)
            for row, name in zip(ordered, new_names)
        )
        # The execution phase must stage ALL files, including already-numbered
        # root entries that currently occupy another file's desired target.
        planned = [
            {"source": row["path"], "target": str(source / name),
             "source_name": row["name"], "target_name": name,
             "original_relative_path": os.path.relpath(row["path"], source),
             "bytes": row["bytes"], "kind": row["kind"]}
            for row, name in zip(ordered, new_names)
        ] if needs_work else []
        return {
            "package": str(source),
            "input_fingerprint": input_fingerprint,
            "status": "ready" if needs_work else "skipped",
            "reason": None if needs_work else "already_flat_numbered",
            "total_files": len(items), "totals": totals, "groups": [],
            "conflicts": [], "sample_moves": planned[:max_rows],
            "total_proposals": len(planned), "needed_moves": len(planned),
            "renamed_count": rename_count,
            "resolved_collision_count": collision_count,
            "truncated": len(planned) > max_rows,
            "read_only": True,
            "operation": "flatten_pure_media",
            **({"_snapshot_items": items} if include_items else {}),
        }

    # Avoid reordering when readdir() order changes. Only metadata, never
    # data file bytes, are read. Bounded to one package, not the whole library.
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

    # Reserve original top-level names to avoid ambiguous destination merges.
    with os.scandir(source) as entries:
        occupied = {entry.name.casefold(): entry.name for entry in entries}
    # Numbered directories from older runs have ambiguous bucket ownership.
    # Reject instead of silently combining them or overwriting their content.
    legacy_numbered = sorted(
        original for folded, original in occupied.items()
        if re.fullmatch(r"(?:p|v)_[1-9][0-9]*", folded)
    )
    if legacy_numbered:
        conflicts.append({
            "reason": "legacy_numbered_bucket_requires_review",
            "existing": legacy_numbered,
        })
    for kind in ("P", "V", "Other"):
        files = observed.get(kind, [])
        if not files:
            continue
        groups_of_kind = [files[i:i + MAX_FILES_PER_GROUP] for i in range(0, len(files), MAX_FILES_PER_GROUP)] if kind != "Other" else [files]
        for index, chunk in enumerate(groups_of_kind):
            stem = kind if index == 0 else f"{kind}_{index}"
            size = sum(row["bytes"] for row in chunk)
            folder = f"{stem} [{len(chunk)} {_size_label(size)}]"
            dest = source / folder
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
            ]
            if competing:
                conflicts.append({"directory": str(dest),
                                  "existing": sorted(competing),
                                  "reason": "existing_bucket_name_requires_review"})
            if existing is not None and any(Path(row["path"]).parent != dest for row in chunk):
                # Existing destination with incoming files requires a guarded
                # merge/execution policy; do not silently overwrite.
                conflicts.append({"directory": str(dest), "reason": "target_directory_exists"})
            assigned, automatic_other = allocate_names(chunk, kind=kind)
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
                if len(sample) < max_rows:
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
    return {
        "package": str(source),
        "input_fingerprint": input_fingerprint,
        "status": "blocked" if conflicts else "ready" if needed_moves else "already_organized",
        "reason": None, "total_files": len(items), "totals": totals,
        "groups": groups, "conflicts": conflicts,
        "sample_moves": sample,
        "total_proposals": planned,
        # Group publishing requires staging each file, even an already-numbered
        # source in one bucket, to guarantee a no-clobber final publication.
        "needed_moves": planned if needed_moves else 0,
        "renamed_count": renamed_count,
        "resolved_collision_count": resolved_collision_count,
        "truncated": len(sample) < planned,
        "read_only": True,
        "operation": ("bucket_pure_media" if totals["Other"] == 0
                      and (totals["P"] == 0 or totals["V"] == 0)
                      else "sort_mixed_media"),
        **({"_snapshot_items": items} if include_items else {}),
    }
