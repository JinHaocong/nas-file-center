from datetime import datetime
import inspect
import json
from typing import Any
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models import ScanJob, TaskEvent, WorkJob, WorkerState, utcnow
from app.tasks.handlers import get_job_capabilities
from app.tasks.logging import log_task_event
from app.tasks.recovery import compute_worker_status
from app.tasks.state_machine import (
    JobState,
    JobTransitionError,
    TERMINAL_STATES,
    validate_transition,
)
from app.tasks.sync import sync_scan_job_status

RETRY_WHITELISTS: dict[str, set[str]] = {
    "index-root": {"root"},
    "fclones-scan": {
        "scan_job_id",
        "roots",
        "isolate",
        "min_size",
        "name_patterns",
        "exclude_patterns",
    },
    "batch-plan-execute": {"plan_id"},
}


def filter_retry_payload(kind: str, state_json: str | None) -> str:
    if not state_json:
        return "{}"
    try:
        data = json.loads(state_json)
        if not isinstance(data, dict):
            return "{}"
    except Exception:
        return "{}"

    allowed = RETRY_WHITELISTS.get(kind)
    if allowed is not None:
        filtered = {k: v for k, v in data.items() if k in allowed}
    else:
        denied = {
            "allow_mutation",
            "allow_delete",
            "authorization",
            "auth",
            "token",
            "password",
            "secret",
            "unexpected",
        }
        filtered = {k: v for k, v in data.items() if k.lower() not in denied}
    return json.dumps(filtered, ensure_ascii=False)


def format_task(job: WorkJob) -> dict:
    caps = get_job_capabilities(job.kind)
    curr = job.progress_current or 0
    tot = job.progress_total or 0
    percent = round((curr / tot) * 100, 1) if tot > 0 else None
    if percent is not None:
        percent = min(100.0, max(0.0, percent))

    return {
        "id": job.id,
        "job_type": job.kind,
        "status": job.status,
        "capabilities": caps,
        "progress": {
            "current": curr,
            "total": tot,
            "message": job.progress_message,
            "percent": percent,
        },
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        "error": job.error_text,
        "error_code": job.error_code,
        "retry_of": job.retry_of,
    }


def atomic_task_transition(
    session_factory: sessionmaker,
    task_id: int,
    transition_fn: Any,
) -> Any:
    """
    Execute a Task state transition under an atomic BEGIN IMMEDIATE write transaction.
    Ensures:
    1. The SQLite writer lock is obtained BEFORE reading the WorkJob state.
    2. transaction_now = utcnow() is sampled immediately AFTER acquiring the writer lock.
    3. The WorkJob is reloaded from fresh database state.
    4. Any validation occurs against current database truth, preventing stale in-memory
       ORM states or concurrent worker completions from being overwritten.
    """
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        transaction_now = utcnow()
        job = session.get(WorkJob, task_id)
        if job is None:
            raise KeyError(task_id)
        sig = inspect.signature(transition_fn)
        if len(sig.parameters) >= 3 or any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values()):
            result = transition_fn(session, job, transaction_now)
        else:
            result = transition_fn(session, job)
        session.commit()
        return result


