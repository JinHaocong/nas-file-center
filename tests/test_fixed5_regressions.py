from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import select, text

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import DuplicateFile, DuplicateGroup, ScanJob, TaskEvent, TaskLock, WorkJob, utcnow
from app.scanners.fclones import run_scan
from app.scanners.parser import ParsedGroup, parse_fclones_report_iter
from app.tasks.context import JobContext
from app.tasks.handlers import FclonesScanHandler, SCAN_IMPORT_BATCH_SIZE
from app.tasks.logging import log_task_event, sanitize_text
from app.tasks.recovery import (
    WORKER_LEASE_TIMEOUT_SECONDS,
    acquire_worker_ownership,
    assert_active_worker_lease,
)
from app.tasks.state_machine import JobLeaseLost
from app.worker import process_work_job


def test_stale_worker_never_cleans_after_lease_lost(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    f1 = data_dir / "f1.txt"
    f2 = data_dir / "f2.txt"
    f1.write_text("aaa")
    f2.write_text("aaa")

    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_a = "worker-A"
    worker_b = "worker-B"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        scan = ScanJob(name="test-fencing", mode="dry-run", roots_json=json.dumps([str(data_dir)]), status="running")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(kind="fclones-scan", status="running", state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(data_dir)]}))
        session.add(work)
        session.commit()
        work_id = work.id

    ctx = JobContext(engine, SessionLocal, work_id, worker_id=worker_a)

    dummy_groups = [
        ParsedGroup(file_size=100, content_hash=f"hash_{i}", files=(f1, f2))
        for i in range(SCAN_IMPORT_BATCH_SIZE * 2)
    ]

    handler = FclonesScanHandler()

    sentinel_id = 999999

    with patch("app.tasks.handlers.run_scan") as mock_scan, \
         patch("app.tasks.handlers.parse_fclones_report_iter", return_value=iter(dummy_groups)):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_scan.return_value = mock_proc

        original_checkpoint = ctx.checkpoint

        def checkpoint_hook(*args, **kwargs):
            # When batch 1 checkpoint is reached: Worker B steals the lease and writes a sentinel result
            if kwargs.get("progress_current") == SCAN_IMPORT_BATCH_SIZE:
                with SessionLocal() as s:
                    lock = s.get(TaskLock, 1)
                    lock.owner = worker_b
                    lock.acquired_at = utcnow()
                    # B writes a sentinel DuplicateGroup
                    sentinel_group = DuplicateGroup(
                        id=sentinel_id,
                        scan_job_id=scan_id,
                        content_hash="sentinel_hash",
                        file_size=555,
                        member_count=2,
                    )
                    s.add(sentinel_group)
                    s.commit()
            return original_checkpoint(*args, **kwargs)

        ctx.checkpoint = checkpoint_hook

        # Worker A must raise JobLeaseLost
        with pytest.raises(JobLeaseLost):
            handler.run(work, ctx, settings)

    # Worker A MUST NOT delete Worker B's sentinel result!
    with SessionLocal() as session:
        b_result = session.get(DuplicateGroup, sentinel_id)
        assert b_result is not None, "Worker A must NOT delete Worker B's result after losing lease!"


def test_checkpoint_rejects_expired_same_owner_lease(tmp_path: Path):
    db_path = tmp_path / "test_exp.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    worker_a = "worker-A"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status="running")
        session.add(job)
        session.commit()
        job_id = job.id

        # Set acquired_at to 120 seconds ago (expired)
        lock = session.get(TaskLock, 1)
        lock.acquired_at = utcnow() - timedelta(seconds=120)
        session.commit()

    ctx = JobContext(engine, SessionLocal, job_id, worker_id=worker_a)

    # Must raise JobLeaseLost because lease has expired
    with pytest.raises(JobLeaseLost, match="expired"):
        ctx.checkpoint(progress_current=10, progress_total=100)


