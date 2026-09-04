from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models import (
    AuditEvent,
    BatchPlan,
    IndexRoot,
    IndexedPath,
    ScanJob,
    User,
    WorkJob,
)
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


def test_preview_audit_retention_read_only(tmp_path: Path):
    """Preview 必须完全只读：调用前后 AuditEvent 数量、行内容、策略完全不变，不产生自审计"""
    client, service, _, _ = make_authed_client(tmp_path)
    now = datetime.now(timezone.utc)

    # 插入两条审计
    with service.SessionLocal() as session:
        session.add(AuditEvent(timestamp=now - timedelta(days=50), operation="op1", result="ok"))
        session.add(AuditEvent(timestamp=now - timedelta(days=10), operation="op2", result="ok"))
        session.commit()

    service.update_data_lifecycle_policy(30)

    # 调用前快照
    with service.SessionLocal() as session:
        count_before = session.scalar(select(func.count(AuditEvent.id)))

    resp = client.get("/api/audit/retention-preview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["retention_days"] == 30
    assert data["enabled"] is True
    assert data["total_count"] == 2
    assert data["delete_count"] == 1
    assert data["keep_count"] == 1

    # 验证零写操作
    with service.SessionLocal() as session:
        count_after = session.scalar(select(func.count(AuditEvent.id)))
        assert count_after == count_before
        # 确认没有产生任何 audit.retention 事件
        self_audits = session.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.operation == "audit.retention"))
        assert self_audits == 0


def test_preview_retention_zero_permanent(tmp_path: Path):
    """策略为 0 时，Preview 返回 enabled=False, delete_count=0, cutoff=None"""
    client, service, _, _ = make_authed_client(tmp_path)
    now = datetime.now(timezone.utc)

    with service.SessionLocal() as session:
        session.add(AuditEvent(timestamp=now - timedelta(days=500), operation="old_op", result="ok"))
        session.commit()

    # 默认 policy=0
    resp = client.get("/api/audit/retention-preview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["retention_days"] == 0
    assert data["enabled"] is False
    assert data["cutoff"] is None
    assert data["total_count"] == 1
    assert data["delete_count"] == 0
    assert data["keep_count"] == 1
    assert data["oldest_timestamp"] is not None
    assert data["newest_timestamp"] is not None


def test_preview_and_cutoff_strict_boundary(tmp_path: Path):
    """时间截止点严格边界测试：timestamp < cutoff 才删除，timestamp == cutoff 严格保留"""
    service, _, _ = make_service(tmp_path)
    service.update_data_lifecycle_policy(90)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=90)

    # 构造精确样本
    t_200 = now - timedelta(days=200)
    t_100 = now - timedelta(days=100)
    t_90_exact = cutoff
    t_30 = now - timedelta(days=30)
    t_now = now

    with service.SessionLocal() as session:
        session.add(AuditEvent(id=1, timestamp=t_200, operation="op200", result="ok"))
        session.add(AuditEvent(id=2, timestamp=t_100, operation="op100", result="ok"))
        session.add(AuditEvent(id=3, timestamp=t_90_exact, operation="op90_exact", result="ok"))
        session.add(AuditEvent(id=4, timestamp=t_30, operation="op30", result="ok"))
        session.add(AuditEvent(id=5, timestamp=t_now, operation="op_now", result="ok"))
        session.commit()

    preview = service.preview_audit_retention(now=now)
    assert preview["total_count"] == 5
    assert preview["delete_count"] == 2  # 仅 t_200 和 t_100
    assert preview["keep_count"] == 3    # t_90_exact, t_30, t_now 全部保留

    # 进一步验证 apply 的严格边界：timestamp == cutoff 绝不删除
    apply_res = service.apply_audit_retention(now=now)
    assert apply_res["deleted_count"] == 2
    with service.SessionLocal() as session:
        assert session.get(AuditEvent, 1) is None
        assert session.get(AuditEvent, 2) is None
        assert session.get(AuditEvent, 3) is not None  # t_90_exact 严格保留
        assert session.get(AuditEvent, 4) is not None
        assert session.get(AuditEvent, 5) is not None


