from __future__ import annotations

from datetime import datetime, timezone
import heapq
import json
import math
import os
from pathlib import Path
import re
import time
from uuid import uuid4


from app.utils.sorting import _MaxHeapCandidate, natural_sort_key

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.batch.plans import OperationItem
from app.batch.rename import RenameCollisionError, RenameRule, _new_name, build_rename_plan
from app.batch.stats import collect_tree_stats
from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.execution.executor import execute_item
from app.execution.verifier import verify_duplicate_pair
from app.indexing.indexer import IndexedEntry, iter_root, scan_root
from app.indexing.matcher import match_entries
from app.models import (
    AuditEvent,
    BatchPlan,
    BatchPlanItem,
    DuplicateFile,
    DuplicateGroup,
    FavoritePath,
    IndexedPath,
    OrganizerProfile,
    RecentPath,
    ScanJob,
    WorkJob,
    utcnow,
)
from app.path_safety import require_allowed_path, validate_mutation_destination
from app.organizers.engine import generate_organizer_proposals
from app.organizers.planner import plan_organizer_operations
from app.organizers.templates import (
    ALLOWED_RENAME_VARS,
    ALLOWED_STATISTICS_VARS,
    sanitize_extensions,
    validate_and_normalize_extensions,
    validate_cleanup_patterns,
    validate_template,
)
from app.planning.engine import CandidateFile, CandidateGroup, generate_plan
from app.tasks.service import TaskService


