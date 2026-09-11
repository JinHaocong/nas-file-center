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


def test_crash_reconciliation_no_nested_begin_immediate(tmp_path):
    """
    HOTFIX1 Requirement 4:
    Crash recovery in BatchPlanExecuteHandler must run transactional filesystem
    reconciliation OUTSIDE the outer SQLite write transaction.
    No SQLITE_BUSY / database is locked.
    tx reconciles and BatchPlanItem converges correctly.
    """
    client, service, settings, data_dir, trash_dir = _setup_app_and_service(tmp_path)

    orig_path = data_dir / "crashed_file.txt"
    payload = b"CRASHED_BEFORE_RECONCILIATION"
    orig_path.write_bytes(payload)
    st = os.stat(orig_path)
    expected_dev = st.st_dev
    expected_ino = st.st_ino
    expected_size = len(payload)
    expected_hash = hashlib.sha256(payload).hexdigest()

    pub_path = trash_dir / "crashed_file.txt"
    tx_dir = trash_dir / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True, exist_ok=True)
    anchor_path = tx_dir / "anchor"
    os.link(str(orig_path), str(anchor_path))

    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        # Active worker lease
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)

        plan = BatchPlan(name="crashed_plan", kind="organize", status="executing")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="quarantine",
            source_path=str(orig_path),
            target_path=str(pub_path),
            state="executing",  # Simulates crash during execution
            expected_device=expected_dev,
            expected_inode=expected_ino,
            expected_size=expected_size,
            expected_hash=expected_hash,
            expected_mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(item)
        session.flush()

        q_entry = QuarantineEntry(
            id=1,
            plan_item_id=item.id,
            original_path=str(orig_path),
            quarantine_path=str(pub_path),
            state="preparing",
            tx_phase="candidate_anchored",  # Candidate anchor exists
            authoritative_anchor_path=None,
            active_attempt_generation=1,
            size=expected_size,
            content_hash=expected_hash,
            device=expected_dev,
            inode=expected_ino,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(q_entry)

        job = WorkJob(kind="batch-plan-execute", status="running", started_at=utcnow(), state_json=json.dumps({"plan_id": plan.id}))
        session.add(job)
        session.commit()
        job_id = job.id

    context = JobContext(service.engine, service.SessionLocal, job_id, worker_id="worker-1")
    handler = BatchPlanExecuteHandler()

    # Re-run after worker crash: must not trigger SQLITE_BUSY / locked database
    with service.SessionLocal() as session:
        job_inst = session.get(WorkJob, job_id)
        handler.run(job_inst, context, settings)

    with service.SessionLocal() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id))
        q_entry = session.get(QuarantineEntry, 1)

        # Successfully reconciled
        assert item.state in ("completed", "planned")
        assert q_entry.state in ("active", "preparing")
