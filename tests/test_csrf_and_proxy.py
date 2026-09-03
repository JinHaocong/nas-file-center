from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app


def test_csrf_protection_on_cookie_authenticated_mutations(tmp_path: Path):
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
    client = TestClient(create_app(settings))

    # 1. Login to obtain session cookie
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login_resp.status_code == 200

    # 2. Mutating request (POST /api/indexes) WITHOUT Origin or Referer should be rejected with 403
    no_origin_resp = client.post(
        "/api/indexes",
        json={"root": str(data)},
    )
    assert no_origin_resp.status_code == 403
    assert "CSRF validation failed: missing Origin" in no_origin_resp.json()["detail"]

    # 3. Mutating request with MISMATCHED Origin should be rejected with 403
    mismatched_resp = client.post(
        "/api/indexes",
        json={"root": str(data)},
        headers={"Origin": "https://evil-attacker.com"},
    )
    assert mismatched_resp.status_code == 403
    assert "CSRF validation failed: Origin mismatch" in mismatched_resp.json()["detail"]

    # 4. Mutating request with MATCHING Origin should SUCCEED
    valid_origin_resp = client.post(
        "/api/indexes",
        json={"root": str(data)},
        headers={"Origin": "http://testserver"},
    )
    assert valid_origin_resp.status_code == 200

    # 5. Mutating request with MATCHING Referer (and no Origin) should SUCCEED
    valid_referer_resp = client.post(
        "/api/indexes",
        json={"root": str(data)},
        headers={"Referer": "http://testserver/indexes"},
    )
    assert valid_referer_resp.status_code == 200

    # 6. Read-only requests (GET) DO NOT require Origin or Referer
    get_resp = client.get("/api/dashboard/summary")
    assert get_resp.status_code == 200


def test_trusted_proxy_and_rate_limiting(tmp_path: Path):
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
        trusted_proxies_raw="127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12",
    )
    app = create_app(settings)
    client = TestClient(app)

    # 1. Verify trusted proxy IP check
    assert settings.is_trusted_proxy("127.0.0.1") is True
    assert settings.is_trusted_proxy("10.0.1.5") is True
    assert settings.is_trusted_proxy("172.20.0.2") is True
    assert settings.is_trusted_proxy("8.8.8.8") is False
    assert settings.is_trusted_proxy("198.51.100.1") is False

    # 2. Test rate limiting locks after 5 failed attempts
    for i in range(5):
        resp = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "WrongPassword!"},
            headers={"Origin": "http://testserver"},
        )
        assert resp.status_code == 401
        assert "用户名或密码错误" in resp.json()["detail"] or "Invalid credentials" in resp.json()["detail"]

    # 6th attempt should be locked (429)
    locked_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "WrongPassword!"},
        headers={"Origin": "http://testserver"},
    )
    assert locked_resp.status_code == 429
    assert "登录尝试过多" in locked_resp.json()["detail"] or "Too many failed" in locked_resp.json()["detail"]
