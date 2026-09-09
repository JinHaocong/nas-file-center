import errno
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
from app.batch_utilities.schema import QuarantineFilteredAction, SuffixTransformAction
from app.batch_utilities.errors import (
    BatchUtilityScopeNotFoundError,
    BatchUtilityInvalidConfigError,
    BatchUtilityLimitExceededError,
)
from app.batch_utilities.digest import (
    canonical_json_dumps,
    canonicalize_quarantine_filtered_action,
    canonicalize_suffix_transform_action,
    compute_action_config_digest,
    compute_preview_digest,
)
from app.batch_utilities.transform import compute_transformed_basename, TransformDecision
from app.batch_utilities.graph import TargetItemCandidate, resolve_suffix_transform_graph
from app.filters.validation import validate_filter_ast
from app.filters.compiler import compile_filter_to_sql
from app.filters.excludes import DEFAULT_EXCLUDE_DIR_NAMES, build_exclude_predicates
from app.path_safety import is_path_allowed, is_reserved_quarantine_path


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
    operation: Literal["quarantine", "rename"]
    source_path: str
    target_path: str | None
    keep_path: str | None
    expected_size: int
    expected_device: int
    expected_inode: int
    expected_mtime_ns: int
    expected_hash: str | None
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
    compiled_where_clause: Any = None
    filter_policy_snapshot: str | None = None


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


def _resolve_existing_candidate_for_safety(path: Path) -> Path:
    return path.expanduser().resolve(strict=True)


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
    *,
    compiled_where_clause: Any | None = None,
    filter_policy_snapshot: str | None = None,
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

    # Check FilterPolicy concurrency if snapshot was provided
    if filter_policy_snapshot is not None:
        policy = session.get(FilterPolicy, 1)
        current_policy_json = policy.exclude_dir_names_json if policy else None
        if current_policy_json != filter_policy_snapshot:
            return "FILTER_POLICY_CHANGED"

    if compiled_where_clause is not None:
        where_condition = compiled_where_clause
    else:
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
        if not is_path_allowed(root_obj.root, safety_snapshot.allowed_roots):
            raise BatchUtilityInvalidConfigError(
                f"IndexRoot #{root_id} ({root_obj.root}) is outside allowed roots",
                details={"root_id": root_id, "root": root_obj.root},
            )
        if is_reserved_quarantine_path(root_obj.root, safety_snapshot.quarantine_root):
            raise BatchUtilityInvalidConfigError(
                f"IndexRoot #{root_id} ({root_obj.root}) is within quarantine storage",
                details={"root_id": root_id, "root": root_obj.root},
            )

    root_map = {r.root: r for r in roots_by_id.values()}
    root_keys = list(root_map.keys())

    # 3. Query candidate IndexedPaths - Phase A authoritative compile
    filter_dict = canonical_action.get("filter")
    filter_ast = None
    if filter_dict:
        filter_ast = _parse_and_validate_filter(filter_dict)
    compiled_filter_sql = compile_filter_to_sql(filter_ast) if filter_ast is not None else None

    policy = session.get(FilterPolicy, 1)
    filter_policy_snapshot = policy.exclude_dir_names_json if policy else None
    excludes = list(DEFAULT_EXCLUDE_DIR_NAMES)
    if policy and policy.exclude_dir_names_json:
        try:
            excludes = json.loads(policy.exclude_dir_names_json)
        except Exception:
            excludes = list(DEFAULT_EXCLUDE_DIR_NAMES)

    lineage_where_clauses = [IndexedPath.root_key.in_(root_keys)]
    if compiled_filter_sql is not None:
        lineage_where_clauses.append(compiled_filter_sql)
    lineage_where_clauses.append(
        build_exclude_predicates(
            excludes,
            quarantine_root=None,
        )
    )
    compiled_lineage_where = and_(*lineage_where_clauses)

    candidates_where_clauses = [IndexedPath.root_key.in_(root_keys)]
    if compiled_filter_sql is not None:
        candidates_where_clauses.append(compiled_filter_sql)
    candidates_where_clauses.append(
        build_exclude_predicates(
            excludes,
            quarantine_root=str(safety_snapshot.quarantine_root) if safety_snapshot.quarantine_root else None,
        )
    )
    where_condition = and_(*candidates_where_clauses)

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

    # DB lineage digest (Phase A using precompiled where condition)
    db_lineage_digest = compute_current_quarantine_filtered_db_lineage_digest(
        session,
        canonical_action,
        compiled_where_clause=compiled_lineage_where,
        filter_policy_snapshot=filter_policy_snapshot,
    ) or ""

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

        # Case 2: Strict existing-path resolution & boundary safety check
        try:
            resolved_candidate = _resolve_existing_candidate_for_safety(abs_p)
        except FileNotFoundError:
            # Source path does not resolve to an existing target.
            # Check if lexical source path itself is an existing symlink (e.g. broken symlink)
            try:
                lex_st = os.lstat(cand.absolute_path)
                if stat.S_ISLNK(lex_st.st_mode):
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
                        "size": lex_st.st_size,
                        "protected_dir": None,
                    })
                    continue
            except Exception:
                pass

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
        except (RuntimeError, OSError) as e:
            # Symlink loop (ELOOP), unresolvable parent chain, etc. fail closed
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
                "reason": "Path is outside allowed roots or contains unresolvable symlink chain",
                "size": cand.size,
                "protected_dir": None,
            })
            continue

        # Resolved object exists. Check boundary containment on resolved_candidate
        if is_reserved_quarantine_path(resolved_candidate, safety_snapshot.quarantine_root):
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
                "size": cand.size,
                "protected_dir": None,
            })
            continue

        if not is_path_allowed(resolved_candidate, safety_snapshot.allowed_roots):
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
                "size": cand.size,
                "protected_dir": None,
            })
            continue

        # Case 3: Read-only live observation via os.lstat on lexical source path
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
        except OSError as e:
            if hasattr(errno, "ELOOP") and e.errno == errno.ELOOP:
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
                    "reason": "Path contains symlink loop",
                    "size": cand.size,
                    "protected_dir": None,
                })
                continue
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

        # Case 4: Live object is a symlink -> SAFETY_EXCLUDED / SYMLINK_BLOCKED
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

        # Case 5: Live object is not a regular file
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
        compiled_where_clause=compiled_lineage_where,
        filter_policy_snapshot=filter_policy_snapshot,
    )


