import json
import os
from pathlib import Path
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import Settings
from app.main import create_app
from app.models import (
    BatchPlan,
    BatchPlanItem,
    OperationJournal,
    QuarantineEntry,
    TaskLock,
    WorkJob,
    utcnow,
)
from app.service import FileCenterService
from app.tasks.context import JobContext
from app.tasks.handlers import get_handler


def _acquire_lease(service: FileCenterService, worker_id: str):
    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1, locked=True, owner=worker_id, acquired_at=utcnow())
            session.add(lock)
        else:
            lock.locked = True
            lock.owner = worker_id
            lock.acquired_at = utcnow()
        session.commit()


def _setup_app_and_service(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    trash_dir = data_dir / ".nas-file-center-trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = config_dir / "app.db"

    settings = Settings(
        config_dir=config_dir,
        database_path=db_path,
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
        quarantine_root=trash_dir,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    app = create_app(settings)
    client = TestClient(app)

    resp = client.post("/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"})
    assert resp.status_code == 200
    client.headers.update({"Origin": "http://testserver"})

    service: FileCenterService = app.state.service
    return client, service, settings, data_dir, trash_dir


def test_worker_executes_batch_plan_and_writes_journal(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)
    file1 = data_dir / "file1.txt"
    file1.write_text("content 1", encoding="utf-8")
    target1 = data_dir / "file1_renamed.txt"

    file2 = data_dir / "file2.txt"
    file2.write_text("content 2", encoding="utf-8")

    file3 = data_dir / "file3.txt"
    file3.write_text("content 3", encoding="utf-8")
    past_mtime_ns = 1_600_000_000_000_000_000

    plan = service.create_plan(
        name="Worker Plan 1",
        kind="organize",
        items=[
            {"source": str(file1), "target": str(target1), "operation": "rename"},
            {"source": str(file2), "operation": "quarantine"},
            {"source": str(file3), "operation": "touch", "expected_mtime_ns": past_mtime_ns},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    enqueue_res = client.post(f"/api/plans/{plan.id}/execute")
    assert enqueue_res.status_code == 200
    job_id = enqueue_res.json()["work_job_id"]

    # Execute with BatchPlanExecuteHandler
    handler = get_handler("batch-plan-execute")
    assert handler is not None, "BatchPlanExecuteHandler must be registered for batch-plan-execute"

    _acquire_lease(service, "test-worker-1")
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="test-worker-1")
        handler.run(job, context, settings)

    # Verify filesystem mutations
    assert not file1.exists()
    assert target1.exists()
    assert target1.read_text(encoding="utf-8") == "content 1"

    assert not file2.exists()
    # Check quarantine target path uses task-<job_id>
    with service.SessionLocal() as session:
        q_entry = session.scalar(select(QuarantineEntry).where(QuarantineEntry.original_path == str(file2)))
        assert q_entry is not None
        assert q_entry.state == "active"
        assert f"task-{job_id}" in q_entry.quarantine_path
        assert Path(q_entry.quarantine_path).exists()
        assert Path(q_entry.quarantine_path).read_text(encoding="utf-8") == "content 2"

        # Check touch
        st3 = file3.stat()
        mtime_ns = getattr(st3, "st_mtime_ns", int(st3.st_mtime * 1e9))
        assert mtime_ns == past_mtime_ns

        # Verify OperationJournal
        journals = list(session.scalars(
            select(OperationJournal).where(OperationJournal.plan_id == plan.id).order_by(OperationJournal.sequence)
        ))
        assert len(journals) == 3
        # Rename journal
        assert journals[0].operation == "rename"
        assert journals[0].sequence == 1
        assert journals[0].task_id == job_id
        after0 = json.loads(journals[0].after_json)
        assert after0["path"] == str(target1)

        # Quarantine journal
        assert journals[1].operation == "quarantine"
        assert journals[1].sequence == 2
        assert journals[1].task_id == job_id
        after1 = json.loads(journals[1].after_json)
        assert after1["quarantine_path"] == q_entry.quarantine_path

        # Touch journal
        assert journals[2].operation == "touch"
        assert journals[2].sequence == 3
        after2 = json.loads(journals[2].after_json)
        assert after2["mtime_ns"] == past_mtime_ns

        # Plan status must be completed
        refreshed_plan = session.get(BatchPlan, plan.id)
        assert refreshed_plan.status == "completed"


def test_worker_safe_pause_and_resume(tmp_path: Path):
    client, service, settings, data_dir, _ = _setup_app_and_service(tmp_path)
    file1 = data_dir / "pause_f1.txt"
    file1.write_text("c1", encoding="utf-8")
    target1 = data_dir / "pause_f1_moved.txt"

    file2 = data_dir / "pause_f2.txt"
    file2.write_text("c2", encoding="utf-8")
    target2 = data_dir / "pause_f2_moved.txt"

    plan = service.create_plan(
        name="Pause Plan",
        kind="organize",
        items=[
            {"source": str(file1), "target": str(target1), "operation": "rename"},
            {"source": str(file2), "target": str(target2), "operation": "rename"},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    enqueue_res = client.post(f"/api/plans/{plan.id}/execute")
    job_id = enqueue_res.json()["work_job_id"]

    handler = get_handler("batch-plan-execute")
    assert handler is not None

    _acquire_lease(service, "worker-p")
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="worker-p")

        # Request pause right after first item
        original_checkpoint = context.checkpoint
        call_count = [0]
        from app.tasks.state_machine import JobPauseRequested
        def mock_checkpoint(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 3:  # boundary before item 2
                raise JobPauseRequested("Simulated pause request")
            return original_checkpoint(*args, **kwargs)
        context.checkpoint = mock_checkpoint

        with pytest.raises(JobPauseRequested):
            handler.run(job, context, settings)

    # First item moved, second item NOT moved
    assert target1.exists()
    assert not file1.exists()
    assert file2.exists()
    assert not target2.exists()

    # Plan items status
    with service.SessionLocal() as session:
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)))
        assert items[0].state == "completed"
        assert items[1].state == "validated"

        # Now resume
        _acquire_lease(service, "worker-p")
        job = session.get(WorkJob, job_id)
        job.status = "running"
        session.commit()

        context2 = JobContext(service.engine, service.SessionLocal, job.id, worker_id="worker-p")
        handler.run(job, context2, settings)

    # Both items now completed
    assert target2.exists()
    assert not file2.exists()
    with service.SessionLocal() as session:
        refreshed_plan = session.get(BatchPlan, plan.id)
        assert refreshed_plan.status == "completed"


def test_crash_recovery_reconciles_interrupted_item(tmp_path: Path):
    client, service, settings, data_dir, _ = _setup_app_and_service(tmp_path)
    file1 = data_dir / "crash_f1.txt"
    file1.write_text("content crash", encoding="utf-8")
    target1 = data_dir / "crash_f1_moved.txt"

    plan = service.create_plan(
        name="Crash Plan",
        kind="organize",
        items=[
            {"source": str(file1), "target": str(target1), "operation": "rename"},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    enqueue_res = client.post(f"/api/plans/{plan.id}/execute")
    job_id = enqueue_res.json()["work_job_id"]

    # Simulate crash: item is in "executing" state, but file was physically moved before worker died!
    file1.rename(target1)
    with service.SessionLocal() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id))
        item.state = "executing"
        session.commit()

    # Now new worker picks up job and runs
    handler = get_handler("batch-plan-execute")
    _acquire_lease(service, "worker-recover")
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        job.status = "running"
        session.commit()

        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="worker-recover")
        handler.run(job, context, settings)

    # Check that item was reconciled to completed and journal was recorded
    with service.SessionLocal() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id))
        assert item.state == "completed"
        assert "reconciled" in item.reason.lower()

        journals = list(session.scalars(select(OperationJournal).where(OperationJournal.plan_id == plan.id)))
        assert len(journals) == 1
        assert journals[0].operation == "rename"
