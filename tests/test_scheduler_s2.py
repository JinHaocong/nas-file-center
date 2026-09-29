from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import (
    IndexRoot,
    ResourcePolicy,
    ScanJob,
    Schedule,
    ScheduleRun,
    User,
    WorkJob,
    utcnow,
)
from app.scheduler.dispatch import run_scheduler_tick
from app.scheduler.schema import ScheduleCreate
from app.scheduler.service import SchedulerService
from app.tasks.recovery import acquire_worker_ownership, claim_next_job
from app.worker import worker_loop


UTC = timezone.utc


def _dt(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 9, 29, hour, minute, second, tzinfo=UTC)


def _env(tmp_path: Path):
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    data_dir.mkdir()
    settings = Settings(
        config_dir=config_dir,
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
    )
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path, backups_dir=settings.backups_dir)
    with SessionLocal() as session:
        admin = User(
            username="scheduler-s2-admin",
            password_hash="hash",
            role="admin",
            is_active=True,
        )
        session.add(admin)
        session.commit()
        admin_id = int(admin.id)
    return settings, engine, SessionLocal, SchedulerService(SessionLocal), data_dir, admin_id


def _register_root(SessionLocal, path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as session:
        row = IndexRoot(root=str(path), created_at=utcnow())
        session.add(row)
        session.commit()
        return int(row.id)


def _create_schedule(
    service: SchedulerService,
    admin_id: int,
    target: dict,
    *,
    name: str = "S2 schedule",
    created_at: datetime = _dt(12, 0, 5),
) -> dict:
    payload = ScheduleCreate.model_validate(
        {
            "name": name,
            "target": target,
            "cron_expression": "* * * * *",
            "timezone": "UTC",
        }
    )
    return service.create_schedule(admin_id, payload, now_utc=created_at)


def test_index_due_slot_dispatch_is_atomic_and_idempotent(tmp_path: Path):
    settings, _, SessionLocal, service, data_dir, admin_id = _env(tmp_path)
    root = data_dir / "indexed"
    root_id = _register_root(SessionLocal, root)
    schedule = _create_schedule(
        service,
        admin_id,
        {"type": "index_root", "root_id": root_id},
        name="Index photos",
    )

    result = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-a",
        now_utc=_dt(12, 1, 20),
    )
    assert result.dispatched == 1
    assert result.failed == 0

    # Repeating the tick in the same minute must not create another WorkJob.
    again = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-a",
        now_utc=_dt(12, 1, 40),
    )
    assert again.dispatched == 0

    with SessionLocal() as session:
        runs = list(session.scalars(select(ScheduleRun)))
        works = list(session.scalars(select(WorkJob)))
        assert len(runs) == 1
        assert len(works) == 1
        assert runs[0].status == "dispatched"
        assert runs[0].work_job_id == works[0].id
        assert works[0].kind == "index-root"
        state = json.loads(works[0].state_json)
        assert state["root"] == str(root)
        assert state["scheduler"]["schedule_id"] == schedule["id"]
        assert state["scheduler"]["schedule_run_id"] == runs[0].id
        assert state["scheduler"]["scheduled_for_utc"] == _dt(12, 1).isoformat()


def test_scheduled_scan_creates_scan_and_workjob_in_same_dispatch(tmp_path: Path):
    settings, _, SessionLocal, service, data_dir, admin_id = _env(tmp_path)
    root_a = data_dir / "a"
    root_b = data_dir / "b"
    root_a.mkdir()
    root_b.mkdir()
    schedule = _create_schedule(
        service,
        admin_id,
        {
            "type": "fclones_scan",
            "roots": [str(root_a), str(root_b)],
            "isolate": True,
            "min_size": "10M",
            "name_patterns": ["*.mkv"],
            "exclude_patterns": ["sample*"],
        },
        name="Night duplicates",
    )

    result = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-a",
        now_utc=_dt(12, 1, 1),
    )
    assert result.dispatched == 1

    with SessionLocal() as session:
        run = session.scalar(select(ScheduleRun))
        scan = session.scalar(select(ScanJob))
        work = session.scalar(select(WorkJob))
        assert run is not None and scan is not None and work is not None
        assert run.work_job_id == work.id
        assert scan.name == "Scheduled: Night duplicates"
        assert scan.mode == "isolate"
        assert work.kind == "fclones-scan"
        state = json.loads(work.state_json)
        assert state["scan_job_id"] == scan.id
        assert state["roots"] == [str(root_a), str(root_b)]
        assert state["isolate"] is True
        assert state["scheduler"]["schedule_id"] == schedule["id"]


