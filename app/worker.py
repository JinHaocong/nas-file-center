from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import threading
import time
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.db import create_engine_and_session, init_db
from app.models import ScanJob, WorkJob, utcnow
from app.tasks.context import JobContext
from app.tasks.handlers import get_handler
from app.tasks.logging import log_task_event
from app.tasks.recovery import (
    acquire_worker_ownership,
    assert_active_worker_lease,
    claim_next_job,
    generate_worker_id,
    recover_interrupted_jobs,
    update_worker_heartbeat,
)
from app.tasks.state_machine import (
    JobCancelRequested,
    JobLeaseLost,
    JobPauseRequested,
    JobState,
    TERMINAL_STATES,
    validate_transition,
)
from app.tasks.sync import sync_batch_plan_status, sync_scan_job_status


def process_work_job(
    settings: Settings,
    work_job_id: int,
    session_factory: sessionmaker | None = None,
    engine: Any = None,
    worker_id: str | None = None,
) -> bool:
    if session_factory is None or engine is None:
        engine, session_factory = create_engine_and_session(settings.database_path)
        init_db(
            engine,
            db_path=settings.database_path,
            backups_dir=settings.backups_dir,
            initial_admin_username=settings.initial_admin_username,
            initial_admin_password=settings.initial_admin_password,
        )

    try:
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            now = utcnow()
            if worker_id is not None:
                assert_active_worker_lease(session, worker_id, now=now)

            work = session.get(WorkJob, work_job_id)
            if work is None:
                session.rollback()
                return False

            job_type = work.kind

            # Worker Preflight
            if work.status == JobState.CANCEL_REQUESTED.value:
                validate_transition(work.status, JobState.CANCELLED.value)
                work.status = JobState.CANCELLED.value
                work.finished_at = now
                work.error_text = "Cancelled by user"
                sync_scan_job_status(
                    session,
                    work,
                    "cancelled",
                    finished_at=now,
                    error_text="Cancelled by user",
                    cleanup_partial_results=True,
                )
                sync_batch_plan_status(
                    session,
                    work,
                    "cancelled",
                    finished_at=now,
                    error_text="Cancelled by user",
                )
                log_task_event(
                    session,
                    job_id=work_job_id,
                    event_type="cancelled",
                    message=f"Job #{work_job_id} cancelled prior to handler execution",
                    level="warning",
                )
                session.commit()
                return True

            if work.status in TERMINAL_STATES or work.status == JobState.PAUSED.value:
                session.rollback()
                return True

            if work.status == JobState.QUEUED.value:
                validate_transition(work.status, JobState.RUNNING.value)
                work.status = JobState.RUNNING.value
                work.started_at = work.started_at or now

            sync_scan_job_status(session, work, "running", started_at=work.started_at)
            sync_batch_plan_status(session, work, "running", started_at=work.started_at)
            work.heartbeat_at = now
            log_task_event(
                session,
                job_id=work_job_id,
                event_type="started",
                message=f"Job #{work_job_id} ({job_type}) started",
                level="info",
            )
            session.commit()

        handler = get_handler(job_type)
        if handler is None:
            with session_factory() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                now = utcnow()
                if worker_id is not None:
                    assert_active_worker_lease(session, worker_id, now=now)

                work = session.get(WorkJob, work_job_id)
                if work:
                    work.status = JobState.FAILED.value
                    work.error_code = "UNKNOWN_JOB_TYPE"
                    work.error_text = f"Unsupported work job kind: {job_type}"
                    work.finished_at = now
                    log_task_event(
                        session,
                        job_id=work_job_id,
                        event_type="failed",
                        message=f"Unknown job type '{job_type}'",
                        level="error",
                        context={"error_code": "UNKNOWN_JOB_TYPE"},
                    )
                    sync_scan_job_status(
                        session,
                        work,
                        "failed",
                        finished_at=now,
                        error_text=work.error_text,
                        cleanup_partial_results=True,
                    )
                    sync_batch_plan_status(
                        session,
                        work,
                        "failed",
                        finished_at=now,
                        error_text=work.error_text,
                    )
                    session.commit()
            return False

        ctx = JobContext(engine, session_factory, work_job_id, worker_id=worker_id)

        with session_factory() as session:
            work = session.get(WorkJob, work_job_id)
            handler.run(work, ctx, settings)

        # Finished cleanly -> completed under active lease
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            now = utcnow()
            if worker_id is not None:
                assert_active_worker_lease(session, worker_id, now=now)

            work = session.get(WorkJob, work_job_id)
            if work and work.status == JobState.RUNNING.value:
                validate_transition(work.status, JobState.COMPLETED.value)
                work.status = JobState.COMPLETED.value
                work.finished_at = now
                work.heartbeat_at = now
                work.error_text = None
                work.error_code = None

                sync_scan_job_status(session, work, "completed", finished_at=now)
                sync_batch_plan_status(session, work, "completed", finished_at=now)

                log_task_event(
                    session,
                    job_id=work_job_id,
                    event_type="completed",
                    message=f"Job #{work_job_id} completed successfully",
                    level="info",
                )
                session.commit()
            elif work and work.status == JobState.CANCEL_REQUESTED.value:
                validate_transition(work.status, JobState.CANCELLED.value)
                work.status = JobState.CANCELLED.value
                work.finished_at = now
                work.heartbeat_at = now
                work.error_text = "Cancelled by user"

                sync_scan_job_status(
                    session,
                    work,
                    "cancelled",
                    finished_at=now,
                    error_text="Cancelled by user",
                    cleanup_partial_results=True,
                )
                sync_batch_plan_status(
                    session,
                    work,
                    "cancelled",
                    finished_at=now,
                    error_text="Cancelled by user",
                )

                log_task_event(
                    session,
                    job_id=work_job_id,
                    event_type="cancelled",
                    message=f"Job #{work_job_id} cancelled (cancel requested prior to finalization)",
                    level="warning",
                )
                session.commit()
        return True

    except JobPauseRequested:
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            work = session.get(WorkJob, work_job_id)
            if work:
                sync_batch_plan_status(session, work, "paused")
                session.commit()
        return True
    except JobCancelRequested:
        # Job safely cancelled at checkpoint boundary. Sync ScanJob if applicable under active lease.
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            now = utcnow()
            if worker_id is not None:
                try:
                    assert_active_worker_lease(session, worker_id, now=now)
                except JobLeaseLost:
                    return False

            work = session.get(WorkJob, work_job_id)
            if work:
                sync_scan_job_status(
                    session,
                    work,
                    "cancelled",
                    finished_at=now,
                    error_text="Cancelled by user",
                    cleanup_partial_results=True,
                )
                sync_batch_plan_status(
                    session,
                    work,
                    "cancelled",
                    finished_at=now,
                    error_text="Cancelled by user",
                )
                session.commit()
        return True
    except JobLeaseLost:
        # Worker lease lost; another worker may have taken ownership or recovered this job.
        # Surrender immediately without mutating WorkJob status or database.
        return False
    except Exception as exc:
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            now = utcnow()
            if worker_id is not None:
                try:
                    assert_active_worker_lease(session, worker_id, now=now)
                except JobLeaseLost:
                    # Stale worker MUST NOT mutate database!
                    return False

            work = session.get(WorkJob, work_job_id)
            if work and work.status not in (JobState.CANCELLED.value, JobState.PAUSED.value):
                work.status = JobState.FAILED.value
                work.finished_at = now
                work.error_text = str(exc)
                work.error_code = getattr(exc, "error_code", "EXECUTION_ERROR")
                log_task_event(
                    session,
                    job_id=work_job_id,
                    event_type="failed",
                    message=f"Job #{work_job_id} failed: {exc}",
                    level="error",
                    context={"error": str(exc)},
                )
                sync_scan_job_status(
                    session,
                    work,
                    "failed",
                    finished_at=now,
                    error_text=str(exc),
                    cleanup_partial_results=True,
                )
                sync_batch_plan_status(
                    session,
                    work,
                    "failed",
                    finished_at=now,
                    error_text=str(exc),
                )
                session.commit()
        return False


