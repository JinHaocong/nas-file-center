from __future__ import annotations

from pathlib import Path
import sqlite3
from sqlalchemy import func, select

from app.db import create_engine_and_session, init_db
from app.models import FavoritePath, OrganizerProfile, RecentPath, ScanJob, User


def test_v032_step1_to_step2_migration_and_seed_idempotency(tmp_path: Path):
    db_path = tmp_path / "config" / "app.db"
    db_path.parent.mkdir(parents=True)
    backups_dir = tmp_path / "config" / "backups"

    # 1. Create a simulated v0.3.2-step1 database (has favorite_paths & recent_paths, but no organizer_profiles)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, role TEXT, is_active BOOLEAN, created_at DATETIME, updated_at DATETIME, last_login_at DATETIME);"
    )
    conn.execute(
        "INSERT INTO users (id, username, password_hash, role, is_active) VALUES (1, 'admin_v032', 'hash', 'admin', 1);"
    )
    conn.execute(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY, user_id INTEGER, token_hash TEXT UNIQUE, created_at DATETIME, expires_at DATETIME, last_seen_at DATETIME, ip_address TEXT, user_agent TEXT, revoked_at DATETIME);"
    )
    conn.execute(
        "CREATE TABLE favorite_paths (id INTEGER PRIMARY KEY, user_id INTEGER, path TEXT, label TEXT, position INTEGER, created_at DATETIME, updated_at DATETIME);"
    )
    conn.execute(
        "INSERT INTO favorite_paths (id, user_id, path, label, position) VALUES (1, 1, '/data/Photos', '我的相册', 0);"
    )
    conn.execute(
        "CREATE TABLE recent_paths (id INTEGER PRIMARY KEY, user_id INTEGER, path TEXT, last_used_at DATETIME);"
    )
    conn.execute(
        "INSERT INTO recent_paths (id, user_id, path) VALUES (1, 1, '/data/Videos');"
    )
    conn.commit()
    conn.close()

    # 2. Run init_db (migrating to v0.3.2-step2)
    engine, SessionLocal = create_engine_and_session(db_path)
    init_db(
        engine,
        db_path=db_path,
        backups_dir=backups_dir,
        initial_admin_username="admin_v032",
        initial_admin_password="password",
    )

    # 3. Verify backup was created
    backups = list(backups_dir.glob("nas-file-center-*.db"))
    assert len(backups) >= 1

    # 4. Verify previous data preserved
    with SessionLocal() as session:
        user = session.get(User, 1)
        assert user is not None and user.username == "admin_v032"

        fav = session.get(FavoritePath, 1)
        assert fav is not None and fav.path == "/data/Photos"

        rec = session.get(RecentPath, 1)
        assert rec is not None and rec.path == "/data/Videos"

        # 5. Verify no builtin profile is seeded (default profiles count is 0)
        total_profiles = session.scalar(select(func.count()).select_from(OrganizerProfile))
        assert total_profiles == 0

    # 6. Run init_db a second time (simulating container restart)
    init_db(
        engine,
        db_path=db_path,
        backups_dir=backups_dir,
        initial_admin_username="admin_v032",
        initial_admin_password="password",
    )

    # Verify still 0 profiles
    with SessionLocal() as session:
        total_profiles = session.scalar(select(func.count()).select_from(OrganizerProfile))
        assert total_profiles == 0
