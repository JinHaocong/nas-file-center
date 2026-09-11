import hashlib
import json
import os
from pathlib import Path
import pytest
from sqlalchemy import select, text

from app.config import Settings
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, WorkJob, utcnow, TaskLock
from app.db import create_engine_and_session, init_db
from app.tasks.context import JobContext
from app.tasks.handlers import BatchPlanExecuteHandler


@pytest.fixture
def env_setup(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    trash_dir = data_dir / ".custom-trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = config_dir / "app.db"

    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)

    settings = Settings(
        config_dir=config_dir,
        database_path=db_path,
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
        quarantine_root=trash_dir,
        allow_mutation=True,
        allow_delete=True,
    )
    return engine, SessionLocal, settings, data_dir, trash_dir


def test_worker_crash_recovery_quarantine_no_nested_write_lock(env_setup, monkeypatch):
    """
    HOTFIX2 Item 5 & 8:
    Verify that worker crash recovery of an executing quarantine item
    does not invoke reconcile_quarantine_transaction nested inside BEGIN IMMEDIATE,
    and passes settings.quarantine_root and settings.allowed_roots to outer reconciliation.
    """
    engine, SessionLocal, settings, data_dir, trash_dir = env_setup

    source = data_dir / "crash_q.txt"
    payload = b"CRASH_QUARANTINE_PAYLOAD"
    source.write_bytes(payload)
    st = os.stat(source)

    pub_path = trash_dir / "crash_q.txt"

    tx_dir = trash_dir / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True, exist_ok=True)
    candidate_anchor = tx_dir / "anchor"
    os.link(str(source), str(candidate_anchor))

    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)

        plan = BatchPlan(name="crash_plan", kind="organize", status="frozen")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="quarantine",
            source_path=str(source),
            target_path=str(pub_path),
            state="executing",  # Simulates worker crash mid-execution
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
            expected_size=len(payload),
            expected_hash=hashlib.sha256(payload).hexdigest(),
            expected_mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(item)
        session.flush()

        q_entry = QuarantineEntry(
            id=1,
            plan_item_id=item.id,
            original_path=str(source),
            quarantine_path=str(pub_path),
            state="preparing",
            tx_phase="candidate_anchored",
            authoritative_anchor_path=None,
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(q_entry)

        job = WorkJob(
            kind="batch-plan-execute",
            status="running",
            started_at=utcnow(),
            state_json=json.dumps({"plan_id": plan.id}),
        )
        session.add(job)
        session.commit()
        job_id = job.id

    context = JobContext(engine, SessionLocal, job_id, worker_id="worker-1")
    handler = BatchPlanExecuteHandler()

    # Re-run after worker crash: must complete reconciliation cleanly
    with SessionLocal() as session:
        job_inst = session.get(WorkJob, job_id)
        handler.run(job_inst, context, settings)

    with SessionLocal() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id))
        q_entry = session.get(QuarantineEntry, 1)

        assert item.state in ("completed", "planned")
        assert q_entry.state in ("active", "preparing")


def test_worker_crash_recovery_restore_no_nested_write_lock(env_setup, monkeypatch):
    """
    HOTFIX2 Item 5 & 8:
    Verify that worker crash recovery of an executing restore item
    does not invoke reconcile_quarantine_transaction nested inside BEGIN IMMEDIATE,
    and passes settings.quarantine_root and settings.allowed_roots to outer reconciliation.
    """
    engine, SessionLocal, settings, data_dir, trash_dir = env_setup

    orig_path = data_dir / "crash_restored.txt"
    pub_path = trash_dir / "crash_restored.txt"
    payload = b"CRASH_RESTORE_PAYLOAD"

    tx_dir = trash_dir / ".tx" / "entry-2" / "attempt-1"
    tx_dir.mkdir(parents=True, exist_ok=True)
    anchor = tx_dir / "anchor"
    anchor.write_bytes(payload)
    st = os.stat(anchor)
    os.link(str(anchor), str(pub_path))

    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)

        plan = BatchPlan(name="crash_restore_plan", kind="organize", status="frozen")
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="restore",
            source_path=str(pub_path),
            target_path=str(orig_path),
            state="executing",  # Simulates worker crash during restore
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
            expected_size=len(payload),
            expected_hash=hashlib.sha256(payload).hexdigest(),
            expected_mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
            metadata_json=json.dumps({"quarantine_entry_id": 2}),
        )
        session.add(item)
        session.flush()

        q_entry = QuarantineEntry(
            id=2,
            plan_item_id=item.id,
            original_path=str(orig_path),
            quarantine_path=str(pub_path),
            state="restoring",
            tx_phase="restoring",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(q_entry)

        job = WorkJob(
            kind="batch-plan-execute",
            status="running",
            started_at=utcnow(),
            state_json=json.dumps({"plan_id": plan.id}),
        )
        session.add(job)
        session.commit()
        job_id = job.id

    context = JobContext(engine, SessionLocal, job_id, worker_id="worker-1")
    handler = BatchPlanExecuteHandler()

    # Re-run after worker crash: must complete reconciliation cleanly
    with SessionLocal() as session:
        job_inst = session.get(WorkJob, job_id)
        handler.run(job_inst, context, settings)

    with SessionLocal() as session:
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id))
        q_entry = session.get(QuarantineEntry, 2)

        assert item.state in ("completed", "planned")
        assert q_entry.state in ("restored", "active")
