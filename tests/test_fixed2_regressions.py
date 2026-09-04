from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import pytest
from sqlalchemy import select, text

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import DuplicateGroup, ScanJob, TaskLock, WorkJob, WorkerState, utcnow
from app.tasks.handlers import TaskHandler, register_handler
from app.tasks.recovery import (
    acquire_worker_ownership,
    recover_interrupted_jobs,
    update_worker_heartbeat,
)
from app.tasks.service import TaskService
from app.worker import process_work_job


@register_handler
class NoRetryHandler(TaskHandler):
    job_type = "no-retry-test"
    supports_pause = False
    supports_resume = False
    supports_cancel = True
    supports_retry = False


def test_atomic_lease_acquisition_concurrent_stale(tmp_path: Path):
    db_path = tmp_path / "test_lease_stale.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    # Setup a stale lease (40 seconds old)
    stale_time = utcnow() - timedelta(seconds=40)
    with SessionLocal() as session:
        lock = TaskLock(id=1, locked=True, owner="worker-old", acquired_at=stale_time)
        session.add(lock)
        state = WorkerState(
            worker_key="default",
            worker_id="worker-old",
            started_at=stale_time,
            heartbeat_at=stale_time,
            updated_at=stale_time,
        )
        session.add(state)
        session.commit()

    barrier = threading.Barrier(2)
    results = {}

    def try_acquire(w_id: str):
        barrier.wait()
        res = acquire_worker_ownership(engine, SessionLocal, worker_id=w_id, timeout_seconds=30.0)
        results[w_id] = res

    t1 = threading.Thread(target=try_acquire, args=("worker-A",))
    t2 = threading.Thread(target=try_acquire, args=("worker-B",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly ONE worker must succeed, the other MUST fail
    successes = [w for w, ok in results.items() if ok is True]
    assert len(successes) == 1, f"Expected exactly 1 acquire success, got: {results}"

    winner = successes[0]
    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        assert lock.owner == winner
        state = session.get(WorkerState, "default")
        assert state.worker_id == winner


def test_atomic_lease_acquisition_concurrent_initial(tmp_path: Path):
    db_path = tmp_path / "test_lease_init.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    # Initial state: NO task_lock row in DB
    with SessionLocal() as session:
        session.execute(text("DELETE FROM task_lock"))
        session.execute(text("DELETE FROM worker_state"))
        session.commit()

    barrier = threading.Barrier(2)
    results = {}

    def try_acquire(w_id: str):
        barrier.wait()
        res = acquire_worker_ownership(engine, SessionLocal, worker_id=w_id, timeout_seconds=30.0)
        results[w_id] = res

    t1 = threading.Thread(target=try_acquire, args=("worker-1",))
    t2 = threading.Thread(target=try_acquire, args=("worker-2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    successes = [w for w, ok in results.items() if ok is True]
    assert len(successes) == 1, f"Expected exactly 1 acquire success on clean DB, got: {results}"

    winner = successes[0]
    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        assert lock.owner == winner


def test_non_owner_forbidden_from_updating_heartbeat(tmp_path: Path):
    db_path = tmp_path / "test_hb.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    # Worker A acquires ownership
    assert acquire_worker_ownership(engine, SessionLocal, worker_id="worker-A") is True

    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        state = session.get(WorkerState, "default")
        initial_lock_time = lock.acquired_at
        initial_state_time = state.heartbeat_at

    time.sleep(0.05)

    # Worker B attempts to update heartbeat -> MUST return False and NOT modify timestamps
    b_updated = update_worker_heartbeat(engine, SessionLocal, worker_id="worker-B")
    assert b_updated is False, "Non-owner Worker B must return False when attempting heartbeat"

    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        state = session.get(WorkerState, "default")
        assert lock.acquired_at == initial_lock_time, "Lock timestamp must NOT be modified by Worker B"
        assert state.heartbeat_at == initial_state_time, "State heartbeat must NOT be modified by Worker B"
        assert lock.owner == "worker-A"

    # Worker A updates heartbeat -> MUST return True and update timestamps
    a_updated = update_worker_heartbeat(engine, SessionLocal, worker_id="worker-A")
    assert a_updated is True, "Owner Worker A must succeed in updating heartbeat"

    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        state = session.get(WorkerState, "default")
        assert lock.acquired_at > initial_lock_time
        assert state.heartbeat_at > initial_state_time


def test_task_service_rejects_unsupported_retry(tmp_path: Path):
    settings = Settings(config_dir=tmp_path)
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)
    srv = TaskService(SessionLocal)

    with SessionLocal() as session:
        job = WorkJob(kind="no-retry-test", status="failed")
        session.add(job)
        session.commit()
        job_id = job.id

    with pytest.raises(ValueError, match="does not support retry"):
        srv.retry_task(job_id)


def test_fclones_scan_job_started_at_sync(tmp_path: Path):
    settings = Settings(config_dir=tmp_path)
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    with SessionLocal() as session:
        scan = ScanJob(name="test-scan", mode="dry-run", roots_json=json.dumps([str(tmp_path)]), status="queued")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(
            kind="fclones-scan",
            status="queued",
            state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(tmp_path)]}),
        )
        session.add(work)
        session.commit()
        work_id = work.id

    from unittest.mock import patch

    with patch("app.worker.get_handler") as mock_get:
        class DummyHandler:
            def run(self, j, ctx, st):
                pass
        mock_get.return_value = DummyHandler()

        process_work_job(settings, work_id, session_factory=SessionLocal, engine=engine)

    with SessionLocal() as session:
        w = session.get(WorkJob, work_id)
        s = session.get(ScanJob, scan_id)
        assert w.status == "completed"
        assert s.status == "completed"
        assert s.started_at is not None, "ScanJob.started_at must be populated when WorkJob starts"
        assert s.finished_at is not None


