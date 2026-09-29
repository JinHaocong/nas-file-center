from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db import create_engine_and_session, init_db
from app.models import (
    Base,
    Schedule,
    SchedulerState,
    ScheduleRun,
    User,
    WorkJob,
)
from app.scheduler.cron import (
    CronNoOccurrenceError,
    CronValidationError,
    next_occurrence,
    parse_cron_expression,
    resolve_scheduler_timezone,
)
from app.scheduler.schema import ScheduleCreate, ScheduleUpdate
from app.scheduler.service import (
    ScheduleRevisionConflictError,
    SchedulerService,
    acquire_scheduler_lease,
    release_scheduler_lease,
    renew_scheduler_lease,
)


UTC = timezone.utc


def _dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _service(tmp_path: Path):
    db_file = tmp_path / "scheduler.db"
    engine, SessionLocal = create_engine_and_session(db_file)
    init_db(engine, db_path=db_file, backups_dir=tmp_path / "backups")
    with SessionLocal() as session:
        session.add(
            User(
                username="scheduler-admin",
                password_hash="hash",
                role="admin",
                is_active=True,
            )
        )
        session.commit()
    return engine, SessionLocal, SchedulerService(SessionLocal)


def _index_schedule(*, enabled: bool = True, root_id: int = 1, cron: str = "*/5 * * * *") -> ScheduleCreate:
    return ScheduleCreate.model_validate(
        {
            "name": "Night index",
            "description": "scheduler S1 test",
            "enabled": enabled,
            "target": {"type": "index_root", "root_id": root_id},
            "cron_expression": cron,
            "timezone": "UTC",
        }
    )


def test_cron_parser_accepts_frozen_numeric_grammar():
    cron = parse_cron_expression("*/15 1-3/2 1,15 * 0")

    assert cron.minute.values == frozenset({0, 15, 30, 45})
    assert cron.hour.values == frozenset({1, 3})
    assert cron.day_of_month.values == frozenset({1, 15})
    assert cron.month.values == frozenset(range(1, 13))
    assert cron.day_of_week.values == frozenset({0})
    assert cron.source == "*/15 1-3/2 1,15 * 0"


@pytest.mark.parametrize(
    "expression",
    [
        "@daily",
        "0 0 * *",
        "0 0 * * * *",
        "60 0 * * *",
        "0 24 * * *",
        "0 0 0 * *",
        "0 0 * 13 *",
        "0 0 * * 7",
        "*/0 * * * *",
        "5-1 * * * *",
        "0 0 * JAN *",
        "0 0 L * *",
        "0 0 * * MON",
    ],
)
def test_cron_parser_rejects_out_of_scope_or_invalid_forms(expression: str):
    with pytest.raises(CronValidationError):
        parse_cron_expression(expression)


def test_cron_dom_dow_uses_standard_or_semantics_when_both_restricted():
    cron = parse_cron_expression("0 0 13 * 1")

    # Day 13 matches even when it is not Monday.
    day_13 = next(
        date(2026, month, 13)
        for month in range(1, 13)
        if date(2026, month, 13).weekday() != 0
    )
    assert cron.matches_date(day_13) is True

    # Monday matches even when it is not day 13.
    cursor = date(2026, 1, 1)
    monday = next(
        cursor + timedelta(days=offset)
        for offset in range(60)
        if (cursor + timedelta(days=offset)).weekday() == 0
        and (cursor + timedelta(days=offset)).day != 13
    )
    assert cron.matches_date(monday) is True


def test_timezone_validation_requires_iana_zone():
    assert resolve_scheduler_timezone("Asia/Shanghai").key == "Asia/Shanghai"
    with pytest.raises(CronValidationError):
        resolve_scheduler_timezone("Mars/Phobos")


def test_spring_forward_nonexistent_wall_time_is_skipped():
    # America/New_York enters DST on 2026-03-08. 02:30 does not exist.
    result = next_occurrence(
        "30 2 * * *",
        "America/New_York",
        after_utc=_dt(2026, 3, 7, 7, 31),
    )
    assert result == _dt(2026, 3, 9, 6, 30)


