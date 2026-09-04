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
from app.models import (
    DuplicateGroup,
    IndexedPath,
    ScanJob,
    TaskEvent,
    TaskLock,
    WorkJob,
    WorkerState,
    utcnow,
)
from app.scanners.parser import ParsedGroup, parse_fclones_report_iter
from app.tasks.context import JobContext
from app.tasks.handlers import FclonesScanHandler, IndexRootHandler
from app.tasks.recovery import (
    WORKER_LEASE_TIMEOUT_SECONDS,
    acquire_worker_ownership,
    claim_next_job,
    recover_interrupted_jobs,
)
from app.tasks.service import TaskService
from app.tasks.state_machine import JobLeaseLost, JobState, TERMINAL_STATES
from app.worker import process_work_job


def test_cancel_cannot_overwrite_completed_job(tmp_path: Path):
    db_path = tmp_path / "test_cancel_completed.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    service = TaskService(SessionLocal)

    with SessionLocal() as session:
        job = WorkJob(kind="fclones-scan", status=JobState.RUNNING.value, state_json="{}")
        session.add(job)
        session.commit()
        job_id = job.id

    # Worker marks job completed
    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        j.status = JobState.COMPLETED.value
        j.finished_at = utcnow()
        session.commit()

    # Cancel must reject because job is completed
    with pytest.raises(ValueError, match="cannot be cancelled"):
        service.cancel_task(job_id)

    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        assert j.status == JobState.COMPLETED.value


def test_cancel_after_last_handler_checkpoint_finishes_cancelled(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_id = "worker-cancel-last"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_id)

    with SessionLocal() as session:
        scan = ScanJob(name="test-scan-cancel", mode="dry-run", roots_json=json.dumps([str(data_dir)]), status="running")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(kind="fclones-scan", status="running", state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(data_dir)]}))
        session.add(work)
        session.commit()
        work_id = work.id

    # Simulate handler running, but before worker finalization commit, user cancel request arrives
    def mock_handler_run(work_job, ctx, cfg):
        # Handler finishes cleanly, but during execution a cancel request arrived
        with SessionLocal() as s:
            w = s.get(WorkJob, work_id)
            w.status = JobState.CANCEL_REQUESTED.value
            w.cancel_requested_at = utcnow()
            s.commit()

    with patch("app.worker.get_handler") as mock_get_handler:
        mock_handler = MagicMock()
        mock_handler.run.side_effect = mock_handler_run
        mock_get_handler.return_value = mock_handler

        res = process_work_job(settings, work_id, session_factory=SessionLocal, engine=engine, worker_id=worker_id)
        assert res is True

    # Final state must be cancelled, NOT cancel_requested, NOT completed
    with SessionLocal() as session:
        w = session.get(WorkJob, work_id)
        s = session.get(ScanJob, scan_id)
        assert w.status == JobState.CANCELLED.value, f"Expected cancelled but got {w.status}"
        assert s.status == "cancelled"
        assert w.finished_at is not None


def test_task_control_transition_uses_fresh_db_state(tmp_path: Path):
    db_path = tmp_path / "test_fresh_db_state.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    service = TaskService(SessionLocal)

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status=JobState.QUEUED.value, state_json="{}")
        session.add(job)
        session.commit()
        job_id = job.id

    # Another session transitions job to RUNNING
    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        j.status = JobState.RUNNING.value
        session.commit()

    # If cancel is called on index-root while running, it should reject because index-root supports_cancel=False
    with pytest.raises(ValueError, match="does not support cancel"):
        service.cancel_task(job_id)


