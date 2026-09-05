import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select, text

import app.quarantine.restore as restore_mod
import app.service as service_mod
import app.tasks.handlers as handlers_mod
from app.config import Settings
from app.models import (
    BatchPlan,
    BatchPlanItem,
    OperationJournal,
    QuarantineEntry,
    TaskLock,
    WorkJob,
    utcnow,
)
from app.quarantine.paths import safe_quarantine_hash
from app.service import FileCenterService
from app.tasks.context import JobContext
from app.tasks.handlers import (
    BatchPlanExecuteHandler,
    _reconcile_executing_item,
    gather_reconcile_evidence,
)


def _setup_service(tmp_path: Path):
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir(parents=True, exist_ok=True)
    q_dir = allowed_dir / ".quarantine"
    q_dir.mkdir(parents=True, exist_ok=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        config_dir=config_dir,
        data_mount=allowed_dir,
        allowed_roots_raw=str(allowed_dir),
        quarantine_root=str(q_dir),
        allow_mutation=True,
        allow_delete=True,
    )
    service = FileCenterService(settings=settings)
    return service, allowed_dir, q_dir, settings


def _overwrite_same_inode(path: Path, new_bytes: bytes, target_mtime_ns: int):
    """Overwrite path in-place to preserve inode and size, then restore original mtime."""
    orig_st = path.stat(follow_symlinks=False)
    assert len(new_bytes) == orig_st.st_size, "Payload length must match exactly"
    with open(path, "r+b") as f:
        f.seek(0)
        f.write(new_bytes)
        f.flush()
        os.fsync(f.fileno())

    os.utime(path, ns=(target_mtime_ns, target_mtime_ns), follow_symlinks=False)

    after_st = path.stat(follow_symlinks=False)
    assert after_st.st_ino == orig_st.st_ino, "Must preserve inode"
    assert after_st.st_dev == orig_st.st_dev, "Must preserve device"
    assert after_st.st_size == orig_st.st_size, "Must preserve size"
    assert getattr(after_st, "st_mtime_ns", int(after_st.st_mtime * 1e9)) == target_mtime_ns, "Must restore mtime"


def test_direct_restore_same_size_same_mtime_tamper_after_hash_is_rejected(tmp_path):
    """
    Blocker A: Direct Restore Same-mtime Tamper
    quarantine source content: ORIGINAL-CONTENT-1234
    After hash verification but before rename_noreplace:
    external actor overwrites SAME inode with TAMPERED-CONTENT-1234 and restores mtime.
    Restore must reject mutation, original path remains absent, quarantine source remains,
    entry is safe non-success (inconsistent), no success OperationJournal.
    """
    service, allowed_dir, q_dir, settings = _setup_service(tmp_path)

    orig_path = allowed_dir / "target.txt"
    q_file = q_dir / "direct_q.bin"
    original_content = b"ORIGINAL-CONTENT-1234"
    tampered_content = b"TAMPERED-CONTENT-1234"
    assert len(original_content) == len(tampered_content)

    q_file.write_bytes(original_content)
    orig_hash = safe_quarantine_hash(q_file)
    orig_st = q_file.stat(follow_symlinks=False)
    orig_mtime_ns = getattr(orig_st, "st_mtime_ns", int(orig_st.st_mtime * 1e9))

    now = utcnow()
    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(orig_path),
            quarantine_path=str(q_file),
            state="active",
            content_hash=orig_hash,
            size=len(original_content),
            mtime_ns=orig_mtime_ns,
            device=orig_st.st_dev,
            inode=orig_st.st_ino,
            quarantined_at=now,
            updated_at=now,
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    assert not orig_path.exists()
    assert q_file.exists()

    # Intercept verify_quarantine_source_integrity: after hash verification, tamper file in place
    real_verify = restore_mod.verify_quarantine_source_integrity

    def hook_verify(target, expected_size=None, expected_hash=None):
        verified_stat = real_verify(target, expected_size, expected_hash)
        _overwrite_same_inode(target, tampered_content, orig_mtime_ns)
        return verified_stat

    restore_mod.verify_quarantine_source_integrity = hook_verify
    service_mod.verify_quarantine_source_integrity = hook_verify
    try:
        with pytest.raises(ValueError):
            service.restore_quarantine_entry(entry_id)
    finally:
        restore_mod.verify_quarantine_source_integrity = real_verify
        service_mod.verify_quarantine_source_integrity = real_verify

    # Verify postconditions
    assert not orig_path.exists(), "Original path must not be created with tampered data"
    assert q_file.exists(), "Quarantined source must remain"
    assert q_file.read_bytes() == tampered_content, "Quarantined file contains tampered bytes"

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry.state != "restored", f"Entry must not be restored, got {entry.state}"
        assert entry.state == "inconsistent"

        journals = session.scalars(
            select(OperationJournal).where(OperationJournal.operation == "restore")
        ).all()
        assert len(journals) == 0, "No success OperationJournal should be written"


