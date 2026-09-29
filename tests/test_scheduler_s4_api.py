from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.password import hash_password
from app.config import Settings
from app.main import create_app
from app.models import IndexRoot, ScheduleRun, User, WorkJob


@pytest.fixture
def scheduler_api_env(tmp_path: Path):
    config = tmp_path / "config"
    data = tmp_path / "data"
    root = data / "library"
    config.mkdir()
    root.mkdir(parents=True)

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    app = create_app(settings)
    service = app.state.service

    with service.SessionLocal() as session:
        idx = IndexRoot(root=str(root))
        member = User(
            username="member",
            password_hash=hash_password("MemberPassword123!"),
            role="member",
            is_active=True,
        )
        session.add_all([idx, member])
        session.commit()
        root_id = int(idx.id)

    def login(username: str, password: str) -> TestClient:
        client = TestClient(app)
        client.headers["Origin"] = "http://testserver"
        res = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
            headers={"Origin": "http://testserver"},
        )
        assert res.status_code == 200
        return client

    return {
        "app": app,
        "service": service,
        "root_id": root_id,
        "admin": login("admin", "AdminPassword123!"),
        "member": login("member", "MemberPassword123!"),
        "anon": TestClient(app),
    }


def _create_index_schedule(client: TestClient, root_id: int) -> dict:
    res = client.post(
        "/api/schedules",
        json={
            "name": "Night index",
            "description": "S4 API test",
            "enabled": True,
            "target": {"type": "index_root", "root_id": root_id},
            "cron_expression": "*/15 * * * *",
            "timezone": "UTC",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_scheduler_api_rbac_read_write_boundary(scheduler_api_env):
    admin = scheduler_api_env["admin"]
    member = scheduler_api_env["member"]
    anon = scheduler_api_env["anon"]
    root_id = scheduler_api_env["root_id"]

    assert anon.get("/api/schedules").status_code == 401

    created = _create_index_schedule(admin, root_id)
    schedule_id = created["id"]

    # Authenticated members can observe schedules and history.
    assert member.get("/api/schedules").status_code == 200
    assert member.get(f"/api/schedules/{schedule_id}").status_code == 200
    runs = member.get(f"/api/schedules/{schedule_id}/runs")
    assert runs.status_code == 200
    assert runs.json()["items"] == []

    # Write operations remain administrator-only.
    assert (
        member.post(
            "/api/schedules",
            json={
                "name": "blocked",
                "target": {"type": "index_root", "root_id": root_id},
                "cron_expression": "0 * * * *",
                "timezone": "UTC",
            },
        ).status_code
        == 403
    )
    assert (
        member.put(
            f"/api/schedules/{schedule_id}",
            json={"expected_revision": 1, "enabled": False},
        ).status_code
        == 403
    )
    assert member.post(f"/api/schedules/{schedule_id}/run-now").status_code == 403
    assert (
        member.post(
            "/api/schedules/recurrence/preview",
            json={
                "cron_expression": "0 * * * *",
                "timezone": "UTC",
                "count": 3,
            },
        ).status_code
        == 403
    )


def test_scheduler_api_crud_revision_preview_and_manual_run(scheduler_api_env):
    admin = scheduler_api_env["admin"]
    member = scheduler_api_env["member"]
    root_id = scheduler_api_env["root_id"]
    service = scheduler_api_env["service"]

    created = _create_index_schedule(admin, root_id)
    schedule_id = created["id"]
    assert created["revision"] == 1
    assert created["next_scheduled_for_utc"] is not None

    preview = admin.post(
        "/api/schedules/recurrence/preview",
        json={
            "cron_expression": "30 2 * * *",
            "timezone": "America/New_York",
            "count": 4,
        },
    )
    assert preview.status_code == 200, preview.text
    preview_data = preview.json()
    assert preview_data["timezone"] == "America/New_York"
    assert len(preview_data["occurrences"]) == 4

    stale = admin.put(
        f"/api/schedules/{schedule_id}",
        json={"expected_revision": 99, "enabled": False},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "SCHEDULE_REVISION_CONFLICT"

    disabled = admin.put(
        f"/api/schedules/{schedule_id}",
        json={"expected_revision": 1, "enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["enabled"] is False
    assert disabled.json()["revision"] == 2
    assert disabled.json()["next_scheduled_for_utc"] is None

    # Run-now is an explicit admin action and may run a disabled schedule. It
    # uses the normal S2 target dispatcher and keeps cron recurrence disabled.
    run_now = admin.post(f"/api/schedules/{schedule_id}/run-now")
    assert run_now.status_code == 201, run_now.text
    run = run_now.json()
    assert run["status"] == "dispatched"
    assert run["work_job_id"] is not None
    assert run["work_job_kind"] == "index-root"
    assert run["work_job_status"] == "queued"

    detail = member.get(f"/api/schedules/{schedule_id}")
    assert detail.status_code == 200
    assert detail.json()["enabled"] is False
    assert detail.json()["next_scheduled_for_utc"] is None

    history = member.get(f"/api/schedules/{schedule_id}/runs?limit=10")
    assert history.status_code == 200
    rows = history.json()["items"]
    assert len(rows) == 1
    assert rows[0]["id"] == run["id"]
    assert rows[0]["work_job_status"] == "queued"

    with service.SessionLocal() as session:
        assert len(list(session.scalars(select(ScheduleRun)))) == 1
        jobs = list(session.scalars(select(WorkJob)))
        assert len(jobs) == 1
        assert jobs[0].kind == "index-root"


def test_scheduler_api_rejects_destructive_or_invalid_targets(scheduler_api_env):
    admin = scheduler_api_env["admin"]

    destructive = admin.post(
        "/api/schedules",
        json={
            "name": "must fail",
            "target": {"type": "batch_plan_execute", "plan_id": 10},
            "cron_expression": "0 * * * *",
            "timezone": "UTC",
        },
    )
    assert destructive.status_code == 422

    bad_cron = admin.post(
        "/api/schedules/recurrence/preview",
        json={
            "cron_expression": "@daily",
            "timezone": "UTC",
            "count": 3,
        },
    )
    assert bad_cron.status_code == 422

    bad_timezone = admin.post(
        "/api/schedules/recurrence/preview",
        json={
            "cron_expression": "0 * * * *",
            "timezone": "Mars/Phobos",
            "count": 3,
        },
    )
    assert bad_timezone.status_code == 422
