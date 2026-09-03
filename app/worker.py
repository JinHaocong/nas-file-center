from __future__ import annotations

import json
from pathlib import Path
import time

from sqlalchemy import delete, select

from app.config import Settings, get_settings
from app.db import create_engine_and_session, init_db
from app.models import DuplicateFile, DuplicateGroup, ScanJob, WorkJob, utcnow
from app.path_safety import require_allowed_path
from app.scanners.fclones import build_group_command, run_scan
from app.scanners.parser import parse_fclones_report


def _containing_root(path: Path, roots: list[Path]) -> tuple[int, Path] | None:
    matches = [(idx, root) for idx, root in enumerate(roots) if path == root or path.is_relative_to(root)]
    if not matches:
        return None
    return max(matches, key=lambda pair: len(pair[1].parts))


def process_work_job(settings: Settings, work_job_id: int) -> None:
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(
        engine,
        db_path=settings.database_path,
        backups_dir=settings.backups_dir,
        initial_admin_username=settings.initial_admin_username,
        initial_admin_password=settings.initial_admin_password,
    )
    with SessionLocal() as session:
        work = session.get(WorkJob, work_job_id)
        if work is None:
            raise KeyError(work_job_id)
        state = json.loads(work.state_json)
        if work.kind == "index-root":
            work.status = "running"
            work.started_at = utcnow()
            session.commit()
            root = state["root"]
            try:
                from app.service import FileCenterService
                result = FileCenterService(settings).reindex_root(root)
                work = session.get(WorkJob, work_job_id)
                work.status = "completed"
                work.finished_at = utcnow()
                work.progress_current = result["files"] + result["folders"]
                work.progress_total = work.progress_current
                work.state_json = json.dumps({**state, "result": result}, ensure_ascii=False)
                work.error_text = None
                session.commit()
            except Exception as exc:
                session.rollback()
                work = session.get(WorkJob, work_job_id)
                work.status = "failed"
                work.finished_at = utcnow()
                work.error_text = str(exc)
                session.commit()
                raise
            return
        if work.kind != "fclones-scan":
            raise ValueError(f"Unsupported work job kind: {work.kind}")
        scan = session.get(ScanJob, int(state["scan_job_id"]))
        if scan is None:
            raise ValueError("scan job missing")
        roots = [require_allowed_path(p, settings.allowed_roots) for p in state["roots"]]
        now = utcnow()
        work.status = "running"
        work.started_at = now
        scan.status = "running"
        scan.started_at = now
        session.commit()

    try:
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
        report_path = settings.reports_dir / f"scan-{state['scan_job_id']}.json"
        completed = run_scan(command, report_path=report_path, home_dir=settings.fclones_home)
    except Exception as exc:
        with SessionLocal() as session:
            now = utcnow()
            work = session.get(WorkJob, work_job_id)
            scan = session.get(ScanJob, int(state["scan_job_id"]))
            if work:
                work.status = "failed"
                work.finished_at = now
                work.error_text = str(exc)
            if scan:
                scan.status = "failed"
                scan.finished_at = now
                scan.error_text = str(exc)
            session.commit()
        raise

    with SessionLocal() as session:
        work = session.get(WorkJob, work_job_id)
        scan = session.get(ScanJob, int(state["scan_job_id"]))
        if completed.returncode != 0:
            now = utcnow()
            message = completed.stderr[-8000:] if completed.stderr else f"fclones exit {completed.returncode}"
            work.status = "failed"
            work.finished_at = now
            work.error_text = message
            scan.status = "failed"
            scan.finished_at = now
            scan.error_text = message
            session.commit()
            return

        try:
            parsed_groups = parse_fclones_report(report_path)
            session.execute(delete(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan.id))
            session.flush()
            total_groups = total_files = reclaimable = 0
            for parsed in parsed_groups:
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
                if len(members) < 2:
                    continue
                group = DuplicateGroup(
                    scan_job_id=scan.id,
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

            now = utcnow()
            scan.status = "completed"
            scan.finished_at = now
            scan.raw_report_path = str(report_path)
            scan.total_groups = total_groups
            scan.total_files_in_groups = total_files
            scan.reclaimable_bytes = reclaimable
            scan.error_text = None
            work.status = "completed"
            work.finished_at = now
            work.progress_current = total_groups
            work.progress_total = total_groups
            work.error_text = None
            session.commit()
        except Exception as exc:
            session.rollback()
            now = utcnow()
            work = session.get(WorkJob, work_job_id)
            scan = session.get(ScanJob, int(state["scan_job_id"]))
            work.status = "failed"
            work.finished_at = now
            work.error_text = str(exc)
            scan.status = "failed"
            scan.finished_at = now
            scan.error_text = str(exc)
            session.commit()
            raise


def recover_running_jobs(settings: Settings) -> int:
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(
        engine,
        db_path=settings.database_path,
        backups_dir=settings.backups_dir,
        initial_admin_username=settings.initial_admin_username,
        initial_admin_password=settings.initial_admin_password,
    )
    with SessionLocal() as session:
        jobs = list(session.scalars(select(WorkJob).where(WorkJob.status == "running")))
        for job in jobs:
            job.status = "queued"
        session.commit()
        return len(jobs)


def worker_loop(settings: Settings | None = None, *, poll_seconds: float = 2.0) -> None:
    settings = settings or get_settings()
    recover_running_jobs(settings)
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(
        engine,
        db_path=settings.database_path,
        backups_dir=settings.backups_dir,
        initial_admin_username=settings.initial_admin_username,
        initial_admin_password=settings.initial_admin_password,
    )
    while True:
        with SessionLocal() as session:
            job = session.scalar(select(WorkJob).where(WorkJob.status == "queued").order_by(WorkJob.id).limit(1))
            job_id = job.id if job else None
        if job_id is None:
            time.sleep(poll_seconds)
            continue
        process_work_job(settings, job_id)


if __name__ == "__main__":
    worker_loop()