def test_index_root_batch_write_is_lease_fenced(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # Create 5 files
    for i in range(5):
        (data_dir / f"f{i}.txt").write_text(f"content {i}")

    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_a = "worker-index-A"
    worker_b = "worker-index-B"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        work = WorkJob(kind="index-root", status="running", state_json=json.dumps({"root": str(data_dir)}))
        session.add(work)
        session.commit()
        work_id = work.id

    ctx = JobContext(engine, SessionLocal, work_id, worker_id=worker_a)
    handler = IndexRootHandler()

    # Hook during reindex batch write to transfer lease to Worker B
    from app.service import FileCenterService
    original_reindex = FileCenterService.reindex_root

    def stolen_reindex(self, root, **kwargs):
        # Worker B steals lease before batch write
        with SessionLocal() as s:
            lock = s.get(TaskLock, 1)
            lock.owner = worker_b
            lock.acquired_at = utcnow()
            s.commit()
        return original_reindex(self, root, **kwargs)

    with patch.object(FileCenterService, "reindex_root", stolen_reindex):
        with pytest.raises(JobLeaseLost):
            handler.run(work, ctx, settings)

    # Verify no IndexedPath rows were committed under the stolen lease
    with SessionLocal() as session:
        count = session.scalar(select(text("count(*)")).select_from(IndexedPath))
        assert count == 0, "No indexed paths should be committed after lease is lost"


def test_index_root_final_generation_cleanup_is_lease_fenced(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "f1.txt").write_text("hello")

    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    # Insert an existing indexed path with old generation
    with SessionLocal() as session:
        old_item = IndexedPath(
            root_key=str(data_dir),
            absolute_path=str(data_dir / "old.txt"),
            relative_path="old.txt",
            basename="old.txt",
            stem="old",
            suffix=".txt",
            size=10,
            mtime_ns=1000,
            device=1,
            inode=100,
            is_dir=False,
            first_seen_at=utcnow(),
            last_seen_at=utcnow(),
            scan_generation="old_gen_123",
        )
        session.add(old_item)
        session.commit()

    worker_a = "worker-cleanup-A"
    worker_b = "worker-cleanup-B"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        work = WorkJob(kind="index-root", status="running", state_json=json.dumps({"root": str(data_dir)}))
        session.add(work)
        session.commit()
        work_id = work.id

    ctx = JobContext(engine, SessionLocal, work_id, worker_id=worker_a)
    handler = IndexRootHandler()

    # Steal lease before final cleanup executes (at the checkpoint boundary after batch write)
    original_checkpoint = ctx.checkpoint

    def steal_before_cleanup(*args, **kwargs):
        res = original_checkpoint(*args, **kwargs)
        if "completed" not in kwargs.get("progress_message", "").lower():
            # Transfer lease right after batch write, before final cleanup
            with SessionLocal() as s2:
                lock = s2.get(TaskLock, 1)
                lock.owner = worker_b
                lock.acquired_at = utcnow()
                s2.commit()
        return res

    ctx.checkpoint = steal_before_cleanup

    with pytest.raises(JobLeaseLost):
        handler.run(work, ctx, settings)

    # The old generation item must NOT have been deleted by stale worker A
    with SessionLocal() as session:
        old = session.scalar(select(IndexedPath).where(IndexedPath.scan_generation == "old_gen_123"))
        assert old is not None, "Stale worker must not delete old generation index rows after lease loss"


def test_recovery_rechecks_lease_with_fresh_time(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_a = "worker-recovery-clock"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        work = WorkJob(kind="index-root", status="running", state_json="{}")
        session.add(work)
        session.commit()
        work_id = work.id

    # Simulate clock advancing past lease timeout during recovery
    now0 = utcnow()
    call_count = 0

    def fake_utcnow():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return now0
        # Subsequent calls: 40 seconds later, lease expired!
        return now0 + timedelta(seconds=WORKER_LEASE_TIMEOUT_SECONDS + 10)

    with patch("app.tasks.recovery.utcnow", side_effect=fake_utcnow):
        stats = recover_interrupted_jobs(engine, SessionLocal, worker_id=worker_a, timeout_seconds=WORKER_LEASE_TIMEOUT_SECONDS)

    assert stats["failed_interrupted"] == 0, "Expired recovery must not mutate jobs"
    with SessionLocal() as session:
        w = session.get(WorkJob, work_id)
        assert w.status == "running", "Job must remain in running state when recovery lease expired"


def test_parser_rejects_schema_invalid_group(tmp_path: Path):
    # Missing files
    p1 = tmp_path / "bad1.json"
    p1.write_text('{"groups": [{"file_hash": "h1", "file_len": 20}]}', encoding="utf-8")
    with pytest.raises(ValueError, match="[Ff]ile"):
        list(parse_fclones_report_iter(p1))

    # Files has only 1 element
    p2 = tmp_path / "bad2.json"
    p2.write_text('{"groups": [{"file_hash": "h1", "file_len": 20, "files": ["/a"]}]}', encoding="utf-8")
    with pytest.raises(ValueError, match="at least 2"):
        list(parse_fclones_report_iter(p2))

    # Path entry is not a string
    p3 = tmp_path / "bad3.json"
    p3.write_text('{"groups": [{"file_hash": "h1", "file_len": 20, "files": ["/a", 123]}]}', encoding="utf-8")
    with pytest.raises(ValueError, match="string"):
        list(parse_fclones_report_iter(p3))

    # Empty content hash
    p4 = tmp_path / "bad4.json"
    p4.write_text('{"groups": [{"file_hash": "", "file_len": 20, "files": ["/a", "/b"]}]}', encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        list(parse_fclones_report_iter(p4))

    # Negative file size
    p5 = tmp_path / "bad5.json"
    p5.write_text('{"groups": [{"file_hash": "h1", "file_len": -1, "files": ["/a", "/b"]}]}', encoding="utf-8")
    with pytest.raises(ValueError, match="size"):
        list(parse_fclones_report_iter(p5))


def test_schema_invalid_report_fails_scan_and_cleans_partial(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    f1 = data_dir / "f1.txt"
    f2 = data_dir / "f2.txt"
    f1.write_text("aaa")
    f2.write_text("aaa")

    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_a = "worker-schema-fail"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        scan = ScanJob(name="test-schema-fail", mode="dry-run", roots_json=json.dumps([str(data_dir)]), status="running")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(kind="fclones-scan", status="running", state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(data_dir)]}))
        session.add(work)
        session.commit()
        work_id = work.id

    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = settings.reports_dir / f"scan-{scan_id}.json"
    # One valid group, followed by schema-invalid group (missing files)
    report_path.write_text(f"""{{
      "groups": [
        {{"file_hash": "valid1", "file_len": 100, "files": ["{f1}", "{f2}"]}},
        {{"file_hash": "invalid2", "file_len": 100}}
      ]
    }}""", encoding="utf-8")

    ctx = JobContext(engine, SessionLocal, work_id, worker_id=worker_a)
    handler = FclonesScanHandler()

    with patch("app.tasks.handlers.run_scan") as mock_scan:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_scan.return_value = mock_proc

        with pytest.raises(Exception):
            handler.run(work, ctx, settings)

    # Verify partial results were cleaned up
    with SessionLocal() as session:
        groups = session.scalars(select(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_id)).all()
        assert len(groups) == 0, "Partial duplicate groups must be deleted when report item schema is invalid"


def test_terminal_state_cannot_be_revived_by_stale_task_service(tmp_path: Path):
    db_path = tmp_path / "test_terminal_revival.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    service = TaskService(SessionLocal)

    for terminal_status in (JobState.COMPLETED.value, JobState.FAILED.value, JobState.CANCELLED.value):
        with SessionLocal() as session:
            job = WorkJob(kind="fclones-scan", status=terminal_status, state_json="{}")
            session.add(job)
            session.commit()
            jid = job.id

        with pytest.raises(ValueError):
            service.pause_task(jid)

        with pytest.raises(ValueError):
            service.resume_task(jid)

        with pytest.raises(ValueError):
            service.cancel_task(jid)

        with SessionLocal() as session:
            refreshed = session.get(WorkJob, jid)
            assert refreshed.status == terminal_status, f"Status {terminal_status} must not change"
