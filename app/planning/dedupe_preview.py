from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DuplicateFile, DuplicateGroup, ScanJob
from app.path_safety import is_path_allowed, is_reserved_quarantine_path
from app.planning.dedupe_config import (
    AdvancedDedupeConfig,
    canonical_json_dumps,
    compute_config_digest,
    validate_and_canonicalize_config,
)
from app.planning.dedupe_engine import (
    AdvancedDedupeResult,
    DedupeGroupSnapshot,
    DedupeMemberSnapshot,
    GroupDecisionResult,
    derive_recursive_balance_bucket,
    directory_ancestors_to_scan_root,
    normalize_dedupe_path,
    run_advanced_dedupe,
    _is_lexical_contained,
    _lexical_relpath,
    _stable_group_path_fingerprint,
)


MAX_DEDUPE_CANDIDATES = 50_000
MAX_PLANNED_QUARANTINE = 100_000


class DedupeError(Exception):
    def __init__(self, message: str, code: str, details: Any = None, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details or {}}}


class DedupeScanNotFoundError(DedupeError, ValueError):
    def __init__(self, message: str = "DEDUPE_SCAN_NOT_FOUND: scan not found", details: Any = None):
        super().__init__(message=message, code="DEDUPE_SCAN_NOT_FOUND", details=details, status_code=404)


class DedupeScanNotCompletedError(DedupeError, ValueError):
    def __init__(self, message: str = "DEDUPE_SCAN_NOT_COMPLETED: scan not completed", details: Any = None):
        super().__init__(message=message, code="DEDUPE_SCAN_NOT_COMPLETED", details=details, status_code=409)


class DedupeLimitExceededError(DedupeError, ValueError):
    def __init__(self, message: str = "DEDUPE_LIMIT_EXCEEDED: limit exceeded", details: Any = None):
        super().__init__(message=message, code="DEDUPE_LIMIT_EXCEEDED", details=details, status_code=422)


class DedupeInvalidConfigError(DedupeError, ValueError):
    def __init__(self, message: str = "DEDUPE_INVALID_CONFIG: invalid dedupe configuration", details: Any = None):
        super().__init__(message=message, code="DEDUPE_INVALID_CONFIG", details=details, status_code=422)


class DedupeFactorUnavailableError(DedupeError, ValueError):
    def __init__(self, message: str = "DEDUPE_FACTOR_UNAVAILABLE: factor unavailable in V1", details: Any = None):
        super().__init__(message=message, code="DEDUPE_FACTOR_UNAVAILABLE", details=details, status_code=422)


class DedupePreviewChangedError(DedupeError):
    def __init__(self, message: str = "Preview changed; run Preview again before generating a Draft", details: Any = None):
        super().__init__(message=message, code="PREVIEW_CHANGED", details=details, status_code=409)


class DedupeEmptyPlanError(DedupeError):
    def __init__(self, message: str = "DEDUPE_EMPTY_PLAN: advanced dedupe produced no quarantine intents", details: Any = None):
        super().__init__(message=message, code="DEDUPE_EMPTY_PLAN", details=details, status_code=422)


def derive_canonical_top_level_dir(scan_root: str, relative_path: str) -> str:
    norm_root = normalize_dedupe_path(scan_root)
    rel_norm = normalize_dedupe_path(relative_path).lstrip("/")
    rel_parts = [p for p in rel_norm.split("/") if p and p != "."]
    if len(rel_parts) > 1:
        return normalize_dedupe_path(f"{norm_root}/{rel_parts[0]}")
    return norm_root


@dataclass(frozen=True)
class _RecursiveProtectionSnapshot:
    count: int
    stable: bool
    device: int | None
    inode: int | None
    tree_identity_digest: str | None

    def digest_payload(self) -> dict[str, Any]:
        return {
            "stable": self.stable,
            "device": self.device,
            "inode": self.inode,
            "tree_identity_digest": self.tree_identity_digest,
        }


def _recursive_directory_open_flags() -> int | None:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        return None
    if os.open not in os.supports_dir_fd:
        return None
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _open_absolute_directory_nofollow(directory: str | Path) -> tuple[int, os.stat_result] | None:
    flags = _recursive_directory_open_flags()
    if flags is None:
        return None

    absolute = os.path.abspath(os.path.normpath(str(directory)))
    if not absolute.startswith(os.sep):
        return None

    current_fd: int | None = None
    try:
        current_fd = os.open(os.sep, os.O_RDONLY | os.O_DIRECTORY)
        for part in Path(absolute).parts[1:]:
            next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        opened_st = os.fstat(current_fd)
        if not stat.S_ISDIR(opened_st.st_mode):
            os.close(current_fd)
            return None
        return current_fd, opened_st
    except OSError:
        if current_fd is not None:
            try:
                os.close(current_fd)
            except OSError:
                pass
        return None


def _directory_binding_matches(directory: str | Path, expected_device: int, expected_inode: int) -> bool:
    reopened = _open_absolute_directory_nofollow(directory)
    if reopened is None:
        return False
    fd, st = reopened
    try:
        return int(st.st_dev) == expected_device and int(st.st_ino) == expected_inode
    finally:
        os.close(fd)


