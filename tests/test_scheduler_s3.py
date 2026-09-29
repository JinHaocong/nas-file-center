from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, inspect, select, text

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import (
    Base,
    BatchPlan,
    IndexRoot,
    IndexedPath,
    Schedule,
    ScheduleRun,
    User,
    WorkJob,
)
from app.scheduler.dispatch import run_scheduler_tick
from app.scheduler.schema import ScheduleCreate
from app.scheduler.service import SchedulerService
from app.tasks.recovery import acquire_worker_ownership, claim_next_job
from app.worker import process_work_job
from app.workflows.schema import (
    WorkflowCreateRequest,
    WorkflowDefinition,
    WorkflowUpdateRequest,
)
from app.workflows.service import WorkflowService


UTC = timezone.utc


def _dt(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 9, 29, hour, minute, second, tzinfo=UTC)


def _env(tmp_path: Path):
    config = tmp_path / "config"
    data = tmp_path / "data"
    media = data / "media"
    config.mkdir()
    media.mkdir(parents=True)

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
    )
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path, backups_dir=settings.backups_dir)

    with SessionLocal() as session:
        admin = User(
            username="scheduler-s3-admin",
            password_hash="hash",
            role="admin",
            is_active=True,
        )
        session.add(admin)
        session.flush()

        root = IndexRoot(root=str(media))
        session.add(root)
        session.flush()

        source = media / "movie1.mkv"
        source.write_text("movie-data")
        stat = source.stat()
        indexed = IndexedPath(
            root_key=str(media),
            absolute_path=str(source),
            relative_path="movie1.mkv",
            basename="movie1.mkv",
            stem="movie1",
            suffix=".mkv",
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            device=stat.st_dev,
            inode=stat.st_ino,
            is_dir=False,
            scan_generation="s3",
        )
        session.add(indexed)
        session.commit()
        admin_id = int(admin.id)
        root_id = int(root.id)

    return (
        settings,
        engine,
        SessionLocal,
        SchedulerService(SessionLocal),
        WorkflowService(SessionLocal, settings),
        admin_id,
        root_id,
    )


def _file_workflow(
    workflow_service: WorkflowService,
    admin_id: int,
    root_id: int,
    *,
    replacement: str = "film",
) -> dict:
    definition = WorkflowDefinition.model_validate(
        {
            "schema_version": 1,
            "mode": "file",
            "steps": [
                {"id": "scan", "type": "scan", "root_ids": [root_id]},
                {
                    "id": "rename",
                    "type": "rename",
                    "pattern": "movie",
                    "replacement": replacement,
                },
            ],
        }
    )
    return workflow_service.create_workflow(
        admin_id,
        WorkflowCreateRequest(
            name="Pinned workflow",
            description="Scheduler S3",
            definition=definition,
        ),
    )


def _workflow_schedule(
    scheduler: SchedulerService,
    admin_id: int,
    workflow: dict,
    *,
    action: str,
    created_at: datetime = _dt(12, 0, 5),
) -> dict:
    return scheduler.create_schedule(
        admin_id,
        ScheduleCreate.model_validate(
            {
                "name": f"Scheduled {action}",
                "target": {
                    "type": "workflow",
                    "workflow_id": workflow["id"],
                    "workflow_revision": workflow["current_revision"],
                    "definition_sha256": workflow["definition_sha256"],
                    "action": action,
                    "runtime_inputs": None,
                },
                "cron_expression": "* * * * *",
                "timezone": "UTC",
            }
        ),
        now_utc=created_at,
    )


def _dispatch_one(
    SessionLocal,
    settings: Settings,
    *,
    owner: str = "scheduler-s3",
):
    result = run_scheduler_tick(
        SessionLocal,
        settings,
        owner=owner,
        now_utc=_dt(12, 1, 5),
    )
    assert result.due_seen == 1
    return result


