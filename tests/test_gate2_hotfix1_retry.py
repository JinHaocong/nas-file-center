import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, WorkJob, utcnow
from app.service import FileCenterService, StateConflictError


def _setup(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = config_dir / "app.db"
    settings = Settings(
        config_dir=config_dir,
        database_path=db_path,
        reports_dir=tmp_path / "reports",
        backups_dir=tmp_path / "backups",
        logs_dir=tmp_path / "logs",
        fclones_home=tmp_path / "fclones",
        secret_key="test-secret",
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    app = create_app(settings)
    service = app.state.service
    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"})
    assert resp.status_code == 200
    client.headers.update({"Origin": "http://testserver"})
    return service, client


def test_retry_rejects_when_same_plan_has_active_execution(tmp_path: Path):
    service, client = _setup(tmp_path)
    with service.SessionLocal() as session:
        plan = BatchPlan(
            name="Test Plan",
            kind="reorganize",
            status="partial",
            expected_changes=1,
            expected_reclaim_bytes=0,
            metadata_json="{}",
            created_at=utcnow(),
        )
        session.add(plan)
        session.flush()

        job1 = WorkJob(
            kind="batch-plan-execute",
            status="failed",
            state_json=json.dumps({"plan_id": plan.id}),
            created_at=utcnow(),
        )
        job2 = WorkJob(
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps({"plan_id": plan.id}),
            created_at=utcnow(),
        )
        session.add_all([job1, job2])
        session.commit()
        job1_id = job1.id
        job2_id = job2.id

    # Retrying job1 while job2 is running must be rejected with 409
    res = client.post(f"/api/tasks/{job1_id}/retry")
    assert res.status_code == 409
    assert f"Plan #{plan.id} already has an active execution task #{job2_id}" in res.text or "already has an active execution task" in res.text


def test_retry_rejects_completed_plan(tmp_path: Path):
    service, client = _setup(tmp_path)
    with service.SessionLocal() as session:
        plan = BatchPlan(
            name="Test Plan",
            kind="reorganize",
            status="completed",
            expected_changes=1,
            expected_reclaim_bytes=0,
            metadata_json="{}",
            created_at=utcnow(),
        )
        session.add(plan)
        session.flush()

        job1 = WorkJob(
            kind="batch-plan-execute",
            status="failed",
            state_json=json.dumps({"plan_id": plan.id}),
            created_at=utcnow(),
        )
        session.add(job1)
        session.commit()
        job1_id = job1.id

    res = client.post(f"/api/tasks/{job1_id}/retry")
    assert res.status_code == 409
    assert "completed" in res.text


def test_retry_rejects_deleted_plan(tmp_path: Path):
    service, client = _setup(tmp_path)
    with service.SessionLocal() as session:
        job1 = WorkJob(
            kind="batch-plan-execute",
            status="failed",
            state_json=json.dumps({"plan_id": 999999}),
            created_at=utcnow(),
        )
        session.add(job1)
        session.commit()
        job1_id = job1.id

    res = client.post(f"/api/tasks/{job1_id}/retry")
    assert res.status_code in (404, 409)


def test_retry_succeeds_when_plan_is_ready_or_partial_and_no_active_jobs(tmp_path: Path):
    service, client = _setup(tmp_path)
    with service.SessionLocal() as session:
        plan = BatchPlan(
            name="Test Plan",
            kind="reorganize",
            status="partial",
            expected_changes=1,
            expected_reclaim_bytes=0,
            metadata_json="{}",
            created_at=utcnow(),
        )
        session.add(plan)
        session.flush()

        job1 = WorkJob(
            kind="batch-plan-execute",
            status="failed",
            state_json=json.dumps({"plan_id": plan.id}),
            created_at=utcnow(),
        )
        session.add(job1)
        session.commit()
        job1_id = job1.id

    res = client.post(f"/api/tasks/{job1_id}/retry")
    assert res.status_code == 200
    data = res.json()
    assert data["job"]["job_type"] == "batch-plan-execute"
    assert data["job"]["status"] == "queued"
    assert data["retry_of"] == job1_id
