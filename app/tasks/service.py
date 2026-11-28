from datetime import datetime
import inspect
import json
from typing import Any
from sqlalchemy import Integer, case, delete, func, or_, select, text
from sqlalchemy.orm import Session, aliased, sessionmaker

from app.batch.organizer_report_cleanup import (
    is_report_task, preview_unavailable, report_task_filter, request_report_cleanup,
)
from app.config import Settings
from app.exceptions import StateConflictError
from app.models import BatchPlan, ScanJob, TaskEvent, WorkJob, WorkerState, utcnow
from app.tasks.handlers import get_job_capabilities
from app.tasks.logging import log_task_event
from app.tasks.recovery import compute_worker_status
from app.tasks.state_machine import (
    JobState,
    JobTransitionError,
    TERMINAL_STATES,
    validate_transition,
)
from app.tasks.sync import sync_batch_plan_status, sync_scan_job_status

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
    "media-analysis": {"root_keys"},
}

_ORGANIZER_PREVIEW = "media-organizer-preview"
_ORGANIZER_BATCH = "media-organizer-batch"
_LEGACY_ORGANIZER_HISTORY = ("media-organizer-execute", "media-organizer-cleanup")
_NEW_ORGANIZER_TASKS = (_ORGANIZER_PREVIEW, _ORGANIZER_BATCH)
_ORGANIZER_TASKS = (*_NEW_ORGANIZER_TASKS, *_LEGACY_ORGANIZER_HISTORY)


def _task_capabilities(kind: str) -> dict[str, bool]:
    caps = get_job_capabilities(kind)
    if kind in _LEGACY_ORGANIZER_HISTORY:
        return dict.fromkeys(caps, False)
    if kind in _NEW_ORGANIZER_TASKS:
        caps["supports_retry"] = False
    return caps


def _public_id(job: WorkJob) -> int | str:
    return str(job.id) if job.kind in _NEW_ORGANIZER_TASKS else job.id


def _task_json(raw: str | None) -> dict:
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _organizer_context(job: WorkJob, data: dict) -> dict:
    """Keep confirmations private and preserve exact IDs for current organizer jobs."""
    if job.kind not in _ORGANIZER_TASKS:
        return data
    return {
        key: str(value) if (job.kind in _NEW_ORGANIZER_TASKS
                            and key.endswith("_job_id") and type(value) is int) else value
        for key, value in data.items()
        if key not in ("confirmation", "recovery_confirmation", "confirmation_tokens")
    }


def _preserved_organizer_history():
    """Retain historical approvals and preview evidence used by a saved batch report."""
    batch = aliased(WorkJob)
    referenced_preview = select(batch.id).where(
        batch.kind == _ORGANIZER_BATCH,
        func.json_extract(batch.state_json, "$.preview_job_id") == WorkJob.id,
    ).exists()
    return or_(
        WorkJob.kind.in_((*_LEGACY_ORGANIZER_HISTORY, _ORGANIZER_BATCH)),
        (WorkJob.kind == _ORGANIZER_PREVIEW) & referenced_preview,
    )