@pytest.mark.parametrize(
    ("target_type", "work_kind"),
    [
        ("media_analysis", "media-analysis"),
        ("media_integrity_verification", "media-integrity-verify"),
    ],
)
def test_media_targets_revalidate_registered_roots_and_dispatch(
    tmp_path: Path,
    target_type: str,
    work_kind: str,
):
    settings, _, SessionLocal, service, data_dir, admin_id = _env(tmp_path)
    root = data_dir / "media"
    _register_root(SessionLocal, root)
    _create_schedule(
        service,
        admin_id,
        {"type": target_type, "root_keys": [str(root)]},
    )

    result = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-a",
        now_utc=_dt(12, 1, 10),
    )
    assert result.dispatched == 1

    with SessionLocal() as session:
        work = session.scalar(select(WorkJob))
        assert work is not None
        assert work.kind == work_kind
        assert json.loads(work.state_json)["root_keys"] == [str(root)]


def test_missing_index_target_fails_closed_with_no_workjob(tmp_path: Path):
    settings, _, SessionLocal, service, data_dir, admin_id = _env(tmp_path)
    root = data_dir / "gone"
    root_id = _register_root(SessionLocal, root)
    _create_schedule(
        service,
        admin_id,
        {"type": "index_root", "root_id": root_id},
    )

    with SessionLocal() as session:
        row = session.get(IndexRoot, root_id)
        session.delete(row)
        session.commit()

    result = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-a",
        now_utc=_dt(12, 1, 5),
    )
    assert result.failed == 1

    with SessionLocal() as session:
        run = session.scalar(select(ScheduleRun))
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == "SCHEDULE_TARGET_INVALID"
        assert run.work_job_id is None
        assert session.scalar(select(func.count()).select_from(WorkJob)) == 0


def test_scan_root_missing_at_dispatch_fails_without_partial_scanjob(tmp_path: Path):
    settings, _, SessionLocal, service, data_dir, admin_id = _env(tmp_path)
    root = data_dir / "later-missing"
    root.mkdir()
    _create_schedule(
        service,
        admin_id,
        {"type": "fclones_scan", "roots": [str(root)]},
    )
    root.rmdir()

    result = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-a",
        now_utc=_dt(12, 1, 5),
    )
    assert result.failed == 1

    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(ScanJob)) == 0
        assert session.scalar(select(func.count()).select_from(WorkJob)) == 0
        run = session.scalar(select(ScheduleRun))
        assert run is not None and run.status == "failed"


def test_tampered_destructive_target_fails_closed(tmp_path: Path):
    settings, _, SessionLocal, service, data_dir, admin_id = _env(tmp_path)
    root = data_dir / "safe"
    root_id = _register_root(SessionLocal, root)
    created = _create_schedule(
        service,
        admin_id,
        {"type": "index_root", "root_id": root_id},
    )

    # Simulate direct DB corruption that bypasses the Pydantic API boundary.
    with SessionLocal() as session:
        row = session.get(Schedule, created["id"])
        row.target_json = json.dumps({"type": "batch_plan_execute", "plan_id": 99})
        session.commit()

    result = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-a",
        now_utc=_dt(12, 1, 5),
    )
    assert result.failed == 1
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(WorkJob)) == 0
        run = session.scalar(select(ScheduleRun))
        assert run is not None
        assert run.status == "failed"


