from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import threading

from sqlalchemy import func, select

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import (
    IndexRoot,
    Schedule,
    ScheduleRun,
    SchedulerState,
    User,
    WorkJob,
)
from app.scheduler.dispatch import run_scheduler_tick
from app.scheduler.schema import ScheduleCreate, ScheduleUpdate
from app.scheduler.service import SchedulerService
from app.workflows.schema import WorkflowCreateRequest, WorkflowDefinition
from app.workflows.service import WorkflowService


UTC = timezone.utc


def _dt(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 9, 29, hour, minute, second, tzinfo=UTC)


def _env(tmp_path: Path):
    config = tmp_path / "config"
    data = tmp_path / "data"
    root = data / "library"
    config.mkdir()
    root.mkdir(parents=True)

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
    )
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(
        engine,
        db_path=settings.database_path,
        backups_dir=settings.backups_dir,
    )

    with SessionLocal() as session:
        admin = User(
            username="scheduler-s5-admin",
            password_hash="hash",
            role="admin",
            is_active=True,
        )
        root_row = IndexRoot(root=str(root))
        session.add_all([admin, root_row])
        session.commit()
        admin_id = int(admin.id)
        root_id = int(root_row.id)

    return (
        settings,
        engine,
        SessionLocal,
        SchedulerService(SessionLocal),
        WorkflowService(SessionLocal, settings),
        admin_id,
        root_id,
    )


def _index_schedule(
    scheduler: SchedulerService,
    admin_id: int,
    root_id: int,
    *,
    created_at: datetime = _dt(12, 0, 5),
):
    return scheduler.create_schedule(
        admin_id,
        ScheduleCreate.model_validate(
            {
                "name": "S5 index",
                "target": {"type": "index_root", "root_id": root_id},
                "cron_expression": "* * * * *",
                "timezone": "UTC",
            }
        ),
        now_utc=created_at,
    )


def test_restart_downtime_skips_missed_slots_then_dispatches_current_slot(tmp_path: Path):
    settings, _engine, SessionLocal, scheduler, _workflows, admin_id, root_id = _env(tmp_path)
    _index_schedule(scheduler, admin_id, root_id)

    restarted = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-after-restart",
        now_utc=_dt(12, 5, 5),
    )
    assert restarted.lease_acquired is True
    assert restarted.missed_skipped == 1
    assert restarted.dispatched == 0

    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(ScheduleRun)) == 0
        assert session.scalar(select(func.count()).select_from(WorkJob)) == 0
        schedule = session.scalar(select(Schedule))
        assert schedule is not None
        assert schedule.next_scheduled_for_utc.replace(tzinfo=UTC) == _dt(12, 6)

    current = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-after-restart",
        now_utc=_dt(12, 6, 5),
    )
    assert current.dispatched == 1

    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(ScheduleRun)) == 1
        assert session.scalar(select(func.count()).select_from(WorkJob)) == 1


def test_competing_scheduler_owners_dispatch_exactly_once(tmp_path: Path):
    settings, _engine, SessionLocal, scheduler, _workflows, admin_id, root_id = _env(tmp_path)
    _index_schedule(scheduler, admin_id, root_id)

    barrier = threading.Barrier(2)

    def tick(owner: str):
        barrier.wait(timeout=5)
        return run_scheduler_tick(
            SessionLocal,
            settings,
            owner=owner,
            now_utc=_dt(12, 1, 5),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(tick, ["worker-a", "worker-b"]))

    assert sum(int(result.lease_acquired) for result in results) == 1
    assert sum(result.dispatched for result in results) == 1

    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(ScheduleRun)) == 1
        assert session.scalar(select(func.count()).select_from(WorkJob)) == 1


def test_unique_slot_fence_survives_scheduler_lease_takeover(tmp_path: Path):
    settings, _engine, SessionLocal, scheduler, _workflows, admin_id, root_id = _env(tmp_path)
    created = _index_schedule(scheduler, admin_id, root_id)

    first = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-a",
        now_utc=_dt(12, 1, 5),
    )
    assert first.dispatched == 1

    # Simulate a crashed owner plus a stale recurrence pointer. Even after lease
    # takeover the durable unique slot identity must remain the final fence.
    with SessionLocal() as session:
        schedule = session.get(Schedule, created["id"])
        state = session.get(SchedulerState, 1)
        assert schedule is not None and state is not None
        schedule.next_scheduled_for_utc = _dt(12, 1)
        state.lease_expires_at = _dt(12, 1, 10)
        session.commit()

    takeover = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-b",
        now_utc=_dt(12, 1, 20),
    )
    assert takeover.lease_acquired is True
    assert takeover.duplicate_slots == 1
    assert takeover.dispatched == 0

    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(ScheduleRun)) == 1
        assert session.scalar(select(func.count()).select_from(WorkJob)) == 1


