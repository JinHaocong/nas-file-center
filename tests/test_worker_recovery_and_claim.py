from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import threading
import time
import pytest
from sqlalchemy import select

from app.db import create_engine_and_session, init_db
from app.models import BatchPlan, BatchPlanItem, WorkJob, WorkerState, TaskLock, TaskEvent, utcnow
from app.tasks.recovery import (
    acquire_worker_ownership,
    recover_interrupted_jobs,
    claim_next_job,
    compute_worker_status,
    WORKER_ONLINE_THRESHOLD_SECONDS,
    WORKER_STALE_THRESHOLD_SECONDS,
)
from app.tasks.state_machine import JobState
from app.tasks.context import JobContext
from app.tasks.handlers import get_handler


def test_worker_status_computation():
    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Online (age <= 30s)
    hb_online = now - timedelta(seconds=10)
    status, age = compute_worker_status(hb_online, current_time=now)
    assert status == "online"
    assert age == pytest.approx(10.0, rel=0.1)

    # 2. Stale (30s < age <= 90s)
    hb_stale = now - timedelta(seconds=45)
    status, age = compute_worker_status(hb_stale, current_time=now)
    assert status == "stale"
    assert age == pytest.approx(45.0, rel=0.1)

    # 3. Offline (age > 90s or None)
    hb_offline = now - timedelta(seconds=120)
    status, age = compute_worker_status(hb_offline, current_time=now)
    assert status == "offline"
    assert age == pytest.approx(120.0, rel=0.1)

    status_none, age_none = compute_worker_status(None, current_time=now)
    assert status_none == "offline"
    assert age_none is None


from app.tasks.handlers import TaskHandler, register_handler


@register_handler
class ResumableRecoveryHandler(TaskHandler):
    job_type = "resumable-recovery-test"
    supports_resume = True


def test_double_claim_protection(tmp_path: Path):
    db_path = tmp_path / "test_claim.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    acquire_worker_ownership(engine, SessionLocal, worker_id="worker-1")

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status=JobState.QUEUED.value)
        session.add(job)
        session.commit()
        job_id = job.id

    results = []

    def try_claim(worker_name: str):
        claimed_id = claim_next_job(engine, SessionLocal, worker_id=worker_name)
        if claimed_id is not None:
            results.append((worker_name, claimed_id))

    # Two concurrent threads of worker-1 attempting to claim the single queued job
    t1 = threading.Thread(target=try_claim, args=("worker-1",))
    t2 = threading.Thread(target=try_claim, args=("worker-1",))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one thread must have succeeded
    assert len(results) == 1
    winner_worker, claimed_id = results[0]
    assert claimed_id == job_id

    with SessionLocal() as session:
        j = session.get(WorkJob, job_id)
        assert j.status == JobState.RUNNING.value


def test_worker_restart_recovery_rules(tmp_path: Path):
    db_path = tmp_path / "test_recovery.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    with SessionLocal() as session:
        # 1. Resumable running job with checkpoint -> should be requeued
        j_resumable = WorkJob(
            kind="resumable-recovery-test",
            status=JobState.RUNNING.value,
            checkpoint_json='{"schema_version": 1, "cursor": 10}',
        )
        # 2. Non-resumable running job -> should be failed with WORKER_INTERRUPTED
        j_non_resumable = WorkJob(
            kind="fclones-scan",
            status=JobState.RUNNING.value,
            state_json='{"roots": ["/test"]}',
        )
        # 3. Cancel requested running job -> should be cancelled
        j_cancel_req = WorkJob(
            kind="index-root",
            status=JobState.CANCEL_REQUESTED.value,
            cancel_requested_at=utcnow(),
        )
        # 4. Paused job -> should remain paused
        j_paused = WorkJob(
            kind="index-root",
            status=JobState.PAUSED.value,
            checkpoint_json='{"schema_version": 1}',
        )
        # 5. Queued job -> should remain queued
        j_queued = WorkJob(
            kind="index-root",
            status=JobState.QUEUED.value,
        )
        # 6. Completed job -> should remain completed
        j_completed = WorkJob(
            kind="index-root",
            status=JobState.COMPLETED.value,
        )

        session.add_all([j_resumable, j_non_resumable, j_cancel_req, j_paused, j_queued, j_completed])
        session.commit()
        ids = {
            "resumable": j_resumable.id,
            "non_resumable": j_non_resumable.id,
            "cancel_req": j_cancel_req.id,
            "paused": j_paused.id,
            "queued": j_queued.id,
            "completed": j_completed.id,
        }

    # Worker acquires exclusive ownership before recovery
    assert acquire_worker_ownership(engine, SessionLocal, worker_id="worker-test") is True

    # Run recovery
    stats = recover_interrupted_jobs(engine, SessionLocal, worker_id="worker-test")
    assert stats["recovered_requeued"] == 1
    assert stats["failed_interrupted"] == 1
    assert stats["cancelled"] == 1

    with SessionLocal() as session:
        resumable = session.get(WorkJob, ids["resumable"])
        assert resumable.status == JobState.QUEUED.value

        non_resumable = session.get(WorkJob, ids["non_resumable"])
        assert non_resumable.status == JobState.FAILED.value
        assert non_resumable.error_code == "WORKER_INTERRUPTED"
        assert non_resumable.finished_at is not None

        cancel_req = session.get(WorkJob, ids["cancel_req"])
        assert cancel_req.status == JobState.CANCELLED.value
        assert cancel_req.finished_at is not None

        paused = session.get(WorkJob, ids["paused"])
        assert paused.status == JobState.PAUSED.value

        queued = session.get(WorkJob, ids["queued"])
        assert queued.status == JobState.QUEUED.value

        completed = session.get(WorkJob, ids["completed"])
        assert completed.status == JobState.COMPLETED.value



