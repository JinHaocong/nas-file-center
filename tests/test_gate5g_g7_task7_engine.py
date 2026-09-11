import hashlib
import os
from pathlib import Path
import pytest
from sqlalchemy import text
from app.models import TaskLock, QuarantineEntry, utcnow
from app.db import create_engine_and_session, init_db
from app.tasks.state_machine import JobLeaseLost
from app.quarantine.engine import execute_transactional_quarantine


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal


def test_transactional_quarantine_success(tmp_path, session_factory):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    source = data_dir / "file.txt"
    content = b"CRITICAL_USER_PAYLOAD"
    source.write_bytes(content)
    st = os.stat(source)
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    h = hashlib.sha256(content).hexdigest()

    public_target = q_dir / "file.txt"

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
            original_path=str(source),
            quarantine_path=str(public_target),
            state="preparing",
            size=len(content),
            content_hash=h,
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=mtime_ns,
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    execute_transactional_quarantine(session_factory, entry_id, "worker-1", [tmp_path])

    with session_factory() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry.tx_phase == "active"
        assert entry.state == "active"
        assert entry.authoritative_anchor_path is not None
        anchor_path = Path(entry.authoritative_anchor_path)
        assert anchor_path.exists()
        assert anchor_path.read_bytes() == content

    assert not source.exists(), "Source path must be retired"
    assert public_target.exists(), "Public view must exist"
    assert public_target.read_bytes() == content
    assert public_target.stat().st_ino == st.st_ino


def test_transactional_quarantine_qualification_mismatch_enters_conflict(tmp_path, session_factory):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    source = data_dir / "file.txt"
    source.write_bytes(b"DATA_INITIAL")
    st = os.stat(source)
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))

    public_target = q_dir / "file.txt"

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
            original_path=str(source),
            quarantine_path=str(public_target),
            state="preparing",
            size=len(b"DATA_INITIAL"),
            content_hash="mismatched_sha256_hash",
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=mtime_ns,
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    with pytest.raises(RuntimeError):
        execute_transactional_quarantine(session_factory, entry_id, "worker-1", [tmp_path])

    with session_factory() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry.tx_phase == "conflict"
        assert entry.state == "conflict"

    assert source.exists(), "Source must be preserved on qualification conflict"
    assert not public_target.exists(), "Public view must not be published on conflict"


def test_transactional_quarantine_stale_worker_fenced(tmp_path, session_factory):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    q_dir = tmp_path / "quarantine"
    q_dir.mkdir()

    source = data_dir / "file.txt"
    source.write_bytes(b"DATA")
    st = os.stat(source)
    public_target = q_dir / "file.txt"

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = "worker-2"
        lock.acquired_at = utcnow()

        entry = QuarantineEntry(
            original_path=str(source),
            quarantine_path=str(public_target),
            state="preparing",
            size=4,
            content_hash="dummy",
            device=st.st_dev,
            inode=st.st_ino,
            mtime_ns=0,
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    with pytest.raises(JobLeaseLost):
        execute_transactional_quarantine(session_factory, entry_id, "worker-1", [tmp_path])
