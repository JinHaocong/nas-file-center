from __future__ import annotations

import contextlib
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
from typing import Any

from sqlalchemy import select

from app.batch.plans import OperationItem
from app.execution.executor import _resolve_utility_empty_wrapper_cleanup_authority
from app.models import BatchPlan, BatchPlanItem, OperationJournal
from app.path_safety import UnsafePathError, is_reserved_quarantine_path, require_allowed_path
from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd
from app.execution.utility_structural_cleanup import UtilityStructuralCleanupResult


RECOVERED_UTILITY_STRUCTURAL_CLEANUP_REASON = (
    "reconciled after crash (utility structural cleanup completed)"
)



@dataclass
class PreparedUtilityStructuralCleanup:
    parent_context: Any
    parent_fd: int
    wrapper_fd: int
    leaf_name: str
    cleanup_item_id: int

    def close(self) -> None:
        try:
            os.close(self.wrapper_fd)
        finally:
            self.parent_context.__exit__(None, None, None)

    def cleanup_after_move(self) -> UtilityStructuralCleanupResult:
        try:
            st_open = os.fstat(self.wrapper_fd)
            st_path = os.stat(
                self.leaf_name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
        except OSError as exc:
            return UtilityStructuralCleanupResult(
                "failed",
                f"post-move wrapper binding inspection failed: {exc}",
            )

        if (
            not stat.S_ISDIR(st_open.st_mode)
            or stat.S_ISLNK(st_open.st_mode)
            or not stat.S_ISDIR(st_path.st_mode)
            or stat.S_ISLNK(st_path.st_mode)
        ):
            return UtilityStructuralCleanupResult(
                "failed",
                "post-move wrapper binding is no longer a directory",
            )

        if (
            int(st_open.st_dev) != int(st_path.st_dev)
            or int(st_open.st_ino) != int(st_path.st_ino)
        ):
            return UtilityStructuralCleanupResult(
                "failed",
                "post-move wrapper path binding changed",
            )

        try:
            if os.listdir(self.wrapper_fd):
                return UtilityStructuralCleanupResult(
                    "failed",
                    "post-move wrapper is not empty",
                )
            os.rmdir(self.leaf_name, dir_fd=self.parent_fd)
        except OSError as exc:
            return UtilityStructuralCleanupResult(
                "failed",
                f"post-move wrapper cleanup failed: {exc}",
            )

        return UtilityStructuralCleanupResult(
            "completed",
            "empty wrapper structurally removed in paired MOVE transaction",
        )


def prepare_utility_structural_cleanup_guard(
    session: Any,
    move_item: BatchPlanItem,
    plan_id: int,
    settings: Any,
) -> PreparedUtilityStructuralCleanup | None:
    if move_item.operation != "move":
        return None

    try:
        move_meta = json.loads(move_item.metadata_json or "{}")
    except Exception:
        return None
    if not isinstance(move_meta, dict):
        return None

    candidate_id = move_meta.get("candidate_id")
    wrapper_path = move_meta.get("wrapper_path")
    child_path = move_meta.get("child_path")
    target_path = move_meta.get("target_path")
    if (
        not isinstance(candidate_id, str)
        or not candidate_id.strip()
        or not isinstance(wrapper_path, str)
        or child_path != move_item.source_path
        or target_path != move_item.target_path
    ):
        return None

    plan = session.get(BatchPlan, plan_id)
    if plan is None:
        return None
    try:
        plan_meta = json.loads(plan.metadata_json or "{}")
    except Exception:
        return None
    compile_context = plan_meta.get("compile_context") if isinstance(plan_meta, dict) else None
    if (
        not isinstance(plan_meta, dict)
        or plan_meta.get("source") != "workflow"
        or plan_meta.get("workflow_mode") != "utility"
        or not isinstance(compile_context, dict)
        or compile_context.get("utility_action") != "single_child_wrapper_collapse"
    ):
        return None

    cleanup = session.scalar(
        select(BatchPlanItem).where(
            BatchPlanItem.plan_id == plan_id,
            BatchPlanItem.sequence == move_item.sequence + 1,
        )
    )
    if cleanup is None or cleanup.operation != "rmdir_empty":
        return None
    try:
        cleanup_meta = json.loads(cleanup.metadata_json or "{}")
    except Exception:
        return None
    if (
        not isinstance(cleanup_meta, dict)
        or cleanup_meta.get("candidate_id") != candidate_id
        or cleanup_meta.get("wrapper_path") != wrapper_path
        or cleanup_meta.get("child_path") != child_path
        or cleanup_meta.get("target_path") != target_path
        or cleanup.source_path != wrapper_path
        or not isinstance(cleanup.expected_device, int)
        or cleanup.expected_device <= 0
        or not isinstance(cleanup.expected_inode, int)
        or cleanup.expected_inode <= 0
    ):
        return None

    source = Path(wrapper_path)
    require_allowed_path(source, settings.allowed_roots)
    if settings.quarantine_root and is_reserved_quarantine_path(
        source, settings.quarantine_root
    ):
        raise RuntimeError("wrapper cleanup path is reserved quarantine storage")
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("safe paired wrapper cleanup requires O_NOFOLLOW")

    parent_context = safe_open_parent_fd(source, settings.allowed_roots)
    parent_fd, leaf_name = parent_context.__enter__()
    wrapper_fd = -1
    try:
        st_path = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            stat.S_ISLNK(st_path.st_mode)
            or not stat.S_ISDIR(st_path.st_mode)
            or int(st_path.st_dev) != int(cleanup.expected_device)
            or int(st_path.st_ino) != int(cleanup.expected_inode)
        ):
            raise RuntimeError(
                "pre-move wrapper identity no longer matches frozen cleanup authority"
            )
        wrapper_fd = os.open(
            leaf_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        st_open = os.fstat(wrapper_fd)
        if (
            int(st_open.st_dev) != int(st_path.st_dev)
            or int(st_open.st_ino) != int(st_path.st_ino)
        ):
            raise RuntimeError("pre-move wrapper path binding changed while opening")
        return PreparedUtilityStructuralCleanup(
            parent_context=parent_context,
            parent_fd=parent_fd,
            wrapper_fd=wrapper_fd,
            leaf_name=leaf_name,
            cleanup_item_id=int(cleanup.id),
        )
    except Exception:
        if wrapper_fd >= 0:
            os.close(wrapper_fd)
        parent_context.__exit__(None, None, None)
        raise


def _operation_item_from_row(item: BatchPlanItem) -> OperationItem:
    return OperationItem(
        sequence=item.sequence,
        operation=item.operation,
        source=Path(item.source_path),
        target=Path(item.target_path) if item.target_path else None,
        keep=Path(item.keep_path) if item.keep_path else None,
        expected_size=item.expected_size,
        expected_hash=item.expected_hash,
        state=item.state,
        expected_mtime_ns=item.expected_mtime_ns,
        expected_device=item.expected_device,
        expected_inode=item.expected_inode,
    )


def _authority_from_existing_session(session: Any, item: BatchPlanItem, plan_id: int) -> bool:
    @contextlib.contextmanager
    def existing_session_factory():
        yield session

    return _resolve_utility_empty_wrapper_cleanup_authority(
        _operation_item_from_row(item),
        plan_id=str(plan_id),
        session_factory=existing_session_factory,
    )


def _inspect_frozen_wrapper(
    source: Path,
    *,
    allowed_roots: list[Path | str],
    quarantine_root: Path | str | None,
    expected_device: int,
    expected_inode: int,
) -> tuple[bool, str | None]:
    try:
        require_allowed_path(source, allowed_roots)
    except (UnsafePathError, OSError, ValueError):
        return False, "reconciliation conflict after crash (path safety violation)"

    if quarantine_root and is_reserved_quarantine_path(source, quarantine_root):
        return False, "reconciliation conflict after crash (quarantine path violation)"
    if not hasattr(os, "O_NOFOLLOW"):
        return False, "reconciliation conflict after crash (O_NOFOLLOW unavailable)"

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        with safe_open_parent_fd(source, allowed_roots) as (parent_fd, leaf_name):
            st_leaf = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
            if stat.S_ISLNK(st_leaf.st_mode) or not stat.S_ISDIR(st_leaf.st_mode):
                return False, "reconciliation conflict after crash (source is not frozen directory)"
            if st_leaf.st_dev != expected_device or st_leaf.st_ino != expected_inode:
                return False, "reconciliation conflict after crash (source identity mismatch)"

            wrapper_fd = os.open(leaf_name, flags, dir_fd=parent_fd)
            try:
                st_open = os.fstat(wrapper_fd)
                if (
                    not stat.S_ISDIR(st_open.st_mode)
                    or stat.S_ISLNK(st_open.st_mode)
                    or st_open.st_dev != expected_device
                    or st_open.st_ino != expected_inode
                ):
                    return False, "reconciliation conflict after crash (source identity mismatch)"
                if os.listdir(wrapper_fd):
                    return False, "reconciliation conflict after crash (source directory is not empty)"
            finally:
                os.close(wrapper_fd)
    except Exception as exc:
        return False, f"reconciliation conflict after crash (wrapper inspection failed: {exc})"

    return True, None


def reconcile_utility_structural_cleanup(
    session: Any,
    item: BatchPlanItem,
    plan_id: int,
    job_id: int,
    user_id: int | None,
    settings: Any,
    now: Any,
) -> bool:
    """Handle crash recovery only for the exact frozen Utility cleanup pair.

    Returns True when the item is an authorized structural cleanup and recovery
    has been fully classified. False means the historical generic rmdir_empty
    reconciliation path must remain authoritative.
    """
    if item.operation != "rmdir_empty":
        return False
    if not _authority_from_existing_session(session, item, plan_id):
        return False

    meta = json.loads(item.metadata_json or "{}")
    exec_meta = meta.get("execution") or {}
    source_stat = exec_meta.get("source_stat") or {}
    metadata_before = exec_meta.get("metadata_before") or source_stat
    expected_device = item.expected_device or source_stat.get("device")
    expected_inode = item.expected_inode or source_stat.get("inode")
    if expected_device is None or expected_inode is None:
        item.state = "failed"
        item.reason = "reconciliation conflict after crash (missing pre-mutation identity evidence)"
        return True
    if exec_meta.get("phase") != "intent" or exec_meta.get("operation") != "rmdir_empty":
        item.state = "failed"
        item.reason = "reconciliation conflict after crash (missing structural cleanup intent)"
        return True

    source = Path(item.source_path)
    if os.path.lexists(source):
        safe, reason = _inspect_frozen_wrapper(
            source,
            allowed_roots=list(settings.allowed_roots),
            quarantine_root=getattr(settings, "quarantine_root", None),
            expected_device=int(expected_device),
            expected_inode=int(expected_inode),
        )
        if safe:
            item.state = "planned"
            item.reason = None
        else:
            item.state = "failed"
            item.reason = reason
        return True

    # A durable execution intent exists, the exact paired MOVE is completed,
    # and the frozen wrapper path is now absent. For this non-recursive
    # structural primitive, absence is the completed namespace state.
    item.state = "completed"
    item.reason = RECOVERED_UTILITY_STRUCTURAL_CLEANUP_REASON
    existing_journal = session.scalar(
        select(OperationJournal).where(OperationJournal.plan_item_id == item.id)
    )
    if existing_journal is None:
        session.add(
            OperationJournal(
                operation=item.operation,
                sequence=item.sequence,
                plan_id=plan_id,
                plan_item_id=item.id,
                task_id=job_id,
                user_id=user_id,
                before_json=json.dumps(
                    {
                        "path": item.source_path,
                        "scope_root": meta.get("scope_root"),
                        "object_type": "directory",
                    },
                    ensure_ascii=False,
                ),
                after_json=json.dumps(
                    {
                        "logical_removed": True,
                        "preserved": False,
                        "removed": True,
                        "structural_cleanup": True,
                        "quarantine_path": None,
                    },
                    ensure_ascii=False,
                ),
                metadata_before_json=json.dumps(metadata_before, ensure_ascii=False),
                metadata_after_json=json.dumps({}, ensure_ascii=False),
                created_at=now,
            )
        )
    return True


def normalize_structural_cleanup_journal(connection: Any, target: OperationJournal) -> None:
    """Correct the historical rmdir journal shape before the row is inserted.

    The base Worker writes a preservation-shaped journal for every completed
    rmdir_empty. Direct Utility structural cleanup is uniquely represented by a
    completed rmdir journal with no quarantine_path. Verify its frozen Utility
    plan/item pairing from the same transaction before changing that shape.
    """
    if target.operation != "rmdir_empty" or target.plan_id is None or target.plan_item_id is None:
        return
    try:
        after = json.loads(target.after_json or "{}")
    except Exception:
        return
    if not isinstance(after, dict) or after.get("logical_removed") is not True:
        return
    if after.get("quarantine_path") is not None:
        return

    plan_table = BatchPlan.__table__
    item_table = BatchPlanItem.__table__
    plan_row = connection.execute(
        select(plan_table.c.metadata_json).where(plan_table.c.id == target.plan_id)
    ).first()
    current_row = connection.execute(
        select(
            item_table.c.sequence,
            item_table.c.operation,
            item_table.c.source_path,
            item_table.c.metadata_json,
        ).where(item_table.c.id == target.plan_item_id)
    ).first()
    if plan_row is None or current_row is None or current_row.operation != "rmdir_empty":
        return

    try:
        plan_meta = json.loads(plan_row.metadata_json or "{}")
        current_meta = json.loads(current_row.metadata_json or "{}")
    except Exception:
        return
    compile_context = plan_meta.get("compile_context") if isinstance(plan_meta, dict) else None
    if (
        not isinstance(plan_meta, dict)
        or plan_meta.get("source") != "workflow"
        or plan_meta.get("workflow_mode") != "utility"
        or not isinstance(compile_context, dict)
        or compile_context.get("utility_action") != "single_child_wrapper_collapse"
        or not isinstance(current_meta, dict)
        or current_meta.get("wrapper_path") != current_row.source_path
    ):
        return

    candidate_id = current_meta.get("candidate_id")
    predecessor = connection.execute(
        select(
            item_table.c.operation,
            item_table.c.state,
            item_table.c.metadata_json,
        ).where(
            item_table.c.plan_id == target.plan_id,
            item_table.c.sequence == current_row.sequence - 1,
        )
    ).first()
    if predecessor is None or predecessor.operation != "move" or predecessor.state != "completed":
        return
    try:
        predecessor_meta = json.loads(predecessor.metadata_json or "{}")
    except Exception:
        return
    if (
        not isinstance(predecessor_meta, dict)
        or not isinstance(candidate_id, str)
        or not candidate_id.strip()
        or predecessor_meta.get("candidate_id") != candidate_id
        or predecessor_meta.get("wrapper_path") != current_meta.get("wrapper_path")
        or predecessor_meta.get("target_path") != current_meta.get("target_path")
    ):
        return

    after["preserved"] = False
    after["structural_cleanup"] = True
    after["quarantine_path"] = None
    target.after_json = json.dumps(after, ensure_ascii=False)
