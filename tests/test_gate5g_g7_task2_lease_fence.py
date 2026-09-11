import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from app.models import TaskLock, QuarantineEntry, utcnow
from app.db import create_engine_and_session, init_db
from app.tasks.state_machine import JobLeaseLost
from app.tasks.recovery import renew_and_assert_worker_lease, assert_active_worker_lease


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine)
    return SessionLocal


def test_pattern_a_lease_fence_renewal_visible_across_sessions(session_factory):
    old_time = utcnow() - timedelta(seconds=10)
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = "worker-1"
        lock.acquired_at = old_time
        session.commit()

    renew_and_assert_worker_lease(session_factory, "worker-1")

    with session_factory() as session:
        lock = session.get(TaskLock, 1)
        lock_time = lock.acquired_at if lock.acquired_at.tzinfo is not None else lock.acquired_at.replace(tzinfo=timezone.utc)
        old_time_utc = old_time if old_time.tzinfo is not None else old_time.replace(tzinfo=timezone.utc)
        assert lock_time > old_time_utc
        # Verify another session can immediately write (no lingering transaction)
        session.execute(text("BEGIN IMMEDIATE"))
        session.commit()


def test_lease_fence_null_acquired_at_raises_job_lease_lost(session_factory):
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = "worker-1"
        lock.acquired_at = None
        session.commit()

    with pytest.raises(JobLeaseLost) as exc_info:
        renew_and_assert_worker_lease(session_factory, "worker-1")
    assert "missing acquired_at" in str(exc_info.value)


def test_pattern_b_stale_worker_cannot_commit_db_transition(session_factory):
    # Lock is owned by worker-2
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = "worker-2"
        lock.acquired_at = utcnow()
        session.commit()

    # Worker-1 attempts a DB state transition under Pattern B
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        with pytest.raises(JobLeaseLost):
            assert_active_worker_lease(session, "worker-1")
            # If assertion fails, the mutation is not executed
            entry = QuarantineEntry(
                original_path="/vol/f.txt",
                quarantine_path="/vol/.q/f.txt",
                state="active",
                tx_phase="active",
            )
            session.add(entry)
            session.commit()
        session.rollback()

    with session_factory() as session:
        count = session.query(QuarantineEntry).count()
        assert count == 0
