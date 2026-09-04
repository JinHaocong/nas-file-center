from __future__ import annotations

from pathlib import Path
import sys
import time
import pytest

from app.db import create_engine_and_session, init_db
from app.models import WorkJob, utcnow
from app.scanners.fclones import run_scan
from app.tasks.context import JobContext
from app.tasks.state_machine import JobCancelRequested, JobState


def test_subprocess_cancellation_terminates_child_without_zombie(tmp_path: Path):
    db_path = tmp_path / "test_subp.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    with SessionLocal() as session:
        job = WorkJob(kind="fclones-scan", status=JobState.RUNNING.value)
        session.add(job)
        session.commit()
        job_id = job.id

    ctx = JobContext(engine, SessionLocal, job_id)

    # Command running python sleep for 10 seconds
    cmd = [sys.executable, "-c", "import time; time.sleep(10)"]
    report_path = tmp_path / "report.json"
    home_dir = tmp_path / "home"

    # In background or simulate cancel requested after 0.5s:
    # We set cancel_requested_at in DB
    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        j.cancel_requested_at = utcnow()
        session.commit()

    start_time = time.time()
    with pytest.raises(JobCancelRequested):
        run_scan(cmd, report_path=report_path, home_dir=home_dir, context=ctx, poll_interval=0.1)
    duration = time.time() - start_time

    # Must terminate quickly (< 3 seconds, instead of sleeping for 10 seconds)
    assert duration < 3.0

    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        assert j.status == JobState.CANCELLED.value
        assert j.finished_at is not None
