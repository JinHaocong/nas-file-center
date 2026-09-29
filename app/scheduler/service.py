from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import Schedule, SchedulerState, ScheduleRun, utcnow
from app.scheduler.cron import next_occurrence
from app.scheduler.schema import (
    ScheduleCreate,
    ScheduleUpdate,
    canonical_target_json,
)


class ScheduleNotFoundError(KeyError):
    pass


class ScheduleRevisionConflictError(RuntimeError):
    pass


class SchedulerLeaseLostError(RuntimeError):
    pass


def _db_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _require_aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def _same_utc(left: datetime | None, right: datetime) -> bool:
    if left is None:
        return False
    return _db_utc(left) == _require_aware_utc(right)


def _serialize_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _db_utc(value).isoformat()


def serialize_schedule(row: Schedule) -> dict[str, Any]:
    try:
        target = json.loads(row.target_json)
    except Exception:
        target = {}
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "enabled": row.enabled,
        "target_type": row.target_type,
        "target": target,
        "cron_expression": row.cron_expression,
        "timezone": row.timezone,
        "overlap_policy": row.overlap_policy,
        "missed_run_policy": row.missed_run_policy,
        "created_by_user_id": row.created_by_user_id,
        "revision": row.revision,
        "created_at": _serialize_dt(row.created_at),
        "updated_at": _serialize_dt(row.updated_at),
        "last_scheduled_for_utc": _serialize_dt(row.last_scheduled_for_utc),
        "next_scheduled_for_utc": _serialize_dt(row.next_scheduled_for_utc),
    }


def serialize_schedule_run(row: ScheduleRun) -> dict[str, Any]:
    try:
        target_snapshot = json.loads(row.target_snapshot_json)
    except Exception:
        target_snapshot = {}
    return {
        "id": row.id,
        "schedule_id": row.schedule_id,
        "schedule_revision": row.schedule_revision,
        "scheduled_for_utc": _serialize_dt(row.scheduled_for_utc),
        "dispatched_at": _serialize_dt(row.dispatched_at),
        "status": row.status,
        "work_job_id": row.work_job_id,
        "error_code": row.error_code,
        "error_text": row.error_text,
        "target_snapshot": target_snapshot,
        "created_at": _serialize_dt(row.created_at),
    }