def test_worker_restore_same_size_same_mtime_tamper_is_rejected(tmp_path):
    """
    Worker Restore Same-mtime Tamper
    Worker executing restore plan: after pre-mutation hash integrity check,
    file is tampered in-place with same inode and restored mtime.
    Worker must fail the item, original path absent, entry inconsistent, no success Journal.
    """
    service, allowed_dir, q_dir, settings = _setup_service(tmp_path)

    orig_path = allowed_dir / "worker_restore.txt"
    q_file = q_dir / "worker_q.bin"
    original_content = b"ORIGINAL-CONTENT-1234"
    tampered_content = b"TAMPERED-CONTENT-1234"
    assert len(original_content) == len(tampered_content)

    q_file.write_bytes(original_content)
    orig_hash = safe_quarantine_hash(q_file)
    orig_st = q_file.stat(follow_symlinks=False)
    orig_mtime_ns = getattr(orig_st, "st_mtime_ns", int(orig_st.st_mtime * 1e9))

    now = utcnow()
    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(orig_path),
            quarantine_path=str(q_file),
            state="active",
            content_hash=orig_hash,
            size=len(original_content),
            mtime_ns=orig_mtime_ns,
            device=orig_st.st_dev,
            inode=orig_st.st_ino,
            quarantined_at=now,
            updated_at=now,
        )
        session.add(entry)
        session.flush()

        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1, locked=True, owner="test-worker", acquired_at=now)
            session.add(lock)
        else:
            lock.locked = True
            lock.owner = "test-worker"
            lock.acquired_at = now

        plan = BatchPlan(
            name="restore-plan",
            kind="organize",
            status="ready",
            created_at=now,
        )
        session.add(plan)
        session.flush()

        job = WorkJob(
            kind="batch-plan-execute",
            status="running",
            started_at=now,
            state_json=json.dumps({"plan_id": plan.id}),
        )
        session.add(job)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="restore",
            source_path=str(q_file),
            target_path=str(orig_path),
            state="pending",
            metadata_json=json.dumps({
                "quarantine_entry_id": entry.id,
                "expected_hash": orig_hash,
                "expected_size": len(original_content),
            }),
        )
        session.add(item)
        session.commit()
        entry_id = entry.id
        job_id = job.id
        item_id = item.id

    real_verify = restore_mod.verify_quarantine_source_integrity

    def hook_verify(target, expected_size=None, expected_hash=None):
        verified_stat = real_verify(target, expected_size, expected_hash)
        _overwrite_same_inode(target, tampered_content, orig_mtime_ns)
        return verified_stat

    handlers_mod.verify_quarantine_source_integrity = hook_verify
    restore_mod.verify_quarantine_source_integrity = hook_verify
    try:
        context = JobContext(
            service.engine,
            service.SessionLocal,
            job_id,
            worker_id="test-worker",
        )
        handler = BatchPlanExecuteHandler()
        with service.SessionLocal() as session:
            job_obj = session.get(WorkJob, job_id)
        handler.run(job_obj, context, settings)
    finally:
        handlers_mod.verify_quarantine_source_integrity = real_verify
        restore_mod.verify_quarantine_source_integrity = real_verify

    assert not orig_path.exists(), "Original path must not be restored with tampered data"
    assert q_file.exists(), "Quarantined file must remain"

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item.state == "failed", f"Item must fail, got {item.state}"

        entry = session.get(QuarantineEntry, entry_id)
        assert entry.state != "restored", f"QuarantineEntry must not be restored, got {entry.state}"
        assert entry.state == "inconsistent"

        journals = session.scalars(
            select(OperationJournal).where(OperationJournal.operation == "restore")
        ).all()
        assert len(journals) == 0, "No success OperationJournal should exist"