def _make_executing_plan_with_job(
    SessionLocal,
    *,
    job_status: str,
    checkpoint_json: str | None = None,
):
    with SessionLocal() as session:
        plan = BatchPlan(
            name="Restart recovery plan",
            kind="organize",
            status="executing",
            expected_changes=1,
        )
        session.add(plan)
        session.flush()
        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="move",
            source_path="/data/source",
            target_path="/data/target",
            state="validated",
        )
        session.add(item)
        job = WorkJob(
            kind="batch-plan-execute",
            status=job_status,
            state_json=json.dumps({"plan_id": plan.id}),
            checkpoint_json=checkpoint_json,
        )
        session.add(job)
        session.commit()
        return plan.id, job.id


def test_worker_restart_failure_synchronizes_batch_plan(tmp_path: Path):
    db_path = tmp_path / "test_plan_recovery.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    plan_id, job_id = _make_executing_plan_with_job(
        SessionLocal,
        job_status=JobState.RUNNING.value,
        checkpoint_json=None,
    )

    assert acquire_worker_ownership(engine, SessionLocal, worker_id="worker-plan-recovery") is True
    stats = recover_interrupted_jobs(
        engine,
        SessionLocal,
        worker_id="worker-plan-recovery",
    )

    assert stats["failed_interrupted"] == 1
    with SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        plan = session.get(BatchPlan, plan_id)
        assert job is not None
        assert plan is not None
        assert job.status == JobState.FAILED.value
        assert job.error_code == "WORKER_INTERRUPTED"
        assert plan.status == "failed"


def test_worker_restart_repairs_historical_orphaned_executing_plan(tmp_path: Path):
    db_path = tmp_path / "test_orphan_plan_recovery.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    plan_id, job_id = _make_executing_plan_with_job(
        SessionLocal,
        job_status=JobState.FAILED.value,
    )
    with SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        job.error_code = "WORKER_INTERRUPTED"
        job.error_text = "Worker restarted while job was running"
        job.finished_at = utcnow()
        session.commit()

    assert acquire_worker_ownership(engine, SessionLocal, worker_id="worker-orphan-recovery") is True
    stats = recover_interrupted_jobs(
        engine,
        SessionLocal,
        worker_id="worker-orphan-recovery",
    )

    assert stats["repaired_orphan_plans"] == 1
    with SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        assert plan.status == "failed"


def test_worker_restart_does_not_repair_plan_with_active_execution_job(tmp_path: Path):
    db_path = tmp_path / "test_active_plan_recovery.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)

    plan_id, _ = _make_executing_plan_with_job(
        SessionLocal,
        job_status=JobState.QUEUED.value,
        checkpoint_json='{"schema_version": 1}',
    )

    assert acquire_worker_ownership(engine, SessionLocal, worker_id="worker-active-plan") is True
    stats = recover_interrupted_jobs(
        engine,
        SessionLocal,
        worker_id="worker-active-plan",
    )

    assert stats["repaired_orphan_plans"] == 0
    with SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        assert plan.status == "executing"