class SchedulerService:
    def __init__(self, session_factory: sessionmaker):
        self.SessionLocal = session_factory

    def create_schedule(
        self,
        created_by_user_id: int | None,
        payload: ScheduleCreate,
        *,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        now = _require_aware_utc(now_utc or utcnow())
        target_json = canonical_target_json(payload.target)
        next_run = (
            next_occurrence(
                payload.cron_expression,
                payload.timezone,
                after_utc=now,
            )
            if payload.enabled
            else None
        )

        with self.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row = Schedule(
                name=payload.name,
                description=payload.description,
                enabled=payload.enabled,
                target_type=payload.target.type,
                target_json=target_json,
                cron_expression=payload.cron_expression,
                timezone=payload.timezone,
                overlap_policy=payload.overlap_policy,
                missed_run_policy=payload.missed_run_policy,
                created_by_user_id=created_by_user_id,
                revision=1,
                created_at=now,
                updated_at=now,
                last_scheduled_for_utc=None,
                next_scheduled_for_utc=next_run,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return serialize_schedule(row)

    def get_schedule(self, schedule_id: int) -> dict[str, Any]:
        with self.SessionLocal() as session:
            row = session.get(Schedule, schedule_id)
            if row is None:
                raise ScheduleNotFoundError(schedule_id)
            return serialize_schedule(row)

    def list_schedules(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        with self.SessionLocal() as session:
            stmt = select(Schedule)
            if not include_disabled:
                stmt = stmt.where(Schedule.enabled.is_(True))
            rows = list(session.scalars(stmt.order_by(Schedule.id)))
            return [serialize_schedule(row) for row in rows]

    def update_schedule(
        self,
        schedule_id: int,
        payload: ScheduleUpdate,
        *,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        now = _require_aware_utc(now_utc or utcnow())

        with self.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row = session.get(Schedule, schedule_id)
            if row is None:
                session.rollback()
                raise ScheduleNotFoundError(schedule_id)
            if row.revision != payload.expected_revision:
                session.rollback()
                raise ScheduleRevisionConflictError(
                    f"schedule revision conflict: expected {payload.expected_revision}, got {row.revision}"
                )

            fields = payload.model_fields_set
            if "name" in fields and payload.name is not None:
                row.name = payload.name
            if "description" in fields and payload.description is not None:
                row.description = payload.description
            if "enabled" in fields and payload.enabled is not None:
                row.enabled = payload.enabled
            if "target" in fields and payload.target is not None:
                row.target_type = payload.target.type
                row.target_json = canonical_target_json(payload.target)
            if "cron_expression" in fields and payload.cron_expression is not None:
                row.cron_expression = payload.cron_expression
            if "timezone" in fields and payload.timezone is not None:
                row.timezone = payload.timezone
            if "overlap_policy" in fields and payload.overlap_policy is not None:
                row.overlap_policy = payload.overlap_policy
            if "missed_run_policy" in fields and payload.missed_run_policy is not None:
                row.missed_run_policy = payload.missed_run_policy

            row.revision += 1
            row.updated_at = now
            row.next_scheduled_for_utc = (
                next_occurrence(
                    row.cron_expression,
                    row.timezone,
                    after_utc=now,
                )
                if row.enabled
                else None
            )
            session.commit()
            session.refresh(row)
            return serialize_schedule(row)

    def list_due_schedules(self, *, now_utc: datetime | None = None) -> list[dict[str, Any]]:
        now = _require_aware_utc(now_utc or utcnow())
        with self.SessionLocal() as session:
            rows = list(
                session.scalars(
                    select(Schedule)
                    .where(
                        Schedule.enabled.is_(True),
                        Schedule.next_scheduled_for_utc.is_not(None),
                        Schedule.next_scheduled_for_utc <= now,
                    )
                    .order_by(Schedule.next_scheduled_for_utc, Schedule.id)
                )
            )
            return [serialize_schedule(row) for row in rows]

    def reserve_scheduled_slot(
        self,
        schedule_id: int,
        scheduled_for_utc: datetime,
        *,
        created_at: datetime | None = None,
    ) -> dict[str, Any] | None:
        slot = _require_aware_utc(scheduled_for_utc)
        created = _require_aware_utc(created_at or utcnow())

        with self.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            try:
                row = session.get(Schedule, schedule_id)
                if row is None:
                    session.rollback()
                    raise ScheduleNotFoundError(schedule_id)

                existing = session.scalar(
                    select(ScheduleRun).where(
                        ScheduleRun.schedule_id == schedule_id,
                        ScheduleRun.scheduled_for_utc == slot,
                    )
                )
                if existing is not None:
                    session.rollback()
                    return None

                if not row.enabled or not _same_utc(row.next_scheduled_for_utc, slot):
                    session.rollback()
                    return None

                run = ScheduleRun(
                    schedule_id=row.id,
                    schedule_revision=row.revision,
                    scheduled_for_utc=slot,
                    dispatched_at=None,
                    status="pending",
                    work_job_id=None,
                    error_code=None,
                    error_text=None,
                    target_snapshot_json=row.target_json,
                    created_at=created,
                )
                session.add(run)
                row.last_scheduled_for_utc = slot
                row.next_scheduled_for_utc = next_occurrence(
                    row.cron_expression,
                    row.timezone,
                    after_utc=slot,
                )
                session.commit()
                session.refresh(run)
                return serialize_schedule_run(run)
            except IntegrityError:
                session.rollback()
                return None

    def list_schedule_runs(
        self,
        schedule_id: int,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        with self.SessionLocal() as session:
            rows = list(
                session.scalars(
                    select(ScheduleRun)
                    .where(ScheduleRun.schedule_id == schedule_id)
                    .order_by(ScheduleRun.scheduled_for_utc.desc())
                    .limit(limit)
                )
            )
            return [serialize_schedule_run(row) for row in rows]


def _get_scheduler_state(session: Session, *, now: datetime) -> SchedulerState:
    state = session.get(SchedulerState, 1)
    if state is None:
        state = SchedulerState(
            id=1,
            owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
            updated_at=now,
        )
        session.add(state)
        session.flush()
    return state


def acquire_scheduler_lease(
    session_factory: sessionmaker,
    owner: str,
    *,
    ttl_seconds: float = 90.0,
    now_utc: datetime | None = None,
) -> bool:
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("scheduler lease owner must be a non-empty string")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)) or ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")

    now = _require_aware_utc(now_utc or utcnow())
    expires = now + timedelta(seconds=float(ttl_seconds))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        state = _get_scheduler_state(session, now=now)
        current_expiry = (
            _db_utc(state.lease_expires_at)
            if state.lease_expires_at is not None
            else None
        )

        if (
            state.owner
            and state.owner != owner
            and current_expiry is not None
            and current_expiry > now
        ):
            session.rollback()
            return False

        state.owner = owner
        state.lease_expires_at = expires
        state.heartbeat_at = now
        state.updated_at = now
        session.commit()
        return True


def renew_scheduler_lease(
    session_factory: sessionmaker,
    owner: str,
    *,
    ttl_seconds: float = 90.0,
    now_utc: datetime | None = None,
) -> bool:
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("scheduler lease owner must be a non-empty string")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)) or ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")

    now = _require_aware_utc(now_utc or utcnow())
    expires = now + timedelta(seconds=float(ttl_seconds))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        state = _get_scheduler_state(session, now=now)
        current_expiry = (
            _db_utc(state.lease_expires_at)
            if state.lease_expires_at is not None
            else None
        )
        if state.owner != owner or current_expiry is None or current_expiry <= now:
            session.rollback()
            return False

        state.lease_expires_at = expires
        state.heartbeat_at = now
        state.updated_at = now
        session.commit()
        return True


def assert_scheduler_lease(
    session: Session,
    owner: str,
    *,
    now_utc: datetime | None = None,
) -> SchedulerState:
    now = _require_aware_utc(now_utc or utcnow())
    state = session.get(SchedulerState, 1)
    if state is None or state.owner != owner or state.lease_expires_at is None:
        raise SchedulerLeaseLostError("scheduler lease is not held by this owner")

    expires = _db_utc(state.lease_expires_at)
    if expires <= now:
        raise SchedulerLeaseLostError("scheduler lease has expired")
    return state


def release_scheduler_lease(
    session_factory: sessionmaker,
    owner: str,
    *,
    now_utc: datetime | None = None,
) -> bool:
    now = _require_aware_utc(now_utc or utcnow())
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        state = _get_scheduler_state(session, now=now)
        if state.owner != owner:
            session.rollback()
            return False
        state.owner = None
        state.lease_expires_at = None
        state.heartbeat_at = now
        state.updated_at = now
        session.commit()
        return True
