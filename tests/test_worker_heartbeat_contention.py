"""Worker heartbeat lock contention is observable and does not weaken lease fencing."""
from __future__ import annotations

from datetime import timedelta
import logging
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

from app.db import create_engine_and_session, init_db
from app.models import TaskLock, utcnow
from app.tasks.recovery import (
    WorkerHeartbeatDatabaseBusy,
    acquire_worker_ownership,
    update_worker_heartbeat,
)
from app.worker import WorkerHeartbeatThread


@pytest.fixture
def lease_db(tmp_path: Path):
    database = tmp_path / "worker-heartbeat.db"
    engine, factory = create_engine_and_session(database)
    init_db(engine, db_path=database)
    assert acquire_worker_ownership(engine, factory, worker_id="owner-1")
    yield engine, factory
    engine.dispose()


def test_database_busy_is_distinct_from_lost_lease(lease_db):
    engine, factory = lease_db
    # BEGIN IMMEDIATE writer contention on a second connection. Make the test
    # bounded by a 100ms SQLite busy timeout; no 5-second CI sleeps.
    with factory() as holder:
        holder.execute(text("BEGIN IMMEDIATE"))

        def fast_heartbeat_factory():
            session = factory()
            session.execute(text("PRAGMA busy_timeout=100"))
            return session

        with pytest.raises(WorkerHeartbeatDatabaseBusy, match="SQLite writer lock"):
            update_worker_heartbeat(
                engine, fast_heartbeat_factory,
                worker_id="owner-1", raise_on_busy=True,
            )
        holder.rollback()

    assert update_worker_heartbeat(
        engine, factory, worker_id="owner-1", raise_on_busy=True
    ) is True
    with factory() as session:
        assert session.get(TaskLock, 1).owner == "owner-1"


def test_old_callers_keep_false_on_database_busy():
    class LockedSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _query):
            raise SQLAlchemyOperationalError(
                "BEGIN IMMEDIATE", {},
                sqlite3.OperationalError("database is locked"),
            )

    assert update_worker_heartbeat(None, LockedSession, "owner-1") is False
    with pytest.raises(WorkerHeartbeatDatabaseBusy):
        update_worker_heartbeat(None, LockedSession, "owner-1", raise_on_busy=True)


def test_contention_retry_does_not_signal_lease_loss(monkeypatch, caplog):
    from app import worker

    stop = threading.Event()
    lost = threading.Event()
    counters = {"calls": 0}

    def fake_update(_engine, _factory, *, worker_id, raise_on_busy=False):
        assert worker_id == "owner-1"
        assert raise_on_busy is True
        counters["calls"] += 1
        if counters["calls"] <= 2:
            raise WorkerHeartbeatDatabaseBusy("simulated SQLITE_BUSY")
        stop.set()
        return True

    monkeypatch.setattr(worker, "update_worker_heartbeat", fake_update)
    heart = WorkerHeartbeatThread(None, None, "owner-1",
                                  interval=0.12, stop_event=stop, lease_lost_event=lost)
    with caplog.at_level(logging.WARNING):
        heart.start()
        heart.join(timeout=2.0)
    assert not heart.is_alive()
    assert counters["calls"] == 3
    assert lost.is_set() is False


def test_definitive_lease_denial_still_sets_fence(monkeypatch):
    from app import worker
    stop = threading.Event()
    lost = threading.Event()

    def fake_rejection(_engine, _factory, *, worker_id, raise_on_busy=False):
        assert raise_on_busy
        stop.set()
        return False

    monkeypatch.setattr(worker, "update_worker_heartbeat", fake_rejection)
    heart = WorkerHeartbeatThread(None, None, "owner-1",
                                  interval=0.02, stop_event=stop, lease_lost_event=lost)
    heart.start()
    heart.join(timeout=2.0)
    assert lost.is_set()


def test_expired_worker_still_cannot_renew_even_with_retry_mode(lease_db):
    engine, factory = lease_db
    with factory() as session:
        lock = session.get(TaskLock, 1)
        lock.acquired_at = utcnow() - timedelta(seconds=45)
        session.commit()

    assert update_worker_heartbeat(
        engine, factory, worker_id="owner-1",
        raise_on_busy=True, timeout_seconds=30.0,
    ) is False
    assert acquire_worker_ownership(engine, factory, worker_id="owner-2") is True
    assert update_worker_heartbeat(
        engine, factory, worker_id="owner-1",
        raise_on_busy=True,
    ) is False
    with factory() as session:
        assert session.get(TaskLock, 1).owner == "owner-2"