class TaskService:
    def __init__(self, session_factory: sessionmaker):
        self.SessionLocal = session_factory

    def list_tasks(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        status: str | None = None,
        job_type: str | None = None,
    ) -> dict:
        page = max(1, int(page))
        page_size = min(500, max(1, int(page_size)))
        offset = (page - 1) * page_size

        with self.SessionLocal() as session:
            stmt = select(WorkJob)
            count_stmt = select(func.count(WorkJob.id))

            if status:
                stmt = stmt.where(WorkJob.status == status)
                count_stmt = count_stmt.where(WorkJob.status == status)
            if job_type:
                stmt = stmt.where(WorkJob.kind == job_type)
                count_stmt = count_stmt.where(WorkJob.kind == job_type)

            total = session.scalar(count_stmt) or 0
            rows = list(session.scalars(stmt.order_by(WorkJob.id.desc()).limit(page_size).offset(offset)))

            return {
                "items": [format_task(r) for r in rows],
                "page": page,
                "page_size": page_size,
                "total": total,
            }

    def get_task_detail(self, task_id: int) -> dict:
        with self.SessionLocal() as session:
            job = session.get(WorkJob, task_id)
            if job is None:
                raise KeyError(task_id)

            data = format_task(job)
            try:
                data["checkpoint"] = json.loads(job.checkpoint_json or "{}")
            except Exception:
                data["checkpoint"] = {}
            try:
                data["payload"] = json.loads(job.state_json or "{}")
            except Exception:
                data["payload"] = {}
            return data

    def pause_task(self, task_id: int) -> dict:
        def _transition(session: Session, job: WorkJob, now: datetime):
            caps = get_job_capabilities(job.kind)
            if not caps.get("supports_pause", False):
                raise ValueError("Job type does not support pause")

            if job.status == JobState.PAUSED.value:
                return format_task(job)

            if job.status in TERMINAL_STATES or job.status == JobState.CANCEL_REQUESTED.value:
                raise ValueError(f"Cannot pause job in status '{job.status}'")

            if job.status == JobState.QUEUED.value:
                validate_transition(job.status, JobState.PAUSED.value)
                job.status = JobState.PAUSED.value
                log_task_event(
                    session,
                    job_id=task_id,
                    event_type="paused",
                    message="Job paused while queued",
                    level="info",
                    timestamp=now,
                )
                return format_task(job)

            if job.status == JobState.RUNNING.value:
                job.pause_requested_at = now
                log_task_event(
                    session,
                    job_id=task_id,
                    event_type="pause_requested",
                    message="Pause requested by user",
                    level="info",
                    timestamp=now,
                )
                return format_task(job)

            raise ValueError(f"Cannot pause job in status '{job.status}'")

        return atomic_task_transition(self.SessionLocal, task_id, _transition)

    def resume_task(self, task_id: int) -> dict:
        def _transition(session: Session, job: WorkJob, now: datetime):
            caps = get_job_capabilities(job.kind)
            if not caps.get("supports_resume", False):
                raise ValueError("Job type does not support resume")

            if job.status != JobState.PAUSED.value:
                raise ValueError(f"Only paused jobs can be resumed (current status is '{job.status}')")

            validate_transition(job.status, JobState.QUEUED.value)
            job.status = JobState.QUEUED.value
            job.pause_requested_at = None
            log_task_event(
                session,
                job_id=task_id,
                event_type="resumed",
                message="Job resumed by user, placed back in queue",
                level="info",
                timestamp=now,
            )
            return format_task(job)

        return atomic_task_transition(self.SessionLocal, task_id, _transition)

    def cancel_task(self, task_id: int) -> dict:
        def _transition(session: Session, job: WorkJob, now: datetime):
            caps = get_job_capabilities(job.kind)
            if not caps.get("supports_cancel", False):
                raise ValueError("Job type does not support cancel")

            if job.status in TERMINAL_STATES:
                raise ValueError(f"Terminal job in state '{job.status}' cannot be cancelled")

            if job.status == JobState.CANCEL_REQUESTED.value:
                return format_task(job)

            if job.status in (JobState.QUEUED.value, JobState.PAUSED.value):
                validate_transition(job.status, JobState.CANCELLED.value)
                job.status = JobState.CANCELLED.value
                job.finished_at = now
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
                    job_id=task_id,
                    event_type="cancelled",
                    message=f"Job cancelled directly from state '{job.status}'",
                    level="warning",
                    timestamp=now,
                )
                return format_task(job)

            if job.status == JobState.RUNNING.value:
                validate_transition(job.status, JobState.CANCEL_REQUESTED.value)
                job.status = JobState.CANCEL_REQUESTED.value
                job.cancel_requested_at = now
                log_task_event(
                    session,
                    job_id=task_id,
                    event_type="cancel_requested",
                    message="Cancel requested by user",
                    level="warning",
                    timestamp=now,
                )
                return format_task(job)

            raise ValueError(f"Cannot cancel job in state '{job.status}'")

        return atomic_task_transition(self.SessionLocal, task_id, _transition)

    def retry_task(self, task_id: int, user_id: int | None = None) -> dict:
        def _transition(session: Session, job: WorkJob, now: datetime):
            caps = get_job_capabilities(job.kind)
            if not caps.get("supports_retry", False):
                raise ValueError("Job type does not support retry")

            if job.status != JobState.FAILED.value:
                raise ValueError(f"Only failed jobs can be retried (current status is '{job.status}')")

            # Create new queued job with whitelisted payload, fresh progress/error
            cleaned_state_json = filter_retry_payload(job.kind, job.state_json)
            if user_id is not None:
                try:
                    payload_dict = json.loads(cleaned_state_json)
                    payload_dict["requested_by_user_id"] = user_id
                    cleaned_state_json = json.dumps(payload_dict, ensure_ascii=False)
                except Exception:
                    pass
            new_job = WorkJob(
                kind=job.kind,
                status=JobState.QUEUED.value,
                state_json=cleaned_state_json,
                progress_current=0,
                progress_total=0,
                retry_of=job.id,
                created_at=now,
            )
            session.add(new_job)
            session.flush()

            log_task_event(
                session,
                job_id=job.id,
                event_type="retry_created",
                message=f"Created retry Job #{new_job.id}",
                level="info",
                timestamp=now,
            )
            log_task_event(
                session,
                job_id=new_job.id,
                event_type="queued",
                message=f"Job created as retry of Job #{job.id}",
                level="info",
                timestamp=now,
            )
            return {"job": format_task(new_job), "retry_of": job.id}

        return atomic_task_transition(self.SessionLocal, task_id, _transition)

    def delete_task(self, task_id: int) -> dict:
        def _transition(session: Session, job: WorkJob, *args: Any):
            if job.status not in TERMINAL_STATES:
                raise ValueError(f"Only terminal jobs can be deleted (current status is '{job.status}')")

            session.execute(delete(TaskEvent).where(TaskEvent.job_id == task_id))
            session.delete(job)
            return {"deleted": True, "id": task_id}

        return atomic_task_transition(self.SessionLocal, task_id, _transition)

    def clear_task_history(self, statuses: list[str] | None = None) -> dict:
        if statuses is None:
            target_statuses = set(TERMINAL_STATES)
        elif len(statuses) == 0:
            raise ValueError("At least one terminal status is required")
        else:
            target_statuses = set(statuses)

        for s in target_statuses:
            if s not in TERMINAL_STATES:
                raise ValueError(f"Cannot clear non-terminal status '{s}'")

        with self.SessionLocal() as session:
            del_stmt = delete(WorkJob).where(WorkJob.status.in_(list(target_statuses)))
            result = session.execute(del_stmt)
            count = result.rowcount
            session.commit()
            return {"deleted_count": count}

    def get_task_logs(
        self,
        task_id: int,
        *,
        page: int = 1,
        page_size: int = 50,
        level: str | None = None,
    ) -> dict:
        page = max(1, int(page))
        page_size = min(500, max(1, int(page_size)))
        offset = (page - 1) * page_size

        with self.SessionLocal() as session:
            job = session.get(WorkJob, task_id)
            if job is None:
                raise KeyError(task_id)

            stmt = select(TaskEvent).where(TaskEvent.job_id == task_id)
            count_stmt = select(func.count(TaskEvent.id)).where(TaskEvent.job_id == task_id)

            if level:
                stmt = stmt.where(TaskEvent.level == level)
                count_stmt = count_stmt.where(TaskEvent.level == level)

            total = session.scalar(count_stmt) or 0
            rows = list(session.scalars(stmt.order_by(TaskEvent.id.asc()).limit(page_size).offset(offset)))

            items = []
            for r in rows:
                try:
                    ctx = json.loads(r.context_json or "{}")
                except Exception:
                    ctx = {}
                items.append({
                    "id": r.id,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                    "level": r.level,
                    "event_type": r.event_type,
                    "message": r.message,
                    "context": ctx,
                })

            return {
                "items": items,
                "page": page,
                "page_size": page_size,
                "total": total,
            }

    def get_worker_status(self) -> dict:
        with self.SessionLocal() as session:
            state = session.get(WorkerState, "default")
            if state is None:
                status, age = compute_worker_status(None)
                return {
                    "status": status,
                    "worker_id": None,
                    "started_at": None,
                    "heartbeat_at": None,
                    "heartbeat_age_seconds": None,
                }

            status, age = compute_worker_status(state.heartbeat_at)
            return {
                "status": status,
                "worker_id": state.worker_id,
                "started_at": state.started_at.isoformat() if state.started_at else None,
                "heartbeat_at": state.heartbeat_at.isoformat() if state.heartbeat_at else None,
                "heartbeat_age_seconds": age,
            }
