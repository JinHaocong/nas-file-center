from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import select, text

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import (
    DuplicateGroup,
    IndexedPath,
    ScanJob,
    TaskEvent,
    TaskLock,
    WorkJob,
    WorkerState,
    utcnow,
)
from app.tasks.context import JobContext
from app.tasks.handlers import FclonesScanHandler, IndexRootHandler
from app.tasks.recovery import (
    WORKER_LEASE_TIMEOUT_SECONDS,
    acquire_worker_ownership,
    claim_next_job,
    recover_interrupted_jobs,
    update_worker_heartbeat,
)
from app.tasks.service import TaskService
from app.tasks.state_machine import JobLeaseLost, JobState, JobTransitionError, TERMINAL_STATES
from app.worker import process_work_job


def test_cancel_between_claim_and_process_start_finishes_cancelled(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_id = "worker-preflight-cancel"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_id)
    service = TaskService(SessionLocal)

    with SessionLocal() as session:
        scan = ScanJob(name="test-preflight-cancel", mode="dry-run", roots_json=json.dumps([str(data_dir)]), status="running")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(kind="fclones-scan", status="queued", state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(data_dir)]}))
        session.add(work)
        session.commit()
        work_id = work.id

    # 1. Claim job
    claimed_id = claim_next_job(engine, SessionLocal, worker_id=worker_id)
    assert claimed_id == work_id

    # 2. Before process_work_job executes, user requests cancel
    service.cancel_task(work_id)

    with SessionLocal() as session:
        w = session.get(WorkJob, work_id)
        assert w.status == JobState.CANCEL_REQUESTED.value

    # 3. Now process_work_job runs
    with patch("app.worker.get_handler") as mock_get_handler:
        mock_handler = MagicMock()
        mock_get_handler.return_value = mock_handler

        # Must not raise JobTransitionError; must return gracefully
        res = process_work_job(settings, work_id, session_factory=SessionLocal, engine=engine, worker_id=worker_id)
        assert res is True
        mock_handler.run.assert_not_called()

    # 4. Final state must be cancelled
    with SessionLocal() as session:
        w = session.get(WorkJob, work_id)
        s = session.get(ScanJob, scan_id)
        assert w.status == JobState.CANCELLED.value, f"Expected cancelled but got {w.status}"
        assert w.finished_at is not None
        assert s.status == "cancelled"


def test_recovery_handles_cancel_that_arrives_after_candidate_snapshot(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_id = "worker-rec-snapshot"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_id)
    service = TaskService(SessionLocal)

    with SessionLocal() as session:
        scan = ScanJob(name="test-rec-snapshot", mode="dry-run", roots_json=json.dumps([str(data_dir)]), status="running")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(kind="fclones-scan", status="running", state_json=json.dumps({"scan_job_id": scan_id}))
        session.add(work)
        session.commit()
        work_id = work.id

    # Hook session.scalars to mutate job status to cancel_requested after snapshot is read
    from sqlalchemy.orm import Session as SASession
    original_scalars = SASession.scalars
    intercepted = False

    def hook_scalars(self, *args, **kwargs):
        nonlocal intercepted
        res = original_scalars(self, *args, **kwargs)
        # If this is reading candidate WorkJob IDs, trigger cancel right after
        if not intercepted:
            intercepted = True
            # Outside this session, transition job to cancel_requested
            with SessionLocal() as s2:
                w2 = s2.get(WorkJob, work_id)
                w2.status = JobState.CANCEL_REQUESTED.value
                w2.cancel_requested_at = utcnow()
                s2.commit()
        return res

    with patch.object(SASession, "scalars", hook_scalars):
        stats = recover_interrupted_jobs(engine, SessionLocal, worker_id=worker_id)

    with SessionLocal() as session:
        w = session.get(WorkJob, work_id)
        s = session.get(ScanJob, scan_id)
        assert w.status == JobState.CANCELLED.value, f"Expected cancelled but got {w.status}"
        assert s.status == "cancelled"
        assert w.finished_at is not None


