from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
from unittest.mock import patch
from app.db import create_engine_and_session, init_db
from app.tasks.recovery import claim_next_job, acquire_worker_ownership
from app.models import WorkJob, ResourcePolicy
from app.tasks.state_machine import JobLeaseLost

FROZEN_OUTSIDE_TIME = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
FROZEN_INSIDE_TIME = datetime(2026, 9, 10, 2, 0, 0, tzinfo=timezone.utc)

def make_task_db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    return engine, SessionLocal

def test_claim_outside_pause_window_holds_resource_job_queued(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-test-1"

    with SessionLocal() as session:
        policy = session.get(ResourcePolicy, 1)
        policy.active_window_enabled = True
        policy.active_window_start = "01:00"
        policy.active_window_end = "03:00"
        policy.active_window_timezone = "UTC"
        policy.outside_window_mode = "pause"
        policy.revision = 2

        job = WorkJob(kind="index-root", status="queued", state_json="{}")
        session.add(job)
        session.commit()
        job_id = job.id

    with patch("app.tasks.recovery.utcnow", return_value=FROZEN_OUTSIDE_TIME):
        acquired = acquire_worker_ownership(engine, SessionLocal, worker_id)
        assert acquired is True

        claimed = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed is None

    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        assert j.status == "queued"

def test_claim_outside_pause_window_allows_mutation_job(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-test-2"
    with SessionLocal() as session:
        policy = session.get(ResourcePolicy, 1)
        policy.active_window_enabled = True
        policy.active_window_start = "01:00"
        policy.active_window_end = "03:00"
        policy.active_window_timezone = "UTC"
        policy.outside_window_mode = "pause"

        j1 = WorkJob(id=101, kind="index-root", status="queued", state_json="{}")
        j2 = WorkJob(id=102, kind="batch-plan-execute", status="queued", state_json="{}")
        session.add_all([j1, j2])
        session.commit()

    with patch("app.tasks.recovery.utcnow", return_value=FROZEN_OUTSIDE_TIME):
        acquire_worker_ownership(engine, SessionLocal, worker_id)
        claimed = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed == 102

def test_claim_rejects_same_revision_fingerprint_drift_and_retries(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-fp-drift"

    with SessionLocal() as session:
        # Phase A initial state: revision=1, job_priority=normal, outside_window_mode=limited
        policy = session.get(ResourcePolicy, 1)
        policy.revision = 1
        policy.job_priority = "normal"
        policy.outside_window_mode = "limited"
        j1 = WorkJob(id=601, kind="index-root", status="queued", state_json="{}")
        session.add(j1)
        session.commit()

    with patch("app.tasks.recovery.utcnow", return_value=FROZEN_INSIDE_TIME):
        acquire_worker_ownership(engine, SessionLocal, worker_id)

        # In attempt 1: Phase B sees same revision 1, but job_priority changed to background
        # This causes mismatch, rollback, and Phase A retry. In attempt 2, DB matches Phase B.
        attempts = 0

        with patch("app.tasks.recovery.get_policy_row_for_check") as mock_check:
            def check_side_effect(sess):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    # Same revision 1, but field drift
                    return ResourcePolicy(
                        id=1, revision=1, scan_threads=2, hash_threads=2, io_limit="normal",
                        job_priority="background", active_window_enabled=False, outside_window_mode="limited"
                    )
                # Attempt 2: consistent row
                return sess.get(ResourcePolicy, 1)

            mock_check.side_effect = check_side_effect
            claimed = claim_next_job(engine, SessionLocal, worker_id)
            assert claimed == 601
            assert attempts >= 2  # Proves retry occurred

def test_claim_repeated_same_revision_drift_exhausts_to_non_resource_only(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-drift-exhaust"

    with SessionLocal() as session:
        j1 = WorkJob(id=601, kind="index-root", status="queued", state_json="{}")
        j2 = WorkJob(id=602, kind="batch-plan-execute", status="queued", state_json="{}")
        session.add_all([j1, j2])
        session.commit()

    with patch("app.tasks.recovery.utcnow", return_value=FROZEN_INSIDE_TIME):
        acquire_worker_ownership(engine, SessionLocal, worker_id)

        # Constant drift on all attempts
        with patch("app.tasks.recovery.get_policy_row_for_check") as mock_check:
            mock_check.side_effect = lambda sess: ResourcePolicy(
                id=1, revision=1, scan_threads=2, hash_threads=2, io_limit="normal",
                job_priority="background", active_window_enabled=False, outside_window_mode="limited"
            )
            # Exhaustion fallback: claims non-resource job only (602)
            claimed = claim_next_job(engine, SessionLocal, worker_id)
            assert claimed == 602

    with SessionLocal() as session:
        # Resource job remains queued
        assert session.get(WorkJob, 601).status == "queued"
        assert session.get(WorkJob, 602).status == "running"

    # Also test exhaustion when ONLY resource job exists: returns None and job remains queued
    with SessionLocal() as session:
        session.delete(session.get(WorkJob, 602))
        session.commit()

    with patch("app.tasks.recovery.utcnow", return_value=FROZEN_INSIDE_TIME):
        with patch("app.tasks.recovery.get_policy_row_for_check") as mock_check:
            mock_check.side_effect = lambda sess: ResourcePolicy(
                id=1, revision=1, scan_threads=2, hash_threads=2, io_limit="normal",
                job_priority="background", active_window_enabled=False, outside_window_mode="limited"
            )
            claimed_none = claim_next_job(engine, SessionLocal, worker_id)
            assert claimed_none is None

    with SessionLocal() as session:
        assert session.get(WorkJob, 601).status == "queued"

def test_claim_lease_fencing_detects_expiry_during_phase_a(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-lease-expire"

    # Lease acquired at T0
    t0 = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
    with patch("app.tasks.recovery.utcnow", return_value=t0):
        acquire_worker_ownership(engine, SessionLocal, worker_id)

    with SessionLocal() as session:
        j = WorkJob(id=650, kind="batch-plan-execute", status="queued", state_json="{}")
        session.add(j)
        session.commit()

    # Time advances by 35s (> 30s timeout) before Phase B runs
    t_expired = t0 + timedelta(seconds=35)
    with patch("app.tasks.recovery.utcnow", return_value=t_expired):
        with pytest.raises(JobLeaseLost):
            claim_next_job(engine, SessionLocal, worker_id)

    with SessionLocal() as session:
        assert session.get(WorkJob, 650).status == "queued"

def test_claim_active_window_boundary_race_evaluates_at_phase_b(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-boundary-race"

    with SessionLocal() as session:
        policy = session.get(ResourcePolicy, 1)
        policy.active_window_enabled = True
        policy.active_window_start = "01:00"
        policy.active_window_end = "03:00"
        policy.active_window_timezone = "UTC"
        policy.outside_window_mode = "pause"

        j1 = WorkJob(id=701, kind="fclones-scan", status="queued", state_json="{}")
        j2 = WorkJob(id=702, kind="batch-plan-execute", status="queued", state_json="{}")
        session.add_all([j1, j2])
        session.commit()

    # Acquire lease inside window: lease_time at 02:59:45 (15 seconds before boundary)
    # This guarantees the Worker lease is unquestionably fresh (age 15s < 30s timeout)
    # when claim occurs exactly at the active-window boundary (03:00:00).
    lease_time = datetime(2026, 9, 10, 2, 59, 45, tzinfo=timezone.utc)
    with patch("app.tasks.recovery.utcnow", return_value=lease_time):
        assert acquire_worker_ownership(engine, SessionLocal, worker_id) is True

    # Phase B runs at exactly 03:00:00 (end of window, exclusive -> outside pause)
    boundary_time = datetime(2026, 9, 10, 3, 0, 0, tzinfo=timezone.utc)
    with patch("app.tasks.recovery.utcnow", return_value=boundary_time):
        claimed = claim_next_job(engine, SessionLocal, worker_id)
        # 701 is held because Phase B evaluates against fresh claim_now boundary_time
        # 702 (mutation) is claimed
        assert claimed == 702

    with SessionLocal() as session:
        assert session.get(WorkJob, 701).status == "queued"

    # Also test: only ID 701 exists -> claim returns None -> 701 remains queued
    with SessionLocal() as session:
        session.delete(session.get(WorkJob, 702))
        session.commit()

    with patch("app.tasks.recovery.utcnow", return_value=boundary_time):
        claimed_only_701 = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed_only_701 is None

    with SessionLocal() as session:
        assert session.get(WorkJob, 701).status == "queued"

def test_claim_with_disabled_window_and_equal_times_admits_resource_job(tmp_path: Path):
    engine, SessionLocal = make_task_db(tmp_path)
    worker_id = "worker-disabled-equal"

    with SessionLocal() as session:
        policy = session.get(ResourcePolicy, 1)
        policy.active_window_enabled = False
        policy.active_window_start = "08:00"
        policy.active_window_end = "08:00"
        policy.active_window_timezone = "UTC"
        policy.outside_window_mode = "pause"
        policy.revision = 2

        job = WorkJob(id=801, kind="index-root", status="queued", state_json="{}")
        session.add(job)
        session.commit()

    with patch("app.tasks.recovery.utcnow", return_value=FROZEN_OUTSIDE_TIME):
        acquired = acquire_worker_ownership(engine, SessionLocal, worker_id)
        assert acquired is True

        claimed = claim_next_job(engine, SessionLocal, worker_id)
        assert claimed == 801

    with SessionLocal() as session:
        j = session.get(WorkJob, 801)
        assert j.status == "running"
