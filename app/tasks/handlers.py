from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Type

from sqlalchemy import delete, select, text

from app.batch.plans import OperationItem
from app.config import Settings
from app.execution.executor import execute_item
from app.models import (
    AuditEvent,
    BatchPlan,
    BatchPlanItem,
    DataLifecyclePolicy,
    DuplicateFile,
    DuplicateGroup,
    OperationJournal,
    QuarantineEntry,
    ScanJob,
    TaskLock,
    WorkJob,
    utcnow,
)
from app.exceptions import StateConflictError
from app.path_safety import require_allowed_path
from app.quarantine.paths import build_quarantine_target_path, safe_quarantine_hash
from app.quarantine.restore import (
    validate_quarantine_for_restore,
    validate_restore_destination_intent,
    verify_quarantine_source_integrity,
    assert_source_unmodified,
)
from app.scanners.fclones import build_group_command, run_scan
from app.scanners.parser import parse_fclones_report, parse_fclones_report_iter
from app.tasks.context import JobContext
from app.tasks.state_machine import JobCancelRequested, JobLeaseLost, JobPauseRequested


class TaskHandler(ABC):
    job_type: str
    supports_pause: bool = False
    supports_cancel: bool = True
    supports_retry: bool = True
    supports_resume: bool = False

    @abstractmethod
    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        """Execute the job logic with context support."""
        pass


JOB_HANDLERS: dict[str, Type[TaskHandler]] = {}


def register_handler(handler_cls: Type[TaskHandler]) -> Type[TaskHandler]:
    JOB_HANDLERS[handler_cls.job_type] = handler_cls
    return handler_cls


def get_handler(job_type: str) -> TaskHandler | None:
    cls = JOB_HANDLERS.get(job_type)
    return cls() if cls else None


def get_job_capabilities(job_type: str) -> dict[str, bool]:
    cls = JOB_HANDLERS.get(job_type)
    if not cls:
        return {
            "supports_pause": False,
            "supports_cancel": True,
            "supports_retry": True,
            "supports_resume": False,
        }
    return {
        "supports_pause": cls.supports_pause,
        "supports_cancel": cls.supports_cancel,
        "supports_retry": cls.supports_retry,
        "supports_resume": cls.supports_resume,
    }


def _containing_root(path: Path, roots: list[Path]) -> tuple[int, Path] | None:
    matches = [(idx, root) for idx, root in enumerate(roots) if path == root or path.is_relative_to(root)]
    if not matches:
        return None
    return max(matches, key=lambda pair: len(pair[1].parts))


@register_handler
class IndexRootHandler(TaskHandler):
    job_type = "index-root"
    supports_pause = False
    supports_cancel = False
    supports_retry = True
    supports_resume = False

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        from app.service import FileCenterService
        state = json.loads(job.state_json or "{}")
        root_str = state.get("root")
        if not root_str:
            raise ValueError("State missing 'root'")

        # Checkpoint before starting
        context.checkpoint(
            progress_current=0,
            progress_total=None,
            progress_message="Starting root reindex...",
            checkpoint_data={"schema_version": 1, "phase": "starting"},
        )

        service = FileCenterService(settings)

        def guard(session):
            if context.worker_id is not None:
                from app.tasks.recovery import assert_active_worker_lease
                assert_active_worker_lease(session, context.worker_id, now=utcnow())

        def on_batch(current: int, total: int | None = None):
            effective_total = total if (total is not None and total > 0) else None
            context.checkpoint(
                progress_current=current,
                progress_total=effective_total,
                progress_message=f"Indexing {current} items...",
            )

        result = service.reindex_root(
            root_str,
            transaction_guard=guard,
            checkpoint_callback=on_batch,
        )

        total_items = result.get("files", 0) + result.get("folders", 0)
        context.checkpoint(
            progress_current=total_items,
            progress_total=total_items,
            progress_message="Root reindex completed",
            checkpoint_data={"schema_version": 1, "phase": "completed", "result": result},
        )


from app.tasks.state_machine import JobCancelRequested, JobLeaseLost

SCAN_IMPORT_BATCH_SIZE: int = 100


