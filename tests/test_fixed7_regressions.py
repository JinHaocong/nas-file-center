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
from app.models import DuplicateFile, DuplicateGroup, ScanJob, TaskEvent, TaskLock, WorkJob, WorkerState, utcnow
from app.scanners.parser import ParsedGroup, parse_fclones_report_iter
from app.tasks.context import JobContext
from app.tasks.handlers import FclonesScanHandler
from app.tasks.recovery import (
    WORKER_LEASE_TIMEOUT_SECONDS,
    acquire_worker_ownership,
    claim_next_job,
    recover_interrupted_jobs,
)
from app.tasks.state_machine import JobLeaseLost
from app.worker import process_work_job


def test_claim_cannot_commit_after_lease_changes(tmp_path: Path):
    db_path = tmp_path / "test_claim_fencing.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    worker_a = "worker-A"
    worker_b = "worker-B"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status="queued", state_json="{}")
        session.add(job)
        session.commit()
        job_id = job.id

    from app.tasks import recovery
    original_assert = recovery.assert_active_worker_lease

    def hook_assert(session, wid, **kwargs):
        res = original_assert(session, wid, **kwargs)
        if wid == worker_a:
            # Another connection attempts to steal lease while A is inside claim
            # If A holds BEGIN IMMEDIATE, this separate connection cannot mutate task_lock
            try:
                with SessionLocal() as s2:
                    s2.execute(text("BEGIN IMMEDIATE"))
                    lock = s2.get(TaskLock, 1)
                    lock.owner = worker_b
                    lock.acquired_at = utcnow()
                    s2.commit()
            except Exception:
                # Expected when A's immediate write lock blocks concurrent writer
                pass
        return res

    with patch("app.tasks.recovery.assert_active_worker_lease", side_effect=hook_assert):
        try:
            claimed = claim_next_job(engine, SessionLocal, worker_id=worker_a)
        except JobLeaseLost:
            claimed = None

    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        j = session.get(WorkJob, job_id)
        if lock.owner == worker_b:
            assert claimed is None, "If B stole ownership, A must not have claimed the job!"
            assert j.status == "queued"
        else:
            assert lock.owner == worker_a
            assert claimed == job_id
            assert j.status == "running"


def test_recovery_cannot_mutate_after_lease_transfer(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_a = "worker-A"
    worker_b = "worker-B"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        scan = ScanJob(name="test-rec-fence", mode="dry-run", roots_json=json.dumps([str(data_dir)]), status="running")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(kind="fclones-scan", status="running", state_json=json.dumps({"scan_job_id": scan_id}))
        session.add(work)
        session.commit()
        work_id = work.id

    # Worker B steals lease right before recovery runs
    with SessionLocal() as s:
        lock = s.get(TaskLock, 1)
        lock.owner = worker_b
        lock.acquired_at = utcnow()
        s.commit()

    # Worker A runs recovery -> must not mutate jobs
    stats = recover_interrupted_jobs(engine, SessionLocal, worker_id=worker_a)
    assert stats["failed_interrupted"] == 0

    with SessionLocal() as session:
        w = session.get(WorkJob, work_id)
        s = session.get(ScanJob, scan_id)
        assert w.status == "running", "Stale worker must not mark WorkJob failed during recovery"
        assert s.status == "running", "Stale worker must not mark ScanJob failed during recovery"
        events = session.scalars(select(TaskEvent).where(TaskEvent.job_id == work_id)).all()
        assert len(events) == 0, "Stale worker must not log TaskEvents during recovery"


def test_stale_worker_unknown_job_type_cannot_mark_failed(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    worker_a = "worker-A"
    worker_b = "worker-B"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        work = WorkJob(kind="non-existent-type", status="running", state_json="{}")
        session.add(work)
        session.commit()
        work_id = work.id

    # Worker B steals lease
    with SessionLocal() as s:
        lock = s.get(TaskLock, 1)
        lock.owner = worker_b
        lock.acquired_at = utcnow()
        s.commit()

    # Worker A executes process_work_job
    res = process_work_job(settings, work_id, session_factory=SessionLocal, engine=engine, worker_id=worker_a)
    assert res is False

    with SessionLocal() as session:
        w = session.get(WorkJob, work_id)
        assert w.status == "running", "Stale worker must not mark unknown job type as failed"
        events = session.scalars(select(TaskEvent).where(TaskEvent.job_id == work_id)).all()
        assert len(events) == 0


def test_job_context_log_is_fenced(tmp_path: Path):
    db_path = tmp_path / "test_log_fence.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    worker_a = "worker-A"
    worker_b = "worker-B"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_a)

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status="running")
        session.add(job)
        session.commit()
        job_id = job.id

    ctx = JobContext(engine, SessionLocal, job_id, worker_id=worker_a)

    # Worker B takes over lease
    with SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        lock.owner = worker_b
        lock.acquired_at = utcnow()
        session.commit()

    # Worker A tries to log an event -> must raise JobLeaseLost and NOT insert event
    with pytest.raises(JobLeaseLost):
        ctx.log(event_type="test_event", message="Should not be logged")

    with SessionLocal() as session:
        events = session.scalars(select(TaskEvent).where(TaskEvent.job_id == job_id)).all()
        assert len(events) == 0


