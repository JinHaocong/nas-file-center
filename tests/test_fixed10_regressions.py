from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time
import pytest
from sqlalchemy import select, text

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import ScanJob, TaskEvent, TaskLock, WorkJob, utcnow
from app.tasks.recovery import acquire_worker_ownership, claim_next_job
from app.tasks.service import TaskService
from app.tasks.state_machine import JobState


def test_cancel_uses_post_lock_transaction_time(tmp_path: Path):
    db_path = tmp_path / "test_cancel_lock_time.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    service = TaskService(SessionLocal)

    with SessionLocal() as session:
        scan = ScanJob(name="test-cancel-time", mode="dry-run", roots_json="[]", status="running")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        job = WorkJob(kind="fclones-scan", status=JobState.RUNNING.value, state_json=json.dumps({"scan_job_id": scan_id}))
        session.add(job)
        session.commit()
        job_id = job.id

    lock_acquired_event = threading.Event()
    release_lock_event = threading.Event()
    release_time: list[datetime] = []

    def lock_holder():
        with SessionLocal() as s:
            s.execute(text("BEGIN IMMEDIATE"))
            lock_acquired_event.set()
            release_lock_event.wait(timeout=5.0)
            release_time.append(utcnow())
            s.commit()

    t = threading.Thread(target=lock_holder)
    t.start()

    try:
        assert lock_acquired_event.wait(timeout=5.0)

        cancel_res = []

        def call_cancel():
            res = service.cancel_task(job_id)
            cancel_res.append(res)

        cancel_thread = threading.Thread(target=call_cancel)
        cancel_thread.start()

        # Hold lock for 0.20s so pre-lock now vs post-lock now has significant gap
        time.sleep(0.20)
        release_lock_event.set()
        cancel_thread.join(timeout=5.0)

        assert len(cancel_res) == 1
        assert len(release_time) == 1

        with SessionLocal() as session:
            j = session.get(WorkJob, job_id)
            assert j.status == JobState.CANCEL_REQUESTED.value
            assert j.cancel_requested_at is not None
            # cancel_requested_at must be sampled AFTER acquiring the writer lock
            # Allow at most 10ms of clock jitter
            rel_t = release_time[0].replace(tzinfo=None)
            req_t = j.cancel_requested_at.replace(tzinfo=None)
            assert req_t >= rel_t - timedelta(milliseconds=10), (
                f"cancel_requested_at ({req_t}) was sampled before writer lock acquisition ({rel_t})"
            )
    finally:
        release_lock_event.set()
        t.join(timeout=5.0)


def test_claim_then_waiting_cancel_preserves_timestamp_order(tmp_path: Path):
    db_path = tmp_path / "test_claim_cancel_order.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    service = TaskService(SessionLocal)

    with SessionLocal() as session:
        scan = ScanJob(name="test-claim-order", mode="dry-run", roots_json="[]", status="running")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        job = WorkJob(kind="fclones-scan", status=JobState.QUEUED.value, state_json=json.dumps({"scan_job_id": scan_id}))
        session.add(job)
        session.commit()
        job_id = job.id

    lock_acquired_event = threading.Event()
    cancel_started_event = threading.Event()

    def claim_holder():
        with SessionLocal() as s:
            s.execute(text("BEGIN IMMEDIATE"))
            lock_acquired_event.set()
            # Wait until cancel_task is launched and waiting on writer lock
            cancel_started_event.wait(timeout=5.0)
            time.sleep(0.15)
            # Simulate claim happening inside writer lock
            claimed_job = s.get(WorkJob, job_id)
            claim_now = utcnow()
            claimed_job.status = JobState.RUNNING.value
            claimed_job.started_at = claim_now
            s.commit()

    t = threading.Thread(target=claim_holder)
    t.start()

    try:
        assert lock_acquired_event.wait(timeout=5.0)

        cancel_res = []

        def call_cancel():
            cancel_started_event.set()
            res = service.cancel_task(job_id)
            cancel_res.append(res)

        cancel_thread = threading.Thread(target=call_cancel)
        cancel_thread.start()

        cancel_thread.join(timeout=5.0)
        t.join(timeout=5.0)

        assert len(cancel_res) == 1

        with SessionLocal() as session:
            j = session.get(WorkJob, job_id)
            assert j.status == JobState.CANCEL_REQUESTED.value
            assert j.started_at is not None
            assert j.cancel_requested_at is not None

            started_t = j.started_at.replace(tzinfo=None)
            cancel_t = j.cancel_requested_at.replace(tzinfo=None)

            # Causality guarantee: Cancel happened after Claim obtained writer lock
            # Therefore cancel_requested_at MUST NOT be earlier than started_at!
            assert cancel_t >= started_t, (
                f"Causality inversion: cancel_requested_at ({cancel_t}) < started_at ({started_t})"
            )
    finally:
        cancel_started_event.set()
        t.join(timeout=5.0)


def test_retry_uses_post_lock_transaction_time(tmp_path: Path):
    db_path = tmp_path / "test_retry_lock_time.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    service = TaskService(SessionLocal)

    with SessionLocal() as session:
        job = WorkJob(
            kind="index-root",
            status=JobState.FAILED.value,
            state_json=json.dumps({"root": "/data"}),
            error_code="TEST_FAIL",
            error_text="test failure",
        )
        session.add(job)
        session.commit()
        job_id = job.id

    lock_acquired_event = threading.Event()
    release_lock_event = threading.Event()
    release_time: list[datetime] = []

    def lock_holder():
        with SessionLocal() as s:
            s.execute(text("BEGIN IMMEDIATE"))
            lock_acquired_event.set()
            release_lock_event.wait(timeout=5.0)
            release_time.append(utcnow())
            s.commit()

    t = threading.Thread(target=lock_holder)
    t.start()

    try:
        assert lock_acquired_event.wait(timeout=5.0)

        retry_res = []

        def call_retry():
            res = service.retry_task(job_id)
            retry_res.append(res)

        retry_thread = threading.Thread(target=call_retry)
        retry_thread.start()

        # Hold lock for 0.20s so pre-lock now vs post-lock now has significant gap
        time.sleep(0.20)
        release_lock_event.set()
        retry_thread.join(timeout=5.0)

        assert len(retry_res) == 1
        assert len(release_time) == 1

        new_job_id = retry_res[0]["job"]["id"]
        with SessionLocal() as session:
            new_job = session.get(WorkJob, new_job_id)
            assert new_job.created_at is not None
            rel_t = release_time[0].replace(tzinfo=None)
            created_t = new_job.created_at.replace(tzinfo=None)
            # created_at must be sampled AFTER acquiring the writer lock
            assert created_t >= rel_t - timedelta(milliseconds=10), (
                f"retry job created_at ({created_t}) was sampled before writer lock acquisition ({rel_t})"
            )
    finally:
        release_lock_event.set()
        t.join(timeout=5.0)