def _unstable_recursive_snapshot(
    *,
    device: int | None = None,
    inode: int | None = None,
) -> _RecursiveProtectionSnapshot:
    return _RecursiveProtectionSnapshot(
        count=0,
        stable=False,
        device=device,
        inode=inode,
        tree_identity_digest=None,
    )


def _collect_recursive_identity_rows(
    root_fd: int,
    *,
    root_device: int,
    root_inode: int,
) -> tuple[int, list[dict[str, Any]]] | None:
    """Consume root_fd and collect one descriptor-bound tree identity pass."""
    dir_flags = _recursive_directory_open_flags()
    if dir_flags is None:
        try:
            os.close(root_fd)
        except OSError:
            pass
        return None

    regular_flags = os.O_RDONLY | os.O_NOFOLLOW
    count = 0
    stable = True
    identity_rows: list[dict[str, Any]] = [
        {
            "path": ".",
            "object_type": "directory",
            "device": root_device,
            "inode": root_inode,
        }
    ]
    stack: list[tuple[int, str]] = [(root_fd, ".")]

    while stack and stable:
        current_fd, relative_dir = stack.pop()
        try:
            try:
                with os.scandir(current_fd) as iterator:
                    entries = sorted(iterator, key=lambda entry: entry.name)
            except OSError:
                stable = False
                continue

            for entry in entries:
                try:
                    entry_st = entry.stat(follow_symlinks=False)
                except OSError:
                    stable = False
                    break

                relative_path = entry.name if relative_dir == "." else f"{relative_dir}/{entry.name}"
                if stat.S_ISLNK(entry_st.st_mode):
                    continue

                if stat.S_ISREG(entry_st.st_mode):
                    try:
                        file_fd = os.open(entry.name, regular_flags, dir_fd=current_fd)
                    except OSError:
                        stable = False
                        break
                    try:
                        opened_file_st = os.fstat(file_fd)
                    finally:
                        os.close(file_fd)
                    if (
                        not stat.S_ISREG(opened_file_st.st_mode)
                        or int(opened_file_st.st_dev) != int(entry_st.st_dev)
                        or int(opened_file_st.st_ino) != int(entry_st.st_ino)
                    ):
                        stable = False
                        break
                    count += 1
                    identity_rows.append(
                        {
                            "path": relative_path,
                            "object_type": "file",
                            "device": int(opened_file_st.st_dev),
                            "inode": int(opened_file_st.st_ino),
                        }
                    )
                    continue

                if stat.S_ISDIR(entry_st.st_mode):
                    try:
                        child_fd = os.open(entry.name, dir_flags, dir_fd=current_fd)
                    except OSError:
                        stable = False
                        break
                    child_st = os.fstat(child_fd)
                    if (
                        not stat.S_ISDIR(child_st.st_mode)
                        or int(child_st.st_dev) != int(entry_st.st_dev)
                        or int(child_st.st_ino) != int(entry_st.st_ino)
                    ):
                        os.close(child_fd)
                        stable = False
                        break
                    identity_rows.append(
                        {
                            "path": relative_path,
                            "object_type": "directory",
                            "device": int(child_st.st_dev),
                            "inode": int(child_st.st_ino),
                        }
                    )
                    stack.append((child_fd, relative_path))
        finally:
            try:
                os.close(current_fd)
            except OSError:
                pass

    if not stable:
        for fd, _relative_dir in stack:
            try:
                os.close(fd)
            except OSError:
                pass
        return None

    identity_rows.sort(key=lambda row: (row["path"], row["object_type"], row["device"], row["inode"]))
    return count, identity_rows


def _identity_rows_still_bound(
    directory: str | Path,
    *,
    root_device: int,
    root_inode: int,
    identity_rows: Sequence[Mapping[str, Any]],
) -> bool:
    """Rebind every recorded identity through the current lexical tree, no-follow."""
    dir_flags = _recursive_directory_open_flags()
    if dir_flags is None:
        return False

    opened = _open_absolute_directory_nofollow(directory)
    if opened is None:
        return False
    root_fd, root_st = opened
    try:
        if (
            int(root_st.st_dev) != root_device
            or int(root_st.st_ino) != root_inode
        ):
            return False

        directory_identities: dict[str, tuple[int, int]] = {}
        for row in identity_rows:
            if row.get("object_type") != "directory":
                continue
            relative = str(row.get("path", ""))
            directory_identities[relative] = (int(row["device"]), int(row["inode"]))

        if directory_identities.get(".") != (root_device, root_inode):
            return False

        for row in identity_rows:
            relative = str(row.get("path", ""))
            object_type = row.get("object_type")
            expected_device = int(row["device"])
            expected_inode = int(row["inode"])

            if relative == ".":
                if object_type != "directory":
                    return False
                continue
            if not relative or os.path.isabs(relative):
                return False

            parts = Path(relative).parts
            if not parts or any(part in ("", ".", "..") for part in parts):
                return False

            current_fd = os.dup(root_fd)
            current_relative = "."
            try:
                for part in parts[:-1]:
                    next_fd = os.open(part, dir_flags, dir_fd=current_fd)
                    next_st = os.fstat(next_fd)
                    next_relative = part if current_relative == "." else f"{current_relative}/{part}"
                    expected_parent = directory_identities.get(next_relative)
                    os.close(current_fd)
                    current_fd = next_fd
                    current_relative = next_relative
                    if (
                        expected_parent is None
                        or not stat.S_ISDIR(next_st.st_mode)
                        or int(next_st.st_dev) != expected_parent[0]
                        or int(next_st.st_ino) != expected_parent[1]
                    ):
                        return False

                leaf = parts[-1]
                if object_type == "directory":
                    leaf_fd = os.open(leaf, dir_flags, dir_fd=current_fd)
                    try:
                        leaf_st = os.fstat(leaf_fd)
                    finally:
                        os.close(leaf_fd)
                    if not stat.S_ISDIR(leaf_st.st_mode):
                        return False
                elif object_type == "file":
                    leaf_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
                    leaf_fd = os.open(leaf, leaf_flags, dir_fd=current_fd)
                    try:
                        leaf_st = os.fstat(leaf_fd)
                    finally:
                        os.close(leaf_fd)
                    if not stat.S_ISREG(leaf_st.st_mode):
                        return False
                else:
                    return False

                if (
                    int(leaf_st.st_dev) != expected_device
                    or int(leaf_st.st_ino) != expected_inode
                ):
                    return False
            except OSError:
                return False
            finally:
                try:
                    os.close(current_fd)
                except OSError:
                    pass
        return True
    finally:
        os.close(root_fd)


