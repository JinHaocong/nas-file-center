import errno
import hashlib
import json
import os
from pathlib import Path
import pytest
from sqlalchemy import text, select
from app.models import (
    BatchPlan,
    BatchPlanItem,
    QuarantineEntry,
    TaskLock,
    utcnow,
)
from app.db import create_engine_and_session, init_db
from app.config import Settings
from app.service import FileCenterService
from app.execution.executor import execute_item
from app.quarantine.engine import execute_transactional_quarantine
from app.quarantine.restore import execute_transactional_restore
from app.tasks.handlers import _reconcile_executing_item


@pytest.fixture
def test_env(tmp_path):
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    q_dir = data_dir / ".trash"
    config_dir.mkdir()
    data_dir.mkdir()
    q_dir.mkdir()

    settings = Settings(
        config_dir=config_dir,
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
        quarantine_root=q_dir,
        allow_mutation=True,
        allow_delete=True,
    )
    service = FileCenterService(settings=settings)
    return {
        "service": service,
        "settings": settings,
        "data_dir": data_dir,
        "q_dir": q_dir,
        "session_factory": service.SessionLocal,
    }


def test_e2e_compat_quarantine_and_restore_lifecycle(test_env, monkeypatch):
    service = test_env["service"]
    session_factory = test_env["session_factory"]
    data_dir = test_env["data_dir"]
    q_dir = test_env["q_dir"]
    settings = test_env["settings"]

    # Simulate non-atomic filesystem to trigger COMPAT_TRANSACTIONAL route
    monkeypatch.setattr("app.quarantine.capability._probe_rename_noreplace_supported", lambda dir_fd: False)

    # 1. Setup source file
    source_file = data_dir / "document.pdf"
    content = b"%PDF-1.4 CRITICAL USER DOCUMENT DATA"
    source_file.write_bytes(content)
    st = os.stat(source_file)
    content_hash = hashlib.sha256(content).hexdigest()

    # 2. Setup active worker lease
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-main", acquired_at=utcnow())
        session.add(lock)

        plan = BatchPlan(
            id=1,
            name="E2E Quarantine Plan",
            kind="quarantine",
            status="executing",
        )
        session.add(plan)

        pub_target = q_dir / "document.pdf"
        item = BatchPlanItem(
            id=1,
            plan_id=1,
            sequence=1,
            operation="quarantine",
            source_path=str(source_file),
            target_path=str(pub_target),
            expected_size=len(content),
            expected_hash=content_hash,
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
            state="executing",
        )
        session.add(item)
        session.flush()

        entry = QuarantineEntry(
            plan_item_id=1,
            original_path=str(source_file),
            quarantine_path=str(pub_target),
            state="preparing",
            size=len(content),
            content_hash=content_hash,
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    # 3. Execute item via executor
    from app.batch.plans import OperationItem
    op_item = OperationItem(
        sequence=1,
        operation="quarantine",
        source=source_file,
        target=pub_target,
        expected_size=len(content),
        expected_hash=content_hash,
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
        expected_mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
    )
    res = execute_item(
        op_item,
        allowed_roots=settings.allowed_roots,
        allow_mutation=settings.allow_mutation,
        allow_delete=settings.allow_delete,
        quarantine_root=settings.quarantine_root,
        plan_id="1",
        session_factory=session_factory,
        worker_id="worker-main",
        quarantine_entry_id=entry_id,
    )
    assert res.state == "completed", f"execute_item failed: {res.reason}"

    with session_factory() as session:
        it = session.get(BatchPlanItem, 1)
        it.state = "completed"
        session.commit()

    # Verify post-quarantine state
    with session_factory() as session:
        entry = session.scalar(select(QuarantineEntry).where(QuarantineEntry.plan_item_id == 1))
        assert entry is not None
        assert entry.state == "active"
        assert entry.tx_phase == "active"
        assert entry.authoritative_anchor_path is not None
        anchor = Path(entry.authoritative_anchor_path)
        assert anchor.exists()
        assert anchor.read_bytes() == content

        # Original path captured
        assert not source_file.exists()
        attempt_dir = anchor.parent
        assert (attempt_dir / "captured_source").exists()
        assert (attempt_dir / "captured_source").read_bytes() == content

        # Public quarantine path exists and is linked
        assert pub_target.exists()
        assert pub_target.stat().st_ino == anchor.stat().st_ino

        # Batch item marked completed
        it = session.get(BatchPlanItem, 1)
        assert it.state == "completed"

    # 4. Zero Payload-Bearing Unlink Guard: Attempt to purge active compat entry
    with pytest.raises(OSError) as exc:
        service.purge_quarantine_entry(entry.id, confirmation="DELETE", is_admin=True)
    assert exc.value.errno == errno.EOPNOTSUPP
    assert anchor.exists()
    assert pub_target.exists()

    # 5. Restore entry
    restore_res = service.restore_quarantine_entry(entry.id, worker_id="worker-main")
    assert restore_res["status"] == "succeeded"

    with session_factory() as session:
        refreshed_entry = session.get(QuarantineEntry, entry.id)
        assert refreshed_entry.state == "restored"
        assert refreshed_entry.tx_phase == "restored"

    # Verify post-restore state
    assert source_file.exists()
    assert source_file.read_bytes() == content
    assert source_file.stat().st_ino == anchor.stat().st_ino
    # Public view retired
    assert not pub_target.exists()
    assert (attempt_dir / "captured_quarantine_view").exists()
    # Authoritative anchor intact
    assert anchor.exists()


def test_e2e_compat_crash_recovery_during_quarantine(test_env):
    session_factory = test_env["session_factory"]
    data_dir = test_env["data_dir"]
    q_dir = test_env["q_dir"]
    settings = test_env["settings"]

    source_file = data_dir / "crash_test.txt"
    content = b"CRASH_RECOVERY_CONTENT"
    source_file.write_bytes(content)
    st = os.stat(source_file)
    content_hash = hashlib.sha256(content).hexdigest()

    pub_target = q_dir / "crash_test.txt"
    tx_dir = q_dir / ".tx" / "entry-99" / "attempt-1"
    tx_dir.mkdir(parents=True)
    anchor = tx_dir / "anchor"
    os.link(str(source_file), str(anchor))
    os.link(str(anchor), str(pub_target))

    # Crash simulated: FS linked anchor and public view, but DB was interrupted at preparing/authoritative_anchored
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-recovery", acquired_at=utcnow())
        session.add(lock)

        plan = BatchPlan(id=2, name="Crash Plan", kind="quarantine", status="executing")
        session.add(plan)

        item = BatchPlanItem(
            id=99,
            plan_id=2,
            sequence=1,
            operation="quarantine",
            source_path=str(source_file),
            target_path=str(pub_target),
            expected_size=len(content),
            expected_hash=content_hash,
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
            state="executing",
        )
        session.add(item)
        session.flush()

        entry = QuarantineEntry(
            id=99,
            plan_item_id=99,
            original_path=str(source_file),
            quarantine_path=str(pub_target),
            state="preparing",
            tx_phase="authoritative_anchored",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(content),
            content_hash=content_hash,
        )
        session.add(entry)
        session.commit()

    # Recovery worker runs reconciliation on executing item
    with session_factory() as session:
        now = utcnow()
        it = session.get(BatchPlanItem, 99)
        _reconcile_executing_item(
            session,
            it,
            plan_id=2,
            job_id=200,
            user_id=1,
            settings=settings,
            now=now,
            worker_id="worker-recovery",
        )
        session.commit()

    with session_factory() as session:
        it = session.get(BatchPlanItem, 99)
        assert it.state == "completed"
        entry = session.get(QuarantineEntry, 99)
        assert entry.state == "active"
        assert entry.tx_phase == "active"

    # Source captured and original source removed
    assert not source_file.exists()
    assert (tx_dir / "captured_source").exists()
    assert (tx_dir / "captured_source").read_bytes() == content
