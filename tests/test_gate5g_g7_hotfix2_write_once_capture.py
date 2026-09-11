import hashlib
import os
from pathlib import Path
import pytest
from sqlalchemy import text

from app.models import QuarantineEntry, utcnow, TaskLock
from app.db import create_engine_and_session, init_db
from app.quarantine.reconcile import reconcile_quarantine_transaction
from app.quarantine.restore import execute_transactional_restore
from app.tasks.recovery import renew_and_assert_worker_lease


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal


def test_write_once_capture_under_lease_takeover_does_not_target_old_slot(tmp_path, session_factory):
    """
    HOTFIX2 Item 7 Test A:
    Deterministic race:
    old worker passes fence and stalls before capture rename
    → new worker takes lease
    → new worker must NOT target old generation capture slot
    → old rename lands
    → both payloads/evidence preserved
    → no overwrite.
    """
    allowed_root = tmp_path / "data"
    allowed_root.mkdir(parents=True, exist_ok=True)
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)

    source = allowed_root / "source.txt"
    payload_1 = b"PAYLOAD_WORKER_1_STALLED"
    source.write_bytes(payload_1)
    st = os.stat(source)

    pub_path = quarantine_root / "source.txt"

    tx_dir_gen1 = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    tx_dir_gen1.mkdir(parents=True, exist_ok=True)
    anchor_gen1 = tx_dir_gen1 / "anchor"
    anchor_gen1.write_bytes(payload_1)

    # Public path is published from anchor
    os.link(str(anchor_gen1), str(pub_path))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=1,
            original_path=str(source),
            quarantine_path=str(pub_path),
            state="preparing",
            tx_phase="public_published",
            authoritative_anchor_path=str(anchor_gen1),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(payload_1),
            content_hash=hashlib.sha256(payload_1).hexdigest(),
        )
        session.add(entry)
        session.commit()

    # Step 1: Worker 1 passes lease fence and stalls before capture rename
    renew_and_assert_worker_lease(session_factory, "worker-1")
    # Worker 1 is now stalled holding the intent to rename source to tx_dir_gen1 / "captured_source"

    # Step 2: Worker 2 takes over lease!
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        l = session.get(TaskLock, 1)
        l.owner = "worker-2"
        l.acquired_at = utcnow()
        session.commit()

    # In the meantime, third party placed a replacement file at source
    payload_2 = b"PAYLOAD_REPLACED_AT_SOURCE_FOR_WORKER_2"
    source.write_bytes(payload_2)

    # Step 3: Worker 2 reconciles / executes:
    # Worker 2 sees attempt-1/captured_source is absent.
    # CRITICAL INVARIANT: Worker 2 MUST NOT issue a rename into attempt-1/captured_source!
    # Worker 2 must allocate generation 2 (attempt-2).
    reconcile_quarantine_transaction(
        session_factory,
        1,
        "worker-2",
        quarantine_root=quarantine_root,
        allowed_roots=[allowed_root],
    )

    # Verify attempt-2 was created and used by worker 2
    tx_dir_gen2 = quarantine_root / ".tx" / "entry-1" / "attempt-2"
    assert tx_dir_gen2.exists(), "Worker 2 must allocate a new generation slot"

    # Step 4: Stalled Worker 1's rename lands into attempt-1/captured_source!
    # (Simulated landing of the in-flight syscall into its authorized gen 1 slot)
    slot_gen1 = tx_dir_gen1 / "captured_source"
    slot_gen1.write_bytes(payload_1)

    # Step 5: Both evidence slots must be preserved! Neither overwrote the other!
    assert slot_gen1.exists()
    assert slot_gen1.read_bytes() == payload_1

    slot_gen2 = tx_dir_gen2 / "captured_source"
    assert slot_gen2.exists()
    assert slot_gen2.read_bytes() == payload_2


def test_write_once_view_retirement_under_lease_takeover_does_not_target_old_slot(tmp_path, session_factory):
    """
    HOTFIX2 Item 7 Test B:
    Restore view retirement under lease takeover:
    Each restore attempt allocates a dedicated generation so that view retirement
    targets a uniquely allocated write-once slot and does not overwrite older attempt slots.
    """
    allowed_root = tmp_path / "data"
    allowed_root.mkdir(parents=True, exist_ok=True)
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)

    orig_path = allowed_root / "restored.txt"
    pub_path = quarantine_root / "restored.txt"

    payload = b"PAYLOAD_RESTORING"
    tx_dir_gen1 = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    tx_dir_gen1.mkdir(parents=True, exist_ok=True)
    anchor = tx_dir_gen1 / "anchor"
    anchor.write_bytes(payload)
    st = os.stat(anchor)
    os.link(str(anchor), str(pub_path))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=1,
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
        session.add(entry)
        session.commit()

    # Execute transactional restore by worker-1 (lease takeover / new restore attempt):
    # Must allocate a new generation for the restore attempt so that attempt-1 is never targeted!
    execute_transactional_restore(
        session_factory,
        1,
        "worker-1",
        allowed_roots=[allowed_root],
        quarantine_root=quarantine_root,
    )

    # Attempt 1 slot must NOT have been used
    old_view_slot = tx_dir_gen1 / "captured_quarantine_view"
    assert not old_view_slot.exists(), "New restore attempt must not target attempt-1 slot"

    # Restore attempt used generation 2
    tx_dir_gen2 = quarantine_root / ".tx" / "entry-1" / "attempt-2"
    assert tx_dir_gen2.exists()
    assert (tx_dir_gen2 / "captured_quarantine_view").read_bytes() == payload
    assert orig_path.read_bytes() == payload

    # Stalled Worker's delayed rename lands into attempt-1 slot
    old_view_slot.write_bytes(b"STALLED_PREVIOUS_WORKER_LANDED")
    # Both evidence slots preserved without overwrite
    assert old_view_slot.read_bytes() == b"STALLED_PREVIOUS_WORKER_LANDED"
    assert (tx_dir_gen2 / "captured_quarantine_view").read_bytes() == payload