class FileCenterService:
    def __init__(self, settings: Settings):
        self.settings = settings
        for directory in (settings.config_dir, settings.reports_dir, settings.backups_dir, settings.logs_dir, settings.fclones_home):
            directory.mkdir(parents=True, exist_ok=True)
        self.engine, self.SessionLocal = create_engine_and_session(settings.database_path)
        init_db(
            self.engine,
            db_path=settings.database_path,
            backups_dir=settings.backups_dir,
            initial_admin_username=settings.initial_admin_username,
            initial_admin_password=settings.initial_admin_password,
        )
        self.task_service = TaskService(self.SessionLocal)
        self._preview_snapshots: dict[str, dict[str, Any]] = {}

    def dashboard_summary(self) -> dict:
        with self.SessionLocal() as session:
            latest_completed = session.scalar(
                select(ScanJob).where(ScanJob.status == "completed").order_by(ScanJob.id.desc()).limit(1)
            )
            return {
                "indexed_files": session.scalar(select(func.count(IndexedPath.id)).where(IndexedPath.is_dir.is_(False))) or 0,
                "indexed_folders": session.scalar(select(func.count(IndexedPath.id)).where(IndexedPath.is_dir.is_(True))) or 0,
                "scan_count": session.scalar(select(func.count(ScanJob.id))) or 0,
                "plan_count": session.scalar(select(func.count(BatchPlan.id))) or 0,
                "duplicate_group_count": session.scalar(select(func.count(DuplicateGroup.id))) or 0,
                "queued_or_running_jobs": session.scalar(
                    select(func.count(WorkJob.id)).where(WorkJob.status.in_(["queued", "running"]))
                ) or 0,
                "latest_reclaimable_bytes": latest_completed.reclaimable_bytes if latest_completed else 0,
            }

    def list_scans(self, *, page: int = 1, page_size: int = 20, limit: int | None = None) -> dict:
        if limit is not None:
            page_size = limit
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 500))
        offset = (page - 1) * page_size
        with self.SessionLocal() as session:
            total = session.scalar(select(func.count(ScanJob.id))) or 0
            rows = list(session.scalars(select(ScanJob).order_by(ScanJob.id.desc()).limit(page_size).offset(offset)))
            items = [{
                "id": row.id,
                "name": row.name,
                "mode": row.mode,
                "roots": json.loads(row.roots_json or "[]"),
                "status": row.status,
                "total_groups": row.total_groups,
                "total_files_in_groups": row.total_files_in_groups,
                "reclaimable_bytes": row.reclaimable_bytes,
                "error": row.error_text,
                "created_at": row.created_at,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
            } for row in rows]
            return {"items": items, "total": total, "page": page, "page_size": page_size}

    def scan_groups(self, scan_job_id: int, *, page: int = 1, page_size: int = 20, limit: int | None = None) -> dict:
        if limit is not None:
            page_size = limit
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 500))
        offset = (page - 1) * page_size
        with self.SessionLocal() as session:
            if session.get(ScanJob, scan_job_id) is None:
                raise KeyError(scan_job_id)
            total = session.scalar(select(func.count(DuplicateGroup.id)).where(DuplicateGroup.scan_job_id == scan_job_id)) or 0
            groups = list(session.scalars(
                select(DuplicateGroup)
                .where(DuplicateGroup.scan_job_id == scan_job_id)
                .order_by(DuplicateGroup.file_size.desc(), DuplicateGroup.id)
                .limit(page_size)
                .offset(offset)
            ))
            items = []
            for group in groups:
                files = list(session.scalars(
                    select(DuplicateFile).where(DuplicateFile.group_id == group.id).order_by(DuplicateFile.root_id, DuplicateFile.relative_path)
                ))
                items.append({
                    "id": group.id,
                    "content_hash": group.content_hash,
                    "file_size": group.file_size,
                    "member_count": group.member_count,
                    "reclaimable_bytes": group.file_size * max(group.member_count - 1, 0),
                    "members": [{
                        "id": file.id,
                        "root_id": file.root_id,
                        "path": file.absolute_path,
                        "relative_path": file.relative_path,
                        "top_level_dir": file.top_level_dir,
                        "size": file.size,
                        "mtime_ns": file.mtime_ns,
                    } for file in files],
                })
            return {"items": items, "total": total, "page": page, "page_size": page_size}

    def list_plans(self, *, page: int = 1, page_size: int = 20, limit: int | None = None) -> dict:
        if limit is not None:
            page_size = limit
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 500))
        offset = (page - 1) * page_size
        with self.SessionLocal() as session:
            total = session.scalar(select(func.count(BatchPlan.id))) or 0
            rows = list(session.scalars(select(BatchPlan).order_by(BatchPlan.id.desc()).limit(page_size).offset(offset)))
            items = [{
                "id": row.id,
                "name": row.name,
                "kind": row.kind,
                "status": row.status,
                "expected_changes": row.expected_changes,
                "expected_reclaim_bytes": row.expected_reclaim_bytes,
                "metadata": json.loads(row.metadata_json or "{}"),
                "created_at": row.created_at,
                "frozen_at": row.frozen_at,
            } for row in rows]
            return {"items": items, "total": total, "page": page, "page_size": page_size}

    def list_work_jobs(self, *, page: int = 1, page_size: int = 20, limit: int | None = None) -> dict:
        if limit is not None:
            page_size = limit
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 500))
        offset = (page - 1) * page_size
        with self.SessionLocal() as session:
            total = session.scalar(select(func.count(WorkJob.id))) or 0
            rows = list(session.scalars(select(WorkJob).order_by(WorkJob.id.desc()).limit(page_size).offset(offset)))
            items = [{
                "id": row.id,
                "kind": row.kind,
                "status": row.status,
                "progress_current": row.progress_current,
                "progress_total": row.progress_total,
                "state": json.loads(row.state_json or "{}"),
                "error": row.error_text,
                "created_at": row.created_at,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
            } for row in rows]
            return {"items": items, "total": total, "page": page, "page_size": page_size}

    def list_tasks(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        status: str | None = None,
        job_type: str | None = None,
    ) -> dict:
        return self.task_service.list_tasks(page=page, page_size=page_size, status=status, job_type=job_type)

    def get_task_detail(self, task_id: int) -> dict:
        return self.task_service.get_task_detail(task_id)

    def pause_task(self, task_id: int) -> dict:
        return self.task_service.pause_task(task_id)

    def resume_task(self, task_id: int) -> dict:
        return self.task_service.resume_task(task_id)

    def cancel_task(self, task_id: int) -> dict:
        return self.task_service.cancel_task(task_id)

    def retry_task(self, task_id: int) -> dict:
        return self.task_service.retry_task(task_id)

    def delete_task(self, task_id: int) -> dict:
        return self.task_service.delete_task(task_id)

    def clear_task_history(self, statuses: list[str] | None = None) -> dict:
        return self.task_service.clear_task_history(statuses)

    def get_task_logs(
        self,
        task_id: int,
        *,
        page: int = 1,
        page_size: int = 50,
        level: str | None = None,
    ) -> dict:
        return self.task_service.get_task_logs(task_id, page=page, page_size=page_size, level=level)

    def get_worker_status(self) -> dict:
        return self.task_service.get_worker_status()

    def list_audit_events(self, *, page: int = 1, page_size: int = 20, limit: int | None = None, query: str | None = None, operation: str | None = None) -> dict:
        if limit is not None:
            page_size = limit
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 500))
        offset = (page - 1) * page_size
        with self.SessionLocal() as session:
            stmt = select(AuditEvent)
            count_stmt = select(func.count(AuditEvent.id))
            if operation:
                stmt = stmt.where(AuditEvent.operation == operation.strip())
                count_stmt = count_stmt.where(AuditEvent.operation == operation.strip())
            if query:
                pattern = f"%{query.strip()}%"
                stmt = stmt.where(AuditEvent.path.like(pattern) | AuditEvent.operation.like(pattern) | AuditEvent.result.like(pattern))
                count_stmt = count_stmt.where(AuditEvent.path.like(pattern) | AuditEvent.operation.like(pattern) | AuditEvent.result.like(pattern))

            total = session.scalar(count_stmt) or 0
            rows = list(session.scalars(stmt.order_by(AuditEvent.id.desc()).limit(page_size).offset(offset)))
            items = []
            for row in rows:
                try:
                    details = json.loads(row.details_json or "{}")
                except json.JSONDecodeError:
                    details = {"raw": row.details_json}
                items.append({
                    "id": row.id,
                    "timestamp": row.timestamp,
                    "operation": row.operation,
                    "path": row.path,
                    "result": row.result,
                    "details": details,
                })
            return {"items": items, "total": total, "page": page, "page_size": page_size}

    def list_index_roots(self, *, page: int = 1, page_size: int = 20, limit: int | None = None) -> dict:
        if limit is not None:
            page_size = limit
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 500))
        offset = (page - 1) * page_size
        with self.SessionLocal() as session:
            total = session.scalar(select(func.count(func.distinct(IndexedPath.root_key)))) or 0
            rows = session.execute(
                select(
                    IndexedPath.root_key,
                    func.sum(func.iif(IndexedPath.is_dir.is_(False), 1, 0)).label("files"),
                    func.sum(func.iif(IndexedPath.is_dir.is_(True), 1, 0)).label("folders"),
                    func.max(IndexedPath.last_seen_at).label("last_seen_at"),
                )
                .group_by(IndexedPath.root_key)
                .order_by(IndexedPath.root_key)
                .limit(page_size)
                .offset(offset)
            ).all()
            items = [{
                "root": row.root_key,
                "files": int(row.files or 0),
                "folders": int(row.folders or 0),
                "last_seen_at": row.last_seen_at,
            } for row in rows]
            return {"items": items, "total": total, "page": page, "page_size": page_size}

    def reindex_root(
        self,
        root: str,
        *,
        batch_size: int = 1000,
        transaction_guard: Any | None = None,
        checkpoint_callback: Any | None = None,
    ) -> dict:
        safe_root = require_allowed_path(root, self.settings.allowed_roots)
        if not safe_root.is_dir():
            raise ValueError(f"Not a directory: {safe_root}")
        root_key = str(safe_root)
        generation = uuid4().hex
        files = folders = 0
        batch: list[dict] = []

        def flush():
            nonlocal batch
            if not batch:
                return
            with self.SessionLocal() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                if transaction_guard is not None:
                    transaction_guard(session)
                stmt = sqlite_insert(IndexedPath).values(batch)
                excluded = stmt.excluded
                stmt = stmt.on_conflict_do_update(
                    index_elements=[IndexedPath.absolute_path],
                    set_={
                        "root_key": excluded.root_key,
                        "relative_path": excluded.relative_path,
                        "basename": excluded.basename,
                        "stem": excluded.stem,
                        "suffix": excluded.suffix,
                        "size": excluded.size,
                        "mtime_ns": excluded.mtime_ns,
                        "device": excluded.device,
                        "inode": excluded.inode,
                        "is_dir": excluded.is_dir,
                        "last_seen_at": excluded.last_seen_at,
                        "scan_generation": excluded.scan_generation,
                    },
                )
                session.execute(stmt)
                session.commit()
            batch = []
            if checkpoint_callback is not None:
                checkpoint_callback(files + folders, None)

        for entry in iter_root(safe_root, self.settings.allowed_roots, root_key=root_key):
            now = utcnow()
            if entry.is_dir:
                folders += 1
            else:
                files += 1
            batch.append({
                "root_key": root_key,
                "absolute_path": str(entry.absolute_path),
                "relative_path": entry.relative_path,
                "basename": entry.basename,
                "stem": entry.stem,
                "suffix": entry.suffix,
                "size": entry.size,
                "mtime_ns": entry.mtime_ns,
                "device": entry.device,
                "inode": entry.inode,
                "is_dir": entry.is_dir,
                "first_seen_at": now,
                "last_seen_at": now,
                "scan_generation": generation,
            })
            if len(batch) >= batch_size:
                flush()
        flush()

        with self.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            if transaction_guard is not None:
                transaction_guard(session)
            session.execute(delete(IndexedPath).where(IndexedPath.root_key == root_key, IndexedPath.scan_generation != generation))
            session.commit()

        return {"root": root_key, "generation": generation, "files": files, "folders": folders}

    def index_match_preview(
        self,
        root_keys: list[str],
        *,
        mode: str,
        normalize_pattern: str | None = None,
        normalize_replacement: str = "",
    ) -> list[dict]:
        normalized_roots = [str(require_allowed_path(root, self.settings.allowed_roots)) for root in root_keys]
        with self.SessionLocal() as session:
            if mode in {"relative-path", "basename", "stem"}:
                column = {
                    "relative-path": IndexedPath.relative_path,
                    "basename": IndexedPath.basename,
                    "stem": IndexedPath.stem,
                }[mode]
                duplicate_keys = list(session.scalars(
                    select(column)
                    .where(IndexedPath.root_key.in_(normalized_roots), IndexedPath.is_dir.is_(False))
                    .group_by(column)
                    .having(func.count(IndexedPath.id) >= 2)
                    .order_by(column)
                ))
                if not duplicate_keys:
                    rows = []
                else:
                    rows = list(session.scalars(
                        select(IndexedPath)
                        .where(IndexedPath.root_key.in_(normalized_roots), IndexedPath.is_dir.is_(False), column.in_(duplicate_keys))
                        .order_by(column, IndexedPath.root_key, IndexedPath.relative_path)
                    ))
            else:
                rows = list(session.scalars(
                    select(IndexedPath)
                    .where(IndexedPath.root_key.in_(normalized_roots), IndexedPath.is_dir.is_(False))
                    .order_by(IndexedPath.root_key, IndexedPath.relative_path)
                ))
        entries = [IndexedEntry(
            root_key=row.root_key,
            absolute_path=Path(row.absolute_path),
            relative_path=row.relative_path,
            basename=row.basename,
            stem=row.stem,
            suffix=row.suffix,
            size=row.size,
            mtime_ns=row.mtime_ns,
            device=row.device,
            inode=row.inode,
            is_dir=row.is_dir,
        ) for row in rows]
        groups = match_entries(
            entries,
            mode=mode,
            normalize_pattern=normalize_pattern,
            normalize_replacement=normalize_replacement,
        )
        return [
            {"key": key, "members": [
                {"root": e.root_key, "path": str(e.absolute_path), "relative_path": e.relative_path, "size": e.size, "mtime_ns": e.mtime_ns}
                for e in members
            ]}
            for key, members in groups.items()
        ]


    def enqueue_index(self, root: str) -> dict:
        safe_root = require_allowed_path(root, self.settings.allowed_roots)
        if not safe_root.is_dir():
            raise ValueError(f"Not a directory: {safe_root}")
        with self.SessionLocal() as session:
            work = WorkJob(
                kind="index-root",
                status="queued",
                state_json=json.dumps({"root": str(safe_root)}, ensure_ascii=False),
            )
            session.add(work); session.commit()
            return {"work_job_id": work.id, "status": work.status, "root": str(safe_root)}

    def work_job_detail(self, work_job_id: int) -> dict:
        with self.SessionLocal() as session:
            work = session.get(WorkJob, work_job_id)
            if work is None:
                raise KeyError(work_job_id)
            return {
                "id": work.id,
                "kind": work.kind,
                "status": work.status,
                "progress_current": work.progress_current,
                "progress_total": work.progress_total,
                "state": json.loads(work.state_json or "{}"),
                "error": work.error_text,
                "created_at": work.created_at,
                "started_at": work.started_at,
                "finished_at": work.finished_at,
            }

    def enqueue_scan(
        self,
        *,
        name: str,
        roots: list[str],
        isolate: bool = False,
        min_size: str | None = None,
        name_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> dict:
        safe_roots = [require_allowed_path(root, self.settings.allowed_roots) for root in roots]
        if not safe_roots:
            raise ValueError("At least one root is required")
        if isolate and len(safe_roots) < 2:
            raise ValueError("Isolate scan requires at least two roots")
        with self.SessionLocal() as session:
            scan = ScanJob(
                name=name,
                mode="isolate" if isolate else "normal",
                roots_json=json.dumps([str(r) for r in safe_roots], ensure_ascii=False),
                status="queued",
                fclones_args_json=json.dumps({"min_size": min_size, "name_patterns": name_patterns, "exclude_patterns": exclude_patterns}, ensure_ascii=False),
            )
            session.add(scan); session.flush()
            work = WorkJob(
                kind="fclones-scan",
                status="queued",
                state_json=json.dumps({
                    "scan_job_id": scan.id,
                    "roots": [str(r) for r in safe_roots],
                    "isolate": isolate,
                    "min_size": min_size,
                    "name_patterns": name_patterns,
                    "exclude_patterns": exclude_patterns,
                }, ensure_ascii=False),
            )
            session.add(work); session.commit()
            return {"scan_job_id": scan.id, "work_job_id": work.id, "status": "queued"}

    def scan_detail(self, scan_job_id: int) -> dict:
        with self.SessionLocal() as session:
            scan = session.get(ScanJob, scan_job_id)
            if scan is None:
                raise KeyError(scan_job_id)
            return {
                "id": scan.id,
                "name": scan.name,
                "mode": scan.mode,
                "roots": json.loads(scan.roots_json),
                "status": scan.status,
                "total_groups": scan.total_groups,
                "total_files_in_groups": scan.total_files_in_groups,
                "reclaimable_bytes": scan.reclaimable_bytes,
                "raw_report_path": scan.raw_report_path,
                "error": scan.error_text,
                "created_at": scan.created_at,
                "started_at": scan.started_at,
                "finished_at": scan.finished_at,
            }

    def create_dedupe_plan(
        self,
        scan_job_id: int,
        *,
        policy: str,
        path_priority_patterns: list[str] | None = None,
        relative_path_priority_patterns: list[str] | None = None,
    ) -> dict:
        with self.SessionLocal() as session:
            scan = session.get(ScanJob, scan_job_id)
            if scan is None:
                raise KeyError(scan_job_id)
            if scan.status != "completed":
                raise ValueError("Scan must be completed")
            db_groups = list(session.scalars(select(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_job_id).order_by(DuplicateGroup.id)))
            candidates: list[CandidateGroup] = []
            top_dirs: set[str] = set()
            root_ids: set[int] = set()
            for db_group in db_groups:
                files = list(session.scalars(select(DuplicateFile).where(DuplicateFile.group_id == db_group.id).order_by(DuplicateFile.absolute_path)))
                cfiles = []
                for file in files:
                    root_ids.add(file.root_id); top_dirs.add(file.top_level_dir)
                    cfiles.append(CandidateFile(
                        path=Path(file.absolute_path),
                        root_id=file.root_id,
                        top_level_dir=file.top_level_dir,
                        size=file.size,
                        mtime_ns=file.mtime_ns,
                        device=file.device,
                        inode=file.inode,
                        relative_path=file.relative_path,
                    ))
                candidates.append(CandidateGroup(db_group.content_hash, db_group.file_size, tuple(cfiles)))

        directory_counts = None
        if self.settings.protect_last_file:
            directory_counts = {}
            for directory in top_dirs:
                count = 0
                path = Path(directory)
                if path.is_dir():
                    for p in path.rglob("*"):
                        if p.is_file() and not p.is_symlink():
                            count += 1
                directory_counts[directory] = count
        generated = generate_plan(
            candidates,
            policy=policy,
            root_order=sorted(root_ids),
            directory_file_counts=directory_counts,
            protect_last_file=self.settings.protect_last_file,
            path_priority_patterns=path_priority_patterns,
            relative_path_priority_patterns=relative_path_priority_patterns,
        )
        raw_items = []
        for item in generated.items:
            raw_items.append({
                "operation": "quarantine",
                "source": str(item.delete.path),
                "keep": str(item.keep.path),
                "expected_size": item.file_size,
                "protected_dir": item.delete.top_level_dir if self.settings.protect_last_file else None,
            })
        plan = self.create_plan(name=f"scan-{scan_job_id}-{policy}", kind="dedupe", items=raw_items)
        with self.SessionLocal() as session:
            db_plan = session.get(BatchPlan, plan.id)
            db_plan.metadata_json = json.dumps({"scan_job_id": scan_job_id, "policy": policy, "delete_counts": generated.delete_counts}, ensure_ascii=False)
            db_plan.expected_reclaim_bytes = sum(item.file_size for item in generated.items)
            session.commit()
        return {"id": plan.id, "status": plan.status, "items": len(generated.items), "delete_counts": generated.delete_counts}

    def validate_plan(self, plan_id: int) -> dict:
        with self.SessionLocal() as session:
            plan = session.get(BatchPlan, plan_id)
            if plan is None:
                raise KeyError(plan_id)
            if plan.status not in {"frozen", "partial", "ready"}:
                raise ValueError(f"Plan must be frozen before validation, current status={plan.status}")
            plan.status = "validating"; session.commit()
            rows = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id).order_by(BatchPlanItem.sequence)))
            all_ok = True
            for row in rows:
                if row.state == "completed":
                    continue
                if row.keep_path:
                    result = verify_duplicate_pair(
                        row.keep_path,
                        row.source_path,
                        allowed_roots=self.settings.allowed_roots,
                        expected_size=row.expected_size,
                        expected_hash=row.expected_hash,
                    )
                    if result.ok:
                        row.expected_hash = result.sha256
                        row.state = "validated"
                        row.reason = "SHA256 verified"
                    else:
                        row.state = "skipped"
                        row.reason = result.reason
                        all_ok = False
                else:
                    row.state = "validated"
                    row.reason = "metadata validation deferred to execution"
                session.add(AuditEvent(operation="validate", path=row.source_path, result=row.state, details_json=json.dumps({"plan_id": plan_id, "item_id": row.id, "reason": row.reason}, ensure_ascii=False)))
                session.commit()
            plan = session.get(BatchPlan, plan_id)
            plan.status = "ready" if all_ok else "partial"
            session.commit()
        return self.plan_detail(plan_id)

    def path_match_preview(self, roots: list[str], *, mode: str, normalize_pattern: str | None = None, normalize_replacement: str = ""):
        entries = []
        for index, root in enumerate(roots):
            entries.extend(scan_root(root, self.settings.allowed_roots, root_key=f"root-{index}"))
        groups = match_entries(
            entries,
            mode=mode,
            normalize_pattern=normalize_pattern,
            normalize_replacement=normalize_replacement,
        )
        return [
            {
                "key": key,
                "members": [
                    {
                        "root": entry.root_key,
                        "path": str(entry.absolute_path),
                        "relative_path": entry.relative_path,
                        "size": entry.size,
                        "mtime_ns": entry.mtime_ns,
                    }
                    for entry in members
                ],
            }
            for key, members in groups.items()
        ]


    def rename_preview(self, paths: list[str], rule: RenameRule) -> list[dict]:
        sources = [require_allowed_path(path, self.settings.allowed_roots) for path in paths]
        sources.sort(key=str)
        source_set = set(sources)
        results = []
        targets: set[Path] = set()

        for index, source in enumerate(sources):
            if not source.exists():
                results.append({
                    "source": str(source),
                    "target": str(source),
                    "conflict": True,
                    "conflict_reason": "源文件不存在",
                })
                continue
            if source.is_symlink():
                results.append({
                    "source": str(source),
                    "target": str(source),
                    "conflict": True,
                    "conflict_reason": "符号链接不允许重命名",
                })
                continue
            try:
                new_file_name = _new_name(source, rule, index)
                target = source.with_name(new_file_name)
                require_allowed_path(target, self.settings.allowed_roots)

                conflict = False
                conflict_reason = None
                if target in targets:
                    conflict = True
                    conflict_reason = "多个源文件映射到同一个目标路径"
                elif target.exists() and target not in source_set and target != source:
                    conflict = True
                    conflict_reason = "目标文件已存在"
                targets.add(target)

                results.append({
                    "source": str(source),
                    "target": str(target),
                    "conflict": conflict,
                    "conflict_reason": conflict_reason,
                })
            except Exception as e:
                results.append({
                    "source": str(source),
                    "target": str(source),
                    "conflict": True,
                    "conflict_reason": str(e),
                })
        return results

    def create_plan(self, *, name: str, kind: str, items: list[dict], metadata: dict | None = None) -> BatchPlan:
        with self.SessionLocal() as session:
            plan = BatchPlan(
                name=name,
                kind=kind,
                status="draft",
                expected_changes=len(items),
                metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
            )
            session.add(plan)
            session.flush()

            # Track planned target paths from renames/moves within this plan
            planned_targets: set[str] = {
                str(validate_mutation_destination(raw["target"], self.settings.allowed_roots))
                for raw in items
                if raw.get("operation") in {"rename", "move"} and raw.get("target")
            }

            for sequence, raw in enumerate(items, 1):
                source = require_allowed_path(raw["source"], self.settings.allowed_roots)
                is_valid_source = (
                    source.exists()
                    or str(source) in planned_targets
                    or any(source.is_relative_to(Path(t)) for t in planned_targets)
                )
                if not is_valid_source:
                    raise ValueError(f"Source does not exist: {source}")
                target = raw.get("target")
                keep = raw.get("keep")
                protected_dir = raw.get("protected_dir")
                if target and raw.get("operation") in {"rename", "move"}:
                    target_path = str(validate_mutation_destination(target, self.settings.allowed_roots))
                elif target:
                    target_path = str(require_allowed_path(target, self.settings.allowed_roots))
                else:
                    target_path = None
                keep_path = str(require_allowed_path(keep, self.settings.allowed_roots)) if keep else None
                item_metadata = {"protected_dir": str(require_allowed_path(protected_dir, self.settings.allowed_roots))} if protected_dir else {}
                session.add(BatchPlanItem(
                    plan_id=plan.id,
                    sequence=raw.get("sequence", sequence),
                    operation=raw["operation"],
                    source_path=str(source),
                    target_path=target_path,
                    keep_path=keep_path,
                    expected_size=int(raw.get("expected_size", 0) or 0),
                    expected_hash=raw.get("expected_hash"),
                    expected_mtime_ns=int(raw.get("expected_mtime_ns", 0) or 0),
                    expected_device=int(raw.get("expected_device", 0) or 0),
                    expected_inode=int(raw.get("expected_inode", 0) or 0),
                    state="planned",
                    metadata_json=json.dumps(item_metadata, ensure_ascii=False),
                ))
            session.commit()
            session.refresh(plan)
            return plan

    def freeze_plan(self, plan_id: int) -> BatchPlan:
        with self.SessionLocal() as session:
            plan = session.get(BatchPlan, plan_id)
            if plan is None:
                raise KeyError(plan_id)
            if plan.status != "draft":
                raise ValueError(f"Only draft plans can be frozen, current status={plan.status}")
            plan.status = "frozen"
            plan.frozen_at = datetime.now(timezone.utc)
            session.commit(); session.refresh(plan)
            return plan

    def execute_plan(self, plan_id: int) -> dict:
        with self.SessionLocal() as session:
            plan = session.get(BatchPlan, plan_id)
            if plan is None:
                raise KeyError(plan_id)
            if plan.status not in {"ready", "partial"}:
                raise ValueError(f"Plan must be validated before execution (status must be 'ready' or 'partial'), current status={plan.status}")
            plan.status = "executing"
            session.commit()

            plan_meta = json.loads(plan.metadata_json or "{}")
            is_organizer = plan_meta.get("is_organizer", False)
            mtime_delay = float(plan_meta.get("mtime_delay_seconds", 0) or 0)

            rows = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id).order_by(BatchPlanItem.sequence)))
            output = []
            for row in rows:
                metadata = json.loads(row.metadata_json or "{}")
                if row.keep_path and not row.expected_hash:
                    row.state = "skipped"
                    row.reason = "duplicate item requires SHA256 validation before execution"
                    session.add(AuditEvent(operation=row.operation, path=row.source_path, result=row.state, details_json=json.dumps({"plan_id": plan_id, "item_id": row.id, "reason": row.reason}, ensure_ascii=False)))
                    session.commit()
                    output.append({"id": row.id, "sequence": row.sequence, "operation": row.operation, "source": row.source_path, "state": row.state, "reason": row.reason, "result_path": None})
                    continue
                operation = OperationItem(
                    sequence=row.sequence,
                    operation=row.operation,
                    source=Path(row.source_path),
                    target=Path(row.target_path) if row.target_path else None,
                    keep=Path(row.keep_path) if row.keep_path else None,
                    expected_size=row.expected_size,
                    expected_hash=row.expected_hash,
                    state=row.state,
                    protected_dir=Path(metadata["protected_dir"]) if metadata.get("protected_dir") else None,
                    expected_mtime_ns=row.expected_mtime_ns,
                    expected_device=row.expected_device,
                    expected_inode=row.expected_inode,
                )
                result = execute_item(
                    operation,
                    allowed_roots=self.settings.allowed_roots,
                    allow_mutation=self.settings.allow_mutation,
                    allow_delete=self.settings.allow_delete,
                    quarantine_root=self.settings.quarantine_root,
                    plan_id=str(plan_id),
                )
                if is_organizer and row.operation == "touch" and result.state == "completed" and mtime_delay > 0:
                    time.sleep(mtime_delay)

                row.state = result.state
                row.reason = result.reason
                if result.result_path is not None:
                    metadata["result_path"] = str(result.result_path)
                    row.metadata_json = json.dumps(metadata, ensure_ascii=False)
                session.add(AuditEvent(
                    operation=row.operation,
                    path=row.source_path,
                    result=result.state,
                    details_json=json.dumps({
                        "plan_id": plan_id,
                        "item_id": row.id,
                        "reason": result.reason,
                        "target": row.target_path,
                        "keep": row.keep_path,
                        "result_path": str(result.result_path) if result.result_path else None,
                    }, ensure_ascii=False),
                ))
                session.commit()
                output.append({
                    "id": row.id,
                    "sequence": row.sequence,
                    "operation": row.operation,
                    "source": row.source_path,
                    "state": row.state,
                    "reason": row.reason,
                    "result_path": str(result.result_path) if result.result_path else None,
                })

            plan = session.get(BatchPlan, plan_id)
            states = {item["state"] for item in output}
            plan.status = "completed" if states <= {"completed"} else "partial"
            session.commit(); session.refresh(plan)
            return {"id": plan.id, "status": plan.status, "items": output}

    def plan_detail(self, plan_id: int, *, page: int = 1, page_size: int = 50) -> dict:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 500))
        offset = (page - 1) * page_size
        with self.SessionLocal() as session:
            plan = session.get(BatchPlan, plan_id)
            if plan is None:
                raise KeyError(plan_id)
            total_items = session.scalar(select(func.count(BatchPlanItem.id)).where(BatchPlanItem.plan_id == plan_id)) or 0
            rows = list(session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan_id)
                .order_by(BatchPlanItem.sequence)
                .limit(page_size)
                .offset(offset)
            ))
            return {
                "id": plan.id,
                "name": plan.name,
                "kind": plan.kind,
                "status": plan.status,
                "expected_changes": plan.expected_changes,
                "expected_reclaim_bytes": plan.expected_reclaim_bytes,
                "created_at": plan.created_at,
                "frozen_at": plan.frozen_at,
                "total_items": total_items,
                "page": page,
                "page_size": page_size,
                "items": [
                    {
                        "id": r.id,
                        "sequence": r.sequence,
                        "operation": r.operation,
                        "source": r.source_path,
                        "target": r.target_path,
                        "keep": r.keep_path,
                        "expected_size": r.expected_size,
                        "expected_hash": r.expected_hash,
                        "state": r.state,
                        "reason": r.reason,
                    }
                    for r in rows
                ],
            }

    def plan_items(self, plan_id: int, *, page: int = 1, page_size: int = 50) -> dict:
        detail = self.plan_detail(plan_id, page=page, page_size=page_size)
        return {
            "items": detail["items"],
            "total": detail["total_items"],
            "page": detail["page"],
            "page_size": detail["page_size"],
        }

    # ==================== Filesystem Browser API ====================

    def list_directory(
        self,
        path: str | None = None,
        *,
        directories_only: bool = True,
        page: int = 1,
        page_size: int = 100,
        search: str | None = None,
    ) -> dict:
        if not path or not path.strip():
            target_path = self.settings.allowed_roots[0]
        else:
            target_path = Path(path.strip())

        safe_path = require_allowed_path(target_path, self.settings.allowed_roots)

        if not safe_path.exists():
            raise FileNotFoundError(f"Path does not exist: {safe_path}")
        if not safe_path.is_dir():
            raise ValueError(f"Path is not a directory: {safe_path}")

        # Compute parent path if parent is still inside ALLOWED_ROOTS and not identical
        parent_str: str | None = None
        if safe_path.parent != safe_path:
            try:
                parent_safe = require_allowed_path(safe_path.parent, self.settings.allowed_roots)
                # If safe_path was already at one of the allowed roots, do not allow going above it
                if safe_path not in self.settings.allowed_roots:
                    parent_str = str(parent_safe)
            except ValueError:
                parent_str = None

        search_clean = search.strip().lower() if search and search.strip() else None

        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 500))
        start = (page - 1) * page_size
        end = start + page_size
        limit = end

        heap: list[_MaxHeapCandidate] = []
        total = 0

        try:
            with os.scandir(safe_path) as it:
                for entry in it:
                    name = entry.name
                    if search_clean and search_clean not in name.lower():
                        continue

                    try:
                        is_symlink = entry.is_symlink()
                        if is_symlink:
                            # Symlink destination security check
                            try:
                                resolved = Path(entry.path).resolve()
                                require_allowed_path(resolved, self.settings.allowed_roots)
                            except (ValueError, RuntimeError):
                                continue

                        is_directory = entry.is_dir(follow_symlinks=True)
                    except OSError:
                        continue

                    if directories_only and not is_directory:
                        continue

                    total += 1
                    type_rank = 0 if is_directory else 1
                    sort_key = (type_rank, natural_sort_key(name), name)
                    cand = _MaxHeapCandidate(sort_key, (name, entry.path, is_directory))

                    if len(heap) < limit:
                        heapq.heappush(heap, cand)
                    elif cand.sort_key < heap[0].sort_key:
                        heapq.heapreplace(heap, cand)
        except PermissionError as exc:
            raise PermissionError(f"Permission denied accessing directory: {safe_path}") from exc

        # Sort the bounded top candidates (at most limit items) in ascending natural order
        top_candidates = sorted(heap, key=lambda c: c.sort_key)
        page_candidates = [c.val for c in top_candidates[start:end]]
        has_more = end < total

        # Only construct full item dicts with stat calls for the requested page slice
        items: list[dict] = []
        for name, entry_path, is_dir in page_candidates:
            size: int | None = None
            mtime_ns: int = 0
            try:
                st = os.stat(entry_path, follow_symlinks=False)
                size = st.st_size if not is_dir else None
                mtime_ns = st.st_mtime_ns
            except OSError:
                size = None
                mtime_ns = 0

            items.append({
                "name": name,
                "path": entry_path,
                "type": "directory" if is_dir else "file",
                "size": size,
                "mtime_ns": mtime_ns,
            })

        return {
            "path": str(safe_path),
            "parent": parent_str,
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": has_more,
            "allowed_roots": [str(r) for r in self.settings.allowed_roots],
        }

    # ==================== Favorite Paths API ====================

    def list_favorites(self, user_id: int) -> list[dict]:
        with self.SessionLocal() as session:
            rows = list(
                session.scalars(
                    select(FavoritePath)
                    .where(FavoritePath.user_id == user_id)
                    .order_by(FavoritePath.position.asc(), FavoritePath.created_at.asc())
                )
            )
            results = []
            for r in rows:
                p = Path(r.path)
                try:
                    safe = require_allowed_path(p, self.settings.allowed_roots)
                    exists = safe.exists() and safe.is_dir()
                except ValueError:
                    exists = False

                results.append({
                    "id": r.id,
                    "path": r.path,
                    "label": r.label or p.name,
                    "position": r.position,
                    "exists": exists,
                    "created_at": r.created_at,
                    "updated_at": r.updated_at,
                })
            return results

    def add_favorite(self, user_id: int, path: str, label: str | None = None) -> dict:
        safe = require_allowed_path(path, self.settings.allowed_roots)
        if not safe.exists():
            raise FileNotFoundError(f"Path does not exist: {safe}")
        if not safe.is_dir():
            raise ValueError(f"Path is not a directory: {safe}")

        str_path = str(safe)
        with self.SessionLocal() as session:
            fav = session.scalar(
                select(FavoritePath).where(FavoritePath.user_id == user_id, FavoritePath.path == str_path)
            )
            now = utcnow()
            if fav:
                if label is not None:
                    fav.label = label.strip() or safe.name
                fav.updated_at = now
            else:
                max_pos = session.scalar(
                    select(func.coalesce(func.max(FavoritePath.position), 0)).where(FavoritePath.user_id == user_id)
                ) or 0
                fav = FavoritePath(
                    user_id=user_id,
                    path=str_path,
                    label=(label.strip() if label else None) or safe.name,
                    position=max_pos + 1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(fav)
            session.commit()
            session.refresh(fav)
            return {
                "id": fav.id,
                "path": fav.path,
                "label": fav.label,
                "position": fav.position,
                "exists": True,
                "created_at": fav.created_at,
                "updated_at": fav.updated_at,
            }

    def delete_favorite(self, user_id: int, favorite_id: int) -> bool:
        with self.SessionLocal() as session:
            fav = session.get(FavoritePath, favorite_id)
            if fav is None or fav.user_id != user_id:
                raise KeyError(f"Favorite #{favorite_id} not found")
            session.delete(fav)
            session.commit()
            return True

    # ==================== Recent Paths API ====================

    def list_recent_paths(self, user_id: int, limit: int = 20) -> list[dict]:
        with self.SessionLocal() as session:
            rows = list(
                session.scalars(
                    select(RecentPath)
                    .where(RecentPath.user_id == user_id)
                    .order_by(RecentPath.last_used_at.desc())
                    .limit(limit)
                )
            )
            results = []
            for r in rows:
                p = Path(r.path)
                try:
                    safe = require_allowed_path(p, self.settings.allowed_roots)
                    exists = safe.exists() and safe.is_dir()
                except ValueError:
                    exists = False

                if exists:
                    results.append({
                        "id": r.id,
                        "path": r.path,
                        "last_used_at": r.last_used_at,
                        "exists": True,
                    })
            return results

    def record_recent_paths(self, user_id: int, paths: list[str]) -> list[dict]:
        now = utcnow()
        with self.SessionLocal() as session:
            for raw in paths:
                if not raw or not raw.strip():
                    continue
                try:
                    safe = require_allowed_path(raw.strip(), self.settings.allowed_roots)
                    if not safe.exists() or not safe.is_dir():
                        continue
                except ValueError:
                    continue

                str_path = str(safe)
                rec = session.scalar(
                    select(RecentPath).where(RecentPath.user_id == user_id, RecentPath.path == str_path)
                )
                if rec:
                    rec.last_used_at = now
                else:
                    session.add(RecentPath(user_id=user_id, path=str_path, last_used_at=now))

            session.commit()

            # Keep only the latest 20 recent paths per user
            all_recent = list(
                session.scalars(
                    select(RecentPath)
                    .where(RecentPath.user_id == user_id)
                    .order_by(RecentPath.last_used_at.desc())
                )
            )
            if len(all_recent) > 20:
                for excess in all_recent[20:]:
                    session.delete(excess)
                session.commit()

        return self.list_recent_paths(user_id, limit=20)

    # =========================================================================
    # Organizer Profiles Service Methods
    # =========================================================================

    @staticmethod
    def _serialize_organizer_profile(profile: OrganizerProfile) -> dict[str, Any]:
        return {
            "id": profile.id,
            "user_id": profile.user_id,
            "slug": profile.slug,
            "builtin_version": profile.builtin_version,
            "name": profile.name,
            "description": profile.description,
            "root": profile.root,
            "recursive": bool(profile.recursive),
            "image_extensions": json.loads(profile.image_extensions or "[]"),
            "video_extensions": json.loads(profile.video_extensions or "[]"),
            "rename_template": profile.rename_template,
            "statistics_template": profile.statistics_template,
            "preserve_tags": json.loads(profile.preserve_tags or "[]"),
            "cleanup_patterns": json.loads(profile.cleanup_patterns or "[]"),
            "numbering_mode": profile.numbering_mode,
            "numbering_start": profile.numbering_start,
            "numbering_padding": profile.numbering_padding,
            "mtime_mode": profile.mtime_mode,
            "mtime_delay_seconds": profile.mtime_delay_seconds,
            "is_builtin": bool(profile.is_builtin),
            "created_at": profile.created_at.isoformat() if profile.created_at else None,
            "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        }

    def _validate_profile_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("方案名称不能为空")

        root = payload.get("root")
        if root and str(root).strip():
            safe_root = require_allowed_path(str(root).strip(), self.settings.allowed_roots)
            clean_root = str(safe_root)
        else:
            clean_root = None

        if "image_extensions" in payload and payload["image_extensions"] is not None:
            image_extensions = validate_and_normalize_extensions(payload["image_extensions"], "image_extensions")
        else:
            image_extensions = ["jpg", "jpeg", "png", "webp"]

        if "video_extensions" in payload and payload["video_extensions"] is not None:
            video_extensions = validate_and_normalize_extensions(payload["video_extensions"], "video_extensions")
        else:
            video_extensions = ["mp4", "mov", "mkv"]

        rename_template = str(payload.get("rename_template") or "{name}").strip()
        r_errors = validate_template(rename_template, ALLOWED_RENAME_VARS)
        if r_errors:
            raise ValueError(r_errors[0])

        statistics_template = str(payload.get("statistics_template") or "[{images}P {videos}V {size}]").strip()
        s_errors = validate_template(statistics_template, ALLOWED_STATISTICS_VARS)
        if s_errors:
            raise ValueError(s_errors[0])

        cleanup_patterns = payload.get("cleanup_patterns") if "cleanup_patterns" in payload and payload["cleanup_patterns"] is not None else []
        if not isinstance(cleanup_patterns, list):
            raise ValueError("cleanup_patterns 必须为列表")
        c_errors = validate_cleanup_patterns(cleanup_patterns)
        if c_errors:
            raise ValueError(c_errors[0])

        preserve_tags = payload.get("preserve_tags") if "preserve_tags" in payload and payload["preserve_tags"] is not None else []
        if not isinstance(preserve_tags, list):
            raise ValueError("preserve_tags 必须为列表")
        clean_tags = [str(t).strip() for t in preserve_tags if str(t).strip()][:20]

        numbering_mode = str(payload.get("numbering_mode") or "none").strip()
        if numbering_mode not in {"none", "sequential"}:
            raise ValueError("numbering_mode 只支持 'none' 或 'sequential'")

        try:
            numbering_start = max(0, int(payload.get("numbering_start", 1)))
        except (ValueError, TypeError):
            numbering_start = 1

        try:
            numbering_padding = min(10, max(1, int(payload.get("numbering_padding", 3))))
        except (ValueError, TypeError):
            numbering_padding = 3

        mtime_mode = str(payload.get("mtime_mode") or "none").strip()
        if mtime_mode not in {"none", "ordered"}:
            raise ValueError("mtime_mode 只支持 'none' 或 'ordered'")

        raw_mtime_delay = payload.get("mtime_delay_seconds", 2.0)
        if raw_mtime_delay is None:
            raw_mtime_delay = 2.0
        try:
            val = float(raw_mtime_delay)
            if not math.isfinite(val):
                raise ValueError("mtime_delay_seconds 必须为有限数值")
            if val < 0.0 or val > 60.0:
                raise ValueError(f"mtime_delay_seconds 必须在 0 到 60 秒之间，当前值: {val}")
            mtime_delay_seconds = val
        except (ValueError, TypeError) as exc:
            raise ValueError(f"无效的 mtime_delay_seconds (必须在 0 到 60 之间): {exc}") from exc

        return {
            "name": name,
            "description": str(payload.get("description") or "").strip() or None,
            "root": clean_root,
            "recursive": bool(payload.get("recursive", False)),
            "image_extensions": json.dumps(image_extensions),
            "video_extensions": json.dumps(video_extensions),
            "rename_template": rename_template,
            "statistics_template": statistics_template,
            "preserve_tags": json.dumps(clean_tags),
            "cleanup_patterns": json.dumps(cleanup_patterns),
            "numbering_mode": numbering_mode,
            "numbering_start": numbering_start,
            "numbering_padding": numbering_padding,
            "mtime_mode": mtime_mode,
            "mtime_delay_seconds": mtime_delay_seconds,
        }

    def list_organizer_profiles(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 50,
        search: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        with self.SessionLocal() as session:
            query = select(OrganizerProfile).where(
                (OrganizerProfile.user_id == user_id) | (OrganizerProfile.is_builtin.is_(True))
            )
            if search and search.strip():
                kw = f"%{search.strip()}%"
                query = query.where(
                    OrganizerProfile.name.ilike(kw) | OrganizerProfile.description.ilike(kw)
                )

            total = session.scalar(select(func.count()).select_from(query.subquery())) or 0

            # Sort builtin first, then user profiles by updated_at desc, then name
            query = query.order_by(
                OrganizerProfile.is_builtin.desc(),
                OrganizerProfile.updated_at.desc(),
                OrganizerProfile.name.asc(),
            )
            offset = max(0, (page - 1) * page_size)
            profiles = list(session.scalars(query.offset(offset).limit(page_size)))
            return [self._serialize_organizer_profile(p) for p in profiles], total

    def get_organizer_profile(self, profile_id: int, user_id: int) -> dict[str, Any] | None:
        with self.SessionLocal() as session:
            profile = session.get(OrganizerProfile, profile_id)
            if not profile:
                return None
            if not profile.is_builtin and profile.user_id != user_id:
                raise PermissionError("无权访问其他用户的方案")
            return self._serialize_organizer_profile(profile)

    def create_organizer_profile(self, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        validated = self._validate_profile_payload(payload)
        now = utcnow()
        with self.SessionLocal() as session:
            profile = OrganizerProfile(
                user_id=user_id,
                slug=None,
                builtin_version=None,
                is_builtin=False,
                created_at=now,
                updated_at=now,
                **validated,
            )
            session.add(profile)
            session.commit()
            session.refresh(profile)
            return self._serialize_organizer_profile(profile)

    def update_organizer_profile(self, profile_id: int, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self.SessionLocal() as session:
            profile = session.get(OrganizerProfile, profile_id)
            if not profile:
                raise ValueError(f"方案不存在 (id={profile_id})")
            if profile.is_builtin:
                raise ValueError("系统内置方案禁止直接修改配置，请使用复制功能创建个人副本")
            if profile.user_id != user_id:
                raise PermissionError("无权修改其他用户的方案")

            validated = self._validate_profile_payload(payload)
            for k, v in validated.items():
                setattr(profile, k, v)
            profile.updated_at = utcnow()
            session.commit()
            session.refresh(profile)
            return self._serialize_organizer_profile(profile)

    def delete_organizer_profile(self, profile_id: int, user_id: int) -> None:
        with self.SessionLocal() as session:
            profile = session.get(OrganizerProfile, profile_id)
            if not profile:
                raise ValueError(f"方案不存在 (id={profile_id})")
            if profile.is_builtin:
                raise ValueError("系统内置方案禁止删除")
            if profile.user_id != user_id:
                raise PermissionError("无权删除其他用户的方案")
            session.delete(profile)
            session.commit()

    def clone_organizer_profile(self, profile_id: int, user_id: int) -> dict[str, Any]:
        with self.SessionLocal() as session:
            profile = session.get(OrganizerProfile, profile_id)
            if not profile:
                raise ValueError(f"方案不存在 (id={profile_id})")
            if not profile.is_builtin and profile.user_id != user_id:
                raise PermissionError("无权访问该方案")

            existing_names = set(
                session.scalars(
                    select(OrganizerProfile.name).where(OrganizerProfile.user_id == user_id)
                ).all()
            )

            base_name = profile.name
            clone_name = f"{base_name} - 副本"
            if clone_name in existing_names:
                idx = 2
                while f"{base_name} - 副本 {idx}" in existing_names:
                    idx += 1
                clone_name = f"{base_name} - 副本 {idx}"

            now = utcnow()
            cloned = OrganizerProfile(
                user_id=user_id,
                slug=None,
                builtin_version=None,
                is_builtin=False,
                name=clone_name,
                description=profile.description,
                root=profile.root,
                recursive=profile.recursive,
                image_extensions=profile.image_extensions,
                video_extensions=profile.video_extensions,
                rename_template=profile.rename_template,
                statistics_template=profile.statistics_template,
                preserve_tags=profile.preserve_tags,
                cleanup_patterns=profile.cleanup_patterns,
                numbering_mode=profile.numbering_mode,
                numbering_start=profile.numbering_start,
                numbering_padding=profile.numbering_padding,
                mtime_mode=profile.mtime_mode,
                mtime_delay_seconds=profile.mtime_delay_seconds,
                created_at=now,
                updated_at=now,
            )
            session.add(cloned)
            session.commit()
            session.refresh(cloned)
            return self._serialize_organizer_profile(cloned)

    def export_organizer_profile(self, profile_id: int, user_id: int) -> dict[str, Any]:
        with self.SessionLocal() as session:
            profile = session.get(OrganizerProfile, profile_id)
            if not profile:
                raise ValueError(f"方案不存在 (id={profile_id})")
            if not profile.is_builtin and profile.user_id != user_id:
                raise PermissionError("无权导出该方案")

            return {
                "schema_version": 1,
                "profile": {
                    "name": profile.name,
                    "description": profile.description,
                    "root": profile.root,
                    "recursive": bool(profile.recursive),
                    "image_extensions": json.loads(profile.image_extensions or "[]"),
                    "video_extensions": json.loads(profile.video_extensions or "[]"),
                    "rename_template": profile.rename_template,
                    "statistics_template": profile.statistics_template,
                    "preserve_tags": json.loads(profile.preserve_tags or "[]"),
                    "cleanup_patterns": json.loads(profile.cleanup_patterns or "[]"),
                    "numbering_mode": profile.numbering_mode,
                    "numbering_start": profile.numbering_start,
                    "numbering_padding": profile.numbering_padding,
                    "mtime_mode": profile.mtime_mode,
                    "mtime_delay_seconds": profile.mtime_delay_seconds,
                },
            }

    def import_organizer_profile(self, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("导入格式无效")

        if payload.get("schema_version") != 1:
            raise ValueError(f"不支持的 Schema 版本: {payload.get('schema_version')}，仅支持版本 1")

        extra_top_level = set(payload.keys()) - {"schema_version", "profile"}
        if extra_top_level:
            raise ValueError(f"导入数据包含未知顶层字段: {', '.join(sorted(extra_top_level))}")

        p_data = payload.get("profile")
        if not isinstance(p_data, dict):
            raise ValueError("导入缺少有效的 'profile' 对象")

        forbidden_keys = {"id", "user_id", "is_builtin", "slug", "builtin_version", "created_at", "updated_at"}
        found_forbidden = forbidden_keys.intersection(p_data.keys())
        if found_forbidden:
            raise ValueError(f"导入配置包含禁止字段: {', '.join(sorted(found_forbidden))}")

        allowed_keys = {
            "name",
            "description",
            "root",
            "recursive",
            "image_extensions",
            "video_extensions",
            "rename_template",
            "statistics_template",
            "preserve_tags",
            "cleanup_patterns",
            "numbering_mode",
            "numbering_start",
            "numbering_padding",
            "mtime_mode",
            "mtime_delay_seconds",
        }
        unknown_keys = set(p_data.keys()) - allowed_keys
        if unknown_keys:
            raise ValueError(f"导入配置包含未知字段: {', '.join(sorted(unknown_keys))}")

        validated = self._validate_profile_payload(p_data)

        # Disambiguate name if already exists
        with self.SessionLocal() as session:
            existing_names = set(
                session.scalars(
                    select(OrganizerProfile.name).where(OrganizerProfile.user_id == user_id)
                ).all()
            )
            name = validated["name"]
            if name in existing_names:
                idx = 2
                while f"{name} - 导入 {idx}" in existing_names:
                    idx += 1
                validated["name"] = f"{name} - 导入 {idx}"

            now = utcnow()
            imported = OrganizerProfile(
                user_id=user_id,
                slug=None,
                builtin_version=None,
                is_builtin=False,
                created_at=now,
                updated_at=now,
                **validated,
            )
            session.add(imported)
            session.commit()
            session.refresh(imported)
            return self._serialize_organizer_profile(imported)

    def preview_organizer_profile(
        self,
        profile_id: int,
        user_id: int,
        root_override: str | None = None,
        page: int = 1,
        page_size: int = 100,
        only_changed: bool = False,
        only_conflicts: bool = False,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        with self.SessionLocal() as session:
            profile = session.get(OrganizerProfile, profile_id)
            if not profile:
                raise ValueError(f"方案不存在 (id={profile_id})")
            if not profile.is_builtin and profile.user_id != user_id:
                raise PermissionError("无权访问该方案")

            target_root = (root_override or profile.root or "").strip()
            if not target_root:
                raise ValueError("未指定整理根目录，请在请求或配置中提供 root")

            safe_root = require_allowed_path(target_root, self.settings.allowed_roots)

            now = time.time()
            # Clean expired snapshots (> 600s)
            expired_keys = [k for k, v in self._preview_snapshots.items() if now - v.get("created_at", 0) > 600]
            for k in expired_keys:
                self._preview_snapshots.pop(k, None)

            cached = self._preview_snapshots.get(snapshot_id) if snapshot_id else None
            if cached and cached.get("profile_id") == profile.id and cached.get("root") == str(safe_root):
                summary = cached["summary"]
                proposals = cached["proposals"]
                active_snapshot_id = snapshot_id
            else:
                image_extensions = json.loads(profile.image_extensions or "[]")
                video_extensions = json.loads(profile.video_extensions or "[]")
                preserve_tags = json.loads(profile.preserve_tags or "[]")
                cleanup_patterns = json.loads(profile.cleanup_patterns or "[]")

                summary, proposals = generate_organizer_proposals(
                    safe_root,
                    allowed_roots=self.settings.allowed_roots,
                    image_extensions=image_extensions,
                    video_extensions=video_extensions,
                    rename_template=profile.rename_template,
                    statistics_template=profile.statistics_template,
                    preserve_tags=preserve_tags,
                    cleanup_patterns=cleanup_patterns,
                    numbering_mode=profile.numbering_mode,
                    numbering_start=profile.numbering_start,
                    numbering_padding=profile.numbering_padding,
                    mtime_mode=profile.mtime_mode,
                    mtime_delay_seconds=profile.mtime_delay_seconds,
                    recursive=profile.recursive,
                )
                active_snapshot_id = uuid4().hex
                self._preview_snapshots[active_snapshot_id] = {
                    "created_at": now,
                    "profile_id": profile.id,
                    "root": str(safe_root),
                    "summary": summary,
                    "proposals": proposals,
                }

            # Filtering
            filtered = proposals
            if only_changed:
                filtered = [p for p in filtered if p.changed]
            if only_conflicts:
                filtered = [p for p in filtered if p.conflict]

            total = len(filtered)
            start = max(0, (page - 1) * page_size)
            end = start + page_size
            page_proposals = filtered[start:end]

            return {
                "snapshot_id": active_snapshot_id,
                "profile_id": profile.id,
                "profile_name": profile.name,
                "root": str(safe_root),
                "summary": summary,
                "proposals": [p.to_dict() for p in page_proposals],
                "page": page,
                "page_size": page_size,
                "total": total,
            }

    def create_organizer_plan(
        self,
        profile_id: int,
        user_id: int,
        root_override: str | None = None,
        include_touch: bool = True,
    ) -> BatchPlan:
        with self.SessionLocal() as session:
            profile = session.get(OrganizerProfile, profile_id)
            if not profile:
                raise ValueError(f"方案不存在 (id={profile_id})")
            if not profile.is_builtin and profile.user_id != user_id:
                raise PermissionError("无权访问该方案")

            target_root = (root_override or profile.root or "").strip()
            if not target_root:
                raise ValueError("未指定整理根目录，请在请求或配置中提供 root")

            safe_root = require_allowed_path(target_root, self.settings.allowed_roots)

            image_extensions = json.loads(profile.image_extensions or "[]")
            video_extensions = json.loads(profile.video_extensions or "[]")
            preserve_tags = json.loads(profile.preserve_tags or "[]")
            cleanup_patterns = json.loads(profile.cleanup_patterns or "[]")

            summary, proposals = generate_organizer_proposals(
                safe_root,
                allowed_roots=self.settings.allowed_roots,
                image_extensions=image_extensions,
                video_extensions=video_extensions,
                rename_template=profile.rename_template,
                statistics_template=profile.statistics_template,
                preserve_tags=preserve_tags,
                cleanup_patterns=cleanup_patterns,
                numbering_mode=profile.numbering_mode,
                numbering_start=profile.numbering_start,
                numbering_padding=profile.numbering_padding,
                mtime_mode=profile.mtime_mode,
                mtime_delay_seconds=profile.mtime_delay_seconds,
                recursive=profile.recursive,
            )

            if summary["conflicts"] > 0:
                conflict_reasons = [p.conflict_reason for p in proposals if p.conflict and p.conflict_reason]
                raise ValueError(f"存在 {summary['conflicts']} 个冲突项，禁止生成计划: {'; '.join(conflict_reasons[:3])}")

            items, cycle_sources = plan_organizer_operations(
                proposals,
                include_touch=include_touch,
                mtime_mode=profile.mtime_mode,
            )
            if cycle_sources:
                raise ValueError(f"检测到循环重命名依赖，禁止生成计划: {', '.join(sorted(cycle_sources))}")

            if not items:
                raise ValueError("当前没有需要执行的操作")

            plan_kind = f"organizer-{profile.slug or profile.id}"
            plan_name = f"整理计划 - {profile.name}"
            metadata = {
                "is_organizer": True,
                "organizer_profile_id": profile.id,
                "mtime_delay_seconds": profile.mtime_delay_seconds,
            }
            return self.create_plan(name=plan_name, kind=plan_kind, items=items, metadata=metadata)
