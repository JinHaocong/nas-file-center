from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import init_db
from app.models import WorkJob, WorkerState, TaskEvent, utcnow


def test_v032_to_v033_migration(tmp_path: Path):
    db_path = tmp_path / "test_migration.db"
    backups_dir = tmp_path / "backups"

    # 1. Create a simulated v0.3.2 database with old work_jobs schema (missing v0.3.3 columns)
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE work_jobs (
            id INTEGER PRIMARY KEY,
            kind VARCHAR(64),
            status VARCHAR(32),
            progress_current BIGINT,
            progress_total BIGINT,
            state_json TEXT,
            error_text TEXT,
            created_at DATETIME,
            started_at DATETIME,
            finished_at DATETIME
        );
    """)
    cursor.execute("""
        INSERT INTO work_jobs (id, kind, status, progress_current, progress_total, state_json, created_at)
        VALUES (1, 'fclones-scan', 'completed', 10, 10, '{"scan_job_id": 1}', '2026-09-01 00:00:00');
    """)
    cursor.execute("""
        INSERT INTO work_jobs (id, kind, status, progress_current, progress_total, state_json, created_at)
        VALUES (2, 'index-root', 'queued', 0, 0, '{"root": "/data"}', '2026-09-02 00:00:00');
    """)
    conn.commit()
    conn.close()

    # 2. Run init_db to migrate to v0.3.3
    engine = create_engine(f"sqlite:///{db_path}")
    init_db(
        engine,
        db_path=db_path,
        backups_dir=backups_dir,
        initial_admin_username="admin",
        initial_admin_password="Password123!",
    )

    # 3. Verify backup was created
    backups = list(backups_dir.glob("*.db"))
    assert len(backups) >= 1

    # 4. Verify existing data preserved and new columns present
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        j1 = session.get(WorkJob, 1)
        assert j1 is not None
        assert j1.kind == "fclones-scan"
        assert j1.status == "completed"
        assert j1.pause_requested_at is None
        assert j1.cancel_requested_at is None
        assert j1.heartbeat_at is None
        assert j1.progress_message is None
        assert j1.checkpoint_json in (None, "{}")
        assert j1.error_code is None
        assert j1.retry_of is None

        j2 = session.get(WorkJob, 2)
        assert j2 is not None
        assert j2.kind == "index-root"
        assert j2.status == "queued"

        # 5. Verify worker_state table functions
        ws = WorkerState(
            worker_key="default",
            worker_id="worker-test-1",
            started_at=utcnow(),
            heartbeat_at=utcnow(),
        )
        session.add(ws)
        session.commit()

        ws_db = session.get(WorkerState, "default")
        assert ws_db is not None
        assert ws_db.worker_id == "worker-test-1"

        # 6. Verify task_events table functions with CASCADE
        event = TaskEvent(
            job_id=j1.id,
            timestamp=utcnow(),
            level="info",
            event_type="started",
            message="Job started",
            context_json=json.dumps({"test": True}),
        )
        session.add(event)
        session.commit()

        events = list(session.scalars(select(TaskEvent).where(TaskEvent.job_id == j1.id)))
        assert len(events) == 1
        assert events[0].event_type == "started"

        # Delete job 1 -> task_events cascade deleted
        session.delete(j1)
        session.commit()

        events_after = list(session.scalars(select(TaskEvent).where(TaskEvent.job_id == 1)))
        assert len(events_after) == 0

    # 7. Idempotency test: second init_db run succeeds without error
    init_db(
        engine,
        db_path=db_path,
        backups_dir=backups_dir,
        initial_admin_username="admin",
        initial_admin_password="Password123!",
    )
