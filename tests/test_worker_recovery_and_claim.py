from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
import threading
import time
import pytest
from sqlalchemy import select

from app.db import create_engine_and_session, init_db
from app.models import WorkJob, WorkerState, TaskLock, TaskEvent, utcnow
from app.tasks.recovery import (
    acquire_worker_ownership,
    recover_interrupted_jobs,
    claim_next_job,
    compute_worker_status,
    WORKER_ONLINE_THRESHOLD_SECONDS,
    WORKER_STALE_THRESHOLD_SECONDS,
)
from app.tasks.state_machine import JobState


def test_worker_status_computation():
    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Online (age <= 30s)
    hb_online = now - timedelta(seconds=10)
    status, age = compute_worker_status(hb_online, current_time=now)
    assert status == "online"
    assert age == pytest.approx(10.0, rel=0.1)

    # 2. Stale (30s < age <= 90s)
    hb_stale = now - timedelta(seconds=45)
    status, age = compute_worker_status(hb_stale, current_time=now)
    assert status == "stale"
    assert age == pytest.approx(45.0, rel=0.1)

    # 3. Offline (age > 90s or None)
    hb_offline = now - timedelta(seconds=120)
    status, age = compute_worker_status(hb_offline, current_time=now)
    assert status == "offline"
    assert age == pytest.approx(120.0, rel=0.1)

    status_none, age_none = compute_worker_status(None, current_time=now)
    assert status_none == "offline"
    assert age_none is None


from app.tasks.handlers import TaskHandler, register_handler


@register_handler
class ResumableRecoveryHandler(TaskHandler):
    job_type = "resumable-recovery-test"
    supports_resume = True


def test_double_claim_protection(tmp_path: Path):
    db_path = tmp_path / "test_claim.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    acquire_worker_ownership(engine, SessionLocal, worker_id="worker-1")

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status=JobState.QUEUED.value)
        session.add(job)
        session.commit()
        job_id = job.id

    results = []

    def try_claim(worker_name: str):
        claimed_id = claim_next_job(engine, SessionLocal, worker_id=worker_name)
        if claimed_id is not None:
            results.append((worker_name, claimed_id))

    # Two concurrent threads of worker-1 attempting to claim the single queued job
    t1 = threading.Thread(target=try_claim, args=("worker-1",))
    t2 = threading.Thread(target=try_claim, args=("worker-1",))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one thread must have succeeded
    assert len(results) == 1
    winner_worker, claimed_id = results[0]
    assert claimed_id == job_id

    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        assert j.status == JobState.RUNNING.value


def test_worker_restart_recovery_rules(tmp_path: Path):
    db_path = tmp_path / "test_recovery.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    with SessionLocal() as session:
        # 1. Resumable running job with checkpoint -> should be requeued
        j_resumable = WorkJob(
            kind="resumable-recovery-test",
            status=JobState.RUNNING.value,
            checkpoint_json='{"schema_version": 1, "cursor": 10}',
        )
        # 2. Non-resumable running job -> should be failed with WORKER_INTERRUPTED
        j_non_resumable = WorkJob(
            kind="fclones-scan",
            status=JobState.RUNNING.value,
            state_json='{"roots": ["/test"]}',
        )
        # 3. Cancel requested running job -> should be cancelled
        j_cancel_req = WorkJob(
            kind="index-root",
            status=JobState.CANCEL_REQUESTED.value,
            cancel_requested_at=utcnow(),
        )
        # 4. Paused job -> should remain paused
        j_paused = WorkJob(
            kind="index-root",
            status=JobState.PAUSED.value,
            checkpoint_json='{"schema_version": 1}',
        )
        # 5. Queued job -> should remain queued
        j_queued = WorkJob(
            kind="index-root",
            status=JobState.QUEUED.value,
        )
        # 6. Completed job -> should remain completed
        j_completed = WorkJob(
            kind="index-root",
            status=JobState.COMPLETED.value,
        )

        session.add_all([j_resumable, j_non_resumable, j_cancel_req, j_paused, j_queued, j_completed])
        session.commit()
        ids = {
            "resumable": j_resumable.id,
            "non_resumable": j_non_resumable.id,
            "cancel_req": j_cancel_req.id,
            "paused": j_paused.id,
            "queued": j_queued.id,
            "completed": j_completed.id,
        }

    # Worker acquires exclusive ownership before recovery
    assert acquire_worker_ownership(engine, SessionLocal, worker_id="worker-test") is True

    # Run recovery
    stats = recover_interrupted_jobs(engine, SessionLocal, worker_id="worker-test")
    assert stats["recovered_requeued"] == 1
    assert stats["failed_interrupted"] == 1
    assert stats["cancelled"] == 1

    with SessionLocal() as session:
        resumable = session.get(WorkJob, ids["resumable"])
        assert resumable.status == JobState.QUEUED.value

        non_resumable = session.get(WorkJob, ids["non_resumable"])
        assert non_resumable.status == JobState.FAILED.value
        assert non_resumable.error_code == "WORKER_INTERRUPTED"
        assert non_resumable.finished_at is not None

        cancel_req = session.get(WorkJob, ids["cancel_req"])
        assert cancel_req.status == JobState.CANCELLED.value
        assert cancel_req.finished_at is not None

        paused = session.get(WorkJob, ids["paused"])
        assert paused.status == JobState.PAUSED.value

        queued = session.get(WorkJob, ids["queued"])
        assert queued.status == JobState.QUEUED.value

        completed = session.get(WorkJob, ids["completed"])
        assert completed.status == JobState.COMPLETED.value
