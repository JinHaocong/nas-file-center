from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.models import (
    AuditEvent,
    BatchPlan,
    BatchPlanItem,
    DuplicateFile,
    DuplicateGroup,
    FavoritePath,
    OrganizerProfile,
    RecentPath,
    ScanJob,
    Session,
    User,
    WorkJob,
    WorkerState,
    TaskEvent,
)

LARGE_INODE = 12164156718799206349
LARGE_INODE_STR = f"u:{LARGE_INODE:x}"


def test_v032_full_database_lossless_migration(tmp_path: Path):
    db_path = tmp_path / "v032_production.db"
    backups_dir = tmp_path / "backups"

    # Create full v0.3.2 schema
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

        CREATE TABLE scan_jobs (
            id INTEGER PRIMARY KEY,
            name VARCHAR(255),
            mode VARCHAR(32),
            roots_json TEXT,
            status VARCHAR(32),
            fclones_args_json TEXT,
            started_at DATETIME,
            finished_at DATETIME,
            raw_report_path TEXT,
            total_groups INTEGER,
            total_files_in_groups INTEGER,
            reclaimable_bytes BIGINT,
            error_text TEXT,
            created_at DATETIME
        );
        INSERT INTO scan_jobs (id, name, mode, roots_json, status)
        VALUES (1, 'Scan1', 'normal', '["/data"]', 'completed');

        CREATE TABLE duplicate_groups (
            id INTEGER PRIMARY KEY,
            scan_job_id INTEGER,
            content_hash VARCHAR(256),
            file_size BIGINT,
            member_count INTEGER
        );
        INSERT INTO duplicate_groups (id, scan_job_id, content_hash, file_size, member_count)
        VALUES (1, 1, 'hash_abc', 1024, 2);

        CREATE TABLE duplicate_files (
            id INTEGER PRIMARY KEY,
            group_id INTEGER,
            root_id INTEGER,
            absolute_path TEXT,
            relative_path TEXT,
            top_level_dir TEXT,
            size BIGINT,
            mtime_ns BIGINT,
            device BIGINT,
            inode BIGINT,
            created_at DATETIME
        );
        INSERT INTO duplicate_files (id, group_id, root_id, absolute_path, relative_path, top_level_dir, size, mtime_ns, device, inode)
        VALUES (1, 1, 0, '/data/a.jpg', 'a.jpg', '/data', 1024, 1000, 1, '{LARGE_INODE_STR}');

        CREATE TABLE batch_plans (
            id INTEGER PRIMARY KEY,
            name VARCHAR(255),
            plan_type VARCHAR(64),
            status VARCHAR(32),
            root_paths_json TEXT,
            total_operations INTEGER,
            metadata_json TEXT,
            error_text TEXT,
            created_at DATETIME,
            frozen_at DATETIME
        );
        INSERT INTO batch_plans (id, name, plan_type, status, root_paths_json, total_operations)
        VALUES (1, 'Plan1', 'dedupe', 'frozen', '["/data"]', 1);

        CREATE TABLE batch_plan_items (
            id INTEGER PRIMARY KEY,
            plan_id INTEGER,
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
        INSERT INTO batch_plan_items (id, plan_id, sequence, operation, source_path, expected_inode, state)
        VALUES (1, 1, 1, 'delete', '/data/a.jpg', '{LARGE_INODE_STR}', 'planned');

        CREATE TABLE audit_events (
            id INTEGER PRIMARY KEY,
            timestamp DATETIME,
            operation VARCHAR(64),
            path TEXT,
            result VARCHAR(32),
            details_json TEXT
        );
        INSERT INTO audit_events (id, operation, path, result)
        VALUES (1, 'delete', '/data/a.jpg', 'success');

        CREATE TABLE organizer_profiles (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            name VARCHAR(128),
            description TEXT,
            rename_template TEXT,
            statistics_template TEXT,
            mtime_mode VARCHAR(32),
            mtime_delay_seconds FLOAT,
            cleanup_patterns_json TEXT,
            target_extensions_json TEXT,
            enable_natural_sort BOOLEAN,
            is_builtin BOOLEAN,
            created_at DATETIME,
            updated_at DATETIME
        );
        INSERT INTO organizer_profiles (id, user_id, name, is_builtin)
        VALUES (1, 1, 'Custom Profile', 0);

        CREATE TABLE favorite_paths (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            path TEXT,
            alias VARCHAR(128),
            created_at DATETIME
        );
        INSERT INTO favorite_paths (id, user_id, path)
        VALUES (1, 1, '/data');

        CREATE TABLE recent_paths (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            path TEXT,
            accessed_at DATETIME
        );
        INSERT INTO recent_paths (id, user_id, path)
        VALUES (1, 1, '/data');

        CREATE TABLE work_jobs (
            id INTEGER PRIMARY KEY,
            kind VARCHAR(64),
            status VARCHAR(32),
            progress_current BIGINT,
            progress_total BIGINT,
            state_json TEXT,
            error_text TEXT,
            created_at DATETIME,
            started_at DATETIME,
            finished_at DATETIME
        );
        INSERT INTO work_jobs (id, kind, status, progress_current, progress_total, state_json)
        VALUES (1, 'fclones-scan', 'completed', 10, 10, '{{"scan_job_id": 1}}');

        CREATE TABLE task_lock (
            id INTEGER PRIMARY KEY,
            locked BOOLEAN,
            owner VARCHAR(128),
            acquired_at DATETIME
        );
    """)
    conn.commit()
    conn.close()

    # Run v0.3.3 init_db migration
    engine = create_engine(f"sqlite:///{db_path}")
    init_db(
        engine,
        db_path=db_path,
        backups_dir=backups_dir,
    )

    # 1. Verify backup was created
    assert len(list(backups_dir.glob("*.db"))) >= 1

    # 2. Verify PRAGMA integrity_check
    with engine.connect() as c:
        res = c.execute(text("PRAGMA integrity_check")).scalar()
        assert res == "ok"

    # 3. Verify all existing counts and rows are intact
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        assert session.scalar(select(User.username).where(User.id == 1)) == "admin"
        assert session.scalar(select(ScanJob.name).where(ScanJob.id == 1)) == "Scan1"
        assert session.scalar(select(DuplicateGroup.content_hash).where(DuplicateGroup.id == 1)) == "hash_abc"

        # Large inode verification
        dup_file = session.get(DuplicateFile, 1)
        assert dup_file is not None
        assert dup_file.inode == LARGE_INODE

        plan_item = session.get(BatchPlanItem, 1)
        assert plan_item is not None
        assert plan_item.expected_inode == LARGE_INODE

        assert session.scalar(select(AuditEvent.operation).where(AuditEvent.id == 1)) == "delete"
        assert session.scalar(select(OrganizerProfile.name).where(OrganizerProfile.id == 1)) == "Custom Profile"
        assert session.scalar(select(FavoritePath.path).where(FavoritePath.id == 1)) == "/data"
        assert session.scalar(select(RecentPath.path).where(RecentPath.id == 1)) == "/data"

        # WorkJob upgraded with new columns
        job = session.get(WorkJob, 1)
        assert job is not None
        assert job.kind == "fclones-scan"
        assert job.status == "completed"
        assert job.pause_requested_at is None
        assert job.retry_of is None

        # New tables exist
        assert session.query(WorkerState).count() == 0
        assert session.query(TaskEvent).count() == 0


def test_retry_does_not_persist_mutation_authorization(tmp_path: Path):
    settings = Settings(config_dir=tmp_path, allow_mutation=False, allow_delete=False)
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(engine, db_path=settings.database_path)

    from app.tasks.service import TaskService
    srv = TaskService(SessionLocal)

    with SessionLocal() as session:
        # Create a failed job with payload attempting to store authorization
        job = WorkJob(
            kind="index-root",
            status="failed",
            state_json=json.dumps({"root": "/data", "allow_mutation": True}),
        )
        session.add(job)
        session.commit()
        old_id = job.id

    # Retry job
    retried = srv.retry_task(old_id)
    new_job_id = retried["job"]["id"]

    # Verify execution always reads current settings, not stale authorizations
    with SessionLocal() as session:
        new_job = session.get(WorkJob, new_job_id)
        assert new_job is not None
        assert new_job.status == "queued"
        assert new_job.retry_of == old_id

        # Payload must strip security authorizations:
        payload = json.loads(new_job.state_json or "{}")
        assert "allow_mutation" not in payload
        assert "allow_delete" not in payload
        assert payload.get("root") == "/data"

        # Settings still govern mutation permissions:
        assert settings.allow_mutation is False
        assert settings.allow_delete is False
