import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, WorkJob, utcnow
from app.service import FileCenterService


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


def test_cancel_paused_plan_never_leaves_plan_executing(tmp_path: Path):
    service, client = _setup(tmp_path)
    with service.SessionLocal() as session:
        plan = BatchPlan(
            name="Test Plan",
            kind="reorganize",
            status="executing",
            expected_changes=2,
            expected_reclaim_bytes=0,
            metadata_json="{}",
            created_at=utcnow(),
        )
        session.add(plan)
        session.flush()

        item1 = BatchPlanItem(plan_id=plan.id, sequence=1, operation="rename", source_path="/data/file1.txt", state="completed")
        item2 = BatchPlanItem(plan_id=plan.id, sequence=2, operation="rename", source_path="/data/file2.txt", state="pending")
        session.add_all([item1, item2])

        job = WorkJob(
            kind="batch-plan-execute",
            status="paused",
            state_json=json.dumps({"plan_id": plan.id}),
            created_at=utcnow(),
        )
        session.add(job)
        session.commit()
        plan_id = plan.id
        job_id = job.id

    res = client.post(f"/api/tasks/{job_id}/cancel")
    assert res.status_code == 200

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan_id)
        assert p.status == "partial", f"Expected 'partial' but got '{p.status}'"


def test_cancel_queued_plan_returns_to_ready(tmp_path: Path):
    service, client = _setup(tmp_path)
    with service.SessionLocal() as session:
        plan = BatchPlan(
            name="Test Plan",
            kind="reorganize",
            status="ready",
            expected_changes=2,
            expected_reclaim_bytes=0,
            metadata_json="{}",
            created_at=utcnow(),
        )
        session.add(plan)
        session.flush()

        item1 = BatchPlanItem(plan_id=plan.id, sequence=1, operation="rename", source_path="/data/file1.txt", state="pending")
        item2 = BatchPlanItem(plan_id=plan.id, sequence=2, operation="rename", source_path="/data/file2.txt", state="pending")
        session.add_all([item1, item2])

        job = WorkJob(
            kind="batch-plan-execute",
            status="queued",
            state_json=json.dumps({"plan_id": plan.id}),
            created_at=utcnow(),
        )
        session.add(job)
        session.commit()
        plan_id = plan.id
        job_id = job.id

    res = client.post(f"/api/tasks/{job_id}/cancel")
    assert res.status_code == 200

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan_id)
        assert p.status == "ready", f"Expected 'ready' but got '{p.status}'"
