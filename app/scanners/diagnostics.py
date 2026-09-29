from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from sqlalchemy import select

from app.models import DuplicateFile, DuplicateGroup, ScanJob
from app.path_safety import UnsafePathError, is_reserved_quarantine_path, require_allowed_path


_HASH_CHUNK_SIZE = 8 * 1024 * 1024


@dataclass(frozen=True)
class _PathInspection:
    requested_path: str
    resolved_path: str | None
    allowed: bool
    exists: bool
    is_symlink: bool
    is_regular_file: bool
    in_quarantine: bool
    device: int | None
    inode: int | None
    size: int | None
    mtime_ns: int | None
    sha256: str | None
    hash_error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_path": self.requested_path,
            "resolved_path": self.resolved_path,
            "allowed": self.allowed,
            "exists": self.exists,
            "is_symlink": self.is_symlink,
            "is_regular_file": self.is_regular_file,
            "in_quarantine": self.in_quarantine,
            "device": self.device,
            "inode": self.inode,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "sha256": self.sha256,
            "hash_error": self.hash_error,
        }


def _stable_sha256(path: Path) -> tuple[str | None, str | None]:
    try:
        before = os.lstat(path)
    except OSError as exc:
        return None, f"stat_before_failed: {exc}"

    if not stat.S_ISREG(before.st_mode):
        return None, "not_regular_file"

    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_HASH_CHUNK_SIZE):
                digest.update(chunk)
        after = os.lstat(path)
    except OSError as exc:
        return None, f"hash_read_failed: {exc}"

    before_identity = (
        int(before.st_dev),
        int(before.st_ino),
        int(before.st_size),
        int(getattr(before, "st_mtime_ns", int(before.st_mtime * 1e9))),
    )
    after_identity = (
        int(after.st_dev),
        int(after.st_ino),
        int(after.st_size),
        int(getattr(after, "st_mtime_ns", int(after.st_mtime * 1e9))),
    )
    if before_identity != after_identity:
        return None, "file_changed_during_hash"
    return digest.hexdigest(), None


def _inspect_path(settings: Any, raw_path: str) -> _PathInspection:
    requested = str(raw_path)
    lexical = Path(requested).expanduser()
    lexical_symlink = lexical.is_symlink() or os.path.islink(lexical)

    diagnostic_roots: list[Path | str] = list(settings.allowed_roots)
    if getattr(settings, "quarantine_root", None):
        diagnostic_roots.append(settings.quarantine_root)

    try:
        safe = require_allowed_path(lexical, diagnostic_roots)
    except UnsafePathError:
        return _PathInspection(
            requested_path=requested,
            resolved_path=None,
            allowed=False,
            exists=False,
            is_symlink=bool(lexical_symlink),
            is_regular_file=False,
            in_quarantine=False,
            device=None,
            inode=None,
            size=None,
            mtime_ns=None,
            sha256=None,
            hash_error="path_outside_configured_roots",
        )

    in_quarantine = is_reserved_quarantine_path(safe, getattr(settings, "quarantine_root", None))
    if lexical_symlink:
        return _PathInspection(
            requested_path=requested,
            resolved_path=str(safe),
            allowed=True,
            exists=os.path.lexists(lexical),
            is_symlink=True,
            is_regular_file=False,
            in_quarantine=in_quarantine,
            device=None,
            inode=None,
            size=None,
            mtime_ns=None,
            sha256=None,
            hash_error="symlink_not_hashable",
        )

    if not os.path.lexists(safe):
        return _PathInspection(
            requested_path=requested,
            resolved_path=str(safe),
            allowed=True,
            exists=False,
            is_symlink=False,
            is_regular_file=False,
            in_quarantine=in_quarantine,
            device=None,
            inode=None,
            size=None,
            mtime_ns=None,
            sha256=None,
            hash_error="path_not_found",
        )

    try:
        st = os.lstat(safe)
    except OSError as exc:
        return _PathInspection(
            requested_path=requested,
            resolved_path=str(safe),
            allowed=True,
            exists=True,
            is_symlink=False,
            is_regular_file=False,
            in_quarantine=in_quarantine,
            device=None,
            inode=None,
            size=None,
            mtime_ns=None,
            sha256=None,
            hash_error=f"stat_failed: {exc}",
        )

    regular = stat.S_ISREG(st.st_mode)
    sha256 = None
    hash_error = None
    if regular:
        sha256, hash_error = _stable_sha256(safe)
    else:
        hash_error = "not_regular_file"

    return _PathInspection(
        requested_path=requested,
        resolved_path=str(safe),
        allowed=True,
        exists=True,
        is_symlink=False,
        is_regular_file=regular,
        in_quarantine=in_quarantine,
        device=int(st.st_dev),
        inode=int(st.st_ino),
        size=int(st.st_size),
        mtime_ns=int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
        sha256=sha256,
        hash_error=hash_error,
    )


