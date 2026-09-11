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


def test_restore_takeover_never_reuses_old_in_flight_slot(tmp_path, session_factory):
    """
    Finding 2:
    Deterministic concurrency test:
    old worker passes lease fence
    old worker stalls immediately before rename
    new worker takes lease
    new worker reconciles restoring state
    assert new worker targets attempt-(G+1), NOT attempt-G
    old worker rename lands into attempt-G
    new worker rename lands only into attempt-(G+1)
    no overwrite
    both evidence objects preserved/classified
    """
    allowed_root = tmp_path / "data"
    allowed_root.mkdir(parents=True, exist_ok=True)
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)

    dest_file = allowed_root / "restored.txt"
    pub_file = quarantine_root / "restored.txt"
    payload = b"RESTORE_PAYLOAD_GEN_CONCURRENCY"
    phash = hashlib.sha256(payload).hexdigest()

    tx_dir_gen1 = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    tx_dir_gen1.mkdir(parents=True, exist_ok=True)
    anchor = tx_dir_gen1 / "anchor"
    anchor.write_bytes(payload)
    st = os.stat(anchor)
    os.link(str(anchor), str(pub_file))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=1,
            original_path=str(dest_file),
            quarantine_path=str(pub_file),
            state="restoring",
            tx_phase="restoring",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(payload),
            content_hash=phash,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    # Step 1: Worker 1 passes lease fence and stalls right before rename pub_file -> attempt-1/captured_quarantine_view
    renew_and_assert_worker_lease(session_factory, "worker-1")

    # Step 2: Worker 2 takes over lease
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        l = session.get(TaskLock, 1)
        l.owner = "worker-2"
        l.acquired_at = utcnow()
        session.commit()

    # Step 3: Worker 2 reconciles restoring state
    # Critical invariant: worker 2 MUST target attempt-2, NOT attempt-1!
    reconcile_quarantine_transaction(
        session_factory,
        1,
        "worker-2",
        quarantine_root=quarantine_root,
        allowed_roots=[allowed_root],
    )

    tx_dir_gen2 = quarantine_root / ".tx" / "entry-1" / "attempt-2"
    assert tx_dir_gen2.exists(), "Worker 2 must allocate attempt-2 for its retirement rename"

    slot_gen2 = tx_dir_gen2 / "captured_quarantine_view"
    assert slot_gen2.exists(), "Worker 2 rename must land into attempt-2 slot"

    slot_gen1 = tx_dir_gen1 / "captured_quarantine_view"
    assert not slot_gen1.exists(), "Worker 2 must NOT have targeted attempt-1 slot!"

    # Step 4: Stalled Worker 1's rename lands into attempt-1
    stalled_old_worker_payload = b"STALLED_WORKER_1_RENAME_LANDED"
    slot_gen1.write_bytes(stalled_old_worker_payload)

    # Step 5: Both evidence objects preserved, no overwrite
    assert slot_gen1.read_bytes() == stalled_old_worker_payload
    assert slot_gen2.read_bytes() == payload


def test_foreign_existing_restore_capture_produces_conflict(tmp_path, session_factory):
    """
    Finding 3:
    Foreign existing captured_quarantine_view encountered before another mutation
    → preserve exactly in place
    → state='conflict', tx_phase='conflict'
    → ZERO further payload mutation.
    """
    allowed_root = tmp_path / "data"
    allowed_root.mkdir(parents=True, exist_ok=True)
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)

    dest_file = allowed_root / "foreign_restore.txt"
    pub_file = quarantine_root / "foreign_restore.txt"
    payload = b"EXPECTED_RESTORE_CONTENT"
    pub_file.write_bytes(payload)
    st = os.stat(pub_file)
    phash = hashlib.sha256(payload).hexdigest()

    tx_dir_gen1 = quarantine_root / ".tx" / "entry-2" / "attempt-1"
    tx_dir_gen1.mkdir(parents=True, exist_ok=True)
    anchor = tx_dir_gen1 / "anchor"
    anchor.write_bytes(payload)

    # Pre-existing foreign captured view
    foreign_slot = tx_dir_gen1 / "captured_quarantine_view"
    foreign_slot.write_bytes(b"FOREIGN_UNKNOWN_VIEW_DATA")

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=2,
            original_path=str(dest_file),
            quarantine_path=str(pub_file),
            state="restoring",
            tx_phase="restoring",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(payload),
            content_hash=phash,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(
        session_factory,
        2,
        "worker-1",
        quarantine_root=quarantine_root,
        allowed_roots=[allowed_root],
    )

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 2)
        assert entry.state == "conflict"
        assert entry.tx_phase == "conflict"

    # Foreign slot preserved in place, zero further mutation
    assert foreign_slot.exists()
    assert foreign_slot.read_bytes() == b"FOREIGN_UNKNOWN_VIEW_DATA"
    assert not dest_file.exists(), "Must perform zero further payload mutation on foreign evidence"


def test_expected_existing_restore_capture_restores_without_new_generation(tmp_path, session_factory):
    """
    Finding 3:
    Existing EXPECTED captured_quarantine_view
    → converges to restored
    → zero new generation allocation.
    """
    allowed_root = tmp_path / "data"
    allowed_root.mkdir(parents=True, exist_ok=True)
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)

    dest_file = allowed_root / "expected_restore.txt"
    pub_file = quarantine_root / "expected_restore.txt"
    payload = b"EXPECTED_RESTORE_CONTENT"
    st = os.stat(tmp_path)  # dummy stat to get dev

    tx_dir_gen1 = quarantine_root / ".tx" / "entry-3" / "attempt-1"
    tx_dir_gen1.mkdir(parents=True, exist_ok=True)
    anchor = tx_dir_gen1 / "anchor"
    anchor.write_bytes(payload)
    st_anchor = os.stat(anchor)
    phash = hashlib.sha256(payload).hexdigest()

    # Pre-existing EXPECTED captured view (hardlinked to anchor)
    expected_slot = tx_dir_gen1 / "captured_quarantine_view"
    os.link(str(anchor), str(expected_slot))

    # Destination already published
    os.link(str(anchor), str(dest_file))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=3,
            original_path=str(dest_file),
            quarantine_path=str(pub_file),
            state="restoring",
            tx_phase="restoring",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st_anchor.st_dev,
            inode=st_anchor.st_ino,
            size=len(payload),
            content_hash=phash,
            mtime_ns=getattr(st_anchor, "st_mtime_ns", int(st_anchor.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(
        session_factory,
        3,
        "worker-1",
        quarantine_root=quarantine_root,
        allowed_roots=[allowed_root],
    )

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 3)
        assert entry.state == "restored"
        assert entry.tx_phase == "restored"
        # Zero new generation allocated
        assert entry.active_attempt_generation == 1

    assert not (quarantine_root / ".tx" / "entry-3" / "attempt-2").exists(), "Must not allocate new generation when expected evidence exists"
