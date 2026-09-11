import hashlib
import os
from pathlib import Path
import pytest
from sqlalchemy import text
from app.models import TaskLock, QuarantineEntry, utcnow
from app.db import create_engine_and_session, init_db
from app.quarantine.restore import execute_transactional_restore


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal


def test_restore_success_terminal_condition(tmp_path, session_factory):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()
    tx_dir = q_dir / ".tx" / "entry-1" / "attempt-1"
    tx_dir.mkdir(parents=True)

    content = b"ORIGINAL_RESTORE_DATA"
    anchor = tx_dir / "anchor"
    anchor.write_bytes(content)
    st = os.stat(anchor)

    orig_path = data_dir / "file.txt"
    public_view = q_dir / "file.txt"
    os.link(str(anchor), str(public_view))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = "worker-1"
        lock.acquired_at = utcnow()

        entry = QuarantineEntry(
            id=1,
            original_path=str(orig_path),
            quarantine_path=str(public_view),
            state="active",
            tx_phase="active",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        session.add(entry)
        session.commit()

    execute_transactional_restore(session_factory, 1, "worker-1", [tmp_path])

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry.state == "restored"
        assert entry.tx_phase == "restored"
        assert entry.restored_at is not None

    assert orig_path.exists()
    assert orig_path.read_bytes() == content
    assert orig_path.stat().st_ino == st.st_ino
    assert not public_view.exists(), "Public view must be retired"
    assert anchor.exists(), "Authoritative anchor must remain intact"
    assert (tx_dir / "captured_quarantine_view").exists()


def test_restore_enters_conflict_if_captured_view_is_foreign(tmp_path, session_factory):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()
    tx_dir = q_dir / ".tx" / "entry-2" / "attempt-1"
    tx_dir.mkdir(parents=True)

    content = b"GENUINE_ANCHOR"
    anchor = tx_dir / "anchor"
    anchor.write_bytes(content)
    st = os.stat(anchor)

    orig_path = data_dir / "file2.txt"
    public_view = q_dir / "file2.txt"
    # Create foreign file at public_view (different inode)
    public_view.write_bytes(b"FOREIGN_VIEW_DATA")

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = "worker-1"
        lock.acquired_at = utcnow()

        entry = QuarantineEntry(
            id=2,
            original_path=str(orig_path),
            quarantine_path=str(public_view),
            state="active",
            tx_phase="active",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        session.add(entry)
        session.commit()

    with pytest.raises(RuntimeError):
        execute_transactional_restore(session_factory, 2, "worker-1", [tmp_path])

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 2)
        assert entry.state == "conflict"
        assert entry.tx_phase == "conflict"

    # Foreign occupant must be preserved in captured_quarantine_view slot (zero unlink)
    captured_view = tx_dir / "captured_quarantine_view"
    assert captured_view.exists()
    assert captured_view.read_bytes() == b"FOREIGN_VIEW_DATA"
    assert anchor.exists()


def test_restore_does_not_mark_restored_before_view_retirement(tmp_path, session_factory, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()
    tx_dir = q_dir / ".tx" / "entry-3" / "attempt-1"
    tx_dir.mkdir(parents=True)

    content = b"GENUINE_DATA"
    anchor = tx_dir / "anchor"
    anchor.write_bytes(content)
    st = os.stat(anchor)

    orig_path = data_dir / "file3.txt"
    public_view = q_dir / "file3.txt"
    os.link(str(anchor), str(public_view))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = "worker-1"
        lock.acquired_at = utcnow()

        entry = QuarantineEntry(
            id=3,
            original_path=str(orig_path),
            quarantine_path=str(public_view),
            state="active",
            tx_phase="active",
            authoritative_anchor_path=str(anchor),
            active_attempt_generation=1,
            device=st.st_dev,
            inode=st.st_ino,
            size=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        session.add(entry)
        session.commit()

    # Simulate failure during Phase 2 (retirement rename)
    real_rename = os.rename
    def failing_rename(src, dst, *args, **kwargs):
        if "captured_quarantine_view" in str(dst):
            raise OSError("Simulated crash during view retirement")
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", failing_rename)

    with pytest.raises(OSError, match="Simulated crash during view retirement"):
        execute_transactional_restore(session_factory, 3, "worker-1", [tmp_path])

    with session_factory() as session:
        entry = session.get(QuarantineEntry, 3)
        # Must remain in restoring phase, NOT restored
        assert entry.state == "restoring"
        assert entry.tx_phase == "restoring"
        assert entry.restored_at is None

    # Destination link is created, but public view was not retired
    assert orig_path.exists()
    assert public_view.exists()