def test_fclones_cancel_syncs_scan_job_queued(tmp_path: Path):
    settings = Settings(config_dir=tmp_path)
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)
    srv = TaskService(SessionLocal)

    with SessionLocal() as session:
        scan = ScanJob(name="test-scan-cancel-queued", mode="dry-run", roots_json=json.dumps([str(tmp_path)]), status="queued")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(
            kind="fclones-scan",
            status="queued",
            state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(tmp_path)]}),
        )
        session.add(work)
        session.commit()
        work_id = work.id

    # Cancel the queued fclones scan task
    srv.cancel_task(work_id)

    with SessionLocal() as session:
        w = session.get(WorkJob, work_id)
        s = session.get(ScanJob, scan_id)
        assert w.status == "cancelled"
        assert s.status == "cancelled"
        assert s.finished_at is not None
        assert s.error_text == "Cancelled by user"


def test_fclones_cancel_e2e_subprocess(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Create fake fclones script that sleeps
    fake_fclones = tmp_path / "fake_fclones.sh"
    fake_fclones.write_text("#!/bin/sh\nsleep 10\n")
    fake_fclones.chmod(0o755)

    settings = Settings(
        config_dir=tmp_path,
        allowed_roots_raw=str(data_dir),
        fclones_binary=str(fake_fclones),
    )
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)
    srv = TaskService(SessionLocal)

    acquire_worker_ownership(engine, SessionLocal, worker_id="worker-test")

    with SessionLocal() as session:
        scan = ScanJob(name="test-e2e-cancel", mode="dry-run", roots_json=json.dumps([str(data_dir)]), status="queued")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(
            kind="fclones-scan",
            status="queued",
            state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(data_dir)]}),
        )
        session.add(work)
        session.commit()
        work_id = work.id

    worker_thread = threading.Thread(
        target=process_work_job,
        args=(settings, work_id),
        kwargs={"session_factory": SessionLocal, "engine": engine},
    )
    worker_thread.start()

    # Wait for job to start running
    for _ in range(50):
        time.sleep(0.1)
        with SessionLocal() as session:
            w = session.get(WorkJob, work_id)
            s = session.get(ScanJob, scan_id)
            if w.status == "running" and s.status == "running":
                assert s.started_at is not None
                break
    else:
        pytest.fail("WorkJob and ScanJob did not transition to running in time")

    # Cancel via TaskService
    srv.cancel_task(work_id)

    # Worker thread should gracefully catch cancel at checkpoint and terminate
    worker_thread.join(timeout=5.0)
    assert not worker_thread.is_alive(), "Worker thread should terminate cleanly upon cancel"

    with SessionLocal() as session:
        w = session.get(WorkJob, work_id)
        s = session.get(ScanJob, scan_id)
        assert w.status == "cancelled"
        assert s.status == "cancelled"
        assert s.finished_at is not None
        assert s.error_text == "Cancelled by user"