def test_apply_retention_zero_rejected(tmp_path: Path):
    """最高安全红线：policy=0 时调用 apply-retention 必须抛出 400 Bad Request，0 删除，0 自审计"""
    client, service, _, _ = make_authed_client(tmp_path)
    now = datetime.now(timezone.utc)

    with service.SessionLocal() as session:
        session.add(AuditEvent(id=1, timestamp=now - timedelta(days=1000), operation="ancient", result="ok"))
        session.commit()

    # policy 默认为 0
    with pytest.raises(ValueError, match="permanent retention"):
        service.apply_audit_retention()

    # API 接口验证 400
    resp = client.post("/api/audit/apply-retention", headers={"Origin": "http://testserver"})
    assert resp.status_code == 400
    assert "permanent retention" in resp.json()["detail"]

    # 验证审计表绝对零变更
    with service.SessionLocal() as session:
        assert session.scalar(select(func.count(AuditEvent.id))) == 1
        assert session.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.operation == "audit.retention")) == 0


def test_apply_retention_transaction_and_self_audit(tmp_path: Path):
    """成功清理必须在同一事务中删除并写入恰好 1 条 audit.retention 自审计，剩余数包含自审计"""
    client, service, _, _ = make_authed_client(tmp_path)
    service.update_data_lifecycle_policy(90)

    now = datetime.now(timezone.utc)

    with service.SessionLocal() as session:
        session.add(AuditEvent(id=1, timestamp=now - timedelta(days=200), operation="old1", result="ok"))
        session.add(AuditEvent(id=2, timestamp=now - timedelta(days=150), operation="old2", result="ok"))
        session.add(AuditEvent(id=3, timestamp=now - timedelta(days=50), operation="window_keep", result="ok"))
        session.add(AuditEvent(id=4, timestamp=now - timedelta(days=10), operation="new_keep", result="ok"))
        session.commit()

    resp = client.post("/api/audit/apply-retention", headers={"Origin": "http://testserver"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["retention_days"] == 90
    assert body["deleted_count"] == 2
    # 剩余数量 = 2 (kept) + 1 (new self audit) = 3
    assert body["remaining_count"] == 3

    # 数据库验证
    with service.SessionLocal() as session:
        # 确认 1 和 2 已被删除
        assert session.get(AuditEvent, 1) is None
        assert session.get(AuditEvent, 2) is None
        # 确认未过期事件被保留
        assert session.get(AuditEvent, 3) is not None
        assert session.get(AuditEvent, 4) is not None

        # 确认恰好产生了 1 条自审计记录
        self_audits = list(session.scalars(select(AuditEvent).where(AuditEvent.operation == "audit.retention")))
        assert len(self_audits) == 1
        sa = self_audits[0]
        assert sa.result == "success"
        details = json.loads(sa.details_json)
        assert details["retention_days"] == 90
        assert details["deleted_count"] == 2
        assert "cutoff" in details


def test_apply_retention_rollback_on_failure(tmp_path: Path):
    """事务回滚测试：清理过程中注入异常，已删行必须完整恢复，绝不残留成功自审计"""
    service, _, _ = make_service(tmp_path)
    service.update_data_lifecycle_policy(30)
    now = datetime.now(timezone.utc)

    with service.SessionLocal() as session:
        session.add(AuditEvent(id=10, timestamp=now - timedelta(days=100), operation="candidate", result="ok"))
        session.commit()

    def fault_injector(session):
        raise RuntimeError("Injected DB failure during retention cleanup")

    with pytest.raises(RuntimeError, match="Injected DB failure"):
        service.apply_audit_retention(transaction_guard=fault_injector)

    # 验证候选记录仍完整存在，且无自审计记录
    with service.SessionLocal() as session:
        assert session.get(AuditEvent, 10) is not None
        self_audits = session.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.operation == "audit.retention"))
        assert self_audits == 0


