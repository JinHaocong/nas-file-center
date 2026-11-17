"""Read-only per-unit media layout preview for the semantic organizer.

This module never changes the filesystem. It does not discover work/collection
boundaries: its caller supplies one independently identified organizing unit.
Only proven classification wrappers are folded into that unit. Real execution
requires a separately reviewed frozen manifest and no-clobber Worker process.
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
from app.batch.media_package_organizer import _size_label, MAX_FILES_PER_GROUP
from app.filters.media_types import get_media_type

MAX_UNIT_FILES = 300_000
MAX_IMMEDIATE_ENTRIES = 300_000
MAX_WRAPPER_DEPTH = 32

# The final named buckets are themselves legacy input wrappers on a rescan.
_BUCKET = re.compile(r"^(?:p|v)(?:_[1-9]\d*)? \[\d+ [^/]+\]$", re.IGNORECASE)
_SHORT = re.compile(r"^(?:p|v)(?:_?[1-9]\d*)?$", re.IGNORECASE)
_IMAGE_ALIASES = frozenset({"图片", "图", "照片", "photo", "photos", "image", "images", "picture", "pictures", "pic"})
_VIDEO_ALIASES = frozenset({"视频", "video", "videos"})
_OTHER_ALIASES = frozenset({"other"})
_OTHER_BUCKET = re.compile(r"^other \[\d+ [^/]+\]$", re.IGNORECASE)


class _Blocked(ValueError):
    pass


def _normalized_excluded_dir_names(values: list[str] | None) -> frozenset[str]:
    """Validate literal basenames; never match filenames by substring."""
    if values is None:
        return frozenset()
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise _Blocked("excluded directory names must be a list")
    names = set()
    for value in values:
        if (not isinstance(value, str) or not value.strip()
                or value in (".", "..")
                or "/" in value or "\\" in value or "\x00" in value):
            raise _Blocked("excluded directory name must be a single safe basename")
        names.add(value.casefold())
    return frozenset(names)


def _is_wrapper(name: str) -> bool:
    folded = name.casefold()
    return bool(_SHORT.fullmatch(name) or _BUCKET.fullmatch(name) or
                _OTHER_BUCKET.fullmatch(name) or folded in _IMAGE_ALIASES or
                folded in _VIDEO_ALIASES or folded in _OTHER_ALIASES)


def _check_scope(unit: Path, allowed_roots: list[Path], quarantine_root: Path | None) -> None:
    """Validate a literal input path; never follow directory symlinks."""
    if not unit.is_absolute() or not allowed_roots:
        raise _Blocked("absolute unit and at least one allowed root required")
    raw = os.path.abspath(unit)
    allowed = [os.path.abspath(root) for root in allowed_roots]
    matching = [root for root in allowed if os.path.commonpath((raw, root)) == root]
    if not matching:
        raise _Blocked("unit outside allowed roots")
    if quarantine_root is not None:
        reserved = os.path.abspath(quarantine_root)
        if os.path.commonpath((raw, reserved)) == reserved:
            raise _Blocked("reserved path")
    # Verify every component from the trusted allowed root, not Path.resolve():
    # resolve would silently follow a malicious symlink before checking it.
    base = max(matching, key=len)
    components = [Path(base)]
    for part in Path(raw).relative_to(base).parts:
        components.append(components[-1] / part)
    for path in components:
        try:
            st = os.lstat(path)
        except OSError as exc:
            raise _Blocked("missing or inaccessible directory") from exc
        if not stat.S_ISDIR(st.st_mode):
            raise _Blocked("scope contains symlink or non-directory")


def _blocked_result(unit: Path, reason: str) -> dict:
    return {"unit": str(unit), "status": "blocked", "reason": reason,
            "operation": None, "totals": {"P": 0, "V": 0, "Other": 0},
            "groups": [], "items": [], "needed_moves": 0,
            "renamed_count": 0, "conflicts": [reason], "read_only": True}


def preview_semantic_unit(unit: Path, *, allowed_roots: list[Path],
                          quarantine_root: Path | None = None,
                          exclude_dir_names: list[str] | None = None) -> dict:
    """Return a complete deterministic read-only plan for one safe unit.

    Recursion is limited to old media classification wrappers. Independent
    work/collection/version children are not eligible to be collapsed here.
    Those children are discovered by a separate semantic traversal layer.
    """
    unit = Path(unit)
    try:
        excluded_names = _normalized_excluded_dir_names(exclude_dir_names)
        if any(piece.casefold() in excluded_names for piece in unit.parts):
            raise _Blocked("organizing unit is inside a protected excluded directory")
        _check_scope(unit, [Path(x) for x in allowed_roots],
                     Path(quarantine_root) if quarantine_root is not None else None)
        rows: list[dict] = []
        wrappers: list[str] = []
        protected: list[str] = []
        root_dev = os.lstat(unit).st_dev
        folders = [(unit, 0, False)]
        while folders:
            current, depth, inside_wrapper = folders.pop()
            if depth > MAX_WRAPPER_DEPTH:
                raise _Blocked("classification wrapper depth limit exceeded")
            if os.lstat(current).st_dev != root_dev:
                raise _Blocked("cross-device classification wrapper")
            count = 0
            children = []
            directory_fd = _open_directory_nofollow(current)
            try:
                if os.fstat(directory_fd).st_dev != root_dev:
                    raise _Blocked("cross-device opened directory")
                with os.scandir(directory_fd) as scan:
                    for entry in scan:
                        count += 1
                        if count > MAX_IMMEDIATE_ENTRIES:
                            raise _Blocked("too many immediate entries")
                        if entry.name.casefold().startswith('.nfc-'):
                            raise _Blocked("reserved workspace requires recovery")
                        st = entry.stat(follow_symlinks=False)
                        if stat.S_ISDIR(st.st_mode):
                            if entry.name.casefold() in excluded_names:
                                # A root-level excluded folder is a protected
                                # sibling. Inside a classification wrapper the
                                # wrapper itself cannot be safely retired.
                                if inside_wrapper:
                                    raise _Blocked("excluded directory inside old classification wrapper")
                                protected.append(str(current / entry.name))
                                continue
                            if st.st_dev != root_dev:
                                raise _Blocked("cross-device child directory")
                            if _is_wrapper(entry.name):
                                children.append((current / entry.name, depth + 1, True))
                                wrappers.append(str(current / entry.name))
                            elif inside_wrapper:
                                raise _Blocked("classification wrapper contains possible independent work")
                            else:
                                protected.append(str(current / entry.name))
                            continue
                        if not stat.S_ISREG(st.st_mode):
                            raise _Blocked("symlink or special file needs manual review")
                        if st.st_dev != root_dev:
                            raise _Blocked("cross-device media file")
                        if len(rows) >= MAX_UNIT_FILES:
                            raise _Blocked("unit exceeds file limit")
                        kind = get_media_type(Path(entry.name).suffix)
                        group_kind = "P" if kind == "image" else "V" if kind == "video" else "Other"
                        rows.append({"path": str(current / entry.name), "name": entry.name,
                                     "kind": group_kind, "bytes": int(st.st_size),
                                     "identity": [int(st.st_dev), int(st.st_ino),
                                                  int(st.st_size), int(st.st_mtime_ns)]})
            finally:
                os.close(directory_fd)
            folders.extend(sorted(children, key=lambda c: (c[0].name.casefold(), c[0].name), reverse=True))
        rows.sort(key=lambda row: (os.path.relpath(row['path'], unit).casefold(),
                                   os.path.relpath(row['path'], unit)))
        source_paths = {row['path'] for row in rows}
        occupied_input_dirs = {str(unit / Path(p).relative_to(unit).parts[0])
                               for p in source_paths
                               if Path(p).parent != unit}
        digest = hashlib.sha256()
        for row in rows:
            digest.update(json.dumps([os.path.relpath(row['path'], unit), row['kind'],
                                      row['identity']], ensure_ascii=False, separators=(',', ':')).encode())
            digest.update(b'\n')
        totals = {kind: sum(r['kind'] == kind for r in rows) for kind in ('P', 'V', 'Other')}
        pure = totals['Other'] == 0 and (totals['P'] == 0 or totals['V'] == 0)
        if not rows:
            return {"unit": str(unit), "status": "skipped", "reason": "no_files_in_unit",
                    "operation": None, "totals": totals, "groups": [], "items": [],
                    "protected_children": protected, "needed_moves": 0,
                    "renamed_count": 0, "conflicts": [], "input_fingerprint": digest.hexdigest(),
                    "read_only": True}
        items = []
        groups = []
        if pure and len(rows) <= MAX_FILES_PER_GROUP:
            operation = 'flatten_pure_media'
            names, _ = allocate_names(rows, kind='flat')
            for row, name in zip(rows, names):
                items.append({"source": row['path'], "target": str(unit / name),
                              "target_name": name, "kind": row['kind'],
                              "bytes": row['bytes'], "identity": row['identity']})
        else:
            operation = 'bucket_pure_media' if pure else 'sort_mixed_media'
            for kind in ('P', 'V', 'Other'):
                group_rows = [r for r in rows if r['kind'] == kind]
                if not group_rows:
                    continue
                batches = [group_rows[i:i+MAX_FILES_PER_GROUP]
                           for i in range(0, len(group_rows), MAX_FILES_PER_GROUP)] if kind != 'Other' else [group_rows]
                for group_no, batch in enumerate(batches):
                    stem = kind if group_no == 0 else f'{kind}_{group_no}'
                    size = sum(r['bytes'] for r in batch)
                    name = f'{stem} [{len(batch)} {_size_label(size)}]'
                    final_dir = unit / name
                    groups.append({'kind': kind, 'name': name, 'count': len(batch),
                                   'bytes': size, 'destination': str(final_dir)})
                    names, _ = allocate_names(batch, kind=kind)
                    for row, filename in zip(batch, names):
                        items.append({"source": row['path'],
                                      "target": str(final_dir / filename),
                                      "target_name": filename, "kind": kind,
                                      "bytes": row['bytes'], "identity": row['identity']})
        # A generated path may be occupied by an unrelated entry. In-place
        # renamed source items are allowed because the executor must stage all
        # files before publishing new names.
        for item in items:
            target = Path(item['target'])
            if os.path.lexists(target) and str(target) not in source_paths:
                raise _Blocked('destination occupied by foreign file')
            parent = target.parent
            if parent != unit and os.path.lexists(parent):
                if not parent.is_dir() or parent.is_symlink():
                    raise _Blocked('destination parent unsafe')
                # An empty foreign P [n size] dir must not be silently reused.
                if str(parent) not in occupied_input_dirs:
                    raise _Blocked('destination folder outside scanned inputs')
        changes = sum(item['source'] != item['target'] for item in items)
        renamed = sum(Path(item['source']).name != item['target_name'] for item in items)
        stale_wrappers = [p for p in wrappers if not any(
            m['target'].startswith(p + os.sep) for m in items)]
        status = 'ready' if changes or stale_wrappers else 'already_organized'
        return {"unit": str(unit), "status": status,
                "reason": None, "operation": operation, "totals": totals,
                "groups": groups, "items": items, "protected_children": protected,
                "wrapper_cleanup": sorted(stale_wrappers, key=lambda p: (-len(Path(p).parts), p)),
                "needed_moves": changes, "renamed_count": renamed,
                "conflicts": [], "input_fingerprint": digest.hexdigest(),
                "read_only": True}
    except (_Blocked, OSError, ValueError) as exc:
        return _blocked_result(unit, str(exc))