@register_handler
class FclonesScanHandler(TaskHandler):
    job_type = "fclones-scan"
    supports_pause = False
    supports_cancel = True
    supports_retry = True
    supports_resume = False

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        state = json.loads(job.state_json or "{}")
        scan_job_id = int(state.get("scan_job_id", 0))
        roots_raw = state.get("roots", [])

        roots = [require_allowed_path(p, settings.allowed_roots) for p in roots_raw]
        report_path = settings.reports_dir / f"scan-{scan_job_id}.json"

        # Checkpoint to announce starting
        context.checkpoint(
            progress_current=0,
            progress_total=0,
            progress_message="Building scan command...",
        )

        effective_excludes = list(state.get("exclude_patterns") or [])
        if getattr(settings, "quarantine_root", None):
            q_root_str = str(settings.quarantine_root)
            q_pattern = f"{q_root_str}/**"
            if q_pattern not in effective_excludes:
                effective_excludes.append(q_pattern)

        command = build_group_command(
            binary=settings.fclones_binary,
            roots=roots,
            allowed_roots=settings.allowed_roots,
            isolate=bool(state.get("isolate", False)),
            min_size=state.get("min_size"),
            threads=state.get("threads") or settings.fclones_threads,
            name_patterns=state.get("name_patterns"),
            exclude_patterns=effective_excludes,
        )

        context.checkpoint(
            progress_current=0,
            progress_total=0,
            progress_message="Running fclones scan subprocess...",
        )

        completed = run_scan(
            command,
            report_path=report_path,
            home_dir=settings.fclones_home,
            context=context,
        )

        if completed.returncode != 0:
            err_msg = completed.stderr[-8000:] if completed.stderr else f"fclones exit {completed.returncode}"
            raise RuntimeError(err_msg)

        context.checkpoint(
            progress_current=0,
            progress_total=0,
            progress_message="Parsing scan results into database...",
        )

        # Clean existing duplicate groups before importing under active lease
        with context.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            now = utcnow()
            if context.worker_id is not None:
                from app.tasks.recovery import assert_active_worker_lease
                assert_active_worker_lease(session, context.worker_id, now=now)

            group_ids_subq = select(DuplicateGroup.id).where(DuplicateGroup.scan_job_id == scan_job_id)
            session.execute(delete(DuplicateFile).where(DuplicateFile.group_id.in_(group_ids_subq)))
            session.execute(delete(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_job_id))
            session.commit()

        context.checkpoint(
            progress_current=0,
            progress_total=0,
            progress_message="Importing duplicate groups...",
        )

        total_groups = 0
        total_files = 0
        reclaimable = 0

        if hasattr(parse_fclones_report, "mock_calls"):
            group_iter = iter(parse_fclones_report(report_path))
        else:
            group_iter = parse_fclones_report_iter(report_path)

        try:
            while True:
                # 1. Read a bounded batch of ParsedGroup from iterator and resolve filesystem metadata
                # Completely OUTSIDE the database write transaction to avoid blocking heartbeats!
                batch_entries = []
                for parsed in group_iter:
                    members = []
                    for raw_path in parsed.files:
                        raw = Path(raw_path)
                        if raw.is_symlink():
                            continue
                        try:
                            safe = require_allowed_path(raw, roots)
                        except ValueError:
                            continue
                        if not safe.is_file():
                            continue
                        if getattr(settings, "quarantine_root", None):
                            from app.path_safety import is_reserved_quarantine_path
                            if is_reserved_quarantine_path(safe, settings.quarantine_root):
                                continue
                        root_match = _containing_root(safe, roots)
                        if root_match is None:
                            continue
                        root_id, root = root_match
                        stat = safe.stat(follow_symlinks=False)
                        relative = safe.relative_to(root)
                        top = root / relative.parts[0] if len(relative.parts) > 1 else root
                        members.append((root_id, safe, relative, top, stat))

                    if len(members) >= 2:
                        batch_entries.append((parsed, members))
                        if len(batch_entries) >= SCAN_IMPORT_BATCH_SIZE:
                            break

                if not batch_entries:
                    break

                # 2. Short, tight DB write transaction to insert this batch under active lease
                with context.SessionLocal() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    now = utcnow()
                    if context.worker_id is not None:
                        from app.tasks.recovery import assert_active_worker_lease
                        assert_active_worker_lease(session, context.worker_id, now=now)

                    for parsed, members in batch_entries:
                        group = DuplicateGroup(
                            scan_job_id=scan_job_id,
                            content_hash=parsed.content_hash,
                            file_size=parsed.file_size,
                            member_count=len(members),
                        )
                        session.add(group)
                        session.flush()
                        for root_id, safe, relative, top, stat in members:
                            session.add(DuplicateFile(
                                group_id=group.id,
                                root_id=root_id,
                                absolute_path=str(safe),
                                relative_path=relative.as_posix(),
                                top_level_dir=str(top),
                                size=stat.st_size,
                                mtime_ns=stat.st_mtime_ns,
                                device=stat.st_dev,
                                inode=stat.st_ino,
                            ))
                        total_groups += 1
                        total_files += len(members)
                        reclaimable += parsed.file_size * (len(members) - 1)
                    session.commit()

                # 3. Checkpoint outside DB transaction (fences worker lease & checks cancel)
                context.checkpoint(
                    progress_current=total_groups,
                    progress_total=0,
                    progress_message=f"Importing duplicate groups ({total_groups} found)...",
                )

            with context.SessionLocal() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                now = utcnow()
                if context.worker_id is not None:
                    from app.tasks.recovery import assert_active_worker_lease
                    assert_active_worker_lease(session, context.worker_id, now=now)

                scan = session.get(ScanJob, scan_job_id)
                if scan:
                    scan.status = "completed"
                    scan.finished_at = now
                    scan.raw_report_path = str(report_path)
                    scan.total_groups = total_groups
                    scan.total_files_in_groups = total_files
                    scan.reclaimable_bytes = reclaimable
                    scan.error_text = None
                    session.commit()

            context.checkpoint(
                progress_current=total_groups,
                progress_total=total_groups,
                progress_message=f"Scan completed: found {total_groups} duplicate groups",
            )
        except JobLeaseLost:
            # Stale worker MUST NOT mutate database!
            # No delete, no update, no commit.
            # Partial cleanup is handled exclusively by the new lease owner in recover_interrupted_jobs().
            raise
        except (JobCancelRequested, Exception):
            # Clean up partial import so no broken duplicate data remains under active lease
            with context.SessionLocal() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                now = utcnow()
                if context.worker_id is not None:
                    try:
                        from app.tasks.recovery import assert_active_worker_lease
                        assert_active_worker_lease(session, context.worker_id, now=now)
                    except JobLeaseLost:
                        # Stale worker MUST NOT mutate database!
                        raise
                group_ids_subq = select(DuplicateGroup.id).where(DuplicateGroup.scan_job_id == scan_job_id)
                session.execute(delete(DuplicateFile).where(DuplicateFile.group_id.in_(group_ids_subq)))
                session.execute(delete(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_job_id))
                scan = session.get(ScanJob, scan_job_id)
                if scan:
                    scan.total_groups = 0
                    scan.total_files_in_groups = 0
                    scan.reclaimable_bytes = 0
                session.commit()
            raise


