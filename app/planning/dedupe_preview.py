from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
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
    normalize_dedupe_path,
    run_advanced_dedupe,
    _is_lexical_contained,
    _lexical_relpath,
    _stable_group_path_fingerprint,
)


MAX_DEDUPE_CANDIDATES = 50_000
MAX_PLANNED_QUARANTINE = 100_000


class DedupeScanNotFoundError(ValueError):
    """Raised when the requested ScanJob does not exist in the database."""
    pass


class DedupeScanNotCompletedError(ValueError):
    """Raised when the ScanJob exists but is not in 'completed' status."""
    pass


class DedupeLimitExceededError(ValueError):
    """Raised when candidate count or planned quarantine items exceed configured caps."""
    pass


def derive_canonical_top_level_dir(scan_root: str, relative_path: str) -> str:
    """Pure lexical derivation of top-level protected directory."""
    norm_root = normalize_dedupe_path(scan_root)
    # Extract components lexically
    rel_norm = normalize_dedupe_path(relative_path).lstrip("/")
    rel_parts = [p for p in rel_norm.split("/") if p and p != "."]
    if len(rel_parts) > 1:
        return normalize_dedupe_path(f"{norm_root}/{rel_parts[0]}")
    return norm_root


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
    summary: dict[str, Any]


def compute_source_snapshot_digest(
    scan_job_id: int,
    scan_roots: Sequence[str],
    scan_provenance: Mapping[str, Any],
    raw_groups_data: Sequence[Mapping[str, Any]],
    member_safety_facts: Mapping[str, Mapping[str, Any]],
    directory_file_counts: Mapping[str, int] | None,
) -> str:
    """Deterministic fingerprint over RAW database rows and read-only filesystem source facts."""
    payload = {
        "scan_job_id": scan_job_id,
        "scan_roots": list(scan_roots),
        "scan_provenance": dict(sorted(scan_provenance.items())),
        "raw_groups": list(raw_groups_data),
        "member_safety_facts": {k: dict(sorted(v.items())) for k, v in sorted(member_safety_facts.items())},
        "directory_file_counts": dict(sorted(directory_file_counts.items())) if directory_file_counts is not None else None,
    }
    serialized = canonical_json_dumps(payload)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_decision_digest(
    scorer_config_digest: str,
    source_snapshot_digest: str,
    dedupe_result: AdvancedDedupeResult,
) -> str:
    """Deterministic fingerprint over engine decisions and summary statistics."""
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
    serialized = canonical_json_dumps(payload)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compile_advanced_dedupe_preview(
    session: Session,
    scan_job_id: int,
    config: AdvancedDedupeConfig | Mapping[str, Any],
    *,
    allowed_roots: Sequence[str | Path],
    quarantine_root: str | Path | None = None,
    protect_last_file: bool = True,
) -> DedupePreviewCompilation:
    """Compile read-only preview of advanced dedupe decisions against a completed scan."""
    # 1. Config canonicalization & digest
    config = validate_and_canonicalize_config(config)
    config_digest = compute_config_digest(config)

    # 2. ScanJob authority validation
    scan = session.get(ScanJob, scan_job_id)
    if scan is None:
        raise DedupeScanNotFoundError(f"DEDUPE_SCAN_NOT_FOUND: scan job #{scan_job_id} not found")
    if scan.status != "completed":
        raise DedupeScanNotCompletedError(
            f"DEDUPE_SCAN_NOT_COMPLETED: scan job #{scan_job_id} has status '{scan.status}'"
        )

    try:
        raw_roots = json.loads(scan.roots_json)
    except Exception as exc:
        raise ValueError(f"Invalid scan roots_json: {exc}") from exc

    if not isinstance(raw_roots, list) or len(raw_roots) == 0 or not all(isinstance(r, str) for r in raw_roots):
        raise ValueError("Invalid scan roots_json: must be non-empty list of strings")

    scan_roots = tuple(normalize_dedupe_path(r) for r in raw_roots)

    # 3. Candidate Cap check (MAX_DEDUPE_CANDIDATES = 50,000)
    total_candidates = session.scalar(
        select(func.count(DuplicateFile.id))
        .join(DuplicateGroup)
        .where(DuplicateGroup.scan_job_id == scan_job_id)
    ) or 0

    if total_candidates > MAX_DEDUPE_CANDIDATES:
        raise DedupeLimitExceededError(
            f"DEDUPE_LIMIT_EXCEEDED: candidate count {total_candidates} exceeds maximum {MAX_DEDUPE_CANDIDATES}"
        )

    # 4. Read DB duplicate groups & files
    db_groups = list(session.scalars(
        select(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_job_id)
    ))

    # Sort groups deterministically for processing
    db_groups.sort(key=lambda g: (-g.file_size, g.content_hash, g.id))

    group_files: dict[int, list[DuplicateFile]] = {}
    seen_member_paths: dict[str, list[int]] = {}

    for db_g in db_groups:
        files = list(session.scalars(
            select(DuplicateFile).where(DuplicateFile.group_id == db_g.id)
        ))
        files.sort(key=lambda f: (f.root_id, normalize_dedupe_path(f.absolute_path), f.id))
        group_files[db_g.id] = files
        for f in files:
            norm_p = normalize_dedupe_path(f.absolute_path)
            seen_member_paths.setdefault(norm_p, []).append(db_g.id)

    # Check cross-group duplicate member paths (inconsistent snapshot)
    inconsistent_group_ids = set()
    for norm_p, gids in seen_member_paths.items():
        if len(gids) > 1:
            inconsistent_group_ids.update(gids)

    group_snapshots: list[DedupeGroupSnapshot] = []
    pre_skipped_reasons: dict[int | str, str] = {}
    member_safety_facts: dict[str, dict[str, Any]] = {}
    distinct_top_dirs: set[str] = set()

    for db_g in db_groups:
        db_files = group_files[db_g.id]

        group_skip_reason: str | None = None
        if db_g.id in inconsistent_group_ids:
            group_skip_reason = "SOURCE_SNAPSHOT_INCONSISTENT"

        members: list[DedupeMemberSnapshot] = []
        candidate_group_top_dirs: set[str] = set()

        for f in db_files:
            abs_p = Path(f.absolute_path)
            norm_abs = normalize_dedupe_path(f.absolute_path)

            member_fail_reason: str | None = None
            if db_g.id in inconsistent_group_ids:
                member_fail_reason = "SOURCE_SNAPSHOT_INCONSISTENT"

            # Step 1: Root index bounds
            if member_fail_reason is None and (f.root_id < 0 or f.root_id >= len(scan_roots)):
                member_fail_reason = "INVALID_SCAN_ROOT_INDEX"

            norm_root = scan_roots[f.root_id] if 0 <= f.root_id < len(scan_roots) else ""

            # Step 2: Authoritative scan root & lexical absolute/relative provenance
            if member_fail_reason is None:
                if not norm_abs.startswith("/"):
                    member_fail_reason = "INVALID_ABSOLUTE_PATH"
                elif not norm_root.startswith("/"):
                    member_fail_reason = "INVALID_ABSOLUTE_PATH"
                elif not _is_lexical_contained(norm_abs, norm_root):
                    member_fail_reason = "PATH_OUTSIDE_SCAN_ROOT"
                else:
                    expected_rel = _lexical_relpath(norm_abs, norm_root)
                    actual_rel = normalize_dedupe_path(f.relative_path) if f.relative_path.startswith("/") else os.path.normpath(f.relative_path)
                    if actual_rel != expected_rel:
                        member_fail_reason = "RELATIVE_PATH_MISMATCH"

            # Step 3: Canonical top-level protected dir & DB consistency
            canonical_top: str | None = None
            if member_fail_reason is None:
                actual_rel = normalize_dedupe_path(f.relative_path) if f.relative_path.startswith("/") else os.path.normpath(f.relative_path)
                canonical_top = derive_canonical_top_level_dir(norm_root, actual_rel)
                norm_db_top = normalize_dedupe_path(f.top_level_dir) if f.top_level_dir else ""
                if norm_db_top != canonical_top:
                    member_fail_reason = "TOP_LEVEL_DIR_MISMATCH"

            # Step 4: Allowed roots & quarantine boundary
            is_allowed = False
            is_reserved_quarantine = False
            if member_fail_reason is None:
                is_allowed = is_path_allowed(abs_p, allowed_roots)
                if not is_allowed:
                    member_fail_reason = "PATH_OUTSIDE_ALLOWED_ROOT"
                elif quarantine_root and is_reserved_quarantine_path(abs_p, quarantine_root):
                    is_reserved_quarantine = True
                    member_fail_reason = "RESERVED_QUARANTINE_PATH"

            # Step 5: Read-only FS checks (symlink, exists, regular)
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

            # Record per-member safety facts
            safety_reasons = (member_fail_reason,) if member_fail_reason else ()
            member_safety_facts[norm_abs] = {
                "exists": exists,
                "is_file": is_file,
                "is_symlink": is_symlink,
                "is_allowed": is_allowed,
                "is_reserved_quarantine": is_reserved_quarantine,
                "safety_reasons": list(safety_reasons),
            }

            if member_fail_reason is not None and group_skip_reason is None:
                if member_fail_reason in ("SOURCE_NOT_FOUND", "NOT_REGULAR_FILE"):
                    group_skip_reason = "SOURCE_SNAPSHOT_STALE"
                elif member_fail_reason in ("SYMLINK", "RESERVED_QUARANTINE_PATH"):
                    group_skip_reason = "FILESYSTEM_SAFETY_CHECK_FAILED"
                else:
                    group_skip_reason = member_fail_reason

            if canonical_top:
                candidate_group_top_dirs.add(canonical_top)

            members.append(
                DedupeMemberSnapshot(
                    absolute_path=norm_abs,
                    relative_path=f.relative_path,
                    scan_root_index=f.root_id if 0 <= f.root_id < len(scan_roots) else 0,
                    scan_root_path=norm_root,
                    mtime_ns=f.mtime_ns,
                    size=f.size,
                    eligible_as_keep=(member_fail_reason is None),
                    safety_reasons=safety_reasons,
                    top_level_dir=canonical_top,
                )
            )

        if group_skip_reason is not None:
            pre_skipped_reasons[db_g.id] = group_skip_reason
        else:
            # ONLY groups that passed structural/path/basic FS safety contribute to distinct_top_dirs!
            distinct_top_dirs.update(candidate_group_top_dirs)

        group_snapshots.append(
            DedupeGroupSnapshot(
                provenance_id=db_g.id,
                content_hash=db_g.content_hash,
                file_size=db_g.file_size,
                members=tuple(members),
            )
        )

    # 5. Read-only PROTECT_LAST_FILE directory file counts
    # ONLY executed on verified canonical top dirs from safe groups
    directory_file_counts: dict[str, int] | None = None
    if protect_last_file:
        directory_file_counts = {}
        for d_dir in distinct_top_dirs:
            cnt = 0
            p = Path(d_dir)
            if p.is_dir():
                for item in p.rglob("*"):
                    try:
                        if item.is_file() and not (item.is_symlink() or os.path.islink(item)):
                            cnt += 1
                    except OSError:
                        pass
            directory_file_counts[d_dir] = cnt

    # 6. Execute D1 Pure Decision Engine
    engine_result = run_advanced_dedupe(
        group_snapshots,
        config,
        scan_roots=scan_roots,
        protect_last_file_counts=directory_file_counts,
        pre_skipped_reasons=pre_skipped_reasons,
    )

    # 7. Check planned quarantine cap (<= 100,000)
    if engine_result.planned_quarantine_count > MAX_PLANNED_QUARANTINE:
        raise DedupeLimitExceededError(
            f"DEDUPE_LIMIT_EXCEEDED: planned quarantine count {engine_result.planned_quarantine_count} exceeds maximum {MAX_PLANNED_QUARANTINE}"
        )

    # 8. Build RAW DB snapshot and digests
    raw_groups_data = []
    for db_g in sorted(db_groups, key=lambda g: (-g.file_size, g.content_hash, g.id)):
        files_for_g = group_files[db_g.id]
        sorted_files = sorted(files_for_g, key=lambda f: (f.root_id, normalize_dedupe_path(f.absolute_path), f.id))
        raw_groups_data.append({
            "provenance_id": db_g.id,
            "content_hash": db_g.content_hash,
            "file_size": db_g.file_size,
            "member_count": db_g.member_count,
            "files": [
                {
                    "group_id": f.group_id,
                    "raw_root_id": f.root_id,  # Bind raw DB root_id without clamping
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
    )

    decision_digest = compute_decision_digest(
        scorer_config_digest=config_digest,
        source_snapshot_digest=source_snapshot_digest,
        dedupe_result=engine_result,
    )

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
        summary=engine_result.summary,
    )
