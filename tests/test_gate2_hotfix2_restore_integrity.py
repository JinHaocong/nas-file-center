from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
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


def test_undo_restore_rejects_tampered_quarantine_content(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)
    src = data_dir / "important.txt"
    src.write_text("pristine content", encoding="utf-8")

    # 1. Quarantine file via plan
    plan = service.create_plan(
        name="Quarantine Test",
        kind="organize",
        items=[{"operation": "quarantine", "source": str(src)}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # Enqueue and execute
    enqueue_res = client.post(f"/api/plans/{plan.id}/execute")
    assert enqueue_res.status_code == 200
    job_id = enqueue_res.json()["work_job_id"]

    handler = get_handler("batch-plan-execute")
    _acquire_lease(service, "test-worker-1")

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        job.status = "running"
        job.started_at = utcnow()
        session.commit()
        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="test-worker-1")
        handler.run(job, context, settings)
        job.status = "completed"
        job.completed_at = utcnow()
        session.commit()

    assert not src.exists()

    with service.SessionLocal() as session:
        q_entry = session.scalar(select(QuarantineEntry).where(QuarantineEntry.original_path == str(src)))
        assert q_entry is not None
        assert q_entry.state == "active"
        assert q_entry.content_hash is not None
        q_path = Path(q_entry.quarantine_path)
        assert q_path.exists()

    # 2. Tamper with the quarantined file on disk (same length 16 bytes)!
    q_path.write_text("tampered content", encoding="utf-8")

    # 3. Create undo plan
    undo_info = service.create_undo_plan(plan.id)
    undo_plan_id = undo_info["id"]
    service.freeze_plan(undo_plan_id)
    service.validate_plan(undo_plan_id)

    # 4. Enqueue undo execution
    undo_enqueue = client.post(f"/api/plans/{undo_plan_id}/execute")
    assert undo_enqueue.status_code == 200
    undo_job_id = undo_enqueue.json()["work_job_id"]

    _acquire_lease(service, "test-worker-1")
    with service.SessionLocal() as session:
        undo_job = session.get(WorkJob, undo_job_id)
        undo_job.status = "running"
        undo_job.started_at = utcnow()
        session.commit()
        context = JobContext(service.engine, service.SessionLocal, undo_job.id, worker_id="test-worker-1")
        handler.run(undo_job, context, settings)

    # 6. VERIFY INTEGRITY GUARANTEES:
    # - Original path MUST NOT be restored with tampered content!
    assert not src.exists(), "Original path must NOT be restored with tampered content!"
    # - Quarantined file remains in quarantine
    assert q_path.exists()
    # - QuarantineEntry marked inconsistent with error
    with service.SessionLocal() as session:
        q_entry_after = session.get(QuarantineEntry, q_entry.id)
        assert q_entry_after.state == "inconsistent"
        assert "Hash verification failed" in (q_entry_after.last_error or "")
        
        # Plan item must be failed
        item = session.scalar(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == undo_plan_id)
        )
        assert item.state == "failed"

        # No successful OperationJournal written for this restore
        restore_j = session.scalars(
            select(OperationJournal).where(
                OperationJournal.plan_id == undo_plan_id,
                OperationJournal.operation == "restore",
            )
        ).all()
        assert len(restore_j) == 0


def test_undo_restore_rejects_symlink_quarantine_target(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)
    src = data_dir / "target_symlink.txt"
    src.write_text("hello world", encoding="utf-8")

    plan = service.create_plan(
        name="Quarantine Test Symlink",
        kind="organize",
        items=[{"operation": "quarantine", "source": str(src)}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    enqueue_res = client.post(f"/api/plans/{plan.id}/execute")
    job_id = enqueue_res.json()["work_job_id"]
    handler = get_handler("batch-plan-execute")
    _acquire_lease(service, "test-worker-1")

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        job.status = "running"
        job.started_at = utcnow()
        session.commit()
        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="test-worker-1")
        handler.run(job, context, settings)
        job.status = "completed"
        job.completed_at = utcnow()
        session.commit()

    with service.SessionLocal() as session:
        q_entry = session.scalar(select(QuarantineEntry).where(QuarantineEntry.original_path == str(src)))
        q_path = Path(q_entry.quarantine_path)

    # Replace quarantine file with a symlink!
    dummy = tmp_path / "dummy.txt"
    dummy.write_text("dummy")
    q_path.unlink()
    q_path.symlink_to(dummy)

    undo_info = service.create_undo_plan(plan.id)
    undo_plan_id = undo_info["id"]
    service.freeze_plan(undo_plan_id)
    service.validate_plan(undo_plan_id)

    undo_enqueue = client.post(f"/api/plans/{undo_plan_id}/execute")
    undo_job_id = undo_enqueue.json()["work_job_id"]

    _acquire_lease(service, "test-worker-1")
    with service.SessionLocal() as session:
        undo_job = session.get(WorkJob, undo_job_id)
        undo_job.status = "running"
        undo_job.started_at = utcnow()
        session.commit()
        context = JobContext(service.engine, service.SessionLocal, undo_job.id, worker_id="test-worker-1")
        handler.run(undo_job, context, settings)

    assert not src.exists()
    with service.SessionLocal() as session:
        q_entry_after = session.get(QuarantineEntry, q_entry.id)
        assert q_entry_after.state == "inconsistent"
        assert "symlink" in (q_entry_after.last_error or "").lower()

        item = session.scalar(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == undo_plan_id)
        )
        assert item.state == "failed"


def test_plan_validation_checks_quarantine_entry_for_restore(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)
    src = data_dir / "valid_test.txt"
    src.write_text("test content", encoding="utf-8")

    plan = service.create_plan(
        name="Quarantine Validate Test",
        kind="organize",
        items=[{"operation": "quarantine", "source": str(src)}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    enqueue_res = client.post(f"/api/plans/{plan.id}/execute")
    job_id = enqueue_res.json()["work_job_id"]
    handler = get_handler("batch-plan-execute")
    _acquire_lease(service, "test-worker-1")

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        job.status = "running"
        job.started_at = utcnow()
        session.commit()
        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="test-worker-1")
        handler.run(job, context, settings)
        job.status = "completed"
        job.completed_at = utcnow()
        session.commit()

    with service.SessionLocal() as session:
        q_entry = session.scalar(select(QuarantineEntry).where(QuarantineEntry.original_path == str(src)))
        # Mark entry as purged / non-active
        q_entry.state = "purged"
        session.commit()

    undo_info = service.create_undo_plan(plan.id)
    undo_plan_id = undo_info["id"]
    service.freeze_plan(undo_plan_id)
    val_res = service.validate_plan(undo_plan_id)

    # Validation must NOT mark plan ready because quarantine entry is not active
    assert val_res["status"] == "partial"
    with service.SessionLocal() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == undo_plan_id))
        assert item.state == "skipped"
        assert "not active" in (item.reason or "")

