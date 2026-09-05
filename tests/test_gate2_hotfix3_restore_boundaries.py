import json
import os
import sqlite3
from pathlib import Path
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.models import AuditEvent, BatchPlan, BatchPlanItem, OperationJournal, QuarantineEntry, WorkJob, TaskLock
from app.service import FileCenterService
from app.tasks.context import JobContext
from app.tasks.handlers import BatchPlanExecuteHandler, _check_target_identity, _reconcile_executing_item
from app.tasks.recovery import utcnow


@pytest.fixture
def h3_env(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    db_file = config_dir / "app.db"

    allowed = tmp_path / "storage"
    allowed.mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()

    settings = Settings(
        config_dir=config_dir,
        database_path=db_file,
        data_mount=allowed,
        allowed_roots_raw=str(allowed),
        quarantine_root=str(quarantine),
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    service = FileCenterService(settings)
    return {
        "service": service,
        "engine": service.engine,
        "SessionLocal": service.SessionLocal,
        "allowed": allowed,
        "quarantine": quarantine,
        "settings": settings,
        "tmp_path": tmp_path,
    }


def _acquire_lease(session, worker_id: str = "worker-1"):
    now = utcnow()
    lock = session.get(TaskLock, 1)
    if not lock:
        lock = TaskLock(id=1, locked=True, owner=worker_id, acquired_at=now)
        session.add(lock)
    else:
        lock.locked = True
        lock.owner = worker_id
        lock.acquired_at = now
    session.commit()


# ==============================================================================
# BLOCKER B: _check_target_identity MUST FAIL CLOSED ON EMPTY/MISSING IDENTITY
# ==============================================================================

def test_reconcile_missing_source_identity_fails_closed(h3_env):
    """
    If execution.source_stat is empty or incomplete, _check_target_identity must
    return False and crash reconciliation must fail closed (zero journal).
    """
    SessionLocal = h3_env["SessionLocal"]
    allowed = h3_env["allowed"]
    settings = h3_env["settings"]

    src = allowed / "missing_source.txt"
    tgt = allowed / "unrelated_target.txt"
    tgt.write_text("unrelated content")

    # 1. Test unit function directly
    assert _check_target_identity(tgt, {}) is False, "_check_target_identity must return False on empty source_stat"
    assert _check_target_identity(tgt, {"size": tgt.stat().st_size}) is False, "Missing device/inode must return False"

    # 2. Test within crash reconciliation
    now = utcnow()
    with SessionLocal() as session:
        plan = BatchPlan(name="test plan", kind="batch-rename", status="executing", created_at=now)
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="rename",
            source_path=str(src),
            target_path=str(tgt),
            state="executing",
            metadata_json=json.dumps({
                "execution": {
                    "phase": "intent",
                    "task_id": 99,
                    "operation": "rename",
                    "source_stat": {},  # Missing/empty identity
                }
            }),
        )
        session.add(item)
        session.commit()
        item_id = item.id
        plan_id = plan.id

    with SessionLocal() as session:
        it = session.get(BatchPlanItem, item_id)
        _reconcile_executing_item(session, it, plan_id, 99, 1, settings, now)
        session.commit()

    with SessionLocal() as session:
        it = session.get(BatchPlanItem, item_id)
        assert it.state == "failed", f"Expected failed, got {it.state}"
        assert "target identity mismatch" in (it.reason or "")

        journals = session.scalars(select(OperationJournal).where(OperationJournal.plan_item_id == item_id)).all()
        assert len(journals) == 0, "No OperationJournal should be written for identity mismatch"


# ==============================================================================
# BLOCKER C: CROSS-FILESYSTEM TARGET MUST NOT BE ACCEPTED
# ==============================================================================

def test_reconcile_cross_filesystem_same_size_target_fails_closed(h3_env):
    """
    If target.st_dev != source_stat['device'], even with identical file size,
    _check_target_identity must return False and fail closed.
    """
    allowed = h3_env["allowed"]

    tgt = allowed / "some_target.txt"
    tgt.write_text("12345678")
    real_stat = tgt.stat()

    # Fake source stat with different device but identical size
    fake_source_stat = {
        "device": real_stat.st_dev + 99999,
        "inode": real_stat.st_ino,
        "size": real_stat.st_size,
    }

    assert _check_target_identity(tgt, fake_source_stat) is False, "Cross-filesystem target must return False"

    # Also test with real Linux /dev/shm if available
    shm_path = Path("/dev/shm")
    if shm_path.exists() and os.access(shm_path, os.W_OK):
        shm_file = shm_path / "test_cross_fs_tgt.txt"
        try:
            shm_file.write_text("12345678")
            shm_stat = shm_file.stat()
            if shm_stat.st_dev != real_stat.st_dev:
                # Same size, same inode if simulated, but different device
                src_stat_real_tmp = {
                    "device": real_stat.st_dev,
                    "inode": shm_stat.st_ino,
                    "size": shm_stat.st_size,
                }
                assert _check_target_identity(shm_file, src_stat_real_tmp) is False
        finally:
            if shm_file.exists():
                shm_file.unlink()


# ==============================================================================
# BLOCKER E: DIRECT RESTORE JOURNAL METADATA
# ==============================================================================

def test_direct_restore_journal_contains_identity_metadata(h3_env):
    """
    Direct restore must persist full stat snapshot metadata in metadata_before_json
    and metadata_after_json (not empty '{}').
    """
    SessionLocal = h3_env["SessionLocal"]
    service = h3_env["service"]
    allowed = h3_env["allowed"]
    quarantine = h3_env["quarantine"]

    original_file = allowed / "direct_doc.txt"
    original_file.write_text("direct restore test data")
    st = original_file.stat()

    # Create active quarantine entry
    q_file = quarantine / "stored_doc.bin"
    q_file.write_text("direct restore test data")
    from app.quarantine.paths import safe_quarantine_hash
    q_hash = safe_quarantine_hash(q_file)

    now = utcnow()
    with SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(original_file),
            quarantine_path=str(q_file),
            state="active",
            content_hash=q_hash,
            size=st.st_size,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
            device=st.st_dev,
            inode=st.st_ino,
            created_at=now,
            updated_at=now,
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    # Make original file absent so restore can proceed
    original_file.unlink()

    with SessionLocal() as session:
        from app.models import User
        user = session.scalar(select(User))
        effective_user_id = user.id if user else None

    # Direct restore
    result = service.restore_quarantine_entry(entry_id, user_id=effective_user_id)
    assert result.get("state") == "restored" or result.get("status") == "restored"
    assert original_file.exists()

    with SessionLocal() as session:
        journal = session.scalar(select(OperationJournal).where(
            OperationJournal.operation == "restore",
            OperationJournal.user_id == effective_user_id,
        ))
        assert journal is not None
        assert journal.plan_id is None
        assert journal.plan_item_id is None
        assert journal.task_id is None

        # Verify metadata_before_json and metadata_after_json
        assert journal.metadata_before_json != "{}", "metadata_before_json must not be empty"
        assert journal.metadata_after_json != "{}", "metadata_after_json must not be empty"

        before_meta = json.loads(journal.metadata_before_json)
        after_meta = json.loads(journal.metadata_after_json)

        for field in ("object_type", "size", "mtime_ns", "device", "inode"):
            assert field in before_meta, f"Missing {field} in metadata_before"
            assert field in after_meta, f"Missing {field} in metadata_after"


# ==============================================================================
# BLOCKER D: NO safe_quarantine_hash UNDER BEGIN IMMEDIATE
# ==============================================================================

def test_worker_restore_hash_does_not_hold_sqlite_write_transaction(h3_env, monkeypatch):
    """
    While safe_quarantine_hash is running during worker restore, a second SQLite
    connection must be able to BEGIN IMMEDIATE and COMMIT without being locked out.
    """
    engine = h3_env["engine"]
    SessionLocal = h3_env["SessionLocal"]
    settings = h3_env["settings"]
    allowed = h3_env["allowed"]
    quarantine = h3_env["quarantine"]

    orig = allowed / "worker_restore.txt"
    q_file = quarantine / "worker_q.bin"
    content = b"WORKER_RESTORE_HASH_TEST"
    q_file.write_bytes(content)

    from app.quarantine.paths import safe_quarantine_hash as real_hash
    real_h = real_hash(q_file)

    now = utcnow()
    with SessionLocal() as session:
        _acquire_lease(session, "worker-1")

        entry = QuarantineEntry(
            original_path=str(orig),
            quarantine_path=str(q_file),
            state="active",
            content_hash=real_h,
            size=len(content),
            created_at=now,
            updated_at=now,
        )
        session.add(entry)
        session.flush()

        plan = BatchPlan(name="restore plan", kind="batch-rename", status="ready", created_at=now)
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="restore",
            source_path=str(q_file),
            target_path=str(orig),
            state="planned",
            metadata_json=json.dumps({"quarantine_entry_id": entry.id}),
        )
        session.add(item)
        session.flush()

        job = WorkJob(
            id=101,
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps({"plan_id": plan.id, "requested_by_user_id": 1}),
            created_at=now,
        )
        session.add(job)
        session.commit()
        plan_id = plan.id
        job_id = job.id

    concurrent_write_succeeded = False

    def instrumented_hash(path):
        nonlocal concurrent_write_succeeded
        # Try a write transaction on a second connection
        with SessionLocal() as s2:
            s2.execute(text("BEGIN IMMEDIATE"))
            concurrent_write_succeeded = True
            s2.commit()
        return real_hash(path)

    monkeypatch.setattr("app.tasks.handlers.safe_quarantine_hash", instrumented_hash)
    monkeypatch.setattr("app.quarantine.restore.safe_quarantine_hash", instrumented_hash)

    handler = BatchPlanExecuteHandler()
    ctx = JobContext(engine, SessionLocal, job_id, worker_id="worker-1")

    with SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        handler.run(job, ctx, settings)

    assert concurrent_write_succeeded is True, "Second connection was locked out while calculating safe_quarantine_hash!"