def _snapshot_real_regular_files_recursive(directory: str | Path) -> _RecursiveProtectionSnapshot:
    """Descriptor-bound recursive regular-file snapshot; any authority race fails closed."""
    opened = _open_absolute_directory_nofollow(directory)
    if opened is None:
        return _unstable_recursive_snapshot()

    root_fd, root_st = opened
    root_device = int(root_st.st_dev)
    root_inode = int(root_st.st_ino)
    first = _collect_recursive_identity_rows(
        root_fd,
        root_device=root_device,
        root_inode=root_inode,
    )
    if first is None:
        return _unstable_recursive_snapshot(device=root_device, inode=root_inode)
    count, identity_rows = first

    # Reacquire the lexical protected root and collect the tree again. The
    # first pass may have kept scanning a descendant fd after that descendant
    # was renamed out of the tree. Requiring an identical second descriptor-
    # bound pass catches persistent membership changes from the first pass.
    verification_opened = _open_absolute_directory_nofollow(directory)
    if verification_opened is None:
        return _unstable_recursive_snapshot(device=root_device, inode=root_inode)
    verification_fd, verification_st = verification_opened
    if (
        int(verification_st.st_dev) != root_device
        or int(verification_st.st_ino) != root_inode
    ):
        os.close(verification_fd)
        return _unstable_recursive_snapshot(device=root_device, inode=root_inode)

    verification = _collect_recursive_identity_rows(
        verification_fd,
        root_device=root_device,
        root_inode=root_inode,
    )
    if verification is None:
        return _unstable_recursive_snapshot(device=root_device, inode=root_inode)
    verification_count, verification_rows = verification
    if verification_count != count or verification_rows != identity_rows:
        return _unstable_recursive_snapshot(device=root_device, inode=root_inode)

    # The verification pass itself can hold a child fd that becomes detached
    # after open but before scan. Rebind every recorded row through a freshly
    # reacquired lexical root so persistent descendant detach/replacement is
    # rejected before this snapshot can be authoritative.
    if not _identity_rows_still_bound(
        directory,
        root_device=root_device,
        root_inode=root_inode,
        identity_rows=identity_rows,
    ):
        return _unstable_recursive_snapshot(device=root_device, inode=root_inode)

    if not _directory_binding_matches(directory, root_device, root_inode):
        return _unstable_recursive_snapshot(device=root_device, inode=root_inode)

    tree_identity_digest = hashlib.sha256(
        canonical_json_dumps(identity_rows).encode("utf-8")
    ).hexdigest()
    return _RecursiveProtectionSnapshot(
        count=count,
        stable=True,
        device=root_device,
        inode=root_inode,
        tree_identity_digest=tree_identity_digest,
    )


def _count_real_regular_files_recursive(directory: str | Path) -> int:
    """Count real regular files recursively with descriptor-bound no-follow authority."""
    return _snapshot_real_regular_files_recursive(directory).count


@dataclass(frozen=True)
class DedupePreviewCompilation:
    scan_job_id: int
    scan_roots: tuple[str, ...]
    scorer_config: AdvancedDedupeConfig
    scorer_config_digest: str
    groups: tuple[GroupDecisionResult, ...]
    candidate_member_count: int
    actionable_group_count: int
    skipped_group_count: int
    planned_quarantine_count: int
    expected_reclaim_bytes: int
    released_bytes_by_scan_root: dict[int, int]
    source_snapshot_digest: str
    decision_digest: str
    db_lineage_digest: str
    summary: dict[str, Any]


