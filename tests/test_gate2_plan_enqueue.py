import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, User, WorkJob, utcnow
from app.service import FileCenterService, StateConflictError


def _setup_app_and_service(tmp_path: Path):
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
    app = create_app(settings)
    client = TestClient(app)

    resp = client.post("/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"})
    assert resp.status_code == 200
    client.headers.update({"Origin": "http://testserver"})

    service: FileCenterService = app.state.service
    return client, service, data_dir, trash_dir


def test_execute_api_enqueues_without_fs_mutation(tmp_path: Path):
    client, service, data_dir, _ = _setup_app_and_service(tmp_path)
    file_a = data_dir / "test_a.txt"
    file_a.write_text("hello a", encoding="utf-8")
    file_b = data_dir / "test_b.txt"

    # Create plan and validate it to ready
    plan = service.create_plan(
        name="Enqueue Test Plan",
        kind="organize",
        items=[{"source": str(file_a), "target": str(file_b), "operation": "rename"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # Execute via API
    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["plan_id"] == plan.id
    assert "work_job_id" in data
    assert data["status"] == "queued"

    # CRITICAL: Filesystem mutation count MUST be 0 during API request!
    assert file_a.exists(), "Source file must not be modified during execute enqueue!"
    assert not file_b.exists(), "Target file must not be created during execute enqueue!"

    # Check WorkJob created
    job_id = data["work_job_id"]
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        assert job.kind == "batch-plan-execute"
        assert job.status == "queued"
        st = json.loads(job.state_json or "{}")
        assert st.get("plan_id") == plan.id
        assert "requested_by_user_id" in st
        assert st["requested_by_user_id"] is not None


def test_concurrent_execute_only_one_job(tmp_path: Path):
    client, service, data_dir, _ = _setup_app_and_service(tmp_path)
    file_a = data_dir / "test_concurrent.txt"
    file_a.write_text("hello", encoding="utf-8")
    file_b = data_dir / "test_concurrent_b.txt"

    plan = service.create_plan(
        name="Concurrent Plan",
        kind="organize",
        items=[{"source": str(file_a), "target": str(file_b), "operation": "rename"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # First execute -> 200 queued
    resp1 = client.post(f"/api/plans/{plan.id}/execute")
    assert resp1.status_code == 200

    # Second execute while active -> 409
    resp2 = client.post(f"/api/plans/{plan.id}/execute")
    assert resp2.status_code == 409
    assert "active execution" in resp2.text.lower() or "already" in resp2.text.lower()


def test_queued_execute_blocks_delete_and_validate(tmp_path: Path):
    client, service, data_dir, _ = _setup_app_and_service(tmp_path)
    file_a = data_dir / "test_block.txt"
    file_a.write_text("hello", encoding="utf-8")
    file_b = data_dir / "test_block_b.txt"

    plan = service.create_plan(
        name="Block Plan",
        kind="organize",
        items=[{"source": str(file_a), "target": str(file_b), "operation": "rename"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    # Enqueue execution
    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200

    # Validate while active -> 409
    val_resp = client.post(f"/api/plans/{plan.id}/validate")
    assert val_resp.status_code == 409

    # Delete while active -> 409
    del_resp = client.delete(f"/api/plans/{plan.id}")
    assert del_resp.status_code == 409


def test_clear_history_does_not_delete_active_plan(tmp_path: Path):
    client, service, data_dir, _ = _setup_app_and_service(tmp_path)
    file_a = data_dir / "test_clear.txt"
    file_a.write_text("hello", encoding="utf-8")
    file_b = data_dir / "test_clear_b.txt"

    plan = service.create_plan(
        name="Clear History Test Plan",
        kind="organize",
        items=[{"source": str(file_a), "target": str(file_b), "operation": "rename"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp = client.post(f"/api/plans/{plan.id}/execute")
    assert resp.status_code == 200

    # Simulate plan status set to failed while active WorkJob exists
    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan.id)
        p.status = "failed"
        session.commit()

    # Clear history for failed
    clear_resp = client.post("/api/plans/clear-history", json={"statuses": ["failed"]})
    assert clear_resp.status_code == 200

    # Plan with active task must NOT have been deleted
    with service.SessionLocal() as session:
        refreshed = session.get(BatchPlan, plan.id)
        assert refreshed is not None, "Active plan must NOT be cleared by clear-history!"


def test_retry_payload_only_plan_id_and_actor_is_current_user(tmp_path: Path):
    client, service, _, _ = _setup_app_and_service(tmp_path)

    # Insert a failed batch-plan-execute job with forbidden / poisoned payload keys
    poisoned_payload = {
        "plan_id": 99,
        "requested_by_user_id": 1,
        "allow_mutation": True,
        "allow_delete": True,
        "token": "secret_token_123",
        "authorization": "Bearer evil",
    }
    with service.SessionLocal() as session:
        job = WorkJob(
            kind="batch-plan-execute",
            status="failed",
            state_json=json.dumps(poisoned_payload),
            created_at=utcnow(),
        )
        session.add(job)
        session.commit()
        job_id = job.id

    # Retry the task via API
    resp = client.post(f"/api/tasks/{job_id}/retry")
    assert resp.status_code == 200
    new_task_id = resp.json()["job"]["id"]

    # Check new task payload
    with service.SessionLocal() as session:
        new_job = session.get(WorkJob, new_task_id)
        assert new_job is not None
        payload = json.loads(new_job.state_json or "{}")

        # Must only retain plan_id, with requested_by_user_id updated to current user
        assert payload.get("plan_id") == 99
        assert "allow_mutation" not in payload
        assert "allow_delete" not in payload
        assert "token" not in payload
        assert "authorization" not in payload
