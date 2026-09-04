from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import select

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import DuplicateFile, DuplicateGroup, ScanJob, TaskLock, WorkJob, utcnow
from app.scanners.parser import ParsedGroup, parse_fclones_report_iter
from app.tasks.context import JobContext
from app.tasks.handlers import FclonesScanHandler, SCAN_IMPORT_BATCH_SIZE
from app.tasks.recovery import acquire_worker_ownership
from app.tasks.state_machine import JobLeaseLost
from app.worker import process_work_job


def test_job_context_lease_fencing_raises_job_lease_lost(tmp_path: Path):
    db_path = tmp_path / "test_fence.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    worker_a = "worker-A"
    worker_b = "worker-B"

    # Worker A acquires ownership
    assert acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a) is True

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status="running")
        session.add(job)
        session.commit()
        job_id = job.id

    ctx = JobContext(engine, SessionLocal, job_id, worker_id=worker_a)

    # First checkpoint succeeds under worker A
    ctx.checkpoint(progress_current=10, progress_total=100)

    # Simulate Worker B taking over ownership
    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        assert lock is not None
        lock.owner = worker_b
        session.commit()

    # Second checkpoint under Worker A MUST raise JobLeaseLost
    with pytest.raises(JobLeaseLost):
        ctx.checkpoint(progress_current=20, progress_total=100)


def test_lease_lost_does_not_mutate_job_status(tmp_path: Path):
    settings = Settings(config_dir=tmp_path)
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_a = "worker-A"
    worker_b = "worker-B"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        job = WorkJob(kind="test-lease-lost-job", status="queued")
        session.add(job)
        session.commit()
        job_id = job.id

    from app.tasks.handlers import TaskHandler, register_handler

    checkpoint_reached = False
    after_checkpoint_executed = False

    @register_handler
    class LeaseFencingTestHandler(TaskHandler):
        job_type = "test-lease-lost-job"
        supports_pause = False
        supports_cancel = True
        supports_retry = False
        supports_resume = False

        def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
            nonlocal checkpoint_reached, after_checkpoint_executed
            checkpoint_reached = True
            # Simulate lease stolen right before checkpoint
            with context.SessionLocal() as s:
                lock = s.get(TaskLock, 1)
                lock.owner = worker_b
                s.commit()

            context.checkpoint(progress_current=1, progress_total=2)
            after_checkpoint_executed = True

    # Run job via worker A
    process_work_job(settings, job_id, session_factory=SessionLocal, engine=engine, worker_id=worker_a)

    assert checkpoint_reached is True
    assert after_checkpoint_executed is False, "Code after lost lease must NOT execute"

    # Status must NOT be overwritten with 'failed' or 'completed'
    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        assert j.status != "failed", "Worker that lost lease must not mark job failed"
        assert j.status != "completed", "Worker that lost lease must not mark job completed"


def test_fclones_subprocess_fencing_terminates_child_on_lease_lost(tmp_path: Path):
    from app.scanners.fclones import run_scan

    db_path = tmp_path / "test_subp.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    worker_a = "worker-A"
    worker_b = "worker-B"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        job = WorkJob(kind="fclones-scan", status="running")
        session.add(job)
        session.commit()
        job_id = job.id

    ctx = JobContext(engine, SessionLocal, job_id, worker_id=worker_a)

    # Spawn a sleeping subprocess
    report_file = tmp_path / "report.json"
    child_cmd = ["sleep", "30"]

    # In background, change owner after 0.2s
    import threading
    def steal_lease():
        time.sleep(0.2)
        with SessionLocal() as s:
            lock = s.get(TaskLock, 1)
            lock.owner = worker_b
            s.commit()

    t = threading.Thread(target=steal_lease)
    t.start()

    with pytest.raises(JobLeaseLost):
        run_scan(child_cmd, report_path=report_file, home_dir=tmp_path, context=ctx, poll_interval=0.1)

    t.join()


def test_db_import_fencing_cleans_partial_duplicate_groups(tmp_path: Path):
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
        scan = ScanJob(name="test-fenced-import", mode="dry-run", roots_json=json.dumps([str(data_dir)]), status="queued")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(kind="fclones-scan", status="running", state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(data_dir)]}))
        session.add(work)
        session.commit()
        work_id = work.id

    ctx = JobContext(engine, SessionLocal, work_id, worker_id=worker_a)

    # Create dummy groups for 2 batches
    dummy_groups = [
        ParsedGroup(file_size=100, content_hash=f"hash_{i}", files=(f1, f2))
        for i in range(SCAN_IMPORT_BATCH_SIZE * 2)
    ]

    handler = FclonesScanHandler()

    with patch("app.tasks.handlers.run_scan") as mock_scan, \
         patch("app.tasks.handlers.parse_fclones_report_iter", return_value=iter(dummy_groups)):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_scan.return_value = mock_proc

        original_checkpoint = ctx.checkpoint

        def fencing_checkpoint(*args, **kwargs):
            # When first batch is imported, worker B steals the lease
            if kwargs.get("progress_current") == SCAN_IMPORT_BATCH_SIZE:
                with SessionLocal() as s:
                    lock = s.get(TaskLock, 1)
                    lock.owner = worker_b
                    s.commit()
            return original_checkpoint(*args, **kwargs)

        ctx.checkpoint = fencing_checkpoint

        with pytest.raises(JobLeaseLost):
            handler.run(work, ctx, settings)

    # In fixed5: Stale Worker A did zero mutations upon JobLeaseLost.
    # Partial rows are cleaned up exclusively by the new lease owner (Worker B) during recovery:
    from app.tasks.recovery import recover_interrupted_jobs
    recover_interrupted_jobs(engine, SessionLocal, worker_id=worker_b)

    with SessionLocal() as session:
        groups = session.scalars(select(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_id)).all()
        assert len(groups) == 0, "Partial duplicate groups must be deleted by new owner during recovery"


def test_streaming_parser_does_not_load_whole_file(tmp_path: Path):
    report_file = tmp_path / "test_report.json"
    groups_data = [
        {"file_hash": f"h{i}", "file_len": 1000 + i, "files": [f"/data/file_{i}_1", f"/data/file_{i}_2"]}
        for i in range(10)
    ]
    report_file.write_text(json.dumps({"header": {"version": "0.35.0"}, "groups": groups_data}), encoding="utf-8")

    # Spy on Path.read_text and json.loads to ensure they are NOT called for the entire report
    with patch.object(Path, "read_text", side_effect=AssertionError("Path.read_text must not be called")), \
         patch("json.loads", side_effect=AssertionError("json.loads whole report must not be called")):
        group_iter = parse_fclones_report_iter(report_file)
        # Should be an iterator
        assert hasattr(group_iter, "__iter__")
        groups = list(group_iter)
        assert len(groups) == 10
        assert groups[0].content_hash == "h0"
        assert groups[0].file_size == 1000