def compute_source_snapshot_digest(
    scan_job_id: int,
    scan_roots: Sequence[str],
    scan_provenance: Mapping[str, Any],
    raw_groups_data: Sequence[Mapping[str, Any]],
    member_safety_facts: Mapping[str, Mapping[str, Any]],
    directory_file_counts: Mapping[str, int] | None,
    directory_protection_snapshots: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    payload = {
        "scan_job_id": scan_job_id,
        "scan_roots": list(scan_roots),
        "scan_provenance": dict(sorted(scan_provenance.items())),
        "raw_groups": list(raw_groups_data),
        "member_safety_facts": {k: dict(sorted(v.items())) for k, v in sorted(member_safety_facts.items())},
        "directory_file_counts": dict(sorted(directory_file_counts.items())) if directory_file_counts is not None else None,
    }
    if directory_protection_snapshots is not None:
        payload["directory_protection_snapshots"] = {
            k: dict(sorted(v.items())) for k, v in sorted(directory_protection_snapshots.items())
        }
    return hashlib.sha256(canonical_json_dumps(payload).encode("utf-8")).hexdigest()


def compute_decision_digest(
    scorer_config_digest: str,
    source_snapshot_digest: str,
    dedupe_result: AdvancedDedupeResult,
) -> str:
    payload = {
        "scorer_config_digest": scorer_config_digest,
        "source_snapshot_digest": source_snapshot_digest,
        "groups": [
            {
                "status": g.status,
                "skip_reason": g.skip_reason,
                "file_size": g.file_size,
                "recommended_keep_path": g.recommended_keep.absolute_path if g.recommended_keep else None,
                "quarantine_candidates": list(g.quarantine_candidates),
                "reclaimable_bytes": g.reclaimable_bytes,
                "group_decision_fingerprint": g.group_decision_fingerprint,
            }
            for g in dedupe_result.groups
        ],
        "summary": {
            "selection_mode": dedupe_result.summary.get("selection_mode"),
            "actionable_group_count": dedupe_result.actionable_group_count,
            "skipped_group_count": dedupe_result.skipped_group_count,
            "planned_quarantine_count": dedupe_result.planned_quarantine_count,
            "expected_reclaim_bytes": dedupe_result.expected_reclaim_bytes,
            "released_bytes_by_scan_root": {str(k): v for k, v in sorted(dedupe_result.released_bytes_by_scan_root.items())},
        },
    }
    return hashlib.sha256(canonical_json_dumps(payload).encode("utf-8")).hexdigest()


def _compute_db_lineage_digest_from_loaded(
    scan: ScanJob,
    scan_roots: Sequence[str],
    db_groups: Sequence[DuplicateGroup],
    group_files: Mapping[int, Sequence[DuplicateFile]],
) -> str:
    payload = {
        "scan": {
            "id": scan.id,
            "name": scan.name,
            "mode": scan.mode,
            "status": scan.status,
            "roots": list(scan_roots),
            "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
        },
        "groups": [],
    }
    for group in sorted(db_groups, key=lambda g: (g.id, g.content_hash, g.file_size)):
        files = sorted(group_files.get(group.id, ()), key=lambda f: (f.id, f.root_id, normalize_dedupe_path(f.absolute_path)))
        payload["groups"].append({
            "id": group.id,
            "scan_job_id": group.scan_job_id,
            "content_hash": group.content_hash,
            "file_size": group.file_size,
            "member_count": group.member_count,
            "files": [
                {
                    "id": f.id,
                    "group_id": f.group_id,
                    "root_id": f.root_id,
                    "absolute_path": f.absolute_path,
                    "relative_path": f.relative_path,
                    "top_level_dir": f.top_level_dir,
                    "size": f.size,
                    "mtime_ns": f.mtime_ns,
                    "device": int(getattr(f, "device", 0) or 0),
                    "inode": int(getattr(f, "inode", 0) or 0),
                }
                for f in files
            ],
        })
    return hashlib.sha256(canonical_json_dumps(payload).encode("utf-8")).hexdigest()


def compute_current_dedupe_db_lineage_digest(session: Session, scan_job_id: int) -> str | None:
    scan = session.get(ScanJob, scan_job_id)
    if scan is None:
        return None
    try:
        raw_roots = json.loads(scan.roots_json)
    except Exception:
        raw_roots = [scan.roots_json]
    if isinstance(raw_roots, list) and all(isinstance(root, str) for root in raw_roots):
        scan_roots = tuple(normalize_dedupe_path(root) for root in raw_roots)
    else:
        scan_roots = (str(scan.roots_json),)
    db_groups = list(session.scalars(select(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_job_id)))
    member_count = session.scalar(
        select(func.count(DuplicateFile.id)).join(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_job_id)
    ) or 0
    if member_count > MAX_DEDUPE_CANDIDATES:
        return None
    group_files: dict[int, list[DuplicateFile]] = {}
    for group in db_groups:
        group_files[group.id] = list(session.scalars(select(DuplicateFile).where(DuplicateFile.group_id == group.id)))
    return _compute_db_lineage_digest_from_loaded(scan, scan_roots, db_groups, group_files)


def compile_advanced_dedupe_preview(
    session: Session,
    scan_job_id: int,
    config: AdvancedDedupeConfig | Mapping[str, Any],
    *,
    allowed_roots: Sequence[str | Path],
    quarantine_root: str | Path | None = None,
    protect_last_file: bool = True,
) -> DedupePreviewCompilation:
    config = validate_and_canonicalize_config(config)
    config_digest = compute_config_digest(config)
    recursive_mode = config.selection_mode == "recursive_directory_balanced_by_bytes"

    scan = session.get(ScanJob, scan_job_id)
    if scan is None:
        raise DedupeScanNotFoundError(f"DEDUPE_SCAN_NOT_FOUND: scan job #{scan_job_id} not found")
    if scan.status != "completed":
        raise DedupeScanNotCompletedError(f"DEDUPE_SCAN_NOT_COMPLETED: scan job #{scan_job_id} has status '{scan.status}'")
    try:
        raw_roots = json.loads(scan.roots_json)
    except Exception as exc:
        raise ValueError(f"Invalid scan roots_json: {exc}") from exc
    if not isinstance(raw_roots, list) or len(raw_roots) == 0 or not all(isinstance(r, str) for r in raw_roots):
        raise ValueError("Invalid scan roots_json: must be non-empty list of strings")
    scan_roots = tuple(normalize_dedupe_path(r) for r in raw_roots)

    total_candidates = session.scalar(
        select(func.count(DuplicateFile.id)).join(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_job_id)
    ) or 0
    if total_candidates > MAX_DEDUPE_CANDIDATES:
        raise DedupeLimitExceededError(f"DEDUPE_LIMIT_EXCEEDED: candidate count {total_candidates} exceeds maximum {MAX_DEDUPE_CANDIDATES}")

    db_groups = list(session.scalars(select(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_job_id)))
    db_groups.sort(key=lambda g: (-g.file_size, g.content_hash, g.id))
    group_files: dict[int, list[DuplicateFile]] = {}
    seen_member_paths: dict[str, list[int]] = {}
    for db_g in db_groups:
        files = list(session.scalars(select(DuplicateFile).where(DuplicateFile.group_id == db_g.id)))
        files.sort(key=lambda f: (f.root_id, normalize_dedupe_path(f.absolute_path), f.id))
        group_files[db_g.id] = files
        for f in files:
            seen_member_paths.setdefault(normalize_dedupe_path(f.absolute_path), []).append(db_g.id)

    inconsistent_group_ids = set()
    for _norm_p, gids in seen_member_paths.items():
        if len(gids) > 1:
            inconsistent_group_ids.update(gids)

    group_snapshots: list[DedupeGroupSnapshot] = []
    pre_skipped_reasons: dict[int | str, str] = {}
    member_safety_facts: dict[str, dict[str, Any]] = {}
    distinct_top_dirs: set[str] = set()
    recursive_protection_dirs: set[str] = set()

    for db_g in db_groups:
        db_files = group_files[db_g.id]
        group_skip_reason: str | None = "SOURCE_SNAPSHOT_INCONSISTENT" if db_g.id in inconsistent_group_ids else None
        members: list[DedupeMemberSnapshot] = []
        candidate_group_top_dirs: set[str] = set()
        candidate_group_recursive_dirs: set[str] = set()

        for f in db_files:
            abs_p = Path(f.absolute_path)
            norm_abs = normalize_dedupe_path(f.absolute_path)
            member_fail_reason: str | None = "SOURCE_SNAPSHOT_INCONSISTENT" if db_g.id in inconsistent_group_ids else None
            if member_fail_reason is None and (f.root_id < 0 or f.root_id >= len(scan_roots)):
                member_fail_reason = "INVALID_SCAN_ROOT_INDEX"
            norm_root = scan_roots[f.root_id] if 0 <= f.root_id < len(scan_roots) else ""
            if member_fail_reason is None:
                if not norm_abs.startswith("/") or not norm_root.startswith("/"):
                    member_fail_reason = "INVALID_ABSOLUTE_PATH"
                elif not _is_lexical_contained(norm_abs, norm_root):
                    member_fail_reason = "PATH_OUTSIDE_SCAN_ROOT"
                else:
                    expected_rel = _lexical_relpath(norm_abs, norm_root)
                    actual_rel = normalize_dedupe_path(f.relative_path) if f.relative_path.startswith("/") else os.path.normpath(f.relative_path)
                    if actual_rel != expected_rel:
                        member_fail_reason = "RELATIVE_PATH_MISMATCH"

            canonical_top: str | None = None
            if member_fail_reason is None:
                actual_rel = normalize_dedupe_path(f.relative_path) if f.relative_path.startswith("/") else os.path.normpath(f.relative_path)
                canonical_top = derive_canonical_top_level_dir(norm_root, actual_rel)
                norm_db_top = normalize_dedupe_path(f.top_level_dir) if f.top_level_dir else ""
                if norm_db_top != canonical_top:
                    member_fail_reason = "TOP_LEVEL_DIR_MISMATCH"

            is_allowed = False
            is_reserved_quarantine = False
            if member_fail_reason is None:
                is_allowed = is_path_allowed(abs_p, allowed_roots)
                if not is_allowed:
                    member_fail_reason = "PATH_OUTSIDE_ALLOWED_ROOT"
                elif quarantine_root and is_reserved_quarantine_path(abs_p, quarantine_root):
                    is_reserved_quarantine = True
                    member_fail_reason = "RESERVED_QUARANTINE_PATH"

            exists = False
            is_file = False
            is_symlink = False
            try:
                is_symlink = abs_p.is_symlink() or os.path.islink(abs_p)
                exists = abs_p.exists()
                is_file = abs_p.is_file() and not is_symlink
            except OSError:
                pass
            if member_fail_reason is None:
                if is_symlink:
                    member_fail_reason = "SYMLINK"
                elif not exists:
                    member_fail_reason = "SOURCE_NOT_FOUND"
                elif not is_file:
                    member_fail_reason = "NOT_REGULAR_FILE"

            live_identity: dict[str, Any] | None = None
            if recursive_mode:
                try:
                    live_stat = os.lstat(abs_p)
                    if stat.S_ISREG(live_stat.st_mode):
                        object_type = "file"
                    elif stat.S_ISDIR(live_stat.st_mode):
                        object_type = "directory"
                    elif stat.S_ISLNK(live_stat.st_mode):
                        object_type = "symlink"
                    else:
                        object_type = "special"
                    live_identity = {
                        "device": int(live_stat.st_dev),
                        "inode": int(live_stat.st_ino),
                        "size": int(live_stat.st_size),
                        "mtime_ns": int(live_stat.st_mtime_ns),
                        "object_type": object_type,
                    }
                except OSError:
                    live_identity = {"missing": True}

            if member_fail_reason is None and recursive_mode:
                try:
                    candidate_group_recursive_dirs.update(directory_ancestors_to_scan_root(norm_abs, norm_root))
                except ValueError:
                    member_fail_reason = "PATH_OUTSIDE_SCAN_ROOT"

            safety_reasons = (member_fail_reason,) if member_fail_reason else ()
            safety_facts: dict[str, Any] = {
                "exists": exists,
                "is_file": is_file,
                "is_symlink": is_symlink,
                "is_allowed": is_allowed,
                "is_reserved_quarantine": is_reserved_quarantine,
                "safety_reasons": list(safety_reasons),
            }
            if recursive_mode:
                safety_facts["live_identity"] = live_identity
            member_safety_facts[norm_abs] = safety_facts
            if member_fail_reason is not None and group_skip_reason is None:
                if member_fail_reason in ("SOURCE_NOT_FOUND", "NOT_REGULAR_FILE"):
                    group_skip_reason = "SOURCE_SNAPSHOT_STALE"
                elif member_fail_reason in ("SYMLINK", "RESERVED_QUARANTINE_PATH"):
                    group_skip_reason = "FILESYSTEM_SAFETY_CHECK_FAILED"
                else:
                    group_skip_reason = member_fail_reason
            if canonical_top:
                candidate_group_top_dirs.add(canonical_top)
            members.append(DedupeMemberSnapshot(
                absolute_path=norm_abs,
                relative_path=f.relative_path,
                scan_root_index=f.root_id if 0 <= f.root_id < len(scan_roots) else 0,
                scan_root_path=norm_root,
                mtime_ns=f.mtime_ns,
                size=f.size,
                eligible_as_keep=(member_fail_reason is None),
                safety_reasons=safety_reasons,
                top_level_dir=canonical_top,
            ))

        if group_skip_reason is not None:
            pre_skipped_reasons[db_g.id] = group_skip_reason
        else:
            distinct_top_dirs.update(candidate_group_top_dirs)
            if recursive_mode:
                recursive_protection_dirs.update(candidate_group_recursive_dirs)
        group_snapshots.append(DedupeGroupSnapshot(
            provenance_id=db_g.id,
            content_hash=db_g.content_hash,
            file_size=db_g.file_size,
            members=tuple(members),
        ))

    directory_file_counts: dict[str, int] | None = None
    directory_protection_snapshots: dict[str, dict[str, Any]] | None = None
    effective_protection = bool(protect_last_file) or recursive_mode
    if effective_protection:
        directory_file_counts = {}
        if recursive_mode:
            directory_protection_snapshots = {}
        protected_dirs = recursive_protection_dirs if recursive_mode else distinct_top_dirs
        for directory in sorted(protected_dirs):
            normalized_directory = normalize_dedupe_path(directory)
            if recursive_mode:
                protection_snapshot = _snapshot_real_regular_files_recursive(directory)
                directory_file_counts[normalized_directory] = protection_snapshot.count
                directory_protection_snapshots[normalized_directory] = protection_snapshot.digest_payload()
            else:
                directory_file_counts[normalized_directory] = _count_real_regular_files_recursive(directory)

    engine_result = run_advanced_dedupe(
        group_snapshots,
        config,
        scan_roots=scan_roots,
        protect_last_file_counts=directory_file_counts,
        pre_skipped_reasons=pre_skipped_reasons,
    )
    if engine_result.planned_quarantine_count > MAX_PLANNED_QUARANTINE:
        raise DedupeLimitExceededError(
            f"DEDUPE_LIMIT_EXCEEDED: planned quarantine count {engine_result.planned_quarantine_count} exceeds maximum {MAX_PLANNED_QUARANTINE}"
        )

    raw_groups_data = []
    for db_g in sorted(db_groups, key=lambda g: (-g.file_size, g.content_hash, g.id)):
        sorted_files = sorted(group_files[db_g.id], key=lambda f: (f.root_id, normalize_dedupe_path(f.absolute_path), f.id))
        raw_groups_data.append({
            "provenance_id": db_g.id,
            "content_hash": db_g.content_hash,
            "file_size": db_g.file_size,
            "member_count": db_g.member_count,
            "files": [
                {
                    "group_id": f.group_id,
                    "raw_root_id": f.root_id,
                    "absolute_path": f.absolute_path,
                    "relative_path": f.relative_path,
                    "top_level_dir": f.top_level_dir,
                    "size": f.size,
                    "mtime_ns": f.mtime_ns,
                    "scan_device": getattr(f, "device", 0),
                    "scan_inode": getattr(f, "inode", 0),
                }
                for f in sorted_files
            ],
        })
    scan_provenance = {
        "name": scan.name,
        "mode": scan.mode,
        "status": scan.status,
        "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
    }
    source_snapshot_digest = compute_source_snapshot_digest(
        scan_job_id=scan_job_id,
        scan_roots=scan_roots,
        scan_provenance=scan_provenance,
        raw_groups_data=raw_groups_data,
        member_safety_facts=member_safety_facts,
        directory_file_counts=directory_file_counts,
        directory_protection_snapshots=directory_protection_snapshots,
    )
    decision_digest = compute_decision_digest(
        scorer_config_digest=config_digest,
        source_snapshot_digest=source_snapshot_digest,
        dedupe_result=engine_result,
    )
    db_lineage_digest = _compute_db_lineage_digest_from_loaded(scan, scan_roots, db_groups, group_files)
    return DedupePreviewCompilation(
        scan_job_id=scan_job_id,
        scan_roots=scan_roots,
        scorer_config=config,
        scorer_config_digest=config_digest,
        groups=tuple(engine_result.groups),
        candidate_member_count=total_candidates,
        actionable_group_count=engine_result.actionable_group_count,
        skipped_group_count=engine_result.skipped_group_count,
        planned_quarantine_count=engine_result.planned_quarantine_count,
        expected_reclaim_bytes=engine_result.expected_reclaim_bytes,
        released_bytes_by_scan_root=engine_result.released_bytes_by_scan_root,
        source_snapshot_digest=source_snapshot_digest,
        decision_digest=decision_digest,
        db_lineage_digest=db_lineage_digest,
        summary=engine_result.summary,
    )


def canonicalize_safety_path(value: Path | str) -> str:
    return str(Path(value).expanduser().resolve(strict=False))


def canonicalize_effective_safety_policy(
    protect_last_file: bool = True,
    allowed_roots: Sequence[str | Path] | None = None,
    quarantine_root: str | Path | None = None,
) -> dict[str, Any]:
    if allowed_roots:
        resolved_roots = {canonicalize_safety_path(r) for r in allowed_roots if str(r).strip()}
        canon_allowed = sorted(list(resolved_roots))
    else:
        canon_allowed = []
    canon_quarantine = (
        canonicalize_safety_path(quarantine_root)
        if quarantine_root is not None and str(quarantine_root).strip()
        else None
    )
    return {
        "allowed_roots": canon_allowed,
        "protect_last_file": bool(protect_last_file),
        "quarantine_root": canon_quarantine,
    }


def compute_preview_digest(
    *,
    scan_job_id: int,
    scorer_config_digest: str,
    source_snapshot_digest: str,
    decision_digest: str,
    effective_safety_policy: Mapping[str, Any],
    dedupe_engine_version: int = 1,
) -> str:
    payload = {
        "dedupe_engine_version": dedupe_engine_version,
        "scan_job_id": scan_job_id,
        "scorer_config_digest": scorer_config_digest,
        "source_snapshot_digest": source_snapshot_digest,
        "decision_digest": decision_digest,
        "effective_safety_policy": dict(sorted(effective_safety_policy.items())),
    }
    return hashlib.sha256(canonical_json_dumps(payload).encode("utf-8")).hexdigest()


def build_preview_response(
    compilation: DedupePreviewCompilation,
    *,
    protect_last_file: bool = True,
    allowed_roots: Sequence[str | Path] | None = None,
    quarantine_root: str | Path | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    canonical_safety_policy = canonicalize_effective_safety_policy(
        protect_last_file=protect_last_file,
        allowed_roots=allowed_roots,
        quarantine_root=quarantine_root,
    )
    preview_digest = compute_preview_digest(
        scan_job_id=compilation.scan_job_id,
        scorer_config_digest=compilation.scorer_config_digest,
        source_snapshot_digest=compilation.source_snapshot_digest,
        decision_digest=compilation.decision_digest,
        effective_safety_policy=canonical_safety_policy,
    )

    recursive_mode = compilation.scorer_config.selection_mode == "recursive_directory_balanced_by_bytes"
    all_rows: list[dict[str, Any]] = []
    for g in compilation.groups:
        g_prov_id = g.group_provenance_id
        g_status = g.status
        g_skip_reason = g.skip_reason
        g_file_size = g.file_size
        g_quarantine_set = set(g.quarantine_candidates)
        keeper_m = next((mem for mem in g.members if mem.recommended_keep), None)
        if g.status == "actionable":
            g_recommended_keep_path = g.recommended_keep.absolute_path if g.recommended_keep else None
            g_reclaimable_bytes = g.reclaimable_bytes
            g_selection_reason = keeper_m.selection_reason if keeper_m else "winner"
            g_balance_info = keeper_m.balance_info if keeper_m else None
        else:
            g_recommended_keep_path = None
            g_reclaimable_bytes = 0
            g_selection_reason = g.skip_reason or "skipped"
            g_balance_info = None

        for m in g.members:
            if g_status == "skipped":
                member_decision = "SKIPPED"
            elif m.recommended_keep:
                member_decision = "KEEP"
            elif m.absolute_path in g_quarantine_set:
                member_decision = "QUARANTINE"
            else:
                member_decision = "SKIPPED"
            contrib_list = [
                {
                    "factor": c.factor,
                    "configured_weight": c.configured_weight,
                    "actual_contribution": c.actual_contribution,
                    "reason": c.reason,
                }
                for c in m.contributions
            ]

            candidate_balance_bucket: str | None = None
            if recursive_mode and isinstance(g_balance_info, dict):
                lca = g_balance_info.get("lca")
                selected_root_index = g_balance_info.get("selected_scan_root_index")
                if isinstance(lca, str) and (
                    selected_root_index is None or selected_root_index == m.scan_root_index
                ):
                    try:
                        parent = normalize_dedupe_path(os.path.dirname(normalize_dedupe_path(m.absolute_path)))
                        candidate_balance_bucket = derive_recursive_balance_bucket(parent, lca)
                    except ValueError:
                        candidate_balance_bucket = None

            recursive_last_file_protection_reason = (
                "RECURSIVE_PROTECT_LAST_FILE"
                if "RECURSIVE_PROTECT_LAST_FILE" in m.safety_reasons
                else None
            )

            all_rows.append({
                "group_provenance_id": g_prov_id,
                "group_status": g_status,
                "group_skip_reason": g_skip_reason,
                "group_file_size": g_file_size,
                "group_recommended_keep_path": g_recommended_keep_path,
                "group_reclaimable_bytes": g_reclaimable_bytes,
                "group_selection_reason": g_selection_reason,
                "group_balance_info": g_balance_info,
                "absolute_path": m.absolute_path,
                "relative_path": m.relative_path,
                "scan_root_index": m.scan_root_index,
                "scan_root_path": m.scan_root_path,
                "eligible_as_keep": m.eligible_as_keep,
                "safety_reasons": list(m.safety_reasons),
                "total_score": m.total_score,
                "contributions": contrib_list,
                "is_top_candidate": m.is_top_candidate,
                "recommended_keep": m.recommended_keep,
                "member_decision": member_decision,
                "selection_reason": m.selection_reason,
                "balance_info": m.balance_info,
                "candidate_balance_bucket": candidate_balance_bucket,
                "recursive_last_file_protection_reason": recursive_last_file_protection_reason,
            })

    total_rows = len(all_rows)
    total_pages = math.ceil(total_rows / page_size) if total_rows > 0 else 0
    start = (page - 1) * page_size
    end = start + page_size
    page_rows = all_rows[start:end] if start < total_rows else []
    released_bytes_by_scan_root_formatted = {
        str(i): compilation.released_bytes_by_scan_root.get(i, 0)
        for i in range(len(compilation.scan_roots))
    }
    summary_data = {
        "selection_mode": compilation.summary.get("selection_mode", compilation.scorer_config.selection_mode),
        "group_count": len(compilation.groups),
        "candidate_member_count": compilation.candidate_member_count,
        "actionable_group_count": compilation.actionable_group_count,
        "skipped_group_count": compilation.skipped_group_count,
        "planned_quarantine_count": compilation.planned_quarantine_count,
        "expected_reclaim_bytes": compilation.expected_reclaim_bytes,
        "released_bytes_by_scan_root": released_bytes_by_scan_root_formatted,
    }
    return {
        "scan_job_id": compilation.scan_job_id,
        "scan_roots": list(compilation.scan_roots),
        "selection_mode": summary_data["selection_mode"],
        "group_count": len(compilation.groups),
        "candidate_member_count": compilation.candidate_member_count,
        "actionable_group_count": compilation.actionable_group_count,
        "skipped_group_count": compilation.skipped_group_count,
        "planned_quarantine_count": compilation.planned_quarantine_count,
        "expected_reclaim_bytes": compilation.expected_reclaim_bytes,
        "released_bytes_by_scan_root": released_bytes_by_scan_root_formatted,
        "scorer_config_digest": compilation.scorer_config_digest,
        "source_snapshot_digest": compilation.source_snapshot_digest,
        "decision_digest": compilation.decision_digest,
        "preview_digest": preview_digest,
        "effective_safety_policy": canonical_safety_policy,
        "preview_source": "completed-scan-readonly-safety",
        "live_filesystem_verified": False,
        "dedupe_engine_version": 1,
        "summary": summary_data,
        "page": page,
        "page_size": page_size,
        "total_rows": total_rows,
        "total_pages": total_pages,
        "rows": page_rows,
    }