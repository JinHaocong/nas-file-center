from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import select, text

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import DuplicateFile, DuplicateGroup, ScanJob, TaskLock, WorkJob, WorkerState, utcnow
from app.scanners.parser import ParsedGroup, parse_fclones_report_iter
from app.tasks.context import JobContext
from app.tasks.handlers import FclonesScanHandler, SCAN_IMPORT_BATCH_SIZE
from app.tasks.recovery import (
    WORKER_LEASE_TIMEOUT_SECONDS,
    acquire_worker_ownership,
    claim_next_job,
    update_worker_heartbeat,
)
from app.tasks.state_machine import JobLeaseLost
from app.worker import WorkerHeartbeatThread, process_work_job


def test_expired_owner_cannot_resurrect_lease_with_heartbeat(tmp_path: Path):
    db_path = tmp_path / "test_hb_resurrect.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    worker_a = "worker-A"
    assert acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a) is True

    # Simulate lease expiration (acquired_at was 40s ago > 30s timeout)
    expired_time = utcnow() - timedelta(seconds=WORKER_LEASE_TIMEOUT_SECONDS + 10)
    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        lock.acquired_at = expired_time
        state = session.get(WorkerState, "default")
        state.heartbeat_at = expired_time
        session.commit()

    # Heartbeat MUST fail because lease is expired
    res = update_worker_heartbeat(engine, SessionLocal, worker_id=worker_a)
    assert res is False, "Heartbeat must not renew or resurrect an expired lease!"

    # Timestamps in DB must remain unchanged (not updated to now)
    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        state = session.get(WorkerState, "default")
        lock_t = lock.acquired_at if lock.acquired_at.tzinfo is not None else lock.acquired_at.replace(tzinfo=timezone.utc)
        exp_t = expired_time if expired_time.tzinfo is not None else expired_time.replace(tzinfo=timezone.utc)
        assert (lock_t - exp_t).total_seconds() < 1.0


def test_idle_worker_reenters_acquire_after_lease_loss(tmp_path: Path):
    db_path = tmp_path / "test_claim_idle.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    worker_a = "worker-A"
    worker_b = "worker-B"
    assert acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a) is True

    # When queue is empty and lease valid -> claim_next_job returns None
    assert claim_next_job(engine, SessionLocal, worker_id=worker_a) is None

    # Simulate Worker B taking over lease
    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        lock.owner = worker_b
        lock.acquired_at = utcnow()
        session.commit()

    # Now Worker A attempts to claim -> must raise JobLeaseLost instead of returning None
    with pytest.raises(JobLeaseLost):
        claim_next_job(engine, SessionLocal, worker_id=worker_a)


def test_stale_worker_cannot_run_initial_scan_cleanup(tmp_path: Path):
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
        scan = ScanJob(name="test-init-cleanup", mode="dry-run", roots_json=json.dumps([str(data_dir)]), status="running")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(kind="fclones-scan", status="running", state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(data_dir)]}))
        session.add(work)
        session.commit()
        work_id = work.id

    ctx = JobContext(engine, SessionLocal, work_id, worker_id=worker_a)
    handler = FclonesScanHandler()

    sentinel_id = 888888
    # Worker B writes a sentinel DuplicateGroup for this scan
    with SessionLocal() as s:
        s.add(DuplicateGroup(
            id=sentinel_id,
            scan_job_id=scan_id,
            content_hash="sentinel_init",
            file_size=100,
            member_count=2,
        ))
        s.commit()

    with patch("app.tasks.handlers.run_scan") as mock_scan:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_scan.return_value = mock_proc

        original_checkpoint = ctx.checkpoint

        def steal_at_parse_start(*args, **kwargs):
            res = original_checkpoint(*args, **kwargs)
            if kwargs.get("progress_message") == "Parsing scan results into database...":
                # Worker B steals lease right before initial cleanup
                with SessionLocal() as s:
                    lock = s.get(TaskLock, 1)
                    lock.owner = worker_b
                    lock.acquired_at = utcnow()
                    s.commit()
            return res

        ctx.checkpoint = steal_at_parse_start

        # Stale Worker A must raise JobLeaseLost and MUST NOT delete sentinel_group
        with pytest.raises(JobLeaseLost):
            handler.run(work, ctx, settings)

    with SessionLocal() as session:
        sentinel = session.get(DuplicateGroup, sentinel_id)
        assert sentinel is not None, "Stale worker must NOT delete duplicate groups during initial cleanup!"


