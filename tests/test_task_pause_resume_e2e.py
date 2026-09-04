from __future__ import annotations

import json
from pathlib import Path
from sqlalchemy import select

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import WorkJob, TaskEvent, utcnow
from app.tasks.context import JobContext
from app.tasks.handlers import TaskHandler, register_handler
from app.tasks.recovery import acquire_worker_ownership, claim_next_job
from app.tasks.state_machine import JobState
from app.worker import process_work_job

PROCESSED_UNITS: list[int] = []


@register_handler
class MultiUnitTestHandler(TaskHandler):
    job_type = "multi-unit-test"
    supports_pause = True
    supports_cancel = True
    supports_retry = True
    supports_resume = True

    def run(self, job: WorkJob, context: JobContext, settings) -> None:
        start_cursor = 0
        if job.checkpoint_json:
            try:
                cp = json.loads(job.checkpoint_json)
                start_cursor = cp.get("cursor", 0)
            except Exception:
                start_cursor = 0

        total_units = 6
        for unit in range(start_cursor + 1, total_units + 1):
            # Checkpoint at safe operation boundary
            context.checkpoint(
                progress_current=unit - 1,
                progress_total=total_units,
                progress_message=f"Processing unit {unit}/{total_units}",
                checkpoint_data={"schema_version": 1, "cursor": unit - 1},
            )
            # Perform atomic unit work
            PROCESSED_UNITS.append(unit)
            # Checkpoint after atomic unit work
            context.checkpoint(
                progress_current=unit,
                progress_total=total_units,
                progress_message=f"Completed unit {unit}/{total_units}",
                checkpoint_data={"schema_version": 1, "cursor": unit},
            )


def test_pause_and_resume_e2e(tmp_path: Path):
    global PROCESSED_UNITS
    PROCESSED_UNITS = []

    settings = Settings(config_dir=tmp_path)
    db_path = settings.database_path
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    # 1. Create queued job
    with SessionLocal() as session:
        job = WorkJob(
            kind="multi-unit-test",
            status=JobState.QUEUED.value,
        )
        session.add(job)
        session.commit()
        job_id = job.id

    # 2. Worker acquires ownership and claims job
    acquire_worker_ownership(engine, SessionLocal, worker_id="worker-test")
    claimed = claim_next_job(engine, SessionLocal, worker_id="worker-test")
    assert claimed == job_id

    # 3. Request Pause after 2 units are processed:
    # We set pause_requested_at in DB
    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        j.pause_requested_at = utcnow()
        session.commit()

    # 4. Worker executes job -> should safely pause at checkpoint
    process_work_job(settings, job_id, session_factory=SessionLocal, engine=engine)

    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        assert j.status == JobState.PAUSED.value
        assert j.finished_at is None
        cp = json.loads(j.checkpoint_json)
        assert cp["cursor"] >= 0

    # Verify that not all 6 units were executed
    units_first_run = list(PROCESSED_UNITS)
    assert len(units_first_run) < 6

    # 5. Resume job: paused -> queued, clear pause_requested_at
    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        j.status = JobState.QUEUED.value
        j.pause_requested_at = None
        session.commit()

    # 6. Worker claims resumed job and completes it
    claimed_again = claim_next_job(engine, SessionLocal, worker_id="worker-test")
    assert claimed_again == job_id

    process_work_job(settings, job_id, session_factory=SessionLocal, engine=engine)

    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        assert j.status == JobState.COMPLETED.value
        assert j.finished_at is not None
        assert j.progress_current == 6
        assert j.progress_total == 6

    # 7. Verify exactly all units 1..6 completed without duplicate execution
    assert sorted(PROCESSED_UNITS) == [1, 2, 3, 4, 5, 6]
