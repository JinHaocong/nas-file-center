from __future__ import annotations

import json
from pathlib import Path
import pytest
from sqlalchemy import select

from app.db import create_engine_and_session, init_db
from app.models import WorkJob, TaskEvent, utcnow
from app.tasks.state_machine import JobState, JobPauseRequested, JobCancelRequested
from app.tasks.context import JobContext


def test_checkpoint_progress_and_heartbeat(tmp_path: Path):
    db_path = tmp_path / "test_cp.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    with SessionLocal() as session:
        job = WorkJob(kind="test-job", status=JobState.RUNNING.value)
        session.add(job)
        session.commit()
        job_id = job.id

    ctx = JobContext(engine, SessionLocal, job_id)
    ctx.checkpoint(
        progress_current=5,
        progress_total=10,
        progress_message="Halfway done",
        checkpoint_data={"schema_version": 1, "phase": "step1", "cursor": 5},
    )

    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        assert j is not None
        assert j.status == JobState.RUNNING.value
        assert j.progress_current == 5
        assert j.progress_total == 10
        assert j.progress_message == "Halfway done"
        assert j.heartbeat_at is not None
        cp = json.loads(j.checkpoint_json)
        assert cp["phase"] == "step1"
        assert cp["cursor"] == 5


def test_checkpoint_pause_detection(tmp_path: Path):
    db_path = tmp_path / "test_cp_pause.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    with SessionLocal() as session:
        job = WorkJob(
            kind="test-job",
            status=JobState.RUNNING.value,
            pause_requested_at=utcnow(),
        )
        session.add(job)
        session.commit()
        job_id = job.id

    ctx = JobContext(engine, SessionLocal, job_id)
    with pytest.raises(JobPauseRequested):
        ctx.checkpoint(
            progress_current=3,
            progress_total=10,
            progress_message="Pausing here",
            checkpoint_data={"schema_version": 1, "cursor": 3},
        )

    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        assert j.status == JobState.PAUSED.value
        assert j.finished_at is None
        cp = json.loads(j.checkpoint_json)
        assert cp["cursor"] == 3

        # Check paused event recorded
        events = list(session.scalars(select(TaskEvent).where(TaskEvent.job_id == job_id)))
        assert any(e.event_type == "paused" for e in events)


def test_checkpoint_cancel_detection(tmp_path: Path):
    db_path = tmp_path / "test_cp_cancel.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    with SessionLocal() as session:
        job = WorkJob(
            kind="test-job",
            status=JobState.RUNNING.value,
            cancel_requested_at=utcnow(),
        )
        session.add(job)
        session.commit()
        job_id = job.id

    ctx = JobContext(engine, SessionLocal, job_id)
    with pytest.raises(JobCancelRequested):
        ctx.checkpoint(
            progress_current=3,
            progress_total=10,
        )

    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        assert j.status == JobState.CANCELLED.value
        assert j.finished_at is not None

        # Check cancelled event recorded
        events = list(session.scalars(select(TaskEvent).where(TaskEvent.job_id == job_id)))
        assert any(e.event_type == "cancelled" for e in events)


def test_checkpoint_invalid_schema_rejected(tmp_path: Path):
    db_path = tmp_path / "test_cp_invalid.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    with SessionLocal() as session:
        job = WorkJob(kind="test-job", status=JobState.RUNNING.value)
        session.add(job)
        session.commit()
        job_id = job.id

    ctx = JobContext(engine, SessionLocal, job_id)
    # Checkpoint must be a dict with schema_version
    with pytest.raises(ValueError):
        ctx.checkpoint(checkpoint_data="invalid string")

    with pytest.raises(ValueError):
        ctx.checkpoint(checkpoint_data={"cursor": 1})  # missing schema_version