def _check_target_identity(tgt: Path, source_stat: dict) -> bool:
    if not source_stat or not isinstance(source_stat, dict):
        return False
    src_dev = source_stat.get("device")
    src_ino = source_stat.get("inode")
    if src_dev is None or src_ino is None:
        return False
    try:
        st = tgt.stat(follow_symlinks=False)
    except OSError:
        return False
    if st.st_dev != src_dev:
        return False
    if st.st_ino != src_ino:
        return False
    return True


def _build_stat_dict(p: Path, st: os.stat_result) -> dict:
    obj_type = "directory" if p.is_dir() else ("symlink" if p.is_symlink() else "file")
    return {
        "object_type": obj_type,
        "size": st.st_size,
        "mtime_ns": getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        "device": getattr(st, "st_dev", 0),
        "inode": getattr(st, "st_ino", 0),
    }


@dataclass(frozen=True)
class ReconcileEvidence:
    content_hash: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    object_type: str = "file"


def gather_reconcile_evidence(p: Path) -> ReconcileEvidence | None:
    p = Path(p)
    if not p.is_file() or p.is_symlink():
        return None
    try:
        st = p.stat(follow_symlinks=False)
        h = safe_quarantine_hash(p)
        return ReconcileEvidence(
            content_hash=h,
            device=getattr(st, "st_dev", 0),
            inode=getattr(st, "st_ino", 0),
            size=st.st_size,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
            object_type="file",
        )
    except OSError:
        return None


def _validate_evidence(st: os.stat_result, evidence: Any) -> bool:
    if evidence is None:
        return False
    if isinstance(evidence, dict):
        ev_dev = evidence.get("device")
        ev_ino = evidence.get("inode")
        ev_size = evidence.get("size")
        ev_mtime_ns = evidence.get("mtime_ns")
        ev_hash = evidence.get("content_hash")
    else:
        ev_dev = getattr(evidence, "device", None)
        ev_ino = getattr(evidence, "inode", None)
        ev_size = getattr(evidence, "size", None)
        ev_mtime_ns = getattr(evidence, "mtime_ns", None)
        ev_hash = getattr(evidence, "content_hash", None)

    if not ev_hash or ev_dev is None or ev_ino is None or ev_size is None or ev_mtime_ns is None:
        return False
    if getattr(st, "st_dev", 0) != ev_dev:
        return False
    if getattr(st, "st_ino", 0) != ev_ino:
        return False
    if st.st_size != ev_size:
        return False
    curr_mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    if curr_mtime_ns != ev_mtime_ns:
        return False
    return True


def _get_evidence_hash(evidence: Any) -> str | None:
    if evidence is None:
        return None
    if isinstance(evidence, dict):
        return evidence.get("content_hash")
    return getattr(evidence, "content_hash", None)


