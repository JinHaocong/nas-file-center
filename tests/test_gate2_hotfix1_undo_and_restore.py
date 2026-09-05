import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import BatchPlanItem, OperationJournal, QuarantineEntry, TaskLock, User, WorkJob, utcnow
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


def _run_job(service: FileCenterService, job_id: int, settings: Settings, worker_id: str = "test-worker-1"):
    _acquire_lease(service, worker_id)
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id=worker_id)
        handler = get_handler(job.kind)
        handler.run(job, context, settings)

        job.status = "completed"
        job.finished_at = utcnow()
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


def test_client_cannot_create_arbitrary_restore_plan(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup(tmp_path)
    file1 = data_dir / "file1.txt"
    file1.write_text("hello", encoding="utf-8")

    res = client.post("/api/plans", json={
        "name": "Malicious Restore Plan",
        "kind": "reorganize",
        "items": [
            {
                "operation": "restore",
                "source": str(file1),
                "target": str(data_dir / "file1_restored.txt"),
            }
        ]
    })
    # Should be rejected with 400
    assert res.status_code == 400
    assert "restore" in res.text


def test_undo_quarantine_creates_restore_operation_and_updates_quarantine_entry(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup(tmp_path)
    target_file = data_dir / "to_quarantine.txt"
    target_file.write_text("important data", encoding="utf-8")

    # Create quarantine plan
    res = client.post("/api/plans", json={
        "name": "Quarantine Plan",
        "kind": "dedupe",
        "items": [
            {
                "operation": "quarantine",
                "source": str(target_file),
            }
        ]
    })
    assert res.status_code == 200
    plan_id = res.json()["id"]

    # Freeze, validate and execute plan
    res = client.post(f"/api/plans/{plan_id}/freeze")
    assert res.status_code == 200
    res = client.post(f"/api/plans/{plan_id}/validate")
    assert res.status_code == 200
    res = client.post(f"/api/plans/{plan_id}/execute")
    assert res.status_code == 200
    task_id = res.json()["work_job_id"]

    # Run worker to process quarantine
    _run_job(service, task_id, settings)
    assert not target_file.exists()

    with service.SessionLocal() as session:
        q_entry = session.scalar(select(QuarantineEntry).where(QuarantineEntry.original_path == str(target_file)))
        assert q_entry is not None
        assert q_entry.state == "active"
        q_entry_id = q_entry.id

    # Create undo plan
    res = client.post(f"/api/plans/{plan_id}/undo-plan")
    assert res.status_code == 200
    undo_plan_id = res.json()["id"]

    # Check undo plan items
    with service.SessionLocal() as session:
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == undo_plan_id)))
        assert len(items) == 1
        assert items[0].operation == "restore"
        meta = json.loads(items[0].metadata_json)
        assert meta.get("quarantine_entry_id") == q_entry_id

    # Freeze, validate and execute undo plan
    res = client.post(f"/api/plans/{undo_plan_id}/freeze")
    assert res.status_code == 200
    res = client.post(f"/api/plans/{undo_plan_id}/validate")
    assert res.status_code == 200
    res = client.post(f"/api/plans/{undo_plan_id}/execute")
    assert res.status_code == 200
    undo_task_id = res.json()["work_job_id"]

    # Run worker to process restore
    _run_job(service, undo_task_id, settings)
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == "important data"

    # Verify QuarantineEntry is now restored!
    with service.SessionLocal() as session:
        q = session.get(QuarantineEntry, q_entry_id)
        assert q.state == "restored"
        assert q.restored_at is not None

        # Verify OperationJournal has operation="restore"
        journals = list(session.scalars(
            select(OperationJournal).where(OperationJournal.plan_id == undo_plan_id)
        ))
        assert len(journals) == 1
        assert journals[0].operation == "restore"


def test_direct_restore_journal_actor_and_no_fake_linkage(tmp_path: Path):
    client, service, settings, data_dir, trash_dir = _setup(tmp_path)
    target_file = data_dir / "direct_restore_me.txt"
    target_file.write_text("direct restore content", encoding="utf-8")

    # Quarantine via plan
    res = client.post("/api/plans", json={
        "name": "Direct Q Plan",
        "kind": "dedupe",
        "items": [{"operation": "quarantine", "source": str(target_file)}],
    })
    plan_id = res.json()["id"]
    client.post(f"/api/plans/{plan_id}/freeze")
    client.post(f"/api/plans/{plan_id}/validate")
    res = client.post(f"/api/plans/{plan_id}/execute")
    task_id = res.json()["work_job_id"]
    _run_job(service, task_id, settings)

    with service.SessionLocal() as session:
        q_entry = session.scalar(select(QuarantineEntry).where(QuarantineEntry.original_path == str(target_file)))
        q_entry_id = q_entry.id
        admin_user = session.scalar(select(User).where(User.username == "admin"))
        admin_id = admin_user.id

    # Call direct restore API
    res = client.post(f"/api/quarantine/{q_entry_id}/restore", json={})
    assert res.status_code == 200

    with service.SessionLocal() as session:
        # Check latest journal entry
        journal = session.scalar(
            select(OperationJournal)
            .where(OperationJournal.operation == "restore")
            .order_by(OperationJournal.id.desc())
        )
        assert journal is not None
        assert journal.plan_id is None, "Direct restore must have plan_id=None"
        assert journal.plan_item_id is None, "Direct restore must have plan_item_id=None"
        assert journal.task_id is None, "Direct restore must have task_id=None"
        assert journal.user_id == admin_id, f"Direct restore must record actor user_id={admin_id}, got {journal.user_id}"