class WorkerHeartbeatThread(threading.Thread):
    def __init__(
        self,
        engine: Any,
        session_factory: sessionmaker,
        worker_id: str,
        interval: float = 10.0,
        stop_event: threading.Event | None = None,
        lease_lost_event: threading.Event | None = None,
    ):
        super().__init__(name="WorkerHeartbeat", daemon=True)
        self.engine = engine
        self.session_factory = session_factory
        self.worker_id = worker_id
        self.interval = interval
        self.stop_event = stop_event or threading.Event()
        self.lease_lost_event = lease_lost_event

    def run(self) -> None:
        while not self.stop_event.is_set():
            if self.stop_event.wait(self.interval):
                break
            try:
                renewed = update_worker_heartbeat(self.engine, self.session_factory, worker_id=self.worker_id)
                if not renewed and self.lease_lost_event is not None:
                    self.lease_lost_event.set()
            except Exception:
                pass


def recover_running_jobs(settings: Settings) -> int:
    """Legacy compatibility function for recovering running jobs on startup."""
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(
        engine,
        db_path=settings.database_path,
        backups_dir=settings.backups_dir,
        initial_admin_username=settings.initial_admin_username,
        initial_admin_password=settings.initial_admin_password,
    )
    worker_id = generate_worker_id()
    if acquire_worker_ownership(engine, SessionLocal, worker_id=worker_id):
        stats = recover_interrupted_jobs(engine, SessionLocal, worker_id=worker_id)
        return stats["recovered_requeued"] + stats["failed_interrupted"] + stats["cancelled"]
    return 0


