import json
import os
import sqlite3
from pathlib import Path
import pytest
from sqlalchemy import select, text

from app.config import Settings
from app.models import (
    AuditEvent,
    BatchPlan,
    BatchPlanItem,
    OperationJournal,
    QuarantineEntry,
    TaskLock,
    WorkJob,
)
from app.service import FileCenterService
from app.tasks.context import JobContext
from app.tasks.handlers import (
    BatchPlanExecuteHandler,
    _check_target_identity,
    _reconcile_executing_item,
)
from app.tasks.recovery import utcnow


@pytest.fixture
def h4_env(tmp_path):
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
# BLOCKER A: RESTORE RECONCILIATION PRECOMPUTE RACE NEVER HASHES UNDER WRITE TX
# ==============================================================================

def test_restore_reconciliation_precompute_race_never_hashes_under_write_transaction(h4_env, monkeypatch):
    """
    1. WorkPlan item is in executing state for restore.
    2. Precompute phase observes filesystem state where target hash is not prepared (e.g. source exists).
    3. Between precompute and reconciliation transaction, simulate race: source absent, target exists.
    4. Enter normal reconciliation flow.
    5. Instrument / block safe_quarantine_hash:
       Second connection must successfully execute BEGIN IMMEDIATE / COMMIT without being locked.
       safe_quarantine_hash must NOT be called from inside the write transaction.
    6. Reconciliation must fail closed / safe non-success (not completed, zero OperationJournal).
    """
    engine = h4_env["engine"]
    SessionLocal = h4_env["SessionLocal"]
    settings = h4_env["settings"]
    allowed = h4_env["allowed"]
    quarantine = h4_env["quarantine"]

    orig = allowed / "r_target.txt"
    q_file = quarantine / "r_quarantine.bin"
    content = b"RESTORE_CONTENT"
    orig.write_bytes(content)
    st = orig.stat()

    from app.quarantine.paths import safe_quarantine_hash as real_hash
    content_hash = real_hash(orig)

    now = utcnow()
    with SessionLocal() as session:
        _acquire_lease(session, "worker-1")

        entry = QuarantineEntry(
            original_path=str(orig),
            quarantine_path=str(q_file),
            state="restoring",
            content_hash=content_hash,
            size=len(content),
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
            device=st.st_dev,
            inode=st.st_ino,
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
            state="executing",
            metadata_json=json.dumps({
                "quarantine_entry_id": entry.id,
                "execution": {
                    "task_id": 101,
                    "operation": "restore",
                    "source_stat": {
                        "object_type": "file",
                        "size": len(content),
                        "mtime_ns": getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
                        "device": st.st_dev,
                        "inode": st.st_ino,
                    },
                },
            }),
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
        item_id = item.id
        job_id = job.id

    # Create source file initially so precompute scanner does not compute target hash
    # (Precompute only hashes if not src.exists())
    q_file.write_bytes(content)

    # Instrument safe_quarantine_hash
    hash_called_under_write_lock = False
    hash_called_during_reconciliation = False

    def instrumented_hash(p):
        nonlocal hash_called_under_write_lock, hash_called_during_reconciliation
        hash_called_during_reconciliation = True
        try:
            with SessionLocal() as s2:
                s2.execute(text("BEGIN IMMEDIATE"))
                s2.commit()
        except sqlite3.OperationalError:
            hash_called_under_write_lock = True
        return real_hash(p)

    monkeypatch.setattr("app.tasks.handlers.safe_quarantine_hash", instrumented_hash)

    # Now hook precompute: right after precompute finishes and before BEGIN IMMEDIATE, simulate race:
    # remove source q_file so that src.exists() is False when transaction starts!
    real_reconcile = _reconcile_executing_item

    def race_reconcile(*args, **kwargs):
        # By the time reconciliation starts, source was deleted (race!)
        if q_file.exists():
            q_file.unlink()
        return real_reconcile(*args, **kwargs)

    monkeypatch.setattr("app.tasks.handlers._reconcile_executing_item", race_reconcile)

    handler = BatchPlanExecuteHandler()
    ctx = JobContext(engine, SessionLocal, job_id, worker_id="worker-1")

    with SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        handler.run(job, ctx, settings)

    # Verification
    # 1. safe_quarantine_hash MUST NOT be called under BEGIN IMMEDIATE
    assert not hash_called_under_write_lock, "safe_quarantine_hash was called while holding BEGIN IMMEDIATE write lock!"
    assert not hash_called_during_reconciliation, "safe_quarantine_hash was called during reconciliation!"

    with SessionLocal() as session:
        it = session.get(BatchPlanItem, item_id)
        # 2. Must fail closed or not completed
        assert it.state != "completed", "Reconciliation must NOT guess completed without prepared evidence"
        # 3. Must NOT emit OperationJournal
        journal = session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == item_id))
        assert journal is None, "Must NOT emit successful OperationJournal without prepared evidence"


# ==============================================================================
# BLOCKER B: QUARANTINE RECONCILIATION PRECOMPUTE RACE NEVER HASHES UNDER WRITE TX
# ==============================================================================

