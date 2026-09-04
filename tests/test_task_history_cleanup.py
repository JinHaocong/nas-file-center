from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.sessions import create_session
from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.main import create_app
from app.models import AuditEvent, TaskEvent, User, WorkJob
from app.tasks.state_machine import JobState


@pytest.fixture
def cleanup_setup(tmp_path: Path):
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
        "service": app.state.service,
        "app": app,
    }


def test_case_a_delete_completed(cleanup_setup):
    """Case A: DELETE completed -> 200 -> Task removed"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status=JobState.COMPLETED.value)
        session.add(job)
        session.commit()
        job_id = job.id

    resp = client.delete(f"/api/tasks/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"deleted": True, "id": job_id}

    with SessionLocal() as session:
        assert session.get(WorkJob, job_id) is None


def test_case_b_delete_failed(cleanup_setup):
    """Case B: DELETE failed -> 200"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status=JobState.FAILED.value)
        session.add(job)
        session.commit()
        job_id = job.id

    resp = client.delete(f"/api/tasks/{job_id}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True, "id": job_id}

    with SessionLocal() as session:
        assert session.get(WorkJob, job_id) is None


def test_case_c_delete_cancelled(cleanup_setup):
    """Case C: DELETE cancelled -> 200"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status=JobState.CANCELLED.value)
        session.add(job)
        session.commit()
        job_id = job.id

    resp = client.delete(f"/api/tasks/{job_id}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True, "id": job_id}

    with SessionLocal() as session:
        assert session.get(WorkJob, job_id) is None


def test_case_d_delete_active_states_rejected(cleanup_setup):
    """Case D: DELETE queued/running/paused/cancel_requested -> 409 -> Task preserved"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    active_statuses = [
        JobState.QUEUED.value,
        JobState.RUNNING.value,
        JobState.PAUSED.value,
        JobState.CANCEL_REQUESTED.value,
    ]

    for st in active_statuses:
        with SessionLocal() as session:
            job = WorkJob(kind="index-root", status=st)
            session.add(job)
            session.commit()
            job_id = job.id

        resp = client.delete(f"/api/tasks/{job_id}")
        assert resp.status_code == 409, f"Status {st} should return 409"
        assert "Only terminal jobs can be deleted" in resp.json()["detail"]

        with SessionLocal() as session:
            assert session.get(WorkJob, job_id) is not None, f"Job {job_id} ({st}) must be preserved"


def test_case_e_delete_terminal_cascades_task_events(cleanup_setup):
    """Case E: DELETE terminal Task -> corresponding TaskEvents removed"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status=JobState.COMPLETED.value)
        session.add(job)
        session.commit()
        job_id = job.id

        ev1 = TaskEvent(job_id=job_id, event_type="started", message="start", level="info")
        ev2 = TaskEvent(job_id=job_id, event_type="completed", message="done", level="info")
        session.add_all([ev1, ev2])
        session.commit()

    resp = client.delete(f"/api/tasks/{job_id}")
    assert resp.status_code == 200

    with SessionLocal() as session:
        events = list(session.scalars(select(TaskEvent).where(TaskEvent.job_id == job_id)))
        assert len(events) == 0


def test_case_f_delete_terminal_preserves_audit_events(cleanup_setup):
    """Case F: DELETE terminal Task -> AuditEvent preserved"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status=JobState.COMPLETED.value)
        session.add(job)
        session.commit()
        job_id = job.id

        audit = AuditEvent(operation="task_exec", result="success", details_json='{"task": "test"}')
        session.add(audit)
        session.commit()
        audit_id = audit.id

    resp = client.delete(f"/api/tasks/{job_id}")
    assert resp.status_code == 200

    with SessionLocal() as session:
        audit_db = session.get(AuditEvent, audit_id)
        assert audit_db is not None
        assert audit_db.operation == "task_exec"


