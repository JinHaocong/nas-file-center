from __future__ import annotations

import json
from pathlib import Path
import pytest
from sqlalchemy import select

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import TaskEvent, WorkJob
from app.tasks.recovery import acquire_worker_ownership
from app.tasks.state_machine import JobState
from app.worker import process_work_job


def _setup_environment(tmp_path: Path, data_dir: Path):
    settings = Settings(config_dir=tmp_path, allowed_roots_raw=str(data_dir))
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)
    worker_id = "worker-test-index-root"
    acquire_worker_ownership(engine, SessionLocal, worker_id=worker_id)
    return settings, engine, SessionLocal, worker_id


def _run_index_root_job(settings, engine, SessionLocal, worker_id, data_dir: Path) -> WorkJob:
    with SessionLocal() as session:
        work = WorkJob(
            kind="index-root",
            status=JobState.QUEUED.value,
            state_json=json.dumps({"root": str(data_dir)}),
        )
        session.add(work)
        session.commit()
        work_id = work.id

    success = process_work_job(
        settings,
        work_id,
        session_factory=SessionLocal,
        engine=engine,
        worker_id=worker_id,
    )
    assert success is True, "process_work_job should return True for clean run"

    with SessionLocal() as session:
        job = session.get(WorkJob, work_id)
        assert job is not None
        return job


def test_index_root_case_a_under_1000_entries(tmp_path: Path):
    """A. <= 1000 entries single batch index."""
    data_dir = tmp_path / "data_a"
    data_dir.mkdir()
    for i in range(350):
        (data_dir / f"f_{i:04d}.txt").touch()

    settings, engine, SessionLocal, worker_id = _setup_environment(tmp_path, data_dir)
    job = _run_index_root_job(settings, engine, SessionLocal, worker_id, data_dir)

    assert job.status == JobState.COMPLETED.value
    assert job.error_code is None
    assert job.error_text is None
    assert job.progress_current == 350
    assert job.progress_total == 350
    assert job.progress_current == job.progress_total


def test_index_root_case_b_over_1000_entries(tmp_path: Path):
    """B. > 1000 entries (2 batches, reproducing and fixing NAS Task #23)."""
    data_dir = tmp_path / "data_b"
    data_dir.mkdir()
    for i in range(1200):
        (data_dir / f"f_{i:04d}.txt").touch()

    settings, engine, SessionLocal, worker_id = _setup_environment(tmp_path, data_dir)
    job = _run_index_root_job(settings, engine, SessionLocal, worker_id, data_dir)

    assert job.status == JobState.COMPLETED.value
    assert job.error_code is None
    assert job.error_text is None
    assert job.progress_current == 1200
    assert job.progress_total == 1200
    assert job.progress_current == job.progress_total


def test_index_root_case_c_over_2000_entries(tmp_path: Path):
    """C. > 2000 entries (3+ batches, verifying multiple successive flush checkpoints)."""
    data_dir = tmp_path / "data_c"
    data_dir.mkdir()
    for i in range(2150):
        (data_dir / f"f_{i:04d}.txt").touch()

    settings, engine, SessionLocal, worker_id = _setup_environment(tmp_path, data_dir)
    job = _run_index_root_job(settings, engine, SessionLocal, worker_id, data_dir)

    assert job.status == JobState.COMPLETED.value
    assert job.error_code is None
    assert job.error_text is None
    assert job.progress_current == 2150
    assert job.progress_total == 2150
    assert job.progress_current == job.progress_total


def test_index_root_case_d_empty_directory(tmp_path: Path):
    """D. Empty directory (0 files, 0 subdirectories)."""
    data_dir = tmp_path / "data_d"
    data_dir.mkdir()

    settings, engine, SessionLocal, worker_id = _setup_environment(tmp_path, data_dir)
    job = _run_index_root_job(settings, engine, SessionLocal, worker_id, data_dir)

    assert job.status == JobState.COMPLETED.value
    assert job.error_code is None
    assert job.error_text is None
    assert job.progress_current == 0
    assert job.progress_total == 0
    assert job.progress_current == job.progress_total


def test_index_root_case_e_reindex_with_existing_rows(tmp_path: Path):
    """E. Re-indexing after existing index rows exist with a new generation."""
    data_dir = tmp_path / "data_e"
    data_dir.mkdir()
    for i in range(400):
        (data_dir / f"orig_{i:04d}.txt").touch()

    settings, engine, SessionLocal, worker_id = _setup_environment(tmp_path, data_dir)

    # 1. Initial index run
    job1 = _run_index_root_job(settings, engine, SessionLocal, worker_id, data_dir)
    assert job1.status == JobState.COMPLETED.value
    assert job1.progress_current == 400
    assert job1.progress_total == 400

    # 2. Add 700 more files (total 1100 files, spanning across 2 batches on next run)
    for i in range(700):
        (data_dir / f"added_{i:04d}.txt").touch()

    # 3. Second index run on the updated directory
    job2 = _run_index_root_job(settings, engine, SessionLocal, worker_id, data_dir)
    assert job2.status == JobState.COMPLETED.value
    assert job2.error_code is None
    assert job2.error_text is None
    assert job2.progress_current == 1100
    assert job2.progress_total == 1100
    assert job2.progress_current == job2.progress_total


def test_index_root_case_f_final_completed_progress_consistency(tmp_path: Path):
    """F. Final completed progress consistency with mixed files and directories."""
    data_dir = tmp_path / "data_f"
    data_dir.mkdir()

    total_dirs = 15
    total_files = 1100
    for d in range(total_dirs):
        sub = data_dir / f"sub_{d:02d}"
        sub.mkdir()
    for f in range(total_files):
        # Place in subdirectories
        sub = data_dir / f"sub_{f % total_dirs:02d}"
        (sub / f"item_{f:04d}.bin").touch()

    settings, engine, SessionLocal, worker_id = _setup_environment(tmp_path, data_dir)
    job = _run_index_root_job(settings, engine, SessionLocal, worker_id, data_dir)

    expected_total = total_dirs + total_files
    assert job.status == JobState.COMPLETED.value
    assert job.error_code is None
    assert job.error_text is None
    assert job.progress_current == expected_total
    assert job.progress_total == expected_total
    assert job.progress_current == job.progress_total

    # Verify checkpoint payload
    checkpoint_data = json.loads(job.checkpoint_json or "{}")
    assert checkpoint_data.get("phase") == "completed"
    res = checkpoint_data.get("result", {})
    assert res.get("files") == total_files
    assert res.get("folders") == total_dirs
