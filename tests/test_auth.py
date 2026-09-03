from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import Base, User, Session as UserSession
from app.auth.password import hash_password, verify_password
from app.auth.sessions import (
    create_session,
    get_valid_session,
    revoke_session,
    revoke_user_sessions,
    hash_token,
)
from app.auth.rate_limiter import LoginRateLimiter
from app.main import create_app


@pytest.fixture
def auth_settings(tmp_path: Path):
    return Settings(
        config_dir=tmp_path / "config",
        data_mount=tmp_path / "data",
        allowed_roots_raw=str(tmp_path / "data"),
        initial_admin_username="admin",
        initial_admin_password="TestPassword123!",
    )


def test_password_hash_and_verify():
    password = "MySecurePassword123!"
    pw_hash = hash_password(password)
    assert pw_hash != password
    assert pw_hash.startswith("$argon2id$")
    assert verify_password(password, pw_hash) is True
    assert verify_password("WrongPassword", pw_hash) is False


def test_session_lifecycle(auth_settings: Settings):
    engine, SessionLocal = create_engine_and_session(auth_settings.database_path)
    init_db(engine)

    with SessionLocal() as db_session:
        user = User(username="kerwin", password_hash=hash_password("Pass123"), role="admin")
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        session_obj, raw_token = create_session(
            db_session,
            user_id=user.id,
            max_age_seconds=3600,
            ip_address="127.0.0.1",
            user_agent="TestAgent/1.0",
        )
        assert raw_token
        assert session_obj.token_hash == hash_token(raw_token)
        assert session_obj.token_hash != raw_token

        # Verify get_valid_session
        valid = get_valid_session(db_session, raw_token)
        assert valid is not None
        assert valid.user_id == user.id
        assert valid.user.username == "kerwin"

        # Verify invalid token
        assert get_valid_session(db_session, "invalid-token-12345") is None

        # Create second session and revoke others
        session_obj2, raw_token2 = create_session(
            db_session,
            user_id=user.id,
            max_age_seconds=3600,
            ip_address="127.0.0.1",
            user_agent="TestAgent/2.0",
        )
        assert get_valid_session(db_session, raw_token) is not None
        assert get_valid_session(db_session, raw_token2) is not None

        # Revoke first session specifically
        assert revoke_session(db_session, session_obj.id, user_id=user.id) is True
        assert get_valid_session(db_session, raw_token) is None
        assert get_valid_session(db_session, raw_token2) is not None


def test_login_rate_limiter():
    limiter = LoginRateLimiter(max_attempts=5, lockout_seconds=900)
    username = "admin"
    ip = "192.168.1.100"

    assert limiter.is_rate_limited(username, ip) is False
    for _ in range(4):
        limiter.record_failure(username, ip)
        assert limiter.is_rate_limited(username, ip) is False

    # 5th failure triggers lockout
    limiter.record_failure(username, ip)
    assert limiter.is_rate_limited(username, ip) is True

    # Different IP should not be locked out
    assert limiter.is_rate_limited(username, "192.168.1.101") is False

    # Record success resets
    limiter.record_success(username, ip)
    assert limiter.is_rate_limited(username, ip) is False


def test_initial_admin_creation_and_reboot_safety(auth_settings: Settings):
    # First boot: creates initial admin
    app = create_app(auth_settings)
    client = TestClient(app)

    # Login with initial credentials
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "TestPassword123!"},
    )
    assert login_resp.status_code == 200
    assert login_resp.json()["username"] == "admin"
    assert "nfc_session" in login_resp.cookies

    # Simulate reboot with DIFFERENT initial password env var -> should NOT overwrite password
    modified_settings = Settings(
        config_dir=auth_settings.config_dir,
        data_mount=auth_settings.data_mount,
        allowed_roots_raw=auth_settings.allowed_roots_raw,
        initial_admin_username="admin",
        initial_admin_password="ChangedPasswordShouldBeIgnored!",
    )
    app2 = create_app(modified_settings)
    client2 = TestClient(app2)

    # Old password should still work
    login_resp2 = client2.post(
        "/api/auth/login",
        json={"username": "admin", "password": "TestPassword123!"},
    )
    assert login_resp2.status_code == 200

    # New env password must fail
    login_bad = client2.post(
        "/api/auth/login",
        json={"username": "admin", "password": "ChangedPasswordShouldBeIgnored!"},
    )
    assert login_bad.status_code == 401


def test_auth_api_endpoints(auth_settings: Settings):
    app = create_app(auth_settings)
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})

    # 1. Unauthenticated /api/auth/me -> 401
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401

    # 2. Login
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "TestPassword123!"},
    )
    assert login_resp.status_code == 200
    user_data = login_resp.json()
    assert user_data["username"] == "admin"
    assert "password_hash" not in user_data
    assert "token" not in user_data

    # 3. Authenticated /api/auth/me
    me_resp = client.get("/api/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "admin"

    # 4. List sessions
    sessions_resp = client.get("/api/auth/sessions")
    assert sessions_resp.status_code == 200
    sessions = sessions_resp.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["is_current"] is True

    # 5. Change password
    change_resp = client.post(
        "/api/auth/change-password",
        json={
            "old_password": "TestPassword123!",
            "new_password": "NewSecurePassword456!",
        },
    )
    assert change_resp.status_code == 200

    # 6. Current session still valid after password change
    me_after = client.get("/api/auth/me")
    assert me_after.status_code == 200

    # 7. Logout
    logout_resp = client.post("/api/auth/logout")
    assert logout_resp.status_code == 200

    # 8. Unauthenticated again
    assert client.get("/api/auth/me").status_code == 401


def test_api_protection_middleware(auth_settings: Settings):
    app = create_app(auth_settings)
    client = TestClient(app)

    # Public endpoint /health works without auth
    health_resp = client.get("/health")
    assert health_resp.status_code == 200

    # Protected endpoints require auth
    assert client.get("/api/scans/1").status_code == 401
    assert client.post("/api/scans", json={"name": "test", "roots": ["/data"]}).status_code == 401
    assert client.post("/api/indexes", json={"root": "/data"}).status_code == 401
    assert client.get("/api/plans/1").status_code == 401

    # Login and verify protected endpoints are accessible
    client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "TestPassword123!"},
    )
    # With auth, missing scan returns 404 (not 401)
    assert client.get("/api/scans/999").status_code == 404
