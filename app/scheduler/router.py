from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.auth.dependencies import get_current_user, require_admin_user
from app.models import ScheduleRun, User, WorkJob, utcnow
from app.scheduler.cron import CronValidationError, next_occurrences
from app.scheduler.dispatch import run_schedule_now
from app.scheduler.schema import ScheduleCreate, ScheduleUpdate
from app.scheduler.service import (
    ScheduleNotFoundError,
    ScheduleRevisionConflictError,
    SchedulerService,
)


router = APIRouter(
    prefix="/api/schedules",
    tags=["scheduler"],
    dependencies=[Depends(get_current_user)],
)


class ScheduleRecurrencePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    cron_expression: str = Field(min_length=1, max_length=128)
    timezone: str = Field(min_length=1, max_length=64)
    count: int = Field(default=5, ge=1, le=10)


def _service(request: Request) -> SchedulerService:
    return SchedulerService(request.app.state.service.SessionLocal)


def _run_with_task(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    work_job_id = payload.get("work_job_id")
    result = dict(payload)
    result["work_job_status"] = None
    result["work_job_kind"] = None
    if isinstance(work_job_id, int) and not isinstance(work_job_id, bool):
        with request.app.state.service.SessionLocal() as session:
            work = session.get(WorkJob, work_job_id)
            if work is not None:
                result["work_job_status"] = work.status
                result["work_job_kind"] = work.kind
    return result


@router.get("")
def list_schedules(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    include_disabled: bool = Query(default=True),
):
    rows = _service(request).list_schedules(include_disabled=include_disabled)
    total = len(rows)
    offset = (page - 1) * page_size
    return {
        "items": rows[offset : offset + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{schedule_id}")
def get_schedule(request: Request, schedule_id: int):
    try:
        return _service(request).get_schedule(schedule_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc


@router.get("/{schedule_id}/runs")
def list_schedule_runs(
    request: Request,
    schedule_id: int,
    limit: int = Query(default=50, ge=1, le=200),
):
    service = _service(request)
    try:
        service.get_schedule(schedule_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc

    rows = service.list_schedule_runs(schedule_id, limit=limit)
    return {"items": [_run_with_task(request, row) for row in rows]}


@router.post(
    "",
    status_code=201,
    dependencies=[Depends(require_admin_user)],
)
def create_schedule(
    request: Request,
    payload: ScheduleCreate,
    current_user: User = Depends(require_admin_user),
):
    try:
        return _service(request).create_schedule(
            current_user.id,
            payload,
            now_utc=utcnow(),
        )
    except (CronValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put(
    "/{schedule_id}",
    dependencies=[Depends(require_admin_user)],
)
def update_schedule(
    request: Request,
    schedule_id: int,
    payload: ScheduleUpdate,
):
    try:
        return _service(request).update_schedule(
            schedule_id,
            payload,
            now_utc=utcnow(),
        )
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    except ScheduleRevisionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SCHEDULE_REVISION_CONFLICT",
                "message": str(exc),
            },
        ) from exc
    except (CronValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/{schedule_id}/run-now",
    status_code=201,
    dependencies=[Depends(require_admin_user)],
)
def run_now(request: Request, schedule_id: int):
    try:
        run = run_schedule_now(
            request.app.state.service.SessionLocal,
            request.app.state.settings,
            schedule_id=schedule_id,
            requested_at_utc=utcnow(),
        )
        return _run_with_task(request, run)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/recurrence-preview",
    dependencies=[Depends(require_admin_user)],
)
def preview_recurrence(
    payload: ScheduleRecurrencePreviewRequest,
):
    try:
        now = datetime.now(timezone.utc)
        occurrences = next_occurrences(
            payload.cron_expression,
            payload.timezone,
            after_utc=now,
            count=payload.count,
        )
        return {
            "cron_expression": payload.cron_expression,
            "timezone": payload.timezone,
            "generated_at_utc": now.isoformat(),
            "occurrences": [item.isoformat() for item in occurrences],
        }
    except CronValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
