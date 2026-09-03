from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app


def test_csrf_untrusted_client_forwarded_host_spoof_rejection(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()

    # Setup settings with explicit trusted proxy CIDR list (e.g. only 10.0.0.0/8 is trusted proxy)
    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        trusted_proxies_raw="10.0.0.0/8",
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    app = create_app(settings)

    # 1. Login with proper Origin
    client = TestClient(app, client=("198.51.100.25", 54321))  # Untrusted external IP
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver", "Host": "testserver"},
    )
    assert login_resp.status_code == 200

    # 2. Untrusted direct client attempts CSRF with spoofed X-Forwarded-Host
    # Direct IP (198.51.100.25) is NOT in TRUSTED_PROXIES (10.0.0.0/8).
    # Even if attacker supplies X-Forwarded-Host: evil.example and Origin: https://evil.example,
    # the server MUST reject X-Forwarded-Host and return 403 Forbidden!
    attack_resp = client.post(
        "/api/indexes",
        json={"root": str(data)},
        headers={
            "Origin": "https://evil.example",
            "X-Forwarded-Host": "evil.example",
            "Host": "testserver",
        },
    )
    assert attack_resp.status_code == 403
    assert "CSRF validation failed: Origin mismatch" in attack_resp.json()["detail"]


def test_csrf_trusted_reverse_proxy_forwarded_host_allowed(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        trusted_proxies_raw="10.0.0.0/8,127.0.0.1",
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    app = create_app(settings)

    # Client connecting from trusted reverse proxy IP (10.0.1.5)
    proxy_client = TestClient(app, client=("10.0.1.5", 54321))
    login_resp = proxy_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={
            "Origin": "https://file.kerwin.cloud",
            "Host": "nas-file-center-api:8080",
            "X-Forwarded-Host": "file.kerwin.cloud",
            "X-Forwarded-For": "203.0.113.195",
        },
    )
    assert login_resp.status_code == 200

    # Authenticated mutation through trusted reverse proxy
    mutate_resp = proxy_client.post(
        "/api/indexes",
        json={"root": str(data)},
        headers={
            "Origin": "https://file.kerwin.cloud",
            "Host": "nas-file-center-api:8080",
            "X-Forwarded-Host": "file.kerwin.cloud",
            "X-Forwarded-For": "203.0.113.195",
        },
    )
    assert mutate_resp.status_code == 200
    assert mutate_resp.json()["status"] == "queued"
