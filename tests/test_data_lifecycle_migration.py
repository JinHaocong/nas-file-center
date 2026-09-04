from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import pytest
from sqlalchemy import create_engine, func, inspect, select, text

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import (
    AuditEvent,
    Base,
    BatchPlan,
    IndexRoot,
    IndexedPath,
    ScanJob,
    User,
    WorkJob,
)
from app.service import FileCenterService


def _create_legacy_v03_database_without_lifecycle_policy(db_path: Path):
    """构建一个缺少 data_lifecycle_policy 表的完整旧版数据库"""
    engine, SessionLocal = create_engine_and_session(db_path)
    tables_to_create = [
        t for name, t in Base.metadata.tables.items() if name != "data_lifecycle_policy"
    ]
    Base.metadata.create_all(engine, tables=tables_to_create)

    with SessionLocal() as session:
        session.add(User(id=1, username="legacy_admin", password_hash="hash", role="admin", is_active=True))
        session.add(ScanJob(id=1, name="Scan1", mode="normal", roots_json='["/data/A"]', status="completed"))
        session.add(BatchPlan(id=1, name="Plan1", kind="dedupe", status="draft"))
        session.add(AuditEvent(id=1, operation="file.delete", path="/data/A/f1.txt", result="ok"))
        session.add(IndexRoot(id=1, root="/data/A", created_at=datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc)))
        session.add(IndexedPath(
            id=1, root_key="/data/A", absolute_path="/data/A/f1.txt", relative_path="f1.txt",
            basename="f1.txt", stem="f1", suffix=".txt", size=100, mtime_ns=1000,
            device=1, inode=101, is_dir=False,
            first_seen_at=datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 9, 1, 8, 30, 0, tzinfo=timezone.utc),
            scan_generation="gen1",
        ))
        session.add(WorkJob(
            id=1, kind="index-root", status="completed", state_json='{"root": "/data/A"}',
            created_at=datetime(2026, 9, 1, 5, 0, 0, tzinfo=timezone.utc),
        ))
        session.commit()


def test_data_lifecycle_migration_and_pre_backup(tmp_path: Path):
    """A ~ M: 迁移前置备份、单例初始化、默认保留为0、存量数据保护、幂等与重启持久化测试"""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    db_path = config_dir / "app.db"
    backups_dir = config_dir / "backups"

    # 1. 构造缺失 data_lifecycle_policy 的旧版数据库
    _create_legacy_v03_database_without_lifecycle_policy(db_path)

    # 确认迁移前确实缺少 data_lifecycle_policy
    conn = sqlite3.connect(str(db_path))
    tables_before = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "data_lifecycle_policy" not in tables_before
    conn.close()

    # 2. 首次升级初始化 init_db
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path, backups_dir=backups_dir)

    # A: 验证自动生成了前置迁移备份
    backups = list(backups_dir.glob("nas-file-center-*.db"))
    assert len(backups) == 1
    backup_file = backups[0]

    # 验证备份数据库中缺少 data_lifecycle_policy（证明是 migration 前的状态）
    b_conn = sqlite3.connect(str(backup_file))
    b_tables = [r[0] for r in b_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "data_lifecycle_policy" not in b_tables
    b_conn.close()

    # B & C: 验证迁移后建立了表并且单例 id=1, audit_retention_days=0（永久保留）
    inspector = inspect(engine)
    assert "data_lifecycle_policy" in inspector.get_table_names()
    with SessionLocal() as session:
        policy_row = session.execute(text("SELECT id, audit_retention_days, updated_at FROM data_lifecycle_policy")).mappings().all()
        assert len(policy_row) == 1
        assert policy_row[0]["id"] == 1
        assert policy_row[0]["audit_retention_days"] == 0
        assert policy_row[0]["updated_at"] is not None

        # D ~ I: 验证既有数据全部完整保留
        assert session.scalar(select(func.count(User.id))) == 1
        assert session.scalar(select(func.count(ScanJob.id))) == 1
        assert session.scalar(select(func.count(BatchPlan.id))) == 1
        assert session.scalar(select(func.count(AuditEvent.id))) == 1
        assert session.scalar(select(func.count(IndexRoot.id))) == 1
        assert session.scalar(select(func.count(IndexedPath.id))) == 1
        assert session.scalar(select(func.count(WorkJob.id))) == 1

    # J: 第二次 init_db 幂等性测试
    init_db(engine, db_path=db_path, backups_dir=backups_dir)
    # 绝不产生二次备份
    assert len(list(backups_dir.glob("nas-file-center-*.db"))) == 1
    with SessionLocal() as session:
        # 单例数量仍然严格为 1
        assert session.scalar(text("SELECT COUNT(*) FROM data_lifecycle_policy")) == 1

    # K: 用户修改为 90 天后重启，策略绝不回滚为 0
    with SessionLocal() as session:
        session.execute(text("UPDATE data_lifecycle_policy SET audit_retention_days = 90 WHERE id = 1"))
        session.commit()

    init_db(engine, db_path=db_path, backups_dir=backups_dir)
    with SessionLocal() as session:
        retained = session.scalar(text("SELECT audit_retention_days FROM data_lifecycle_policy WHERE id = 1"))
        assert retained == 90

    # L: 全新数据库初始化无多余备份
    fresh_dir = tmp_path / "fresh_config"
    fresh_dir.mkdir(parents=True)
    fresh_db = fresh_dir / "fresh.db"
    fresh_backups = fresh_dir / "backups"
    fresh_engine, fresh_Session = create_engine_and_session(fresh_db)
    init_db(fresh_engine, db_path=fresh_db, backups_dir=fresh_backups)
    assert not fresh_backups.exists() or len(list(fresh_backups.glob("*.db"))) == 0
    with fresh_Session() as session:
        assert session.scalar(text("SELECT audit_retention_days FROM data_lifecycle_policy WHERE id = 1")) == 0

    # M: PRAGMA integrity_check
    with engine.connect() as conn:
        res = conn.execute(text("PRAGMA integrity_check")).scalar()
        assert res == "ok"
