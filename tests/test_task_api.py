from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.sessions import create_session
from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.main import create_app
from app.models import AuditEvent, TaskEvent, User, WorkJob, utcnow
from app.tasks.recovery import acquire_worker_ownership
from app.tasks.state_machine import JobState


from app.tasks.handlers import TaskHandler, register_handler


@register_handler
class ResumableTestHandler(TaskHandler):
    job_type = "resumable-test"
    supports_pause = True
    supports_resume = True
    supports_cancel = True
    supports_retry = True


@pytest.fixture
def test_setup(tmp_path: Path):
    settings = Settings(config_dir=tmp_path)
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(
        engine,
        db_path=settings.database_path,
        backups_dir=settings.backups_dir,
        initial_admin_username="admin",
        initial_admin_password="Password123!",
    )
    app = create_app(settings)
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})

    # Log in as admin
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == "admin"))
        _, token = create_session(session, user_id=user.id, max_age_seconds=86400)
        session.commit()
    client.cookies.set(settings.session_cookie_name, token)

    return {
        "settings": settings,
        "engine": engine,
        "SessionLocal": SessionLocal,
        "client": client,
    }


def test_task_list_and_detail(test_setup):
    client = test_setup["client"]
    SessionLocal = test_setup["SessionLocal"]

    with SessionLocal() as session:
        j1 = WorkJob(
            kind="index-root",
            status=JobState.QUEUED.value,
            progress_current=0,
            progress_total=100,
            state_json='{"root": "/data"}',
        )
        j2 = WorkJob(
            kind="fclones-scan",
            status=JobState.COMPLETED.value,
            progress_current=50,
            progress_total=50,
            state_json='{"roots": ["/data"]}',
        )
        session.add_all([j1, j2])
        session.commit()
        j1_id, j2_id = j1.id, j2.id

    # 1. List tasks
    resp = client.get("/api/tasks?page=1&page_size=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2
    items = data["items"]
    ids = [item["id"] for item in items]
    assert j1_id in ids
    assert j2_id in ids

    # Check structure
    j1_item = next(i for i in items if i["id"] == j1_id)
    assert j1_item["job_type"] == "index-root"
    assert j1_item["status"] == "queued"
    assert j1_item["capabilities"]["supports_pause"] is False
    assert j1_item["capabilities"]["supports_cancel"] is False
    assert j1_item["capabilities"]["supports_retry"] is True
    assert j1_item["progress"]["current"] == 0
    assert j1_item["progress"]["total"] == 100
    assert j1_item["progress"]["percent"] == 0.0

    # 2. Filter by status
    resp_filtered = client.get("/api/tasks?status=completed")
    assert resp_filtered.status_code == 200
    data_filtered = resp_filtered.json()
    assert all(i["status"] == "completed" for i in data_filtered["items"])

    # 3. Get task detail
    resp_detail = client.get(f"/api/tasks/{j1_id}")
    assert resp_detail.status_code == 200
    detail = resp_detail.json()
    assert detail["id"] == j1_id
    assert detail["job_type"] == "index-root"
    assert "checkpoint" in detail


def test_task_pause_and_resume_api(test_setup):
    client = test_setup["client"]
    SessionLocal = test_setup["SessionLocal"]

    with SessionLocal() as session:
        # Queued job
        j_queued = WorkJob(kind="resumable-test", status=JobState.QUEUED.value)
        # Running job
        j_running = WorkJob(kind="resumable-test", status=JobState.RUNNING.value)
        # Completed job
        j_completed = WorkJob(kind="resumable-test", status=JobState.COMPLETED.value)
        session.add_all([j_queued, j_running, j_completed])
        session.commit()
        q_id, r_id, c_id = j_queued.id, j_running.id, j_completed.id

    # 1. Pause queued job -> immediately paused
    res_pause_q = client.post(f"/api/tasks/{q_id}/pause")
    assert res_pause_q.status_code == 200
    with SessionLocal() as session:
        assert session.get(WorkJob, q_id).status == JobState.PAUSED.value

    # 2. Pause running job -> sets pause_requested_at
    res_pause_r = client.post(f"/api/tasks/{r_id}/pause")
    assert res_pause_r.status_code == 200
    with SessionLocal() as session:
        j = session.get(WorkJob, r_id)
        assert j.status == JobState.RUNNING.value
        assert j.pause_requested_at is not None

    # 3. Pause terminal job -> 409 Conflict
    res_pause_c = client.post(f"/api/tasks/{c_id}/pause")
    assert res_pause_c.status_code == 409

    # 4. Resume paused job -> moves back to queued
    res_resume = client.post(f"/api/tasks/{q_id}/resume")
    assert res_resume.status_code == 200
    with SessionLocal() as session:
        j = session.get(WorkJob, q_id)
        assert j.status == JobState.QUEUED.value
        assert j.pause_requested_at is None

    # 5. Resume non-paused job -> 409 Conflict
    res_resume_invalid = client.post(f"/api/tasks/{r_id}/resume")
    assert res_resume_invalid.status_code == 409


def test_task_cancel_api(test_setup):
    client = test_setup["client"]
    SessionLocal = test_setup["SessionLocal"]

    with SessionLocal() as session:
        j_queued = WorkJob(kind="resumable-test", status=JobState.QUEUED.value)
        j_running = WorkJob(kind="resumable-test", status=JobState.RUNNING.value)
        j_completed = WorkJob(kind="resumable-test", status=JobState.COMPLETED.value)
        session.add_all([j_queued, j_running, j_completed])
        session.commit()
        q_id, r_id, c_id = j_queued.id, j_running.id, j_completed.id

    # 1. Cancel queued -> immediately cancelled
    res_q = client.post(f"/api/tasks/{q_id}/cancel")
    assert res_q.status_code == 200
    with SessionLocal() as session:
        j = session.get(WorkJob, q_id)
        assert j.status == JobState.CANCELLED.value
        assert j.finished_at is not None

    # 2. Cancel running -> cancel_requested
    res_r = client.post(f"/api/tasks/{r_id}/cancel")
    assert res_r.status_code == 200
    with SessionLocal() as session:
        j = session.get(WorkJob, r_id)
        assert j.status == JobState.CANCEL_REQUESTED.value
        assert j.cancel_requested_at is not None

    # 3. Cancel terminal -> 409
    res_c = client.post(f"/api/tasks/{c_id}/cancel")
    assert res_c.status_code == 409


def test_task_retry_api(test_setup):
    client = test_setup["client"]
    SessionLocal = test_setup["SessionLocal"]

    with SessionLocal() as session:
        j_failed = WorkJob(
            kind="index-root",
            status=JobState.FAILED.value,
            state_json='{"root": "/data"}',
            progress_current=5,
            progress_total=10,
            error_code="TEST_ERROR",
            error_text="Something went wrong",
        )
        j_completed = WorkJob(kind="index-root", status=JobState.COMPLETED.value)
        session.add_all([j_failed, j_completed])
        session.commit()
        f_id, c_id = j_failed.id, j_completed.id

    # 1. Retry failed job -> creates new queued job
    resp = client.post(f"/api/tasks/{f_id}/retry")
    assert resp.status_code == 200
    data = resp.json()
    new_job = data["job"]
    assert new_job["id"] != f_id
    assert new_job["status"] == "queued"
    assert new_job["retry_of"] == f_id
    assert new_job["progress"]["current"] == 0
    assert new_job["error"] is None

    # Verify original job remained failed
    with SessionLocal() as session:
        orig = session.get(WorkJob, f_id)
        assert orig.status == JobState.FAILED.value

    # 2. Retry non-failed job -> 409
    resp_invalid = client.post(f"/api/tasks/{c_id}/retry")
    assert resp_invalid.status_code == 409


def test_task_cleanup_and_logs(test_setup):
    client = test_setup["client"]
    SessionLocal = test_setup["SessionLocal"]

    with SessionLocal() as session:
        j_comp = WorkJob(kind="index-root", status=JobState.COMPLETED.value)
        j_run = WorkJob(kind="index-root", status=JobState.RUNNING.value)
        session.add_all([j_comp, j_run])
        session.commit()
        c_id, r_id = j_comp.id, j_run.id

        # Add task event and audit event
        ev = TaskEvent(job_id=c_id, event_type="test", message="Test event", level="info")
        audit = AuditEvent(operation="test_op", result="success", details_json="{}")
        session.add_all([ev, audit])
        session.commit()
        audit_id = audit.id

    # 1. Get task logs
    resp_logs = client.get(f"/api/tasks/{c_id}/logs")
    assert resp_logs.status_code == 200
    logs = resp_logs.json()
    assert logs["total"] >= 1
    assert logs["items"][0]["event_type"] == "test"

    # 2. Delete running job -> 409
    res_del_run = client.delete(f"/api/tasks/{r_id}")
    assert res_del_run.status_code == 409

    # 3. Delete terminal job -> 200, cascades task_events, preserves audit_events
    res_del_comp = client.delete(f"/api/tasks/{c_id}")
    assert res_del_comp.status_code == 200

    with SessionLocal() as session:
        assert session.get(WorkJob, c_id) is None
        events = list(session.scalars(select(TaskEvent).where(TaskEvent.job_id == c_id)))
        assert len(events) == 0
        # Audit event preserved!
        assert session.get(AuditEvent, audit_id) is not None


def test_worker_status_api(test_setup):
    client = test_setup["client"]
    engine = test_setup["engine"]
    SessionLocal = test_setup["SessionLocal"]

    acquire_worker_ownership(engine, SessionLocal, worker_id="worker-test-api")

    resp = client.get("/api/tasks/worker")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("online", "stale", "offline")
    assert data["worker_id"] == "worker-test-api"
    assert "heartbeat_at" in data
    assert "heartbeat_age_seconds" in data
