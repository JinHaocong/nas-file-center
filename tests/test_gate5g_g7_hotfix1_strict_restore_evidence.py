import pytest
from app.db import create_engine_and_session, init_db

@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal

import hashlib
import os
from pathlib import Path
import pytest
from sqlalchemy import text

from app.models import QuarantineEntry, TaskLock, utcnow
from app.quarantine.reconcile import reconcile_quarantine_transaction
from app.quarantine.restore import execute_transactional_restore


def test_restore_evidence_public_absent_and_capture_absent_fails_closed(tmp_path, session_factory):
    """
    HOTFIX1 Requirement 5:
    If original path is restored, but public quarantine path is absent AND
    captured_quarantine_view slot is absent:
    FAIL CLOSED to conflict. Must NOT become restored.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    orig_path = data_dir / "target.txt"
    payload = b"GENUINE_PAYLOAD"
    orig_path.write_bytes(payload)
    st = os.stat(orig_path)

    # Authoritative anchor intact
    tx_dir = q_dir / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True)
    anchor = tx_dir / "anchor"
    os.link(str(orig_path), str(anchor))

    pub_path = q_dir / "target.txt"
    # Note: neither pub_path nor captured_quarantine_view exists!

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
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(session_factory, 1, "worker-1")

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        # Must fail-closed: MUST NOT become restored!
        assert entry.state == "conflict", f"Expected conflict, got {entry.state}"
        assert entry.tx_phase == "conflict"


def test_restore_evidence_captured_view_expected_becomes_restored(tmp_path, session_factory):
    """
    HOTFIX1 Requirement 5:
    captured_quarantine_view exists and matches expected anchor dev/ino:
    Entry transitions to restored.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    orig_path = data_dir / "target2.txt"
    payload = b"GENUINE_PAYLOAD_2"
    orig_path.write_bytes(payload)
    st = os.stat(orig_path)

    tx_dir = q_dir / ".tx" / "entry-2" / "attempt-1"
    tx_dir.mkdir(parents=True)
    anchor = tx_dir / "anchor"
    os.link(str(orig_path), str(anchor))

    # Captured view slot holds matching inode
    captured_view = tx_dir / "captured_quarantine_view"
    os.link(str(anchor), str(captured_view))

    pub_path = q_dir / "target2.txt"

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=2,
            original_path=str(orig_path),
            quarantine_path=str(pub_path),
            state="restoring",
            tx_phase="restoring",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(session_factory, 2, "worker-1")

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 2)
        assert entry.state == "restored"
        assert entry.tx_phase == "restored"


def test_restore_evidence_captured_view_foreign_enters_conflict(tmp_path, session_factory):
    """
    HOTFIX1 Requirement 5:
    captured_quarantine_view exists but is a foreign file:
    Must enter conflict and preserve foreign view.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    orig_path = data_dir / "target3.txt"
    payload = b"GENUINE_PAYLOAD_3"
    orig_path.write_bytes(payload)
    st = os.stat(orig_path)

    tx_dir = q_dir / ".tx" / "entry-3" / "attempt-1"
    tx_dir.mkdir(parents=True)
    anchor = tx_dir / "anchor"
    os.link(str(orig_path), str(anchor))

    # Foreign file placed in captured view slot
    captured_view = tx_dir / "captured_quarantine_view"
    captured_view.write_bytes(b"FOREIGN_VIEW_DATA")

    pub_path = q_dir / "target3.txt"

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)
        entry = QuarantineEntry(
            id=3,
            original_path=str(orig_path),
            quarantine_path=str(pub_path),
            state="restoring",
            tx_phase="restoring",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(session_factory, 3, "worker-1")

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 3)
        assert entry.state == "conflict"
        assert entry.tx_phase == "conflict"

    # Foreign view preserved
    assert captured_view.exists()
    assert captured_view.read_bytes() == b"FOREIGN_VIEW_DATA"
