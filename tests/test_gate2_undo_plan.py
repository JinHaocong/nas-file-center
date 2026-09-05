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


def test_undo_plan_generation_and_execution_restores_files(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)
    file1 = data_dir / "orig1.txt"
    file1.write_text("orig content 1", encoding="utf-8")
    target1 = data_dir / "renamed1.txt"

    file2 = data_dir / "orig2.txt"
    file2.write_text("orig content 2", encoding="utf-8")

    file3 = data_dir / "orig3.txt"
    file3.write_text("orig content 3", encoding="utf-8")
    past_mtime_ns = 1_500_000_000_000_000_000
    # Set initial mtime of file3
    import os
    os.utime(file3, ns=(past_mtime_ns, past_mtime_ns))

    # Create and execute original plan
    plan = service.create_plan(
        name="Original Plan",
        kind="organize",
        items=[
            {"source": str(file1), "target": str(target1), "operation": "rename"},
            {"source": str(file2), "operation": "quarantine"},
            {"source": str(file3), "operation": "touch", "expected_mtime_ns": 1_700_000_000_000_000_000},
        ],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    res = client.post(f"/api/plans/{plan.id}/execute")
    job_id = res.json()["work_job_id"]

    handler = get_handler("batch-plan-execute")
    _acquire_lease(service, "worker-undo-test")
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        job.status = "running"
        session.commit()
        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="worker-undo-test")
        handler.run(job, context, settings)
        job.status = "completed"
        session.commit()

    # Verify original mutations occurred
    assert not file1.exists()
    assert target1.exists()
    assert not file2.exists()

    # Call Undo Plan API
    undo_resp = client.post(f"/api/plans/{plan.id}/undo-plan")
    assert undo_resp.status_code == 200, undo_resp.text
    undo_data = undo_resp.json()
    undo_plan_id = undo_data["id"]
    assert undo_data["kind"] == "undo"
    assert undo_data["status"] == "draft"

    # Verify 0 mutations occurred during undo-plan generation
    assert not file1.exists()
    assert target1.exists()
    assert not file2.exists()

    # Inspect undo plan items: must be in reverse order of operations!
    with service.SessionLocal() as session:
        undo_items = list(session.scalars(
            select(BatchPlanItem).where(BatchPlanItem.plan_id == undo_plan_id).order_by(BatchPlanItem.sequence)
        ))
        assert len(undo_items) == 3
        # First undo item is reverse of touch (seq 3 -> 1)
        assert undo_items[0].operation == "touch"
        assert undo_items[0].source_path == str(file3)
        assert undo_items[0].expected_mtime_ns == past_mtime_ns

        # Second undo item is reverse of quarantine (seq 2 -> 2): moving from quarantine path back to file2
        assert undo_items[1].target_path == str(file2)
        assert "task-" in undo_items[1].source_path or ".q-" in undo_items[1].source_path

        # Third undo item is reverse of rename (seq 1 -> 3): target1 -> file1
        assert undo_items[2].operation in ("rename", "move")
        assert undo_items[2].source_path == str(target1)
        assert undo_items[2].target_path == str(file1)

    # Now freeze, validate and execute the undo plan!
    service.freeze_plan(undo_plan_id)
    service.validate_plan(undo_plan_id)

    undo_exec_res = client.post(f"/api/plans/{undo_plan_id}/execute")
    assert undo_exec_res.status_code == 200
    undo_job_id = undo_exec_res.json()["work_job_id"]

    _acquire_lease(service, "worker-undo-test")
    with service.SessionLocal() as session:
        undo_job = session.get(WorkJob, undo_job_id)
        undo_job.status = "running"
        session.commit()
        context2 = JobContext(service.engine, service.SessionLocal, undo_job.id, worker_id="worker-undo-test")
        handler.run(undo_job, context2, settings)
        undo_job.status = "completed"
        session.commit()

    # Verify all files are restored!
    assert file1.exists()
    assert file1.read_text(encoding="utf-8") == "orig content 1"
    assert not target1.exists()

    assert file2.exists()
    assert file2.read_text(encoding="utf-8") == "orig content 2"

    st3 = file3.stat()
    assert getattr(st3, "st_mtime_ns", int(st3.st_mtime * 1e9)) == past_mtime_ns


def test_operation_journal_apis(tmp_path: Path):
    client, service, settings, data_dir, _ = _setup_app_and_service(tmp_path)
    file1 = data_dir / "j1.txt"
    file1.write_text("j1", encoding="utf-8")
    target1 = data_dir / "j1_renamed.txt"

    plan = service.create_plan(
        name="Journal Query Plan",
        kind="organize",
        items=[{"source": str(file1), "target": str(target1), "operation": "rename"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    res = client.post(f"/api/plans/{plan.id}/execute")
    job_id = res.json()["work_job_id"]

    handler = get_handler("batch-plan-execute")
    _acquire_lease(service, "worker-j")
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        job.status = "running"
        session.commit()
        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="worker-j")
        handler.run(job, context, settings)
        job.status = "completed"
        session.commit()

    # 1. Global list
    resp1 = client.get("/api/operation-journal")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["total"] >= 1
    assert any(item["plan_id"] == plan.id for item in data1["items"])

    # 2. Filter by plan_id
    resp2 = client.get(f"/api/plans/{plan.id}/operation-journal")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["total"] == 1
    item = data2["items"][0]
    assert item["operation"] == "rename"
    assert item["plan_id"] == plan.id
    assert item["task_id"] == job_id
    assert "path" in item["before"]
    assert "path" in item["after"]


def test_quarantine_restore_records_operation_journal(tmp_path: Path):
    client, service, settings, data_dir, _ = _setup_app_and_service(tmp_path)
    file_q = data_dir / "test_q.txt"
    file_q.write_text("quarantine test", encoding="utf-8")

    plan = service.create_plan(
        name="Quarantine Direct Test Plan",
        kind="organize",
        items=[{"source": str(file_q), "operation": "quarantine"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    res = client.post(f"/api/plans/{plan.id}/execute")
    job_id = res.json()["work_job_id"]

    handler = get_handler("batch-plan-execute")
    _acquire_lease(service, "worker-q")
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        job.status = "running"
        session.commit()
        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="worker-q")
        handler.run(job, context, settings)
        job.status = "completed"
        session.commit()

    # Find the quarantine entry id
    with service.SessionLocal() as session:
        q_entry = session.scalar(select(QuarantineEntry).where(QuarantineEntry.original_path == str(file_q)))
        assert q_entry is not None
        eid = q_entry.id

    # Restore via API
    rest_resp = client.post(f"/api/quarantine/{eid}/restore", json={"conflict_policy": "rename"})
    assert rest_resp.status_code == 200, rest_resp.text

    # Verify OperationJournal has a 'restore' entry
    with service.SessionLocal() as session:
        j = session.scalar(select(OperationJournal).where(OperationJournal.operation == "restore"))
        assert j is not None
        before = json.loads(j.before_json)
        after = json.loads(j.after_json)
        assert before["quarantine_entry_id"] == eid
        assert "restored_path" in after

