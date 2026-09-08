import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
import stat
from typing import Any, Literal, Mapping, Sequence

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models import IndexRoot, IndexedPath, FilterPolicy
from app.batch_utilities.schema import QuarantineFilteredAction
from app.batch_utilities.errors import (
    BatchUtilityScopeNotFoundError,
    BatchUtilityInvalidConfigError,
    BatchUtilityLimitExceededError,
)
from app.batch_utilities.digest import (
    canonical_json_dumps,
    canonicalize_quarantine_filtered_action,
    compute_action_config_digest,
    compute_preview_digest,
)
from app.filters.validation import validate_filter_ast
from app.filters.compiler import compile_filter_to_sql
from app.filters.excludes import DEFAULT_EXCLUDE_DIR_NAMES, build_exclude_predicates


MAX_CANDIDATES_LIMIT = 50000


@dataclass(frozen=True)
class BatchUtilitySafetySnapshot:
    protect_last_file: bool
    allowed_roots: tuple[Path, ...]
    quarantine_root: Path | None
    effective_policy: dict[str, Any]


@dataclass(frozen=True)
class BatchUtilityDraftIntent:
    sequence: int
    operation: Literal["quarantine"]
    source_path: str
    target_path: None
    keep_path: None
    expected_size: int
    expected_device: int
    expected_inode: int
    expected_mtime_ns: int
    expected_hash: None
    metadata_json: str


@dataclass(frozen=True)
class BatchUtilityCompilation:
    canonical_action: dict[str, Any]
    action_config_digest: str
    source_snapshot_digest: str
    db_lineage_digest: str
    rows: tuple[dict[str, Any], ...]
    intents: tuple[BatchUtilityDraftIntent, ...]
    matched_count: int
    matched_bytes: int
    candidate_count: int
    candidate_bytes: int
    planned_operations_count: int
    skipped_count: int
    safety_excluded_count: int
    blocking_conflict_count: int
    expected_reclaim_bytes: int
    summary: dict[str, Any]


def _count_regular_files_in_dir(dir_path: Path) -> int:
    """
    Recursively count regular, non-symlink files under dir_path,
    identical to executor._count_regular_files semantics.
    """
    if not dir_path.exists() or not dir_path.is_dir():
        return 0
    count = 0
    for current, dirnames, filenames in os.walk(dir_path, followlinks=False):
        current_path = Path(current)
        dirnames[:] = [d for d in dirnames if not (current_path / d).is_symlink()]
        for name in filenames:
            p = current_path / name
            if not p.is_symlink() and p.is_file():
                count += 1
    return count


def _parse_and_validate_filter(filter_obj: Any) -> Any:
    if filter_obj is None:
        return None
    if isinstance(filter_obj, dict):
        from app.filters.schema import FilterExpression
        parsed = FilterExpression.model_validate({"node": filter_obj}).node
    else:
        parsed = filter_obj
    return validate_filter_ast(parsed)


def _build_filter_where_clause(
    session: Session,
    root_keys: list[str],
    filter_ast: Any | None,
    quarantine_root: Path | None,
) -> Any:
    where_clauses = [IndexedPath.root_key.in_(root_keys)]

    if filter_ast is not None:
        validated_ast = _parse_and_validate_filter(filter_ast)
        where_clauses.append(compile_filter_to_sql(validated_ast))

    policy = session.get(FilterPolicy, 1)
    excludes = list(DEFAULT_EXCLUDE_DIR_NAMES)
    if policy and policy.exclude_dir_names_json:
        try:
            excludes = json.loads(policy.exclude_dir_names_json)
        except Exception:
            excludes = list(DEFAULT_EXCLUDE_DIR_NAMES)

    where_clauses.append(
        build_exclude_predicates(
            excludes,
            quarantine_root=str(quarantine_root) if quarantine_root else None,
        )
    )

    return and_(*where_clauses)


