from datetime import datetime, timezone
from pathlib import Path
import pytest
from unittest.mock import patch
from app.db import create_engine_and_session, init_db
from app.models import WorkJob, ResourcePolicy
from app.tasks.handlers import FclonesScanHandler, IndexRootHandler
from app.tasks.recovery import acquire_worker_ownership, claim_next_job

def make_task_db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    return engine, SessionLocal

def test_handlers_declare_supports_pause_false():
    assert FclonesScanHandler.supports_pause is False
    assert IndexRootHandler.supports_pause is False

def test_running_job_remains_running_on_window_transition(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-transition-test"

    with SessionLocal() as session:
        p = session.get(ResourcePolicy, 1)
        p.active_window_enabled = False
        p.revision = 1

        j1 = WorkJob(id=501, kind="fclones-scan", status="running", state_json='{"roots": ["/allowed/root"]}')
        j2 = WorkJob(id=502, kind="index-root", status="queued", state_json='{"root": "/allowed/root"}')
        j3 = WorkJob(id=503, kind="batch-plan-execute", status="queued", state_json='{}')
        session.add_all([j1, j2, j3])
        session.commit()

    fixed_outside = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
    with SessionLocal() as session:
        p = session.get(ResourcePolicy, 1)
        p.active_window_enabled = True
        p.active_window_start = "01:00"
        p.active_window_end = "06:00"
        p.active_window_timezone = "UTC"
        p.outside_window_mode = "pause"
        p.revision = 2
        session.commit()

    with patch("app.tasks.recovery.utcnow", return_value=fixed_outside):
        acquired = acquire_worker_ownership(engine, SessionLocal, worker_id)
        assert acquired is True

        claimed_mutation = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed_mutation == 503

        claimed_none = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed_none is None

    with SessionLocal() as session:
        current_j1 = session.get(WorkJob, 501)
        assert current_j1.status == "running"
        assert current_j1.pause_requested_at is None
        assert current_j1.cancel_requested_at is None
        assert current_j1.error_code is None

        current_j2 = session.get(WorkJob, 502)
        assert current_j2.status == "queued"
