import json
import os
from pathlib import Path
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, OperationJournal, TaskLock, WorkJob, utcnow
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


def _setup(tmp_path: Path):
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
        reports_dir=tmp_path / "reports",
        backups_dir=tmp_path / "backups",
        logs_dir=tmp_path / "logs",
        fclones_home=tmp_path / "fclones",
        secret_key="test-secret",
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    app = create_app(settings)
    service = app.state.service
    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"})
    assert resp.status_code == 200
    client.headers.update({"Origin": "http://testserver"})
    return client, service, settings, data_dir, trash_dir


def test_touch_crash_reconciliation_does_not_retouch(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup(tmp_path)
    file1 = data_dir / "touch_me.txt"
    file1.write_text("touch content", encoding="utf-8")

    # Set initial mtime to 1000 seconds in the past
    t0_ns = int((time.time() - 1000) * 1e9)
    os.utime(file1, ns=(t0_ns, t0_ns))

    intended_t1_ns = int((time.time() - 500) * 1e9)

    # Create plan with touch operation
    with service.SessionLocal() as session:
        plan = BatchPlan(
            name="Touch Plan",
            kind="organize",
            status="ready",
            expected_changes=1,
            expected_reclaim_bytes=0,
            metadata_json="{}",
            created_at=utcnow(),
        )
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="touch",
            source_path=str(file1),
            target_path=None,
            expected_size=len("touch content"),
            expected_mtime_ns=intended_t1_ns,
            state="executing",
            metadata_json=json.dumps({
                "execution": {
                    "phase": "intent",
                    "source_stat": {
                        "object_type": "file",
                        "size": len("touch content"),
                        "mtime_ns": t0_ns,
                    },
                    "target_mtime_ns": intended_t1_ns,
                }
            }),
        )
        session.add(item)
        session.flush()

        job = WorkJob(
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps({"plan_id": plan.id}),
            created_at=utcnow(),
        )
        session.add(job)
        session.commit()
        plan_id = plan.id
        job_id = job.id
        item_id = item.id

    # Simulate that physical touch took place before crash: mtime is now intended_t1_ns
    os.utime(file1, ns=(intended_t1_ns, intended_t1_ns))
    stat_before_recovery = file1.stat()
    assert getattr(stat_before_recovery, "st_mtime_ns", int(stat_before_recovery.st_mtime * 1e9)) == intended_t1_ns

    # Worker crashes and new worker recovers
    handler = get_handler("batch-plan-execute")
    _acquire_lease(service, "recovery-worker")
    with service.SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        context = JobContext(service.engine, service.SessionLocal, j.id, worker_id="recovery-worker")
        handler.run(j, context, settings)

    # Verify that file mtime was NOT changed again!
    stat_after_recovery = file1.stat()
    actual_mtime_ns = getattr(stat_after_recovery, "st_mtime_ns", int(stat_after_recovery.st_mtime * 1e9))
    assert actual_mtime_ns == intended_t1_ns, f"Expected {intended_t1_ns}, got {actual_mtime_ns} (file was retouched!)"

    with service.SessionLocal() as session:
        recovered_item = session.get(BatchPlanItem, item_id)
        assert recovered_item.state == "completed"
        assert "reconciled" in recovered_item.reason.lower()

        journal = session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == item_id))
        assert journal is not None
        assert journal.operation == "touch"


def test_durable_execution_intent_and_journal_metadata(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup(tmp_path)
    file1 = data_dir / "journal_meta.txt"
    file1.write_text("metadata content", encoding="utf-8")
    target1 = data_dir / "journal_meta_renamed.txt"

    res = client.post("/api/plans", json={
        "name": "Rename Metadata Plan",
        "kind": "reorganize",
        "items": [
            {
                "operation": "rename",
                "source": str(file1),
                "target": str(target1),
            }
        ],
    })
    plan_id = res.json()["id"]
    client.post(f"/api/plans/{plan_id}/freeze")
    client.post(f"/api/plans/{plan_id}/validate")
    res = client.post(f"/api/plans/{plan_id}/execute")
    task_id = res.json()["work_job_id"]

    _acquire_lease(service, "worker-meta")
    with service.SessionLocal() as session:
        job = session.get(WorkJob, task_id)
        job.status = "running"
        session.commit()
        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="worker-meta")
        handler = get_handler(job.kind)
        handler.run(job, context, settings)

    with service.SessionLocal() as session:
        journal = session.scalar(select(OperationJournal).where(OperationJournal.plan_id == plan_id))
        assert journal is not None
        assert journal.metadata_before_json != "{}"
        assert journal.metadata_after_json != "{}"

        meta_b = json.loads(journal.metadata_before_json)
        meta_a = json.loads(journal.metadata_after_json)

        assert "size" in meta_b
        assert "mtime_ns" in meta_b
        assert "device" in meta_b
        assert "inode" in meta_b
        assert meta_b.get("object_type") == "file"

        assert "size" in meta_a
        assert "mtime_ns" in meta_a