def test_stale_worker_generic_exception_cannot_mark_job_failed(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_a = "worker-A"
    worker_b = "worker-B"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        scan = ScanJob(name="test-fail-fence", mode="dry-run", roots_json=json.dumps([str(data_dir)]), status="running")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(kind="fclones-scan", status="running", state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(data_dir)]}))
        session.add(work)
        session.commit()
        work_id = work.id

    with patch("app.tasks.handlers.FclonesScanHandler.run") as mock_run:
        def fail_after_lease_loss(*args, **kwargs):
            # Worker B steals lease while handler is running
            with SessionLocal() as s:
                lock = s.get(TaskLock, 1)
                lock.owner = worker_b
                lock.acquired_at = utcnow()
                s.commit()
            raise RuntimeError("Something exploded in stale worker")

        mock_run.side_effect = fail_after_lease_loss

        # Run via worker A
        res = process_work_job(settings, work_id, session_factory=SessionLocal, engine=engine, worker_id=worker_a)
        assert res is False

    # Verify that Worker A did NOT mark the job failed or mutate ScanJob
    with SessionLocal() as session:
        w = session.get(WorkJob, work_id)
        s = session.get(ScanJob, scan_id)
        assert w.status != "failed", "Stale worker must not mutate WorkJob to failed"
        assert s.status != "failed", "Stale worker must not mutate ScanJob to failed"


def test_checkpoint_lease_check_and_mutation_are_same_write_transaction(tmp_path: Path):
    db_path = tmp_path / "test_chk_txn.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    worker_a = "worker-A"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status="running")
        session.add(job)
        session.commit()
        job_id = job.id

    ctx = JobContext(engine, SessionLocal, job_id, worker_id=worker_a)

    # Checkpoint must execute under immediate write transaction and succeed
    ctx.checkpoint(progress_current=5, progress_total=10)

    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        assert j.progress_current == 5


def test_parser_rejects_missing_top_level_closing_brace(tmp_path: Path):
    report_file = tmp_path / "missing_brace.json"
    report_file.write_text('{"header": {}, "groups": [{"file_hash": "h1", "file_len": 10, "files": ["/a", "/b"]}]', encoding="utf-8")

    with pytest.raises(ValueError, match="top-level"):
        list(parse_fclones_report_iter(report_file))


def test_parser_rejects_trailing_garbage(tmp_path: Path):
    report_file = tmp_path / "trailing_garbage.json"
    report_file.write_text('{"header": {}, "groups": [{"file_hash": "h1", "file_len": 10, "files": ["/a", "/b"]}]} GARBAGE_DATA', encoding="utf-8")

    with pytest.raises(ValueError, match="trailing"):
        list(parse_fclones_report_iter(report_file))


def test_parser_uses_groups_key_not_first_array(tmp_path: Path):
    report_file = tmp_path / "header_arrays.json"
    # Header contains arrays, but groups is the actual duplicate groups array
    report_file.write_text(json.dumps({
        "header": {
            "features": ["feature1", "feature2"],
            "roots": ["/data/root1"]
        },
        "groups": [
            {
                "file_hash": "valid_hash",
                "file_len": 4096,
                "files": ["/data/root1/file1.txt", "/data/root1/file2.txt"]
            }
        ]
    }), encoding="utf-8")

    groups = list(parse_fclones_report_iter(report_file))
    assert len(groups) == 1
    assert groups[0].content_hash == "valid_hash"
    assert groups[0].file_size == 4096
    assert len(groups[0].files) == 2
