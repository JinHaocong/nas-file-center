from pathlib import Path
import pytest
from sqlalchemy import text
from app.models import TaskLock, QuarantineEntry, utcnow
from app.db import create_engine_and_session, init_db
from app.tasks.state_machine import JobLeaseLost
from app.quarantine.tx_allocator import allocate_next_generation


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal


def test_allocate_next_generation_monotonic(session_factory):
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
            original_path="/data/file.txt",
            quarantine_path="/data/.quarantine/file.txt",
            state="preparing",
            active_attempt_generation=0,
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    gen1, path1 = allocate_next_generation(session_factory, entry_id, "worker-1")
    assert gen1 == 1
    assert path1 == Path("/data/.quarantine/.tx") / f"entry-{entry_id}" / "attempt-1"

    with session_factory() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry.active_attempt_generation == 1

    gen2, path2 = allocate_next_generation(session_factory, entry_id, "worker-1")
    assert gen2 == 2
    assert path2 == Path("/data/.quarantine/.tx") / f"entry-{entry_id}" / "attempt-2"

    with session_factory() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry.active_attempt_generation == 2


def test_stale_worker_cannot_allocate_generation(session_factory):
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
            original_path="/data/file.txt",
            quarantine_path="/data/.quarantine/file.txt",
            state="preparing",
            active_attempt_generation=1,
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    with pytest.raises(JobLeaseLost):
        allocate_next_generation(session_factory, entry_id, "worker-1")

    with session_factory() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry.active_attempt_generation == 1