def test_case_g_clear_history_completed_only(cleanup_setup):
    """Case G: POST clear-history statuses=["completed"] -> only completed removed"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        j_comp = WorkJob(kind="index-root", status=JobState.COMPLETED.value)
        j_fail = WorkJob(kind="index-root", status=JobState.FAILED.value)
        j_canc = WorkJob(kind="index-root", status=JobState.CANCELLED.value)
        j_run = WorkJob(kind="index-root", status=JobState.RUNNING.value)
        session.add_all([j_comp, j_fail, j_canc, j_run])
        session.commit()
        c_id, f_id, ca_id, r_id = j_comp.id, j_fail.id, j_canc.id, j_run.id

    resp = client.post("/api/tasks/clear-history", json={"statuses": ["completed"]})
    assert resp.status_code == 200
    assert resp.json() == {"deleted_count": 1}

    with SessionLocal() as session:
        assert session.get(WorkJob, c_id) is None
        assert session.get(WorkJob, f_id) is not None
        assert session.get(WorkJob, ca_id) is not None
        assert session.get(WorkJob, r_id) is not None


def test_case_h_clear_history_failed_and_cancelled(cleanup_setup):
    """Case H: statuses=["failed","cancelled"] -> failed/cancelled removed -> completed preserved"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        j_comp = WorkJob(kind="index-root", status=JobState.COMPLETED.value)
        j_fail = WorkJob(kind="index-root", status=JobState.FAILED.value)
        j_canc = WorkJob(kind="index-root", status=JobState.CANCELLED.value)
        session.add_all([j_comp, j_fail, j_canc])
        session.commit()
        c_id, f_id, ca_id = j_comp.id, j_fail.id, j_canc.id

    resp = client.post("/api/tasks/clear-history", json={"statuses": ["failed", "cancelled"]})
    assert resp.status_code == 200
    assert resp.json() == {"deleted_count": 2}

    with SessionLocal() as session:
        assert session.get(WorkJob, c_id) is not None
        assert session.get(WorkJob, f_id) is None
        assert session.get(WorkJob, ca_id) is None


def test_case_i_clear_history_statuses_none_clears_all_terminal(cleanup_setup):
    """Case I: statuses=None -> all terminal removed -> active tasks preserved"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        j_comp = WorkJob(kind="index-root", status=JobState.COMPLETED.value)
        j_fail = WorkJob(kind="index-root", status=JobState.FAILED.value)
        j_canc = WorkJob(kind="index-root", status=JobState.CANCELLED.value)
        j_run = WorkJob(kind="index-root", status=JobState.RUNNING.value)
        j_que = WorkJob(kind="index-root", status=JobState.QUEUED.value)
        session.add_all([j_comp, j_fail, j_canc, j_run, j_que])
        session.commit()
        c_id, f_id, ca_id, r_id, q_id = j_comp.id, j_fail.id, j_canc.id, j_run.id, j_que.id

    resp = client.post("/api/tasks/clear-history", json={})
    assert resp.status_code == 200
    assert resp.json() == {"deleted_count": 3}

    with SessionLocal() as session:
        assert session.get(WorkJob, c_id) is None
        assert session.get(WorkJob, f_id) is None
        assert session.get(WorkJob, ca_id) is None
        assert session.get(WorkJob, r_id) is not None
        assert session.get(WorkJob, q_id) is not None


def test_case_j_clear_history_statuses_empty_rejected(cleanup_setup):
    """Case J (CRITICAL): statuses=[] -> 400 -> deleted_count must NOT happen -> all tasks preserved"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        j_comp = WorkJob(kind="index-root", status=JobState.COMPLETED.value)
        j_fail = WorkJob(kind="index-root", status=JobState.FAILED.value)
        j_canc = WorkJob(kind="index-root", status=JobState.CANCELLED.value)
        session.add_all([j_comp, j_fail, j_canc])
        session.commit()
        ids = [j_comp.id, j_fail.id, j_canc.id]

    resp = client.post("/api/tasks/clear-history", json={"statuses": []})
    assert resp.status_code == 400
    assert "At least one terminal status is required" in resp.json()["detail"]

    with SessionLocal() as session:
        for tid in ids:
            assert session.get(WorkJob, tid) is not None


def test_case_k_clear_history_non_terminal_status_rejected(cleanup_setup):
    """Case K: statuses=["running"] -> 400 -> nothing deleted"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        j_run = WorkJob(kind="index-root", status=JobState.RUNNING.value)
        session.add(j_run)
        session.commit()
        r_id = j_run.id

    resp = client.post("/api/tasks/clear-history", json={"statuses": ["running"]})
    assert resp.status_code == 400
    assert "Cannot clear non-terminal status 'running'" in resp.json()["detail"]

    with SessionLocal() as session:
        assert session.get(WorkJob, r_id) is not None


def test_case_l_clear_history_mixed_statuses_rejected_atomically(cleanup_setup):
    """Case L: mixed: ["completed","running"] -> 400 -> atomic no deletion"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        j_comp = WorkJob(kind="index-root", status=JobState.COMPLETED.value)
        j_run = WorkJob(kind="index-root", status=JobState.RUNNING.value)
        session.add_all([j_comp, j_run])
        session.commit()
        c_id, r_id = j_comp.id, j_run.id

    resp = client.post("/api/tasks/clear-history", json={"statuses": ["completed", "running"]})
    assert resp.status_code == 400
    assert "Cannot clear non-terminal status 'running'" in resp.json()["detail"]

    with SessionLocal() as session:
        assert session.get(WorkJob, c_id) is not None
        assert session.get(WorkJob, r_id) is not None


