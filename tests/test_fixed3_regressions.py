from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import pytest
from sqlalchemy import select, text

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import DuplicateFile, DuplicateGroup, ScanJob, TaskEvent, TaskLock, WorkJob, WorkerState, utcnow
from app.tasks.context import JobContext
from app.tasks.logging import log_task_event, sanitize_text
from app.tasks.recovery import (
    acquire_worker_ownership,
    recover_interrupted_jobs,
)
from app.tasks.service import TaskService


def test_recovery_syncs_cancel_requested_fclones_scan(tmp_path: Path):
    db_path = tmp_path / "test_rec.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    acquire_worker_ownership(engine, SessionLocal, worker_id="worker-test")

    with SessionLocal() as session:
        scan = ScanJob(name="test-scan", mode="dry-run", roots_json=json.dumps([str(tmp_path)]), status="running")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(
            kind="fclones-scan",
            status="cancel_requested",
            state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(tmp_path)]}),
        )
        session.add(work)
        session.commit()
        work_id = work.id

    # Run worker restart recovery
    stats = recover_interrupted_jobs(engine, SessionLocal, worker_id="worker-test")
    assert stats["cancelled"] == 1

    with SessionLocal() as session:
        w = session.get(WorkJob, work_id)
        s = session.get(ScanJob, scan_id)
        assert w.status == "cancelled"
        assert s.status == "cancelled", "ScanJob must be cancelled during recovery of cancel_requested job"
        assert s.finished_at is not None
        assert s.error_text == "Cancelled by user"


def test_retry_payload_whitelist_schema(tmp_path: Path):
    settings = Settings(config_dir=tmp_path)
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)
    srv = TaskService(SessionLocal)

    with SessionLocal() as session:
        # 1. index-root job with malicious / unexpected fields
        job1 = WorkJob(
            kind="index-root",
            status="failed",
            state_json=json.dumps({
                "root": "/data",
                "allow_mutation": True,
                "allow_delete": True,
                "authorization": "secret",
                "unexpected": "x",
            }),
        )
        # 2. fclones-scan job with unexpected fields
        job2 = WorkJob(
            kind="fclones-scan",
            status="failed",
            state_json=json.dumps({
                "scan_job_id": 42,
                "roots": ["/data"],
                "isolate": False,
                "min_size": 1024,
                "name_patterns": ["*.jpg"],
                "exclude_patterns": ["*.tmp"],
                "allow_mutation": True,
                "allow_delete": True,
                "authorization": "super-secret",
                "unexpected": "y",
            }),
        )
        session.add(job1)
        session.add(job2)
        session.commit()
        id1 = job1.id
        id2 = job2.id

    # Retry index-root
    ret1 = srv.retry_task(id1)
    new_id1 = ret1["job"]["id"]

    # Retry fclones-scan
    ret2 = srv.retry_task(id2)
    new_id2 = ret2["job"]["id"]

    with SessionLocal() as session:
        nj1 = session.get(WorkJob, new_id1)
        nj2 = session.get(WorkJob, new_id2)

        payload1 = json.loads(nj1.state_json or "{}")
        assert "allow_mutation" not in payload1
        assert "allow_delete" not in payload1
        assert "authorization" not in payload1
        assert "unexpected" not in payload1
        assert payload1 == {"root": "/data"}

        payload2 = json.loads(nj2.state_json or "{}")
        assert "allow_mutation" not in payload2
        assert "allow_delete" not in payload2
        assert "authorization" not in payload2
        assert "unexpected" not in payload2
        assert payload2 == {
            "scan_job_id": 42,
            "roots": ["/data"],
            "isolate": False,
            "min_size": 1024,
            "name_patterns": ["*.jpg"],
            "exclude_patterns": ["*.tmp"],
        }


