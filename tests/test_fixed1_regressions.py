from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import threading
import time
import pytest
from sqlalchemy import select

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import TaskLock, WorkJob, WorkerState, utcnow
from app.tasks.context import JobContext
from app.tasks.handlers import get_handler, get_job_capabilities
from app.tasks.recovery import (
    acquire_worker_ownership,
    generate_worker_id,
    recover_interrupted_jobs,
    update_worker_heartbeat,
)
from app.tasks.service import TaskService
from app.worker import WorkerHeartbeatThread


@pytest.fixture
def setup_db(tmp_path: Path):
    settings = Settings(config_dir=tmp_path)
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)
    return {"settings": settings, "engine": engine, "SessionLocal": SessionLocal}


def test_unique_worker_id_not_just_pid():
    w1 = generate_worker_id()
    w2 = generate_worker_id()
    assert w1 != w2, "worker_ids generated in same process must be distinct"
    assert str(os.getpid()) in w1
    assert str(os.getpid()) in w2


def test_exclusive_ownership_rejects_fresh_second_worker(setup_db):
    engine = setup_db["engine"]
    SessionLocal = setup_db["SessionLocal"]

    # 1. Worker A acquires ownership
    acquired_a = acquire_worker_ownership(engine, SessionLocal, worker_id="worker-A", timeout_seconds=30.0)
    assert acquired_a is True

    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        assert lock.owner == "worker-A"

    # 2. Worker B attempts to acquire while A's lease is fresh -> MUST FAIL
    acquired_b = acquire_worker_ownership(engine, SessionLocal, worker_id="worker-B", timeout_seconds=30.0)
    assert acquired_b is False, "Worker B should NOT acquire lease when Worker A is fresh"

    # Owner must still be Worker A
    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        assert lock.owner == "worker-A"
        state = session.get(WorkerState, "default")
        assert state.worker_id == "worker-A"


def test_exclusive_ownership_takeover_when_stale(setup_db):
    engine = setup_db["engine"]
    SessionLocal = setup_db["SessionLocal"]

    # Worker A acquires ownership
    acquire_worker_ownership(engine, SessionLocal, worker_id="worker-A", timeout_seconds=30.0)

    # Simulate Worker A heartbeat becoming stale (e.g. 40s ago)
    past = utcnow() - timedelta(seconds=40)
    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        lock.acquired_at = past
        state = session.get(WorkerState, "default")
        state.heartbeat_at = past
        session.commit()

    # Worker B acquires ownership -> MUST SUCCEED because A is stale
    acquired_b = acquire_worker_ownership(engine, SessionLocal, worker_id="worker-B", timeout_seconds=30.0)
    assert acquired_b is True, "Worker B should take over stale lease"

    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        assert lock.owner == "worker-B"
        state = session.get(WorkerState, "default")
        assert state.worker_id == "worker-B"


def test_overlapping_worker_does_not_fail_active_worker_jobs(setup_db):
    engine = setup_db["engine"]
    SessionLocal = setup_db["SessionLocal"]

    # Worker A acquires ownership and runs a job
    acquire_worker_ownership(engine, SessionLocal, worker_id="worker-A", timeout_seconds=30.0)

    with SessionLocal() as session:
        job = WorkJob(
            kind="fclones-scan",
            status="running",
            started_at=utcnow(),
            heartbeat_at=utcnow(),
        )
        session.add(job)
        session.commit()
        job_id = job.id

    # Worker B starts up, fails to acquire lease
    acquired_b = acquire_worker_ownership(engine, SessionLocal, worker_id="worker-B", timeout_seconds=30.0)
    assert acquired_b is False

    # Worker B tries to recover jobs -> MUST NOT recover or fail Worker A's running job!
    stats = recover_interrupted_jobs(engine, SessionLocal, worker_id="worker-B")
    assert stats["failed_interrupted"] == 0
    assert stats["recovered_requeued"] == 0

    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        assert j.status == "running", "Active job of Worker A must NOT be failed by Worker B"


def test_index_root_handler_honest_capabilities():
    caps = get_job_capabilities("index-root")
    assert caps["supports_pause"] is False, "IndexRootHandler does not support pause"
    assert caps["supports_resume"] is False, "IndexRootHandler does not support resume"
    assert caps["supports_cancel"] is False, "IndexRootHandler does not support interruptible cancel"
    assert caps["supports_retry"] is True


from app.tasks.handlers import TaskHandler, register_handler


@register_handler
class NoRetryFixed1Handler(TaskHandler):
    job_type = "no-retry-fixed1"
    supports_cancel = False
    supports_retry = False


def test_task_service_rejects_unsupported_cancel_and_retry(setup_db):
    SessionLocal = setup_db["SessionLocal"]
    srv = TaskService(SessionLocal)

    with SessionLocal() as session:
        # Create a queued index-root job
        job = WorkJob(kind="index-root", status="queued")
        session.add(job)
        session.commit()
        job_id = job.id

    # 1. cancel_task must reject because index-root has supports_cancel=False
    with pytest.raises(ValueError, match="does not support cancel"):
        srv.cancel_task(job_id)

    # 2. retry_task must reject because no-retry-fixed1 has supports_retry=False
    with SessionLocal() as session:
        no_retry_job = WorkJob(kind="no-retry-fixed1", status="failed")
        session.add(no_retry_job)
        session.commit()
        nr_id = no_retry_job.id

    with pytest.raises(ValueError, match="does not support retry"):
        srv.retry_task(nr_id)


def test_checkpoint_size_limit_and_progress_validation(setup_db):
    engine = setup_db["engine"]
    SessionLocal = setup_db["SessionLocal"]

    with SessionLocal() as session:
        job = WorkJob(kind="fclones-scan", status="running")
        session.add(job)
        session.commit()
        job_id = job.id

    ctx = JobContext(engine, SessionLocal, job_id)

    # 1. Negative progress total must be rejected
    with pytest.raises(ValueError, match="non-negative"):
        ctx.checkpoint(progress_total=-1)

    # 2. Negative progress current must be rejected
    with pytest.raises(ValueError, match="non-negative"):
        ctx.checkpoint(progress_current=-5)

    # 3. Oversized checkpoint data (> 64KB) must be rejected
    huge_payload = {"schema_version": 1, "data": "x" * (70 * 1024)}
    with pytest.raises(ValueError, match="exceeds maximum allowed size"):
        ctx.checkpoint(checkpoint_data=huge_payload)


def test_busy_worker_heartbeat_thread_renews_lease(setup_db):
    engine = setup_db["engine"]
    SessionLocal = setup_db["SessionLocal"]

    worker_id = "worker-busy-test"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_id, timeout_seconds=5.0)

    with SessionLocal() as session:
        state_initial = session.get(WorkerState, "default")
        initial_heartbeat = state_initial.heartbeat_at

    stop_event = threading.Event()
    # Heartbeat thread with short 0.05s interval (no 90s sleep)
    thread = WorkerHeartbeatThread(
        engine,
        SessionLocal,
        worker_id=worker_id,
        interval=0.05,
        stop_event=stop_event,
    )
    thread.start()

    try:
        # Simulate busy worker running a job for 0.15s
        time.sleep(0.15)
        with SessionLocal() as session:
            state_updated = session.get(WorkerState, "default")
            lock = session.get(TaskLock, 1)
            assert state_updated.heartbeat_at > initial_heartbeat, "Heartbeat must be updated during busy work"
            assert lock.owner == worker_id
            assert lock.acquired_at > initial_heartbeat, "Lease must be renewed during busy work"
    finally:
        stop_event.set()
        thread.join(timeout=1.0)
