from __future__ import annotations

import concurrent.futures
from pathlib import Path
import sqlite3

from app.db import create_engine_and_session, init_db


def _run_init(db_path: Path, backups_dir: Path, admin_pass: str):
    engine, _ = create_engine_and_session(db_path)
    init_db(
        engine,
        db_path=db_path,
        backups_dir=backups_dir,
        initial_admin_username="admin",
        initial_admin_password=admin_pass,
    )
    engine.dispose()
    return True


def test_concurrent_api_and_worker_db_init_on_legacy_v02(tmp_path: Path):
    db_path = tmp_path / "config" / "app.db"
    db_path.parent.mkdir(parents=True)
    backups_dir = tmp_path / "config" / "backups"

    # 1. Create a simulated v0.2 legacy database with pre-existing tables & data
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE scan_jobs (id INTEGER PRIMARY KEY, name TEXT, mode TEXT, roots_json TEXT, status TEXT, total_groups INTEGER, total_files_in_groups INTEGER, reclaimable_bytes INTEGER, raw_report_path TEXT, error_text TEXT, fclones_args_json TEXT, created_at DATETIME, started_at DATETIME, finished_at DATETIME);")
    conn.execute("INSERT INTO scan_jobs (id, name, mode, roots_json, status, total_groups, total_files_in_groups, reclaimable_bytes, created_at) VALUES (1, 'Legacy Scan', 'normal', '[\"/data\"]', 'completed', 10, 20, 1048576, '2026-01-01 00:00:00');")
    conn.execute("CREATE TABLE indexed_paths (id INTEGER PRIMARY KEY, root_key TEXT, absolute_path TEXT UNIQUE, relative_path TEXT, basename TEXT, stem TEXT, suffix TEXT, size INTEGER, mtime_ns INTEGER, device INTEGER, inode INTEGER, is_dir BOOLEAN, first_seen_at DATETIME, last_seen_at DATETIME, scan_generation INTEGER);")
    conn.execute("INSERT INTO indexed_paths (id, root_key, absolute_path, relative_path, basename, size, is_dir, first_seen_at, last_seen_at, scan_generation) VALUES (1, 'root-0', '/data/file.txt', 'file.txt', 'file.txt', 100, 0, '2026-01-01 00:00:00', '2026-01-01 00:00:00', 1);")
    conn.commit()
    conn.close()

    # 2. Run concurrent init_db calls simultaneously (simulating API and Worker race condition)
    num_workers = 8
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(_run_init, db_path, backups_dir, f"AdminPass_{i}!")
            for i in range(num_workers)
        ]
        results = [f.result() for f in futures]

    assert all(results)

    # 3. Verify schema is valid & users table created
    engine, SessionLocal = create_engine_and_session(db_path)
    with SessionLocal() as session:
        from app.models import ScanJob, IndexedPath, User
        # Legacy data preserved
        scan = session.get(ScanJob, 1)
        assert scan is not None
        assert scan.name == "Legacy Scan"

        idx = session.get(IndexedPath, 1)
        assert idx is not None
        assert idx.basename == "file.txt"

        # Users table created and exactly 1 admin exists
        users = list(session.query(User).all())
        assert len(users) == 1
        assert users[0].username == "admin"

    # 4. Verify backup was created
    backups = list(backups_dir.glob("nas-file-center-*.db"))
    assert len(backups) >= 1
    # Verify backup contains the legacy tables
    b_conn = sqlite3.connect(str(backups[0]))
    b_cursor = b_conn.cursor()
    b_cursor.execute("SELECT name FROM scan_jobs WHERE id=1")
    assert b_cursor.fetchone()[0] == "Legacy Scan"
    b_conn.close()