def compute_current_quarantine_filtered_db_lineage_digest(
    session: Session,
    canonical_action: Mapping[str, Any],
) -> str | None:
    root_ids = canonical_action.get("root_ids", [])
    if not root_ids:
        return None

    roots = session.execute(
        select(IndexRoot).where(IndexRoot.id.in_(root_ids)).order_by(IndexRoot.id.asc())
    ).scalars().all()

    if len(roots) != len(root_ids):
        return None

    root_keys = [r.root for r in roots]
    filter_dict = canonical_action.get("filter")
    filter_ast = None
    if filter_dict:
        filter_ast = _parse_and_validate_filter(filter_dict)

    where_condition = _build_filter_where_clause(
        session=session,
        root_keys=root_keys,
        filter_ast=filter_ast,
        quarantine_root=None,
    )

    query = (
        select(
            IndexedPath.id,
            IndexedPath.root_key,
            IndexedPath.absolute_path,
            IndexedPath.relative_path,
            IndexedPath.basename,
            IndexedPath.suffix,
            IndexedPath.size,
            IndexedPath.mtime_ns,
            IndexedPath.device,
            IndexedPath.inode,
            IndexedPath.is_dir,
            IndexedPath.scan_generation,
        )
        .where(where_condition)
        .order_by(IndexedPath.absolute_path.asc(), IndexedPath.id.asc())
    )

    rows = session.execute(query).all()
    lineage_payload = {
        "roots": [{"id": r.id, "root": r.root} for r in roots],
        "indexed_paths": [
            {
                "id": r.id,
                "root_key": r.root_key,
                "absolute_path": r.absolute_path,
                "relative_path": r.relative_path,
                "basename": r.basename,
                "suffix": r.suffix,
                "size": r.size,
                "mtime_ns": r.mtime_ns,
                "device": r.device,
                "inode": r.inode,
                "is_dir": r.is_dir,
                "scan_generation": r.scan_generation,
            }
            for r in rows
        ],
    }

    return hashlib.sha256(canonical_json_dumps(lineage_payload).encode("utf-8")).hexdigest()


