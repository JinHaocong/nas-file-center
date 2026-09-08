import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.main import create_app
from app.models import (
    Base,
    IndexRoot,
    IndexedPath,
    BatchPlan,
    BatchPlanItem,
    WorkJob,
    QuarantineEntry,
    TaskLock,
    User,
    utcnow,
)
from app.auth.password import hash_password
from app.config import Settings
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


@pytest.fixture
def lifecycle_test_env(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()

    db_path = config_dir / "app.db"
    settings = Settings(
        config_dir=config_dir,
        reports_dir=tmp_path / "reports",
        backups_dir=tmp_path / "backups",
        logs_dir=tmp_path / "logs",
        fclones_home=tmp_path / "fclones",
        database_path=db_path,
        allowed_roots_raw=f"{data_dir},{quarantine_dir}",
        quarantine_root=quarantine_dir,
        protect_last_file=True,
        allow_mutation=True,
        allow_delete=True,
    )

    service = FileCenterService(settings)
    app = create_app(settings)
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"

    with service.SessionLocal() as session:
        reg_user = User(
            username="adminuser",
            password_hash=hash_password("AdminPass123!"),
            is_active=True,
            role="admin",
        )
        session.add(reg_user)
        session.commit()

    login_resp = client.post(
        "/api/auth/login",
        json={"username": "adminuser", "password": "AdminPass123!"},
    )
    assert login_resp.status_code == 200

    return {
        "service": service,
        "settings": settings,
        "client": client,
        "data_dir": data_dir,
        "quarantine_dir": quarantine_dir,
    }


def test_gate5e_e1_worker_last_file_fence_preserved(lifecycle_test_env):
    service = lifecycle_test_env["service"]
    settings = lifecycle_test_env["settings"]
    client = lifecycle_test_env["client"]
    data_dir = lifecycle_test_env["data_dir"]

    root_dir = data_dir / "root1"
    sub_dir = root_dir / "dirA"
    sub_dir.mkdir(parents=True)

    file1 = sub_dir / "file1.txt"
    file1.write_text("file 1 content")
    file2 = sub_dir / "file2.txt"
    file2.write_text("file 2 content")

    st1 = file1.stat()
    st2 = file2.stat()

    with service.SessionLocal() as session:
        r = IndexRoot(id=1, root=str(root_dir))
        session.add(r)
        session.commit()

        p1 = IndexedPath(
            root_key=str(root_dir),
            absolute_path=str(file1),
            relative_path="dirA/file1.txt",
            basename=file1.name,
            stem=file1.stem,
            suffix=".txt",
            size=st1.st_size,
            mtime_ns=st1.st_mtime_ns,
            device=st1.st_dev,
            inode=st1.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        p2 = IndexedPath(
            root_key=str(root_dir),
            absolute_path=str(file2),
            relative_path="dirA/file2.txt",
            basename=file2.name,
            stem=file2.stem,
            suffix=".txt",
            size=st2.st_size,
            mtime_ns=st2.st_mtime_ns,
            device=st2.st_dev,
            inode=st2.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        session.add_all([p1, p2])
        session.commit()

    # 1. Preview
    prev_resp = client.post("/api/batch-utilities/preview", json={
        "action": {
            "type": "quarantine_filtered",
            "root_ids": [1],
            "filter": {"field": "extension", "operator": "eq", "value": "txt"},
        },
    })
    assert prev_resp.status_code == 200
    digest = prev_resp.json()["preview_digest"]

    # 2. Generate Draft
    gen_resp = client.post("/api/batch-utilities/generate-plan", json={
        "action": {
            "type": "quarantine_filtered",
            "root_ids": [1],
            "filter": {"field": "extension", "operator": "eq", "value": "txt"},
        },
        "expected_preview_digest": digest,
    })
    assert gen_resp.status_code == 201
    plan_id = gen_resp.json()["plan_id"]

    # Freeze & Validate
    service.freeze_plan(plan_id)
    val_res = service.validate_plan(plan_id)
    assert val_res["status"] == "ready"

    # Now simulate race before execution: remove sibling file2.txt from disk
    # This leaves file1.txt as the ONLY remaining regular file in dirA!
    file2.unlink()
    assert not file2.exists()
    assert file1.exists()

    # Enqueue execution
    enqueue_res = client.post(f"/api/plans/{plan_id}/execute")
    assert enqueue_res.status_code == 200
    job_id = enqueue_res.json()["work_job_id"]

    handler = get_handler("batch-plan-execute")
    assert handler is not None

    _acquire_lease(service, "worker-1")
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="worker-1")
        handler.run(job, context, settings)

    # After execution:
    # file1.txt MUST remain on disk because the final fence protected it as the last file in dirA!
    assert file1.exists(), "file1.txt should have been preserved by the final last-file fence!"

    with service.SessionLocal() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert item.state == "skipped"
        assert "protected directory last file" in (item.reason or "")

        # 0 active quarantine entry for file1
        qe = session.scalar(select(QuarantineEntry).where(QuarantineEntry.original_path == str(file1)))
        assert qe is None or qe.state != "active"


def test_gate5e_e1_draft_lifecycle_end_to_end(lifecycle_test_env):
    service = lifecycle_test_env["service"]
    settings = lifecycle_test_env["settings"]
    client = lifecycle_test_env["client"]
    data_dir = lifecycle_test_env["data_dir"]

    root_dir = data_dir / "root_e2e"
    sub_dir = root_dir / "dirB"
    sub_dir.mkdir(parents=True)

    file_a = sub_dir / "a.txt"
    file_a.write_text("file A content")
    file_b = sub_dir / "b.txt"
    file_b.write_text("file B content")

    st_a = file_a.stat()
    st_b = file_b.stat()

    with service.SessionLocal() as session:
        r = IndexRoot(id=10, root=str(root_dir))
        session.add(r)
        session.commit()

        p_a = IndexedPath(
            root_key=str(root_dir),
            absolute_path=str(file_a),
            relative_path="dirB/a.txt",
            basename=file_a.name,
            stem=file_a.stem,
            suffix=".txt",
            size=st_a.st_size,
            mtime_ns=st_a.st_mtime_ns,
            device=st_a.st_dev,
            inode=st_a.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        p_b = IndexedPath(
            root_key=str(root_dir),
            absolute_path=str(file_b),
            relative_path="dirB/b.txt",
            basename=file_b.name,
            stem=file_b.stem,
            suffix=".txt",
            size=st_b.st_size,
            mtime_ns=st_b.st_mtime_ns,
            device=st_b.st_dev,
            inode=st_b.st_ino,
            is_dir=False,
            scan_generation=1,
        )
        session.add_all([p_a, p_b])
        session.commit()

    # 1. Preview
    prev_resp = client.post("/api/batch-utilities/preview", json={
        "action": {
            "type": "quarantine_filtered",
            "root_ids": [10],
            "filter": {"field": "extension", "operator": "eq", "value": "txt"},
        },
    })
    assert prev_resp.status_code == 200
    digest = prev_resp.json()["preview_digest"]

    # 2. Generate Draft
    gen_resp = client.post("/api/batch-utilities/generate-plan", json={
        "action": {
            "type": "quarantine_filtered",
            "root_ids": [10],
            "filter": {"field": "extension", "operator": "eq", "value": "txt"},
        },
        "expected_preview_digest": digest,
    })
    assert gen_resp.status_code == 201
    plan_id = gen_resp.json()["plan_id"]

    # 3. Assert physical identity snapshot is placeholder immediately after generate
    with service.SessionLocal() as session:
        items = session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id)).all()
        assert len(items) == 1
        it = items[0]
        assert it.expected_device == 0
        assert it.expected_inode == 0
        assert it.expected_mtime_ns == 0
        assert it.expected_hash is None

    # 4. Freeze plan -> captures live physical snapshot
    freeze_res = service.freeze_plan(plan_id)
    with service.SessionLocal() as session:
        it = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert it.expected_mtime_ns > 0
        assert it.expected_device > 0
        assert it.expected_inode > 0

    # 5. Validate plan
    val_res = service.validate_plan(plan_id)
    assert val_res["status"] == "ready"

    # 6. Execute plan
    enqueue_res = client.post(f"/api/plans/{plan_id}/execute")
    assert enqueue_res.status_code == 200
    job_id = enqueue_res.json()["work_job_id"]

    handler = get_handler("batch-plan-execute")
    _acquire_lease(service, "worker-1")
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="worker-1")
        handler.run(job, context, settings)
        job.status = "completed"
        job.completed_at = utcnow()
        session.commit()

    # 7. File A was quarantined
    assert not file_a.exists()
    assert file_b.exists()

    with service.SessionLocal() as session:
        qe = session.scalar(select(QuarantineEntry).where(QuarantineEntry.original_path == str(file_a)))
        assert qe is not None
        assert qe.state == "active"
        q_path = Path(qe.quarantine_path)
        assert q_path.exists()
        assert q_path.read_text() == "file A content"

    # 8. Create undo plan and restore
    undo_info = service.create_undo_plan(plan_id)
    undo_plan_id = undo_info["id"]

    service.freeze_plan(undo_plan_id)
    service.validate_plan(undo_plan_id)

    undo_enqueue = client.post(f"/api/plans/{undo_plan_id}/execute")
    undo_job_id = undo_enqueue.json()["work_job_id"]

    _acquire_lease(service, "worker-1")
    with service.SessionLocal() as session:
        job = session.get(WorkJob, undo_job_id)
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id="worker-1")
        handler.run(job, context, settings)
        job.status = "completed"
        job.completed_at = utcnow()
        session.commit()

    # 9. Original path restored
    assert file_a.exists()
    assert file_a.read_text() == "file A content"
    with service.SessionLocal() as session:
        qe = session.scalar(select(QuarantineEntry).where(QuarantineEntry.original_path == str(file_a)))
        assert qe.state == "restored"