def test_quarantine_reconciliation_precompute_race_never_hashes_under_write_transaction(h4_env, monkeypatch):
    """
    1. WorkPlan item is in executing state for quarantine.
    2. Precompute phase does not produce target hash (e.g. source still existed during precompute).
    3. Race occurs: source becomes absent, quarantine target exists.
    4. Enter normal reconciliation flow.
    5. Missing hash evidence must NOT trigger fallback safe_quarantine_hash under write tx.
    6. Second SQLite writer must be able to BEGIN IMMEDIATE / COMMIT.
    7. Must fail closed, no false success journal.
    """
    engine = h4_env["engine"]
    SessionLocal = h4_env["SessionLocal"]
    settings = h4_env["settings"]
    allowed = h4_env["allowed"]
    quarantine = h4_env["quarantine"]

    src_file = allowed / "doc.txt"
    src_file.write_text("DATA TO QUARANTINE")
    st = src_file.stat()

    q_file = quarantine / "q_target.bin"
    q_file.write_text("DATA TO QUARANTINE")

    from app.quarantine.paths import safe_quarantine_hash as real_hash
    content_hash = real_hash(src_file)

    now = utcnow()
    with SessionLocal() as session:
        _acquire_lease(session, "worker-1")

        plan = BatchPlan(name="quarantine plan", kind="organize", status="ready", created_at=now)
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="quarantine",
            source_path=str(src_file),
            target_path=str(q_file),
            state="executing",
            metadata_json=json.dumps({
                "execution": {
                    "task_id": 202,
                    "operation": "quarantine",
                    "source_stat": {
                        "object_type": "file",
                        "size": st.st_size,
                        "mtime_ns": getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
                        "device": st.st_dev,
                        "inode": st.st_ino,
                    },
                },
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
        session.flush()

        q_entry = QuarantineEntry(
            plan_item_id=item.id,
            task_id=job.id,
            original_path=str(src_file),
            quarantine_path=str(q_file),
            state="preparing",
            created_at=now,
            updated_at=now,
        )
        session.add(q_entry)
        session.commit()
        item_id = item.id
        job_id = job.id

    # Instrument safe_quarantine_hash
    hash_called_under_write_lock = False
    hash_called_during_reconciliation = False

    def instrumented_hash(p):
        nonlocal hash_called_under_write_lock, hash_called_during_reconciliation
        hash_called_during_reconciliation = True
        try:
            with SessionLocal() as s2:
                s2.execute(text("BEGIN IMMEDIATE"))
                s2.commit()
        except sqlite3.OperationalError:
            hash_called_under_write_lock = True
        return real_hash(p)

    monkeypatch.setattr("app.tasks.handlers.safe_quarantine_hash", instrumented_hash)

    # Hook precompute: remove src_file right after precompute scans, creating the race
    real_reconcile = _reconcile_executing_item

    def race_reconcile(*args, **kwargs):
        if src_file.exists():
            src_file.unlink()
        return real_reconcile(*args, **kwargs)

    monkeypatch.setattr("app.tasks.handlers._reconcile_executing_item", race_reconcile)

    handler = BatchPlanExecuteHandler()
    ctx = JobContext(engine, SessionLocal, job_id, worker_id="worker-1")

    with SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        handler.run(job, ctx, settings)

    assert not hash_called_under_write_lock, "safe_quarantine_hash was called while holding BEGIN IMMEDIATE write lock!"
    assert not hash_called_during_reconciliation, "safe_quarantine_hash was called during reconciliation!"

    with SessionLocal() as session:
        it = session.get(BatchPlanItem, item_id)
        assert it.state != "completed", "Quarantine reconciliation must NOT succeed without prepared hash evidence"
        journal = session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == item_id))
        assert journal is None, "Must NOT emit successful OperationJournal without prepared evidence"


# ==============================================================================
# BLOCKER D: STALE PRECOMPUTED HASH EVIDENCE FAILS CLOSED
# ==============================================================================

