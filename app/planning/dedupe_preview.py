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
    groups_snapshot: Sequence[DedupeGroupSnapshot],
    member_safety_facts: Mapping[str, Mapping[str, Any]],
    directory_file_counts: Mapping[str, int] | None,
) -> str:
    """Deterministic fingerprint over database and read-only filesystem source state."""
    # Deterministic sorting of groups
    sorted_groups = sorted(
        groups_snapshot,
        key=lambda g: (-g.file_size, g.content_hash, _stable_group_path_fingerprint(g)),
    )

    payload = {
        "scan_job_id": scan_job_id,
        "scan_roots": list(scan_roots),
        "scan_provenance": dict(sorted(scan_provenance.items())),
        "groups": [
            {
                "provenance_id": g.provenance_id,
                "content_hash": g.content_hash,
                "file_size": g.file_size,
                "members": [
                    {
                        "absolute_path": m.absolute_path,
                        "relative_path": m.relative_path,
                        "scan_root_index": m.scan_root_index,
                        "size": m.size,
                        "mtime_ns": m.mtime_ns,
                        "top_level_dir": m.top_level_dir,
                        "safety_facts": dict(sorted(member_safety_facts.get(m.absolute_path, {}).items())),
                    }
                    for m in sorted(g.members, key=lambda x: normalize_dedupe_path(x.absolute_path))
                ],
            }
            for g in sorted_groups
        ],
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

    # Sort groups deterministically by content_hash, file_size, id
    db_groups.sort(key=lambda g: (-g.file_size, g.content_hash, g.id))

    group_snapshots: list[DedupeGroupSnapshot] = []
    pre_skipped_reasons: dict[int | str, str] = {}
    member_safety_facts: dict[str, dict[str, Any]] = {}
    distinct_top_dirs: set[str] = set()

    for db_g in db_groups:
        db_files = list(session.scalars(
            select(DuplicateFile).where(DuplicateFile.group_id == db_g.id)
        ))
        # Sort files deterministically
        db_files.sort(key=lambda f: (f.root_id, normalize_dedupe_path(f.absolute_path)))

        group_skip_reason: str | None = None
        members: list[DedupeMemberSnapshot] = []

        for f in db_files:
            abs_p = Path(f.absolute_path)
            norm_abs = normalize_dedupe_path(f.absolute_path)

            # Facts collection
            exists = False
            is_file = False
            is_symlink = False
            is_allowed = False

            try:
                is_symlink = abs_p.is_symlink() or os.path.islink(abs_p)
                exists = abs_p.exists()
                is_file = abs_p.is_file() and not is_symlink
                is_allowed = is_path_allowed(abs_p, allowed_roots)
            except OSError:
                pass

            member_safety_facts[norm_abs] = {
                "exists": exists,
                "is_file": is_file,
                "is_symlink": is_symlink,
                "is_allowed": is_allowed,
            }

            # Safety Rule 1: Valid scan root index
            if f.root_id < 0 or f.root_id >= len(scan_roots):
                if group_skip_reason is None:
                    group_skip_reason = "INVALID_SCAN_ROOT_INDEX"

            # Safety Rule 2: Allowed roots boundary
            elif not is_allowed:
                if group_skip_reason is None:
                    group_skip_reason = "PATH_OUTSIDE_ALLOWED_ROOT"

            # Safety Rule 3: Quarantine storage boundary
            elif quarantine_root and is_reserved_quarantine_path(abs_p, quarantine_root):
                if group_skip_reason is None:
                    group_skip_reason = "FILESYSTEM_SAFETY_CHECK_FAILED"

            # Safety Rule 4: Not a symlink
            elif is_symlink:
                if group_skip_reason is None:
                    group_skip_reason = "FILESYSTEM_SAFETY_CHECK_FAILED"

            # Safety Rule 5: Existing regular file
            elif not exists or not is_file:
                if group_skip_reason is None:
                    group_skip_reason = "SOURCE_SNAPSHOT_STALE"

            root_p = scan_roots[f.root_id] if 0 <= f.root_id < len(scan_roots) else ""
            top_dir = f.top_level_dir
            if not top_dir and root_p:
                rel_parts = Path(f.relative_path).parts
                top_dir = str(Path(root_p) / rel_parts[0] if len(rel_parts) > 1 else Path(root_p))

            if top_dir:
                distinct_top_dirs.add(top_dir)

            members.append(
                DedupeMemberSnapshot(
                    absolute_path=norm_abs,
                    relative_path=f.relative_path,
                    scan_root_index=f.root_id if 0 <= f.root_id < len(scan_roots) else 0,
                    scan_root_path=root_p,
                    mtime_ns=f.mtime_ns,
                    size=f.size,
                    top_level_dir=top_dir,
                )
            )

        if group_skip_reason is not None:
            pre_skipped_reasons[db_g.id] = group_skip_reason

        group_snapshots.append(
            DedupeGroupSnapshot(
                provenance_id=db_g.id,
                content_hash=db_g.content_hash,
                file_size=db_g.file_size,
                members=tuple(members),
            )
        )

    # 5. Read-only PROTECT_LAST_FILE directory file counts
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

    # 8. Compute Source Snapshot Digest & Decision Digest
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
        groups_snapshot=group_snapshots,
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
