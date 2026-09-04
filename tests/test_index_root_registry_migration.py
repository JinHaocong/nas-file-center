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


def _create_legacy_v03_database_without_index_roots(db_path: Path):
    """构建一个不包含 index_roots 表的完整旧版 v0.3 数据库"""
    engine, SessionLocal = create_engine_and_session(db_path)
    # 创建全部除 index_roots 以外的表
    tables_to_create = [
        t for name, t in Base.metadata.tables.items() if name != "index_roots"
    ]
    Base.metadata.create_all(engine, tables=tables_to_create)

    # 填充已有的测试数据：User, Scan, Plan, Audit, WorkJob, IndexedPath
    with SessionLocal() as session:
        # 1. User
        session.add(User(id=1, username="legacy_admin", password_hash="hash", role="admin", is_active=True))
        # 2. ScanJob
        session.add(ScanJob(id=1, name="Scan1", mode="normal", roots_json='["/data/A"]', status="completed"))
        # 3. BatchPlan
        session.add(BatchPlan(id=1, name="Plan1", kind="dedupe", status="draft"))
        # 4. AuditEvent
        session.add(AuditEvent(id=1, operation="op", path="/data/A", result="ok"))
        # 5. IndexedPath (跨两个 root_key：/data/A 和 /data/B)
        session.add_all([
            IndexedPath(
                id=1, root_key="/data/A", absolute_path="/data/A/f1.txt", relative_path="f1.txt",
                basename="f1.txt", stem="f1", suffix=".txt", size=100, mtime_ns=1000,
                device=1, inode=101, is_dir=False,
                first_seen_at=datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc),
                last_seen_at=datetime(2026, 9, 1, 8, 30, 0, tzinfo=timezone.utc),
                scan_generation="gen1",
            ),
            IndexedPath(
                id=2, root_key="/data/A", absolute_path="/data/A/f2.txt", relative_path="f2.txt",
                basename="f2.txt", stem="f2", suffix=".txt", size=200, mtime_ns=2000,
                device=1, inode=102, is_dir=False,
                first_seen_at=datetime(2026, 9, 1, 8, 10, 0, tzinfo=timezone.utc),
                last_seen_at=datetime(2026, 9, 1, 9, 0, 0, tzinfo=timezone.utc),
                scan_generation="gen1",
            ),
            IndexedPath(
                id=3, root_key="/data/B", absolute_path="/data/B/b1.jpg", relative_path="b1.jpg",
                basename="b1.jpg", stem="b1", suffix=".jpg", size=500, mtime_ns=3000,
                device=1, inode=103, is_dir=False,
                first_seen_at=datetime(2026, 9, 2, 1, 0, 0, tzinfo=timezone.utc),
                last_seen_at=datetime(2026, 9, 2, 2, 0, 0, tzinfo=timezone.utc),
                scan_generation="gen2",
            ),
        ])
        # 6. Active WorkJob (属于尚无 IndexedPath 的新目录 /data/C)
        session.add(WorkJob(
            id=42, kind="index-root", status="queued", state_json='{"root": "/data/C"}',
            created_at=datetime(2026, 9, 3, 5, 0, 0, tzinfo=timezone.utc),
        ))
        # 7. Terminal WorkJob (旧的已完成任务)
        session.add(WorkJob(
            id=43, kind="index-root", status="completed", state_json='{"root": "/data/OldDone"}',
            created_at=datetime(2026, 9, 1, 5, 0, 0, tzinfo=timezone.utc),
        ))
        session.commit()


def test_index_root_registry_migration_full_suite(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    db_path = config_dir / "app.db"
    backups_dir = config_dir / "backups"

    # 1. 构造缺失 index_roots 的旧版数据库
    _create_legacy_v03_database_without_index_roots(db_path)

    # 验证初始状态确实缺少 index_roots
    src_conn = sqlite3.connect(str(db_path))
    tables_before = [r[0] for r in src_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "index_roots" not in tables_before
    src_conn.close()

    # 2. 执行首次 init_db
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path, backups_dir=backups_dir)

    # A & F. 验证在创建表前自动产生了备份文件
    backups = list(backups_dir.glob("nas-file-center-*.db"))
    assert len(backups) == 1, "必须在升级前触发数据库安全备份"
    backup_conn = sqlite3.connect(str(backups[0]))
    backup_tables = [r[0] for r in backup_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "index_roots" not in backup_tables, "备份数据库必须保持迁移前原始状态"
    backup_conn.close()

    with SessionLocal() as session:
        # A. 验证 index_roots 表已成功建立
        inspector = inspect(engine)
        assert "index_roots" in inspector.get_table_names()

        # B. 验证已从 indexed_paths 回填 distinct root_key (/data/A 和 /data/B)
        roots = session.scalars(select(IndexRoot).order_by(IndexRoot.root)).all()
        root_map = {r.root: r for r in roots}

        assert "/data/A" in root_map
        assert "/data/B" in root_map

        # C. 验证现有 IndexedPath 记录完全保留 (3 条)
        indexed_count = session.scalar(select(func.count(IndexedPath.id)))
        assert indexed_count == 3

        # D & E. 验证时间戳推导：/data/A created_at 为 min, last_indexed_at 为 max
        root_a = root_map["/data/A"]
        assert "2026-09-01 08:00:00" in str(root_a.created_at)
        assert "2026-09-01 09:00:00" in str(root_a.last_indexed_at)

        # K (Section 六十九). 验证未完结的 WorkJob(root=/data/C) 补入 Registry，且 last_indexed_at 为 null
        assert "/data/C" in root_map
        root_c = root_map["/data/C"]
        assert root_c.last_indexed_at is None
        assert "2026-09-03 05:00:00" in str(root_c.created_at)

        # 终态但无 IndexedPath 的任务不强制补入
        assert "/data/OldDone" not in root_map

        # J. 验证现有的用户、扫描、计划、审计数据完全无损
        assert session.scalar(select(func.count(User.id))) == 1
        assert session.scalar(select(func.count(ScanJob.id))) == 1
        assert session.scalar(select(func.count(BatchPlan.id))) == 1
        assert session.scalar(select(func.count(AuditEvent.id))) == 1
        assert session.scalar(select(func.count(WorkJob.id))) == 2

    # H. 验证 SQLite 完整性检查通过
    with engine.connect() as conn:
        integrity = conn.execute(text("PRAGMA integrity_check")).scalar()
        assert integrity == "ok"

    # G. 验证再次执行 init_db 的幂等性
    init_db(engine, db_path=db_path, backups_dir=backups_dir)
    # 不产生多余的二次备份
    assert len(list(backups_dir.glob("nas-file-center-*.db"))) == 1
    with SessionLocal() as session:
        roots_second = session.scalars(select(IndexRoot)).all()
        assert len(roots_second) == len(roots)


def test_fresh_database_has_no_unnecessary_backup(tmp_path: Path):
    """I. 全新数据库直接建立 index_roots，无需触发多余备份"""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    db_path = config_dir / "app_fresh.db"
    backups_dir = config_dir / "backups"

    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path, backups_dir=backups_dir)

    inspector = inspect(engine)
    assert "index_roots" in inspector.get_table_names()
    assert not backups_dir.exists() or len(list(backups_dir.glob("*.db"))) == 0

    with SessionLocal() as session:
        count = session.scalar(select(func.count(IndexRoot.id)))
        assert count == 0