def test_case_m_clear_history_cascades_task_events(cleanup_setup):
    """Case M: clear-history -> TaskEvents cascade removed"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        j_comp = WorkJob(kind="index-root", status=JobState.COMPLETED.value)
        session.add(j_comp)
        session.commit()
        c_id = j_comp.id

        ev = TaskEvent(job_id=c_id, event_type="completed", message="finished", level="info")
        session.add(ev)
        session.commit()

    resp = client.post("/api/tasks/clear-history", json={"statuses": ["completed"]})
    assert resp.status_code == 200
    assert resp.json() == {"deleted_count": 1}

    with SessionLocal() as session:
        events = list(session.scalars(select(TaskEvent).where(TaskEvent.job_id == c_id)))
        assert len(events) == 0


def test_case_n_clear_history_preserves_audit_events(cleanup_setup):
    """Case N: clear-history -> AuditEvents preserved"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        j_comp = WorkJob(kind="index-root", status=JobState.COMPLETED.value)
        audit = AuditEvent(operation="bulk_op", result="success", details_json="{}")
        session.add_all([j_comp, audit])
        session.commit()
        audit_id = audit.id

    resp = client.post("/api/tasks/clear-history", json={"statuses": ["completed"]})
    assert resp.status_code == 200

    with SessionLocal() as session:
        assert session.get(AuditEvent, audit_id) is not None


def test_case_o_retry_child_survives_parent_deletion(cleanup_setup):
    """Case O: retry child surviving parent deletion -> FK integrity preserved -> retry_of becomes null"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        p_fail = WorkJob(kind="index-root", status=JobState.FAILED.value)
        session.add(p_fail)
        session.commit()
        p_id = p_fail.id

        c_retry = WorkJob(kind="index-root", status=JobState.QUEUED.value, retry_of=p_id)
        session.add(c_retry)
        session.commit()
        c_id = c_retry.id

    # Delete failed parent job
    resp = client.delete(f"/api/tasks/{p_id}")
    assert resp.status_code == 200

    with SessionLocal() as session:
        assert session.get(WorkJob, p_id) is None
        child = session.get(WorkJob, c_id)
        assert child is not None
        assert child.retry_of is None  # ON DELETE SET NULL satisfied!


def test_case_p_delete_nonexistent_task(cleanup_setup):
    """Case P: 404 delete nonexistent"""
    client = cleanup_setup["client"]
    resp = client.delete("/api/tasks/999999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Task not found"


def test_case_q_unauthenticated_delete_rejected(cleanup_setup):
    """Case Q: unauthenticated DELETE /tasks/{id} -> 401"""
    app = cleanup_setup["app"]
    anon_client = TestClient(app)
    resp = anon_client.delete("/api/tasks/1")
    assert resp.status_code == 401


def test_case_r_authenticated_mutation_missing_origin_rejected(cleanup_setup):
    """Case R: authenticated mutation missing Origin/Referer -> 403 CSRF"""
    app = cleanup_setup["app"]
    settings = cleanup_setup["settings"]
    SessionLocal = cleanup_setup["SessionLocal"]

    no_origin_client = TestClient(app)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == "admin"))
        _, token = create_session(session, user_id=user.id, max_age_seconds=86400)
        session.commit()
    no_origin_client.cookies.set(settings.session_cookie_name, token)

    # Missing Origin header
    resp = no_origin_client.delete("/api/tasks/1")
    assert resp.status_code == 403
    assert "CSRF validation failed" in resp.json()["detail"]

    resp_clear = no_origin_client.post("/api/tasks/clear-history", json={"statuses": ["completed"]})
    assert resp_clear.status_code == 403
    assert "CSRF validation failed" in resp_clear.json()["detail"]


def test_case_s_authenticated_valid_origin_succeeds(cleanup_setup):
    """Case S: authenticated valid Origin -> normal Backend response"""
    client = cleanup_setup["client"]
    SessionLocal = cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        job = WorkJob(kind="index-root", status=JobState.COMPLETED.value)
        session.add(job)
        session.commit()
        job_id = job.id

    client.headers.update({"Origin": "http://testserver"})
    resp = client.delete(f"/api/tasks/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True
