import hashlib
import json
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, WorkJob, utcnow, TaskLock
from app.quarantine.capability import MutationCapability
from app.service import FileCenterService
from app.tasks.context import JobContext
from app.tasks.handlers import BatchPlanExecuteHandler


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


def test_transaction_engine_conflict_not_overwritten_by_phase3(tmp_path, monkeypatch):
    """
    HOTFIX1 Requirement 3:
    When transaction engine enters conflict, generic Phase 3 MUST NOT overwrite
    QuarantineEntry state to 'abandoned' or 'inconsistent'. Entry must remain conflict/conflict.
    """
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)

    import app.quarantine.capability as cap_module
    monkeypatch.setattr(cap_module, "resolve_mutation_capability", lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL)

    src_file = data_dir / "conflict_test.txt"
    payload = b"GENUINE_BEFORE_TAMPER"
    src_file.write_bytes(payload)
    st = os.stat(src_file)

    plan = service.create_plan(
        name="test_conflict_plan",
        kind="organize",
        items=[{"source": str(src_file), "operation": "quarantine", "expected_hash": hashlib.sha256(payload).hexdigest()}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    res = client.post(f"/api/plans/{plan.id}/execute")
    assert res.status_code == 200
    job_id = res.json()["work_job_id"]

    # Hook execute_transactional_quarantine to tamper file right before Gate3 qualification
    import app.quarantine.engine as engine_module
    real_exec_tx_q = engine_module.execute_transactional_quarantine

    def hooked_exec_tx_q(*args, **kwargs):
        src_file.write_bytes(b"TAMPERED_CONTENT_CAUSES_CONFLICT")
        return real_exec_tx_q(*args, **kwargs)

    monkeypatch.setattr(engine_module, "execute_transactional_quarantine", hooked_exec_tx_q)

    worker_id = "test-worker-1"
    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner=worker_id, acquired_at=utcnow())
        session.add(lock)
        job = session.get(WorkJob, job_id)
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

    context = JobContext(service.engine, service.SessionLocal, job_id, worker_id=worker_id)
    handler = BatchPlanExecuteHandler()
    handler.run(job, context, settings)

    with service.SessionLocal() as session:
        q_entry = session.scalar(select(QuarantineEntry).where(QuarantineEntry.original_path == str(src_file)))
        assert q_entry is not None
        # MUST remain conflict/conflict, NEVER abandoned or inconsistent
        assert q_entry.state == "conflict", f"Expected conflict, got {q_entry.state}"
        assert q_entry.tx_phase == "conflict", f"Expected tx_phase conflict, got {q_entry.tx_phase}"


def test_public_view_replacement_does_not_alter_db_authority(tmp_path, monkeypatch):
    """
    HOTFIX1 Requirement 3:
    Public view replacement after engine success must NOT rewrite DB authority
    (device, inode, size, content_hash) during generic finalize.
    """
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)

    import app.quarantine.capability as cap_module
    monkeypatch.setattr(cap_module, "resolve_mutation_capability", lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL)

    src_file = data_dir / "authority_test.txt"
    payload = b"AUTHORITATIVE_CONTENT"
    src_file.write_bytes(payload)
    st = os.stat(src_file)
    expected_dev = st.st_dev
    expected_ino = st.st_ino
    expected_size = len(payload)
    expected_hash = hashlib.sha256(payload).hexdigest()

    plan = service.create_plan(
        name="test_authority_plan",
        kind="organize",
        items=[{"source": str(src_file), "operation": "quarantine", "expected_hash": expected_hash}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    res = client.post(f"/api/plans/{plan.id}/execute")
    assert res.status_code == 200
    job_id = res.json()["work_job_id"]

    worker_id = "test-worker-1"
    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner=worker_id, acquired_at=utcnow())
        session.add(lock)
        job = session.get(WorkJob, job_id)
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

    # We hook execute_transactional_quarantine to replace public view right before Phase 3
    import app.quarantine.engine as engine_module
    real_exec_tx_q = engine_module.execute_transactional_quarantine

    def hooked_exec_tx_q(*args, **kwargs):
        real_exec_tx_q(*args, **kwargs)
        # Directly replace the public view file with a foreign file!
        with service.SessionLocal() as s:
            e = s.get(QuarantineEntry, args[1])
            p_path = Path(e.quarantine_path)
            os.unlink(p_path)
            p_path.write_bytes(b"FOREIGN_PUBLIC_VIEW_REPLACEMENT")

    monkeypatch.setattr(engine_module, "execute_transactional_quarantine", hooked_exec_tx_q)

    context = JobContext(service.engine, service.SessionLocal, job_id, worker_id=worker_id)
    handler = BatchPlanExecuteHandler()
    handler.run(job, context, settings)

    with service.SessionLocal() as session:
        q_entry = session.scalar(select(QuarantineEntry).where(QuarantineEntry.original_path == str(src_file)))
        assert q_entry is not None
        # Must retain original authoritative identity, NOT foreign public view identity
        assert q_entry.size == expected_size
        assert q_entry.content_hash == expected_hash
        assert q_entry.device == expected_dev
        assert q_entry.inode == expected_ino
