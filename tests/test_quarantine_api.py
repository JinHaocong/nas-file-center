from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import QuarantineEntry, User, utcnow
from app.quarantine.paths import safe_quarantine_hash
from app.service import FileCenterService


def _setup_api_env(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    trash = data / ".nas-file-center-trash"
    trash.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=trash,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    service = FileCenterService(settings)
    app = create_app(settings)
    client = TestClient(app)

    # Login as admin
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    admin_cookie = client.cookies.get(settings.session_cookie_name)

    # Create non-admin user
    with service.SessionLocal() as session:
        from app.auth.password import hash_password
        regular_user = User(
            username="regular",
            password_hash=hash_password("RegularPassword123!"),
            role="user",
        )
        session.add(regular_user)
        session.commit()

    regular_client = TestClient(app)
    resp_reg = regular_client.post(
        "/api/auth/login",
        json={"username": "regular", "password": "RegularPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert resp_reg.status_code == 200

    unauth_client = TestClient(app)

    return {
        "admin_client": client,
        "regular_client": regular_client,
        "unauth_client": unauth_client,
        "service": service,
        "data": data,
        "trash": trash,
    }


def test_api_unauthorized_access(tmp_path: Path):
    """Endpoints require authentication; return 401 when unauthenticated."""
    env = _setup_api_env(tmp_path)
    client = env["unauth_client"]

    assert client.get("/api/quarantine").status_code == 401
    assert client.get("/api/quarantine/1").status_code == 401
    assert client.get("/api/quarantine/retention-policy").status_code == 401
    assert client.post("/api/quarantine/1/restore", json={"conflict_policy": "skip"}).status_code == 401
    assert client.post("/api/quarantine/1/purge", json={"confirmation": "DELETE"}).status_code == 401


def test_api_csrf_validation(tmp_path: Path):
    """Mutating endpoints reject requests without valid Origin or Referer (CSRF protection)."""
    env = _setup_api_env(tmp_path)
    client = env["admin_client"]

    # Without Origin/Referer header on POST/PUT
    resp = client.post("/api/quarantine/1/restore", json={"conflict_policy": "skip"})
    assert resp.status_code == 403


def test_api_non_admin_forbidden_for_purge_and_policy(tmp_path: Path):
    """Non-admin user receives 403 Forbidden for purge and policy update."""
    env = _setup_api_env(tmp_path)
    client = env["regular_client"]

    # Policy update
    resp = client.put(
        "/api/quarantine/retention-policy",
        json={"quarantine_retention_days": 30},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 403

    # Purge
    resp_purge = client.post(
        "/api/quarantine/1/purge",
        json={"confirmation": "DELETE"},
        headers={"Origin": "http://testserver"},
    )
    assert resp_purge.status_code == 403


def test_api_retention_policy_strict_validation(tmp_path: Path):
    """Retention policy PUT rejects invalid values and accepts valid values."""
    env = _setup_api_env(tmp_path)
    client = env["admin_client"]

    # Valid values
    for val in [0, 7, 30, 90]:
        resp = client.put(
            "/api/quarantine/retention-policy",
            json={"quarantine_retention_days": val},
            headers={"Origin": "http://testserver"},
        )
        assert resp.status_code == 200
        assert resp.json()["quarantine_retention_days"] == val

    # Invalid values: boolean, float, string, non-whitelisted ints
    for invalid in [True, False, 15, -1, 1, 365, "30", 30.0]:
        resp = client.put(
            "/api/quarantine/retention-policy",
            json={"quarantine_retention_days": invalid},
            headers={"Origin": "http://testserver"},
        )
        assert resp.status_code in (400, 422)


def test_api_list_pagination_and_detail(tmp_path: Path):
    """Pagination, filtering, and detail endpoints work correctly."""
    env = _setup_api_env(tmp_path)
    client = env["admin_client"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]
    now = utcnow()

    # Seed 3 entries
    with service.SessionLocal() as session:
        for i in range(1, 4):
            session.add(
                QuarantineEntry(
                    plan_item_id=None,
                    original_path=str(data / f"file_{i}.txt"),
                    quarantine_path=str(trash / f"file_{i}.q-{i}.txt"),
                    state="active" if i < 3 else "restored",
                    size=100 * i,
                    content_hash=f"hash_{i}",
                    created_at=now,
                    updated_at=now,
                )
            )
        session.commit()

    # List all
    resp = client.get("/api/quarantine?page=1&page_size=2")
    assert resp.status_code == 200
    data_json = resp.json()
    assert data_json["total"] == 3
    assert len(data_json["items"]) == 2

    # Filter by state
    resp_state = client.get("/api/quarantine?state=restored")
    assert resp_state.status_code == 200
    assert resp_state.json()["total"] == 1

    # Filter by query
    resp_query = client.get("/api/quarantine?query=file_1")
    assert resp_query.status_code == 200
    assert resp_query.json()["total"] == 1

    # Detail
    resp_detail = client.get("/api/quarantine/1")
    assert resp_detail.status_code == 200
    assert resp_detail.json()["id"] == 1
    assert resp_detail.json()["original_path"] == str(data / "file_1.txt")

    # Detail not found
    assert client.get("/api/quarantine/999").status_code == 404


def test_api_restore_flow(tmp_path: Path):
    """Restore endpoint works with default skip and rename."""
    env = _setup_api_env(tmp_path)
    client = env["admin_client"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    src = data / "api_restore.txt"
    tgt = trash / "api_restore.q-1.txt"
    tgt.write_text("api restore content")
    sha = safe_quarantine_hash(tgt)

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            plan_item_id=None,
            original_path=str(src),
            quarantine_path=str(tgt),
            state="active",
            size=len("api restore content"),
            content_hash=sha,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    resp = client.post(
        f"/api/quarantine/{entry_id}/restore",
        json={"conflict_policy": "skip"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "restored"
    assert src.exists()


def test_api_purge_flow(tmp_path: Path):
    """Purge endpoint permanently deletes file and requires confirmation='DELETE'."""
    env = _setup_api_env(tmp_path)
    client = env["admin_client"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    tgt = trash / "plan-api" / "root-0" / "purge_api.q-1.txt"
    tgt.parent.mkdir(parents=True, exist_ok=True)
    tgt.write_text("api purge content")
    sha = safe_quarantine_hash(tgt)

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            plan_item_id=None,
            original_path=str(data / "purge_api.txt"),
            quarantine_path=str(tgt),
            state="active",
            size=len("api purge content"),
            content_hash=sha,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    # Invalid confirmation
    resp_bad = client.post(
        f"/api/quarantine/{entry_id}/purge",
        json={"confirmation": "NO"},
        headers={"Origin": "http://testserver"},
    )
    assert resp_bad.status_code == 400

    # Valid confirmation
    resp_ok = client.post(
        f"/api/quarantine/{entry_id}/purge",
        json={"confirmation": "DELETE"},
        headers={"Origin": "http://testserver"},
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["state"] == "purged"
    assert not tgt.exists()
