from __future__ import annotations

import json
import time
from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models import TaskLock, WorkJob, utcnow
from app.tasks.logging import log_task_event
from app.tasks.state_machine import (
    JobCancelRequested,
    JobLeaseLost,
    JobPauseRequested,
    JobState,
    validate_transition,
)


MAX_CHECKPOINT_SIZE_BYTES = 64 * 1024  # 64 KB limit


class JobContext:
    def __init__(
        self,
        engine: Any,
        session_factory: sessionmaker,
        job_id: int,
        worker_id: str | None = None,
    ):
        self.engine = engine
        self.SessionLocal = session_factory
        self.job_id = job_id
        self.worker_id = worker_id
        self._last_progress_percent: float | None = None
        self._last_progress_event_time: float = 0.0

    def log(
        self,
        event_type: str,
        message: str,
        level: str = "info",
        context: dict | None = None,
    ) -> None:
        with self.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            now = utcnow()
            if self.worker_id is not None:
                from app.tasks.recovery import assert_active_worker_lease
                assert_active_worker_lease(session, self.worker_id, now=now)

            log_task_event(
                session,
                job_id=self.job_id,
                event_type=event_type,
                message=message,
                level=level,
                context=context,
            )
            session.commit()

    def checkpoint(
        self,
        *,
        progress_current: int | None = None,
        progress_total: int | None = None,
        progress_message: str | None = None,
        checkpoint_data: dict[str, Any] | None = None,
    ) -> None:
        """
        Safe execution checkpoint boundary:
        1. Validates checkpoint data schema and size limit
        2. Validates progress bounds (non-negative, current <= total)
        3. Refreshes job state from database
        4. Checks cancel requests -> transitions to cancelled and raises JobCancelRequested
        5. Checks pause requests -> saves checkpoint, transitions to paused and raises JobPauseRequested
        6. Updates progress, heartbeat, checkpoint data and commits
        """
        if progress_total is not None and progress_total < 0:
            raise ValueError("progress_total must be non-negative")
        if progress_current is not None and progress_current < 0:
            raise ValueError("progress_current must be non-negative")

        serialized_checkpoint = None
        if progress_current is not None and progress_current < 0:
            raise ValueError("progress_current must be non-negative")
        if progress_total is not None and progress_total < 0:
            raise ValueError("progress_total must be non-negative")

        if checkpoint_data is not None:
            if not isinstance(checkpoint_data, dict):
                raise ValueError("checkpoint_data must be a dictionary")
            if "schema_version" not in checkpoint_data:
                raise ValueError("checkpoint_data must contain 'schema_version'")
            serialized_checkpoint = json.dumps(checkpoint_data, ensure_ascii=False)
            if len(serialized_checkpoint.encode("utf-8")) > MAX_CHECKPOINT_SIZE_BYTES:
                raise ValueError(
                    f"checkpoint_data exceeds maximum allowed size of {MAX_CHECKPOINT_SIZE_BYTES} bytes"
                )

        with self.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            now = utcnow()
            # 0. Check Worker Lease Fencing
            if self.worker_id is not None:
                from app.tasks.recovery import assert_active_worker_lease
                assert_active_worker_lease(session, self.worker_id, now=now)

            job = session.get(WorkJob, self.job_id)
            if job is None:
                raise KeyError(f"Job {self.job_id} not found")

            # 1. Check Cancel
            if job.cancel_requested_at is not None or job.status == JobState.CANCEL_REQUESTED.value:
                if job.status == JobState.RUNNING.value:
                    validate_transition(job.status, JobState.CANCEL_REQUESTED.value)
                    job.status = JobState.CANCEL_REQUESTED.value
                validate_transition(job.status, JobState.CANCELLED.value)
                job.status = JobState.CANCELLED.value
                job.finished_at = now
                from app.tasks.sync import sync_scan_job_status
                sync_scan_job_status(
                    session,
                    job,
                    "cancelled",
                    finished_at=now,
                    error_text="Cancelled by user",
                    cleanup_partial_results=True,
                )
                log_task_event(
                    session,
                    job_id=self.job_id,
                    event_type="cancelled",
                    message="Job cancelled at checkpoint boundary",
                    level="warning",
                )
                session.commit()
                raise JobCancelRequested("Job cancelled by user request")

            def _apply_progress(target_job: WorkJob, p_curr: int | None, p_tot: int | None, p_msg: str | None) -> None:
                saved_curr = target_job.progress_current or 0
                if p_tot is not None:
                    if p_tot < saved_curr:
                        raise ValueError(
                            f"progress_total ({p_tot}) cannot be smaller than saved progress_current ({saved_curr})"
                        )
                    target_job.progress_total = p_tot

                if p_curr is not None:
                    eff_total = target_job.progress_total
                    if eff_total is not None and eff_total > 0 and p_curr > eff_total:
                        raise ValueError(
                            f"progress_current ({p_curr}) cannot exceed progress_total ({eff_total})"
                        )
                    target_job.progress_current = max(saved_curr, p_curr)
                elif target_job.progress_total and target_job.progress_total > 0:
                    if saved_curr > target_job.progress_total:
                        raise ValueError(
                            f"progress_current ({saved_curr}) cannot exceed progress_total ({target_job.progress_total})"
                        )

                if p_msg is not None:
                    target_job.progress_message = p_msg

            # 2. Check Pause
            if job.pause_requested_at is not None:
                validate_transition(job.status, JobState.PAUSED.value)
                job.status = JobState.PAUSED.value
                job.finished_at = None
                if serialized_checkpoint is not None:
                    job.checkpoint_json = serialized_checkpoint
                _apply_progress(job, progress_current, progress_total, progress_message)

                log_task_event(
                    session,
                    job_id=self.job_id,
                    event_type="paused",
                    message="Job safely paused at checkpoint boundary",
                    level="info",
                    context=checkpoint_data,
                )
                session.commit()
                raise JobPauseRequested("Job paused by user request")

            # 3. Normal progress & heartbeat update
            job.heartbeat_at = now
            _apply_progress(job, progress_current, progress_total, progress_message)
            if serialized_checkpoint is not None:
                job.checkpoint_json = serialized_checkpoint

            # Throttled progress event (write if percent delta >= 1% or time delta >= 10s)
            curr = job.progress_current or 0
            tot = job.progress_total or 0
            if tot > 0:
                percent = round((curr / tot) * 100, 1)
                now_ts = time.time()
                should_log_progress = (
                    self._last_progress_percent is None
                    or (percent - self._last_progress_percent >= 1.0)
                    or (now_ts - self._last_progress_event_time >= 10.0)
                )
                if should_log_progress:
                    self._last_progress_percent = percent
                    self._last_progress_event_time = now_ts
                    log_task_event(
                        session,
                        job_id=self.job_id,
                        event_type="progress",
                        message=job.progress_message or f"Progress: {percent}% ({curr}/{tot})",
                        level="info",
                        context={"percent": percent, "current": curr, "total": tot},
                    )

            session.commit()
