from pathlib import Path
import pytest
from sqlalchemy import inspect, select, text
from app.db import init_db, create_engine_and_session
from app.models import ResourcePolicy

def test_init_db_creates_resource_policy_singleton(tmp_path: Path):
    db_file = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_file)
    init_db(engine, db_path=db_file)

    inspector = inspect(engine)
    assert "resource_policy" in inspector.get_table_names()

    with SessionLocal() as session:
        policy = session.get(ResourcePolicy, 1)
        assert policy is not None
        assert policy.id == 1
        assert policy.scan_threads == 2
        assert policy.hash_threads == 2
        assert policy.io_limit == "normal"
        assert policy.job_priority == "normal"
        assert policy.active_window_enabled is False
        assert policy.active_window_start is None
        assert policy.active_window_end is None
        assert policy.active_window_timezone is None
        assert policy.outside_window_mode == "limited"
        assert policy.revision == 1

def test_init_db_idempotency_preserves_custom_policy(tmp_path: Path):
    db_file = tmp_path / "test.db"
    engine, SessionLocal = create_engine_and_session(db_file)
    init_db(engine, db_path=db_file)

    with SessionLocal() as session:
        policy = session.get(ResourcePolicy, 1)
        policy.scan_threads = 4
        policy.revision = 2
        session.commit()

    # Re-run init_db
    init_db(engine, db_path=db_file)

    with SessionLocal() as session:
        policy = session.get(ResourcePolicy, 1)
        assert policy.scan_threads == 4
        assert policy.revision == 2

def test_existing_db_upgrade_triggers_backup_before_creating_table(tmp_path: Path):
    db_file = tmp_path / "legacy.db"
    backups_dir = tmp_path / "backups"
    engine, SessionLocal = create_engine_and_session(db_file)
    # Simulate existing DB with only users and work_jobs
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)"))
        conn.execute(text("INSERT INTO users VALUES (1, 'admin')"))
        conn.commit()

    init_db(engine, db_path=db_file, backups_dir=backups_dir)

    backup_files = list(backups_dir.glob("nas-file-center-*.db"))
    assert len(backup_files) >= 1
    inspector = inspect(engine)
    assert "resource_policy" in inspector.get_table_names()
