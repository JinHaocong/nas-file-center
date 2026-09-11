import hashlib
import os
from pathlib import Path
import pytest
from sqlalchemy import text
from app.models import TaskLock, QuarantineEntry, BatchPlanItem, utcnow
from app.db import create_engine_and_session, init_db
from app.quarantine.reconcile import reconcile_quarantine_transaction


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal


def test_reconcile_preparing_with_candidate_anchor_mismatch_enters_conflict(tmp_path, session_factory):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()
    tx_dir = q_dir / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True)

    orig_path = data_dir / "file.txt"
    orig_path.write_bytes(b"ORIGINAL_DATA")
    st_orig = os.stat(orig_path)

    # Candidate anchor with corrupted / mismatched data
    candidate_anchor = tx_dir / "anchor"
    candidate_anchor.write_bytes(b"CORRUPTED_CANDIDATE")
    st_candidate = os.stat(candidate_anchor)

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)

        entry = QuarantineEntry(
            id=1,
            original_path=str(orig_path),
            quarantine_path=str(q_dir / "file.txt"),
            state="preparing",
            tx_phase="preparing",
            active_attempt_generation=1,
            device=st_orig.st_dev,
            inode=st_orig.st_ino,
            size=len(b"ORIGINAL_DATA"),
            mtime_ns=st_orig.st_mtime_ns,
            content_hash=hashlib.sha256(b"ORIGINAL_DATA").hexdigest(),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(session_factory, 1, "worker-1")

    with session_factory() as session:
        e = session.get(QuarantineEntry, 1)
        assert e.state == "conflict"
        assert e.tx_phase == "conflict"
        assert "qualification failed" in (e.last_error or "").lower()

    # Candidate preserved in place, zero unlink
    assert candidate_anchor.exists()
    assert candidate_anchor.read_bytes() == b"CORRUPTED_CANDIDATE"


def test_reconcile_restoring_original_present_view_foreign_enters_conflict(tmp_path, session_factory):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()
    tx_dir = q_dir / ".tx" / "entry-2" / "attempt-1"
    tx_dir.mkdir(parents=True)

    content = b"GENUINE_DATA"
    anchor = tx_dir / "anchor"
    anchor.write_bytes(content)
    st_anchor = os.stat(anchor)

    orig_path = data_dir / "file2.txt"
    # Original destination is already linked/restored to anchor
    os.link(str(anchor), str(orig_path))

    # Public view is occupied by foreign file
    public_view = q_dir / "file2.txt"
    public_view.write_bytes(b"FOREIGN_VIEW_DATA")

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)

        entry = QuarantineEntry(
            id=2,
            original_path=str(orig_path),
            quarantine_path=str(public_view),
            state="restoring",
            tx_phase="restoring",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st_anchor.st_dev,
            inode=st_anchor.st_ino,
            size=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(session_factory, 2, "worker-1")

    with session_factory() as session:
        e = session.get(QuarantineEntry, 2)
        assert e.state == "conflict"
        assert e.tx_phase == "conflict"

    # Foreign occupant must be preserved in captured_quarantine_view slot
    captured_view = q_dir / ".tx" / "entry-2" / f"attempt-{e.active_attempt_generation}" / "captured_quarantine_view"
    assert captured_view.exists()
    assert captured_view.read_bytes() == b"FOREIGN_VIEW_DATA"
    assert anchor.exists()


def test_reconcile_variant2_candidate_anchor_match_advances_to_active(tmp_path, session_factory):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()
    tx_dir = q_dir / ".tx" / "entry-3" / "attempt-1"
    tx_dir.mkdir(parents=True)

    content = b"GENUINE_FILE_CONTENT"
    orig_path = data_dir / "file3.txt"
    orig_path.write_bytes(content)

    # Hardlink candidate anchor directly from source
    candidate_anchor = tx_dir / "anchor"
    os.link(str(orig_path), str(candidate_anchor))
    st = os.stat(candidate_anchor)

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)

        entry = QuarantineEntry(
            id=3,
            original_path=str(orig_path),
            quarantine_path=str(q_dir / "file3.txt"),
            state="preparing",
            tx_phase="preparing",
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(content),
            mtime_ns=st.st_mtime_ns,
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(session_factory, 3, "worker-1")

    with session_factory() as session:
        e = session.get(QuarantineEntry, 3)
        assert e.state == "active"
        assert e.tx_phase == "active"
        assert e.authoritative_anchor_path == str(candidate_anchor)

    assert not orig_path.exists()
    assert (tx_dir / "captured_source").exists()
    assert (q_dir / "file3.txt").exists()


def test_reconcile_variant6_public_path_foreign_enters_conflict(tmp_path, session_factory):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()
    tx_dir = q_dir / ".tx" / "entry-4" / "attempt-1"
    tx_dir.mkdir(parents=True)

    content = b"ANCHOR_CONTENT"
    anchor = tx_dir / "anchor"
    anchor.write_bytes(content)
    st = os.stat(anchor)

    # Public path is occupied by foreign file
    pub_path = q_dir / "file4.txt"
    pub_path.write_bytes(b"FOREIGN_PUB")

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)

        entry = QuarantineEntry(
            id=4,
            original_path=str(data_dir / "file4.txt"),
            quarantine_path=str(pub_path),
            state="preparing",
            tx_phase="authoritative_anchored",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(session_factory, 4, "worker-1")

    with session_factory() as session:
        e = session.get(QuarantineEntry, 4)
        assert e.state == "conflict"
        assert e.tx_phase == "conflict"

    # Foreign occupant must be untouched
    assert pub_path.read_bytes() == b"FOREIGN_PUB"


def test_reconcile_variant8_captured_source_lag_advances_to_active(tmp_path, session_factory):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()
    tx_dir = q_dir / ".tx" / "entry-5" / "attempt-1"
    tx_dir.mkdir(parents=True)

    content = b"GENUINE_PAYLOAD"
    anchor = tx_dir / "anchor"
    anchor.write_bytes(content)
    st = os.stat(anchor)

    pub_path = q_dir / "file5.txt"
    os.link(str(anchor), str(pub_path))

    # Captured source rename already succeeded on disk (same dev/ino), but DB lagged in public_published
    captured_source = tx_dir / "captured_source"
    os.link(str(anchor), str(captured_source))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)

        entry = QuarantineEntry(
            id=5,
            original_path=str(data_dir / "file5.txt"),
            quarantine_path=str(pub_path),
            state="preparing",
            tx_phase="public_published",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(session_factory, 5, "worker-1")

    with session_factory() as session:
        e = session.get(QuarantineEntry, 5)
        assert e.state == "active"
        assert e.tx_phase == "active"


def test_reconcile_variant12_restore_dest_foreign_enters_conflict(tmp_path, session_factory):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()
    tx_dir = q_dir / ".tx" / "entry-6" / "attempt-1"
    tx_dir.mkdir(parents=True)

    content = b"GENUINE_DATA"
    anchor = tx_dir / "anchor"
    anchor.write_bytes(content)
    st_anchor = os.stat(anchor)

    orig_path = data_dir / "file6.txt"
    # Destination is occupied by foreign file
    orig_path.write_bytes(b"FOREIGN_ORIG_DATA")

    public_view = q_dir / "file6.txt"
    os.link(str(anchor), str(public_view))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow())
        session.add(lock)

        entry = QuarantineEntry(
            id=6,
            original_path=str(orig_path),
            quarantine_path=str(public_view),
            state="restoring",
            tx_phase="restoring",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st_anchor.st_dev,
            inode=st_anchor.st_ino,
            size=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        session.add(entry)
        session.commit()

    reconcile_quarantine_transaction(session_factory, 6, "worker-1")

    with session_factory() as session:
        e = session.get(QuarantineEntry, 6)
        assert e.state == "conflict"
        assert e.tx_phase == "conflict"

    # Foreign occupant must be untouched
    assert orig_path.read_bytes() == b"FOREIGN_ORIG_DATA"

