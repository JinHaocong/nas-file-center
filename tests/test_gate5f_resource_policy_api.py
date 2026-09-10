from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.models import User
from app.auth.password import hash_password
from app.service import FileCenterService

def make_api_client(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)
    with service.SessionLocal() as session:
        user = User(
            username="staff_user",
            password_hash=hash_password("StaffPassword123!"),
            role="user",
            is_active=True,
        )
        session.add(user)
        session.commit()
    app = create_app(settings)
    client = TestClient(app)
    return client, service, settings

def test_get_resource_policy_auth_matrix(tmp_path: Path):
    client, service, settings = make_api_client(tmp_path)

    # 1. Unauthenticated -> 401
    resp = client.get("/api/settings/resource-policy")
    assert resp.status_code == 401

    # 2. Normal user session -> 403
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "staff_user", "password": "StaffPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login_resp.status_code == 200
    user_get = client.get("/api/settings/resource-policy")
    assert user_get.status_code == 403

    # 3. Admin user session -> 200
    admin_login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert admin_login.status_code == 200
    admin_get = client.get("/api/settings/resource-policy")
    assert admin_get.status_code == 200
    data = admin_get.json()
    assert data["scan_threads"] == 2
    assert data["hash_threads"] == 2
    assert data["revision"] == 1
    assert data["effective_now"]["profile"] == "full"

def test_put_resource_policy_updates_and_increments_revision(tmp_path: Path):
    client, service, settings = make_api_client(tmp_path)
    client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    update_payload = {
        "scan_threads": 4,
        "hash_threads": 4,
        "io_limit": "low",
        "job_priority": "background",
        "active_window_enabled": True,
        "active_window_start": "01:00",
        "active_window_end": "07:00",
        "active_window_timezone": "UTC",
        "outside_window_mode": "pause",
    }
    resp = client.put(
        "/api/settings/resource-policy",
        json=update_payload,
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["scan_threads"] == 4
    assert data["io_limit"] == "low"
    assert data["revision"] == 2

def test_put_resource_policy_semantic_validation_matrix_returns_422(tmp_path: Path):
    client, service, settings = make_api_client(tmp_path)
    client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )

    PERSISTED_POLICY_KEYS = (
        "id",
        "scan_threads",
        "hash_threads",
        "io_limit",
        "job_priority",
        "active_window_enabled",
        "active_window_start",
        "active_window_end",
        "active_window_timezone",
        "outside_window_mode",
        "revision",
        "updated_at",
    )

    def persisted_projection(payload: dict) -> dict:
        return {key: payload[key] for key in PERSISTED_POLICY_KEYS}

    before_resp = client.get("/api/settings/resource-policy")
    assert before_resp.status_code == 200
    before = persisted_projection(before_resp.json())

    base_valid = {
        "scan_threads": 2,
        "hash_threads": 2,
        "io_limit": "normal",
        "job_priority": "normal",
        "active_window_enabled": True,
        "active_window_start": "01:00",
        "active_window_end": "07:00",
        "active_window_timezone": "UTC",
        "outside_window_mode": "limited",
    }

    invalid_cases = [
        ("scan_threads_zero", {**base_valid, "scan_threads": 0}),
        ("scan_threads_bool", {**base_valid, "scan_threads": True}),
        ("hash_threads_too_large", {**base_valid, "hash_threads": 33}),
        ("io_limit_invalid", {**base_valid, "io_limit": "superfast"}),
        ("job_priority_invalid", {**base_valid, "job_priority": "urgent"}),
        ("outside_window_mode_invalid", {**base_valid, "outside_window_mode": "halt"}),
        ("window_start_equals_end", {**base_valid, "active_window_start": "08:00", "active_window_end": "08:00"}),
        ("timezone_invalid", {**base_valid, "active_window_timezone": "Invalid/Zone"}),
        ("extra_field_forbidden", {**base_valid, "unexpected_field": 123}),
    ]

    for name, payload in invalid_cases:
        resp = client.put(
            "/api/settings/resource-policy",
            json=payload,
            headers={"Origin": "http://testserver"},
        )
        assert resp.status_code == 422, f"Failed on case {name}: {resp.text}"

        after_resp = client.get("/api/settings/resource-policy")
        assert after_resp.status_code == 200
        after = persisted_projection(after_resp.json())
        assert after == before, f"Case {name} mutated persisted policy state!"

def test_put_resource_policy_disabled_window_allows_equal_times(tmp_path: Path):
    client, service, settings = make_api_client(tmp_path)
    client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    payload = {
        "scan_threads": 2,
        "hash_threads": 2,
        "io_limit": "normal",
        "job_priority": "normal",
        "active_window_enabled": False,
        "active_window_start": "08:00",
        "active_window_end": "08:00",
        "active_window_timezone": "UTC",
        "outside_window_mode": "pause",
    }
    resp = client.put(
        "/api/settings/resource-policy",
        json=payload,
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_window_enabled"] is False
    assert data["active_window_start"] == "08:00"
    assert data["active_window_end"] == "08:00"
    assert data["active_window_timezone"] == "UTC"
    assert data["effective_now"]["profile"] == "full"
    assert data["effective_now"]["resource_jobs_admitted"] is True
