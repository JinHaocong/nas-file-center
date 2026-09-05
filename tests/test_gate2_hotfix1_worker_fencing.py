import json
from pathlib import Path
import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import (
    BatchPlan,
    BatchPlanItem,
    QuarantineEntry,
    TaskLock,
    WorkJob,
    utcnow,
)
from app.service import FileCenterService
from app.tasks.context import JobContext
from app.tasks.handlers import get_handler
from app.tasks.recovery import JobLeaseLost


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
    trash_dir = data_dir / ".trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        config_dir=config_dir,
        database_path=config_dir / "app.db",
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
    client.post("/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"}, headers={"Origin": "http://testserver"})
    service = FileCenterService(settings)
    return client, service, data_dir, trash_dir, settings


def test_lease_loss_after_intent_before_fs_causes_zero_fs_mutation(tmp_path: Path, monkeypatch):
    """
    BLOCKER 1:
    Old worker commits Phase 1 intent.
    Before filesystem mutation (execute_item), lease is lost to new-worker.
    Expected:
    - Old worker raises JobLeaseLost at mutation boundary
    - Source remains on disk
    - Target is absent
    - Zero filesystem mutation
    - Zero DB finalization
    """
    client, service, data_dir, trash_dir, settings = _setup(tmp_path)
    src_file = data_dir / "fence_source.txt"
    src_file.write_text("critical data", encoding="utf-8")
    target_file = data_dir / "fence_target.txt"

    plan = service.create_plan(
        name="Fence Test Plan",
        kind="organize",
        items=[{"source": str(src_file), "target": str(target_file), "operation": "rename"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    enqueue_res = client.post(f"/api/plans/{plan.id}/execute", headers={"Origin": "http://testserver"})
    assert enqueue_res.status_code == 200
    job_id = enqueue_res.json()["work_job_id"]

    old_worker_id = "worker-old"
    _acquire_lease(service, old_worker_id)

    import app.tasks.handlers as handlers_mod
    original_execute_item = handlers_mod.execute_item
    execute_item_called = False

    def wrapped_execute_item(*args, **kwargs):
        nonlocal execute_item_called
        execute_item_called = True
        return original_execute_item(*args, **kwargs)

    monkeypatch.setattr(handlers_mod, "execute_item", wrapped_execute_item)

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    context = JobContext(engine=service.engine, session_factory=service.SessionLocal, job_id=job_id, worker_id=old_worker_id)
    handler = get_handler(job.kind)

    phase1_done = False
    real_session_class = service.SessionLocal

    class FencingInterceptSession:
        def __init__(self, real_sess):
            self._sess = real_sess

        def __enter__(self):
            return self._sess.__enter__()

        def __exit__(self, exc_type, exc_val, exc_tb):
            res = self._sess.__exit__(exc_type, exc_val, exc_tb)
            nonlocal phase1_done
            if not phase1_done:
                with real_session_class() as s:
                    row = s.query(BatchPlanItem).filter_by(plan_id=plan.id).first()
                    if row and row.state == "executing":
                        phase1_done = True
                        _acquire_lease(service, "worker-new")
            return res

        def __getattr__(self, name):
            return getattr(self._sess, name)

    monkeypatch.setattr(context, "SessionLocal", lambda: FencingInterceptSession(real_session_class()))

    with pytest.raises(JobLeaseLost):
        handler.run(job, context, settings)

    assert execute_item_called is False, "execute_item MUST NOT be called if lease was lost before filesystem mutation!"
    assert src_file.exists(), "Source file MUST remain untouched!"
    assert not target_file.exists(), "Target file MUST NOT be created!"

    with service.SessionLocal() as session:
        row = session.query(BatchPlanItem).filter_by(plan_id=plan.id).first()
        assert row.state == "executing", "Old worker must not finalize to completed"


def test_quarantine_hash_runs_without_sqlite_write_transaction(tmp_path: Path, monkeypatch):
    """
    BLOCKER 6:
    Hash calculation on quarantine target must happen outside SQLite write transaction.
    """
    client, service, data_dir, trash_dir, settings = _setup(tmp_path)
    src_file = data_dir / "hash_outside.txt"
    src_file.write_text("hash data payload", encoding="utf-8")

    plan = service.create_plan(
        name="Hash Test Plan",
        kind="dedupe",
        items=[{"source": str(src_file), "operation": "quarantine", "expected_size": len("hash data payload")}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    enqueue_res = client.post(f"/api/plans/{plan.id}/execute", headers={"Origin": "http://testserver"})
    assert enqueue_res.status_code == 200
    job_id = enqueue_res.json()["work_job_id"]

    worker_id = "worker-hasher"
    _acquire_lease(service, worker_id)

    import app.tasks.handlers as handlers_mod
    original_hash = handlers_mod.safe_quarantine_hash
    hash_verified_outside_tx = False

    def wrapped_hash(path):
        nonlocal hash_verified_outside_tx
        with service.SessionLocal() as concurrent_session:
            concurrent_session.execute(text("BEGIN IMMEDIATE"))
            concurrent_session.execute(text("SELECT 1"))
            concurrent_session.commit()
        hash_verified_outside_tx = True
        return original_hash(path)

    monkeypatch.setattr(handlers_mod, "safe_quarantine_hash", wrapped_hash)

    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)

    context = JobContext(engine=service.engine, session_factory=service.SessionLocal, job_id=job_id, worker_id=worker_id)
    handler = get_handler(job.kind)
    handler.run(job, context, settings)

    assert hash_verified_outside_tx is True, "safe_quarantine_hash must run without an active SQLite write transaction!"
