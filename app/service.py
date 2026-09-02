from __future__ import annotations

from datetime import datetime, timezone
import json
from uuid import uuid4
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.batch.plans import OperationItem
from app.batch.rename import RenameRule, build_rename_plan
from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.execution.executor import execute_item
from app.execution.verifier import verify_duplicate_pair
from app.indexing.indexer import IndexedEntry, iter_root, scan_root
from app.indexing.matcher import match_entries
from app.models import AuditEvent, BatchPlan, BatchPlanItem, DuplicateFile, DuplicateGroup, IndexedPath, ScanJob, WorkJob, utcnow
from app.path_safety import require_allowed_path
from app.organizers.shaonv import build_stat_rename_proposals
from app.planning.engine import CandidateFile, CandidateGroup, generate_plan


class FileCenterService:
    def __init__(self, settings: Settings):
        self.settings = settings
        for directory in (settings.config_dir, settings.reports_dir, settings.backups_dir, settings.logs_dir, settings.fclones_home):
            directory.mkdir(parents=True, exist_ok=True)
        self.engine, self.SessionLocal = create_engine_and_session(settings.database_path)
        init_db(self.engine)



    def reindex_root(self, root: str, *, batch_size: int = 1000) -> dict:
        safe_root = require_allowed_path(root, self.settings.allowed_roots)
        if not safe_root.is_dir():
            raise ValueError(f"Not a directory: {safe_root}")
        root_key = str(safe_root)
        generation = uuid4().hex
        files = folders = 0
        batch: list[dict] = []

        def flush(session):
            nonlocal batch
            if not batch:
                return
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

        with self.SessionLocal() as session:
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
                    flush(session)
            flush(session)
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


    def shaonv_preview(self, root: str) -> list[dict]:
        proposals = build_stat_rename_proposals(root, allowed_roots=self.settings.allowed_roots)
        return [{"source": str(p.source), "target": str(p.target)} for p in proposals]

    def rename_preview(self, paths: list[str], rule: RenameRule):
        proposals = build_rename_plan(paths, rule=rule, allowed_roots=self.settings.allowed_roots)
        return [{"source": str(p.source), "target": str(p.target)} for p in proposals]

    def create_plan(self, *, name: str, kind: str, items: list[dict]) -> BatchPlan:
        with self.SessionLocal() as session:
            plan = BatchPlan(name=name, kind=kind, status="draft", expected_changes=len(items), metadata_json="{}")
            session.add(plan)
            session.flush()
            for sequence, raw in enumerate(items, 1):
                source = require_allowed_path(raw["source"], self.settings.allowed_roots)
                if not source.exists():
                    raise ValueError(f"Source does not exist: {source}")
                target = raw.get("target")
                keep = raw.get("keep")
                protected_dir = raw.get("protected_dir")
                target_path = str(require_allowed_path(target, self.settings.allowed_roots)) if target else None
                keep_path = str(require_allowed_path(keep, self.settings.allowed_roots)) if keep else None
                metadata = {"protected_dir": str(require_allowed_path(protected_dir, self.settings.allowed_roots))} if protected_dir else {}
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
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
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
            if plan.status not in {"frozen", "ready", "partial"}:
                raise ValueError(f"Plan must be frozen before execution, current status={plan.status}")
            plan.status = "executing"
            session.commit()

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

    def plan_detail(self, plan_id: int) -> dict:
        with self.SessionLocal() as session:
            plan = session.get(BatchPlan, plan_id)
            if plan is None:
                raise KeyError(plan_id)
            rows = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id).order_by(BatchPlanItem.sequence)))
            return {
                "id": plan.id,
                "name": plan.name,
                "kind": plan.kind,
                "status": plan.status,
                "items": [
                    {"id": r.id, "sequence": r.sequence, "operation": r.operation, "source": r.source_path, "target": r.target_path, "keep": r.keep_path, "state": r.state, "reason": r.reason}
                    for r in rows
                ],
            }