def test_restore_reconciliation_same_inode_same_size_restored_mtime_tamper_fails_closed(tmp_path):
    """
    Blocker B: Restore Crash Reconciliation Same-mtime Tamper
    Physical restore happened before crash. Phase A gathers valid evidence for ORIGINAL.
    Before Phase B: overwrite target with same-length TAMPERED content and restore mtime.
    Phase B must fail-closed: item failed, entry not restored, no success Journal, no hash under BEGIN IMMEDIATE.
    """
    service, allowed_dir, q_dir, settings = _setup_service(tmp_path)

    orig_path = allowed_dir / "target.txt"
    original_content = b"ORIGINAL-CONTENT-1234"
    tampered_content = b"TAMPERED-CONTENT-1234"
    assert len(original_content) == len(tampered_content)

    orig_path.write_bytes(original_content)
    orig_hash = safe_quarantine_hash(orig_path)
    orig_st = orig_path.stat(follow_symlinks=False)
    orig_mtime_ns = getattr(orig_st, "st_mtime_ns", int(orig_st.st_mtime * 1e9))

    now = utcnow()
    q_file = q_dir / "test.q"  # absent

    with service.SessionLocal() as session:
        job = WorkJob(
            id=10,
            kind="batch-plan-execute",
            status="running",
            started_at=now,
            state_json=json.dumps({"plan_id": 1}),
        )
        session.add(job)
        session.flush()

        entry = QuarantineEntry(
            original_path=str(orig_path),
            quarantine_path=str(q_file),
            state="restoring",
            content_hash=orig_hash,
            size=len(original_content),
            mtime_ns=orig_mtime_ns,
            device=orig_st.st_dev,
            inode=orig_st.st_ino,
            quarantined_at=now,
            updated_at=now,
        )
        session.add(entry)
        session.flush()

        plan = BatchPlan(
            name="restore-crash-plan",
            kind="batch-rename",
            status="ready",
            created_at=now,
        )
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="restore",
            source_path=str(q_file),
            target_path=str(orig_path),
            state="executing",
            metadata_json=json.dumps({
                "quarantine_entry_id": entry.id,
                "expected_hash": orig_hash,
                "expected_size": len(original_content),
                "execution": {
                    "source_stat": {
                        "device": orig_st.st_dev,
                        "inode": orig_st.st_ino,
                        "size": orig_st.st_size,
                        "mtime_ns": orig_mtime_ns,
                    },
                },
            }),
        )
        session.add(item)
        session.commit()
        entry_id = entry.id
        item_id = item.id
        plan_id = plan.id
        job_id = job.id

    # Phase A: gather valid evidence for ORIGINAL target
    evidence = gather_reconcile_evidence(orig_path)
    assert evidence is not None
    assert evidence.content_hash == orig_hash

    # Before Phase B: overwrite target with same length TAMPERED content and restore mtime
    _overwrite_same_inode(orig_path, tampered_content, orig_mtime_ns)

    # Phase B: run reconciliation
    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        item_row = session.get(BatchPlanItem, item_id)
        _reconcile_executing_item(
            session,
            item_row,
            plan_id=plan_id,
            job_id=job_id,
            user_id=None,
            settings=settings,
            now=now,
            precomputed_evidence=evidence,
        )
        session.commit()

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item.state == "failed", f"Item must fail, got {item.state}"

        entry = session.get(QuarantineEntry, entry_id)
        assert entry.state != "restored", f"QuarantineEntry must not be restored, got {entry.state}"
        assert entry.state == "inconsistent"

        journals = session.scalars(
            select(OperationJournal).where(OperationJournal.operation == "restore")
        ).all()
        assert len(journals) == 0, "No success OperationJournal should exist"


