from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import pytest
from sqlalchemy import inspect, select, text

from app.db import create_engine_and_session, init_db
from app.models import Base, DataLifecyclePolicy, QuarantineEntry


def _create_v033_baseline_db(db_path: Path, audit_retention: int = 90):
    """Creates a simulated v0.3.3 database without quarantine_entries and without quarantine_retention_days."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.executescript(f"""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username VARCHAR(64) UNIQUE,
            password_hash VARCHAR(255),
            role VARCHAR(32),
            is_active BOOLEAN,
            created_at DATETIME,
            updated_at DATETIME,
            last_login_at DATETIME
        );
        INSERT INTO users (id, username, password_hash, role, is_active)
        VALUES (1, 'admin', 'hash123', 'admin', 1);

        CREATE TABLE data_lifecycle_policy (
            id INTEGER PRIMARY KEY,
            audit_retention_days INTEGER NOT NULL,
            updated_at DATETIME NOT NULL
        );
        INSERT INTO data_lifecycle_policy (id, audit_retention_days, updated_at)
        VALUES (1, {audit_retention}, CURRENT_TIMESTAMP);

        CREATE TABLE audit_events (
            id INTEGER PRIMARY KEY,
            timestamp DATETIME,
            operation VARCHAR(64),
            path TEXT,
            result VARCHAR(32),
            details_json TEXT
        );
        INSERT INTO audit_events (id, operation, path, result, details_json)
        VALUES (1, 'quarantine', '/data/test.txt', 'completed', '{{}}');

        CREATE TABLE batch_plans (
            id INTEGER PRIMARY KEY,
            name VARCHAR(255),
            kind VARCHAR(64),
            status VARCHAR(32),
            created_at DATETIME,
            frozen_at DATETIME,
            expected_changes INTEGER,
            expected_reclaim_bytes BIGINT,
            metadata_json TEXT
        );
        CREATE TABLE batch_plan_items (
            id INTEGER PRIMARY KEY,
            plan_id INTEGER REFERENCES batch_plans(id) ON DELETE CASCADE,
            sequence INTEGER,
            operation VARCHAR(64),
            source_path TEXT,
            target_path TEXT,
            keep_path TEXT,
            expected_size BIGINT,
            expected_mtime_ns BIGINT,
            expected_device BIGINT,
            expected_inode BIGINT,
            expected_hash VARCHAR(128),
            state VARCHAR(32),
            reason TEXT,
            metadata_json TEXT
        );
        CREATE TABLE index_roots (
            id INTEGER PRIMARY KEY,
            root TEXT UNIQUE NOT NULL,
            created_at DATETIME,
            last_indexed_at DATETIME
        );
        CREATE TABLE work_jobs (
            id INTEGER PRIMARY KEY,
            kind VARCHAR(64),
            status VARCHAR(32),
            progress_current BIGINT,
            progress_total BIGINT,
            progress_message TEXT,
            state_json TEXT,
            checkpoint_json TEXT,
            error_text TEXT,
            error_code VARCHAR(64),
            pause_requested_at DATETIME,
            cancel_requested_at DATETIME,
            heartbeat_at DATETIME,
            retry_of INTEGER REFERENCES work_jobs(id) ON DELETE SET NULL,
            created_at DATETIME,
            started_at DATETIME,
            finished_at DATETIME
        );
    """)
    conn.commit()
    conn.close()


def test_fresh_database_initialization(tmp_path: Path):
    """Fresh DB initializes all tables including quarantine_entries with 0 backups."""
    db_path = tmp_path / "config" / "fresh.db"
    backups_dir = tmp_path / "config" / "backups"

    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path, backups_dir=backups_dir)

    # Check tables
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "quarantine_entries" in tables
    assert "data_lifecycle_policy" in tables

    # Check columns of quarantine_entries
    q_cols = {c["name"] for c in inspector.get_columns("quarantine_entries")}
    expected_q_cols = {
        "id", "original_path", "quarantine_path", "task_id", "plan_item_id",
        "state", "size", "content_hash", "mtime_ns", "device", "inode",
        "quarantined_at", "expires_at", "restored_at", "purged_at",
        "last_error", "created_at", "updated_at"
    }
    assert expected_q_cols.issubset(q_cols)

    # Check columns of data_lifecycle_policy
    dlp_cols = {c["name"] for c in inspector.get_columns("data_lifecycle_policy")}
    assert "quarantine_retention_days" in dlp_cols
    assert "audit_retention_days" in dlp_cols

    # Check seed values
    with SessionLocal() as session:
        policy = session.get(DataLifecyclePolicy, 1)
        assert policy is not None
        assert policy.audit_retention_days == 0
        assert policy.quarantine_retention_days == 0

    # Verify no backups created on fresh DB
    backup_files = list(backups_dir.glob("*.db")) if backups_dir.exists() else []
    assert len(backup_files) == 0

    engine.dispose()


def test_migration_from_v033_with_backup_before_mutation(tmp_path: Path):
    """Migration from v0.3.3 takes a backup BEFORE mutation and preserves existing audit retention."""
    db_path = tmp_path / "config" / "app.db"
    backups_dir = tmp_path / "config" / "backups"
    _create_v033_baseline_db(db_path, audit_retention=90)

    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path, backups_dir=backups_dir)

    # 1. Verify backup was created
    backup_files = list(backups_dir.glob("nas-file-center-*.db"))
    assert len(backup_files) == 1, f"Expected exactly 1 backup, found {len(backup_files)}"
    backup_file = backup_files[0]

    # 2. Open backup file and verify it represents the pre-mutation state
    backup_conn = sqlite3.connect(str(backup_file))
    cur = backup_conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    backup_tables = {row[0] for row in cur.fetchall()}
    assert "quarantine_entries" not in backup_tables, "Backup must NOT contain quarantine_entries"

    cur.execute("PRAGMA table_info(data_lifecycle_policy);")
    backup_dlp_cols = {row[1] for row in cur.fetchall()}
    assert "quarantine_retention_days" not in backup_dlp_cols, "Backup must NOT contain quarantine_retention_days"

    cur.execute("PRAGMA integrity_check;")
    assert cur.fetchone()[0] == "ok"
    backup_conn.close()

    # 3. Verify upgraded DB has new table and columns
    inspector = inspect(engine)
    assert "quarantine_entries" in set(inspector.get_table_names())
    dlp_cols = {c["name"] for c in inspector.get_columns("data_lifecycle_policy")}
    assert "quarantine_retention_days" in dlp_cols

    # 4. Verify existing data preserved
    with SessionLocal() as session:
        policy = session.get(DataLifecyclePolicy, 1)
        assert policy is not None
        assert policy.audit_retention_days == 90, "Existing audit retention must be preserved!"
        assert policy.quarantine_retention_days == 0, "Default quarantine retention must be 0 (never)"

    # 5. Integrity and foreign keys
    with engine.connect() as conn:
        res = conn.execute(text("PRAGMA integrity_check;")).scalar()
        assert res == "ok"
        fk_res = conn.execute(text("PRAGMA foreign_key_check;")).fetchall()
        assert len(fk_res) == 0

    engine.dispose()


def test_migration_idempotency_second_init(tmp_path: Path):
    """Second call to init_db produces 0 new backups and preserves data."""
    db_path = tmp_path / "config" / "app.db"
    backups_dir = tmp_path / "config" / "backups"
    _create_v033_baseline_db(db_path, audit_retention=30)

    engine, _ = create_engine_and_session(db_path)
    init_db(engine, db_path=db_path, backups_dir=backups_dir)

    initial_backups = list(backups_dir.glob("nas-file-center-*.db"))
    assert len(initial_backups) == 1

    # Second init
    init_db(engine, db_path=db_path, backups_dir=backups_dir)
    second_backups = list(backups_dir.glob("nas-file-center-*.db"))
    assert len(second_backups) == 1, "Second init must NOT create duplicate backup"

    engine.dispose()


def test_concurrent_init_db_gate1(tmp_path: Path):
    """4 concurrent init_db calls on v0.3.3 baseline succeed without lock failures or duplicate backups."""
    db_path = tmp_path / "config" / "concurrent.db"
    backups_dir = tmp_path / "config" / "backups"
    _create_v033_baseline_db(db_path, audit_retention=90)

    def _worker(worker_idx: int):
        eng, _ = create_engine_and_session(db_path)
        init_db(
            eng,
            db_path=db_path,
            backups_dir=backups_dir,
            initial_admin_username="admin",
            initial_admin_password=f"Pass_{worker_idx}!",
        )
        eng.dispose()
        return True

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_worker, i) for i in range(4)]
        results = [f.result() for f in futures]

    assert all(results)

    # Verify single backup
    backup_files = list(backups_dir.glob("nas-file-center-*.db"))
    assert len(backup_files) == 1, f"Expected exactly 1 backup from concurrent init, got {len(backup_files)}"

    # Check DB integrity
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("PRAGMA integrity_check;")
    assert cur.fetchone()[0] == "ok"
    conn.close()