def test_apply_retention_with_zero_candidates(tmp_path: Path):
    """当无过期候选记录时，Apply 成功执行，deleted_count=0，依然记录一条 self-audit"""
    service, _, _ = make_service(tmp_path)
    service.update_data_lifecycle_policy(90)
    now = datetime.now(timezone.utc)

    with service.SessionLocal() as session:
        session.add(AuditEvent(id=1, timestamp=now - timedelta(days=10), operation="recent", result="ok"))
        session.commit()

    res = service.apply_audit_retention()
    assert res["deleted_count"] == 0
    assert res["remaining_count"] == 2  # 1 原记录 + 1 自审计

    with service.SessionLocal() as session:
        self_audit = session.scalar(select(AuditEvent).where(AuditEvent.operation == "audit.retention"))
        assert self_audit is not None
        details = json.loads(self_audit.details_json)
        assert details["deleted_count"] == 0


def test_apply_retention_preserves_other_models_and_filesystem(tmp_path: Path):
    """数据保护测试：Audit 清理绝对不影响 WorkJob、TaskEvent、ScanJob、BatchPlan、IndexRoot 及物理文件"""
    service, data, _ = make_service(tmp_path)
    service.update_data_lifecycle_policy(30)
    now = datetime.now(timezone.utc)

    # 创建物理文件
    test_dir = data / "ProtectedDir"
    test_dir.mkdir()
    test_file = test_dir / "vital.txt"
    test_file.write_text("precious payload")

    with service.SessionLocal() as session:
        # 过期审计记录
        session.add(AuditEvent(id=1, timestamp=now - timedelta(days=100), operation="op", result="ok"))
        # 其它模型数据
        session.add(User(id=2, username="user2", password_hash="h", role="admin", is_active=True))
        session.add(ScanJob(id=1, name="scan", mode="normal", roots_json="[]", status="completed"))
        session.add(BatchPlan(id=1, name="plan", kind="dedupe", status="draft"))
        session.add(IndexRoot(id=1, root=str(test_dir.resolve()), created_at=now))
        session.add(IndexedPath(
            id=1, root_key=str(test_dir.resolve()), absolute_path=str(test_file.resolve()),
            relative_path="vital.txt", basename="vital.txt", stem="vital", suffix=".txt",
            size=10, mtime_ns=1, device=1, inode=1, is_dir=False, first_seen_at=now, last_seen_at=now,
            scan_generation="gen",
        ))
        session.add(WorkJob(id=1, kind="index-root", status="completed", state_json="{}"))
        session.commit()

    # 执行清理
    res = service.apply_audit_retention()
    assert res["deleted_count"] == 1

    # 验证物理文件未被改动
    assert test_file.exists()
    assert test_file.read_text() == "precious payload"

    # 验证其它模型全部完好无损
    with service.SessionLocal() as session:
        assert session.scalar(select(func.count(User.id)).where(User.id == 2)) == 1
        assert session.scalar(select(func.count(ScanJob.id))) == 1
        assert session.scalar(select(func.count(BatchPlan.id))) == 1
        assert session.scalar(select(func.count(IndexRoot.id))) == 1
        assert session.scalar(select(func.count(IndexedPath.id))) == 1
        assert session.scalar(select(func.count(WorkJob.id))) == 1


def test_apply_api_auth_and_csrf(tmp_path: Path):
    """Apply API 未认证返回 401，已认证缺 Origin 返回 403"""
    service, data, settings = make_service(tmp_path)
    app = create_app(settings)
    client = TestClient(app)

    # 未认证
    assert client.get("/api/audit/retention-preview").status_code == 401
    assert client.post("/api/audit/apply-retention").status_code == 401

    # 登录
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login_resp.status_code == 200

    # 认证后无 Origin 发起 POST
    resp_no_origin = client.post("/api/audit/apply-retention")
    assert resp_no_origin.status_code == 403
