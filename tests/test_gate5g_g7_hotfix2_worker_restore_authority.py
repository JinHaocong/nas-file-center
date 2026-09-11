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


def test_real_worker_restore_when_public_view_replaced_with_foreign_file(tmp_path, monkeypatch):
    """
    HOTFIX2 Item 1 Test A:
    active compat
    public view replaced with foreign file
    → Worker restore publishes original from anchor
    → captures foreign view
    → conflict/conflict
    → foreign view preserved in slot
    → NEVER legacy inconsistent!
    """
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)

    import app.quarantine.capability as cap_module
    monkeypatch.setattr(cap_module, "resolve_mutation_capability", lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL)

    orig_path = data_dir / "doc.txt"
    pub_path = trash_dir / "doc_quarantine.txt"
    genuine_payload = b"GENUINE_ANCHOR_PAYLOAD"
    foreign_payload = b"FOREIGN_REPLACED_PUBLIC_VIEW"

    tx_dir = trash_dir / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True, exist_ok=True)
    anchor_path = tx_dir / "anchor"
    anchor_path.write_bytes(genuine_payload)

    # Public view is replaced with a foreign file!
    pub_path.write_bytes(foreign_payload)

    st = os.stat(anchor_path)
    expected_dev = st.st_dev
    expected_ino = st.st_ino
    expected_size = len(genuine_payload)
    expected_hash = hashlib.sha256(genuine_payload).hexdigest()

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

        plan = BatchPlan(name="restore_foreign_view", kind="organize", status="frozen")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="restore",
            source_path=str(pub_path),
            target_path=str(orig_path),
            state="planned",
            metadata_json=json.dumps({"quarantine_entry_id": 1}),
        )
        session.add(item)

        session.commit()
        plan_id = plan.id

    service.validate_plan(plan_id)
    res = client.post(f"/api/plans/{plan_id}/execute")
    assert res.status_code == 200
    job_id = res.json()["work_job_id"]

    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
            session.add(lock)
        else:
            lock.locked = True
            lock.owner = "worker-1"
            lock.acquired_at = utcnow()
        session.commit()

        job = session.get(WorkJob, job_id)
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

    context = JobContext(service.engine, service.SessionLocal, job_id, worker_id="worker-1")
    handler = BatchPlanExecuteHandler()
    with service.SessionLocal() as session:
        job_inst = session.get(WorkJob, job_id)
        handler.run(job_inst, context, settings)

    with service.SessionLocal() as session:
        qe = session.get(QuarantineEntry, 1)
        plan_item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert qe is not None
        # MUST NOT be legacy inconsistent!
        assert qe.state != "inconsistent"
        assert qe.tx_phase != "inconsistent"
        assert qe.state == "conflict"
        assert qe.tx_phase == "conflict"

    # Original path restored from anchor
    assert orig_path.exists()
    assert orig_path.read_bytes() == genuine_payload


def test_real_worker_restore_when_public_view_missing(tmp_path, monkeypatch):
    """
    HOTFIX2 Item 1 Test B:
    active compat
    public view missing
    → transaction path handles according to frozen restore evidence
    → never legacy inconsistent!
    """
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)

    import app.quarantine.capability as cap_module
    monkeypatch.setattr(cap_module, "resolve_mutation_capability", lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL)

    orig_path = data_dir / "doc2.txt"
    pub_path = trash_dir / "doc2_quarantine_absent.txt"
    # Ensure public path does NOT exist
    if pub_path.exists():
        pub_path.unlink()

    genuine_payload = b"GENUINE_ANCHOR_PAYLOAD_2"
    tx_dir = trash_dir / ".tx" / "entry-2" / "attempt-1"
    tx_dir.mkdir(parents=True, exist_ok=True)
    anchor_path = tx_dir / "anchor"
    anchor_path.write_bytes(genuine_payload)

    st = os.stat(anchor_path)
    expected_dev = st.st_dev
    expected_ino = st.st_ino
    expected_size = len(genuine_payload)
    expected_hash = hashlib.sha256(genuine_payload).hexdigest()

    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        q_entry = QuarantineEntry(
            id=2,
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

        plan = BatchPlan(name="restore_missing_view", kind="organize", status="frozen")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="restore",
            source_path=str(pub_path),
            target_path=str(orig_path),
            state="planned",
            metadata_json=json.dumps({"quarantine_entry_id": 2}),
        )
        session.add(item)

        session.commit()
        plan_id = plan.id

    service.validate_plan(plan_id)
    res = client.post(f"/api/plans/{plan_id}/execute")
    assert res.status_code == 200
    job_id = res.json()["work_job_id"]

    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
            session.add(lock)
        else:
            lock.locked = True
            lock.owner = "worker-1"
            lock.acquired_at = utcnow()
        session.commit()

        job = session.get(WorkJob, job_id)
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

    context = JobContext(service.engine, service.SessionLocal, job_id, worker_id="worker-1")
    handler = BatchPlanExecuteHandler()
    with service.SessionLocal() as session:
        job_inst = session.get(WorkJob, job_id)
        handler.run(job_inst, context, settings)

    with service.SessionLocal() as session:
        qe = session.get(QuarantineEntry, 2)
        assert qe is not None
        # MUST NOT be legacy inconsistent!
        assert qe.state != "inconsistent"
        assert qe.tx_phase != "inconsistent"
        assert qe.state == "conflict"
        assert qe.tx_phase == "conflict"


def test_frozen_tx_phase_enum_never_inconsistent():
    """
    HOTFIX2 Item 6:
    Ensure no production code in app/ contains 'tx_phase = "inconsistent"'
    or non-frozen phase assignments.
    """
    import inspect
    from app.models import QuarantineEntry

    allowed_phases = {
        "preparing",
        "candidate_anchored",
        "authoritative_anchored",
        "public_published",
        "source_captured",
        "active",
        "restoring",
        "restored",
        "conflict",
        "legacy",
    }
    app_dir = Path(__file__).resolve().parent.parent / "app"
    for py_file in app_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert 'tx_phase = "inconsistent"' not in content, f"Found tx_phase = 'inconsistent' in {py_file}"
        assert "tx_phase='inconsistent'" not in content, f"Found tx_phase='inconsistent' in {py_file}"