def test_restore_reconciliation_hash_does_not_hold_sqlite_write_transaction(h3_env, monkeypatch):
    """
    While safe_quarantine_hash is running during crash reconciliation, a second SQLite
    connection must be able to BEGIN IMMEDIATE and COMMIT without being locked out.
    """
    engine = h3_env["engine"]
    SessionLocal = h3_env["SessionLocal"]
    settings = h3_env["settings"]
    allowed = h3_env["allowed"]
    quarantine = h3_env["quarantine"]

    orig = allowed / "reconcile_restore.txt"
    orig.write_bytes(b"RECONCILE_RESTORE_DATA")
    st = orig.stat()

    q_file = quarantine / "reconcile_q.bin"
    # Source is absent (already moved to orig during crash)
    from app.quarantine.paths import safe_quarantine_hash as real_hash
    real_h = real_hash(orig)

    now = utcnow()
    with SessionLocal() as session:
        _acquire_lease(session, "worker-1")

        entry = QuarantineEntry(
            original_path=str(orig),
            quarantine_path=str(q_file),
            state="active",
            content_hash=real_h,
            size=st.st_size,
            created_at=now,
            updated_at=now,
        )
        session.add(entry)
        session.flush()

        plan = BatchPlan(name="reconcile plan", kind="batch-rename", status="executing", created_at=now)
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="restore",
            source_path=str(q_file),
            target_path=str(orig),
            state="executing",
            metadata_json=json.dumps({
                "quarantine_entry_id": entry.id,
                "execution": {
                    "phase": "intent",
                    "task_id": 202,
                    "operation": "restore",
                    "source_stat": {
                        "device": st.st_dev,
                        "inode": st.st_ino,
                        "size": st.st_size,
                        "mtime_ns": getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
                        "object_type": "file",
                    },
                }
            }),
        )
        session.add(item)
        session.flush()

        job = WorkJob(
            id=202,
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps({"plan_id": plan.id, "requested_by_user_id": 1}),
            created_at=now,
        )
        session.add(job)
        session.commit()
        job_id = job.id

    concurrent_write_succeeded = False

    def instrumented_hash(path):
        nonlocal concurrent_write_succeeded
        with SessionLocal() as s2:
            s2.execute(text("BEGIN IMMEDIATE"))
            concurrent_write_succeeded = True
            s2.commit()
        return real_hash(path)

    monkeypatch.setattr("app.tasks.handlers.safe_quarantine_hash", instrumented_hash)

    handler = BatchPlanExecuteHandler()
    ctx = JobContext(engine, SessionLocal, job_id, worker_id="worker-1")

    with SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        handler.run(job, ctx, settings)

    assert concurrent_write_succeeded is True, "Second connection was locked out while calculating safe_quarantine_hash during reconciliation!"