def test_fall_back_ambiguous_wall_time_fires_first_occurrence_only():
    first = next_occurrence(
        "30 1 * * *",
        "America/New_York",
        after_utc=_dt(2026, 11, 1, 4, 0),
    )
    assert first == _dt(2026, 11, 1, 5, 30)

    # The repeated fold=1 01:30 at 06:30Z is intentionally not another run.
    after_first = next_occurrence(
        "30 1 * * *",
        "America/New_York",
        after_utc=_dt(2026, 11, 1, 5, 31),
    )
    assert after_first == _dt(2026, 11, 2, 6, 30)


def test_impossible_cron_fails_closed_after_horizon():
    with pytest.raises(CronNoOccurrenceError):
        next_occurrence(
            "0 0 31 2 *",
            "UTC",
            after_utc=_dt(2026, 1, 1, 0, 0),
            horizon_days=366,
        )


def test_scheduler_migration_is_additive_backs_up_and_preserves_existing_rows(tmp_path: Path):
    db_file = tmp_path / "legacy.db"
    backups = tmp_path / "backups"
    engine = create_engine(f"sqlite:///{db_file}")

    # Simulate a current pre-Scheduler database with representative durable rows.
    Base.metadata.create_all(
        engine,
        tables=[
            Base.metadata.tables["users"],
            Base.metadata.tables["work_jobs"],
        ],
    )
    LegacySession = sessionmaker(bind=engine, expire_on_commit=False)
    with LegacySession() as session:
        user = User(username="legacy", password_hash="hash", role="admin", is_active=True)
        session.add(user)
        session.add(
            WorkJob(
                kind="index-root",
                status="completed",
                state_json='{"root":"/data/legacy"}',
            )
        )
        session.commit()

    init_db(engine, db_path=db_file, backups_dir=backups)

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"schedules", "schedule_runs", "scheduler_state"}.issubset(tables)
    assert list(backups.glob("nas-file-center-*.db"))

    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(WorkJob)) == 1
        assert session.scalar(select(func.count()).select_from(Schedule)) == 0
        state = session.get(SchedulerState, 1)
        assert state is not None
        assert state.owner is None


def test_schedule_service_revision_disable_and_recurrence(tmp_path: Path):
    _, _, service = _service(tmp_path)
    now = _dt(2026, 9, 29, 1, 2)

    created = service.create_schedule(1, _index_schedule(), now_utc=now)
    assert created["revision"] == 1
    assert created["enabled"] is True
    assert created["target_type"] == "index_root"
    assert created["next_scheduled_for_utc"] == _dt(2026, 9, 29, 1, 5).isoformat()

    with pytest.raises(ScheduleRevisionConflictError):
        service.update_schedule(
            created["id"],
            ScheduleUpdate.model_validate(
                {"expected_revision": 99, "name": "stale"}
            ),
            now_utc=now,
        )

    disabled = service.update_schedule(
        created["id"],
        ScheduleUpdate.model_validate(
            {"expected_revision": 1, "enabled": False}
        ),
        now_utc=now,
    )
    assert disabled["revision"] == 2
    assert disabled["enabled"] is False
    assert disabled["next_scheduled_for_utc"] is None
    assert service.list_due_schedules(now_utc=_dt(2026, 9, 29, 2, 0)) == []


def test_run_slot_identity_is_unique_snapshot_bound_and_creates_no_workjob(tmp_path: Path):
    _, SessionLocal, service = _service(tmp_path)
    now = _dt(2026, 9, 29, 1, 2)
    created = service.create_schedule(1, _index_schedule(root_id=7), now_utc=now)
    slot = _dt(2026, 9, 29, 1, 5)

    first = service.reserve_scheduled_slot(created["id"], slot, created_at=slot)
    assert first is not None
    assert first["status"] == "pending"
    assert first["schedule_revision"] == 1
    assert first["target_snapshot"] == {"type": "index_root", "root_id": 7}
    assert first["work_job_id"] is None

    duplicate = service.reserve_scheduled_slot(created["id"], slot, created_at=slot)
    assert duplicate is None

    updated = service.update_schedule(
        created["id"],
        ScheduleUpdate.model_validate(
            {
                "expected_revision": 1,
                "target": {"type": "index_root", "root_id": 8},
            }
        ),
        now_utc=_dt(2026, 9, 29, 1, 6),
    )
    assert updated["revision"] == 2
    assert service.list_schedule_runs(created["id"])[0]["target_snapshot"]["root_id"] == 7

    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(WorkJob)) == 0
        assert session.scalar(select(func.count()).select_from(ScheduleRun)) == 1