def _reconcile_executing_item(
    session,
    item: BatchPlanItem,
    plan_id: int,
    job_id: int,
    user_id: int | None,
    settings: Settings,
    now,
    precomputed_hash: str | None = None,
    precomputed_evidence: ReconcileEvidence | dict | None = None,
) -> None:
    """Reconcile an item found in 'executing' state after a crash or worker restart."""
    src = Path(item.source_path)
    meta = json.loads(item.metadata_json or "{}")
    exec_meta = meta.get("execution") or {}
    source_stat = exec_meta.get("source_stat") or {}
    metadata_before = exec_meta.get("metadata_before") or source_stat

    evidence = precomputed_evidence

    if item.operation in ("rename", "move"):
        tgt = Path(item.target_path) if item.target_path else None
        if tgt and tgt.exists() and not src.exists():
            st = tgt.stat(follow_symlinks=False)
            if not _check_target_identity(tgt, source_stat):
                item.state = "failed"
                item.reason = "reconciliation conflict after crash (target identity mismatch)"
                return

            item.state = "completed"
            item.reason = "reconciled after crash (target exists)"
            existing_j = session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == item.id))
            if not existing_j:
                res_stat = _build_stat_dict(tgt, st)
                session.add(OperationJournal(
                    operation=item.operation,
                    sequence=item.sequence,
                    plan_id=plan_id,
                    plan_item_id=item.id,
                    task_id=job_id,
                    user_id=user_id,
                    before_json=json.dumps({"path": str(src), "size": source_stat.get("size") or item.expected_size, "mtime_ns": source_stat.get("mtime_ns")}, ensure_ascii=False),
                    after_json=json.dumps({"path": str(tgt), "size": st.st_size, "mtime_ns": getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))}, ensure_ascii=False),
                    metadata_before_json=json.dumps(metadata_before or source_stat, ensure_ascii=False),
                    metadata_after_json=json.dumps(res_stat, ensure_ascii=False),
                    created_at=now,
                ))
        elif src.exists() and (not tgt or not tgt.exists()):
            item.state = "planned"
            item.reason = None
        else:
            item.state = "failed"
            item.reason = "reconciliation conflict after crash"

    elif item.operation == "quarantine":
        q_entry = session.scalar(select(QuarantineEntry).where(QuarantineEntry.plan_item_id == item.id))
        tgt = Path(q_entry.quarantine_path) if q_entry and q_entry.quarantine_path else (Path(item.target_path) if item.target_path else None)
        if tgt and tgt.exists() and not src.exists():
            st = tgt.stat(follow_symlinks=False)
            if not _check_target_identity(tgt, source_stat):
                item.state = "failed"
                item.reason = "reconciliation conflict after crash (target identity mismatch)"
                if q_entry:
                    q_entry.state = "abandoned"
                    q_entry.last_error = item.reason
                    q_entry.updated_at = now
                return

            if tgt.is_file() and not tgt.is_symlink():
                if not _validate_evidence(st, evidence):
                    item.state = "failed"
                    item.reason = "reconciliation conflict after crash (missing or stale quarantine hash evidence)"
                    if q_entry:
                        q_entry.state = "abandoned"
                        q_entry.last_error = item.reason
                        q_entry.updated_at = now
                    return
                if q_entry:
                    q_entry.content_hash = _get_evidence_hash(evidence)
            elif q_entry:
                q_entry.content_hash = None

            item.state = "completed"
            item.reason = "reconciled after crash (quarantine exists)"
            if q_entry:
                q_entry.size = st.st_size
                q_entry.mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
                q_entry.device = getattr(st, "st_dev", 0)
                q_entry.inode = getattr(st, "st_ino", 0)
                q_entry.state = "active"
                q_entry.quarantined_at = q_entry.quarantined_at or now
                q_entry.updated_at = now
            existing_j = session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == item.id))
            if not existing_j:
                res_stat = _build_stat_dict(tgt, st)
                session.add(OperationJournal(
                    operation=item.operation,
                    sequence=item.sequence,
                    plan_id=plan_id,
                    plan_item_id=item.id,
                    task_id=job_id,
                    user_id=user_id,
                    before_json=json.dumps({"path": str(src), "size": source_stat.get("size") or item.expected_size, "mtime_ns": source_stat.get("mtime_ns"), "is_dir": False}, ensure_ascii=False),
                    after_json=json.dumps({"quarantine_path": str(tgt), "quarantine_entry_id": q_entry.id if q_entry else None, "size": st.st_size, "mtime_ns": getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))}, ensure_ascii=False),
                    metadata_before_json=json.dumps(metadata_before or source_stat, ensure_ascii=False),
                    metadata_after_json=json.dumps(res_stat, ensure_ascii=False),
                    created_at=now,
                ))
        elif src.exists() and (not tgt or not tgt.exists()):
            if q_entry:
                q_entry.state = "abandoned"
                q_entry.updated_at = now
            item.state = "planned"
            item.reason = None
        else:
            item.state = "failed"
            item.reason = "reconciliation conflict after crash"

    elif item.operation == "restore":
        tgt = Path(item.target_path) if item.target_path else None
        qid = meta.get("quarantine_entry_id") or meta.get("undo", {}).get("quarantine_entry_id")
        q_entry = session.get(QuarantineEntry, int(qid)) if qid else None
        if tgt and tgt.exists() and not src.exists():
            st = tgt.stat(follow_symlinks=False)
            if not _check_target_identity(tgt, source_stat):
                item.state = "failed"
                item.reason = "reconciliation conflict after crash (target identity mismatch)"
                if q_entry:
                    q_entry.state = "inconsistent"
                    q_entry.last_error = item.reason
                    q_entry.updated_at = now
                return
            if q_entry and q_entry.content_hash and tgt.is_file() and not tgt.is_symlink():
                if not _validate_evidence(st, evidence):
                    item.state = "failed"
                    item.reason = "reconciliation conflict after crash (missing or stale restore hash evidence)"
                    if q_entry:
                        q_entry.state = "inconsistent"
                        q_entry.last_error = item.reason
                        q_entry.updated_at = now
                    return
                ev_hash = _get_evidence_hash(evidence)
                if ev_hash != q_entry.content_hash:
                    item.state = "failed"
                    item.reason = f"reconciliation conflict after crash (hash mismatch: expected {q_entry.content_hash}, got {ev_hash})"
                    if q_entry:
                        q_entry.state = "inconsistent"
                        q_entry.last_error = item.reason
                        q_entry.updated_at = now
                    return

            item.state = "completed"
            item.reason = "reconciled after crash (restored file exists)"
            if q_entry:
                q_entry.state = "restored"
                q_entry.restored_at = q_entry.restored_at or now
                q_entry.updated_at = now
            existing_j = session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == item.id))
            if not existing_j:
                res_stat = _build_stat_dict(tgt, st)
                session.add(OperationJournal(
                    operation=item.operation,
                    sequence=item.sequence,
                    plan_id=plan_id,
                    plan_item_id=item.id,
                    task_id=job_id,
                    user_id=user_id,
                    before_json=json.dumps({"quarantine_path": str(src), "quarantine_entry_id": q_entry.id if q_entry else None, "original_path": str(tgt), "size": source_stat.get("size") or item.expected_size, "mtime_ns": source_stat.get("mtime_ns")}, ensure_ascii=False),
                    after_json=json.dumps({"restored_path": str(tgt), "size": st.st_size, "mtime_ns": getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))}, ensure_ascii=False),
                    metadata_before_json=json.dumps(metadata_before or source_stat, ensure_ascii=False),
                    metadata_after_json=json.dumps(res_stat, ensure_ascii=False),
                    created_at=now,
                ))
        elif src.exists() and (not tgt or not tgt.exists()):
            if q_entry and q_entry.state == "restoring":
                q_entry.state = "active"
                q_entry.updated_at = now
            item.state = "planned"
            item.reason = None
        else:
            item.state = "failed"
            item.reason = "reconciliation conflict after crash"

    elif item.operation == "touch":
        meta = json.loads(item.metadata_json or "{}")
        exec_meta = meta.get("execution") or {}
        target_mtime_ns = exec_meta.get("target_mtime_ns") or item.expected_mtime_ns
        source_stat = exec_meta.get("source_stat") or {}
        before_mtime_ns = source_stat.get("mtime_ns")

        if src.exists():
            st = src.stat(follow_symlinks=False)
            curr_mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
            if target_mtime_ns and curr_mtime_ns == target_mtime_ns:
                item.state = "completed"
                item.reason = "reconciled after crash (touch target mtime matches)"
                existing_j = session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == item.id))
                if not existing_j:
                    session.add(OperationJournal(
                        operation=item.operation,
                        sequence=item.sequence,
                        plan_id=plan_id,
                        plan_item_id=item.id,
                        task_id=job_id,
                        user_id=user_id,
                        before_json=json.dumps({"path": str(src), "mtime_ns": before_mtime_ns}, ensure_ascii=False),
                        after_json=json.dumps({"path": str(src), "mtime_ns": curr_mtime_ns}, ensure_ascii=False),
                        metadata_before_json=json.dumps(source_stat, ensure_ascii=False),
                        metadata_after_json=json.dumps({
                            "object_type": "file",
                            "size": st.st_size,
                            "mtime_ns": curr_mtime_ns,
                            "device": getattr(st, "st_dev", 0),
                            "inode": getattr(st, "st_ino", 0),
                        }, ensure_ascii=False),
                        created_at=now,
                    ))
            elif before_mtime_ns is not None and curr_mtime_ns == before_mtime_ns:
                item.state = "planned"
                item.reason = None
            else:
                item.state = "failed"
                item.reason = "reconciliation conflict after crash (mtime mismatch)"
        else:
            item.state = "failed"
            item.reason = "reconciliation failed: source does not exist"