def worker_loop(
    settings: Settings | None = None,
    *,
    poll_seconds: float = 2.0,
    heartbeat_interval: float = 10.0,
    stop_event: threading.Event | None = None,
) -> None:
    settings = settings or get_settings()
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(
        engine,
        db_path=settings.database_path,
        backups_dir=settings.backups_dir,
        initial_admin_username=settings.initial_admin_username,
        initial_admin_password=settings.initial_admin_password,
    )

    worker_id = generate_worker_id()
    stop_event = stop_event or threading.Event()
    lease_lost_event = threading.Event()

    def _sig_handler(signum, frame):
        if stop_event:
            stop_event.set()

    try:
        signal.signal(signal.SIGTERM, _sig_handler)
        signal.signal(signal.SIGINT, _sig_handler)
    except (ValueError, AttributeError):
        pass

    acquired = acquire_worker_ownership(engine, SessionLocal, worker_id=worker_id)

    heartbeat_thread = WorkerHeartbeatThread(
        engine,
        SessionLocal,
        worker_id=worker_id,
        interval=heartbeat_interval,
        stop_event=stop_event,
        lease_lost_event=lease_lost_event,
    )
    heartbeat_thread.start()

    if acquired:
        recover_interrupted_jobs(engine, SessionLocal, worker_id=worker_id)

    try:
        while True:
            if stop_event.is_set():
                break

            if lease_lost_event.is_set():
                acquired = False
                lease_lost_event.clear()

            if not acquired:
                acquired = acquire_worker_ownership(engine, SessionLocal, worker_id=worker_id)
                if not acquired:
                    time.sleep(poll_seconds)
                    continue
                recover_interrupted_jobs(engine, SessionLocal, worker_id=worker_id)

            try:
                claimed_id = claim_next_job(engine, SessionLocal, worker_id=worker_id)
            except JobLeaseLost:
                acquired = False
                continue

            if claimed_id is None:
                time.sleep(poll_seconds)
                continue

            try:
                success = process_work_job(
                    settings,
                    claimed_id,
                    session_factory=SessionLocal,
                    engine=engine,
                    worker_id=worker_id,
                )
                if success is False:
                    acquired = False
            except JobLeaseLost:
                acquired = False
            except Exception:
                # Individual job failures do not terminate the worker container
                pass
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=1.0)


if __name__ == "__main__":
    worker_loop()