def test_overlap_skips_second_slot_until_prior_workjob_terminal(tmp_path: Path):
    settings, _, SessionLocal, service, data_dir, admin_id = _env(tmp_path)
    root = data_dir / "overlap"
    root_id = _register_root(SessionLocal, root)
    _create_schedule(
        service,
        admin_id,
        {"type": "index_root", "root_id": root_id},
    )

    first = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-a",
        now_utc=_dt(12, 1, 5),
    )
    assert first.dispatched == 1

    second = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-a",
        now_utc=_dt(12, 2, 5),
    )
    assert second.skipped_overlap == 1

    with SessionLocal() as session:
        runs = list(session.scalars(select(ScheduleRun).order_by(ScheduleRun.id)))
        works = list(session.scalars(select(WorkJob).order_by(WorkJob.id)))
        assert [run.status for run in runs] == ["dispatched", "skipped_overlap"]
        assert len(works) == 1
        assert runs[1].work_job_id is None
        works[0].status = "completed"
        works[0].finished_at = _dt(12, 2, 30)
        session.commit()

    third = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-a",
        now_utc=_dt(12, 3, 5),
    )
    assert third.dispatched == 1
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(WorkJob)) == 2


def test_missed_slots_are_not_replayed_or_recorded(tmp_path: Path):
    settings, _, SessionLocal, service, data_dir, admin_id = _env(tmp_path)
    root = data_dir / "missed"
    root_id = _register_root(SessionLocal, root)
    created = _create_schedule(
        service,
        admin_id,
        {"type": "index_root", "root_id": root_id},
    )

    # The first due slot was 12:01. Starting at 12:05 must skip it rather than
    # replaying four minutes of work.
    result = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-a",
        now_utc=_dt(12, 5, 10),
    )
    assert result.missed_skipped == 1
    assert result.dispatched == 0

    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(ScheduleRun)) == 0
        assert session.scalar(select(func.count()).select_from(WorkJob)) == 0
        row = session.get(Schedule, created["id"])
        assert row is not None
        next_run = row.next_scheduled_for_utc
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=UTC)
        assert next_run == _dt(12, 6)


def test_resource_policy_pause_still_blocks_scheduled_index_claim(tmp_path: Path):
    settings, engine, SessionLocal, service, data_dir, admin_id = _env(tmp_path)
    root = data_dir / "resource-controlled"
    root_id = _register_root(SessionLocal, root)
    _create_schedule(
        service,
        admin_id,
        {"type": "index_root", "root_id": root_id},
    )

    dispatched = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="scheduler-owner",
        now_utc=_dt(12, 1, 5),
    )
    assert dispatched.dispatched == 1

    with SessionLocal() as session:
        policy = session.get(ResourcePolicy, 1)
        assert policy is not None
        policy.active_window_enabled = True
        policy.active_window_start = "13:00"
        policy.active_window_end = "14:00"
        policy.active_window_timezone = "UTC"
        policy.outside_window_mode = "pause"
        policy.revision += 1
        session.commit()

    worker_now = _dt(12, 1, 20)
    with patch("app.tasks.recovery.utcnow", return_value=worker_now):
        assert acquire_worker_ownership(
            engine,
            SessionLocal,
            worker_id="resource-worker",
        )
        assert claim_next_job(
            engine,
            SessionLocal,
            worker_id="resource-worker",
        ) is None

    with SessionLocal() as session:
        work = session.scalar(select(WorkJob))
        assert work is not None
        assert work.kind == "index-root"
        assert work.status == "queued"


def test_worker_attempts_scheduler_tick_at_most_once_per_minute(tmp_path: Path):
    settings, _, _, _, _, _ = _env(tmp_path)
    stop_event = threading.Event()
    claim_calls = {"count": 0}

    def fake_claim(*args, **kwargs):
        claim_calls["count"] += 1
        if claim_calls["count"] >= 2:
            stop_event.set()
        return None

    with (
        patch("app.worker.acquire_worker_ownership", return_value=True),
        patch("app.worker.recover_interrupted_jobs", return_value={}),
        patch("app.worker.claim_next_job", side_effect=fake_claim),
        patch("app.worker.run_scheduler_tick") as tick,
        patch("app.worker.utcnow", return_value=_dt(12, 1, 5)),
    ):
        worker_loop(
            settings,
            poll_seconds=0,
            heartbeat_interval=999,
            stop_event=stop_event,
        )

    assert tick.call_count == 1