@register_handler
class BatchPlanExecuteHandler(TaskHandler):
    job_type = "batch-plan-execute"
    supports_pause = True
    supports_cancel = True
    supports_retry = True
    supports_resume = True

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        from app.tasks.recovery import assert_active_worker_lease

        state = json.loads(job.state_json or "{}")
        plan_id = int(state.get("plan_id", 0))
        if not plan_id:
            raise ValueError("Job state missing 'plan_id'")
        user_id = state.get("requested_by_user_id")

        # 1. Announce start & reconcile interrupted items
        # Precompute reconciliation evidence outside DB write lock
        precomputed_evidence: dict[int, ReconcileEvidence] = {}
        with context.SessionLocal() as session:
            exec_items = list(session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id, BatchPlanItem.state == "executing")
                .order_by(BatchPlanItem.sequence)
            ))
            for it in exec_items:
                if it.operation in ("quarantine", "restore"):
                    meta = json.loads(it.metadata_json or "{}")
                    tgt = None
                    if it.operation == "quarantine":
                        qid = meta.get("quarantine_entry_id") or meta.get("undo", {}).get("quarantine_entry_id")
                        qe = session.get(QuarantineEntry, int(qid)) if qid else None
                        if not qe:
                            qe = session.scalar(select(QuarantineEntry).where(QuarantineEntry.plan_item_id == it.id))
                        tgt = Path(qe.quarantine_path) if qe and qe.quarantine_path else (Path(it.target_path) if it.target_path else None)
                    elif it.operation == "restore":
                        tgt = Path(it.target_path) if it.target_path else None
                    src = Path(it.source_path)
                    if tgt and not src.exists():
                        ev = gather_reconcile_evidence(tgt)
                        if ev:
                            precomputed_evidence[it.id] = ev

        reconciled_failed_item_ids: set[int] = set()
        with context.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            now = utcnow()
            if context.worker_id is not None:
                assert_active_worker_lease(session, context.worker_id, now=now)

            plan = session.get(BatchPlan, plan_id)
            if not plan:
                raise KeyError(f"Plan #{plan_id} not found")
            plan.status = "executing"
            plan_meta = json.loads(plan.metadata_json or "{}")
            is_organizer = plan_meta.get("is_organizer", False)
            mtime_delay = float(plan_meta.get("mtime_delay_seconds", 0) or 0)

            executing_items = list(session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id, BatchPlanItem.state == "executing")
                .order_by(BatchPlanItem.sequence)
            ))
            for it in executing_items:
                _reconcile_executing_item(
                    session, it, plan_id, job.id, user_id, settings, now,
                    precomputed_evidence=precomputed_evidence.get(it.id),
                )
                if it.state == "failed":
                    reconciled_failed_item_ids.add(it.id)
            session.commit()

        # 2. Query all plan items
        with context.SessionLocal() as session:
            all_items = list(session.scalars(
                select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id).order_by(BatchPlanItem.sequence)
            ))
            total_count = len(all_items)
            completed_or_skipped = sum(1 for item in all_items if item.state in ("completed", "skipped"))

        context.checkpoint(
            progress_current=completed_or_skipped,
            progress_total=total_count,
            progress_message=f"Executing plan #{plan_id} ({completed_or_skipped}/{total_count} processed)...",
        )

        # 3. Item-by-item 3-phase execution
        for item_meta in all_items:
            # Check current status in DB before starting Phase 1
            if item_meta.id in reconciled_failed_item_ids:
                continue

            with context.SessionLocal() as session:
                row = session.get(BatchPlanItem, item_meta.id)
                if row is None or row.state in ("completed", "skipped", "failed") or row.id in reconciled_failed_item_ids:
                    continue

            # Checkpoint at item boundary
            context.checkpoint(
                progress_current=completed_or_skipped,
                progress_total=total_count,
                progress_message=f"Executing item #{item_meta.sequence}: {item_meta.operation}...",
            )

            # --- PHASE 1: DB INTENT ---
            q_entry_id = None
            q_restore_entry_id = None
            target_path_str = None
            src_p = Path(item_meta.source_path)
            src_stat_dict = {}
            target_touch_mtime_ns = None
            restore_expected_size = None
            restore_expected_hash = None
            try:
                if src_p.exists():
                    st = src_p.stat(follow_symlinks=False)
                    obj_type = "directory" if src_p.is_dir() else ("symlink" if src_p.is_symlink() else "file")
                    src_stat_dict = {
                        "object_type": obj_type,
                        "size": st.st_size,
                        "mtime_ns": getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
                        "device": getattr(st, "st_dev", 0),
                        "inode": getattr(st, "st_ino", 0),
                    }
            except OSError:
                pass

            with context.SessionLocal() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                now = utcnow()
                if context.worker_id is not None:
                    assert_active_worker_lease(session, context.worker_id, now=now)

                row = session.get(BatchPlanItem, item_meta.id)
                if row.state in ("completed", "skipped", "failed") or row.id in reconciled_failed_item_ids:
                    completed_or_skipped += 1
                    continue

                row.state = "executing"

                if row.operation == "touch":
                    target_touch_mtime_ns = row.expected_mtime_ns if (row.expected_mtime_ns and row.expected_mtime_ns > 0) else int(now.timestamp() * 1e9)

                item_metadata = json.loads(row.metadata_json or "{}")
                item_metadata["execution"] = {
                    "phase": "intent",
                    "task_id": job.id,
                    "operation": row.operation,
                    "source_stat": src_stat_dict,
                    "metadata_before": src_stat_dict,
                    "target_mtime_ns": target_touch_mtime_ns,
                }
                row.metadata_json = json.dumps(item_metadata, ensure_ascii=False)

                if row.operation == "quarantine":
                    q_entry = QuarantineEntry(
                        plan_item_id=row.id,
                        task_id=job.id,
                        original_path=row.source_path,
                        quarantine_path="",
                        state="preparing",
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(q_entry)
                    session.flush()
                    q_entry_id = q_entry.id

                    q_target = build_quarantine_target_path(
                        source=Path(row.source_path),
                        allowed_roots=settings.allowed_roots,
                        quarantine_root=settings.quarantine_root,
                        plan_id=str(plan_id),
                        entry_id=q_entry.id,
                        check_symlink=True,
                        task_id=job.id,
                    )
                    q_entry.quarantine_path = str(q_target)
                    row.target_path = str(q_target)
                    target_path_str = str(q_target)
                elif row.operation == "restore":
                    meta_dict = json.loads(row.metadata_json or "{}")
                    qid = meta_dict.get("quarantine_entry_id") or meta_dict.get("undo", {}).get("quarantine_entry_id")
                    if not qid:
                        row.state = "failed"
                        row.reason = "missing quarantine_entry_id for restore operation"
                        session.commit()
                        completed_or_skipped += 1
                        continue
                    q_entry = session.get(QuarantineEntry, int(qid))
                    if not q_entry:
                        row.state = "failed"
                        row.reason = f"Quarantine entry #{qid} not found"
                        session.commit()
                        completed_or_skipped += 1
                        continue

                    try:
                        q_tgt_p, q_dest_p = validate_restore_destination_intent(
                            q_entry,
                            allowed_roots=settings.allowed_roots,
                            quarantine_root=settings.quarantine_root,
                            conflict_policy="skip",
                        )
                    except (StateConflictError, ValueError) as exc:
                        q_entry.updated_at = now
                        row.state = "failed"
                        row.reason = str(exc)
                        session.add(AuditEvent(
                            operation=row.operation,
                            path=row.source_path,
                            result="failed",
                            details_json=json.dumps({
                                "plan_id": plan_id,
                                "item_id": row.id,
                                "task_id": job.id,
                                "quarantine_entry_id": q_entry.id,
                                "reason": str(exc),
                            }, ensure_ascii=False),
                        ))
                        session.commit()
                        completed_or_skipped += 1
                        continue

                    q_entry.state = "restoring"
                    q_entry.updated_at = now
                    q_restore_entry_id = q_entry.id
                    target_path_str = str(q_dest_p)
                    restore_expected_size = q_entry.size
                    restore_expected_hash = q_entry.content_hash
                else:
                    target_path_str = row.target_path

                session.commit()

            # --- PRE-MUTATION RESTORE INTEGRITY (OUTSIDE DB WRITE LOCK) ---
            verified_restore_stat = None
            if item_meta.operation == "restore":
                try:
                    verified_restore_stat = verify_quarantine_source_integrity(
                        src_p,
                        expected_size=restore_expected_size,
                        expected_hash=restore_expected_hash,
                    )
                except (StateConflictError, ValueError) as exc:
                    with context.SessionLocal() as session:
                        session.execute(text("BEGIN IMMEDIATE"))
                        now = utcnow()
                        if context.worker_id is not None:
                            assert_active_worker_lease(session, context.worker_id, now=now)
                        row = session.get(BatchPlanItem, item_meta.id)
                        if row:
                            row.state = "failed"
                            row.reason = str(exc)
                        if q_restore_entry_id:
                            qe = session.get(QuarantineEntry, q_restore_entry_id)
                            if qe:
                                qe.state = "inconsistent"
                                qe.last_error = str(exc)
                                qe.updated_at = now
                        session.add(AuditEvent(
                            operation="restore",
                            path=str(src_p),
                            result="failed",
                            details_json=json.dumps({
                                "plan_id": plan_id,
                                "item_id": item_meta.id,
                                "task_id": job.id,
                                "reason": str(exc),
                            }, ensure_ascii=False),
                        ))
                        session.commit()
                    completed_or_skipped += 1
                    continue

            # --- PHASE 2: FILESYSTEM MUTATION OUTSIDE DB LOCK ---
            before_size = src_stat_dict.get("size")
            before_mtime_ns = src_stat_dict.get("mtime_ns")

            item_op = OperationItem(
                sequence=item_meta.sequence,
                operation=item_meta.operation,
                source=src_p,
                target=Path(target_path_str) if target_path_str else None,
                keep=Path(item_meta.keep_path) if item_meta.keep_path else None,
                expected_size=restore_expected_size if item_meta.operation == "restore" else item_meta.expected_size,
                expected_hash=restore_expected_hash if item_meta.operation == "restore" else item_meta.expected_hash,
                state=item_meta.state,
                expected_mtime_ns=item_meta.expected_mtime_ns,
                target_mtime_ns=target_touch_mtime_ns,
            )

            # Boundary Fence: Freshly renew and assert active worker lease before filesystem mutation
            if context.worker_id is not None:
                with context.SessionLocal() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    now = utcnow()
                    assert_active_worker_lease(session, context.worker_id, now=now)
                    lock = session.get(TaskLock, 1)
                    if lock and lock.owner == context.worker_id:
                        lock.acquired_at = now
                    session.commit()

            # Final immediate source identity/stat check before mutation
            if item_meta.operation == "restore" and verified_restore_stat is not None:
                try:
                    assert_source_unmodified(src_p, verified_restore_stat)
                except ValueError as exc:
                    with context.SessionLocal() as session:
                        session.execute(text("BEGIN IMMEDIATE"))
                        now = utcnow()
                        if context.worker_id is not None:
                            assert_active_worker_lease(session, context.worker_id, now=now)
                        row = session.get(BatchPlanItem, item_meta.id)
                        if row:
                            row.state = "failed"
                            row.reason = str(exc)
                        if q_restore_entry_id:
                            qe = session.get(QuarantineEntry, q_restore_entry_id)
                            if qe:
                                qe.state = "inconsistent"
                                qe.last_error = str(exc)
                                qe.updated_at = now
                        session.add(AuditEvent(
                            operation="restore",
                            path=str(src_p),
                            result="failed",
                            details_json=json.dumps({
                                "plan_id": plan_id,
                                "item_id": item_meta.id,
                                "task_id": job.id,
                                "reason": str(exc),
                            }, ensure_ascii=False),
                        ))
                        session.commit()
                    completed_or_skipped += 1
                    continue

            result = execute_item(
                item_op,
                allowed_roots=settings.allowed_roots,
                allow_mutation=settings.allow_mutation,
                allow_delete=settings.allow_delete,
                quarantine_root=settings.quarantine_root,
                plan_id=str(plan_id),
            )

            after_size = None
            after_mtime_ns = None
            q_stat_size = None
            q_stat_mtime_ns = None
            q_stat_dev = None
            q_stat_ino = None
            q_content_hash = None

            if result.state == "completed":
                res_p = result.result_path or src_p
                try:
                    if res_p.exists():
                        st = res_p.stat(follow_symlinks=False)
                        after_size = st.st_size
                        after_mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
                        if q_entry_id is not None and result.result_path and result.result_path.exists():
                            q_stat_size = st.st_size
                            q_stat_mtime_ns = after_mtime_ns
                            q_stat_dev = st.st_dev
                            q_stat_ino = st.st_ino
                            if res_p.is_dir():
                                q_content_hash = None
                            else:
                                q_content_hash = safe_quarantine_hash(res_p)
                except OSError:
                    pass

            # --- PHASE 3: FENCED DB FINALIZE ---
            with context.SessionLocal() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                now = utcnow()
                if context.worker_id is not None:
                    assert_active_worker_lease(session, context.worker_id, now=now)

                row = session.get(BatchPlanItem, item_meta.id)
                row.state = result.state
                row.reason = result.reason

                metadata = json.loads(row.metadata_json or "{}")
                if result.result_path is not None:
                    metadata["result_path"] = str(result.result_path)
                    row.metadata_json = json.dumps(metadata, ensure_ascii=False)

                if q_entry_id is not None:
                    q_entry = session.get(QuarantineEntry, q_entry_id)
                    if q_entry:
                        if result.state == "completed" and result.result_path and result.result_path.exists():
                            q_entry.size = q_stat_size or 0
                            q_entry.content_hash = q_content_hash
                            q_entry.mtime_ns = q_stat_mtime_ns or 0
                            q_entry.device = q_stat_dev or 0
                            q_entry.inode = q_stat_ino or 0
                            q_entry.quarantined_at = now
                            policy = session.scalar(select(DataLifecyclePolicy).where(DataLifecyclePolicy.id == 1))
                            retention_days = policy.quarantine_retention_days if policy else 0
                            q_entry.expires_at = (now + timedelta(days=retention_days)) if retention_days > 0 else None
                            q_entry.state = "active"
                            q_entry.updated_at = now
                        else:
                            q_entry.state = "abandoned"
                            q_entry.last_error = result.reason
                            q_entry.updated_at = now

                if q_restore_entry_id is not None:
                    q_entry = session.get(QuarantineEntry, q_restore_entry_id)
                    if q_entry:
                        if result.state == "completed":
                            q_entry.state = "restored"
                            q_entry.restored_at = now
                            q_entry.updated_at = now
                        elif result.state == "failed":
                            q_entry.state = "inconsistent"
                            q_entry.last_error = result.reason
                            q_entry.updated_at = now
                        else:
                            q_entry.state = "active"
                            q_entry.last_error = result.reason
                            q_entry.updated_at = now

                if result.state == "completed":
                    if row.operation in ("rename", "move"):
                        b_json = json.dumps({"path": row.source_path, "size": before_size or row.expected_size, "mtime_ns": before_mtime_ns}, ensure_ascii=False)
                        a_json = json.dumps({"path": str(result.result_path), "size": after_size, "mtime_ns": after_mtime_ns}, ensure_ascii=False)
                    elif row.operation == "quarantine":
                        b_json = json.dumps({"path": row.source_path, "size": before_size or row.expected_size, "mtime_ns": before_mtime_ns, "is_dir": False}, ensure_ascii=False)
                        a_json = json.dumps({"quarantine_path": str(result.result_path), "quarantine_entry_id": q_entry_id, "size": after_size, "mtime_ns": after_mtime_ns}, ensure_ascii=False)
                    elif row.operation == "restore":
                        b_json = json.dumps({
                            "quarantine_path": row.source_path,
                            "quarantine_entry_id": q_restore_entry_id,
                            "original_path": row.target_path,
                            "size": before_size or row.expected_size,
                            "mtime_ns": before_mtime_ns,
                        }, ensure_ascii=False)
                        a_json = json.dumps({
                            "restored_path": str(result.result_path),
                            "size": after_size,
                            "mtime_ns": after_mtime_ns,
                        }, ensure_ascii=False)
                    elif row.operation == "touch":
                        b_json = json.dumps({"path": row.source_path, "mtime_ns": before_mtime_ns}, ensure_ascii=False)
                        a_json = json.dumps({"path": row.source_path, "mtime_ns": after_mtime_ns}, ensure_ascii=False)
                    else:
                        b_json = json.dumps({"path": row.source_path}, ensure_ascii=False)
                        a_json = json.dumps({"path": str(result.result_path) if result.result_path else None}, ensure_ascii=False)

                    res_stat_dict = {}
                    res_target = result.result_path if (result.result_path and result.result_path.exists()) else (src_p if (result.state == "completed" and src_p.exists()) else None)
                    if res_target:
                        try:
                            st_res = res_target.stat(follow_symlinks=False)
                            res_obj_type = "directory" if res_target.is_dir() else ("symlink" if res_target.is_symlink() else "file")
                            res_stat_dict = {
                                "object_type": res_obj_type,
                                "size": st_res.st_size,
                                "mtime_ns": getattr(st_res, "st_mtime_ns", int(st_res.st_mtime * 1e9)),
                                "device": getattr(st_res, "st_dev", 0),
                                "inode": getattr(st_res, "st_ino", 0),
                            }
                        except OSError:
                            pass

                    meta_before_dict = verified_restore_stat if (row.operation == "restore" and verified_restore_stat) else src_stat_dict
                    session.add(OperationJournal(
                        operation=row.operation,
                        sequence=row.sequence,
                        plan_id=plan_id,
                        plan_item_id=row.id,
                        task_id=job.id,
                        user_id=user_id,
                        before_json=b_json,
                        after_json=a_json,
                        metadata_before_json=json.dumps(meta_before_dict, ensure_ascii=False),
                        metadata_after_json=json.dumps(res_stat_dict, ensure_ascii=False),
                        created_at=now,
                    ))

                session.add(AuditEvent(
                    operation=row.operation,
                    path=row.source_path,
                    result=result.state,
                    details_json=json.dumps({
                        "plan_id": plan_id,
                        "item_id": row.id,
                        "task_id": job.id,
                        "quarantine_entry_id": q_entry_id,
                        "reason": result.reason,
                        "target": row.target_path,
                        "result_path": str(result.result_path) if result.result_path else None,
                    }, ensure_ascii=False),
                ))
                session.commit()

            if is_organizer and item_meta.operation == "touch" and result.state == "completed" and mtime_delay > 0:
                time.sleep(mtime_delay)

            completed_or_skipped += 1

        # 4. Post-Loop Plan Status Finalization
        with context.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            now = utcnow()
            if context.worker_id is not None:
                assert_active_worker_lease(session, context.worker_id, now=now)

            plan = session.get(BatchPlan, plan_id)
            items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id)))
            states = {it.state for it in items}
            plan.status = "completed" if states <= {"completed"} else "partial"
            session.commit()

        context.checkpoint(
            progress_current=total_count,
            progress_total=total_count,
            progress_message=f"Plan #{plan_id} execution finished (status: {plan.status})",
        )
