from __future__ import annotations

from pathlib import Path
import sqlite3
import pytest
from sqlalchemy import create_engine, inspect, select, text

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import Base, ScanJob, User, Session as UserSession
from app.service import FileCenterService
from app.worker import recover_running_jobs


def _create_legacy_v02_database(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE scan_jobs (
            id INTEGER PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            mode VARCHAR(32) NOT NULL,
            roots_json TEXT NOT NULL,
            status VARCHAR(32) NOT NULL,
            fclones_args_json TEXT,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            raw_report_path TEXT,
            total_groups INTEGER,
            total_files_in_groups INTEGER,
            reclaimable_bytes BIGINT,
            error_text TEXT,
            created_at TIMESTAMP
        );
    """)
    cursor.execute("""
        INSERT INTO scan_jobs (id, name, mode, roots_json, status, total_groups, total_files_in_groups, reclaimable_bytes, created_at)
        VALUES (1, 'Legacy Scan', 'normal', '["/data/test"]', 'completed', 5, 10, 1048576, '2026-09-01 12:00:00')
    """)
    conn.commit()
    conn.close()


def test_migration_and_backup_from_v02_service(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    db_path = config_dir / "app.db"

    # 1. Create a simulated v0.2 database WITHOUT users or sessions table
    _create_legacy_v02_database(db_path)

    # 2. Run FileCenterService on the legacy DB
    settings = Settings(
        config_dir=config_dir,
        data_mount=tmp_path / "data",
        allowed_roots_raw=str(tmp_path / "data"),
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)

    # 3. Verify backup was created in /config/backups/
    backups = list(settings.backups_dir.glob("*.db"))
    assert len(backups) >= 1
    assert backups[0].name.startswith("nas-file-center-")

    # 4. Verify existing v0.2 data is preserved
    scans = service.list_scans()
    assert scans["total"] == 1
    assert scans["items"][0]["name"] == "Legacy Scan"
    assert scans["items"][0]["total_groups"] == 5

    # 5. Verify new tables exist and initial admin was created
    with service.SessionLocal() as db_session:
        inspector = inspect(service.engine)
        assert "users" in inspector.get_table_names()
        assert "sessions" in inspector.get_table_names()

        users = list(db_session.scalars(select(User)))
        assert len(users) == 1
        assert users[0].username == "admin"


def test_worker_first_migration_creates_backup_before_schema_mutation(tmp_path: Path):
    config_dir = tmp_path / "config_worker"
    config_dir.mkdir(parents=True)
    db_path = config_dir / "app.db"

    # 1. Create a simulated v0.2 database WITHOUT users or sessions table
    _create_legacy_v02_database(db_path)

    settings = Settings(
        config_dir=config_dir,
        data_mount=tmp_path / "data",
        allowed_roots_raw=str(tmp_path / "data"),
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )

    # 2. Simulate Worker starting BEFORE the API container
    # Worker runs recover_running_jobs which calls init_db(engine)
    recover_running_jobs(settings)

    # 3. Verify backup was created by the worker before creating users/sessions
    backups = list(settings.backups_dir.glob("*.db"))
    assert len(backups) >= 1
    assert backups[0].name.startswith("nas-file-center-")

    # 4. Verify the backup database contains the pristine v0.2 schema (no users table)
    backup_conn = sqlite3.connect(str(backups[0]))
    backup_tables = [r[0] for r in backup_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    backup_conn.close()
    assert "scan_jobs" in backup_tables
    assert "users" not in backup_tables

    # 5. Verify current active database was updated with v0.3.1 schema
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    inspector = inspect(engine)
    assert "users" in inspector.get_table_names()
    assert "sessions" in inspector.get_table_names()
