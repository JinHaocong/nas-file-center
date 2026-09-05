from __future__ import annotations

import json
from pathlib import Path
import pytest
from app.config import Settings
from app.models import BatchPlan, WorkJob, utcnow
from app.service import FileCenterService


def _setup_service(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    trash_dir = data_dir / ".nas-file-center-trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = config_dir / "app.db"

    settings = Settings(
        config_dir=config_dir,
        database_path=db_path,
        data_mount=data_dir,
        allowed_roots_raw=str(data_dir),
        quarantine_root=trash_dir,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    svc = FileCenterService(settings)
    return svc, settings, data_dir


def test_retry_rejects_draft_plan(tmp_path: Path):
    svc, settings, data_dir = _setup_service(tmp_path)
    src = data_dir / "f1.txt"
    src.write_text("hello", encoding="utf-8")

    plan = svc.create_plan(
        name="Draft Plan",
        kind="organize",
        items=[{"operation": "touch", "source": str(src)}],
    )
    assert plan.status == "draft"

    # Create a failed job pointing to this draft plan
    now = utcnow()
    with svc.SessionLocal() as session:
        job = WorkJob(
            kind="batch-plan-execute",
            status="failed",
            state_json=json.dumps({"plan_id": plan.id}),
            created_at=now,
        )
        session.add(job)
        session.commit()
        job_id = job.id

    with pytest.raises(ValueError) as exc:
        svc.retry_task(job_id)
    assert "draft" in str(exc.value) or "ready" in str(exc.value)


def test_retry_rejects_frozen_plan(tmp_path: Path):
    svc, settings, data_dir = _setup_service(tmp_path)
    src = data_dir / "f2.txt"
    src.write_text("hello", encoding="utf-8")

    plan = svc.create_plan(
        name="Frozen Plan",
        kind="organize",
        items=[{"operation": "touch", "source": str(src)}],
    )
    svc.freeze_plan(plan.id)
    assert svc.plan_detail(plan.id)["status"] == "frozen"

    now = utcnow()
    with svc.SessionLocal() as session:
        job = WorkJob(
            kind="batch-plan-execute",
            status="failed",
            state_json=json.dumps({"plan_id": plan.id}),
            created_at=now,
        )
        session.add(job)
        session.commit()
        job_id = job.id

    with pytest.raises(ValueError) as exc:
        svc.retry_task(job_id)
    assert "frozen" in str(exc.value) or "ready" in str(exc.value)


def test_retry_rejects_executing_plan(tmp_path: Path):
    svc, settings, data_dir = _setup_service(tmp_path)
    src = data_dir / "f3.txt"
    src.write_text("hello", encoding="utf-8")

    plan = svc.create_plan(
        name="Executing Plan",
        kind="organize",
        items=[{"operation": "touch", "source": str(src)}],
    )
    now = utcnow()
    with svc.SessionLocal() as session:
        db_plan = session.get(BatchPlan, plan.id)
        db_plan.status = "executing"
        job = WorkJob(
            kind="batch-plan-execute",
            status="failed",
            state_json=json.dumps({"plan_id": plan.id}),
            created_at=now,
        )
        session.add(job)
        session.commit()
        job_id = job.id

    with pytest.raises(ValueError) as exc:
        svc.retry_task(job_id)
    assert "executing" in str(exc.value) or "ready" in str(exc.value)


def test_retry_allows_ready_or_partial_plan(tmp_path: Path):
    svc, settings, data_dir = _setup_service(tmp_path)
    src = data_dir / "f4.txt"
    src.write_text("hello", encoding="utf-8")

    plan = svc.create_plan(
        name="Ready Plan",
        kind="organize",
        items=[{"operation": "touch", "source": str(src)}],
    )
    svc.freeze_plan(plan.id)
    svc.validate_plan(plan.id)
    assert svc.plan_detail(plan.id)["status"] == "ready"

    now = utcnow()
    with svc.SessionLocal() as session:
        job = WorkJob(
            kind="batch-plan-execute",
            status="failed",
            state_json=json.dumps({"plan_id": plan.id}),
            created_at=now,
        )
        session.add(job)
        session.commit()
        job_id = job.id

    retry_res = svc.retry_task(job_id)
    assert retry_res["job"]["status"] == "queued"