def _dismiss_task(job: WorkJob) -> bool:
    checkpoint = _task_json(job.checkpoint_json)
    if checkpoint.get("_task_queue_dismissed") == 1:
        return False
    checkpoint["_task_queue_dismissed"] = True
    job.checkpoint_json = json.dumps(checkpoint, ensure_ascii=False)
    return True


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
    caps = _task_capabilities(job.kind)
    curr = job.progress_current or 0
    tot = job.progress_total or 0
    percent = round((curr / tot) * 100, 1) if tot > 0 else None
    if percent is not None:
        percent = min(100.0, max(0.0, percent))

    return {
        "id": _public_id(job),
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
        "retry_of": str(job.retry_of) if job.kind in _NEW_ORGANIZER_TASKS and job.retry_of is not None else job.retry_of,
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
    def __init__(self, session_factory: sessionmaker, *, report_settings: Settings | None = None):
        self.SessionLocal = session_factory
        self.report_settings = report_settings

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

            # A dismissed failed media-package execution remains durable for recovery,
            # but is no longer part of the user-facing task queue.
            visible = func.coalesce(func.json_extract(WorkJob.checkpoint_json, "$._task_queue_dismissed"), 0) != 1
            stmt = stmt.where(visible)
            count_stmt = count_stmt.where(visible)
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
            if job is None or preview_unavailable(job):
                raise KeyError(task_id)

            data = format_task(job)
            data["checkpoint"] = _organizer_context(job, _task_json(job.checkpoint_json))
            data["payload"] = _organizer_context(job, _task_json(job.state_json))
            if job.kind == "archive-recovery":
                # A one-time tmpfs reference is a secret capability, not task UI data.
                data["payload"].pop("secret_token", None)
            return data

    def latest_workflow_run(self, workflow_id: int) -> dict | None:
        """Read the latest scheduled task for this workflow without exposing its inputs."""
        with self.SessionLocal() as session:
            state = case((func.json_valid(WorkJob.state_json) == 1, WorkJob.state_json), else_="{}")
            job = session.scalar(select(WorkJob).where(
                WorkJob.kind == "workflow-scheduled",
                func.json_extract(state, "$.workflow_id") == workflow_id,
            ).order_by(WorkJob.id.desc()).limit(1))
            return {**format_task(job), "id": str(job.id)} if job else None

    def pause_task(self, task_id: int) -> dict:
        def _transition(session: Session, job: WorkJob, now: datetime):
            caps = _task_capabilities(job.kind)
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
            caps = _task_capabilities(job.kind)
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
            caps = _task_capabilities(job.kind)
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
                sync_batch_plan_status(
                    session,
                    job,
                    "cancelled",
                    finished_at=now,
                    error_text="Cancelled by user",
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

        response = atomic_task_transition(self.SessionLocal, task_id, _transition)
        if response["job_type"] == "archive-recovery" and response["status"] == "cancelled":
            with self.SessionLocal() as session:
                current = session.get(WorkJob, task_id)
                if current is not None:
                    from app.archive_recovery.integration import cleanup_cancelled_queued_recovery
                    cleanup_cancelled_queued_recovery(current.state_json)
        return response

    def retry_task(self, task_id: int, user_id: int | None = None) -> dict:
        def _transition(session: Session, job: WorkJob, now: datetime):
            caps = _task_capabilities(job.kind)
            if not caps.get("supports_retry", False):
                raise ValueError("Job type does not support retry")

            if job.status != JobState.FAILED.value:
                raise ValueError(f"Only failed jobs can be retried (current status is '{job.status}')")

            if job.kind == "batch-plan-execute":
                try:
                    payload_data = json.loads(job.state_json or "{}")
                    plan_id = payload_data.get("plan_id")
                except Exception:
                    plan_id = None
                if not plan_id:
                    raise ValueError("Invalid batch-plan-execute job: missing plan_id")

                plan = session.get(BatchPlan, int(plan_id))
                if plan is None:
                    raise ValueError(f"Cannot retry execution: plan #{plan_id} not found")
                if plan.status not in {"ready", "partial"}:
                    raise StateConflictError(
                        f"Cannot retry execution: plan #{plan_id} is in status '{plan.status}', expected 'ready' or 'partial'"
                    )

                active_job = session.scalars(
                    select(WorkJob)
                    .where(
                        WorkJob.kind == "batch-plan-execute",
                        WorkJob.status.in_(("queued", "running", "paused", "cancel_requested")),
                        func.cast(func.json_extract(WorkJob.state_json, "$.plan_id"), Integer) == int(plan_id),
                    )
                    .order_by(WorkJob.id.desc())
                ).first()
                if active_job is not None:
                    raise ValueError(
                        f"Cannot retry execution: plan #{plan_id} already has an active execution task #{active_job.id} (status: {active_job.status})"
                    )

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

    def delete_task(self, task_id: int, *, reclaim_reports: bool = True) -> dict:
        def _transition(session: Session, job: WorkJob, *args: Any):
            if job.status not in TERMINAL_STATES:
                raise ValueError(f"Only terminal jobs can be deleted (current status is '{job.status}')")
            if self.report_settings is not None and is_report_task(job):
                disposition = (request_report_cleanup(session, job, self.report_settings)
                               if reclaim_reports else "retained_count")
                _dismiss_task(job)
                return {"deleted": True, "id": _public_id(job), "report_cleanup": {
                    name: int(name == disposition) for name in ("queued_count", "retained_count")
                }}
            if ((job.kind == "media_package-package-execute" and job.status == "failed")
                    or (job.kind in _ORGANIZER_TASKS and session.scalar(select(WorkJob.id).where(
                        WorkJob.id == task_id, _preserved_organizer_history(),
                    )) is not None)):
                _dismiss_task(job)
                return {"deleted": True, "id": _public_id(job)}

            session.execute(delete(TaskEvent).where(TaskEvent.job_id == task_id))
            session.delete(job)
            return {"deleted": True, "id": _public_id(job)}

        return atomic_task_transition(self.SessionLocal, task_id, _transition)

    def clear_task_history(self, statuses: list[str] | None = None, *, reclaim_reports: bool = True) -> dict:
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
            session.execute(text("BEGIN IMMEDIATE"))
            report_counts = {"queued_count": 0, "retained_count": 0}
            report_dismissed = 0
            if self.report_settings is not None:
                jobs = list(session.scalars(select(WorkJob).where(
                    WorkJob.status.in_(target_statuses), report_task_filter(),
                    func.coalesce(func.json_extract(WorkJob.checkpoint_json, "$._task_queue_dismissed"), 0) != 1,
                ).order_by((WorkJob.kind == _ORGANIZER_BATCH).desc())))
                report_dismissed = len(jobs)
                for job in jobs:
                    disposition = (request_report_cleanup(session, job, self.report_settings)
                                   if reclaim_reports else "retained_count")
                    if disposition:
                        report_counts[disposition] += 1
                    _dismiss_task(job)
            retain_stmt = select(WorkJob).where(WorkJob.status.in_(target_statuses), _preserved_organizer_history())
            if self.report_settings is not None:
                retain_stmt = retain_stmt.where(~report_task_filter())
            retained = session.scalars(retain_stmt)
            dismissed = sum(_dismiss_task(job) for job in retained)
            del_stmt = delete(WorkJob).where(
                WorkJob.status.in_(target_statuses),
                ~_preserved_organizer_history(),
                (WorkJob.kind != "media_package-package-execute") |
                (WorkJob.status != "failed"),
            )
            if self.report_settings is not None:
                del_stmt = del_stmt.where(~report_task_filter())
            # Failed media-package execution records retain the only durable
            # link between an interrupted stage and its frozen manifest.
            result = session.execute(del_stmt)
            count = result.rowcount + dismissed + report_dismissed
            session.commit()
            return {"deleted_count": count, **({"report_cleanup": report_counts} if report_dismissed else {})}

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
                if job.kind in _ORGANIZER_TASKS:
                    ctx = _organizer_context(job, ctx if isinstance(ctx, dict) else {})
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
