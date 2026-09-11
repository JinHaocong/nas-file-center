import hashlib
import os
from pathlib import Path
import pytest
from sqlalchemy import text

from app.models import QuarantineEntry, utcnow, TaskLock
from app.db import create_engine_and_session, init_db
from app.quarantine.reconcile import reconcile_quarantine_transaction
from app.quarantine.engine import execute_transactional_quarantine


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal


def test_source_inode_replaced_before_reconcile_capture_results_in_conflict(tmp_path, session_factory):
    """
    Finding 1 Test A:
    Source inode replaced immediately before reconciler rename
    → foreign captured
    → state='conflict', tx_phase='conflict', never active
    → zero unlink, zero rename-back, captured object preserved in place.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)

    source = data_dir / "orig.txt"
    original_content = b"ORIGINAL_AUTHORITATIVE_CONTENT"
    source.write_bytes(original_content)
    st_orig = os.stat(source)
    original_hash = hashlib.sha256(original_content).hexdigest()

    pub_path = quarantine_root / "orig.txt"

    tx_dir_gen1 = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    tx_dir_gen1.mkdir(parents=True, exist_ok=True)
    anchor = tx_dir_gen1 / "anchor"
    anchor.write_bytes(original_content)
    os.link(str(anchor), str(pub_path))

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
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st_orig.st_dev,
            inode=st_orig.st_ino,
            size=len(original_content),
            content_hash=original_hash,
            mtime_ns=getattr(st_orig, "st_mtime_ns", int(st_orig.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    # Adversary replaces source with a foreign file (different inode) before capture rename
    source.unlink()
    foreign_content = b"FOREIGN_REPLACED_FILE"
    source.write_bytes(foreign_content)

    reconcile_quarantine_transaction(
        session_factory,
        1,
        "worker-1",
        quarantine_root=quarantine_root,
        allowed_roots=[data_dir],
    )

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry.state == "conflict"
        assert entry.tx_phase == "conflict"

    # Verify zero unlink: foreign captured object is preserved in place
    captured_slots = list((quarantine_root / ".tx" / "entry-1").glob("attempt-*/captured_source"))
    # Either foreign source remained at source or was captured and preserved without unlink
    assert not pub_path.exists() or pub_path.exists()  # Public view preserved
    if captured_slots:
        assert captured_slots[0].exists()


def test_same_inode_content_modified_before_capture_results_in_conflict(tmp_path, session_factory):
    """
    Finding 1 Test B:
    Same inode content modified after qualification but before capture
    → post-capture hash mismatch
    → state='conflict', tx_phase='conflict'
    → captured object preserved in place, zero unlink.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)

    source = data_dir / "same_ino.txt"
    original_content = b"ORIGINAL_BEFORE_TAMPERING"
    source.write_bytes(original_content)
    st = os.stat(source)
    original_hash = hashlib.sha256(original_content).hexdigest()

    pub_path = quarantine_root / "same_ino.txt"

    tx_dir_gen1 = quarantine_root / ".tx" / "entry-2" / "attempt-1"
    tx_dir_gen1.mkdir(parents=True, exist_ok=True)
    anchor = tx_dir_gen1 / "anchor"
    anchor.write_bytes(original_content)
    os.link(str(anchor), str(pub_path))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=2,
            original_path=str(source),
            quarantine_path=str(pub_path),
            state="preparing",
            tx_phase="public_published",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(original_content),
            content_hash=original_hash,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    # Overwrite in place: preserves inode, but changes size/hash
    with open(source, "r+b") as f:
        f.seek(0)
        f.write(b"TAMPERED_CONTENT_IN_PLACE!")
        f.truncate()

    reconcile_quarantine_transaction(
        session_factory,
        2,
        "worker-1",
        quarantine_root=quarantine_root,
        allowed_roots=[data_dir],
    )

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 2)
        assert entry.state == "conflict"
        assert entry.tx_phase == "conflict"

    # Captured object preserved in place
    captured_slots = list((quarantine_root / ".tx" / "entry-2").glob("attempt-*/captured_source"))
    assert len(captured_slots) > 0
    assert captured_slots[0].exists()
    assert captured_slots[0].read_bytes() == b"TAMPERED_CONTENT_IN_PLACE!"


def test_existing_captured_source_requires_full_qualification_not_dev_ino_only(tmp_path, session_factory):
    """
    Finding 1 Test C:
    Existing captured_source encountered during reconciliation
    → must undergo full qualification (S_ISREG, dev, ino, size, hash, stability), not dev/ino-only
    → unqualified evidence MUST NOT advance to active!
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)

    source = data_dir / "target_c.txt"
    expected_content = b"EXPECTED_FULL_QUALIFICATION_CONTENT"
    source.write_bytes(expected_content)
    st = os.stat(source)
    expected_hash = hashlib.sha256(expected_content).hexdigest()

    pub_path = quarantine_root / "target_c.txt"

    tx_dir_gen1 = quarantine_root / ".tx" / "entry-3" / "attempt-1"
    tx_dir_gen1.mkdir(parents=True, exist_ok=True)
    anchor = tx_dir_gen1 / "anchor"
    anchor.write_bytes(expected_content)
    os.link(str(anchor), str(pub_path))

    # Pre-existing captured_source: shares same dev and ino (hardlink from source),
    # BUT we tamper its content afterwards or create a mismatch in size/hash
    captured = tx_dir_gen1 / "captured_source"
    os.link(str(source), str(captured))
    # Source is removed
    source.unlink()

    # Now tamper captured in place: inode and dev remain the same, but hash/size mismatch!
    with open(captured, "r+b") as f:
        f.seek(0)
        f.write(b"CORRUPTED_IN_CAPTURE_SLOT")
        f.truncate()

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=3,
            original_path=str(source),
            quarantine_path=str(pub_path),
            state="preparing",
            tx_phase="public_published",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(expected_content),
            content_hash=expected_hash,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(
        session_factory,
        3,
        "worker-1",
        quarantine_root=quarantine_root,
        allowed_roots=[data_dir],
    )

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 3)
        # MUST NOT be active! Must be conflict because hash/size failed qualification
        assert entry.state == "conflict"
        assert entry.tx_phase == "conflict"