def test_batch_execution_restart_checkpoint_is_durable_before_purge_replay(
    tmp_path: Path, monkeypatch,
):
    """Crash at the first checkpoint: restart requeues frozen plan, not a purge.

    This is deliberately a synthetic local DB/payload, never a live NAS path.
    The real batch handler must publish a versioned checkpoint *before* any
    potentially irreversible item recovery or purge execution.
    """
    from app.models import QuarantineEntry

    db_path = tmp_path / "checkpoint_restart.db"
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path)
    qroot = tmp_path / ".nas-file-center-trash"
    qroot.mkdir()
    payload = qroot / "synthetic-interrupted.bin"
    payload.write_bytes(b"NEVER DELETE DURING CHECKPOINT")
    baseline = payload.read_bytes()

    with SessionLocal() as session:
        plan = BatchPlan(
            name="Synthetic restartable purge plan",
            kind="quarantine-bulk-purge",
            status="executing",
            expected_changes=1,
        )
        session.add(plan)
        session.flush()
        item = BatchPlanItem(
            plan_id=plan.id,
            sequence=1,
            operation="quarantine_purge",
            source_path=str(payload),
            state="executing",
        )
        entry = QuarantineEntry(
            original_path=str(tmp_path / "never-touch-original.bin"),
            quarantine_path=str(payload),
            state="purging",
            tx_phase="purging",
            transaction_mode="transactional",
            quarantined_at=utcnow(),
        )
        session.add_all([item, entry])
        job = WorkJob(
            kind="batch-plan-execute",
            status=JobState.RUNNING.value,
            state_json=json.dumps({"plan_id": plan.id}),
            checkpoint_json=None,
        )
        session.add(job)
        session.commit()
        plan_id, job_id, item_id, entry_id = plan.id, job.id, item.id, entry.id

    handler = get_handler("batch-plan-execute")
    assert handler is not None and handler.supports_resume
    assert acquire_worker_ownership(
        engine, SessionLocal, worker_id="worker-before-crash",
    )
    context = JobContext(engine, SessionLocal, job_id, worker_id="worker-before-crash")
    persist_checkpoint = context.checkpoint
    observed = []

    def stop_at_first_durable_checkpoint(**kwargs):
        persist_checkpoint(**kwargs)
        observed.append(kwargs.get("checkpoint_data"))
        # Simulate a terminated worker *after* the SQLite transaction commits,
        # but before any filesystem-affecting reconcile/execute step.
        raise RuntimeError("simulated Docker worker termination")

    monkeypatch.setattr(context, "checkpoint", stop_at_first_durable_checkpoint)
    with SessionLocal() as session:
        running_job = session.get(WorkJob, job_id)
        with pytest.raises(RuntimeError, match="simulated Docker worker termination"):
            handler.run(running_job, context, None)

    assert observed == [{
        "schema_version": 1,
        "plan_id": plan_id,
        "resume_mode": "reconcile_executing_items",
    }]
    with SessionLocal() as session:
        stored = session.get(WorkJob, job_id)
        assert json.loads(stored.checkpoint_json) == observed[0]
        assert stored.status == JobState.RUNNING.value
        assert session.get(QuarantineEntry, entry_id).state == "purging"
        assert session.get(BatchPlanItem, item_id).state == "executing"
    assert payload.read_bytes() == baseline

    # On restart, existing lease-fenced policy now recognizes the
    # checkpoint and requeues the original job; it does not mutate data.
    stats = recover_interrupted_jobs(
        engine, SessionLocal, worker_id="worker-before-crash",
    )
    assert stats["recovered_requeued"] == 1
    assert stats["failed_interrupted"] == 0
    with SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job.status == JobState.QUEUED.value
        assert job.error_code is None
        assert session.get(BatchPlan, plan_id).status == "executing"
        assert session.get(BatchPlanItem, item_id).state == "executing"
        entry = session.get(QuarantineEntry, entry_id)
        assert entry.state == "purging"
        assert entry.tx_phase == "purging"
    assert payload.read_bytes() == baseline


def test_batch_plan_durable_checkpoint_must_precede_item_mutations():
    """Pin restart eligibility at initial/boundary checkpoints, not on replay."""
    from pathlib import Path
    source = Path("app/tasks/handlers_base.py").read_text(encoding="utf-8")
    start = source.index('        restart_checkpoint = {')
    reconciliation = source.index('        # 1. Announce start & reconcile interrupted items', start)
    assert source.index(
        '        context.checkpoint(checkpoint_data=restart_checkpoint)', start,
    ) < reconciliation
    boundary = source.index('            # Checkpoint at item boundary', reconciliation)
    phase1 = source.index('            # --- PHASE 1: DB INTENT ---', boundary)
    assert "checkpoint_data=restart_checkpoint" in source[boundary:phase1]
    assert "schema_version" in source[start:reconciliation]
    assert "plan_id" in source[start:reconciliation]