def test_database_unique_constraint_is_final_run_slot_fence(tmp_path: Path):
    _, SessionLocal, service = _service(tmp_path)
    now = _dt(2026, 9, 29, 1, 2)
    created = service.create_schedule(1, _index_schedule(), now_utc=now)
    slot = _dt(2026, 9, 29, 1, 5)

    with SessionLocal() as session:
        schedule = session.get(Schedule, created["id"])
        assert schedule is not None
        for _ in range(2):
            session.add(
                ScheduleRun(
                    schedule_id=schedule.id,
                    schedule_revision=schedule.revision,
                    scheduled_for_utc=slot,
                    status="pending",
                    target_snapshot_json=schedule.target_json,
                    created_at=slot,
                )
            )
            if _ == 0:
                session.commit()
            else:
                with pytest.raises(IntegrityError):
                    session.commit()
                session.rollback()


def test_disabled_schedule_cannot_reserve_old_slot(tmp_path: Path):
    _, _, service = _service(tmp_path)
    now = _dt(2026, 9, 29, 1, 2)
    created = service.create_schedule(1, _index_schedule(), now_utc=now)
    slot = _dt(2026, 9, 29, 1, 5)
    service.update_schedule(
        created["id"],
        ScheduleUpdate.model_validate(
            {"expected_revision": 1, "enabled": False}
        ),
        now_utc=_dt(2026, 9, 29, 1, 3),
    )

    assert service.reserve_scheduled_slot(created["id"], slot) is None
    assert service.list_schedule_runs(created["id"]) == []


def test_schedule_target_schema_is_closed_and_rejects_credentials():
    with pytest.raises(ValidationError):
        ScheduleCreate.model_validate(
            {
                "name": "bad",
                "target": {
                    "type": "index_root",
                    "root_id": 1,
                    "token": "must-not-be-stored",
                },
                "cron_expression": "0 * * * *",
                "timezone": "UTC",
            }
        )

    with pytest.raises(ValidationError):
        ScheduleCreate.model_validate(
            {
                "name": "bad-kind",
                "target": {"type": "batch_plan_execute", "plan_id": 10},
                "cron_expression": "0 * * * *",
                "timezone": "UTC",
            }
        )


def test_scheduler_lease_contention_expiry_and_takeover(tmp_path: Path):
    _, SessionLocal, _ = _service(tmp_path)
    t0 = _dt(2026, 9, 29, 1, 0)

    assert acquire_scheduler_lease(SessionLocal, "worker-a", ttl_seconds=60, now_utc=t0)
    assert not acquire_scheduler_lease(
        SessionLocal,
        "worker-b",
        ttl_seconds=60,
        now_utc=t0 + timedelta(seconds=30),
    )
    assert renew_scheduler_lease(
        SessionLocal,
        "worker-a",
        ttl_seconds=60,
        now_utc=t0 + timedelta(seconds=40),
    )
    assert not acquire_scheduler_lease(
        SessionLocal,
        "worker-b",
        ttl_seconds=60,
        now_utc=t0 + timedelta(seconds=80),
    )

    assert acquire_scheduler_lease(
        SessionLocal,
        "worker-b",
        ttl_seconds=60,
        now_utc=t0 + timedelta(seconds=101),
    )
    assert not renew_scheduler_lease(
        SessionLocal,
        "worker-a",
        ttl_seconds=60,
        now_utc=t0 + timedelta(seconds=102),
    )
    assert release_scheduler_lease(
        SessionLocal,
        "worker-b",
        now_utc=t0 + timedelta(seconds=103),
    )