def test_batch_write_rechecks_lease_inside_write_transaction(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    f1 = data_dir / "f1.txt"
    f2 = data_dir / "f2.txt"
    f1.write_text("aaa")
    f2.write_text("aaa")

    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_a = "worker-A"
    worker_b = "worker-B"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        scan = ScanJob(name="test-batch-recheck", mode="dry-run", roots_json=json.dumps([str(data_dir)]), status="running")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(kind="fclones-scan", status="running", state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(data_dir)]}))
        session.add(work)
        session.commit()
        work_id = work.id

    ctx = JobContext(engine, SessionLocal, work_id, worker_id=worker_a)

    dummy_groups = [
        ParsedGroup(file_size=100, content_hash=f"hash_{i}", files=(f1, f2))
        for i in range(10)
    ]

    handler = FclonesScanHandler()

    with patch("app.tasks.handlers.run_scan") as mock_scan, \
         patch("app.tasks.handlers.parse_fclones_report_iter", return_value=iter(dummy_groups)):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_scan.return_value = mock_proc

        # Transfer lease to Worker B right after parsing starts but before batch write transaction
        with SessionLocal() as s:
            lock = s.get(TaskLock, 1)
            lock.owner = worker_b
            lock.acquired_at = utcnow()
            s.commit()

        # Handler run must raise JobLeaseLost inside the batch write transaction
        with pytest.raises(JobLeaseLost):
            handler.run(work, ctx, settings)

    # Verify no groups were written
    with SessionLocal() as session:
        groups = session.scalars(select(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_id)).all()
        assert len(groups) == 0


def test_final_completion_rechecks_lease(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    f1 = data_dir / "f1.txt"
    f2 = data_dir / "f2.txt"
    f1.write_text("aaa")
    f2.write_text("aaa")

    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_a = "worker-A"
    worker_b = "worker-B"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        scan = ScanJob(name="test-final-recheck", mode="dry-run", roots_json=json.dumps([str(data_dir)]), status="running")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(kind="fclones-scan", status="running", state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(data_dir)]}))
        session.add(work)
        session.commit()
        work_id = work.id

    ctx = JobContext(engine, SessionLocal, work_id, worker_id=worker_a)

    dummy_groups = [
        ParsedGroup(file_size=100, content_hash="hash_final", files=(f1, f2))
    ]

    handler = FclonesScanHandler()

    with patch("app.tasks.handlers.run_scan") as mock_scan, \
         patch("app.tasks.handlers.parse_fclones_report_iter", return_value=iter(dummy_groups)):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_scan.return_value = mock_proc

        original_checkpoint = ctx.checkpoint

        def final_checkpoint_hook(*args, **kwargs):
            # Right when final batch checkpoint passes, B steals lease before final completion commit
            res = original_checkpoint(*args, **kwargs)
            with SessionLocal() as s:
                lock = s.get(TaskLock, 1)
                lock.owner = worker_b
                lock.acquired_at = utcnow()
                s.commit()
            return res

        ctx.checkpoint = final_checkpoint_hook

        with pytest.raises(JobLeaseLost):
            handler.run(work, ctx, settings)

    with SessionLocal() as session:
        s = session.get(ScanJob, scan_id)
        assert s.status != "completed", "Stale worker must not mark ScanJob completed"


def test_worker_can_reacquire_after_losing_ownership(tmp_path: Path):
    settings = Settings(config_dir=tmp_path)
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_a = "worker-A"
    worker_b = "worker-B"

    # Worker A acquires lease
    assert acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a) is True

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status="queued", state_json=json.dumps({"root": str(tmp_path)}))
        session.add(job)
        session.commit()
        job_id = job.id

    # Simulate Worker A lease becoming stale so Worker B legitimately takes over
    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        lock.acquired_at = utcnow() - timedelta(seconds=WORKER_LEASE_TIMEOUT_SECONDS + 5)
        session.commit()

    # Worker B acquires ownership (now B is fresh owner)
    assert acquire_worker_ownership(engine, SessionLocal, worker_id=worker_b) is True

    # Worker A runs job and detects lease loss
    result = process_work_job(settings, job_id, session_factory=SessionLocal, engine=engine, worker_id=worker_a)
    assert result is False

    # Worker A attempts to acquire while B is fresh -> must fail
    assert acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a) is False

    # Simulate Worker B becoming stale (> 30s)
    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        lock.acquired_at = utcnow() - timedelta(seconds=WORKER_LEASE_TIMEOUT_SECONDS + 5)
        session.commit()

    # Worker A can now reacquire ownership!
    assert acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a) is True


