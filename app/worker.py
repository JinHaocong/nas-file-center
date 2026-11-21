from __future__ import annotations

import json
import logging
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
from app.scheduler.dispatch import run_scheduler_tick
from app.models import BatchPlanItem, ScanJob, WorkJob, utcnow
from app.tasks.context import JobContext
from app.tasks.handlers import get_handler
from app.tasks.logging import log_task_event
from app.tasks.media_mutation_lock import (
    MediaMutationLockBusy,
    MediaMutationLockUnavailable,
    assert_media_mutation_lock,
    media_mutation_lock,
)
from app.tasks.recovery import (
    acquire_worker_ownership,
    assert_active_worker_lease,
    assert_no_maintenance_reservation,
    claim_next_job,
    generate_worker_id,
    MaintenanceReservationActive,
    recover_interrupted_jobs,
    update_worker_heartbeat,
    work_job_allowed_by_maintenance_reservation,
    WorkerHeartbeatDatabaseBusy,
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


logger = logging.getLogger(__name__)


def _build_incomplete_plan_error_text(
    plan_id: int,
    plan_status: str,
    items: list[BatchPlanItem],
) -> str:
    """Build a concise failure summary without mislabeling unexecuted validated rows."""

    failed_items = [item for item in items if item.state == "failed"]
    if failed_items:
        problem_items = failed_items[:3]
    else:
        problem_items = [item for item in items if item.state != "completed"][:3]

    parts = [f"Batch plan #{plan_id} finished with status {plan_status}"]
    if problem_items:
        parts.extend(
            f"item #{item.sequence} {item.operation}: {item.reason or item.state}"
            for item in problem_items
        )
    else:
        parts.append("inspect plan items for details")

    if failed_items:
        remaining_unexecuted = sum(
            1
            for item in items
            if item.state not in {"completed", "failed"}
        )
        if remaining_unexecuted:
            suffix = "item" if remaining_unexecuted == 1 else "items"
            parts.append(
                f"{remaining_unexecuted} remaining {suffix} were not executed after the fail-closed stop"
            )

    return "; ".join(parts)


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
        with media_mutation_lock(settings):
            return _process_work_job(settings, work_job_id, session_factory, engine, worker_id)
    except MediaMutationLockUnavailable:
        logger.exception("WorkJob %s held because the media mutation lock is unavailable", work_job_id)
        return False


def _process_work_job(
    settings: Settings,
    work_job_id: int,
    session_factory: sessionmaker,
    engine: Any,
    worker_id: str | None,
) -> bool:
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

            if not work_job_allowed_by_maintenance_reservation(session, work):
                session.rollback()
                return False

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
            assert_media_mutation_lock(settings)
            handler.run(work, ctx, settings)

        # Finished cleanly -> completed under active lease
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            now = utcnow()
            if worker_id is not None:
                assert_active_worker_lease(session, worker_id, now=now)

            work = session.get(WorkJob, work_job_id)
            if work and work.status == JobState.RUNNING.value:
                sync_scan_job_status(session, work, "completed", finished_at=now)
                linked_plan = sync_batch_plan_status(
                    session,
                    work,
                    "completed",
                    finished_at=now,
                )

                if (
                    linked_plan is not None
                    and linked_plan.status != "completed"
                ):
                    validate_transition(work.status, JobState.FAILED.value)
                    work.status = JobState.FAILED.value
                    work.finished_at = now
                    work.heartbeat_at = now
                    plan_items = list(
                        session.scalars(
                            select(BatchPlanItem)
                            .where(BatchPlanItem.plan_id == linked_plan.id)
                            .order_by(BatchPlanItem.sequence)
                        )
                    )
                    work.error_text = _build_incomplete_plan_error_text(
                        linked_plan.id,
                        linked_plan.status,
                        plan_items,
                    )
                    work.error_code = "BATCH_PLAN_NOT_COMPLETED"
                    log_task_event(
                        session,
                        job_id=work_job_id,
                        event_type="failed",
                        message=work.error_text,
                        level="error",
                    )
                else:
                    validate_transition(work.status, JobState.COMPLETED.value)
                    work.status = JobState.COMPLETED.value
                    work.finished_at = now
                    work.heartbeat_at = now
                    work.error_text = None
                    work.error_code = None
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
        # SQLITE_BUSY is not a proof of lost ownership: retry quickly instead
        # of waiting another full heartbeat interval. Every real renewal still
        # checks the original 30s lease limit; no expired owner is resurrected.
        retry_interval = max(0.05, min(1.0, self.interval / 3.0))
        wait_seconds = self.interval
        contention_since: float | None = None
        last_busy_log_at = 0.0
        denial_reported = False
        while not self.stop_event.wait(wait_seconds):
            try:
                renewed = update_worker_heartbeat(
                    self.engine, self.session_factory,
                    worker_id=self.worker_id, raise_on_busy=True,
                )
                if not renewed:
                    if not denial_reported:
                        logger.warning(
                            "Worker %s heartbeat rejected: not current owner or lease expired; "
                            "task lease fencing remains active",
                            self.worker_id,
                        )
                    denial_reported = True
                    if self.lease_lost_event is not None:
                        self.lease_lost_event.set()
                else:
                    denial_reported = False
                    if contention_since is not None:
                        logger.info(
                            "Worker %s heartbeat resumed after %.2fs of SQLite writer contention",
                            self.worker_id, time.monotonic() - contention_since,
                        )
                contention_since = None
                wait_seconds = self.interval
            except WorkerHeartbeatDatabaseBusy:
                now = time.monotonic()
                if contention_since is None:
                    contention_since = now
                if now - last_busy_log_at >= 5.0:
                    logger.warning(
                        "Worker %s heartbeat waiting on SQLite writer (%.2fs elapsed); "
                        "will retry promptly, without extending lease",
                        self.worker_id, now - contention_since,
                    )
                    last_busy_log_at = now
                wait_seconds = retry_interval
            except Exception:
                # Unexpected errors are observable and the next heartbeat still
                # enforces the lease fence; never silently hide failures.
                logger.exception("Worker %s heartbeat thread raised an error", self.worker_id)
                wait_seconds = retry_interval


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
        with media_mutation_lock(settings):
            stats = recover_interrupted_jobs(engine, SessionLocal, worker_id=worker_id)
        return stats["recovered_requeued"] + stats["failed_interrupted"] + stats["cancelled"]
    return 0


def _cleanup_transaction_residue_after_recovery(
    settings: Settings,
    session_factory: sessionmaker,
    worker_id: str,
) -> None:
    """Best-effort retirement of NFC-owned terminal transaction metadata."""
    try:
        assert_media_mutation_lock(settings)
        with session_factory() as session:
            assert_no_maintenance_reservation(session)
        from app.quarantine.transaction_residue import cleanup_terminal_transaction_residue

        stats = cleanup_terminal_transaction_residue(
            settings=settings,
            session_factory=session_factory,
            worker_id=worker_id,
        )
        if any(stats.values()):
            logger.info("Retired terminal transaction residue: %s", stats)
    except MaintenanceReservationActive:
        return
    except Exception:
        # Residue cleanup is maintenance only. Unknown or unsafe artifacts are
        # intentionally retained; a cleanup failure must never stop the Worker.
        logger.exception("Terminal transaction residue cleanup failed closed")


def _cleanup_archive_after_recovery(
    settings: Settings, session_factory: sessionmaker, worker_id: str, *, cancelled_only: bool = False,
) -> bool:
    """Finish only registered archive staging cleanup after Worker lease recovery."""
    try:
        assert_media_mutation_lock(settings)
        with session_factory() as session:
            assert_no_maintenance_reservation(session)
        from app.archive_recovery.integration import cleanup_recovery_after_worker_restart
        cleanup_recovery_after_worker_restart(
            settings, session_factory, worker_id, cancelled_only=cancelled_only,
        )
    except MaintenanceReservationActive:
        return False
    except Exception:
        logger.exception("Archive recovery temporary cleanup failed closed")
        return False
    return True


def worker_loop(
    settings: Settings | None = None,
    *,
    poll_seconds: float = 2.0,
    heartbeat_interval: float = 10.0,
    stop_event: threading.Event | None = None,
) -> None:
    settings = settings or get_settings()
    # The optional NAS DAC profile must be proven before SQLite, recovery,
    # scheduler or any media WorkJob can execute. Normal mode is unchanged.
    from app.nas_compat_launcher import verify_optional_worker_runtime
    verify_optional_worker_runtime()
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
    heartbeat_stop_event = threading.Event()
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
    logger.info(
        "Worker started worker_id=%s pid=%s owner_acquired=%s "
        "heartbeat_interval=%.2fs lease_timeout=30s",
        worker_id, os.getpid(), acquired, heartbeat_interval,
    )

    heartbeat_thread = WorkerHeartbeatThread(
        engine,
        SessionLocal,
        worker_id=worker_id,
        interval=heartbeat_interval,
        # Keep heartbeats alive while the current task unwinds after SIGTERM.
        # Stop the heartbeat only when the main Worker loop actually exits.
        stop_event=heartbeat_stop_event,
        lease_lost_event=lease_lost_event,
    )
    heartbeat_thread.start()

    needs_recovery = acquired
    needs_archive_recovery = True
    last_scheduler_tick_minute = None

    try:
        while not stop_event.is_set():
            if lease_lost_event.is_set():
                logger.warning(
                    "Worker %s released task ownership after a confirmed lease denial; "
                    "new ownership must be acquired before any further work",
                    worker_id,
                )
                acquired = False
                lease_lost_event.clear()

            if not acquired:
                acquired = acquire_worker_ownership(engine, SessionLocal, worker_id=worker_id)
                if not acquired:
                    stop_event.wait(poll_seconds)
                    continue
                needs_recovery = True

            try:
                with media_mutation_lock(settings, blocking=False):
                    recovered_this_cycle = needs_recovery
                    if needs_recovery:
                        stats = recover_interrupted_jobs(engine, SessionLocal, worker_id=worker_id)
                        if any(stats.values()):
                            logger.warning("Worker %s recovered interrupted tasks: %s", worker_id, stats)
                        _cleanup_transaction_residue_after_recovery(settings, SessionLocal, worker_id)
                        needs_archive_recovery = not _cleanup_archive_after_recovery(
                            settings, SessionLocal, worker_id,
                        )
                        needs_recovery = False

                    scheduler_now = utcnow()
                    scheduler_minute = scheduler_now.replace(second=0, microsecond=0)
                    if scheduler_minute != last_scheduler_tick_minute:
                        # This also retires empty, inode-bound output directories
                        # from archive jobs cancelled through the API between ticks.
                        if not recovered_this_cycle:
                            needs_archive_recovery = not _cleanup_archive_after_recovery(
                                settings, SessionLocal, worker_id, cancelled_only=not needs_archive_recovery,
                            )
                        # Failed ticks are retryable. ScheduleRun's slot identity
                        # provides durable duplicate-dispatch fencing.
                        try:
                            run_scheduler_tick(
                                SessionLocal, settings, owner=worker_id, now_utc=scheduler_now,
                            )
                        except Exception:
                            logger.exception(
                                "Scheduler tick failed for %s; retrying within the current minute",
                                scheduler_minute.isoformat(),
                            )
                        else:
                            last_scheduler_tick_minute = scheduler_minute

                    claimed_id = claim_next_job(engine, SessionLocal, worker_id=worker_id)
                    if claimed_id is not None:
                        success = process_work_job(
                            settings, claimed_id, session_factory=SessionLocal,
                            engine=engine, worker_id=worker_id,
                        )
                        if not success:
                            acquired = False
                        else:
                            _cleanup_transaction_residue_after_recovery(settings, SessionLocal, worker_id)
                            if needs_archive_recovery:
                                needs_archive_recovery = not _cleanup_archive_after_recovery(
                                    settings, SessionLocal, worker_id,
                                )
                        continue
            except JobLeaseLost:
                acquired = False
                continue
            except MediaMutationLockBusy:
                # A live filesystem holder may outlast its database lease.
                pass
            except MediaMutationLockUnavailable:
                logger.exception("Worker %s held because the media mutation lock is unavailable", worker_id)
            except Exception:
                logger.exception("Worker %s could not complete a work cycle", worker_id)
            stop_event.wait(poll_seconds)
    finally:
        logger.info("Worker stopping worker_id=%s pid=%s", worker_id, os.getpid())
        stop_event.set()
        heartbeat_stop_event.set()
        heartbeat_thread.join(timeout=1.0)


if __name__ == "__main__":
    # Keep normal application logs at WARNING, but record Worker lifecycle
    # events and successful heartbeat recovery at INFO for NAS diagnostics.
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logger.setLevel(logging.INFO)
    worker_loop()