def test_quarantine_reconciliation_same_inode_same_size_restored_mtime_tamper_fails_closed(tmp_path):
    """
    Blocker C: Quarantine Crash Reconciliation Same-mtime Tamper
    Quarantine physically completed before crash. Phase A gathers valid evidence for ORIGINAL in quarantine.
    Before Phase B: overwrite quarantine file with same-length TAMPERED content and restore mtime.
    Phase B must fail-closed: item failed, entry not active, no success Journal, no false content_hash.
    """
    service, allowed_dir, q_dir, settings = _setup_service(tmp_path)

    orig_path = allowed_dir / "to_quarantine.txt"  # absent
    q_file = q_dir / "item.q"
    original_content = b"ORIGINAL-CONTENT-1234"
    tampered_content = b"TAMPERED-CONTENT-1234"
    assert len(original_content) == len(tampered_content)

    q_file.write_bytes(original_content)
    orig_hash = safe_quarantine_hash(q_file)
    orig_st = q_file.stat(follow_symlinks=False)
    orig_mtime_ns = getattr(orig_st, "st_mtime_ns", int(orig_st.st_mtime * 1e9))

    now = utcnow()

    with service.SessionLocal() as session:
        job = WorkJob(
            id=20,
            kind="batch-plan-execute",
            status="running",
            started_at=now,
            state_json=json.dumps({"plan_id": 1}),
        )
        session.add(job)
        session.flush()

        plan = BatchPlan(
            name="quarantine-crash-plan",
            kind="batch-rename",
            status="ready",
            created_at=now,
        )
        session.add(plan)
        session.flush()

        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="quarantine",
            source_path=str(orig_path),
            target_path=str(q_file),
            state="executing",
            metadata_json=json.dumps({
                "execution": {
                    "source_stat": {
                        "device": orig_st.st_dev,
                        "inode": orig_st.st_ino,
                        "size": orig_st.st_size,
                        "mtime_ns": orig_mtime_ns,
                    },
                },
            }),
        )
        session.add(item)
        session.flush()

        entry = QuarantineEntry(
            plan_item_id=item.id,
            original_path=str(orig_path),
            quarantine_path=str(q_file),
            state="quarantining",
            content_hash=None,
            size=len(original_content),
            mtime_ns=orig_mtime_ns,
            device=orig_st.st_dev,
            inode=orig_st.st_ino,
            quarantined_at=now,
            updated_at=now,
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id
        item_id = item.id
        plan_id = plan.id
        job_id = job.id

    # Phase A: gather valid evidence for ORIGINAL target in quarantine
    evidence = gather_reconcile_evidence(q_file)
    assert evidence is not None
    assert evidence.content_hash == orig_hash

    # Before Phase B: overwrite quarantine file with same length TAMPERED content and restore mtime
    _overwrite_same_inode(q_file, tampered_content, orig_mtime_ns)

    # Phase B: run reconciliation
    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        item_row = session.get(BatchPlanItem, item_id)
        _reconcile_executing_item(
            session,
            item_row,
            plan_id=plan_id,
            job_id=job_id,
            user_id=None,
            settings=settings,
            now=now,
            precomputed_evidence=evidence,
        )
        session.commit()

    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item.state == "failed", f"Item must fail, got {item.state}"

        entry = session.get(QuarantineEntry, entry_id)
        assert entry.state != "active", f"QuarantineEntry must not be active, got {entry.state}"
        assert entry.state == "abandoned"
        assert entry.content_hash != orig_hash, "False content_hash must not be persisted"

        journals = session.scalars(
            select(OperationJournal).where(OperationJournal.operation == "quarantine")
        ).all()
        assert len(journals) == 0, "No success OperationJournal should exist"


def test_reconcile_evidence_rejects_file_changed_during_hash(tmp_path):
    """
    Test real evidence-gathering boundary:
    If file content/stat changes while safe_quarantine_hash is running,
    gather_reconcile_evidence must detect stat_before != stat_after and return None.
    """
    target = tmp_path / "dynamic_file.txt"
    target.write_bytes(b"HELLO-WORLD-1111")
    orig_st = target.stat(follow_symlinks=False)
    orig_mtime_ns = getattr(orig_st, "st_mtime_ns", int(orig_st.st_mtime * 1e9))

    real_hash = handlers_mod.safe_quarantine_hash

    def mutating_hash(p: Path) -> str:
        # File mutates during hash computation
        h = real_hash(p)
        target.write_bytes(b"HELLO-WORLD-2222")  # mutates content and timestamps
        return h

    handlers_mod.safe_quarantine_hash = mutating_hash
    try:
        evidence = gather_reconcile_evidence(target)
        assert evidence is None, f"Expected None when file changes during hash, got {evidence}"
    finally:
        handlers_mod.safe_quarantine_hash = real_hash