def test_run_scan_large_stderr_does_not_deadlock(tmp_path: Path):
    report_file = tmp_path / "report.json"

    # Command that writes 2MB to stderr and exits 0
    cmd = [
        sys.executable,
        "-c",
        "import sys; sys.stderr.write('E' * (2 * 1024 * 1024)); sys.stderr.flush(); sys.exit(0)",
    ]

    start = time.time()
    res = run_scan(cmd, report_path=report_file, home_dir=tmp_path, poll_interval=0.1)
    duration = time.time() - start

    assert duration < 10.0, f"run_scan took {duration:.2f}s, likely deadlocked on stderr PIPE!"
    assert res.returncode == 0
    assert len(res.stderr) > 0


def test_stream_parser_rejects_truncated_json(tmp_path: Path):
    truncated_report = tmp_path / "truncated.json"
    truncated_report.write_text("""{"header": {}, "groups": [
      {"file_hash": "hash1", "file_len": 100, "files": ["/a", "/b"]},
      {"file_hash":
    """, encoding="utf-8")

    with pytest.raises((ValueError, json.JSONDecodeError)):
        list(parse_fclones_report_iter(truncated_report))


def test_truncated_scan_report_marks_job_failed_and_cleans_partial(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    f1 = data_dir / "f1.txt"
    f2 = data_dir / "f2.txt"
    f1.write_text("aaa")
    f2.write_text("aaa")

    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_a = "worker-A"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        scan = ScanJob(name="test-truncated", mode="dry-run", roots_json=json.dumps([str(data_dir)]), status="running")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(kind="fclones-scan", status="running", state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(data_dir)]}))
        session.add(work)
        session.commit()
        work_id = work.id

    ctx = JobContext(engine, SessionLocal, work_id, worker_id=worker_a)

    def truncated_generator():
        # First yield valid group
        yield ParsedGroup(file_size=100, content_hash="hash_1", files=(f1, f2))
        # Then simulate unexpected truncation exception
        raise ValueError("Truncated or malformed fclones JSON report")

    handler = FclonesScanHandler()

    with patch("app.tasks.handlers.run_scan") as mock_scan, \
         patch("app.tasks.handlers.parse_fclones_report_iter", return_value=truncated_generator()):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_scan.return_value = mock_proc

        with pytest.raises(ValueError, match="Truncated or malformed"):
            handler.run(work, ctx, settings)

    # Verify that partial groups were cleaned up
    with SessionLocal() as session:
        groups = session.scalars(select(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_id)).all()
        assert len(groups) == 0, "Partial groups from truncated report must be cleaned up"


def test_json_style_secret_redaction(tmp_path: Path):
    db_path = tmp_path / "test_json_secret.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status="running")
        session.add(job)
        session.commit()
        job_id = job.id

        log_task_event(
            session,
            job_id=job_id,
            event_type="test_event",
            message='Config: {"password":"SECRET123","token":"ABC","api_key":"XYZ","session":"SESS999"}',
            level="info",
            context={"details": '{"authorization":"BEARER_SECRET"}'},
        )
        session.commit()

        event = session.scalars(select(TaskEvent).where(TaskEvent.job_id == job_id)).one()

        assert "SECRET123" not in event.message, f"Secret leaked in message: {event.message}"
        assert "ABC" not in event.message, f"Token leaked in message: {event.message}"
        assert "XYZ" not in event.message, f"API key leaked in message: {event.message}"
        assert "SESS999" not in event.message, f"Session leaked in message: {event.message}"
        assert "BEARER_SECRET" not in event.context_json, f"Auth leaked in context: {event.context_json}"
