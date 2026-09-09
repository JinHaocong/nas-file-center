import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.main import create_app
from app.models import Base, IndexRoot, IndexedPath, BatchPlan, BatchPlanItem, WorkJob, QuarantineEntry
from app.config import Settings
from app.service import FileCenterService
from app.auth.password import hash_password
from app.models import User

@pytest.fixture
def api_test_env(tmp_path):
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
        allowed_roots_raw=str(data_dir),
        quarantine_root=quarantine_dir,
        protect_last_file=True,
    )

    service = FileCenterService(settings)

    root1_path = data_dir / "root1"
    root1_path.mkdir()

    with service.SessionLocal() as session:
        r = IndexRoot(id=1, root=str(root1_path))
        session.add(r)
        session.commit()
        reg_user = User(
            username="normaluser",
            password_hash=hash_password("UserPassword123!"),
            is_active=True,
            role="user",
        )
        session.add(reg_user)
        session.commit()

    app = create_app(settings)
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "normaluser", "password": "UserPassword123!"},
    )
    assert login_resp.status_code == 200

    return {
        "service": service,
        "settings": settings,
        "client": client,
        "data_dir": data_dir,
        "root1_path": root1_path,
    }
import pytest
from httpx import AsyncClient
from app.tasks.handlers import get_handler
from app.tasks.context import JobContext
from app.models import utcnow
from app.models import WorkJob, TaskLock
import errno
from unittest.mock import patch

def _acquire_lease(service, worker_id):
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

def run_job_sync(service, settings, job_id):
    handler = get_handler("batch-plan-execute")
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

def test_lifecycle_flatten_file_and_dir(api_test_env):
    service = api_test_env["service"]
    settings = api_test_env["settings"]
    settings.allow_mutation = True
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    
    wrapper = root / "wrapper"
    wrapper.mkdir()
    
    # File
    file_path = wrapper / "a.txt"
    file_path.write_text("a")
    
    # Directory
    dir_path = wrapper / "b_dir"
    dir_path.mkdir()
    (dir_path / "child.txt").write_text("b")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    # 1. Preview
    resp = client.post("/api/batch-utilities/preview", json={"action": action, "page": 1, "page_size": 50})
    assert resp.status_code == 200, resp.text
    preview_digest = resp.json()["preview_digest"]
    
    # 2. Generate (Freeze / Validate)
    req = {
        "action": action,
        "expected_preview_digest": preview_digest
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 201, resp.text
    plan_id = resp.json()["id"]
    
    # Initialize worker lease once
    try:
        _acquire_lease(service, "worker-1")
    except Exception:
        pass
    
    # 3. Execute
    service.freeze_plan(plan_id)
    service.validate_plan(plan_id)
    resp = client.post(f"/api/plans/{plan_id}/execute")
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["work_job_id"]
    
    run_job_sync(service, settings, job_id)
    
    # Verify executed
    from app.models import BatchPlanItem, WorkJob; 
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        
        for it in session.query(BatchPlanItem).filter_by(plan_id=plan_id):
            print("ITEM STATE:", it.state, it.operation, it.reason)
    assert (root / "a.txt").exists()
    assert (root / "b_dir").exists()
    assert (root / "b_dir" / "child.txt").exists()
    assert not file_path.exists()
    assert not dir_path.exists()
    
    # 4. Undo
    undo_info = service.create_undo_plan(plan_id)
    undo_plan_id = undo_info["id"]
    
    service.freeze_plan(undo_plan_id)
    service.validate_plan(undo_plan_id)
    resp = client.post(f"/api/plans/{undo_plan_id}/execute")
    assert resp.status_code == 200, resp.text
    undo_job_id = resp.json()["work_job_id"]
    
    run_job_sync(service, settings, undo_job_id)
    
    # Verify undone
    assert not (root / "a.txt").exists()
    assert not (root / "b_dir").exists()
    assert file_path.exists()
    assert dir_path.exists()

def test_lifecycle_flatten_exdev_fail_closed(api_test_env):
    service = api_test_env["service"]
    settings = api_test_env["settings"]
    settings.allow_mutation = True
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    
    wrapper = root / "wrapper2"
    wrapper.mkdir()
    file_path = wrapper / "a.txt"
    file_path.write_text("a")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    resp = client.post("/api/batch-utilities/preview", json={"action": action, "page": 1, "page_size": 50})
    assert resp.status_code == 200, resp.text
    
    req = {
        "action": action,
        "expected_preview_digest": resp.json()["preview_digest"]
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 201, resp.text
    plan_id = resp.json()["id"]
    
    try:
        _acquire_lease(service, "worker-1")
    except Exception:
        pass
        
    service.freeze_plan(plan_id)
    service.validate_plan(plan_id)
    resp = client.post(f"/api/plans/{plan_id}/execute")
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["work_job_id"]
    
    handler = get_handler("batch-plan-execute")
    with patch("app.fs_ops.rename_noreplace", side_effect=OSError(errno.EXDEV, "Invalid cross-device link")):
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
            
    # Verify exdev failed closed: source remains, target absent
    assert file_path.exists()
    assert not (root / "a.txt").exists()
