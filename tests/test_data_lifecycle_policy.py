from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models import AuditEvent
from app.service import FileCenterService


def make_service(tmp_path: Path):
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
    return FileCenterService(settings), data, settings


def make_authed_client(tmp_path: Path):
    service, data, settings = make_service(tmp_path)
    app = create_app(settings)
    client = TestClient(app)

    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    return client, service, data, settings


def test_get_policy_default_value(tmp_path: Path):
    """GET 策略默认返回 0（永久保留）"""
    service, _, _ = make_service(tmp_path)
    policy = service.get_data_lifecycle_policy()
    assert policy["audit_retention_days"] == 0
    assert policy["updated_at"] is not None


def test_api_get_policy_contract(tmp_path: Path):
    """API 契约：GET /api/data-lifecycle"""
    client, _, _, _ = make_authed_client(tmp_path)
    resp = client.get("/api/data-lifecycle")
    assert resp.status_code == 200
    data = resp.json()
    assert data["audit_retention_days"] == 0
    assert "updated_at" in data


def test_put_policy_valid_values(tmp_path: Path):
    """PUT /api/data-lifecycle 允许设置 0, 1, 90, 365, 3650"""
    client, service, _, _ = make_authed_client(tmp_path)

    for days in [1, 90, 365, 3650, 0]:
        resp = client.put(
            "/api/data-lifecycle",
            json={"audit_retention_days": days},
            headers={"Origin": "http://testserver"},
        )
        assert resp.status_code == 200
        assert resp.json()["audit_retention_days"] == days

        # 验证数据库持久化值
        policy = service.get_data_lifecycle_policy()
        assert policy["audit_retention_days"] == days


def test_put_policy_invalid_values(tmp_path: Path):
    """PUT /api/data-lifecycle 严格拒绝非法取值：负数、>3650、null、字符串、浮点数、空对象"""
    client, _, _, _ = make_authed_client(tmp_path)

    invalid_payloads = [
        {"audit_retention_days": -1},
        {"audit_retention_days": 3651},
        {"audit_retention_days": None},
        {"audit_retention_days": "abc"},
        {"audit_retention_days": 90.5},
        {"audit_retention_days": True},
        {},
    ]

    for payload in invalid_payloads:
        resp = client.put(
            "/api/data-lifecycle",
            json=payload,
            headers={"Origin": "http://testserver"},
        )
        assert resp.status_code in (400, 422), f"Expected 400/422 for payload {payload}, got {resp.status_code}"


def test_save_policy_never_deletes_audit_events(tmp_path: Path):
    """安全红线：保存策略（PUT）绝对不能触发任何 AuditEvent 清理！"""
    client, service, _, _ = make_authed_client(tmp_path)

    now = datetime.now(timezone.utc)
    # 插入 100 条各年龄段的审计事件（包括 1000 天前的老事件）
    with service.SessionLocal() as session:
        for i in range(100):
            session.add(AuditEvent(
                timestamp=now - timedelta(days=i * 10),
                operation="test.op",
                path=f"/data/file_{i}.txt",
                result="ok",
                details_json="{}",
            ))
        session.commit()

    with service.SessionLocal() as session:
        assert session.scalar(select(func.count(AuditEvent.id))) == 100

    # 修改策略为保留 30 天
    resp = client.put(
        "/api/data-lifecycle",
        json={"audit_retention_days": 30},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200

    # 验证全部 100 条审计记录完好无损，零删除！
    with service.SessionLocal() as session:
        assert session.scalar(select(func.count(AuditEvent.id))) == 100


def test_policy_api_auth_and_csrf(tmp_path: Path):
    """未认证拦截 401，已认证缺 Origin 拦截 403"""
    service, data, settings = make_service(tmp_path)
    app = create_app(settings)
    client = TestClient(app)

    # 未认证
    assert client.get("/api/data-lifecycle").status_code == 401
    assert client.put("/api/data-lifecycle", json={"audit_retention_days": 30}).status_code == 401

    # 登录获取 session
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login_resp.status_code == 200

    # 已认证但无 Origin/Referer 头
    resp_no_origin = client.put("/api/data-lifecycle", json={"audit_retention_days": 30})
    assert resp_no_origin.status_code == 403