def _containing_scan_root(path: str | None, scan_roots: list[str]) -> int | None:
    if not path:
        return None
    resolved = Path(path).resolve(strict=False)
    matches: list[tuple[int, Path]] = []
    for index, raw_root in enumerate(scan_roots):
        root = Path(raw_root).resolve(strict=False)
        if resolved == root or resolved.is_relative_to(root):
            matches.append((index, root))
    if not matches:
        return None
    return max(matches, key=lambda item: len(item[1].parts))[0]


def _load_scan_context(
    session_factory: Any,
    scan_job_id: int,
    inspections: tuple[_PathInspection, _PathInspection],
) -> dict[str, Any]:
    with session_factory() as session:
        scan = session.get(ScanJob, scan_job_id)
        if scan is None:
            raise KeyError(scan_job_id)

        try:
            scan_roots_raw = json.loads(scan.roots_json or "[]")
        except Exception:
            scan_roots_raw = []
        scan_roots = [str(root) for root in scan_roots_raw if isinstance(root, str)]

        try:
            scan_args_raw = json.loads(scan.fclones_args_json or "{}")
        except Exception:
            scan_args_raw = {}
        scan_args = scan_args_raw if isinstance(scan_args_raw, dict) else {}

        resolved_paths = [
            item.resolved_path for item in inspections if item.resolved_path is not None
        ]
        memberships: dict[str, list[dict[str, Any]]] = {path: [] for path in resolved_paths}
        if resolved_paths:
            rows = session.execute(
                select(DuplicateFile, DuplicateGroup)
                .join(DuplicateGroup, DuplicateFile.group_id == DuplicateGroup.id)
                .where(
                    DuplicateGroup.scan_job_id == scan_job_id,
                    DuplicateFile.absolute_path.in_(resolved_paths),
                )
            ).all()
            for duplicate_file, group in rows:
                memberships.setdefault(duplicate_file.absolute_path, []).append(
                    {
                        "duplicate_file_id": int(duplicate_file.id),
                        "group_id": int(group.id),
                        "root_id": int(duplicate_file.root_id),
                        "snapshot_size": int(duplicate_file.size),
                        "snapshot_mtime_ns": int(duplicate_file.mtime_ns),
                        "snapshot_device": int(duplicate_file.device),
                        "snapshot_inode": int(duplicate_file.inode),
                        "discovery_hash": str(group.content_hash),
                    }
                )

    path_contexts: list[dict[str, Any]] = []
    for item in inspections:
        root_index = _containing_scan_root(item.resolved_path, scan_roots)
        entries = memberships.get(item.resolved_path or "", [])
        reasons: list[str] = []
        if root_index is None:
            reasons.append("PATH_OUTSIDE_SCAN_ROOTS")
        if item.in_quarantine:
            reasons.append("QUARANTINE_EXCLUDED")
        if item.is_symlink:
            reasons.append("SYMLINK_EXCLUDED")
        elif item.exists and not item.is_regular_file:
            reasons.append("NON_REGULAR_FILE_EXCLUDED")
        if not entries and not reasons and scan.status == "completed":
            if scan_args.get("min_size") or scan_args.get("name_patterns") or scan_args.get("exclude_patterns"):
                reasons.append("NOT_IN_SNAPSHOT_FILTER_OR_SCAN_TIME_STATE")
            else:
                reasons.append("NOT_IN_SNAPSHOT_AT_SCAN_TIME")

        path_contexts.append(
            {
                "resolved_path": item.resolved_path,
                "scan_root_index": root_index,
                "included_in_duplicate_snapshot": bool(entries),
                "memberships": entries,
                "reasons": reasons,
            }
        )

    group_ids_a = {
        entry["group_id"]
        for entry in path_contexts[0]["memberships"]
    }
    group_ids_b = {
        entry["group_id"]
        for entry in path_contexts[1]["memberships"]
    }
    shared_groups = sorted(group_ids_a & group_ids_b)

    return {
        "scan_job_id": int(scan.id),
        "name": scan.name,
        "status": scan.status,
        "mode": scan.mode,
        "roots": scan_roots,
        "fclones_args": {
            "min_size": scan_args.get("min_size"),
            "name_patterns": scan_args.get("name_patterns"),
            "exclude_patterns": scan_args.get("exclude_patterns"),
            "match_links": False,
            "hidden": True,
            "no_ignore": True,
        },
        "paths": path_contexts,
        "same_duplicate_group": bool(shared_groups),
        "shared_group_ids": shared_groups,
    }