def test_heartbeat_rechecks_fresh_time_after_writer_lock_wait(tmp_path: Path):
    db_path = tmp_path / "test_hb_lock_wait.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    worker_id = "worker-hb-wait"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_id)

    short_timeout = 0.15
    lock_acquired_event = threading.Event()
    release_lock_event = threading.Event()

    def lock_holder():
        with SessionLocal() as s:
            s.execute(text("BEGIN IMMEDIATE"))
            lock_acquired_event.set()
            release_lock_event.wait(timeout=5.0)
            s.commit()

    t = threading.Thread(target=lock_holder)
    t.start()

    try:
        lock_acquired_event.wait(timeout=5.0)
        # Launch heartbeat while lock is held; it will sample now, then wait for BEGIN IMMEDIATE
        hb_result = []

        def call_hb():
            res = update_worker_heartbeat(engine, SessionLocal, worker_id=worker_id, timeout_seconds=short_timeout)
            hb_result.append(res)

        hb_thread = threading.Thread(target=call_hb)
        hb_thread.start()

        # Hold lock until lease expires (> 0.15s)
        time.sleep(0.20)
        release_lock_event.set()
        hb_thread.join(timeout=5.0)

        assert hb_result == [False], "Heartbeat must return False because lease expired while waiting for lock"
    finally:
        release_lock_event.set()
        t.join(timeout=5.0)


def test_claim_rechecks_fresh_time_after_writer_lock_wait(tmp_path: Path):
    db_path = tmp_path / "test_claim_lock_wait.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    worker_id = "worker-claim-wait"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_id)

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status="queued", state_json="{}")
        session.add(job)
        session.commit()
        job_id = job.id

    short_timeout = 0.15
    lock_acquired_event = threading.Event()
    release_lock_event = threading.Event()

    def lock_holder():
        with SessionLocal() as s:
            s.execute(text("BEGIN IMMEDIATE"))
            lock_acquired_event.set()
            release_lock_event.wait(timeout=5.0)
            s.commit()

    t = threading.Thread(target=lock_holder)
    t.start()

    try:
        lock_acquired_event.wait(timeout=5.0)
        claim_exc = []

        def call_claim():
            try:
                claim_next_job(engine, SessionLocal, worker_id=worker_id, timeout_seconds=short_timeout)
            except Exception as e:
                claim_exc.append(e)

        claim_thread = threading.Thread(target=call_claim)
        claim_thread.start()

        # Hold lock until lease expires (> 0.15s)
        time.sleep(0.20)
        release_lock_event.set()
        claim_thread.join(timeout=5.0)

        assert len(claim_exc) == 1 and isinstance(claim_exc[0], JobLeaseLost), "Claim must raise JobLeaseLost because lease expired while waiting for lock"
    finally:
        release_lock_event.set()
        t.join(timeout=5.0)


def test_checkpoint_uses_post_lock_transaction_time(tmp_path: Path):
    db_path = tmp_path / "test_checkpoint_time.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    worker_id = "worker-cp-time"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_id)

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status="running", state_json="{}")
        session.add(job)
        session.commit()
        job_id = job.id

    ctx = JobContext(engine, SessionLocal, job_id, worker_id=worker_id)

    time_before = utcnow().replace(tzinfo=None)
    ctx.checkpoint(progress_current=5, progress_total=10, progress_message="testing")

    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        assert j.heartbeat_at.replace(tzinfo=None) >= time_before


def test_worker_finalization_uses_post_lock_transaction_time(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_id = "worker-fin-time"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_id)

    with SessionLocal() as session:
        work = WorkJob(kind="index-root", status="running", state_json=json.dumps({"root": str(data_dir)}))
        session.add(work)
        session.commit()
        work_id = work.id

    time_before = utcnow().replace(tzinfo=None)
    res = process_work_job(settings, work_id, session_factory=SessionLocal, engine=engine, worker_id=worker_id)
    assert res is True

    with SessionLocal() as session:
        w = session.get(WorkJob, work_id)
        assert w.status == JobState.COMPLETED.value
        assert w.finished_at.replace(tzinfo=None) >= time_before
