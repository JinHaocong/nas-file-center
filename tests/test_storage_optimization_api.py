from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.auth.password import hash_password
from app.models import User
from app.service import FileCenterService


def _client(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)
    with service.SessionLocal() as session:
        session.add(User(
            username="member",
            password_hash=hash_password("MemberPassword123!"),
            role="user",
            is_active=True,
        ))
        session.commit()
    return TestClient(create_app(settings)), data


def _login(client: TestClient, username: str, password: str):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200


def test_storage_capability_probe_is_admin_only(tmp_path: Path):
    client, data = _client(tmp_path)

    unauth = client.post(
        "/api/storage-optimization/capabilities",
        json={"directory": str(data)},
        headers={"Origin": "http://testserver"},
    )
    assert unauth.status_code == 401

    _login(client, "member", "MemberPassword123!")
    member = client.post(
        "/api/storage-optimization/capabilities",
        json={"directory": str(data)},
        headers={"Origin": "http://testserver"},
    )
    assert member.status_code == 403


def test_admin_storage_capability_probe_returns_closed_states_and_zero_residue(tmp_path: Path):
    client, data = _client(tmp_path)
    _login(client, "admin", "AdminPassword123!")

    response = client.post(
        "/api/storage-optimization/capabilities",
        json={"directory": str(data)},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"hardlink", "reflink"}
    assert payload["hardlink"]["capability"] in {"supported", "unsupported", "unknown"}
    assert payload["reflink"]["capability"] in {"supported", "unsupported", "unknown"}
    assert payload["hardlink"]["operation"] == "hardlink"
    assert payload["reflink"]["operation"] == "reflink"
    assert [
        path.name
        for path in data.iterdir()
        if path.name.startswith(".__nfc_hardlink_probe_")
        or path.name.startswith(".__nfc_reflink_probe_")
    ] == []
