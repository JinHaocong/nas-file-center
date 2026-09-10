from datetime import datetime, timezone
from pathlib import Path
import pytest
from sqlalchemy import text
from unittest.mock import patch
from app.db import create_engine_and_session, init_db
from app.tasks.recovery import claim_next_job, acquire_worker_ownership
from app.models import WorkJob

FROZEN_TIME = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)

def make_task_db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    return engine, SessionLocal

def test_corrupted_active_window_holds_resource_job_but_allows_mutation(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-fail-closed-1"

    # Deterministically force timezone evaluation by enabling window
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE resource_policy
            SET active_window_enabled = 1,
                active_window_start = '01:00',
                active_window_end = '03:00',
                active_window_timezone = 'Invalid/Zone'
            WHERE id = 1
        """))
        conn.commit()

    with SessionLocal() as session:
        j1 = WorkJob(id=301, kind="fclones-scan", status="queued", state_json="{}")
        j2 = WorkJob(id=302, kind="batch-plan-execute", status="queued", state_json="{}")
        session.add_all([j1, j2])
        session.commit()

    with patch("app.tasks.recovery.utcnow", return_value=FROZEN_TIME):
        acquired = acquire_worker_ownership(engine, SessionLocal, worker_id)
        assert acquired is True
        claimed = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed == 302

def test_missing_singleton_holds_resource_job_but_allows_mutation(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-fail-closed-2"

    with engine.connect() as conn:
        conn.execute(text("DELETE FROM resource_policy WHERE id = 1"))
        conn.commit()

    with SessionLocal() as session:
        j1 = WorkJob(id=303, kind="index-root", status="queued", state_json="{}")
        j2 = WorkJob(id=304, kind="batch-plan-execute", status="queued", state_json="{}")
        session.add_all([j1, j2])
        session.commit()

    with patch("app.tasks.recovery.utcnow", return_value=FROZEN_TIME):
        acquired = acquire_worker_ownership(engine, SessionLocal, worker_id)
        assert acquired is True
        claimed = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed == 304
