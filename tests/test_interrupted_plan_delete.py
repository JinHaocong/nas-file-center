from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import Settings
from app.exceptions import StateConflictError
from app.models import BatchPlan, BatchPlanItem, TaskEvent, WorkJob
from app.service import FileCenterService


def _service(tmp_path: Path) -> FileCenterService:
    config = tmp_path / "config"
    data = tmp_path / "data"
    config.mkdir()
    data.mkdir()
    return FileCenterService(
        Settings(
            config_dir=config,
            data_mount=data,
            allowed_roots_raw=str(data),
        )
    )


def _executing_plan(
    service: FileCenterService,
    *,
    job_status: str,
    recovered_after_restart: bool = False,
) -> tuple[int, int]:
    with service.SessionLocal() as session:
        plan = BatchPlan(
            name="Interrupted plan",
            kind="quarantine-bulk-purge",
            status="executing",
            expected_changes=1,
        )
        session.add(plan)
        session.flush()
        session.add(
            BatchPlanItem(
                plan_id=plan.id,
                sequence=1,
                operation="quarantine_purge",
                source_path="/data/example",
                state="validated",
            )
        )
        job = WorkJob(
            kind="batch-plan-execute",
            status=job_status,
            state_json=json.dumps({"plan_id": plan.id}),
        )
        session.add(job)
        session.flush()
        if recovered_after_restart:
            session.add(
                TaskEvent(
                    job_id=job.id,
                    event_type="recovered_after_worker_restart",
                    message="Resumable job requeued after worker restart",
                    level="info",
                )
            )
        session.commit()
        return int(plan.id), int(job.id)


@pytest.mark.parametrize("job_status", ["queued", "paused"])
def test_delete_interrupted_plan_cancels_idle_execution_task(
    tmp_path: Path,
    job_status: str,
) -> None:
    service = _service(tmp_path)
    plan_id, job_id = _executing_plan(
        service,
        job_status=job_status,
        recovered_after_restart=True,
    )

    result = service.delete_plan(plan_id)

    assert result["deleted"] is True
    assert result["id"] == plan_id
    assert result["cancelled_work_job_id"] == job_id
    with service.SessionLocal() as session:
        assert session.get(BatchPlan, plan_id) is None
        job = session.get(WorkJob, job_id)
        assert job is not None
        assert job.status == "cancelled"
        assert job.finished_at is not None


@pytest.mark.parametrize("job_status", ["running", "cancel_requested"])
def test_delete_plan_still_blocks_live_execution_task(
    tmp_path: Path,
    job_status: str,
) -> None:
    service = _service(tmp_path)
    plan_id, job_id = _executing_plan(service, job_status=job_status)

    with pytest.raises(StateConflictError, match="active execution task"):
        service.delete_plan(plan_id)

    with service.SessionLocal() as session:
        assert session.get(BatchPlan, plan_id) is not None
        job = session.get(WorkJob, job_id)
        assert job is not None
        assert job.status == job_status


def test_plan_list_exposes_active_execution_status(tmp_path: Path) -> None:
    service = _service(tmp_path)
    plan_id, job_id = _executing_plan(
        service,
        job_status="queued",
        recovered_after_restart=True,
    )

    listing = service.list_plans()
    row = next(item for item in listing["items"] if item["id"] == plan_id)

    assert row["active_work_job_id"] == job_id
    assert row["active_work_job_status"] == "queued"
    assert row["active_work_job_recovered_after_restart"] is True


def test_fresh_queued_execution_still_blocks_plan_delete(tmp_path: Path) -> None:
    service = _service(tmp_path)
    plan_id, job_id = _executing_plan(
        service,
        job_status="queued",
        recovered_after_restart=False,
    )

    with pytest.raises(StateConflictError, match="active execution task"):
        service.delete_plan(plan_id)

    with service.SessionLocal() as session:
        assert session.get(BatchPlan, plan_id) is not None
        job = session.get(WorkJob, job_id)
        assert job is not None
        assert job.status == "queued"


def test_delete_orphaned_executing_plan_without_active_job(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with service.SessionLocal() as session:
        plan = BatchPlan(
            name="Legacy orphan execution",
            kind="quarantine-bulk-purge",
            status="executing",
            expected_changes=1,
        )
        session.add(plan)
        session.flush()
        session.add(
            BatchPlanItem(
                plan_id=plan.id,
                sequence=1,
                operation="quarantine_purge",
                source_path="/data/legacy-orphan",
                state="executing",
            )
        )
        session.commit()
        plan_id = int(plan.id)

    listing = service.list_plans()
    row = next(item for item in listing["items"] if item["id"] == plan_id)
    assert row["status"] == "executing"
    assert row["active_work_job_id"] is None

    result = service.delete_plan(plan_id)

    assert result == {"deleted": True, "id": plan_id}
    with service.SessionLocal() as session:
        assert session.get(BatchPlan, plan_id) is None