def test_parser_rejects_missing_top_level_comma(tmp_path: Path):
    report_file = tmp_path / "missing_comma.json"
    report_file.write_text('{"header": {} "groups": []}', encoding="utf-8")

    with pytest.raises(ValueError, match="comma"):
        list(parse_fclones_report_iter(report_file))


def test_parser_rejects_leading_group_comma(tmp_path: Path):
    report_file = tmp_path / "leading_comma.json"
    report_file.write_text('{"groups": [ , {"file_hash": "h1", "file_len": 10, "files": ["/a", "/b"]} ]}', encoding="utf-8")

    with pytest.raises(ValueError, match="comma"):
        list(parse_fclones_report_iter(report_file))


def test_parser_rejects_double_group_comma(tmp_path: Path):
    report_file = tmp_path / "double_comma.json"
    report_file.write_text('{"groups": [ {"file_hash": "h1", "file_len": 10, "files": ["/a", "/b"]}, , {"file_hash": "h2", "file_len": 10, "files": ["/c", "/d"]} ]}', encoding="utf-8")

    with pytest.raises(ValueError, match="comma"):
        list(parse_fclones_report_iter(report_file))


def test_parser_rejects_trailing_group_comma(tmp_path: Path):
    report_file = tmp_path / "trailing_comma.json"
    report_file.write_text('{"groups": [ {"file_hash": "h1", "file_len": 10, "files": ["/a", "/b"]}, ]}', encoding="utf-8")

    with pytest.raises(ValueError, match="comma"):
        list(parse_fclones_report_iter(report_file))


def test_parser_rejects_duplicate_groups_key(tmp_path: Path):
    report_file = tmp_path / "dup_groups.json"
    report_file.write_text('{"groups": [], "groups": []}', encoding="utf-8")

    with pytest.raises(ValueError, match="[Dd]uplicate"):
        list(parse_fclones_report_iter(report_file))


def test_invalid_stream_report_fails_job_and_cleans_partial(tmp_path: Path):
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
        scan = ScanJob(name="test-fail-stream", mode="dry-run", roots_json=json.dumps([str(data_dir)]), status="running")
        session.add(scan)
        session.commit()
        scan_id = scan.id

        work = WorkJob(kind="fclones-scan", status="running", state_json=json.dumps({"scan_job_id": scan_id, "roots": [str(data_dir)]}))
        session.add(work)
        session.commit()
        work_id = work.id

    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = settings.reports_dir / f"scan-{scan_id}.json"
    report_path.write_text(f"""{{
      "groups": [
        {{"file_hash": "valid1", "file_len": 100, "files": ["{f1}", "{f2}"]}},
        ,
        {{"file_hash": "valid2", "file_len": 100, "files": ["{f1}", "{f2}"]}}
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

    # Verify that partial results were cleaned up
    with SessionLocal() as session:
        groups = session.scalars(select(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan_id)).all()
        assert len(groups) == 0, "Partial duplicate groups must be deleted when report syntax is invalid"
