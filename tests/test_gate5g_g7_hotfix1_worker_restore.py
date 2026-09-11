import errno
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


def test_real_worker_compat_restore_uses_transactional_restore(tmp_path, monkeypatch):
    """
    HOTFIX1 Requirement 2:
    Actual BatchPlan restore on COMPAT must use execute_transactional_restore,
    retire public view to captured_quarantine_view, publish authoritative anchor,
    and advance to restored.
    """
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)

    import app.quarantine.capability as cap_module
    monkeypatch.setattr(cap_module, "resolve_mutation_capability", lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL)

    # Setup source payload and transaction directories
    orig_path = data_dir / "restored_target.txt"
    pub_path = trash_dir / "public_view.txt"
    payload = b"RESTORE_TRANSACTIONAL_TEST_PAYLOAD"
    pub_path.write_bytes(payload)

    st = os.stat(pub_path)
    expected_dev = st.st_dev
    expected_ino = st.st_ino
    expected_size = len(payload)
    expected_hash = hashlib.sha256(payload).hexdigest()

    tx_dir = trash_dir / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True, exist_ok=True)
    anchor_path = tx_dir / "anchor"
    os.link(str(pub_path), str(anchor_path))

    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        q_entry = QuarantineEntry(
            id=1,
            original_path=str(orig_path),
            quarantine_path=str(pub_path),
            state="active",
            tx_phase="active",
            authoritative_anchor_path=str(anchor_path),
            active_attempt_generation=1,
            size=expected_size,
            content_hash=expected_hash,
            device=expected_dev,
            inode=expected_ino,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(q_entry)

        plan = BatchPlan(name="restore_plan", kind="organize", status="frozen")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="restore",
            source_path=str(pub_path),
            target_path=str(orig_path),
            state="planned",
            expected_device=expected_dev,
            expected_inode=expected_ino,
            expected_size=expected_size,
            expected_hash=expected_hash,
            metadata_json=json.dumps({"quarantine_entry_id": 1}),
        )
        session.add(item)
        session.commit()
        plan_id = plan.id

    service.validate_plan(plan_id)
    res = client.post(f"/api/plans/{plan_id}/execute")
    assert res.status_code == 200
    job_id = res.json()["work_job_id"]

    worker_id = "test-worker-1"
    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1, locked=True, owner=worker_id, acquired_at=utcnow())
            session.add(lock)
        else:
            lock.locked = True
            lock.owner = worker_id
            lock.acquired_at = utcnow()
        job = session.get(WorkJob, job_id)
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

    context = JobContext(service.engine, service.SessionLocal, job_id, worker_id=worker_id)
    handler = BatchPlanExecuteHandler()
    with service.SessionLocal() as session:
        job_inst = session.get(WorkJob, job_id)
        handler.run(job_inst, context, settings)

    with service.SessionLocal() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert item.state == "completed", f"Plan item failed: {item.reason}"

        q_entry = session.get(QuarantineEntry, 1)
        assert q_entry.state == "restored"
        assert q_entry.tx_phase == "restored"

    # Filesystem assertions
    assert orig_path.exists()
    st_restored = os.stat(orig_path)
    assert st_restored.st_dev == expected_dev
    assert st_restored.st_ino == expected_ino

    # Public view must be retired to captured_quarantine_view
    assert not pub_path.exists()
    captured_view = tx_dir / "captured_quarantine_view"
    assert captured_view.exists()
    st_cap = os.stat(captured_view)
    assert st_cap.st_dev == expected_dev
    assert st_cap.st_ino == expected_ino


def test_real_worker_compat_restore_legacy_without_anchor_fails_closed(tmp_path, monkeypatch):
    """
    HOTFIX1 Requirement 2:
    Legacy row on COMPAT without authoritative anchor MUST fail closed with EOPNOTSUPP.
    """
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)

    import app.quarantine.capability as cap_module
    monkeypatch.setattr(cap_module, "resolve_mutation_capability", lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL)

    orig_path = data_dir / "legacy_dest.txt"
    pub_path = trash_dir / "legacy_pub.txt"
    pub_path.write_bytes(b"LEGACY_DATA")
    st = os.stat(pub_path)

    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        # Legacy entry without anchor
        q_entry = QuarantineEntry(
            id=2,
            original_path=str(orig_path),
            quarantine_path=str(pub_path),
            state="active",
            tx_phase="legacy",
            authoritative_anchor_path=None,
            size=st.st_size,
            content_hash=hashlib.sha256(b"LEGACY_DATA").hexdigest(),
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(q_entry)

        plan = BatchPlan(name="legacy_restore_plan", kind="organize", status="frozen")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="restore",
            source_path=str(pub_path),
            target_path=str(orig_path),
            state="planned",
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
            expected_size=st.st_size,
            expected_hash=hashlib.sha256(b"LEGACY_DATA").hexdigest(),
            metadata_json=json.dumps({"quarantine_entry_id": 2}),
        )
        session.add(item)
        session.commit()
        plan_id = plan.id

    service.validate_plan(plan_id)
    res = client.post(f"/api/plans/{plan_id}/execute")
    assert res.status_code == 200
    job_id = res.json()["work_job_id"]

    worker_id = "test-worker-1"
    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1, locked=True, owner=worker_id, acquired_at=utcnow())
            session.add(lock)
        else:
            lock.locked = True
            lock.owner = worker_id
            lock.acquired_at = utcnow()
        job = session.get(WorkJob, job_id)
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

    context = JobContext(service.engine, service.SessionLocal, job_id, worker_id=worker_id)
    handler = BatchPlanExecuteHandler()
    with service.SessionLocal() as session:
        job_inst = session.get(WorkJob, job_id)
        handler.run(job_inst, context, settings)

    with service.SessionLocal() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        # Must fail closed with unsupported/EOPNOTSUPP
        assert item.state == "failed"
        assert "EOPNOTSUPP" in (item.reason or "") or "unsupported" in (item.reason or "").lower()