# ==============================================================================
# BLOCKER A: RESTORE INTEGRITY TAMPER AFTER PHASE 1 BEFORE MUTATION IS REJECTED
# ==============================================================================

def test_restore_tamper_after_phase1_before_mutation_is_rejected(h3_env, monkeypatch):
    """
    If the quarantined file is tampered with AFTER Phase 1 DB intent commit
    and BEFORE filesystem mutation (same length but different content):
    - Zero restore mutation: original path must remain absent.
    - Quarantined file remains in quarantine.
    - Item state is failed.
    - QuarantineEntry is inconsistent.
    - Zero successful Restore Journal recorded.
    """
    engine = h3_env["engine"]
    SessionLocal = h3_env["SessionLocal"]
    settings = h3_env["settings"]
    allowed = h3_env["allowed"]
    quarantine = h3_env["quarantine"]

    orig = allowed / "tamper_target.txt"
    q_file = quarantine / "tamper_q.bin"
    initial_content = b"ORIGINAL"
    q_file.write_bytes(initial_content)

    from app.quarantine.paths import safe_quarantine_hash
    orig_hash = safe_quarantine_hash(q_file)

    now = utcnow()
    with SessionLocal() as session:
        _acquire_lease(session, "worker-1")

        entry = QuarantineEntry(
            original_path=str(orig),
            quarantine_path=str(q_file),
            state="active",
            content_hash=orig_hash,
            size=len(initial_content),
            created_at=now,
            updated_at=now,
        )
        session.add(entry)
        session.flush()

        plan = BatchPlan(name="tamper test plan", kind="batch-rename", status="ready", created_at=now)
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="restore",
            source_path=str(q_file),
            target_path=str(orig),
            state="planned",
            metadata_json=json.dumps({"quarantine_entry_id": entry.id}),
        )
        session.add(item)
        session.flush()

        job = WorkJob(
            id=303,
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps({"plan_id": plan.id, "requested_by_user_id": 1}),
            created_at=now,
        )
        session.add(job)
        session.commit()
        entry_id = entry.id
        item_id = item.id
        job_id = job.id

    # Hook before filesystem mutation to overwrite the file with same-length TAMPERED content
    tampered_done = False
    from app.execution import executor

    real_execute_item = executor.execute_item

    def tamper_before_execute(item_op, **kwargs):
        nonlocal tampered_done
        if item_op.operation == "restore" and not tampered_done:
            # Overwrite with same-length tampered content
            q_file.write_bytes(b"TAMPERED")
            tampered_done = True
        return real_execute_item(item_op, **kwargs)

    monkeypatch.setattr("app.tasks.handlers.execute_item", tamper_before_execute)

    handler = BatchPlanExecuteHandler()
    ctx = JobContext(engine, SessionLocal, job_id, worker_id="worker-1")

    with SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        handler.run(job, ctx, settings)

    # Assertions
    # 1. Zero restore mutation: original path absent
    assert not orig.exists(), "Original path MUST NOT exist (tampered content was restored!)"

    # 2. Quarantine target remains
    assert q_file.exists(), "Quarantine file must remain in quarantine"
    assert q_file.read_bytes() == b"TAMPERED"

    with SessionLocal() as session:
        it = session.get(BatchPlanItem, item_id)
        assert it.state == "failed", f"Expected item failed, got {it.state}"

        qe = session.get(QuarantineEntry, entry_id)
        assert qe.state == "inconsistent", f"Expected QuarantineEntry inconsistent, got {qe.state}"

        journals = session.scalars(select(OperationJournal).where(
            OperationJournal.plan_item_id == item_id,
            OperationJournal.operation == "restore",
        )).all()
        assert len(journals) == 0, "No Restore Journal should be written for tampered restore"
