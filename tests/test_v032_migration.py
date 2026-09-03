from __future__ import annotations

from pathlib import Path
import sqlite3

from app.db import create_engine_and_session, init_db


def test_v031_to_v032_lossless_migration_and_backup(tmp_path: Path):
    db_path = tmp_path / "config" / "app.db"
    db_path.parent.mkdir(parents=True)
    backups_dir = tmp_path / "config" / "backups"

    # 1. Create a simulated v0.3.1 database with pre-existing v0.3.1 tables and data
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, role TEXT, is_active BOOLEAN, created_at DATETIME, updated_at DATETIME, last_login_at DATETIME);"
    )
    conn.execute(
        "INSERT INTO users (id, username, password_hash, role, is_active) VALUES (1, 'nas_admin', 'argon2id_hash', 'admin', 1);"
    )
    conn.execute(
        "CREATE TABLE scan_jobs (id INTEGER PRIMARY KEY, name TEXT, mode TEXT, roots_json TEXT, status TEXT, total_groups INTEGER, total_files_in_groups INTEGER, reclaimable_bytes INTEGER, raw_report_path TEXT, error_text TEXT, fclones_args_json TEXT, created_at DATETIME, started_at DATETIME, finished_at DATETIME);"
    )
    conn.execute(
        "INSERT INTO scan_jobs (id, name, mode, roots_json, status, total_groups, total_files_in_groups, reclaimable_bytes, created_at) VALUES (1, 'v0.3.1 Scan', 'normal', '[\"/data\"]', 'completed', 5, 10, 524288, '2026-09-01 00:00:00');"
    )
    conn.commit()
    conn.close()

    # 2. Run v0.3.2-step1 init_db
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(
        engine,
        db_path=db_path,
        backups_dir=backups_dir,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )

    # 3. Verify backup was created before schema migration
    backups = list(backups_dir.glob("nas-file-center-*.db"))
    assert len(backups) >= 1
    # Verify backup contains the pre-migration tables
    b_conn = sqlite3.connect(str(backups[0]))
    b_cursor = b_conn.cursor()
    b_cursor.execute("SELECT name FROM scan_jobs WHERE id=1")
    assert b_cursor.fetchone()[0] == "v0.3.1 Scan"
    b_conn.close()

    # 4. Verify v0.3.1 data preserved
    with SessionLocal() as session:
        from app.models import User, ScanJob, FavoritePath, RecentPath
        user = session.get(User, 1)
        assert user is not None
        assert user.username == "nas_admin"

        scan = session.get(ScanJob, 1)
        assert scan is not None
        assert scan.name == "v0.3.1 Scan"

        # 5. Verify new v0.3.2 tables are queryable and functional
        fav = FavoritePath(user_id=1, path="/data/FavoriteFolder", label="我的收藏")
        rec = RecentPath(user_id=1, path="/data/RecentFolder")
        session.add_all([fav, rec])
        session.commit()

        assert session.get(FavoritePath, fav.id) is not None
        assert session.get(RecentPath, rec.id) is not None

    engine.dispose()


def test_partial_migration_when_favorite_exists_but_recent_missing(tmp_path: Path):
    db_path = tmp_path / "config" / "partial_app.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    backups_dir = tmp_path / "config" / "partial_backups"

    # Simulate database where users and favorite_paths exist, but recent_paths is missing
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, role TEXT, is_active BOOLEAN, created_at DATETIME, updated_at DATETIME, last_login_at DATETIME);"
    )
    conn.execute(
        "INSERT INTO users (id, username, password_hash, role, is_active) VALUES (1, 'nas_admin', 'argon2id_hash', 'admin', 1);"
    )
    conn.execute(
        "CREATE TABLE favorite_paths (id INTEGER PRIMARY KEY, user_id INTEGER, path TEXT, label TEXT, position INTEGER, created_at DATETIME, updated_at DATETIME);"
    )
    conn.execute(
        "INSERT INTO favorite_paths (id, user_id, path, label) VALUES (1, 1, '/data/Photos', '相册');"
    )
    conn.commit()
    conn.close()

    # Run init_db
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(
        engine,
        db_path=db_path,
        backups_dir=backups_dir,
    )

    # 1. Verify backup was created because recent_paths was missing
    backups = list(backups_dir.glob("nas-file-center-*.db"))
    assert len(backups) >= 1

    # 2. Verify recent_paths is now created and usable
    with SessionLocal() as session:
        from app.models import FavoritePath, RecentPath
        fav = session.get(FavoritePath, 1)
        assert fav is not None
        assert fav.label == "相册"

        rec = RecentPath(user_id=1, path="/data/RecentDocs")
        session.add(rec)
        session.commit()
        assert session.get(RecentPath, rec.id) is not None

    engine.dispose()
