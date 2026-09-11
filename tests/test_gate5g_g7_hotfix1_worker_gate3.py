import hashlib
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


def test_real_worker_quarantine_carries_gate3_authority(tmp_path, monkeypatch):
    """
    HOTFIX1 Requirement 1:
    Real Worker Quarantine Must Carry Gate3 Authority from frozen BatchPlanItem.
    The test must fail on baseline 8057724 and prove:
    entry.state == active
    entry.tx_phase == active
    anchor identity matches frozen BatchPlanItem
    source retired
    public view present
    captured_source present
    No manual pre-seeding of QuarantineEntry identity.
    """
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)

    # 1. Setup real source file
    src_file = data_dir / "target_file.txt"
    payload = b"AUTHORITATIVE_GATE3_PAYLOAD_TEST"
    src_file.write_bytes(payload)

    st = os.stat(src_file)
    expected_dev = st.st_dev
    expected_ino = st.st_ino
    expected_size = len(payload)
    expected_hash = hashlib.sha256(payload).hexdigest()
    expected_mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))

    # 2. Force capability resolution to COMPAT_TRANSACTIONAL
    import app.quarantine.capability as cap_module
    monkeypatch.setattr(cap_module, "resolve_mutation_capability", lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL)

    # 3. Create, freeze, and validate plan to establish Gate3 frozen baseline
    plan = service.create_plan(
        name="test_worker_gate3",
        kind="organize",
        items=[{"source": str(src_file), "operation": "quarantine", "expected_hash": expected_hash}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # Verify that BatchPlanItem has frozen Gate3 authority
    with service.SessionLocal() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id))
        assert item.expected_device == expected_dev
        assert item.expected_inode == expected_ino
        assert item.expected_size == expected_size
        assert item.expected_hash == expected_hash

    # 4. Enqueue execution job
    res = client.post(f"/api/plans/{plan.id}/execute")
    assert res.status_code == 200
    job_id = res.json()["work_job_id"]

    # 5. Acquire lease for test-worker-1
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

    # 6. Execute through real worker pipeline
    handler.run(job, context, settings)

    # 7. Assertions: Verify QuarantineEntry state and Gate3 authority without manual seeding
    with service.SessionLocal() as session:
        q_entry = session.scalar(select(QuarantineEntry).where(QuarantineEntry.original_path == str(src_file)))
        assert q_entry is not None, "QuarantineEntry must exist"
        assert q_entry.state == "active", f"Expected active, got {q_entry.state}, error: {q_entry.last_error}"
        assert q_entry.tx_phase == "active", f"Expected tx_phase active, got {q_entry.tx_phase}"

        # Gate3 anchor authority matches frozen BatchPlanItem
        assert q_entry.device == expected_dev
        assert q_entry.inode == expected_ino
        assert q_entry.size == expected_size
        assert q_entry.content_hash == expected_hash

        assert q_entry.authoritative_anchor_path is not None
        anchor_path = Path(q_entry.authoritative_anchor_path)
        assert anchor_path.exists()
        st_anchor = os.stat(anchor_path)
        assert st_anchor.st_dev == expected_dev
        assert st_anchor.st_ino == expected_ino

        # Source must be retired
        assert not src_file.exists()

        # Public view present
        pub_path = Path(q_entry.quarantine_path)
        assert pub_path.exists()
        st_pub = os.stat(pub_path)
        assert st_pub.st_dev == expected_dev
        assert st_pub.st_ino == expected_ino

        # Captured source slot present in attempt dir
        attempt_dir = anchor_path.parent
        captured_source = attempt_dir / "captured_source"
        assert captured_source.exists()
        st_cap = os.stat(captured_source)
        assert st_cap.st_dev == expected_dev
        assert st_cap.st_ino == expected_ino