def test_orphaned_pending_run_is_recovered_before_overlap(tmp_path: Path):
    settings, _engine, SessionLocal, scheduler, _workflows, admin_id, root_id = _env(tmp_path)
    created = _index_schedule(scheduler, admin_id, root_id)

    # S1's durable reservation helper can represent an interrupted historical
    # dispatch. S2's atomic path never commits pending, so a durable unbound
    # pending row is orphaned recovery state and must not block forever.
    orphan = scheduler.reserve_scheduled_slot(
        created["id"],
        _dt(12, 1),
        created_at=_dt(12, 1, 1),
    )
    assert orphan is not None
    assert orphan["status"] == "pending"
    assert orphan["work_job_id"] is None

    recovered = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-recovery",
        now_utc=_dt(12, 2, 5),
    )
    assert recovered.dispatched == 1
    assert recovered.skipped_overlap == 0

    with SessionLocal() as session:
        runs = list(session.scalars(select(ScheduleRun).order_by(ScheduleRun.id)))
        assert len(runs) == 2
        assert runs[0].status == "failed"
        assert runs[0].error_code == "SCHEDULER_DISPATCH_INTERRUPTED"
        assert runs[0].work_job_id is None
        assert runs[1].status == "dispatched"
        assert session.scalar(select(func.count()).select_from(WorkJob)) == 1


def test_schedule_run_and_workjob_linkage_metadata_remain_consistent(tmp_path: Path):
    settings, _engine, SessionLocal, scheduler, _workflows, admin_id, root_id = _env(tmp_path)
    created = _index_schedule(scheduler, admin_id, root_id)

    result = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-linkage",
        now_utc=_dt(12, 1, 5),
    )
    assert result.dispatched == 1

    with SessionLocal() as session:
        run = session.scalar(select(ScheduleRun))
        work = session.scalar(select(WorkJob))
        assert run is not None and work is not None
        assert run.work_job_id == work.id
        assert run.schedule_id == created["id"]
        state = json.loads(work.state_json)
        scheduler_meta = state["scheduler"]
        assert scheduler_meta["schedule_id"] == run.schedule_id
        assert scheduler_meta["schedule_revision"] == run.schedule_revision
        assert scheduler_meta["schedule_run_id"] == run.id
        assert scheduler_meta["scheduled_for_utc"] == _dt(12, 1).isoformat()


def test_pinned_workflow_recovers_only_after_explicit_rebind(tmp_path: Path):
    settings, _engine, SessionLocal, scheduler, workflows, admin_id, root_id = _env(tmp_path)
    workflow = workflows.create_workflow(
        admin_id,
        WorkflowCreateRequest(
            name="S5 pinned workflow",
            definition=WorkflowDefinition.model_validate(
                {
                    "schema_version": 1,
                    "mode": "file",
                    "steps": [
                        {"id": "scan", "type": "scan", "root_ids": [root_id]},
                        {
                            "id": "rename",
                            "type": "rename",
                            "pattern": "movie",
                            "replacement": "film",
                        },
                    ],
                }
            ),
        ),
    )

    bad_target = {
        "type": "workflow",
        "workflow_id": workflow["id"],
        "workflow_revision": workflow["current_revision"],
        "definition_sha256": "0" * 64,
        "action": "preview",
        "runtime_inputs": None,
    }
    created = scheduler.create_schedule(
        admin_id,
        ScheduleCreate.model_validate(
            {
                "name": "Pinned recovery",
                "target": bad_target,
                "cron_expression": "* * * * *",
                "timezone": "UTC",
            }
        ),
        now_utc=_dt(12, 0, 5),
    )

    stale = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-workflow-recovery",
        now_utc=_dt(12, 1, 5),
    )
    assert stale.failed == 1

    correct_target = dict(bad_target)
    correct_target["definition_sha256"] = workflow["definition_sha256"]
    rebound = scheduler.update_schedule(
        created["id"],
        ScheduleUpdate.model_validate(
            {
                "expected_revision": 1,
                "target": correct_target,
            }
        ),
        now_utc=_dt(12, 1, 10),
    )
    assert rebound["revision"] == 2

    recovered = run_scheduler_tick(
        SessionLocal,
        settings,
        owner="worker-workflow-recovery",
        now_utc=_dt(12, 2, 5),
    )
    assert recovered.dispatched == 1

    with SessionLocal() as session:
        runs = list(session.scalars(select(ScheduleRun).order_by(ScheduleRun.id)))
        works = list(session.scalars(select(WorkJob).order_by(WorkJob.id)))
        assert [row.status for row in runs] == ["failed", "dispatched"]
        assert len(works) == 1
        assert works[0].kind == "workflow-scheduled"
        state = json.loads(works[0].state_json)
        assert state["scheduler"]["schedule_revision"] == 2
        assert state["workflow_revision"] == workflow["current_revision"]
        assert state["definition_sha256"] == workflow["definition_sha256"]