def compute_current_suffix_transform_db_lineage_digest(
    session: Session,
    canonical_action: Mapping[str, Any],
    *,
    compiled_where_clause: Any | None = None,
    filter_policy_snapshot: str | None = None,
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

    if filter_policy_snapshot is not None:
        policy = session.get(FilterPolicy, 1)
        current_policy_json = policy.exclude_dir_names_json if policy else None
        if current_policy_json != filter_policy_snapshot:
            return "FILTER_POLICY_CHANGED"

    if compiled_where_clause is not None:
        where_condition = compiled_where_clause
    else:
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


def compile_suffix_transform_preview(
    *,
    session: Session,
    action: SuffixTransformAction,
    safety_snapshot: BatchUtilitySafetySnapshot,
) -> BatchUtilityCompilation:
    canonical_action = canonicalize_suffix_transform_action(action)
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
        if not is_path_allowed(root_obj.root, safety_snapshot.allowed_roots):
            raise BatchUtilityInvalidConfigError(
                f"IndexRoot #{root_id} ({root_obj.root}) is outside allowed roots",
                details={"root_id": root_id, "root": root_obj.root},
            )
        if is_reserved_quarantine_path(root_obj.root, safety_snapshot.quarantine_root):
            raise BatchUtilityInvalidConfigError(
                f"IndexRoot #{root_id} ({root_obj.root}) is within quarantine storage",
                details={"root_id": root_id, "root": root_obj.root},
            )

    root_map = {r.root: r for r in roots_by_id.values()}
    root_keys = list(root_map.keys())

    # 3. Query candidate IndexedPaths
    filter_dict = canonical_action.get("filter")
    filter_ast = None
    if filter_dict:
        filter_ast = _parse_and_validate_filter(filter_dict)
    compiled_filter_sql = compile_filter_to_sql(filter_ast) if filter_ast is not None else None

    policy = session.get(FilterPolicy, 1)
    filter_policy_snapshot = policy.exclude_dir_names_json if policy else None
    excludes = list(DEFAULT_EXCLUDE_DIR_NAMES)
    if policy and policy.exclude_dir_names_json:
        try:
            excludes = json.loads(policy.exclude_dir_names_json)
        except Exception:
            excludes = list(DEFAULT_EXCLUDE_DIR_NAMES)

    lineage_where_clauses = [IndexedPath.root_key.in_(root_keys)]
    if compiled_filter_sql is not None:
        lineage_where_clauses.append(compiled_filter_sql)
    lineage_where_clauses.append(
        build_exclude_predicates(
            excludes,
            quarantine_root=None,
        )
    )
    compiled_lineage_where = and_(*lineage_where_clauses)

    candidates_where_clauses = [IndexedPath.root_key.in_(root_keys)]
    if compiled_filter_sql is not None:
        candidates_where_clauses.append(compiled_filter_sql)
    candidates_where_clauses.append(
        build_exclude_predicates(
            excludes,
            quarantine_root=str(safety_snapshot.quarantine_root) if safety_snapshot.quarantine_root else None,
        )
    )
    where_condition = and_(*candidates_where_clauses)

    count_query = select(func.count(IndexedPath.id)).where(where_condition)
    total_candidates = session.scalar(count_query) or 0
    if total_candidates > MAX_CANDIDATES_LIMIT:
        raise BatchUtilityLimitExceededError(
            f"Matching candidates count ({total_candidates}) exceeds maximum limit of {MAX_CANDIDATES_LIMIT}",
            details={"count": total_candidates, "limit": MAX_CANDIDATES_LIMIT},
        )

    candidates_query = (
        select(IndexedPath)
        .where(where_condition)
        .order_by(IndexedPath.absolute_path.asc(), IndexedPath.id.asc())
    )
    candidates = session.execute(candidates_query).scalars().all()

    db_lineage_digest = compute_current_suffix_transform_db_lineage_digest(
        session,
        canonical_action,
        compiled_where_clause=compiled_lineage_where,
        filter_policy_snapshot=filter_policy_snapshot,
    ) or ""

    decision_rows: list[dict[str, Any]] = []
    source_facts: list[dict[str, Any]] = []
    actionable_candidates: list[TargetItemCandidate] = []

    matched_count = len(candidates)
    matched_bytes = sum(c.size for c in candidates if not c.is_dir)
    candidate_count = matched_count
    candidate_bytes = matched_bytes

    mode = canonical_action["mode"]
    target_suffix = canonical_action["suffix"]

    for cand in candidates:
        root_obj = root_map.get(cand.root_key)
        index_root_id = root_obj.id if root_obj else 0
        index_root_path = root_obj.root if root_obj else cand.root_key
        abs_p = Path(cand.absolute_path)

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

        # Case 2: Strict existing-path resolution & boundary safety check
        try:
            resolved_candidate = _resolve_existing_candidate_for_safety(abs_p)
        except FileNotFoundError:
            try:
                lex_st = os.lstat(cand.absolute_path)
                if stat.S_ISLNK(lex_st.st_mode):
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
                        "size": lex_st.st_size,
                        "protected_dir": None,
                    })
                    continue
            except Exception:
                pass

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
        except (RuntimeError, OSError) as e:
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
                "reason": "Path is outside allowed roots or contains unresolvable symlink chain",
                "size": cand.size,
                "protected_dir": None,
            })
            continue

        if is_reserved_quarantine_path(resolved_candidate, safety_snapshot.quarantine_root):
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
                "size": cand.size,
                "protected_dir": None,
            })
            continue

        if not is_path_allowed(resolved_candidate, safety_snapshot.allowed_roots):
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
                "size": cand.size,
                "protected_dir": None,
            })
            continue

        # Case 3: Read-only live observation via os.lstat
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
        except OSError as e:
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

        # Case 4: Symlink
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

        # Case 5: Not regular file
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

        # Case 6: Stat mismatch
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

        # Candidate is live regular file. Compute suffix transformation
        trans_res = compute_transformed_basename(cand.basename, mode=mode, target_suffix=target_suffix)
        if trans_res.decision == TransformDecision.SKIPPED:
            cand_fact["status"] = f"skipped_{trans_res.reason_code}"
            source_facts.append(cand_fact)
            decision_rows.append({
                "source_path": cand.absolute_path,
                "target_path": None,
                "index_root_id": index_root_id,
                "index_root_path": index_root_path,
                "relative_path": cand.relative_path,
                "object_type": "file",
                "decision": "SKIPPED",
                "reason_code": trans_res.reason_code,
                "reason": trans_res.reason,
                "size": st.st_size,
                "protected_dir": None,
            })
            continue

        # Actionable target candidate
        target_path = str(abs_p.parent / trans_res.target_basename)
        cand_fact["status"] = "actionable"
        cand_fact["planned_target"] = target_path
        source_facts.append(cand_fact)

        actionable_candidates.append(
            TargetItemCandidate(
                source_path=cand.absolute_path,
                target_path=target_path,
                index_root_id=index_root_id,
                index_root_path=index_root_path,
                relative_path=cand.relative_path,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                device=st.st_dev,
                inode=st.st_ino,
                original_cand_id=cand.id,
                resolved_source_path=str(resolved_candidate),
                resolved_target_path=None,
            )
        )

    # 4. Dependency graph, collision detection & topological sort
    graph_res = resolve_suffix_transform_graph(
        items=actionable_candidates,
        allowed_roots=safety_snapshot.allowed_roots,
        quarantine_root=safety_snapshot.quarantine_root,
    )

    conflicts_by_src: dict[str, list[Any]] = {}
    for c in graph_res.conflicts:
        conflicts_by_src.setdefault(c.source_path, []).append(c)

    for cand_item in actionable_candidates:
        if cand_item.source_path in conflicts_by_src:
            primary_c = conflicts_by_src[cand_item.source_path][0]
            decision_rows.append({
                "source_path": cand_item.source_path,
                "target_path": cand_item.target_path,
                "index_root_id": cand_item.index_root_id,
                "index_root_path": cand_item.index_root_path,
                "relative_path": cand_item.relative_path,
                "object_type": "file",
                "decision": "BLOCKING_CONFLICT",
                "reason_code": primary_c.conflict_type,
                "reason": primary_c.reason,
                "size": cand_item.size,
                "protected_dir": None,
            })
        else:
            decision_rows.append({
                "source_path": cand_item.source_path,
                "target_path": cand_item.target_path,
                "index_root_id": cand_item.index_root_id,
                "index_root_path": cand_item.index_root_path,
                "relative_path": cand_item.relative_path,
                "object_type": "file",
                "decision": "RENAME",
                "reason_code": None,
                "reason": None,
                "size": cand_item.size,
                "protected_dir": None,
            })

    # Sort decision rows deterministically by source_path asc
    decision_rows.sort(key=lambda r: r["source_path"])

    # Build intents from surviving ordered items (Blocker F)
    intents: list[BatchUtilityDraftIntent] = []
    for seq, ord_item in enumerate(graph_res.ordered_items, start=1):
        meta_dict = {
            "utility_action": "suffix_transform",
            "mode": mode,
            "suffix": target_suffix,
            "index_root_id": ord_item.index_root_id,
            "index_root_path": ord_item.index_root_path,
            "relative_path": ord_item.relative_path,
            "source_basename": Path(ord_item.source_path).name,
            "target_basename": Path(ord_item.target_path).name,
        }
        intents.append(
            BatchUtilityDraftIntent(
                sequence=seq,
                operation="rename",
                source_path=ord_item.source_path,
                target_path=ord_item.target_path,
                keep_path=None,
                expected_size=ord_item.size,
                expected_device=0,
                expected_inode=0,
                expected_mtime_ns=0,
                expected_hash=None,
                metadata_json=canonical_json_dumps(meta_dict),
            )
        )

    planned_operations_count = len(intents)
    skipped_count = sum(1 for r in decision_rows if r["decision"] == "SKIPPED")
    safety_excluded_count = sum(1 for r in decision_rows if r["decision"] == "SAFETY_EXCLUDED")
    blocking_conflict_count = sum(1 for r in decision_rows if r["decision"] == "BLOCKING_CONFLICT")
    expected_reclaim_bytes = 0

    source_snapshot_payload = {
        "roots": [{"id": r.id, "root": r.root} for r in roots_by_id.values()],
        "source_facts": source_facts,
        "mode": mode,
        "suffix": target_suffix,
        "blocking_conflict_count": blocking_conflict_count,
        "ordered_sources": [item.source_path for item in graph_res.ordered_items],
        "target_observations": list(graph_res.target_observations),
        "casefold_directory_observations": list(graph_res.directory_observations),
        "dependency_edges": list(graph_res.dependency_edges),
        "conflict_facts": [
            {
                "source_path": c.source_path,
                "target_path": c.target_path,
                "conflict_type": c.conflict_type,
                "reason": c.reason,
            }
            for c in graph_res.conflicts
        ],
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
        compiled_where_clause=compiled_lineage_where,
        filter_policy_snapshot=filter_policy_snapshot,
    )


def compile_batch_utility_preview(
    *,
    session: Session,
    action: QuarantineFilteredAction | SuffixTransformAction,
    safety_snapshot: BatchUtilitySafetySnapshot,
) -> BatchUtilityCompilation:
    if action.type == "quarantine_filtered":
        return compile_quarantine_filtered_preview(
            session=session,
            action=action,
            safety_snapshot=safety_snapshot,
        )
    elif action.type == "suffix_transform":
        return compile_suffix_transform_preview(
            session=session,
            action=action,
            safety_snapshot=safety_snapshot,
        )
    raise BatchUtilityInvalidConfigError(f"Unsupported action type: {getattr(action, 'type', None)}")