def test_s3_migrates_old_schedule_constraint_with_backup_and_preserves_rows(tmp_path: Path):
    db_file = tmp_path / "legacy-s2.db"
    backups = tmp_path / "backups"
    legacy_engine = create_engine(f"sqlite:///{db_file}")

    # Build every current table except Scheduler tables, then install the exact
    # pre-S3 schedules CHECK manually.
    legacy_tables = [
        table
        for table in Base.metadata.sorted_tables
        if table.name not in {"schedules", "schedule_runs", "scheduler_state"}
    ]
    Base.metadata.create_all(legacy_engine, tables=legacy_tables)

    with legacy_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE schedules (
                    id INTEGER NOT NULL PRIMARY KEY,
                    name VARCHAR(128) NOT NULL,
                    description TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL,
                    target_type VARCHAR(64) NOT NULL,
                    target_json TEXT NOT NULL,
                    cron_expression VARCHAR(128) NOT NULL,
                    timezone VARCHAR(64) NOT NULL,
                    overlap_policy VARCHAR(32) NOT NULL,
                    missed_run_policy VARCHAR(32) NOT NULL,
                    created_by_user_id INTEGER,
                    revision INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    last_scheduled_for_utc DATETIME,
                    next_scheduled_for_utc DATETIME,
                    CONSTRAINT ck_schedules_target_type CHECK (
                        target_type IN (
                            'index_root',
                            'fclones_scan',
                            'media_analysis',
                            'media_integrity_verification'
                        )
                    ),
                    CONSTRAINT ck_schedules_overlap_policy CHECK (
                        overlap_policy = 'skip_if_active'
                    ),
                    CONSTRAINT ck_schedules_missed_run_policy CHECK (
                        missed_run_policy = 'skip'
                    ),
                    CONSTRAINT ck_schedules_revision CHECK (revision >= 1),
                    FOREIGN KEY(created_by_user_id)
                        REFERENCES users (id) ON DELETE SET NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO schedules (
                    id, name, description, enabled, target_type, target_json,
                    cron_expression, timezone, overlap_policy,
                    missed_run_policy, created_by_user_id, revision,
                    created_at, updated_at, last_scheduled_for_utc,
                    next_scheduled_for_utc
                ) VALUES (
                    7, 'legacy index', '', 1, 'index_root',
                    '{"type":"index_root","root_id":1}',
                    '0 * * * *', 'UTC', 'skip_if_active', 'skip',
                    NULL, 3, '2026-09-29 00:00:00',
                    '2026-09-29 00:00:00', NULL,
                    '2026-09-29 01:00:00'
                )
                """
            )
        )
    legacy_engine.dispose()

    engine, SessionLocal = create_engine_and_session(db_file)
    init_db(engine, db_path=db_file, backups_dir=backups)

    assert list(backups.glob("nas-file-center-*.db"))

    inspector = inspect(engine)
    target_check = next(
        item
        for item in inspector.get_check_constraints("schedules")
        if item.get("name") == "ck_schedules_target_type"
    )
    assert "'workflow'" in str(target_check.get("sqltext"))

    with SessionLocal() as session:
        legacy = session.get(Schedule, 7)
        assert legacy is not None
        assert legacy.name == "legacy index"
        assert legacy.revision == 3

        workflow_target_row = Schedule(
            name="workflow target writable",
            description="",
            enabled=False,
            target_type="workflow",
            target_json=json.dumps(
                {
                    "type": "workflow",
                    "workflow_id": 1,
                    "workflow_revision": 1,
                    "definition_sha256": "a" * 64,
                    "action": "preview",
                    "runtime_inputs": None,
                }
            ),
            cron_expression="0 * * * *",
            timezone="UTC",
            overlap_policy="skip_if_active",
            missed_run_policy="skip",
            revision=1,
        )
        session.add(workflow_target_row)
        session.commit()
        assert workflow_target_row.id is not None


def test_preview_schedule_is_pinned_and_creates_no_plan(tmp_path: Path):
    (
        settings,
        engine,
        SessionLocal,
        scheduler,
        workflows,
        admin_id,
        root_id,
    ) = _env(tmp_path)
    workflow = _file_workflow(workflows, admin_id, root_id, replacement="film")
    schedule = _workflow_schedule(scheduler, admin_id, workflow, action="preview")

    # Update the Workflow after binding. The schedule must remain pinned to r1.
    updated_definition = WorkflowDefinition.model_validate(
        {
            "schema_version": 1,
            "mode": "file",
            "steps": [
                {"id": "scan", "type": "scan", "root_ids": [root_id]},
                {
                    "id": "rename",
                    "type": "rename",
                    "pattern": "movie",
                    "replacement": "cinema",
                },
            ],
        }
    )
    updated = workflows.update_workflow(
        admin_id,
        workflow["id"],
        WorkflowUpdateRequest(
            expected_current_revision=1,
            definition=updated_definition,
        ),
    )
    assert updated["current_revision"] == 2

    dispatched = _dispatch_one(SessionLocal, settings)
    assert dispatched.dispatched == 1

    with SessionLocal() as session:
        work = session.scalar(select(WorkJob))
        run = session.scalar(select(ScheduleRun))
        assert work is not None and run is not None
        assert work.kind == "workflow-scheduled"
        state = json.loads(work.state_json)
        assert state["workflow_revision"] == 1
        assert state["definition_sha256"] == workflow["definition_sha256"]
        assert state["scheduler"]["schedule_id"] == schedule["id"]
        work_id = int(work.id)

    assert process_work_job(
        settings,
        work_id,
        session_factory=SessionLocal,
        engine=engine,
    )

    with SessionLocal() as session:
        work = session.get(WorkJob, work_id)
        assert work is not None
        assert work.status == "completed"
        checkpoint = json.loads(work.checkpoint_json)
        assert checkpoint["phase"] == "completed"
        assert checkpoint["action"] == "preview"
        assert checkpoint["plan_id"] is None
        assert checkpoint["preview"]["workflow_revision"] == 1
        assert (
            checkpoint["preview"]["definition_sha256"]
            == workflow["definition_sha256"]
        )
        assert session.scalar(select(func.count()).select_from(BatchPlan)) == 0


def test_draft_schedule_creates_draft_only_and_never_execute_job(tmp_path: Path):
    (
        settings,
        engine,
        SessionLocal,
        scheduler,
        workflows,
        admin_id,
        root_id,
    ) = _env(tmp_path)
    workflow = _file_workflow(workflows, admin_id, root_id)
    _workflow_schedule(scheduler, admin_id, workflow, action="draft")

    dispatched = _dispatch_one(SessionLocal, settings)
    assert dispatched.dispatched == 1

    with SessionLocal() as session:
        work = session.scalar(select(WorkJob))
        assert work is not None
        work_id = int(work.id)

    assert process_work_job(
        settings,
        work_id,
        session_factory=SessionLocal,
        engine=engine,
    )

    with SessionLocal() as session:
        work = session.get(WorkJob, work_id)
        assert work is not None and work.status == "completed"
        checkpoint = json.loads(work.checkpoint_json)
        assert checkpoint["phase"] == "completed"
        assert checkpoint["action"] == "draft"
        assert checkpoint["plan_status"] == "draft"
        assert checkpoint["auto_freeze"] is False
        assert checkpoint["auto_validate"] is False
        assert checkpoint["auto_execute"] is False

        plan = session.get(BatchPlan, int(checkpoint["plan_id"]))
        assert plan is not None
        assert plan.status == "draft"
        metadata = json.loads(plan.metadata_json)
        assert metadata["workflow_revision"] == 1
        assert metadata["definition_sha256"] == workflow["definition_sha256"]

        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkJob)
                .where(WorkJob.kind == "batch-plan-execute")
            )
            == 0
        )


def test_archived_or_sha_mismatched_workflow_fails_before_workjob(tmp_path: Path):
    (
        settings,
        _engine,
        SessionLocal,
        scheduler,
        workflows,
        admin_id,
        root_id,
    ) = _env(tmp_path)
    workflow = _file_workflow(workflows, admin_id, root_id)
    _workflow_schedule(scheduler, admin_id, workflow, action="preview")

    workflows.archive_workflow(admin_id, workflow["id"], expected_current_revision=1)
    result = _dispatch_one(SessionLocal, settings)
    assert result.failed == 1

    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(WorkJob)) == 0
        run = session.scalar(select(ScheduleRun))
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == "SCHEDULE_TARGET_INVALID"


def test_sha_mismatch_fails_closed_before_workjob(tmp_path: Path):
    (
        settings,
        _engine,
        SessionLocal,
        scheduler,
        workflows,
        admin_id,
        root_id,
    ) = _env(tmp_path)
    workflow = _file_workflow(workflows, admin_id, root_id)
    bad = dict(workflow)
    bad["definition_sha256"] = "0" * 64
    _workflow_schedule(scheduler, admin_id, bad, action="preview")

    result = _dispatch_one(SessionLocal, settings)
    assert result.failed == 1
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(WorkJob)) == 0


def test_utility_draft_is_rejected_without_workjob(tmp_path: Path):
    (
        settings,
        _engine,
        SessionLocal,
        scheduler,
        workflows,
        admin_id,
        root_id,
    ) = _env(tmp_path)

    utility = workflows.create_workflow(
        admin_id,
        WorkflowCreateRequest(
            name="Utility preview only",
            definition=WorkflowDefinition.model_validate(
                {
                    "schema_version": 1,
                    "mode": "utility",
                    "steps": [
                        {
                            "id": "collapse",
                            "type": "single_child_wrapper_collapse",
                            "root_id": root_id,
                            "subpath": "",
                        }
                    ],
                }
            ),
        ),
    )
    _workflow_schedule(scheduler, admin_id, utility, action="draft")

    result = _dispatch_one(SessionLocal, settings)
    assert result.failed == 1

    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(WorkJob)) == 0
        assert session.scalar(select(func.count()).select_from(BatchPlan)) == 0


def test_resource_policy_pause_holds_scheduled_workflow_job(tmp_path: Path):
    (
        settings,
        engine,
        SessionLocal,
        scheduler,
        workflows,
        admin_id,
        root_id,
    ) = _env(tmp_path)
    workflow = _file_workflow(workflows, admin_id, root_id)
    _workflow_schedule(scheduler, admin_id, workflow, action="preview")

    result = _dispatch_one(SessionLocal, settings)
    assert result.dispatched == 1

    from app.models import ResourcePolicy

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

    from unittest.mock import patch

    with patch("app.tasks.recovery.utcnow", return_value=_dt(12, 1, 20)):
        assert acquire_worker_ownership(
            engine,
            SessionLocal,
            worker_id="workflow-policy-worker",
        )
        assert (
            claim_next_job(
                engine,
                SessionLocal,
                worker_id="workflow-policy-worker",
            )
            is None
        )

    with SessionLocal() as session:
        work = session.scalar(select(WorkJob))
        assert work is not None
        assert work.kind == "workflow-scheduled"
        assert work.status == "queued"
