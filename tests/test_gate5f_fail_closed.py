import logging
from datetime import datetime, timezone
from pathlib import Path
import pytest
from sqlalchemy import text
from unittest.mock import patch
from app.db import create_engine_and_session, init_db
from app.tasks.recovery import claim_next_job, acquire_worker_ownership, assert_active_worker_lease
from app.models import WorkJob

FROZEN_TIME = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)

def make_task_db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    return engine, SessionLocal

def test_corrupted_active_window_holds_resource_job_but_allows_mutation(tmp_path: Path, caplog: pytest.LogCaptureFixture):
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
        with caplog.at_level(logging.WARNING):
            claimed = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed == 302

    with SessionLocal() as session:
        assert session.get(WorkJob, 301).status == "queued"
        assert session.get(WorkJob, 302).status == "running"

    assert any(
        record.levelno >= logging.WARNING
        and "ResourcePolicy invalid or unavailable" in record.message
        and "resource-controlled jobs held fail-closed" in record.message
        for record in caplog.records
    ), f"Expected fail-closed warning log not found in {caplog.text}"

def test_missing_singleton_holds_resource_job_but_allows_mutation(tmp_path: Path, caplog: pytest.LogCaptureFixture):
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
        with caplog.at_level(logging.WARNING):
            claimed = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed == 304

    with SessionLocal() as session:
        assert session.get(WorkJob, 303).status == "queued"
        assert session.get(WorkJob, 304).status == "running"

    assert any(
        record.levelno >= logging.WARNING
        and "ResourcePolicy invalid or unavailable" in record.message
        and "resource-controlled jobs held fail-closed" in record.message
        for record in caplog.records
    ), f"Expected fail-closed warning log not found in {caplog.text}"

def test_missing_singleton_with_only_resource_job_returns_none_and_logs(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-fail-closed-3"

    with engine.connect() as conn:
        conn.execute(text("DELETE FROM resource_policy WHERE id = 1"))
        conn.commit()

    with SessionLocal() as session:
        j1 = WorkJob(id=305, kind="index-root", status="queued", state_json="{}")
        session.add(j1)
        session.commit()

    with patch("app.tasks.recovery.utcnow", return_value=FROZEN_TIME):
        acquired = acquire_worker_ownership(engine, SessionLocal, worker_id)
        assert acquired is True
        with caplog.at_level(logging.WARNING):
            claimed = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed is None

    with SessionLocal() as session:
        assert session.get(WorkJob, 305).status == "queued"
        assert_active_worker_lease(session, worker_id, now=FROZEN_TIME)

    assert any(
        record.levelno >= logging.WARNING
        and "ResourcePolicy invalid or unavailable" in record.message
        and "resource-controlled jobs held fail-closed" in record.message
        for record in caplog.records
    ), f"Expected fail-closed warning log not found in {caplog.text}"
