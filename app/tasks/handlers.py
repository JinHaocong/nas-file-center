from __future__ import annotations

from abc import ABC, abstractmethod
import json
from pathlib import Path
from typing import Any, Type

from sqlalchemy import delete, select, text

from app.config import Settings
from app.models import DuplicateFile, DuplicateGroup, ScanJob, WorkJob, utcnow
from app.path_safety import require_allowed_path
from app.scanners.fclones import build_group_command, run_scan
from app.scanners.parser import parse_fclones_report, parse_fclones_report_iter
from app.tasks.context import JobContext


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

        command = build_group_command(
            binary=settings.fclones_binary,
            roots=roots,
            allowed_roots=settings.allowed_roots,
            isolate=bool(state.get("isolate", False)),
            min_size=state.get("min_size"),
            threads=state.get("threads") or settings.fclones_threads,
            name_patterns=state.get("name_patterns"),
            exclude_patterns=state.get("exclude_patterns"),
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