def test_task_event_secret_redaction(tmp_path: Path):
    db_path = tmp_path / "test_logging.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    with SessionLocal() as session:
        # Create a work job for FK
        job = WorkJob(kind="index-root", status="running")
        session.add(job)
        session.commit()
        job_id = job.id

        log_task_event(
            session,
            job_id=job_id,
            event_type="test_event",
            message="Connecting with Authorization: Bearer SECRET123 and token=ABC",
            level="info",
            context={
                "error": "Failed authentication with password=SECRET123; token: ABC",
                "details": {
                    "cookie": "session=ABC; api_key=XYZ123",
                    "safe_key": "safe_value",
                },
            },
        )
        session.commit()

        event = session.scalars(select(TaskEvent).where(TaskEvent.job_id == job_id)).one()

        # Database raw fields MUST NOT leak secrets
        assert "SECRET123" not in event.message, f"Secret leaked in message: {event.message}"
        assert "SECRET123" not in event.context_json, f"Secret leaked in context_json: {event.context_json}"
        assert "ABC" not in event.context_json, f"Token leaked in context_json: {event.context_json}"
        assert "XYZ123" not in event.context_json, f"API key leaked in context_json: {event.context_json}"

        assert "[REDACTED]" in event.message
        assert "[REDACTED]" in event.context_json
        assert "safe_value" in event.context_json


def test_progress_consistency_bounds(tmp_path: Path):
    db_path = tmp_path / "test_progress.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status="running", progress_current=100, progress_total=100)
        session.add(job)
        session.commit()
        job_id = job.id

    ctx = JobContext(engine, SessionLocal, job_id)

    # 1. Total cannot shrink below saved current
    with pytest.raises(ValueError, match="cannot be smaller than saved progress_current"):
        ctx.checkpoint(progress_total=50)

    # 2. Current cannot exceed total
    with pytest.raises(ValueError, match="cannot exceed progress_total"):
        ctx.checkpoint(progress_current=150, progress_total=100)

    # 3. Negative current not allowed
    with pytest.raises(ValueError, match="non-negative"):
        ctx.checkpoint(progress_current=-1)

    # 4. Negative total not allowed
    with pytest.raises(ValueError, match="non-negative"):
        ctx.checkpoint(progress_total=-5)


def test_fclones_import_batching_and_cleanup_on_cancel(tmp_path: Path):
    from unittest.mock import patch, MagicMock
    from app.tasks.handlers import FclonesScanHandler, SCAN_IMPORT_BATCH_SIZE
    from app.scanners.parser import ParsedGroup
    from app.tasks.state_machine import JobCancelRequested

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    f1 = data_dir / "file1.txt"
    f2 = data_dir / "file2.txt"
    f1.write_text("hello")
    f2.write_text("hello")

    settings = Settings(
        config_dir=tmp_path,
        allowed_roots_raw=str(data_dir),
    )
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    with SessionLocal() as session:
        scan = ScanJob(name="test-batch-import", mode="dry-run", roots_json=json.dumps([str(data_dir)]), status="queued")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(
            kind="fclones-scan",
            status="running",
            state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(data_dir)]}),
        )
        session.add(work)
        session.commit()
        work_id = work.id

    ctx = JobContext(engine, SessionLocal, work_id)

    # Create dummy parsed groups (more than 1 batch)
    num_groups = SCAN_IMPORT_BATCH_SIZE + 20
    dummy_groups = [
        ParsedGroup(file_size=100, content_hash=f"hash_{i}", files=[str(f1), str(f2)])
        for i in range(num_groups)
    ]

    handler = FclonesScanHandler()

    with patch("app.tasks.handlers.run_scan") as mock_scan, \
         patch("app.tasks.handlers.parse_fclones_report_iter", return_value=iter(dummy_groups)):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_scan.return_value = mock_proc

        # Simulate user cancelling after first batch is imported
        original_checkpoint = ctx.checkpoint
        checkpoints_called = []

        def cancelling_checkpoint(*args, **kwargs):
            checkpoints_called.append(kwargs)
            # When we reach the first batch boundary (progress_current == SCAN_IMPORT_BATCH_SIZE), request cancel
            if kwargs.get("progress_current") == SCAN_IMPORT_BATCH_SIZE:
                with SessionLocal() as s:
                    w = s.get(WorkJob, work_id)
                    w.cancel_requested_at = utcnow()
                    s.commit()
            return original_checkpoint(*args, **kwargs)

        ctx.checkpoint = cancelling_checkpoint

        # Should raise JobCancelRequested and perform cleanup
        with pytest.raises(JobCancelRequested):
            handler.run(work, ctx, settings)

    # Verify cleanup: NO partial DuplicateGroup / DuplicateFile left in DB!
    with SessionLocal() as session:
        groups = session.scalars(select(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_id)).all()
        assert len(groups) == 0, "Partial duplicate groups must be deleted upon cancel"
        s = session.get(ScanJob, scan_id)
        assert s.total_groups == 0
        assert s.reclaimable_bytes == 0