def diagnose_duplicate_pair(
    session_factory: Any,
    settings: Any,
    *,
    path_a: str,
    path_b: str,
    scan_job_id: int | None = None,
) -> dict[str, Any]:
    first = _inspect_path(settings, path_a)
    second = _inspect_path(settings, path_b)
    inspections = (first, second)

    same_filesystem_entry = bool(
        first.device is not None
        and first.inode is not None
        and second.device is not None
        and second.inode is not None
        and (first.device, first.inode) == (second.device, second.inode)
    )
    size_match = (
        first.size == second.size
        if first.size is not None and second.size is not None
        else None
    )
    sha256_match = (
        first.sha256 == second.sha256
        if first.sha256 is not None and second.sha256 is not None
        else None
    )

    if not first.allowed or not second.allowed:
        diagnosis = "PATH_OUTSIDE_CONFIGURED_ROOTS"
    elif not first.exists or not second.exists:
        diagnosis = "PATH_NOT_FOUND"
    elif first.is_symlink or second.is_symlink:
        diagnosis = "SYMLINK_UNSUPPORTED"
    elif not first.is_regular_file or not second.is_regular_file:
        diagnosis = "NOT_REGULAR_FILE"
    elif same_filesystem_entry:
        diagnosis = "SAME_FILESYSTEM_ENTRY"
    elif size_match is False:
        diagnosis = "DIFFERENT_SIZE"
    elif sha256_match is False:
        diagnosis = "DIFFERENT_CONTENT"
    elif sha256_match is True:
        diagnosis = "EXACT_CONTENT_DUPLICATE"
    else:
        diagnosis = "INDETERMINATE"

    response: dict[str, Any] = {
        "diagnosis": diagnosis,
        "same_filesystem_entry": same_filesystem_entry,
        "size_match": size_match,
        "sha256_match": sha256_match,
        "exact_duplicate_copies": bool(
            diagnosis == "EXACT_CONTENT_DUPLICATE" and not same_filesystem_entry
        ),
        "paths": [first.to_dict(), second.to_dict()],
        "scan": None,
    }

    if scan_job_id is not None:
        response["scan"] = _load_scan_context(
            session_factory,
            int(scan_job_id),
            inspections,
        )

    return response