def test_reconciliation_stale_precomputed_hash_evidence_fails_closed(h4_env, monkeypatch):
    """
    1. target exists.
    2. Outside transaction, reconciliation evidence is prepared.
    3. Before transaction consumes it, mutate/replace target so the evidence no longer matches.
    4. Reconciliation runs.
    Expected:
    - Evidence identity/stat check fails
    - Item is NOT reconciled as successful
    - NO successful OperationJournal
    - NO fallback content hash under BEGIN IMMEDIATE
    """
    engine = h4_env["engine"]
    SessionLocal = h4_env["SessionLocal"]
    settings = h4_env["settings"]
    allowed = h4_env["allowed"]
    quarantine = h4_env["quarantine"]

    orig = allowed / "stale_target.txt"
    q_file = quarantine / "stale_q.bin"
    initial_content = b"INITIAL_VALID_CONTENT"
    orig.write_bytes(initial_content)
    st = orig.stat()

    from app.quarantine.paths import safe_quarantine_hash as real_hash
    initial_hash = real_hash(orig)

    now = utcnow()
    with SessionLocal() as session:
        _acquire_lease(session, "worker-1")

        entry = QuarantineEntry(
            original_path=str(orig),
            quarantine_path=str(q_file),
            state="restoring",
            content_hash=initial_hash,
            size=len(initial_content),
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
            device=st.st_dev,
            inode=st.st_ino,
            created_at=now,
            updated_at=now,
        )
        session.add(entry)
        session.flush()

        plan = BatchPlan(name="stale plan", kind="batch-rename", status="ready", created_at=now)
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
                    "task_id": 303,
                    "operation": "restore",
                    "source_stat": {
                        "object_type": "file",
                        "size": len(initial_content),
                        "mtime_ns": getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
                        "device": st.st_dev,
                        "inode": st.st_ino,
                    },
                },
            }),
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
        item_id = item.id
        job_id = job.id

    # Instrument safe_quarantine_hash: must NOT run inside write transaction
    hash_called_in_tx = False

    def instrumented_hash(p):
        nonlocal hash_called_in_tx
        try:
            with SessionLocal() as s2:
                s2.execute(text("BEGIN IMMEDIATE"))
                s2.commit()
        except sqlite3.OperationalError:
            hash_called_in_tx = True
        return real_hash(p)

    monkeypatch.setattr("app.tasks.handlers.safe_quarantine_hash", instrumented_hash)

    # Hook: between precompute and reconciliation transaction, mutate orig target (change content/mtime)
    real_reconcile = _reconcile_executing_item

    def tamper_before_reconcile(*args, **kwargs):
        # Mutate the file so mtime/identity is stale compared to precomputed evidence!
        orig.write_bytes(b"TAMPERED_AFTER_PRECOMPUTE")
        # Ensure mtime is different
        new_mtime = (st.st_mtime + 10)
        os.utime(orig, (new_mtime, new_mtime))
        return real_reconcile(*args, **kwargs)

    monkeypatch.setattr("app.tasks.handlers._reconcile_executing_item", tamper_before_reconcile)

    handler = BatchPlanExecuteHandler()
    ctx = JobContext(engine, SessionLocal, job_id, worker_id="worker-1")

    with SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        handler.run(job, ctx, settings)

    assert not hash_called_in_tx, "safe_quarantine_hash was called under write transaction!"

    with SessionLocal() as session:
        it = session.get(BatchPlanItem, item_id)
        assert it.state != "completed", f"Expected item not completed due to stale evidence, got {it.state}"
        journal = session.scalar(select(OperationJournal).where(OperationJournal.plan_item_id == item_id))
        assert journal is None, "Must not emit OperationJournal when evidence is stale"


# ==============================================================================
# BLOCKER E: SAME RUN MUST NOT EXECUTE A FAILED RECONCILIATION ITEM AGAIN
# ==============================================================================

def test_reconciliation_failed_item_not_reexecuted_in_same_run(h4_env, monkeypatch):
    """
    If an item is marked failed during startup/pre-execution reconciliation,
    the same Worker run MUST NOT fall through to execute_item() on that item.
    """
    engine = h4_env["engine"]
    SessionLocal = h4_env["SessionLocal"]
    settings = h4_env["settings"]
    allowed = h4_env["allowed"]

    src = allowed / "f_src.txt"
    tgt = allowed / "f_tgt.txt"
    tgt.write_text("UNRELATED_TARGET")
    # Different inode -> identity mismatch

    now = utcnow()
    with SessionLocal() as session:
        _acquire_lease(session, "worker-1")

        plan = BatchPlan(name="fail plan", kind="batch-rename", status="ready", created_at=now)
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
                    "task_id": 404,
                    "operation": "rename",
                    "source_stat": {
                        "object_type": "file",
                        "size": 10,
                        "mtime_ns": 100,
                        "device": 99999,  # Non-matching device
                        "inode": 99999,   # Non-matching inode
                    },
                },
            }),
        )
        session.add(item)
        session.flush()

        job = WorkJob(
            id=404,
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps({"plan_id": plan.id, "requested_by_user_id": 1}),
            created_at=now,
        )
        session.add(job)
        session.commit()
        item_id = item.id
        job_id = job.id

    # Track calls to execute_item
    execute_item_called = False
    from app.execution import executor
    real_exec = executor.execute_item

    def tracked_exec(*args, **kwargs):
        nonlocal execute_item_called
        execute_item_called = True
        return real_exec(*args, **kwargs)

    monkeypatch.setattr("app.tasks.handlers.execute_item", tracked_exec)

    handler = BatchPlanExecuteHandler()
    ctx = JobContext(engine, SessionLocal, job_id, worker_id="worker-1")

    with SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        handler.run(job, ctx, settings)

    assert not execute_item_called, "Item failed in reconciliation must NOT be passed to execute_item in same run!"

    with SessionLocal() as session:
        it = session.get(BatchPlanItem, item_id)
        assert it.state == "failed", f"Expected failed, got {it.state}"
        assert "target identity mismatch" in (it.reason or ""), f"Reason should be reconciliation failure, got: {it.reason}"