def compile_quarantine_filtered_preview(
    *,
    session: Session,
    action: QuarantineFilteredAction,
    safety_snapshot: BatchUtilitySafetySnapshot,
) -> BatchUtilityCompilation:
    canonical_action = canonicalize_quarantine_filtered_action(action)
    action_config_digest = compute_action_config_digest(canonical_action)

    # 1. Resolve every root_id to IndexRoot
    roots_by_id: dict[int, IndexRoot] = {}
    for root_id in canonical_action["root_ids"]:
        root_obj = session.get(IndexRoot, root_id)
        if root_obj is None:
            raise BatchUtilityScopeNotFoundError(
                f"IndexRoot #{root_id} not found",
                details={"root_id": root_id},
            )
        roots_by_id[root_id] = root_obj

    # 2. Validate root paths within allowed_roots and outside quarantine_root
    for root_id, root_obj in roots_by_id.items():
        root_p = Path(root_obj.root).resolve()
        is_allowed = any(root_p == ar or root_p.is_relative_to(ar) for ar in safety_snapshot.allowed_roots)
        if not is_allowed:
            raise BatchUtilityInvalidConfigError(
                f"IndexRoot #{root_id} ({root_obj.root}) is outside allowed roots",
                details={"root_id": root_id, "root": root_obj.root},
            )
        if safety_snapshot.quarantine_root:
            qr = safety_snapshot.quarantine_root.resolve()
            if root_p == qr or root_p.is_relative_to(qr):
                raise BatchUtilityInvalidConfigError(
                    f"IndexRoot #{root_id} ({root_obj.root}) is within quarantine storage",
                    details={"root_id": root_id, "root": root_obj.root},
                )

    root_map = {r.root: r for r in roots_by_id.values()}
    root_keys = list(root_map.keys())

    # 3. Query candidate IndexedPaths
    where_condition = _build_filter_where_clause(
        session=session,
        root_keys=root_keys,
        filter_ast=action.filter,
        quarantine_root=safety_snapshot.quarantine_root,
    )

    # Cap check
    count_query = select(func.count(IndexedPath.id)).where(where_condition)
    total_candidates = session.scalar(count_query) or 0
    if total_candidates > MAX_CANDIDATES_LIMIT:
        raise BatchUtilityLimitExceededError(
            f"Matching candidates count ({total_candidates}) exceeds maximum limit of {MAX_CANDIDATES_LIMIT}",
            details={"count": total_candidates, "limit": MAX_CANDIDATES_LIMIT},
        )

    # Fetch ordered candidates
    candidates_query = (
        select(IndexedPath)
        .where(where_condition)
        .order_by(IndexedPath.absolute_path.asc(), IndexedPath.id.asc())
    )
    candidates = session.execute(candidates_query).scalars().all()

    # DB lineage digest
    db_lineage_digest = compute_current_quarantine_filtered_db_lineage_digest(session, canonical_action) or ""

    decision_rows: list[dict[str, Any]] = []
    intents: list[BatchUtilityDraftIntent] = []
    source_facts: list[dict[str, Any]] = []

    cached_parent_counts: dict[Path, int] = {}
    planned_parent_quarantines: dict[Path, int] = {}

    matched_count = len(candidates)
    matched_bytes = sum(c.size for c in candidates if not c.is_dir)
    candidate_count = matched_count
    candidate_bytes = matched_bytes

    sequence = 1

    for cand in candidates:
        root_obj = root_map.get(cand.root_key)
        index_root_id = root_obj.id if root_obj else 0
        index_root_path = root_obj.root if root_obj else cand.root_key
        abs_p = Path(cand.absolute_path)

        # Default fact record for source_snapshot_digest
        cand_fact = {
            "id": cand.id,
            "path": cand.absolute_path,
            "indexed_is_dir": cand.is_dir,
            "indexed_size": cand.size,
            "indexed_mtime_ns": cand.mtime_ns,
            "indexed_device": cand.device,
            "indexed_inode": cand.inode,
        }

        # Case 1: Indexed Directory -> SKIPPED / NOT_REGULAR_FILE
        if cand.is_dir:
            cand_fact["status"] = "indexed_directory"
            source_facts.append(cand_fact)
            decision_rows.append({
                "source_path": cand.absolute_path,
                "target_path": None,
                "index_root_id": index_root_id,
                "index_root_path": index_root_path,
                "relative_path": cand.relative_path,
                "object_type": "directory",
                "decision": "SKIPPED",
                "reason_code": "NOT_REGULAR_FILE",
                "reason": "Indexed object is a directory",
                "size": 0,
                "protected_dir": None,
            })
            continue

        # Case 2: Read-only live observation via os.lstat
        try:
            st = os.lstat(cand.absolute_path)
        except FileNotFoundError:
            cand_fact["status"] = "missing"
            source_facts.append(cand_fact)
            decision_rows.append({
                "source_path": cand.absolute_path,
                "target_path": None,
                "index_root_id": index_root_id,
                "index_root_path": index_root_path,
                "relative_path": cand.relative_path,
                "object_type": "missing",
                "decision": "SKIPPED",
                "reason_code": "SOURCE_MISSING",
                "reason": "Source file does not exist on disk",
                "size": cand.size,
                "protected_dir": None,
            })
            continue
        except Exception as e:
            cand_fact["status"] = f"lstat_error_{e}"
            source_facts.append(cand_fact)
            decision_rows.append({
                "source_path": cand.absolute_path,
                "target_path": None,
                "index_root_id": index_root_id,
                "index_root_path": index_root_path,
                "relative_path": cand.relative_path,
                "object_type": "missing",
                "decision": "SKIPPED",
                "reason_code": "SOURCE_MISSING",
                "reason": str(e),
                "size": cand.size,
                "protected_dir": None,
            })
            continue

        cand_fact["live_stat"] = {
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "device": st.st_dev,
            "inode": st.st_ino,
            "mode": st.st_mode,
        }

        # Case 3: Live object is a symlink -> SAFETY_EXCLUDED / SYMLINK_BLOCKED
        if stat.S_ISLNK(st.st_mode):
            cand_fact["status"] = "symlink"
            source_facts.append(cand_fact)
            decision_rows.append({
                "source_path": cand.absolute_path,
                "target_path": None,
                "index_root_id": index_root_id,
                "index_root_path": index_root_path,
                "relative_path": cand.relative_path,
                "object_type": "symlink",
                "decision": "SAFETY_EXCLUDED",
                "reason_code": "SYMLINK_BLOCKED",
                "reason": "Source path is a symlink",
                "size": st.st_size,
                "protected_dir": None,
            })
            continue

        # Case 4: Live path outside allowed roots
        is_path_allowed = any(abs_p == ar or abs_p.is_relative_to(ar) for ar in safety_snapshot.allowed_roots)
        if not is_path_allowed:
            cand_fact["status"] = "outside_allowed"
            source_facts.append(cand_fact)
            decision_rows.append({
                "source_path": cand.absolute_path,
                "target_path": None,
                "index_root_id": index_root_id,
                "index_root_path": index_root_path,
                "relative_path": cand.relative_path,
                "object_type": "file",
                "decision": "SAFETY_EXCLUDED",
                "reason_code": "PATH_OUTSIDE_ALLOWED_ROOT",
                "reason": "Path is outside allowed roots",
                "size": st.st_size,
                "protected_dir": None,
            })
            continue

        # Case 5: Live path in quarantine reserved
        if safety_snapshot.quarantine_root:
            qr = safety_snapshot.quarantine_root.resolve()
            if abs_p == qr or abs_p.is_relative_to(qr):
                cand_fact["status"] = "reserved_quarantine"
                source_facts.append(cand_fact)
                decision_rows.append({
                    "source_path": cand.absolute_path,
                    "target_path": None,
                    "index_root_id": index_root_id,
                    "index_root_path": index_root_path,
                    "relative_path": cand.relative_path,
                    "object_type": "file",
                    "decision": "SAFETY_EXCLUDED",
                    "reason_code": "RESERVED_QUARANTINE_PATH",
                    "reason": "Path is within reserved quarantine storage",
                    "size": st.st_size,
                    "protected_dir": None,
                })
                continue

        # Case 6: Live object is not a regular file
        if not stat.S_ISREG(st.st_mode):
            cand_fact["status"] = "unsupported_object"
            source_facts.append(cand_fact)
            decision_rows.append({
                "source_path": cand.absolute_path,
                "target_path": None,
                "index_root_id": index_root_id,
                "index_root_path": index_root_path,
                "relative_path": cand.relative_path,
                "object_type": "unsupported",
                "decision": "SKIPPED",
                "reason_code": "NOT_REGULAR_FILE",
                "reason": "Live object is not a regular file",
                "size": st.st_size,
                "protected_dir": None,
            })
            continue

        # Case 7: Stat identity differs from index -> SKIPPED / SOURCE_SNAPSHOT_STALE
        if (
            st.st_size != cand.size
            or st.st_mtime_ns != cand.mtime_ns
            or st.st_dev != cand.device
            or st.st_ino != cand.inode
        ):
            cand_fact["status"] = "stat_mismatch"
            source_facts.append(cand_fact)
            decision_rows.append({
                "source_path": cand.absolute_path,
                "target_path": None,
                "index_root_id": index_root_id,
                "index_root_path": index_root_path,
                "relative_path": cand.relative_path,
                "object_type": "file",
                "decision": "SKIPPED",
                "reason_code": "SOURCE_SNAPSHOT_STALE",
                "reason": "File stat has changed since indexing",
                "size": st.st_size,
                "protected_dir": None,
            })
            continue

        # Candidate is live regular file eligible for quarantine check
        parent_dir = abs_p.parent
        if parent_dir not in cached_parent_counts:
            cached_parent_counts[parent_dir] = _count_regular_files_in_dir(parent_dir)
            planned_parent_quarantines[parent_dir] = 0

        cand_fact["parent_dir"] = str(parent_dir)
        cand_fact["parent_regular_files"] = cached_parent_counts[parent_dir]

        # Case 8: Check aggregate PROTECT_LAST_FILE
        can_quarantine = True
        if safety_snapshot.protect_last_file:
            current_total = cached_parent_counts[parent_dir]
            already_planned = planned_parent_quarantines[parent_dir]
            if current_total - already_planned - 1 < 1:
                can_quarantine = False

        if not can_quarantine:
            cand_fact["status"] = "protected_last_file"
            source_facts.append(cand_fact)
            decision_rows.append({
                "source_path": cand.absolute_path,
                "target_path": None,
                "index_root_id": index_root_id,
                "index_root_path": index_root_path,
                "relative_path": cand.relative_path,
                "object_type": "file",
                "decision": "SAFETY_EXCLUDED",
                "reason_code": "PROTECT_LAST_FILE",
                "reason": "Directory-level last-file protection",
                "size": st.st_size,
                "protected_dir": str(parent_dir) if safety_snapshot.protect_last_file else None,
            })
            continue

        # Actionable quarantine intent
        planned_parent_quarantines[parent_dir] += 1
        cand_fact["status"] = "quarantine_actionable"
        source_facts.append(cand_fact)

        protected_dir_str = str(parent_dir) if safety_snapshot.protect_last_file else None
        item_meta_dict: dict[str, Any] = {
            "utility_action": "quarantine_filtered",
            "index_root_id": index_root_id,
            "index_root_path": index_root_path,
            "relative_path": cand.relative_path,
        }
        if protected_dir_str:
            item_meta_dict["protected_dir"] = protected_dir_str

        intent = BatchUtilityDraftIntent(
            sequence=sequence,
            operation="quarantine",
            source_path=cand.absolute_path,
            target_path=None,
            keep_path=None,
            expected_size=st.st_size,
            expected_device=0,
            expected_inode=0,
            expected_mtime_ns=0,
            expected_hash=None,
            metadata_json=canonical_json_dumps(item_meta_dict),
        )
        intents.append(intent)
        sequence += 1

        decision_rows.append({
            "source_path": cand.absolute_path,
            "target_path": None,
            "index_root_id": index_root_id,
            "index_root_path": index_root_path,
            "relative_path": cand.relative_path,
            "object_type": "file",
            "decision": "QUARANTINE",
            "reason_code": None,
            "reason": None,
            "size": st.st_size,
            "protected_dir": protected_dir_str,
        })

    # Summary
    planned_operations_count = len(intents)
    skipped_count = sum(1 for r in decision_rows if r["decision"] == "SKIPPED")
    safety_excluded_count = sum(1 for r in decision_rows if r["decision"] == "SAFETY_EXCLUDED")
    blocking_conflict_count = 0
    expected_reclaim_bytes = sum(intent.expected_size for intent in intents)

    # Source snapshot digest
    source_snapshot_payload = {
        "roots": [{"id": r.id, "root": r.root} for r in roots_by_id.values()],
        "source_facts": source_facts,
        "parent_counts": {str(k): v for k, v in cached_parent_counts.items()},
    }
    source_snapshot_digest = hashlib.sha256(
        canonical_json_dumps(source_snapshot_payload).encode("utf-8")
    ).hexdigest()

    summary = {
        "matched_count": matched_count,
        "matched_bytes": matched_bytes,
        "candidate_count": candidate_count,
        "candidate_bytes": candidate_bytes,
        "planned_operations_count": planned_operations_count,
        "skipped_count": skipped_count,
        "safety_excluded_count": safety_excluded_count,
        "blocking_conflict_count": blocking_conflict_count,
        "expected_reclaim_bytes": expected_reclaim_bytes,
    }

    return BatchUtilityCompilation(
        canonical_action=canonical_action,
        action_config_digest=action_config_digest,
        source_snapshot_digest=source_snapshot_digest,
        db_lineage_digest=db_lineage_digest,
        rows=tuple(decision_rows),
        intents=tuple(intents),
        matched_count=matched_count,
        matched_bytes=matched_bytes,
        candidate_count=candidate_count,
        candidate_bytes=candidate_bytes,
        planned_operations_count=planned_operations_count,
        skipped_count=skipped_count,
        safety_excluded_count=safety_excluded_count,
        blocking_conflict_count=blocking_conflict_count,
        expected_reclaim_bytes=expected_reclaim_bytes,
        summary=summary,
    )
